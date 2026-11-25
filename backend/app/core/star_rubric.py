"""객관적 다차원 평가 루브릭 중앙 레지스트리 (Single Source of Truth).

1. 개별 경험 평가: 5축 STAR-L BARS 루브릭
   - 레퍼런스: DDI Targeted Selection (BARS 1~5 행동 기준 척도)
             × Amazon Bar Raiser Rubric ("I" Rule & Action 50% 비중)
             × Google Hiring Rubric (XYZ Formula: [X] as measured by [Y] by doing [Z])
2. 전체 포트폴리오 캐릭터 진단: 6축 육각형 모델 (내적 3축 × 외적 3축)
   - 레퍼런스: Korn Ferry Leadership Architect (KFLA 4대 팩터: Thought / Results / People / Self)
             × Google 4 Hiring Attributes (GCA / RRK / Emergent Leadership / Googleyness)
             × Spencer & Spencer 역량 빙산 모델 (수면 위 역량 vs 수면 아래 성향·동기)
   - 객관성 안전장치: 근거 없는 외적 축은 추측 채점하지 않고 `evidence_status='missing'`(사각지대)으로 정직 표기.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_fast_llm

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. 5축 STAR-L BARS 루브릭 정의
# ==============================================================================
STAR_AXIS_ORDER = ["situation", "task", "action", "result", "learning"]

STAR_AXES: dict[str, dict[str, Any]] = {
    "situation": {
        "id": "situation",
        "code": "S",
        "label": "상황 · 제약 명확성",
        "short_label": "S 상황",
        "weight": 0.15,
        "reference": "DDI Targeted Selection — Context Clarity",
        "description": "프로젝트 배경, 규모, 핵심 병목 및 제약조건이 군더더기 없이 명확한가",
        "bars": {
            "1": "배경이나 문제 정의가 추상적이거나 누락됨",
            "3": "프로젝트 배경과 해결해야 할 문제가 드러남",
            "5": "규모·제약조건·핵심 병목이 2~3문장으로 명료하게 제시됨",
        },
    },
    "task": {
        "id": "task",
        "code": "T",
        "label": "본인 책임 · 오너십",
        "short_label": "T 책임",
        "weight": 0.15,
        "reference": "Amazon Bar Raiser — Ownership ('I' Rule)",
        "description": "팀 목표가 아닌 '내가' 직접 책임진 과제와 성공 기준이 선명하게 분리되어 있는가",
        "bars": {
            "1": "'우리가 했다' 식 서술로 본인 담당 과제 불명확",
            "3": "본인의 담당 영역과 역할이 언급됨",
            "5": "본인이 오너십을 갖고 책임진 목표와 성공 기준이 명확히 분리됨",
        },
    },
    "action": {
        "id": "action",
        "code": "A",
        "label": "행동 구체성 · 의사결정",
        "short_label": "A 행동",
        "weight": 0.35,
        "reference": "Amazon Dive Deep (50% Core) × Google GCA",
        "description": "단순 작업 나열이 아니라 대안 비교, 트레이드오프 근거, 본인만의 문제 해결 논리가 드러나는가",
        "bars": {
            "1": "단순 나열 수준('기능을 개발했다', '기획했다')",
            "3": "구체적 실행 절차와 사용 도구/방법론이 서술됨",
            "5": "대안 비교·트레이드오프·트러블슈팅/조율 의사결정 논리가 선명함",
        },
    },
    "result": {
        "id": "result",
        "code": "R",
        "label": "정량 · 객관적 성과",
        "short_label": "R 성과",
        "weight": 0.25,
        "reference": "Google XYZ Formula ([X] as measured by [Y] by doing [Z])",
        "description": "전/후 비교 수치(Y), 배포·사용자 반응·비용/시간 절감 등 객관적 검증 결과가 있는가",
        "bars": {
            "1": "'잘 마무리했다', '성공적이었다' 등 정성적 느낌만 존재",
            "3": "관찰 가능한 결과물이나 단일 지표가 제시됨",
            "5": "전/후 비교 수치 또는 객관적 외부 검증(배포·사용자·수상·절감)이 명확함",
        },
    },
    "learning": {
        "id": "learning",
        "code": "L",
        "label": "회고 · 확장성",
        "short_label": "L 회고",
        "weight": 0.10,
        "reference": "STAR-L / CARL Framework & Bar Raiser Growth",
        "description": "경험에서 도출한 재발 방지 설계, 일반화한 원칙, 다음 직무 적용점이 드러나는가",
        "bars": {
            "1": "회고나 배운 점 언급 없음",
            "3": "단순 소감이나 느낀 점 수준으로 언급됨",
            "5": "재발 방지 구조·일반화한 업무 원칙·다음 프로젝트 적용점까지 연결됨",
        },
    },
}


# ==============================================================================
# 2. 6축 육각형 포트폴리오 캐릭터 진단 모델 (내적 3축 × 외적 3축)
# ==============================================================================
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
        "domain_label": "내적 역량 (산출물·전문성)",
        "label": "문제해결 깊이",
        "short_label": "문제해결 깊이",
        "reference": "KFLA Thought × Google GCA / RRK",
        "description": "복잡한 문제를 구조화하고 대안 비교·트레이드오프·트러블슈팅을 거쳐 끝까지 해결한 깊이",
    },
    "evidence_impact": {
        "id": "evidence_impact",
        "domain": "internal",
        "domain_label": "내적 역량 (산출물·전문성)",
        "label": "증거력 · 성과 검증",
        "short_label": "증거력·성과",
        "reference": "KFLA Results × Google XYZ Formula",
        "description": "정량 지표, 전후 비교, 코드·문서·배포·수상 등 객관적으로 증명 가능한 산출물의 힘",
    },
    "narrative_coherence": {
        "id": "narrative_coherence",
        "domain": "internal",
        "domain_label": "내적 역량 (산출물·전문성)",
        "label": "서사 일관성 · 시그니처",
        "short_label": "서사 일관성",
        "reference": "Spencer Iceberg (Motives & Self-Image)",
        "description": "여러 프로젝트가 커리어 비전·핵심 신념과 하나의 스토리로 이어지며 고유 시그니처가 드러나는가",
    },
    "time_execution": {
        "id": "time_execution",
        "domain": "external",
        "domain_label": "외적 역량 (운영·협업·태도)",
        "label": "시간 · 일정 · 우선순위 관리",
        "short_label": "시간·우선순위",
        "reference": "KFLA Plans & Aligns × Prioritization",
        "description": "제한된 기간·리소스 안에서 MVP 범위를 절단하고 일정을 준수하며 완결(배포/마감)해낸 운영력",
    },
    "people_collaboration": {
        "id": "people_collaboration",
        "domain": "external",
        "domain_label": "외적 역량 (운영·협업·태도)",
        "label": "인적 · 이해관계자 관리",
        "short_label": "인적·협업관리",
        "reference": "KFLA People × Google Emergent Leadership",
        "description": "팀원·타 직군·외부 파트너와 소통하고 역할 분배, 의견 충돌 조율, 비공식 리더십을 발휘한 역량",
    },
    "adaptability_growth": {
        "id": "adaptability_growth",
        "domain": "external",
        "domain_label": "외적 역량 (운영·협업·태도)",
        "label": "적응력 · 학습 민첩성",
        "short_label": "적응·학습력",
        "reference": "KFLA Self (Manages Ambiguity) × Googleyness",
        "description": "요구사항 변경·실패·장애·모호한 환경에서 피벗하고 회고를 다음 프로젝트 개선으로 연결한 회복탄력성",
    },
}


# ==============================================================================
# 3. 결정론적 점수 계산 및 정규화 헬퍼
# ==============================================================================
def level_to_score(level: int) -> int:
    clamped = max(1, min(5, int(level)))
    return clamped * 20


def compute_weighted_star_score(axes: dict[str, dict[str, Any]]) -> int:
    """5축 STAR-L 점수를 공식 가중치(0.15/0.15/0.35/0.25/0.10)로 결정론적 합산한다."""
    total = 0.0
    for axis_id in STAR_AXIS_ORDER:
        meta = STAR_AXES[axis_id]
        entry = axes.get(axis_id) or {}
        if "score" in entry and entry["score"] is not None:
            sc = max(0, min(100, int(entry["score"])))
        elif "level" in entry and entry["level"] is not None:
            sc = level_to_score(int(entry["level"]))
        else:
            sc = 0
        total += sc * float(meta["weight"])
    return int(round(total))


def normalize_star_scores(raw: dict[str, Any] | None) -> dict[str, Any]:
    """DB에 저장된 star_scores JSONB를 표준 형식으로 정규화한다 (레거시 {} 안전 처리)."""
    if not raw or not isinstance(raw, dict):
        return {}
    raw_axes = raw.get("axes")
    if not isinstance(raw_axes, dict) or not raw_axes:
        return {}

    axes: dict[str, dict[str, Any]] = {}
    for axis_id in STAR_AXIS_ORDER:
        item = raw_axes.get(axis_id) or {}
        lvl = max(1, min(5, int(item.get("level") or max(1, round((item.get("score") or 20) / 20)))))
        sc = max(0, min(100, int(item.get("score") if item.get("score") is not None else lvl * 20)))
        axes[axis_id] = {
            "level": lvl,
            "score": sc,
            "evidence": str(item.get("evidence") or "").strip(),
            "tip": str(item.get("tip") or "").strip(),
        }

    weighted = compute_weighted_star_score(axes)
    return {
        "framework": str(raw.get("framework") or "DDI BARS × Amazon Bar Raiser × Google XYZ"),
        "axes": axes,
        "weighted_score": weighted,
    }


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
                axis_id: {"score": 0, "level": 0} for axis_id in STAR_AXIS_ORDER
            },
        }

    avg_axes: dict[str, dict[str, Any]] = {}
    for axis_id in STAR_AXIS_ORDER:
        mean_sc = round(
            sum(item["axes"][axis_id]["score"] for item in scored) / len(scored)
        )
        avg_axes[axis_id] = {
            "score": int(mean_sc),
            "level": round(mean_sc / 20, 1),
        }

    return {
        "evaluated_count": len(scored),
        "total_count": len(experiences),
        "weighted_score": compute_weighted_star_score(avg_axes),
        "axes": avg_axes,
    }


def compute_portfolio_overall_score(axes: dict[str, dict[str, Any]]) -> dict[str, int]:
    """6축 포트폴리오 점수의 전체·내적·외적 평균을 결정론적으로 산출한다."""
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


def get_rubric_reference_payload() -> dict[str, Any]:
    """프론트엔드 평가 기준 레퍼런스 모달 및 그래프 렌더링용 메타데이터."""
    return {
        "star_rubric": {
            "name": "5축 STAR-L BARS 루브릭",
            "frameworks": [
                {
                    "name": "DDI Targeted Selection (BARS)",
                    "role": "STAR 원조 기관의 Level 1~5 행동 기준 평가 척도",
                },
                {
                    "name": "Amazon Bar Raiser Rubric",
                    "role": "'우리가' 아닌 '내가' 한 Action(35%) + Ownership(15%) 중시 원칙",
                },
                {
                    "name": "Google XYZ Formula & GCA",
                    "role": "Accomplished [X] as measured by [Y] by doing [Z] 정량 검증 & 문제 분해 논리",
                },
            ],
            "formula": "종합 점수 = 0.15×S + 0.15×T + 0.35×A + 0.25×R + 0.10×L",
            "axes": [STAR_AXES[k] for k in STAR_AXIS_ORDER],
        },
        "portfolio_rubric": {
            "name": "6축 포트폴리오 캐릭터 진단 (내적 3 × 외적 3)",
            "frameworks": [
                {
                    "name": "Korn Ferry Leadership Architect (KFLA)",
                    "role": "Thought · Results · People · Self 4대 역량 팩터 (일정·우선순위·협업·적응 포함)",
                },
                {
                    "name": "Google 4 Hiring Attributes",
                    "role": "GCA · RRK · Emergent Leadership(비공식 리더십) · Googleyness",
                },
                {
                    "name": "Spencer 역량 빙산 모델",
                    "role": "수면 위 산출물(내적)과 수면 아래 운영·협업·회복탄력성(외적) 동시 평가",
                },
            ],
            "honesty_rule": "포트폴리오와 보충 메모에 근거가 없는 외적 축은 추측 채점하지 않고 '근거 부족(사각지대)'으로 표기합니다.",
            "axes": [PORTFOLIO_AXES[k] for k in PORTFOLIO_AXIS_ORDER],
        },
    }


# ==============================================================================
# 4. Structured Output 기반 5축 STAR-L 채점 실행기
# ==============================================================================
class AxisEvaluationItem(BaseModel):
    level: int = Field(ge=1, le=5, description="BARS 1~5 행동 등급")
    score: int = Field(ge=0, le=100, description="0~100 환산 점수 (level*20 기준 ±10 미세조정 가능)")
    evidence: str = Field(default="", description="해당 점수를 부여한 근거 (실제 기록 인용 1문장)")
    tip: str = Field(default="", description="다음 등급으로 올리기 위한 1줄 구체 보완 팁")


class StarRubricEvaluationSchema(BaseModel):
    situation: AxisEvaluationItem
    task: AxisEvaluationItem
    action: AxisEvaluationItem
    result: AxisEvaluationItem
    learning: AxisEvaluationItem
    is_sufficient: bool = Field(
        default=False,
        description="종합 80점 이상이고 Action·Result에 치명적 빈틈이 없을 때만 true",
    )
    missing_points: list[str] = Field(
        default_factory=list,
        description="가장 우선 보완해야 할 구체 빈틈 1~4개",
    )


async def evaluate_star_experience_rubric(
    star: dict[str, Any],
    *,
    context_text: str = "",
) -> dict[str, Any]:
    """단일 STAR 경험을 DDI BARS × Amazon Bar Raiser × Google XYZ 5축 기준으로 객관 채점한다."""
    llm = get_fast_llm(temperature=0.1, max_tokens=2048)

    rubric_lines = []
    for axis_id in STAR_AXIS_ORDER:
        m = STAR_AXES[axis_id]
        rubric_lines.append(
            f"- {axis_id} ({m['label']}, 가중치 {int(m['weight']*100)}%, 기준: {m['reference']}): "
            f"Lv1={m['bars']['1']} / Lv3={m['bars']['3']} / Lv5={m['bars']['5']}"
        )

    system_prompt = (
        "당신은 DDI BARS, Amazon Bar Raiser, Google XYZ 기준을 적용하는 객관적 커리어 면접 평가관입니다.\n"
        "아래 5축 행동 기준 척도(Level 1~5)에 따라 지원자의 STAR 기록을 엄정하게 채점하세요.\n\n"
        + "\n".join(rubric_lines)
        + "\n\n엄격한 채점 규칙:\n"
        "1. 기록에 없는 수치·성과·대안 비교를 긍정 추측하지 마세요. 정량 근거가 없으면 result는 최대 Level 3(60점) 이하로 채점합니다.\n"
        "2. '우리가 했다' 식 서술로 본인 기여가 모호하면 task/action을 낮게 채점하세요.\n"
        "3. evidence에는 실제 기록에서 확인된 사실(또는 결여된 점)을 1문장으로 쓰고, tip에는 구체적 개선 액션을 1문장으로 쓰세요.\n"
        "4. 종합 가중 점수가 80점 이상이고 action·result에 치명적 공백이 없을 때만 is_sufficient=true로 설정하세요."
    )

    user_prompt = (
        f"[평가 대상 STAR]\n"
        f"- 제목: {star.get('title', '')}\n"
        f"- Situation: {star.get('situation', '')}\n"
        f"- Task: {star.get('task', '')}\n"
        f"- Action: {star.get('action', '')}\n"
        f"- Result: {star.get('result', '')}\n"
        f"- 정량 지표: {star.get('quantified_metrics', '')}\n"
    )
    if context_text.strip():
        user_prompt += f"\n[추가 맥락/원본 메모]\n{context_text[:6000]}"

    evaluated = await ainvoke_structured(
        llm,
        StarRubricEvaluationSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
    )

    axes = {
        axis_id: getattr(evaluated, axis_id).model_dump()
        for axis_id in STAR_AXIS_ORDER
    }
    weighted_score = compute_weighted_star_score(axes)
    star_scores = {
        "framework": "DDI BARS × Amazon Bar Raiser × Google XYZ",
        "axes": axes,
        "weighted_score": weighted_score,
    }
    is_sufficient = bool(evaluated.is_sufficient and weighted_score >= 80)
    return {
        "completeness_score": weighted_score,
        "is_sufficient": is_sufficient,
        "missing_points": [m.strip() for m in evaluated.missing_points if m.strip()][:5],
        "star_scores": star_scores,
    }
