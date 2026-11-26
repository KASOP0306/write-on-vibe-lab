"""객관적 STAR-L 21지표 3단계 하이브리드 평가 엔진 & 누적식 600 XP 포트폴리오 레지스트리.

설계 레퍼런스:
1. Sackett, Zhang, Berry, & Lievens (2022, JAP): 구조화 면접 직무 성과 예측 타당도 1위 (r=0.42)
2. Google re:Work Structured Interviewing & BARS + Amazon Bar Raiser STAR Probing
3. CheckEval (arXiv:2403.18771) × Rulers (2026, Locked Rubrics & Evidence-Anchored Scoring)
   × FActScore (arXiv:2305.14251) × FLASK (ICLR 2024) × RaR (arXiv:2507.17746)

3단계 하이브리드 평가 흐름:
- Layer 1 (LLM 근거 판별기): 21개 Atomic 체크포인트별 status(0/1/2) + 원문 evidence_quote 추출 (점수 계산 금지)
- Layer 2 (Python 결정론적 검증·채점기): 원문 Quote 대조 · 코드 하드 캡(R1/R2/A3/L2) · 짝수 배점 정수 합산
- Layer 3 (버전 진화 & 캘리브레이션): rubric_v2.0.json 번들 · Zero-LLM 재채점 · 문항 분석 · 골든셋 검증
"""

from __future__ import annotations

from functools import lru_cache
import json
import logging
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_fast_llm
from app.prompts import build_chat_prompt

logger = logging.getLogger(__name__)

RUBRICS_DIR = Path(__file__).resolve().parent.parent / "rubrics"
CURRENT_RUBRIC_VERSION = "v2.0"

STAR_AXIS_ORDER = ["situation", "task", "action", "result", "learning"]
STAR_CHECKPOINT_IDS = [
    "S1", "S2", "S3", "S4",
    "T1", "T2", "T3", "T4",
    "A1", "A2", "A3", "A4", "A5", "A6",
    "R1", "R2", "R3", "R4",
    "L1", "L2", "L3",
]


@lru_cache(maxsize=8)
def load_rubric_bundle(version: str = CURRENT_RUBRIC_VERSION) -> dict[str, Any]:
    """버전 고정 루브릭 번들(rubric_<version>.json)을 로드한다 (Rulers Locked Rubric 패턴)."""
    safe_ver = re.sub(r"[^a-zA-Z0-9._-]", "", str(version or CURRENT_RUBRIC_VERSION))
    path = RUBRICS_DIR / f"rubric_{safe_ver}.json"
    if not path.exists():
        logger.warning("Rubric bundle %s not found; falling back to %s", path, CURRENT_RUBRIC_VERSION)
        path = RUBRICS_DIR / f"rubric_{CURRENT_RUBRIC_VERSION}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_rubric_versions() -> list[str]:
    """사용 가능한 루브릭 버전 목록을 반환한다."""
    if not RUBRICS_DIR.exists():
        return [CURRENT_RUBRIC_VERSION]
    versions: list[str] = []
    for f in sorted(RUBRICS_DIR.glob("rubric_*.json")):
        versions.append(f.stem.replace("rubric_", "", 1))
    return versions or [CURRENT_RUBRIC_VERSION]


def _default_bundle() -> dict[str, Any]:
    return load_rubric_bundle(CURRENT_RUBRIC_VERSION)


# ==============================================================================
# 0. Calibration 등급, 프로빙 기법, 축 메타데이터 (rubric_v2.0.json 연동)
# ==============================================================================
CALIBRATION_TIERS: list[dict[str, Any]] = list(_default_bundle()["calibration_tiers"])
STAR_AXES: dict[str, dict[str, Any]] = dict(_default_bundle()["axes"])
STAR_CHECKPOINTS: list[dict[str, Any]] = list(_default_bundle()["checkpoints"])
STAR_CHECKPOINTS_BY_ID: dict[str, dict[str, Any]] = {
    cp["id"]: cp for cp in STAR_CHECKPOINTS
}

PROBING_TECHNIQUES: dict[str, dict[str, str]] = {
    "ownership_drilldown": {
        "id": "ownership_drilldown",
        "label": "'I' Rule 오너십 드릴다운",
        "reference": "Amazon Bar Raiser — Peel-the-Onion",
        "purpose": "'우리가 했다'에서 본인 고유의 판단·실행 경계를 분리합니다.",
    },
    "micro_behavioral": {
        "id": "micro_behavioral",
        "label": "DDI 미세 행동 프로빙",
        "reference": "DDI Funnel Probing (Directed → Micro)",
        "purpose": "추상적 요약 대신 그 순간 취한 구체적 행동·데이터·대화 근거를 끌어냅니다.",
    },
    "counter_factual": {
        "id": "counter_factual",
        "label": "반사실 · 트레이드오프 프로빙",
        "reference": "Google GCA & Amazon Dive Deep",
        "purpose": "포기한 대안, 제약 조건, 리스크 감수 논리를 검증합니다.",
    },
    "xyz_quantification": {
        "id": "xyz_quantification",
        "label": "Google XYZ 정량화 프로빙",
        "reference": "Google XYZ ([X] measured by [Y] by doing [Z])",
        "purpose": "전후 비교 기준치·규모·객관적 변화 증거를 구체화합니다.",
    },
    "learning_transfer": {
        "id": "learning_transfer",
        "label": "회고 · 재발방지 일반화 프로빙",
        "reference": "STAR-L / CARL Framework",
        "purpose": "단순 소감을 넘어 다음 프로젝트에 재사용할 원칙·구조 개선을 도출합니다.",
    },
}

