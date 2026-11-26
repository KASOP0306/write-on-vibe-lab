"""루프 B: 프로젝트 정리·요약 퀄리티 상승 루프 (Evidence Map → 3축 Critic-Repair 최대 2회)."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_fast_llm, get_smart_llm
from app.core.chunker import split_into_chunks
from app.core.project_templates import resolve_section_title
from app.core.vector_store import tokenize_korean_2gram
from app.prompts import build_chat_prompt

logger = logging.getLogger(__name__)

MAX_SUMMARY_REVISIONS = 2
SUMMARY_PASS_THRESHOLD = 82
MAX_CROSS_SECTION_OVERLAP = 0.42

_METRIC_RE = re.compile(
    r"(?<!\d)\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%p|%|배|ms|초|분|시간|일|주|개월|년|만\s*명|만\s*건|만\s*원|억|건|명|개|곳|GB|MB|KB|TPS|VU)",
    re.IGNORECASE,
)
_NUM_ONLY_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


class EvidenceFactItem(BaseModel):
    category: Literal[
        "background",
        "decision",
        "implementation",
        "troubleshooting",
        "metric",
        "collaboration",
        "learning",
    ] = "implementation"
    importance: Literal["high", "normal"] = "normal"
    fact: str = Field(description="원문에서 직접 확인된 사실 1문장")
    metric: str = Field(default="", description="원문에 명시된 수치 그대로 (없으면 빈 문자열)")
    source_ref: str = Field(default="", description="출처 파일명 또는 섹션 헤더")


class EvidenceMapSchema(BaseModel):
    facts: list[EvidenceFactItem] = Field(default_factory=list)


class SummaryCriticSchema(BaseModel):
    faithfulness: int = Field(ge=0, le=35)
    coverage: int = Field(ge=0, le=35)
    signal_density: int = Field(ge=0, le=30)
    total_score: int = Field(ge=0, le=100)
    hallucinations: list[str] = Field(default_factory=list)
    missing_high_facts: list[str] = Field(default_factory=list)
    redundant_pairs: list[str] = Field(default_factory=list)
    repair_instructions: str = Field(default="")


class RepairedSectionItem(BaseModel):
    section_type: str
    title: str = ""
    content: str = ""


class RepairedSectionsSchema(BaseModel):
    sections: list[RepairedSectionItem] = Field(default_factory=list)


def _normalize_metric(token: str) -> str:
    return re.sub(r"\s+", "", token.lower()).replace(",", "")


def detect_unverified_metrics(generated_text: str, source_text: str) -> list[str]:
    """코드 레벨 환각 수치 검사: 생성 본문에 등장한 정량 지표 중 원문에 없는 수치를 반환한다."""
    if not generated_text or not source_text:
        return []

    source_norm = _normalize_metric(source_text)
    source_nums = {m.replace(",", "") for m in _NUM_ONLY_RE.findall(source_text)}

    unverified: list[str] = []
    seen: set[str] = set()
    for match in _METRIC_RE.findall(generated_text):
        norm = _normalize_metric(match)
        if norm in seen:
            continue
        seen.add(norm)
        # 정확한 수치+단위가 원문에 있으면 통과
        if norm in source_norm:
            continue
        # 숫자 부분만 원문에 있는 경우도 소소한 단위 표현 차이(예: 1,420ms vs 1420 ms)로 허용
        num_match = _NUM_ONLY_RE.search(match)
        if num_match and num_match.group(0).replace(",", "") in source_nums:
            continue
        unverified.append(match.strip())
    return unverified


def compute_cross_section_overlap(sections: list[dict[str, Any]]) -> float:
    """비어 있지 않은 섹션 쌍들 사이의 최대 한국어 2-gram Jaccard 중복률을 계산한다 (0.0 ~ 1.0)."""
    token_sets: list[set[str]] = []
    for sec in sections:
        content = str(sec.get("content") or "").strip()
        if len(content) < 40:
            continue
        toks = set(tokenize_korean_2gram(content))
        if toks:
            token_sets.append(toks)

    if len(token_sets) < 2:
        return 0.0

    max_overlap = 0.0
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            inter = len(token_sets[i] & token_sets[j])
            union = len(token_sets[i] | token_sets[j])
            if union > 0:
                max_overlap = max(max_overlap, inter / union)
    return round(max_overlap, 4)


async def extract_evidence_map(
    doc_text: str,
    *,
    filename: str = "document",
    max_chunks: int = 4,
) -> list[dict[str, Any]]:
    """Stage 1 (Map): 긴 원문에서 출처 태깅된 검증 팩트 카드 목록을 추출한다."""
    clean = (doc_text or "").strip()
    if not clean:
        return []

    chunks = split_into_chunks(
        clean[:18000],
        doc_type="experience",
        ref_id=filename[:40],
        metadata={"source_label": filename},
        chunk_size=4200,
        chunk_overlap=200,
        min_chunk_threshold=4500,
    )[:max_chunks]

    llm = get_fast_llm(temperature=0.1, max_tokens=2048)
    collected: list[dict[str, Any]] = []
    seen_facts: set[str] = set()

    for ch in chunks:
        source_tag = ch.section_header or filename
        msgs = build_chat_prompt(
            "evidence_extract",
            "[출처 파일/구간] {source_tag}\n\n[원문]\n{chunk_text}",
            human_vars={"source_tag": source_tag, "chunk_text": ch.content},
        )
        try:
            res = await ainvoke_structured(
                llm,
                EvidenceMapSchema,
                msgs,
                max_retries=1,
                caller=f"summary:evidence_map_c{ch.chunk_index}",
            )
            for item in res.facts:
                f_clean = item.fact.strip()
                if not f_clean or f_clean in seen_facts:
                    continue
                seen_facts.add(f_clean)
                collected.append(
                    {
                        "category": item.category,
                        "importance": item.importance,
                        "fact": f_clean,
                        "metric": item.metric.strip(),
                        "source_ref": item.source_ref.strip() or source_tag,
                    }
                )
        except Exception as exc:
            logger.warning("Evidence map extraction failed on chunk %d: %s", ch.chunk_index, exc)

    return collected[:24]


def format_evidence_map_block(evidence_facts: list[dict[str, Any]]) -> str:
    if not evidence_facts:
        return "(추출된 팩트 카드 없음 — 원문 직접 참고)"
    lines = []
    for idx, f in enumerate(evidence_facts, start=1):
        imp = "★핵심" if f.get("importance") == "high" else "일반"
        metric_tag = f" | 수치: {f['metric']}" if f.get("metric") else ""
        lines.append(
            f"{idx}. [{imp}/{f.get('category', '')}] {f.get('fact', '')}{metric_tag} (출처: {f.get('source_ref', '')})"
        )
    return "\n".join(lines)


async def verify_and_repair_sections(
    sections: list[dict[str, Any]],
    *,
    source_text: str,
    evidence_facts: list[dict[str, Any]] | None = None,
    max_revisions: int = MAX_SUMMARY_REVISIONS,
    pass_threshold: int = SUMMARY_PASS_THRESHOLD,
    flow_name: str = "doc_to_portfolio",
) -> dict[str, Any]:
    """Stage 3 (Critic-Repair, 최대 2회): Fact-Faithfulness × Key-Coverage × Signal-Density 3축 검증 및 보정."""
    if not sections:
        return {
            "sections": [],
            "quality_report": {
                "score": 0,
                "revisions": 0,
                "unverified_metrics": [],
                "cross_section_overlap": 0.0,
                "evidence_count": len(evidence_facts or []),
                "history": [],
            },
        }

    current = [dict(s) for s in sections]
    facts = list(evidence_facts or [])
    evidence_block = format_evidence_map_block(facts)
    history: list[dict[str, Any]] = []
    revisions = 0
    last_score = 100
    last_unverified: list[str] = []
    last_overlap = 0.0

    critic_llm = get_fast_llm(temperature=0.1, max_tokens=1600)
    repair_llm = get_smart_llm(temperature=0.2, max_tokens=4500)

    for attempt in range(max_revisions + 1):
        joined_text = "\n\n".join(
            f"### [{s.get('section_type')}] {s.get('title')}\n{s.get('content') or ''}"
            for s in current
            if (s.get("content") or "").strip()
        )
        unverified = detect_unverified_metrics(joined_text, source_text)
        overlap = compute_cross_section_overlap(current)
        last_unverified = unverified
        last_overlap = overlap

        critic_msgs = build_chat_prompt(
            "summary_verifier",
            (
                "[Evidence Map (원문 검증 팩트)]\n{evidence_block}\n\n"
                "[원문 발췌]\n{source_preview}\n\n"
                "[코드 자동 검사 결과]\n"
                "- 원문 미확인 수치(환각 의심): {unverified}\n"
                "- 섹션 간 최대 2-gram 중복률: {overlap:.2f} (기준 < 0.42)\n\n"
                "[검증 대상 섹션 본문]\n{joined_text}"
            ),
            human_vars={
                "evidence_block": evidence_block[:4500],
                "source_preview": source_text[:4500],
                "unverified": ", ".join(unverified) if unverified else "(없음)",
                "overlap": overlap,
                "joined_text": joined_text[:8000],
            },
        )

        try:
            critic_res = await ainvoke_structured(
                critic_llm,
                SummaryCriticSchema,
                critic_msgs,
                max_retries=1,
                caller=f"{flow_name}:summary_critic_r{attempt}",
            )
            score = int(
                critic_res.faithfulness
                + critic_res.coverage
                + critic_res.signal_density
            )
            if unverified and score >= pass_threshold:
                score = min(score, pass_threshold - 10)
            if overlap >= MAX_CROSS_SECTION_OVERLAP and score >= pass_threshold:
                score = min(score, pass_threshold - 5)
            hallucinations = list(dict.fromkeys([*unverified, *critic_res.hallucinations]))
            missing_facts = list(critic_res.missing_high_facts)
            redundant_pairs = list(critic_res.redundant_pairs)
            instructions = critic_res.repair_instructions.strip()
        except Exception as exc:
            logger.warning("Summary critic failed (attempt %d): %s", attempt, exc)
            score = 65 if (unverified or overlap >= MAX_CROSS_SECTION_OVERLAP) else 85
            hallucinations = list(unverified)
            missing_facts = []
            redundant_pairs = [f"섹션 중복률 {overlap:.2f}"] if overlap >= MAX_CROSS_SECTION_OVERLAP else []
            instructions = "미확인 수치를 제거하고 중복 문장을 압축하세요."

        last_score = score
        history.append(
            {
                "attempt": attempt,
                "score": score,
                "unverified_metrics": unverified,
                "cross_section_overlap": overlap,
                "hallucinations": hallucinations,
                "missing_high_facts": missing_facts,
                "redundant_pairs": redundant_pairs,
            }
        )

        if score >= pass_threshold and not unverified and overlap < MAX_CROSS_SECTION_OVERLAP:
            break
        if attempt >= max_revisions:
            break

        # Auto-Repair (최대 max_revisions=2회)
        repair_msgs = build_chat_prompt(
            "summary_repair",
            (
                "[Evidence Map (유일한 사실 근거)]\n{evidence_block}\n\n"
                "[원문 발췌]\n{source_preview}\n\n"
                "[현재 섹션 본문]\n{joined_text}\n\n"
                "[수정해야 할 결함]\n"
                "- 환각/미확인 수치: {hallucinations}\n"
                "- 누락된 핵심 팩트: {missing_facts}\n"
                "- 중복 섹션/내용: {redundant_pairs}\n"
                "- 수정 지시: {instructions}"
            ),
            human_vars={
                "evidence_block": evidence_block[:4500],
                "source_preview": source_text[:4500],
                "joined_text": joined_text[:8000],
                "hallucinations": ", ".join(hallucinations) or "(없음)",
                "missing_facts": ", ".join(missing_facts) or "(없음)",
                "redundant_pairs": ", ".join(redundant_pairs) or "(없음)",
                "instructions": instructions or "환각 제거·핵심 팩트 복구·중복 압축을 수행하세요.",
            },
        )
        try:
            repaired = await ainvoke_structured(
                repair_llm,
                RepairedSectionsSchema,
                repair_msgs,
                max_retries=1,
                caller=f"{flow_name}:summary_repair_r{attempt + 1}",
            )
            if repaired.sections:
                rep_map = {
                    r.section_type.strip(): r for r in repaired.sections if r.section_type.strip()
                }
                updated_list: list[dict[str, Any]] = []
                for sec in current:
                    st = sec["section_type"]
                    if st in rep_map and rep_map[st].content.strip():
                        updated_list.append(
                            {
                                **sec,
                                "title": resolve_section_title(
                                    st,
                                    rep_map[st].title,
                                    fallback_title=sec["title"],
                                ),
                                "content": rep_map[st].content.strip(),
                            }
                        )
                    else:
                        updated_list.append(sec)
                current = updated_list
                revisions += 1
        except Exception as exc:
            logger.warning("Summary repair failed (attempt %d): %s", attempt + 1, exc)
            break

    return {
        "sections": current,
        "quality_report": {
            "score": last_score,
            "revisions": revisions,
            "unverified_metrics": last_unverified,
            "cross_section_overlap": last_overlap,
            "evidence_count": len(facts),
            "history": history,
        },
    }
