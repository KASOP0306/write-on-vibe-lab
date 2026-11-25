"""RAG 정량 평가 러너 (Unit 6: 느낌 대신 숫자 — Retrieval 비교 · LLM-as-a-Judge 6지표 · Bedrock BYOI JSONL).

사용 예:
  # 1. 검색 설정별(Baseline unchunked vs Chunked/Hybrid/MMR/Rewrite/HyDE) 비교
  python -m eval.run_eval --mode retrieval

  # 2. LLM-as-a-Judge (Nova Lite 생성 → Nova Pro 6지표 채점) + BYOI JSONL 내보내기
  python -m eval.run_eval --mode judge --config baseline_unchunked_basic --export-byoi /tmp/byoi_baseline.jsonl
  python -m eval.run_eval --mode judge --config chunked_hybrid_mmr --export-byoi /tmp/byoi_upgraded.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import delete

from app.core.bedrock import (
    ainvoke_structured,
    ainvoke_tracked,
    get_fast_llm,
    get_smart_llm,
    llm_telemetry_scope,
)
from app.core.database import VectorDocument, close_db, get_session_factory, init_db
from app.core.vector_store import (
    DocType,
    SearchStrategy,
    format_hits_with_citations,
    search_documents,
    upsert_document,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).resolve().parent / "golden_dataset.json"
EVAL_CORPUS_TAG = "golden_v1_eval"


@dataclass(frozen=True)
class EvalConfig:
    name: str
    chunk: bool
    strategy: SearchStrategy
    top_k: int = 3
    max_distance: float | None = None
    use_mmr: bool = False


EVAL_CONFIGS: dict[str, EvalConfig] = {
    "baseline_unchunked_basic": EvalConfig(
        name="baseline_unchunked_basic",
        chunk=False,
        strategy="basic",
        top_k=3,
        max_distance=None,
        use_mmr=False,
    ),
    "chunked_basic": EvalConfig(
        name="chunked_basic",
        chunk=True,
        strategy="basic",
        top_k=3,
        max_distance=None,
        use_mmr=False,
    ),
    "chunked_threshold": EvalConfig(
        name="chunked_threshold",
        chunk=True,
        strategy="basic",
        top_k=3,
        max_distance=0.72,
        use_mmr=False,
    ),
    "chunked_hybrid": EvalConfig(
        name="chunked_hybrid",
        chunk=True,
        strategy="hybrid",
        top_k=3,
        max_distance=0.74,
        use_mmr=False,
    ),
    "chunked_hybrid_mmr": EvalConfig(
        name="chunked_hybrid_mmr",
        chunk=True,
        strategy="hybrid",
        top_k=3,
        max_distance=0.74,
        use_mmr=True,
    ),
    "chunked_rewrite": EvalConfig(
        name="chunked_rewrite",
        chunk=True,
        strategy="rewrite",
        top_k=3,
        max_distance=0.76,
        use_mmr=False,
    ),
    "chunked_hyde": EvalConfig(
        name="chunked_hyde",
        chunk=True,
        strategy="hyde",
        top_k=3,
        max_distance=0.80,
        use_mmr=False,
    ),
}


class RagJudgeScoresSchema(BaseModel):
    context_relevance: float = Field(ge=0.0, le=1.0, description="검색 조각이 질문과 얼마나 관련 있는지 (0~1)")
    context_coverage: float = Field(ge=0.0, le=1.0, description="정답에 필요한 정보가 검색 조각에 다 들어 있는지 (0~1)")
    correctness: float = Field(ge=0.0, le=1.0, description="답변이 정답과 일치하며 틀린 내용이 없는지 (0~1)")
    completeness: float = Field(ge=0.0, le=1.0, description="질문이 묻는 핵심 요소를 빠짐없이 답했는지 (0~1)")
    faithfulness: float = Field(ge=0.0, le=1.0, description="답변의 모든 주장이 검색 조각에 근거했는지 (지어내지 않았는지, 0~1)")
    helpfulness: float = Field(ge=0.0, le=1.0, description="답변의 형식·명확성·실용성 (0~1)")
    reason: str = Field(description="점수를 매긴 핵심 근거 1~2문장")


def build_byoi_jsonl_line(
    *,
    question: str,
    reference_answer: str,
    generated_answer: str,
    passages: list[dict[str, str]],
    model_identifier: str,
    kb_identifier: str,
) -> dict[str, Any]:
    """Amazon Bedrock Evaluations Bring Your Own Inference(BYOI) JSONL 1줄 포맷 (Unit 6 [s9])."""
    return {
        "conversationTurns": [
            {
                "prompt": {"content": [{"text": question}]},
                "referenceResponses": [{"content": [{"text": reference_answer}]}],
                "output": {
                    "text": generated_answer,
                    "modelIdentifier": model_identifier,
                    "knowledgeBaseIdentifier": kb_identifier,
                    "retrievedPassages": {
                        "retrievalResults": [
                            {
                                "name": p["name"],
                                "content": {"text": p["text"]},
                            }
                            for p in passages
                        ]
                    },
                },
            }
        ]
    }


def load_golden_dataset(path: Path = DATASET_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def _cleanup_eval_rows() -> None:
    async with get_session_factory()() as session:
        stmt = delete(VectorDocument).where(
            VectorDocument.doc_metadata.contains({"eval_corpus": EVAL_CORPUS_TAG})
        )
        await session.execute(stmt)
        await session.commit()


async def _seed_eval_corpus(corpus: list[dict[str, Any]], *, chunk: bool) -> int:
    await _cleanup_eval_rows()
    inserted_docs = 0
    async with get_session_factory()() as session:
        for item in corpus:
            meta = {**dict(item.get("metadata") or {}), "eval_corpus": EVAL_CORPUS_TAG}
            await upsert_document(
                session,
                doc_type=DocType(item["doc_type"]),
                ref_id=item["ref_id"],
                content=item["content"],
                metadata=meta,
                chunk=chunk,
            )
            inserted_docs += 1
    return inserted_docs


async def evaluate_retrieval_config(
    dataset: dict[str, Any],
    cfg: EvalConfig,
) -> dict[str, Any]:
    """단일 검색 설정에 대해 Hit@K, Keyword Hit@K, MRR, Out-of-Scope 차단률을 측정한다."""
    await _seed_eval_corpus(dataset["corpus"], chunk=cfg.chunk)
    questions = dataset["questions"]

    in_scope_total = 0
    parent_hits = 0
    keyword_hits = 0
    mrr_sum = 0.0
    oos_total = 0
    oos_clean_rejects = 0
    per_question: list[dict[str, Any]] = []

    async with get_session_factory()() as session:
        for q in questions:
            hits = await search_documents(
                session,
                query=q["question"],
                doc_types=[DocType(dt) for dt in q["doc_types"]],
                top_k=cfg.top_k,
                metadata_filter={"eval_corpus": EVAL_CORPUS_TAG},
                strategy=cfg.strategy,
                max_distance=cfg.max_distance,
                use_mmr=cfg.use_mmr,
            )
            expected_parent = q.get("expected_parent_ref_id")
            expected_kws = q.get("expected_keywords") or []

            if expected_parent is None:
                oos_total += 1
                clean_reject = len(hits) == 0 or (hits[0].distance > 0.72)
                if clean_reject:
                    oos_clean_rejects += 1
                per_question.append(
                    {
                        "id": q["id"],
                        "category": q["category"],
                        "hit": clean_reject,
                        "keyword_hit": clean_reject,
                        "hit_count": len(hits),
                        "top_distance": round(hits[0].distance, 4) if hits else None,
                    }
                )
                continue

            in_scope_total += 1
            rank_found = 0
            kw_found = False
            for rank, h in enumerate(hits, start=1):
                parent_id = str(h.metadata.get("parent_ref_id") or h.ref_id.split("::c")[0])
                if parent_id == expected_parent and rank_found == 0:
                    rank_found = rank
                if expected_kws and any(kw.lower() in h.content.lower() for kw in expected_kws):
                    kw_found = True

            if rank_found > 0:
                parent_hits += 1
                mrr_sum += 1.0 / rank_found
            if kw_found:
                keyword_hits += 1

            per_question.append(
                {
                    "id": q["id"],
                    "category": q["category"],
                    "hit": rank_found > 0,
                    "keyword_hit": kw_found,
                    "rank": rank_found,
                    "top_distance": round(hits[0].distance, 4) if hits else None,
                    "top_ref": hits[0].ref_id if hits else None,
                }
            )

    return {
        "config": cfg.name,
        "chunk": cfg.chunk,
        "strategy": cfg.strategy,
        "top_k": cfg.top_k,
        "max_distance": cfg.max_distance,
        "use_mmr": cfg.use_mmr,
        "parent_hit_at_k": round(parent_hits / max(1, in_scope_total), 4),
        "keyword_hit_at_k": round(keyword_hits / max(1, in_scope_total), 4),
        "mrr": round(mrr_sum / max(1, in_scope_total), 4),
        "oos_clean_rate": round(oos_clean_rejects / max(1, oos_total), 4),
        "details": per_question,
    }


async def evaluate_end_to_end_judge(
    dataset: dict[str, Any],
    cfg: EvalConfig,
    *,
    export_byoi_path: str | None = None,
) -> dict[str, Any]:
    """Nova Lite로 RAG 답을 생성하고, 별도 채점 모델(Nova Pro)로 6대 지표를 채점한다 (Unit 6)."""
    await _seed_eval_corpus(dataset["corpus"], chunk=cfg.chunk)
    gen_llm = get_fast_llm(temperature=0.1, max_tokens=600)
    judge_llm = get_smart_llm(temperature=0.0, max_tokens=800)

    byoi_lines: list[str] = []
    rows: list[dict[str, Any]] = []

    with llm_telemetry_scope(f"eval_judge:{cfg.name}") as telemetry:
        async with get_session_factory()() as session:
            for q in dataset["questions"]:
                hits = await search_documents(
                    session,
                    query=q["question"],
                    doc_types=[DocType(dt) for dt in q["doc_types"]],
                    top_k=cfg.top_k,
                    metadata_filter={"eval_corpus": EVAL_CORPUS_TAG},
                    strategy=cfg.strategy,
                    max_distance=cfg.max_distance,
                    use_mmr=cfg.use_mmr,
                )
                context_block = format_hits_with_citations(hits, max_chars_per_hit=650)

                if not hits:
                    gen_answer = "등록된 포트폴리오에서 확인할 수 없습니다."
                else:
                    gen_msg = await ainvoke_tracked(
                        gen_llm,
                        [
                            SystemMessage(
                                content=(
                                    "당신은 지원자 포트폴리오 질의응답 어시스턴트입니다. "
                                    "반드시 <context> 안에 명시된 사실과 수치만 근거로 간결하게 답하세요. "
                                    "<context>에 질문의 답이 없으면 추측하지 말고 정확히 "
                                    "'등록된 포트폴리오에서 확인할 수 없습니다.'라고 답하세요."
                                )
                            ),
                            HumanMessage(
                                content=f"<context>\n{context_block}\n</context>\n\n질문: {q['question']}"
                            ),
                        ],
                        caller=f"eval_gen:{q['id']}",
                    )
                    gen_answer = (
                        gen_msg.content
                        if isinstance(gen_msg.content, str)
                        else str(gen_msg.content)
                    ).strip()

                passages = [
                    {
                        "name": h.source_label or h.ref_id,
                        "text": h.content,
                    }
                    for h in hits
                ]
                byoi_lines.append(
                    json.dumps(
                        build_byoi_jsonl_line(
                            question=q["question"],
                            reference_answer=q["reference_answer"],
                            generated_answer=gen_answer,
                            passages=passages,
                            model_identifier="amazon.nova-lite-v1:0",
                            kb_identifier=f"write-on-vibe-lab-{cfg.name}",
                        ),
                        ensure_ascii=False,
                    )
                )

                # LLM-as-a-Judge (별도 모델 Nova Pro 채점)
                judge_res = await ainvoke_structured(
                    judge_llm,
                    RagJudgeScoresSchema,
                    [
                        SystemMessage(
                            content=(
                                "당신은 엄격한 RAG 품질 평가자(LLM-as-a-Judge)입니다. "
                                "질문, 사람이 쓴 정답(reference), RAG가 검색한 조각(context), RAG의 실제 답변을 비교해 "
                                "6개 지표를 0.0~1.0 사이 숫자로 공정하게 채점하세요. "
                                "정답이 '등록된 포트폴리오에서 확인할 수 없습니다.'인 거절 문항에서 RAG가 올바르게 거절했다면 "
                                "correctness=1.0, completeness=1.0, faithfulness=1.0으로 채점하세요."
                            )
                        ),
                        HumanMessage(
                            content=(
                                f"[질문] {q['question']}\n"
                                f"[사람이 쓴 정답] {q['reference_answer']}\n\n"
                                f"[검색한 조각]\n{context_block}\n\n"
                                f"[RAG 실제 답변]\n{gen_answer}"
                            )
                        ),
                    ],
                    max_retries=1,
                    caller=f"eval_judge:{q['id']}",
                )
                rows.append(
                    {
                        "id": q["id"],
                        "category": q["category"],
                        "question": q["question"],
                        "answer": gen_answer,
                        "hit_count": len(hits),
                        **judge_res.model_dump(),
                    }
                )

    if export_byoi_path:
        Path(export_byoi_path).write_text("\n".join(byoi_lines) + "\n", encoding="utf-8")
        logger.info("Exported Bedrock BYOI JSONL to %s (%d lines)", export_byoi_path, len(byoi_lines))

    metric_names = (
        "context_relevance",
        "context_coverage",
        "correctness",
        "completeness",
        "faithfulness",
        "helpfulness",
    )
    averages = {
        m: round(sum(r[m] for r in rows) / max(1, len(rows)), 4)
        for m in metric_names
    }
    lowest = sorted(rows, key=lambda r: (r["correctness"], r["completeness"]))[:3]

    return {
        "config": cfg.name,
        "averages": averages,
        "lowest_questions": [
            {
                "id": r["id"],
                "category": r["category"],
                "correctness": r["correctness"],
                "completeness": r["completeness"],
                "faithfulness": r["faithfulness"],
                "reason": r["reason"],
            }
            for r in lowest
        ],
        "telemetry": telemetry.summary(),
        "rows": rows,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Write-on-Vibe-Lab RAG Quantitative Evaluator")
    parser.add_argument("--mode", choices=["retrieval", "judge"], default="retrieval")
    parser.add_argument(
        "--configs",
        nargs="+",
        default=None,
        help="평가할 설정 이름 목록 (기본: retrieval은 전체, judge는 baseline + chunked_hybrid_mmr)",
    )
    parser.add_argument("--export-byoi", default=None, help="BYOI JSONL 저장 경로 (단일 config judge 시)")
    parser.add_argument("--output-json", default=None, help="전체 결과 JSON 저장 경로")
    args = parser.parse_args()

    await init_db()
    dataset = load_golden_dataset()
    results: list[dict[str, Any]] = []

    try:
        if args.mode == "retrieval":
            target_names = args.configs or list(EVAL_CONFIGS.keys())
            for name in target_names:
                cfg = EVAL_CONFIGS[name]
                res = await evaluate_retrieval_config(dataset, cfg)
                results.append(res)
                print(
                    f"[{res['config']:26s}] ParentHit@3={res['parent_hit_at_k']:.3f} | "
                    f"KwHit@3={res['keyword_hit_at_k']:.3f} | MRR={res['mrr']:.3f} | "
                    f"OOS_Clean={res['oos_clean_rate']:.3f}"
                )
        else:
            target_names = args.configs or ["baseline_unchunked_basic", "chunked_hybrid_mmr"]
            for idx, name in enumerate(target_names):
                cfg = EVAL_CONFIGS[name]
                byoi_out = args.export_byoi if (args.export_byoi and len(target_names) == 1) else None
                if args.export_byoi and len(target_names) > 1:
                    p = Path(args.export_byoi)
                    byoi_out = str(p.with_name(f"{p.stem}_{name}{p.suffix}"))
                res = await evaluate_end_to_end_judge(dataset, cfg, export_byoi_path=byoi_out)
                results.append(res)
                avg = res["averages"]
                print(
                    f"[{name:26s}] Rel={avg['context_relevance']:.3f} Cov={avg['context_coverage']:.3f} "
                    f"Corr={avg['correctness']:.3f} Comp={avg['completeness']:.3f} "
                    f"Faith={avg['faithfulness']:.3f} Help={avg['helpfulness']:.3f}"
                )
    finally:
        await _cleanup_eval_rows()
        await close_db()

    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(main())