# 레거시 호환용 6축 상수 (코파일럿 도구/기존 DB 레코드 하위 호환 유지)
PORTFOLIO_AXIS_ORDER = [
    "problem_depth",
    "evidence_impact",
    "narrative_coherence",
    "time_execution",
    "people_collaboration",
    "adaptability_growth",
]

PORTFOLIO_AXES: dict[str, dict[str, Any]] = {
    "problem_depth": {
        "id": "problem_depth",
        "domain": "internal",
        "domain_label": "내적 역량",
        "label": "문제해결 깊이",
        "short_label": "문제해결 깊이",
        "reference": "STAR-L Action (A1·A2·A4)",
        "description": "복잡한 문제를 구조화하고 대안 비교·트레이드오프·트러블슈팅을 거쳐 끝까지 해결한 깊이",
    },
    "evidence_impact": {
        "id": "evidence_impact",
        "domain": "internal",
        "domain_label": "내적 역량",
        "label": "증거력 · 성과 검증",
        "short_label": "증거력·성과",
        "reference": "STAR-L Result (R1·R2·R3·R4)",
        "description": "정량 지표, 전후 비교, 외부 검증 등 객관적으로 증명 가능한 산출물의 힘",
    },
    "narrative_coherence": {
        "id": "narrative_coherence",
        "domain": "internal",
        "domain_label": "내적 역량",
        "label": "서사 일관성",
        "short_label": "서사 일관성",
        "reference": "STAR-L Situation·Task (S1~S4·T1~T4)",
        "description": "문제 정의·목표·역할 경계가 일관된 맥락으로 연결되는가",
    },
    "time_execution": {
        "id": "time_execution",
        "domain": "external",
        "domain_label": "외적 역량",
        "label": "일정 · 스코프 · 리스크 관리",
        "short_label": "일정·리스크",
        "reference": "STAR-L Action A5",
        "description": "제한된 기간·리소스 안에서 MVP 범위를 조정하고 리스크를 관리한 운영력",
    },
    "people_collaboration": {
        "id": "people_collaboration",
        "domain": "external",
        "domain_label": "외적 역량",
        "label": "협업 · 이해관계자 조율",
        "short_label": "협업·조율",
        "reference": "STAR-L Action A6",
        "description": "팀원·타 직군·고객과 소통하고 의견 충돌을 데이터로 합의한 역량",
    },
    "adaptability_growth": {
        "id": "adaptability_growth",
        "domain": "external",
        "domain_label": "외적 역량",
        "label": "회고 · 학습 민첩성",
        "short_label": "회고·학습력",
        "reference": "STAR-L Learning (L1·L2·L3)",
        "description": "실패·한계를 메타인지하고 일반화한 원칙을 후속 프로젝트에 재적용한 역량",
    },
}


# ==============================================================================
# 1. 기본 등급 / XP / 가중 점수 헬퍼
# ==============================================================================
def get_calibration_tier(score: int, rubric_version: str = CURRENT_RUBRIC_VERSION) -> dict[str, Any]:
    """0~100 점수를 보수적 Calibration 등급(S/A/B/C/D)으로 매핑한다."""
    bundle = load_rubric_bundle(rubric_version)
    s = max(0, min(100, int(score or 0)))
    for tier in bundle["calibration_tiers"]:
        if s >= int(tier["min_score"]):
            return dict(tier)
    return dict(bundle["calibration_tiers"][-1])


def compute_experience_xp(score: int, rubric_version: str = CURRENT_RUBRIC_VERSION) -> dict[str, Any]:
    """품질 게이트 배수(S:1.5, A:1.3, B:1.0, C:0.6, D:0.25)로 경험 1건의 누적 XP를 산출한다."""
    s = max(0, min(100, int(score or 0)))
    tier = get_calibration_tier(s, rubric_version=rubric_version)
    multiplier = float(tier.get("xp_multiplier", 1.0))
    xp = int(round(s * multiplier))
    return {
        "xp": xp,
        "grade": tier["grade"],
        "multiplier": multiplier,
        "tier_label": tier["label"],
    }


def level_to_score(level: int) -> int:
    clamped = max(1, min(5, int(level)))
    return clamped * 20


def pct_to_level(pct: int) -> int:
    """0~100 축 달성률을 1~5 등급으로 결정론적 변환한다."""
    p = max(0, min(100, int(pct or 0)))
    if p >= 85:
        return 5
    if p >= 68:
        return 4
    if p >= 45:
        return 3
    if p >= 20:
        return 2
    return 1


def compute_weighted_star_score(
    axes: dict[str, dict[str, Any]],
    rubric_version: str = CURRENT_RUBRIC_VERSION,
) -> int:
    """5축 STAR-L 점수를 현재 루브릭 가중치(S 12 / T 14 / A 36 / R 26 / L 12)로 결정론적 합산한다."""
    bundle = load_rubric_bundle(rubric_version)
    bundle_axes = bundle["axes"]
    # earned 필드가 모든 축에 있으면 정수 earned 합산 (v2.0 정밀 합산)
    if all(
        isinstance(axes.get(ax), dict) and axes[ax].get("earned") is not None
        for ax in STAR_AXIS_ORDER
    ):
        return max(
            0,
            min(
                100,
                sum(int(axes[ax]["earned"]) for ax in STAR_AXIS_ORDER),
            ),
        )

    total = 0.0
    for axis_id in STAR_AXIS_ORDER:
        meta = bundle_axes[axis_id]
        entry = axes.get(axis_id) or {}
        if "score" in entry and entry["score"] is not None:
            sc = max(0, min(100, int(entry["score"])))
        elif "level" in entry and entry["level"] is not None:
            sc = level_to_score(int(entry["level"]))
        else:
            sc = 0
        total += sc * float(meta["weight"])
    return max(0, min(100, int(round(total))))


