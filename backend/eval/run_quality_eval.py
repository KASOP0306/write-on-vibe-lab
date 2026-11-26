"""질문 퀄리티 루프(루프 A) & 프로젝트 정리·요약 루프(루프 B) 정량 평가 러너.

사용 예:
  # 1. 질문 퀄리티 Baseline vs Quality Loop(max 2) 비교
  python -m eval.run_quality_eval --mode question

  # 2. 프로젝트 정리·요약 Baseline vs Quality Loop(max 2) 비교
  python -m eval.run_quality_eval --mode summary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_smart_llm, llm_telemetry_scope
from app.core.question_critic import (
    code_lint_questions,
    critique_and_refine_questions,
)
from app.core.star_rubric import evaluate_star_experience_rubric
from app.core.summary_verifier import (
    compute_cross_section_overlap,
    detect_unverified_metrics,
)
from app.graphs.interview_graph import extract_star, generate_questions
from app.tools.portfolio_manager import analyze_document_to_portfolio

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).resolve().parent
QUESTION_DATASET_PATH = EVAL_DIR / "question_golden_dataset.json"
SUMMARY_DATASET_PATH = EVAL_DIR / "summary_golden_dataset.json"


class QuestionJudgeSchema(BaseModel):
    specificity: float = Field(ge=0.0, le=1.0, description="모호한 일반론이 아니라 메모 속 빈틈을 날카롭게 찌르는지")
    answerability: float = Field(ge=0.0, le=1.0, description="질문이 간결하고 1개 핵심만 물어 답변하기 쉬운지")
    non_redundancy: float = Field(ge=0.0, le=1.0, description="이미 메모에 나온 사실을 반복해서 묻지 않는지")
    axis_alignment: float = Field(ge=0.0, le=1.0, description="가장 약한 STAR-L 축을 정확히 겨냥했는지")
    reason: str = Field(description="채점 근거 1~2문장")


class SummaryJudgeSchema(BaseModel):
    faithfulness: float = Field(ge=0.0, le=1.0, description="원문에 없는 수치·기술·성과를 지어내지 않았는지")
    coverage: float = Field(ge=0.0, le=1.0, description="원문의 핵심 기술 결정·수치·트러블슈팅을 빠뜨리지 않았는지")
    signal_density: float = Field(ge=0.0, le=1.0, description="섹션 간 중복과 추상적 미사여구 없이 정보 밀도가 높은지")
    track_fit: float = Field(ge=0.0, le=1.0, description="선택된 프로젝트 트랙 성격에 맞게 섹션이 적절히 배치되었는지")
    reason: str = Field(description="채점 근거 1~2문장")


def load_question_golden_dataset(path: Path = QUESTION_DATASET_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_summary_golden_dataset(path: Path = SUMMARY_DATASET_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def evaluate_questions(*, enable_loop: bool) -> dict[str, Any]:
    """루프 A: Baseline(enable_loop=False) vs Critic-Refiner(enable_loop=True, max 2) 비교."""
    dataset = load_question_golden_dataset()
    judge_llm = get_smart_llm(temperature=0.0, max_tokens=700)
    rows: list[dict[str, Any]] = []

    with llm_telemetry_scope(f"eval_question:loop={enable_loop}") as telemetry:
        for case in dataset["cases"]:
            state: dict[str, Any] = {
                "raw_notes": case["raw_notes"],
                "qa_history": [],
                "enable_question_critic": enable_loop,
            }
            ext = await extract_star(state)
            state.update(ext)
            grade = await evaluate_star_experience_rubric(
                state["star"], context_text=case["raw_notes"]
            )
            state.update(grade)
            q_out = await generate_questions(state)
            qs = q_out.get("structured_questions") or []
            lint_issues = code_lint_questions(
                qs,
                prev_questions=[],
                known_text=case["raw_notes"],
            )

            judge = await ainvoke_structured(
                judge_llm,
                QuestionJudgeSchema,
                [
                    SystemMessage(
                        content=(
                            "당신은 채용 면접 질문 품질 평가자입니다. "
                            "지원자 원문 메모, 이미 알려진 사실, 기대 보강 포인트를 보고 생성된 역질문의 품질을 0~1로 엄격 채점하세요."
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"[원문 메모]\n{case['raw_notes']}\n"
                            f"[이미 알려진 사실 (다시 물으면 감점)]\n{case['already_known_facts']}\n"
                            f"[기대 보강 축]\n{case['expected_weak_axes']} — {case['ideal_probe_focus']}\n\n"
                            f"[생성된 역질문]\n{json.dumps(qs, ensure_ascii=False, indent=2)}"
                        )
                    ),
                ],
                max_retries=1,
                caller=f"eval_q_judge:{case['id']}",
            )
            rows.append(
                {
                    "id": case["id"],
                    "lint_issue_count": len(lint_issues),
                    "critic_revisions": q_out.get("question_critic_revisions", 0),
                    **judge.model_dump(),
                }
            )

    metrics = ("specificity", "answerability", "non_redundancy", "axis_alignment")
    averages = {m: round(sum(r[m] for r in rows) / max(1, len(rows)), 4) for m in metrics}
    return {
        "mode": "question",
        "enable_loop": enable_loop,
        "averages": averages,
        "total_lint_issues": sum(r["lint_issue_count"] for r in rows),
        "telemetry": telemetry.summary(),
        "rows": rows,
    }


async def evaluate_summaries(*, enable_loop: bool) -> dict[str, Any]:
    """루프 B: Baseline(enable_loop=False) vs EvidenceMap+3AxisVerifier(enable_loop=True, max 2) 비교."""
    dataset = load_summary_golden_dataset()
    judge_llm = get_smart_llm(temperature=0.0, max_tokens=800)
    rows: list[dict[str, Any]] = []

    with llm_telemetry_scope(f"eval_summary:loop={enable_loop}") as telemetry:
        for case in dataset["cases"]:
            res = await analyze_document_to_portfolio(
                doc_text=case["doc_text"],
                filename=case["filename"],
                project_types=case["project_types"],
                role_hint=case["role_hint"],
                enable_quality_loop=enable_loop,
            )
            sections = res.get("sections") or []
            joined = "\n".join(s.get("content") or "" for s in sections)

            must_facts = case.get("must_include_facts") or []
            fact_hits = sum(1 for f in must_facts if f.lower() in joined.lower())
            fact_cov = round(fact_hits / max(1, len(must_facts)), 4)
            hallucinated_metrics = detect_unverified_metrics(joined, case["doc_text"])
            overlap_ratio = compute_cross_section_overlap(sections)

            judge = await ainvoke_structured(
                judge_llm,
                SummaryJudgeSchema,
                [
                    SystemMessage(
                        content=(
                            "당신은 포트폴리오 정리·요약 품질 평가자입니다. "
                            "원문 문서와 정리된 멀티트랙 섹션을 비교해 Faithfulness, Coverage, Signal Density, Track Fit을 0~1로 엄격 채점하세요."
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"[프로젝트 유형] {case['project_types']}\n"
                            f"[원문 문서]\n{case['doc_text']}\n\n"
                            f"[생성된 포트폴리오 Markdown]\n{res.get('portfolio_markdown', '')[:6000]}"
                        )
                    ),
                ],
                max_retries=1,
                caller=f"eval_s_judge:{case['id']}",
            )
            rows.append(
                {
                    "id": case["id"],
                    "code_fact_coverage": fact_cov,
                    "hallucinated_metric_count": len(hallucinated_metrics),
                    "cross_section_overlap": overlap_ratio,
                    **judge.model_dump(),
                }
            )

    metrics = ("faithfulness", "coverage", "signal_density", "track_fit")
    averages = {m: round(sum(r[m] for r in rows) / max(1, len(rows)), 4) for m in metrics}
    return {
        "mode": "summary",
        "enable_loop": enable_loop,
        "averages": averages,
        "avg_code_fact_coverage": round(
            sum(r["code_fact_coverage"] for r in rows) / max(1, len(rows)), 4
        ),
        "total_hallucinated_metrics": sum(r["hallucinated_metric_count"] for r in rows),
        "avg_cross_section_overlap": round(
            sum(r["cross_section_overlap"] for r in rows) / max(1, len(rows)), 4
        ),
        "telemetry": telemetry.summary(),
        "rows": rows,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Question & Summary Quality Loop Evaluator")
    parser.add_argument("--mode", choices=["question", "summary", "all"], default="all")
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args()

    reports: list[dict[str, Any]] = []
    if args.mode in ("question", "all"):
        for flag in (False, True):
            rep = await evaluate_questions(enable_loop=flag)
            reports.append(rep)
            print(
                f"[QUESTION loop={str(flag):5s}] {rep['averages']} | lint_issues={rep['total_lint_issues']}"
            )
    if args.mode in ("summary", "all"):
        for flag in (False, True):
            rep = await evaluate_summaries(enable_loop=flag)
            reports.append(rep)
            print(
                f"[SUMMARY  loop={str(flag):5s}] {rep['averages']} | "
                f"code_cov={rep['avg_code_fact_coverage']:.3f} | "
                f"hallucinated_metrics={rep['total_hallucinated_metrics']} | "
                f"overlap={rep['avg_cross_section_overlap']:.3f}"
            )

    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(main())