# ==============================================================================
# 2. Layer 2: 결정론적 원문 대조(Quote Grounding) & 코드 하드 캡(Guardrails)
# ==============================================================================
_METRIC_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_METRIC_UNIT_RE = re.compile(
    r"(?:\d+(?:[.,]\d+)?\s*(?:%|ms|초|분|시간|일|주|개월|년|명|건|회|배|원|만|억|천|개|점|위|TPS|QPS|RPS|MB|GB|KB|p95|p99|x|X|억|만원|퍼센트|배수))",
    re.IGNORECASE,
)
_COMPARISON_SIGNAL_RE = re.compile(
    r"(→|->|~에서|에서\s*\d|전\s*대비|대비|기존\s*대비|기존보다|목표\s*대비|감소|증가|단축|절감|향상|상승|하락|줄였|줄어들|늘었|늘렸|개선되었|before|after|vs\.?|baseline|기준선)",
    re.IGNORECASE,
)
_TEAM_PHRASE_RE = re.compile(r"(우리\s*팀|팀원들과|팀이|다\s*같이|함께\s*진행|공동으로)")
_OWNERSHIP_SIGNAL_RE = re.compile(
    r"(제가|내가|본인이|직접|단독|주도|설계했|구현했|구축했|작성했|개발했|도입했|제안했|결정했|분석했|진단했|해결했|최적화했|리딩|담당하여\s*직접|설득했|정의했|마이그레이션했)"
)
_CLICHE_LEARNING_RE = re.compile(
    r"(많이\s*배웠|뜻깊은|좋은\s*경험|뿌듯|소통이\s*중요|협업이\s*중요|성장할\s*수\s*있|성장했|유익한\s*시간|열심히\s*해야)"
)
_PRINCIPLE_SIGNAL_RE = re.compile(
    r"(원칙|기준|체크리스트|프로세스|구조|재발\s*방지|자동화|검증|모니터링|벤치마크|문서화|설계|사전|먼저|우선|트레이드오프|기준선|표준|템플릿|룰|가이드|다음\s*프로젝트|이후\s*프로젝트)"
)


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[\s\"'`.,!?;:()\[\]{}·—\-_/]+", "", (text or "").lower())


def _char_2grams(text: str) -> set[str]:
    norm = _normalize_for_match(text)
    if len(norm) < 2:
        return {norm} if norm else set()
    return {norm[i : i + 2] for i in range(len(norm) - 1)}


def verify_quote_grounding(quote: str, source_text: str) -> tuple[bool, float]:
    """LLM이 추출한 evidence_quote가 원문에 실제로 근거하는지 결정론적으로 검증한다."""
    q_norm = _normalize_for_match(quote)
    s_norm = _normalize_for_match(source_text)
    if not q_norm or len(q_norm) < 2 or not s_norm:
        return False, 0.0
    if q_norm in s_norm:
        return True, 1.0
    # 긴 인용구 중간 일부가 생략(...)되었을 수 있으므로 2-gram recall 측정
    q_grams = _char_2grams(quote)
    s_grams = _char_2grams(source_text)
    if not q_grams:
        return False, 0.0
    overlap = len(q_grams & s_grams) / len(q_grams)
    return overlap >= 0.48, round(overlap, 3)


def verify_and_score_checkpoints(
    raw_checkpoints: dict[str, dict[str, Any]],
    *,
    star: dict[str, Any],
    context_text: str = "",
    rubric_version: str = CURRENT_RUBRIC_VERSION,
) -> dict[str, Any]:
    """Layer 2: 21개 체크포인트 판정 결과를 원문 대조·코드 하드캡·짝수 정수 합산으로 결정론적 채점한다."""
    bundle = load_rubric_bundle(rubric_version)
    cp_defs: list[dict[str, Any]] = bundle["checkpoints"]
    axis_defs: dict[str, dict[str, Any]] = bundle["axes"]

    s_txt = str(star.get("situation") or "").strip()
    t_txt = str(star.get("task") or "").strip()
    a_txt = str(star.get("action") or "").strip()
    r_txt = str(star.get("result") or "").strip()
    l_txt = str(star.get("learning") or "").strip()
    m_txt = str(star.get("quantified_metrics") or "").strip()
    title_txt = str(star.get("title") or "").strip()

    axis_texts = {
        "situation": s_txt,
        "task": t_txt,
        "action": a_txt,
        "result": f"{r_txt} {m_txt}".strip(),
        "learning": l_txt,
    }
    full_source = "\n".join(
        p for p in [title_txt, s_txt, t_txt, a_txt, r_txt, l_txt, m_txt, context_text] if p
    )
    result_combined = f"{r_txt} {m_txt}".strip()

    # 사전 신호 계산 (결정론적 규칙)
    has_any_digit_result = bool(_METRIC_NUMBER_RE.search(result_combined))
    has_metric_unit_result = bool(_METRIC_UNIT_RE.search(result_combined))
    has_comparison_result = bool(_COMPARISON_SIGNAL_RE.search(f"{result_combined} {context_text}"))
    has_team_phrase = bool(_TEAM_PHRASE_RE.search(f"{t_txt} {a_txt} {context_text}"))
    has_ownership_signal = bool(_OWNERSHIP_SIGNAL_RE.search(f"{t_txt} {a_txt} {context_text}"))
    has_cliche_learning = bool(_CLICHE_LEARNING_RE.search(l_txt))
    has_principle_learning = bool(_PRINCIPLE_SIGNAL_RE.search(f"{l_txt} {r_txt}"))

    checkpoints_out: dict[str, dict[str, Any]] = {}
    cap_events: list[dict[str, Any]] = []

    for cp in cp_defs:
        cid = cp["id"]
        axis_id = cp["axis"]
        weight = int(cp["weight"])
        raw = raw_checkpoints.get(cid) or {}

        raw_status = max(0, min(2, int(raw.get("status", 0) or 0)))
        quote = str(raw.get("quote") or raw.get("evidence_quote") or "").strip()
        tip = str(raw.get("tip") or "").strip()

        status = raw_status
        grounded = False
        grounding_overlap = 0.0
        capped_reason = ""

        # 1) Quote Grounding 검증 (Rulers Evidence-Anchored Scoring)
        if status >= 1:
            grounded, grounding_overlap = verify_quote_grounding(quote, full_source)
            if not quote:
                if status == 2:
                    status = 1
                    capped_reason = "missing_quote"
                elif len(axis_texts.get(axis_id, "")) < 15:
                    status = 0
                    capped_reason = "empty_quote_and_short_axis"
            elif not grounded:
                # 원문에 없는 환각 인용구 → 강등
                status = 0 if grounding_overlap < 0.25 else min(status, 1)
                capped_reason = f"ungrounded_quote(overlap={grounding_overlap})"

        # 2) 빈 축/극단적 단문 가드
        if len(axis_texts.get(axis_id, "")) < 10 and len(full_source) < 60 and status == 2:
            status = 1
            capped_reason = capped_reason or "too_short_axis"
        if axis_id == "learning" and not l_txt and status > 0:
            # Learning 원문이 완전히 비어있고 Result에도 원칙/회고가 없으면 0
            if not has_principle_learning:
                status = 0
                capped_reason = capped_reason or "empty_learning"

        # 3) 핵심 체크포인트별 결정론적 코드 하드 캡
        if cid == "R1":
            if not has_any_digit_result:
                if status > 0:
                    status = 0
                    capped_reason = "R1_no_numeric_metric"
            elif not has_metric_unit_result and status == 2:
                status = 1
                capped_reason = "R1_no_metric_unit"
        elif cid == "R2":
            if not has_comparison_result:
                if status == 2:
                    status = 1
                    capped_reason = "R2_no_before_after_signal"
                elif not has_any_digit_result and status == 1 and len(result_combined) < 25:
                    status = 0
                    capped_reason = "R2_no_baseline"
        elif cid == "A3":
            if has_team_phrase and not has_ownership_signal and status == 2:
                status = 1
                capped_reason = "A3_team_only_without_I_signal"
        elif cid == "L2":
            if has_cliche_learning and not has_principle_learning and len(l_txt) < 55 and status > 0:
                status = 0
                capped_reason = "L2_cliche_only_learning"

        if capped_reason and status < raw_status:
            cap_events.append(
                {
                    "checkpoint_id": cid,
                    "raw_status": raw_status,
                    "final_status": status,
                    "reason": capped_reason,
                }
            )
            if not tip:
                tip = cp.get("probe_hint", "")

        # 4) 짝수 배점 정수 점수 산출 (0 / weight//2 / weight)
        earned = int(status * (weight // 2))
        checkpoints_out[cid] = {
            "id": cid,
            "axis": axis_id,
            "label": cp["label"],
            "weight": weight,
            "status": status,
            "raw_status": raw_status,
            "earned": earned,
            "quote": quote if status > 0 else "",
            "grounded": grounded if status > 0 else False,
            "capped_reason": capped_reason,
            "tip": "" if status == 2 else (tip or cp.get("probe_hint", "")),
            "technique": cp.get("technique", "micro_behavioral"),
        }

    # 5) 5축 집계 (하위 호환 level 1~5 + score 0~100 + earned/max_points)
    axes_out: dict[str, dict[str, Any]] = {}
    for axis_id in STAR_AXIS_ORDER:
        meta = axis_defs[axis_id]
        max_pts = int(meta["max_points"])
        axis_cps = [checkpoints_out[cp["id"]] for cp in cp_defs if cp["axis"] == axis_id]
        earned_pts = sum(c["earned"] for c in axis_cps)
        pct = int(round((earned_pts / max_pts) * 100)) if max_pts > 0 else 0
        lvl = pct_to_level(pct)

        ev_quotes = [c["quote"] for c in axis_cps if c["status"] >= 1 and c["quote"]]
        weakest_cp = sorted(axis_cps, key=lambda c: (c["status"], -c["weight"]))[0]
        passed_cnt = sum(1 for c in axis_cps if c["status"] == 2)
        partial_cnt = sum(1 for c in axis_cps if c["status"] == 1)

        axes_out[axis_id] = {
            "level": lvl,
            "score": pct,
            "earned": earned_pts,
            "max_points": max_pts,
            "passed_count": passed_cnt,
            "partial_count": partial_cnt,
            "total_checkpoints": len(axis_cps),
            "evidence": " / ".join(ev_quotes[:2]) if ev_quotes else "원문에서 입증된 구체 근거가 부족합니다.",
            "tip": weakest_cp["tip"] if weakest_cp["status"] < 2 else "핵심 체크포인트가 모두 입증되었습니다.",
        }

    weighted_score = sum(c["earned"] for c in checkpoints_out.values())
    tier = get_calibration_tier(weighted_score, rubric_version=rubric_version)
    xp_info = compute_experience_xp(weighted_score, rubric_version=rubric_version)

    # 6) 역질문 우선 타겟 (status 오름차순 → 배점 내림차순)
    unmet = [c for c in checkpoints_out.values() if c["status"] < 2]
    unmet.sort(key=lambda c: (c["status"], -c["weight"]))
    priority_targets = [
        {
            "id": c["id"],
            "axis": c["axis"],
            "label": c["label"],
            "weight": c["weight"],
            "status": c["status"],
            "technique": c["technique"],
            "tip": c["tip"],
        }
        for c in unmet[:5]
    ]

    passed_total = sum(1 for c in checkpoints_out.values() if c["status"] == 2)
    partial_total = sum(1 for c in checkpoints_out.values() if c["status"] == 1)

    return {
        "framework": bundle["name"],
        "rubric_version": bundle["version"],
        "axes": axes_out,
        "checkpoints": checkpoints_out,
        "cap_events": cap_events,
        "priority_targets": priority_targets,
        "passed_checkpoints": passed_total,
        "partial_checkpoints": partial_total,
        "total_checkpoints": len(checkpoints_out),
        "weighted_score": weighted_score,
        "grade": tier["grade"],
        "tier_label": tier["label"],
        "xp": xp_info["xp"],
        "xp_multiplier": xp_info["multiplier"],
    }


def rescore_experience_with_rubric(
    star_scores: dict[str, Any],
    star: dict[str, Any],
    *,
    context_text: str = "",
    rubric_version: str = CURRENT_RUBRIC_VERSION,
) -> dict[str, Any]:
    """Zero-LLM 재채점: 저장된 21개 체크포인트 원시 판정을 새 루브릭 버전으로 LLM 호출 없이 즉시 재계산한다."""
    raw_cps = (star_scores or {}).get("checkpoints")
    if not isinstance(raw_cps, dict) or not raw_cps:
        return normalize_star_scores(star_scores)
    reconstructed = {
        cid: {
            "status": item.get("raw_status", item.get("status", 0)),
            "quote": item.get("quote", ""),
            "tip": item.get("tip", ""),
        }
        for cid, item in raw_cps.items()
        if isinstance(item, dict)
    }
    return verify_and_score_checkpoints(
        reconstructed,
        star=star,
        context_text=context_text,
        rubric_version=rubric_version,
    )


# ==============================================================================
# 3. 정규화 및 누적식 600 XP 포트폴리오 집계 엔진
# ==============================================================================
def normalize_star_scores(raw: dict[str, Any] | None) -> dict[str, Any]:
    """DB에 저장된 star_scores JSONB를 표준 형식으로 정규화한다 (v1 레거시 & v2.0 모두 안전 지원)."""
    if not raw or not isinstance(raw, dict):
        return {}
    raw_axes = raw.get("axes")
    if not isinstance(raw_axes, dict) or not raw_axes:
        return {}

    rubric_ver = str(raw.get("rubric_version") or CURRENT_RUBRIC_VERSION)
    bundle = load_rubric_bundle(rubric_ver)
    bundle_axes = bundle["axes"]

    axes: dict[str, dict[str, Any]] = {}
    for axis_id in STAR_AXIS_ORDER:
        item = raw_axes.get(axis_id) or {}
        max_pts = int(bundle_axes[axis_id]["max_points"])
        sc = max(
            0,
            min(
                100,
                int(
                    item["score"]
                    if item.get("score") is not None
                    else level_to_score(int(item.get("level") or 1))
                ),
            ),
        )
        lvl = max(1, min(5, int(item.get("level") or pct_to_level(sc))))
        earned = (
            int(item["earned"])
            if item.get("earned") is not None
            else int(round((sc / 100.0) * max_pts))
        )
        axes[axis_id] = {
            "level": lvl,
            "score": sc,
            "earned": max(0, min(max_pts, earned)),
            "max_points": max_pts,
            "passed_count": int(item.get("passed_count") or 0),
            "partial_count": int(item.get("partial_count") or 0),
            "total_checkpoints": int(item.get("total_checkpoints") or 0),
            "evidence": str(item.get("evidence") or "").strip(),
            "tip": str(item.get("tip") or "").strip(),
        }

    weighted = (
        int(raw["weighted_score"])
        if raw.get("weighted_score") is not None and raw.get("checkpoints")
        else compute_weighted_star_score(axes, rubric_version=rubric_ver)
    )
    weighted = max(0, min(100, weighted))
    tier = get_calibration_tier(weighted, rubric_version=rubric_ver)
    xp_info = compute_experience_xp(weighted, rubric_version=rubric_ver)

    normalized: dict[str, Any] = {
        "framework": str(raw.get("framework") or bundle["name"]),
        "rubric_version": rubric_ver,
        "axes": axes,
        "weighted_score": weighted,
        "grade": tier["grade"],
        "tier_label": tier["label"],
        "xp": xp_info["xp"],
        "xp_multiplier": xp_info["multiplier"],
    }
    if isinstance(raw.get("checkpoints"), dict) and raw["checkpoints"]:
        normalized["checkpoints"] = raw["checkpoints"]
        normalized["passed_checkpoints"] = int(
            raw.get("passed_checkpoints")
            or sum(1 for c in raw["checkpoints"].values() if int(c.get("status", 0)) == 2)
        )
        normalized["partial_checkpoints"] = int(
            raw.get("partial_checkpoints")
            or sum(1 for c in raw["checkpoints"].values() if int(c.get("status", 0)) == 1)
        )
        normalized["total_checkpoints"] = len(raw["checkpoints"])
    if isinstance(raw.get("cap_events"), list):
        normalized["cap_events"] = raw["cap_events"]
    if isinstance(raw.get("priority_targets"), list):
        normalized["priority_targets"] = raw["priority_targets"]
    return normalized


def compute_average_star_axes(experiences: list[dict[str, Any]]) -> dict[str, Any]:
    """여러 STAR 경험의 5축 평균 점수와 종합 평균을 계산한다."""
    scored = [
        normalize_star_scores(e.get("star_scores"))
        for e in experiences
        if isinstance(e, dict) and normalize_star_scores(e.get("star_scores"))
    ]
    if not scored:
        return {
            "evaluated_count": 0,
            "total_count": len(experiences),
            "weighted_score": 0,
            "axes": {
                axis_id: {
                    "score": 0,
                    "level": 0,
                    "earned": 0,
                    "max_points": int(STAR_AXES[axis_id]["max_points"]),
                }
                for axis_id in STAR_AXIS_ORDER
            },
        }

    avg_axes: dict[str, dict[str, Any]] = {}
    for axis_id in STAR_AXIS_ORDER:
        max_pts = int(STAR_AXES[axis_id]["max_points"])
        mean_sc = round(
            sum(item["axes"][axis_id]["score"] for item in scored) / len(scored)
        )
        mean_earned = round(
            sum(item["axes"][axis_id]["earned"] for item in scored) / len(scored)
        )
        avg_axes[axis_id] = {
            "score": int(mean_sc),
            "level": round(mean_sc / 20, 1),
            "earned": int(mean_earned),
            "max_points": max_pts,
        }

    avg_weighted = int(round(sum(item["weighted_score"] for item in scored) / len(scored)))
    return {
        "evaluated_count": len(scored),
        "total_count": len(experiences),
        "weighted_score": avg_weighted,
        "axes": avg_axes,
    }


def compute_cumulative_portfolio_xp(
    projects: list[dict[str, Any]],
    experiences: list[dict[str, Any]],
    *,
    rubric_version: str = CURRENT_RUBRIC_VERSION,
) -> dict[str, Any]:
    """대표 4개 프로젝트 × 프로젝트당 150 XP 캡 = 총 600 XP 누적 포트폴리오 마스터리를 계산한다."""
    bundle = load_rubric_bundle(rubric_version)
    xp_cfg = bundle["portfolio_xp"]
    project_cap = int(xp_cfg["project_cap"])
    max_selected = int(xp_cfg["max_selected_projects"])
    max_total_xp = int(xp_cfg["max_total_xp"])
    levels_cfg: list[dict[str, Any]] = xp_cfg["levels"]
    cp_defs: list[dict[str, Any]] = bundle["checkpoints"]

    # 프로젝트별 경험 매핑
    exps_by_proj: dict[int | None, list[dict[str, Any]]] = {}
    for exp in experiences:
        pid = exp.get("project_id")
        exps_by_proj.setdefault(pid, []).append(exp)

    project_entries: list[dict[str, Any]] = []
    for proj in projects:
        pid = proj["id"]
        p_exps = exps_by_proj.get(pid, [])
        raw_xp_sum = 0
        best_score = 0
        exp_summaries: list[dict[str, Any]] = []
        for exp in p_exps:
            norm = normalize_star_scores(exp.get("star_scores"))
            sc = norm["weighted_score"] if norm else int(exp.get("completeness_score") or 0)
            xp_info = compute_experience_xp(sc, rubric_version=rubric_version)
            raw_xp_sum += xp_info["xp"]
            best_score = max(best_score, sc)
            exp_summaries.append(
                {
                    "id": exp.get("id"),
                    "title": exp.get("title", ""),
                    "score": sc,
                    "grade": xp_info["grade"],
                    "xp": xp_info["xp"],
                }
            )
        capped_xp = min(raw_xp_sum, project_cap)
        project_entries.append(
            {
                "project_id": pid,
                "name": proj.get("name", ""),
                "period": proj.get("period", ""),
                "project_types": list(proj.get("project_types") or ["engineering"]),
                "is_selected": bool(proj.get("is_portfolio_selected", False)),
                "selection_mode": "manual" if proj.get("is_portfolio_selected") else "candidate",
                "experience_count": len(p_exps),
                "best_score": best_score,
                "raw_xp": raw_xp_sum,
                "capped_xp": capped_xp,
                "cap": project_cap,
                "cap_reached": raw_xp_sum >= project_cap,
                "progress_pct": int(round((capped_xp / project_cap) * 100)) if project_cap else 0,
                "experiences": exp_summaries,
            }
        )

    # 대표 4개 프로젝트 선정: 수동 선택 우선(최대 4개), 남은 슬롯은 XP 높은 순 자동 충원
    manual_selected = sorted(
        [p for p in project_entries if p["is_selected"]],
        key=lambda x: (-x["capped_xp"], -x["best_score"], x["project_id"]),
    )[:max_selected]
    selected_ids = {p["project_id"] for p in manual_selected}

    remaining_slots = max_selected - len(manual_selected)
    auto_filled: list[dict[str, Any]] = []
    if remaining_slots > 0:
        candidates = sorted(
            [p for p in project_entries if p["project_id"] not in selected_ids],
            key=lambda x: (-x["capped_xp"], -x["experience_count"], x["project_id"]),
        )[:remaining_slots]
        for cand in candidates:
            cand["selection_mode"] = "auto_fill"
            auto_filled.append(cand)
            selected_ids.add(cand["project_id"])

    selected_projects = manual_selected + auto_filled
    total_xp = min(max_total_xp, sum(p["capped_xp"] for p in selected_projects))
    xp_pct = int(round((total_xp / max_total_xp) * 100)) if max_total_xp else 0

    current_level = levels_cfg[-1]
    next_level = None
    for idx, lv in enumerate(levels_cfg):
        if total_xp >= int(lv["min_xp"]):
            current_level = lv
            next_level = levels_cfg[idx - 1] if idx > 0 else None
            break

    # 대표 4개 프로젝트 소속 경험 기반 5축 평균 & 21지표 히트맵
    selected_exps: list[dict[str, Any]] = []
    for pid in selected_ids:
        selected_exps.extend(exps_by_proj.get(pid, []))
    # 프로젝트 미연결 경험만 있는 경우에도 참고 통계 표시 (XP에는 프로젝트 기반만 합산하되 미연결 안내)
    unlinked_exps = exps_by_proj.get(None, [])
    analysis_exps = selected_exps if selected_exps else experiences
    star_averages = compute_average_star_axes(analysis_exps)

    # 21개 체크포인트 히트맵 집계
    cp_stats: list[dict[str, Any]] = []
    for cp in cp_defs:
        cid = cp["id"]
        statuses: list[int] = []
        weakest_project_id: int | None = None
        weakest_project_name = ""
        for exp in analysis_exps:
            norm = normalize_star_scores(exp.get("star_scores"))
            cps_map = norm.get("checkpoints") if norm else None
            if isinstance(cps_map, dict) and cid in cps_map:
                st = int(cps_map[cid].get("status", 0))
                statuses.append(st)
                if st == 0 and weakest_project_id is None and exp.get("project_id") is not None:
                    weakest_project_id = exp["project_id"]
        if weakest_project_id is not None:
            for p in project_entries:
                if p["project_id"] == weakest_project_id:
                    weakest_project_name = p["name"]
                    break
        evaluated = len(statuses)
        passed = sum(1 for s in statuses if s == 2)
        partial = sum(1 for s in statuses if s == 1)
        missed = sum(1 for s in statuses if s == 0)
        avg_pct = int(round((sum(statuses) / (evaluated * 2)) * 100)) if evaluated else 0
        cp_stats.append(
            {
                "id": cid,
                "axis": cp["axis"],
                "label": cp["label"],
                "weight": int(cp["weight"]),
                "evaluated_count": evaluated,
                "passed_count": passed,
                "partial_count": partial,
                "missed_count": missed,
                "mastery_pct": avg_pct,
                "probe_hint": cp.get("probe_hint", ""),
                "suggested_project_id": weakest_project_id
                or (selected_projects[0]["project_id"] if selected_projects else None),
                "suggested_project_name": weakest_project_name
                or (selected_projects[0]["name"] if selected_projects else ""),
            }
        )

    # 우선 보강 체크포인트 TOP 3 (평가된 경험 기준 달성률 낮고 배점 높은 순)
    evaluated_cps = [c for c in cp_stats if c["evaluated_count"] > 0]
    weakest_checkpoints = sorted(
        evaluated_cps if evaluated_cps else cp_stats,
        key=lambda c: (c["mastery_pct"], -c["weight"]),
    )[:3]

    return {
        "rubric_version": bundle["version"],
        "total_xp": total_xp,
        "max_total_xp": max_total_xp,
        "xp_pct": xp_pct,
        "project_cap": project_cap,
        "max_selected_projects": max_selected,
        "manual_selected_count": len(manual_selected),
        "level": current_level,
        "next_level": next_level,
        "xp_to_next_level": (
            max(0, int(next_level["min_xp"]) - total_xp) if next_level else 0
        ),
        "selected_projects": selected_projects,
        "all_projects": sorted(
            project_entries,
            key=lambda x: (-int(x["project_id"] in selected_ids), -x["capped_xp"], x["project_id"]),
        ),
        "unlinked_experience_count": len(unlinked_exps),
        "star_averages": star_averages,
        "checkpoint_heatmap": cp_stats,
        "weakest_checkpoints": weakest_checkpoints,
    }


def compute_portfolio_overall_score(axes: dict[str, dict[str, Any]]) -> dict[str, int]:
    """레거시 6축 호출 하위 호환용 평균 계산기."""
    internal_scores: list[int] = []
    external_scores: list[int] = []
    all_scores: list[int] = []

    for axis_id in PORTFOLIO_AXIS_ORDER:
        meta = PORTFOLIO_AXES[axis_id]
        entry = axes.get(axis_id) or {}
        sc = max(0, min(100, int(entry.get("score") or 0)))
        all_scores.append(sc)
        if meta["domain"] == "internal":
            internal_scores.append(sc)
        else:
            external_scores.append(sc)

    return {
        "overall_score": int(round(sum(all_scores) / len(all_scores))) if all_scores else 0,
        "internal_score": int(round(sum(internal_scores) / len(internal_scores))) if internal_scores else 0,
        "external_score": int(round(sum(external_scores) / len(external_scores))) if external_scores else 0,
    }


def get_rubric_reference_payload(rubric_version: str = CURRENT_RUBRIC_VERSION) -> dict[str, Any]:
    """프론트엔드 평가 기준 레퍼런스 모달 및 대시보드 렌더링용 메타데이터."""
    bundle = load_rubric_bundle(rubric_version)
    return {
        "rubric_version": bundle["version"],
        "available_versions": list_rubric_versions(),
        "calibration_tiers": bundle["calibration_tiers"],
        "portfolio_xp": bundle["portfolio_xp"],
        "probing_techniques": list(PROBING_TECHNIQUES.values()),
        "star_rubric": {
            "name": bundle["name"],
            "frameworks": bundle["references"],
            "formula": "21개 Atomic 체크포인트 하이브리드 채점: S(12) + T(14) + A(36) + R(26) + L(12) = 100점 (LLM 0/1/2 근거 판별 → Python 원문 대조·하드캡·정수 합산)",
            "axes": [bundle["axes"][k] for k in STAR_AXIS_ORDER],
            "checkpoints": bundle["checkpoints"],
        },
    }


# ==============================================================================
# 4. Layer 1: Structured Output 기반 21개 체크포인트 근거 판별기
# ==============================================================================
class CheckpointAuditItem(BaseModel):
    status: int = Field(ge=0, le=2, description="0=미충족, 1=부분/추상 언급, 2=구체 근거·수치로 입증")
    quote: str = Field(default="", description="status>=1일 때 원문에서 직접 인용한 핵심 구절(10~70자)")
    tip: str = Field(default="", description="status<2일 때 보강할 1줄 팁 (status==2면 빈 문자열)")


class StarCheckpointAuditSchema(BaseModel):
    S1: CheckpointAuditItem
    S2: CheckpointAuditItem
    S3: CheckpointAuditItem
    S4: CheckpointAuditItem
    T1: CheckpointAuditItem
    T2: CheckpointAuditItem
    T3: CheckpointAuditItem
    T4: CheckpointAuditItem
    A1: CheckpointAuditItem
    A2: CheckpointAuditItem
    A3: CheckpointAuditItem
    A4: CheckpointAuditItem
    A5: CheckpointAuditItem
    A6: CheckpointAuditItem
    R1: CheckpointAuditItem
    R2: CheckpointAuditItem
    R3: CheckpointAuditItem
    R4: CheckpointAuditItem
    L1: CheckpointAuditItem
    L2: CheckpointAuditItem
    L3: CheckpointAuditItem
    missing_points: list[str] = Field(
        default_factory=list,
        description="가장 치명적으로 부족한 핵심 공백 2~4개",
    )


async def evaluate_star_experience_rubric(
    star: dict[str, Any],
    *,
    context_text: str = "",
    project_types: list[str] | None = None,
    rubric_version: str = CURRENT_RUBRIC_VERSION,
) -> dict[str, Any]:
    """3단계 하이브리드 평가 실행: Layer 1(LLM 21지표 근거 판별) → Layer 2(Python 검증·하드캡·정수 합산)."""
    bundle = load_rubric_bundle(rubric_version)
    llm = get_fast_llm(temperature=0.05, max_tokens=3000)

    checkpoint_guide_lines = [
        f"- {cp['id']} [{cp['axis'].upper()}, 배점 {cp['weight']}점] {cp['label']}: "
        f"0={cp['anchor_0']} | 1={cp['anchor_1']} | 2={cp['anchor_2']}"
        for cp in bundle["checkpoints"]
    ]

    tracks = [t for t in (project_types or []) if t in bundle.get("track_hints", {})]
    if tracks:
        track_hint = "\n".join(
            f"- {t}: {bundle['track_hints'][t]}" for t in tracks
        )
    else:
        track_hint = "직무 무관 범용 기준을 적용하되, 기술·기획·데이터·운영 등 해당 분야의 객관적 근거를 공정하게 인정하세요."

    human_body = (
        "[평가 대상 STAR-L]\n"
        "- 제목: {title}\n"
        "- Situation: {situation}\n"
        "- Task: {task}\n"
        "- Action: {action}\n"
        "- Result: {result}\n"
        "- Learning: {learning}\n"
        "- 정량 지표: {quantified_metrics}\n"
        "{extra_context}"
    )
    extra_ctx = f"\n[추가 맥락 / 원본 메모 및 프로젝트 요약]\n{context_text[:5500]}" if context_text.strip() else ""

    messages = build_chat_prompt(
        "star_checkpoint_audit",
        human_body,
        system_vars={
            "checkpoint_guide": "\n".join(checkpoint_guide_lines),
            "track_hint": track_hint,
        },
        human_vars={
            "title": str(star.get("title") or ""),
            "situation": str(star.get("situation") or ""),
            "task": str(star.get("task") or ""),
            "action": str(star.get("action") or ""),
            "result": str(star.get("result") or ""),
            "learning": str(star.get("learning") or ""),
            "quantified_metrics": str(star.get("quantified_metrics") or ""),
            "extra_context": extra_ctx,
        },
    )

    evaluated = await ainvoke_structured(
        llm,
        StarCheckpointAuditSchema,
        messages,
        max_retries=2,
        caller=f"star_rubric:audit_{bundle['version']}",
    )

    raw_checkpoints: dict[str, dict[str, Any]] = {}
    for cid in STAR_CHECKPOINT_IDS:
        item = getattr(evaluated, cid)
        raw_checkpoints[cid] = item.model_dump()

    # Layer 2: 결정론적 Python 원문 대조 + 코드 하드 캡 + 정수 합산
    star_scores = verify_and_score_checkpoints(
        raw_checkpoints,
        star=star,
        context_text=context_text,
        rubric_version=rubric_version,
    )

    weighted_score = int(star_scores["weighted_score"])
    action_pct = int(star_scores["axes"]["action"]["score"])
    result_pct = int(star_scores["axes"]["result"]["score"])
    is_sufficient = bool(
        weighted_score >= 80
        and action_pct >= 65
        and result_pct >= 55
    )

    missing = [m.strip() for m in (evaluated.missing_points or []) if m and m.strip()][:4]
    if not missing:
        missing = [
            f"[{t['id']}] {t['label']}: {t['tip']}"
            for t in star_scores["priority_targets"][:3]
        ]

    return {
        "completeness_score": weighted_score,
        "is_sufficient": is_sufficient,
        "missing_points": missing,
        "star_scores": star_scores,
    }
