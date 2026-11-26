"""나의 신념 카드(인간·사회·인문학적 커리어 가치관) & 책/강의 구절·일상 회고 저널 API 라우터."""

from __future__ import annotations

from datetime import datetime
import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.bedrock import ainvoke_structured, get_smart_llm
from app.core.database import (
    BeliefNote,
    BeliefPillar,
    Experience,
    Project,
    UserProfile,
    get_db_session,
)
from app.core.vector_store import DocType, delete_document, try_upsert_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/beliefs", tags=["beliefs"])

SOURCE_TYPE_LABELS = {
    "book": "책 / 독서 구절",
    "lecture": "강의 / 세미나",
    "article": "아티클 / 영상",
    "thought": "일상 생각 / 회고",
}

PILLAR_CATEGORY_LABELS = {
    "human_value": "인간 · 인문학 가치",
    "social_impact": "사회적 문제의식",
    "career_calling": "커리어 지향 · 하고 싶은 일",
    "tech_and_people": "기술과 사람의 관계",
    # 레거시 하위 호환 라벨
    "work_principle": "커리어 지향 · 하고 싶은 일",
    "problem_lens": "사회적 문제의식",
    "collaboration": "인간 · 인문학 가치",
    "career_direction": "커리어 지향 · 하고 싶은 일",
}

ALLOWED_PILLAR_CATEGORIES = Literal[
    "human_value",
    "social_impact",
    "career_calling",
    "tech_and_people",
    "work_principle",
    "problem_lens",
    "collaboration",
    "career_direction",
]

_BELIEF_CLICHE_PATTERNS = (
    "끊임없이 성장",
    "열정적인",
    "최선을 다하",
    "도전정신",
    "책임감을 가지",
    "더 나은 세상",
    "혁신적인 가치",
    "글로벌 인재",
)

_DIRECTION_SIGNAL_RE = re.compile(
    r"(사람|인간|사회|공동체|격차|주체|존엄|관계|연결|신뢰|기회|삶|경험|감정|공감|소외|접근성|"
    r"보다|대신|지키|바꾸|돕|해결|위해|하고\s*싶|만들고\s*싶|기여|지향|본질|의미|가치|포기|않는다|안\s*한다)",
    re.IGNORECASE,
)


def evaluate_belief_pillar_quality(
    *,
    title: str,
    tradeoff_rule: str = "",
    origin_story: str = "",
    linked_project_ids: list[int] | None = None,
    linked_experience_ids: list[int] | None = None,
    linked_note_ids: list[int] | None = None,
) -> dict[str, Any]:
    """신념 카드의 선명도(인간·사회적 지향성 · 클리셰 여부 · 계기/실천 경험 연결)를 결정론적으로 진단한다."""
    title_clean = (title or "").strip()
    direction_clean = (tradeoff_rule or "").strip()
    origin_clean = (origin_story or "").strip()
    combined = f"{title_clean} {direction_clean} {origin_clean}"

    cliche_hits = [c for c in _BELIEF_CLICHE_PATTERNS if c in combined]
    has_direction = len(direction_clean) >= 12 or bool(
        _DIRECTION_SIGNAL_RE.search(title_clean + " " + direction_clean)
    )
    has_origin = len(origin_clean) >= 12 or len(linked_note_ids or []) > 0
    action_proof_count = len(linked_project_ids or []) + len(linked_experience_ids or [])
    note_count = len(linked_note_ids or [])
    proof_count = action_proof_count + note_count
    has_action_proof = action_proof_count > 0

    score = 0
    if len(title_clean) >= 10:
        score += 20
    if has_direction:
        score += 30
    if has_origin:
        score += 20
    if has_action_proof:
        score += min(30, 22 + (action_proof_count - 1) * 4)
    elif note_count > 0:
        score += 15
    if cliche_hits and not has_direction:
        score = max(10, score - 20)
    score = max(0, min(100, score))

    if cliche_hits and not has_direction:
        proof_status = "cliche_risk"
        tip = (
            f"추상 표현({', '.join(cliche_hits[:2])})이 포함되어 있습니다. "
            "'어떤 사람·사회 문제에 주목하며 어떤 변화를 만들고 싶은지' 구체적인 지향으로 다듬어 보세요."
        )
    elif not has_direction:
        proof_status = "needs_direction"
        tip = "이 신념을 통해 커리어에서 이루고 싶은 방향이나 포기하지 않는 기준을 한 줄 덧붙이면 훨씬 선명해집니다."
    elif not has_action_proof:
        proof_status = "needs_proof"
        tip = (
            "사유·가치관은 선명합니다. 이 신념을 탐구하거나 실천해 본 프로젝트·경험을 연결하면 자소서·면접 설득력이 크게 올라갑니다."
        )
    else:
        proof_status = "proven"
        tip = "인간·사회적 지향과 실제 실천 경험이 함께 연결된 나만의 핵심 신념입니다."

    return {
        "proof_status": proof_status,
        "strength_score": score,
        "cliche_hits": cliche_hits,
        "diagnostic_tip": tip,
        "proof_count": proof_count,
    }


def _clean_int_ids(ids: list[Any] | None) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw in ids or []:
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val > 0 and val not in seen:
            seen.add(val)
            out.append(val)
    return out


# ==============================================================================
# 1. 핵심 신념 카드 (인간·사회·인문학적 커리어 가치관) CRUD + AI 발굴/다듬기
# ==============================================================================
class BeliefPillarCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=300, description="나의 신념 한 줄 선언")
    category: ALLOWED_PILLAR_CATEGORIES = Field(default="human_value")
    tradeoff_rule: str = Field(
        default="", description="커리어에서 이루고 싶은 방향 / 포기하지 않는 가치 기준"
    )
    origin_story: str = Field(default="", description="이 신념이 생긴 계기 · 영향을 준 책/경험")
    linked_project_ids: list[int] = Field(default_factory=list)
    linked_experience_ids: list[int] = Field(default_factory=list)
    linked_note_ids: list[int] = Field(default_factory=list)


class BeliefPillarUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    category: ALLOWED_PILLAR_CATEGORIES | None = None
    tradeoff_rule: str | None = None
    origin_story: str | None = None
    linked_project_ids: list[int] | None = None
    linked_experience_ids: list[int] | None = None
    linked_note_ids: list[int] | None = None


class BeliefPillarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    tradeoff_rule: str = ""
    origin_story: str = ""
    linked_project_ids: list[int] = Field(default_factory=list)
    linked_experience_ids: list[int] = Field(default_factory=list)
    linked_note_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    proof_status: str = "needs_proof"
    strength_score: int = 0
    cliche_hits: list[str] = Field(default_factory=list)
    diagnostic_tip: str = ""
    proof_count: int = 0
    vector_synced: bool | None = None


class BeliefPillarSharpenRequest(BaseModel):
    context_hint: str = Field(
        default="", description="이 신념을 품게 된 계기나 관심 있는 사람·사회 문제 한 줄 힌트 (선택)"
    )


class SharpenedPillarSchema(BaseModel):
    sharpened_title: str = Field(
        description="업무 방식이 아니라 인간·사회·인문학적 관점과 커리어에서 이루고 싶은 가치가 또렷이 드러나는 한 줄 신념 선언"
    )
    sharpened_tradeoff_rule: str = Field(
        description="커리어를 통해 어떤 사람·사회적 변화를 만들고 싶으며 무엇을 타협하지 않는지 구체적 지향 (1~2문장)"
    )
    sharpened_origin_story: str = Field(
        description="기존 계기·독서/회고·프로젝트 맥락을 살려 다듬은 형성 스토리 (1~2문장)"
    )
    why_better: str = Field(description="기존 문장 대비 인간적 진정성과 차별성이 왜 높아졌는지 1문장")


class DiscoveredPillarCandidate(BaseModel):
    title: str = Field(
        description="업무 습관이 아니라, 인간·사회·인문학적 관점 및 커리어에서 이루고 싶은 방향을 담은 한 줄 신념 선언"
    )
    category: Literal[
        "human_value", "social_impact", "career_calling", "tech_and_people"
    ] = Field(default="human_value")
    tradeoff_rule: str = Field(
        description="커리어에서 어떤 사람·사회적 가치를 실현하고 싶고 무엇을 포기하지 않는지 (1~2문장)"
    )
    origin_story: str = Field(
        description="어떤 독서·회고·프로젝트 문제의식에서 이 신념이 드러났는지 근거 요약 (1~2문장)"
    )
    linked_project_ids: list[int] = Field(
        default_factory=list, description="이 신념을 탐구·실천한 등록 프로젝트 ID 목록"
    )
    linked_experience_ids: list[int] = Field(
        default_factory=list, description="이 신념과 맞닿은 등록 STAR 경험 ID 목록"
    )
    linked_note_ids: list[int] = Field(
        default_factory=list, description="이 신념이 담긴 일상 회고·독서 노트 ID 목록"
    )
    evidence_summary: str = Field(description="자소서·지원동기에서 이 신념을 어떻게 풀어낼 수 있는지 1문장")


class PortfolioBeliefDiscoverySchema(BaseModel):
    overall_observation: str = Field(
        description="지원자의 회고 노트와 프로젝트 문제의식 전반을 관통하는 인간적·사회적 관심사와 커리어 지향 요약 (2문장)"
    )
    candidates: list[DiscoveredPillarCandidate] = Field(
        default_factory=list, description="인간·사회·커리어 지향 기반 핵심 신념 카드 후보 3~4개"
    )


def _serialize_pillar(pillar: BeliefPillar, *, vector_synced: bool | None = None) -> BeliefPillarResponse:
    qual = evaluate_belief_pillar_quality(
        title=pillar.title,
        tradeoff_rule=pillar.tradeoff_rule,
        origin_story=pillar.origin_story,
        linked_project_ids=list(pillar.linked_project_ids or []),
        linked_experience_ids=list(pillar.linked_experience_ids or []),
        linked_note_ids=list(pillar.linked_note_ids or []),
    )
    resp = BeliefPillarResponse.model_validate(pillar)
    resp.proof_status = qual["proof_status"]
    resp.strength_score = qual["strength_score"]
    resp.cliche_hits = qual["cliche_hits"]
    resp.diagnostic_tip = qual["diagnostic_tip"]
    resp.proof_count = qual["proof_count"]
    resp.vector_synced = vector_synced
    return resp


async def _sync_belief_pillar_vector(session: AsyncSession, pillar: BeliefPillar) -> bool:
    cat_label = PILLAR_CATEGORY_LABELS.get(pillar.category, pillar.category)
    parts = [f"[핵심 신념 카드 | {cat_label}] {pillar.title}"]
    if pillar.tradeoff_rule.strip():
        parts.append(f"[커리어 지향 · 지키는 가치] {pillar.tradeoff_rule.strip()}")
    if pillar.origin_story.strip():
        parts.append(f"[형성 계기 · 사유] {pillar.origin_story.strip()}")
    content = "\n".join(parts)
    return await try_upsert_document(
        session,
        doc_type=DocType.CAREER_IDENTITY,
        ref_id=f"belief-pillar-{pillar.id}",
        content=content,
        metadata={
            "belief_pillar_id": pillar.id,
            "category": pillar.category,
            "title": pillar.title,
            "linked_project_ids": list(pillar.linked_project_ids or []),
            "linked_experience_ids": list(pillar.linked_experience_ids or []),
        },
    )


async def _auto_sync_pillars_to_profile(session: AsyncSession) -> None:
    """BeliefPillar 변경 시 UserProfile.core_beliefs 요약을 자동 동기화해 단일 진실 공급원(SSOT)을 유지한다."""
    pillars = (
        (await session.execute(select(BeliefPillar).order_by(BeliefPillar.id.asc())))
        .scalars()
        .all()
    )
    profile = await session.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1)
        session.add(profile)
    lines = []
    for idx, p in enumerate(pillars, start=1):
        cat = PILLAR_CATEGORY_LABELS.get(p.category, p.category)
        line = f"{idx}. [{cat}] {p.title}"
        if p.tradeoff_rule.strip():
            line += f" — {p.tradeoff_rule.strip()}"
        lines.append(line)
    profile.core_beliefs = "\n".join(lines)
    await session.commit()


@router.get("/pillars", response_model=list[BeliefPillarResponse])
async def list_belief_pillars(
    session: AsyncSession = Depends(get_db_session),
) -> list[BeliefPillarResponse]:
    stmt = select(BeliefPillar).order_by(BeliefPillar.created_at.desc(), BeliefPillar.id.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize_pillar(r) for r in rows]


@router.post(
    "/pillars", response_model=BeliefPillarResponse, status_code=status.HTTP_201_CREATED
)
async def create_belief_pillar(
    payload: BeliefPillarCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> BeliefPillarResponse:
    pillar = BeliefPillar(
        title=payload.title.strip(),
        category=payload.category,
        tradeoff_rule=payload.tradeoff_rule.strip(),
        origin_story=payload.origin_story.strip(),
        linked_project_ids=_clean_int_ids(payload.linked_project_ids),
        linked_experience_ids=_clean_int_ids(payload.linked_experience_ids),
        linked_note_ids=_clean_int_ids(payload.linked_note_ids),
    )
    session.add(pillar)
    await session.commit()
    await session.refresh(pillar)
    await _auto_sync_pillars_to_profile(session)
    synced = await _sync_belief_pillar_vector(session, pillar)
    return _serialize_pillar(pillar, vector_synced=synced)


@router.put("/pillars/{pillar_id}", response_model=BeliefPillarResponse)
async def update_belief_pillar(
    pillar_id: int,
    payload: BeliefPillarUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> BeliefPillarResponse:
    pillar = await session.get(BeliefPillar, pillar_id)
    if pillar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Belief pillar {pillar_id} not found.",
        )

    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        pillar.title = data["title"].strip()
    if "category" in data and data["category"] is not None:
        pillar.category = data["category"]
    if "tradeoff_rule" in data and data["tradeoff_rule"] is not None:
        pillar.tradeoff_rule = data["tradeoff_rule"].strip()
    if "origin_story" in data and data["origin_story"] is not None:
        pillar.origin_story = data["origin_story"].strip()
    if "linked_project_ids" in data and data["linked_project_ids"] is not None:
        pillar.linked_project_ids = _clean_int_ids(data["linked_project_ids"])
    if "linked_experience_ids" in data and data["linked_experience_ids"] is not None:
        pillar.linked_experience_ids = _clean_int_ids(data["linked_experience_ids"])
    if "linked_note_ids" in data and data["linked_note_ids"] is not None:
        pillar.linked_note_ids = _clean_int_ids(data["linked_note_ids"])

    await session.commit()
    await session.refresh(pillar)
    await _auto_sync_pillars_to_profile(session)
    synced = await _sync_belief_pillar_vector(session, pillar)
    return _serialize_pillar(pillar, vector_synced=synced)


@router.delete("/pillars/{pillar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_belief_pillar(
    pillar_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    pillar = await session.get(BeliefPillar, pillar_id)
    if pillar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Belief pillar {pillar_id} not found.",
        )
    await session.delete(pillar)
    await session.commit()
    await _auto_sync_pillars_to_profile(session)
    await delete_document(
        session, doc_type=DocType.CAREER_IDENTITY, ref_id=f"belief-pillar-{pillar_id}"
    )


@router.post("/pillars/{pillar_id}/sharpen")
async def sharpen_belief_pillar(
    pillar_id: int,
    payload: BeliefPillarSharpenRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """추상적인 신념 문장을 AI 시대에 사람·사회·인문학적 관점과 커리어 지향이 또렷이 드러나는 문장으로 다듬는다."""
    pillar = await session.get(BeliefPillar, pillar_id)
    if pillar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Belief pillar {pillar_id} not found.",
        )

    linked_projs: list[Project] = []
    if pillar.linked_project_ids:
        linked_projs = (
            (
                await session.execute(
                    select(Project).where(Project.id.in_(pillar.linked_project_ids))
                )
            )
            .scalars()
            .all()
        )
    linked_exps: list[Experience] = []
    if pillar.linked_experience_ids:
        linked_exps = (
            (
                await session.execute(
                    select(Experience).where(Experience.id.in_(pillar.linked_experience_ids))
                )
            )
            .scalars()
            .all()
        )

    proof_dump = "\n".join(
        [f"- [프로젝트] {p.name}: {p.summary[:220]}" for p in linked_projs]
        + [
            f"- [경험] {e.title}: Situation={(e.situation or '')[:140]} | Learning={(e.learning or '')[:160]}"
            for e in linked_exps
        ]
    ) or "(연결된 프로젝트·경험 없음)"

    system_prompt = (
        "당신은 AI 시대의 인문학적·사회적 커리어 철학을 다듬는 에디터입니다.\n"
        "중요: '어떻게 일할 것인가(코드 품질, 빠른 배포, 테스트 습관)' 같은 업무 프로세스 신념으로 바꾸지 마세요!\n"
        "지원자가 커리어를 통해 **어떤 사람·사회적 문제에 기여하고 싶은지, 인간에게 지켜야 할 본질적 가치는 무엇인지, 기술과 사람이 어떤 관계여야 하는지**가 "
        "뻔한 클리셰 없이 진정성 있고 선명하게 드러나도록 다듬어 주세요.\n"
        "규칙: 제공된 기록과 힌트에 없는 사실이나 수치는 절대 지어내지 마세요."
    )
    user_prompt = (
        f"[현재 신념 카드]\n"
        f"- 카테고리: {PILLAR_CATEGORY_LABELS.get(pillar.category, pillar.category)}\n"
        f"- 선언문: {pillar.title}\n"
        f"- 커리어 지향 / 지키는 가치: {pillar.tradeoff_rule or '(미입력)'}\n"
        f"- 형성 계기: {pillar.origin_story or '(미입력)'}\n\n"
        f"[연결된 프로젝트·경험]\n{proof_dump}\n\n"
        f"[사용자 추가 힌트]\n{payload.context_hint.strip() or '(없음)'}"
    )

    try:
        llm = get_smart_llm(temperature=0.35, max_tokens=1800)
        res = await ainvoke_structured(
            llm,
            SharpenedPillarSchema,
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            max_retries=2,
            caller="beliefs:sharpen_pillar",
        )
        return res.model_dump()
    except Exception as exc:
        logger.exception("Sharpen belief pillar %s failed: %s", pillar_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"신념 다듬기 생성 실패: {exc}",
        )


@router.post("/discover-from-portfolio")
async def discover_beliefs_from_portfolio(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """일상 회고·독서 노트와 프로젝트의 문제의식에서 인간·사회·인문학적 커리어 신념 후보 3~4개를 역추출한다."""
    profile = await session.get(UserProfile, 1)
    notes = (
        (
            await session.execute(
                select(BeliefNote).order_by(BeliefNote.created_at.desc()).limit(20)
            )
        )
        .scalars()
        .all()
    )
    projects = (
        (
            await session.execute(
                select(Project)
                .options(selectinload(Project.sections))
                .order_by(Project.created_at.desc(), Project.id.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    experiences = (
        (
            await session.execute(
                select(Experience)
                .order_by(Experience.completeness_score.desc(), Experience.created_at.desc())
                .limit(12)
            )
        )
        .scalars()
        .all()
    )
    existing_pillars = (
        (await session.execute(select(BeliefPillar).order_by(BeliefPillar.id.asc())))
        .scalars()
        .all()
    )

    if not projects and not experiences and not notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="신념을 발굴할 회고 노트, 프로젝트, 또는 경험이 아직 없습니다. 하나 이상 기록한 뒤 시도해 주세요.",
        )

    note_blocks = [
        f"- [note_id={n.id}] [{SOURCE_TYPE_LABELS.get(n.source_type, n.source_type)}] {n.source_title or '무제'}\n"
        f"  구절: {(n.quote_text or '')[:160]} | 생각: {n.my_reflection[:260]}"
        for n in notes
    ]
    proj_blocks = []
    for p in projects:
        sec_preview = " / ".join(
            f"[{s.title}] {(s.content or '').strip()[:150]}"
            for s in p.sections
            if (s.content or "").strip()
        )[:450]
        proj_blocks.append(
            f"- [project_id={p.id}] {p.name} | 문제의식·요약: {p.summary[:240]} | 목표 연결: {p.portfolio_goal_link[:160]}\n"
            f"  발췌: {sec_preview or '(없음)'}"
        )
    exp_blocks = [
        f"- [experience_id={e.id}, project_id={e.project_id}] {e.title}\n"
        f"  Situation: {(e.situation or '')[:140]} | Learning: {(e.learning or '')[:200]}"
        for e in experiences
    ]
    existing_dump = "\n".join(f"- {ep.title}" for ep in existing_pillars) or "(없음)"

    system_prompt = (
        "당신은 AI 시대의 인문학적·사회적 커리어 철학 파트너입니다.\n"
        "지원자의 **일상 회고·독서/강의 노트(최우선 근거)**와 프로젝트·경험에서 드러나는 **'왜 이 문제를 풀려 했는가(Why)'**를 분석해, "
        "**인간·사회·인문학적 가치와 커리어에서 궁극적으로 이루고 싶은 방향을 담은 핵심 신념 카드 3~4개**를 발굴하세요.\n\n"
        "핵심 규칙 (필수 준수):\n"
        "1. **업무 방식/개발 방법론 신념 절대 금지!** ('테스트를 먼저 작성한다', '빠르게 배포하고 측정한다', '성능을 최적화한다' 같은 How-to-work 원칙이 아니라, "
        "**'사람에게 어떤 의미가 있어야 하는가', '사회·산업의 어떤 문제를 바꾸고 싶은가', 'AI 시대에 기술이 인간을 어떻게 도와야 하는가', '커리어를 통해 어떤 일을 하고 싶은가'**를 추출하세요!)\n"
        "2. '열정적인', '끊임없이 성장하는', '더 나은 세상' 같은 뻔한 구호 대신 지원자 기록에서 우러나온 고유한 관점을 쓰세요.\n"
        "3. `category`는 반드시 `human_value`, `social_impact`, `career_calling`, `tech_and_people` 중 하나를 고르세요.\n"
        "4. `linked_note_ids`, `linked_project_ids`, `linked_experience_ids`에는 아래 목록에 실존하는 정수 ID만 넣으세요.\n"
        "5. 이미 등록된 신념 카드와 겹치지 않는 새로운 관점을 제안하세요."
    )
    user_prompt = (
        f"[현재 프로필]\n"
        f"비전: {profile.career_vision if profile else '(미설정)'}\n"
        f"희망 직무: {profile.target_roles if profile else '(미설정)'}\n\n"
        f"[이미 등록된 신념 카드 (중복 방지)]\n{existing_dump}\n\n"
        f"[1순위 근거: 일상 회고 · 독서/강의 저널 ({len(notes)}건)]\n" + ("\n".join(note_blocks)[:5000] or "(없음)") + "\n\n"
        f"[2순위 근거: 보유 프로젝트의 문제의식 ({len(projects)}건)]\n" + ("\n".join(proj_blocks)[:4500] or "(없음)") + "\n\n"
        f"[3순위 근거: STAR-L 경험 속 문제의식과 회고 ({len(experiences)}건)]\n" + ("\n".join(exp_blocks)[:3000] or "(없음)")
    )

    try:
        llm = get_smart_llm(temperature=0.35, max_tokens=3200)
        discovered = await ainvoke_structured(
            llm,
            PortfolioBeliefDiscoverySchema,
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            max_retries=2,
            caller="beliefs:discover_from_portfolio",
        )
    except Exception as exc:
        logger.exception("Discover beliefs from portfolio failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"신념 역추출 실패: {exc}",
        )

    valid_proj_ids = {p.id for p in projects}
    valid_exp_ids = {e.id for e in experiences}
    valid_note_ids = {n.id for n in notes}

    cleaned_candidates: list[dict[str, Any]] = []
    for cand in (discovered.candidates or [])[:4]:
        d = cand.model_dump()
        d["linked_project_ids"] = [pid for pid in _clean_int_ids(d.get("linked_project_ids")) if pid in valid_proj_ids]
        d["linked_experience_ids"] = [eid for eid in _clean_int_ids(d.get("linked_experience_ids")) if eid in valid_exp_ids]
        d["linked_note_ids"] = [nid for nid in _clean_int_ids(d.get("linked_note_ids")) if nid in valid_note_ids]
        qual = evaluate_belief_pillar_quality(
            title=d["title"],
            tradeoff_rule=d["tradeoff_rule"],
            origin_story=d["origin_story"],
            linked_project_ids=d["linked_project_ids"],
            linked_experience_ids=d["linked_experience_ids"],
            linked_note_ids=d["linked_note_ids"],
        )
        d.update(qual)
        cleaned_candidates.append(d)

    return {
        "overall_observation": discovered.overall_observation.strip(),
        "candidates": cleaned_candidates,
        "source_counts": {
            "projects": len(projects),
            "experiences": len(experiences),
            "notes": len(notes),
        },
    }


@router.post("/pillars/sync-to-profile")
async def sync_pillars_to_profile(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """등록된 핵심 신념 카드들을 UserProfile.core_beliefs 요약 텍스트와 career_identity 벡터에 동기화한다."""
    pillars = (
        (await session.execute(select(BeliefPillar).order_by(BeliefPillar.id.asc())))
        .scalars()
        .all()
    )
    if not pillars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="동기화할 신념 카드가 아직 없습니다.",
        )

    await _auto_sync_pillars_to_profile(session)
    profile = await session.get(UserProfile, 1)
    identity_text = "\n\n".join(
        part
        for part in [
            f"희망 직무: {profile.target_roles}" if profile and profile.target_roles else "",
            f"커리어 비전: {profile.career_vision}" if profile and profile.career_vision else "",
            f"핵심 신념 및 철학:\n{profile.core_beliefs}" if profile and profile.core_beliefs else "",
            f"선호 문체: {profile.preferred_tone}" if profile and profile.preferred_tone else "",
        ]
        if part
    )
    synced = await try_upsert_document(
        session,
        doc_type=DocType.CAREER_IDENTITY,
        ref_id="profile-1",
        content=identity_text,
        metadata={"target_roles": profile.target_roles if profile else "", "pillar_count": len(pillars)},
    )
    return {
        "core_beliefs": profile.core_beliefs if profile else "",
        "pillar_count": len(pillars),
        "vector_synced": synced,
    }


# ==============================================================================
# 2. 일상 회고 · 책/강의 구절 저널 (Belief Notes) 스키마 & CRUD
# ==============================================================================
class BeliefNoteCreateRequest(BaseModel):
    source_type: Literal["book", "lecture", "article", "thought"] = Field(
        default="thought", description="출처 유형"
    )
    source_title: str = Field(
        default="", max_length=300, description="책 제목/저자, 강의명, 또는 생각 주제"
    )
    quote_text: str = Field(default="", description="인상 깊은 구절 원문 (선택)")
    my_reflection: str = Field(..., min_length=2, description="나의 생각 및 회고")
    tags: list[str] = Field(default_factory=list, description="주제 태그 목록")


class BeliefNoteUpdateRequest(BaseModel):
    source_type: Literal["book", "lecture", "article", "thought"] | None = None
    source_title: str | None = Field(default=None, max_length=300)
    quote_text: str | None = None
    my_reflection: str | None = Field(default=None, min_length=2)
    tags: list[str] | None = None


class BeliefNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    source_title: str
    quote_text: str
    my_reflection: str
    tags: list[str] = Field(default_factory=list)
    ai_reflection: str = ""
    created_at: datetime
    updated_at: datetime
    vector_synced: bool | None = None


class IdentitySynthesisSchema(BaseModel):
    suggested_career_vision: str = Field(
        description="축적된 신념 카드·독서/회고 노트를 통합해 AI 시대에 어떤 인간적·사회적 가치를 만드는 커리어를 지향하는지 정리한 커리어 비전 (2~3문장)"
    )
    suggested_core_beliefs: str = Field(
        description="반복되는 인문학적·사회적 문제의식과 커리어 지향을 응축한 핵심 신념 요약 (3~4문장)"
    )
    key_themes: list[str] = Field(
        default_factory=list, description="노트 전반을 관통하는 핵심 가치관 키워드 3~5개"
    )
    synthesis_rationale: str = Field(
        description="어떤 노트와 신념에서 이 방향이 도출되었는지 설명 (2문장)"
    )


async def _sync_belief_note_vector(session: AsyncSession, note: BeliefNote) -> bool:
    label = SOURCE_TYPE_LABELS.get(note.source_type, note.source_type)
    parts = [f"[신념·생각 노트 | {label}] {note.source_title or '무제'}"]
    if note.tags:
        parts.append(f"[키워드] {', '.join(note.tags)}")
    if note.quote_text.strip():
        parts.append(f"[인상 깊은 구절] {note.quote_text.strip()}")
    if note.my_reflection.strip():
        parts.append(f"[나의 생각·회고] {note.my_reflection.strip()}")
    content = "\n".join(parts)
    return await try_upsert_document(
        session,
        doc_type=DocType.CAREER_IDENTITY,
        ref_id=f"belief-note-{note.id}",
        content=content,
        metadata={
            "belief_note_id": note.id,
            "source_type": note.source_type,
            "source_title": note.source_title,
            "tags": list(note.tags or []),
        },
    )


@router.get("/notes", response_model=list[BeliefNoteResponse])
async def list_belief_notes(
    source_type: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[BeliefNoteResponse]:
    stmt = select(BeliefNote).order_by(BeliefNote.created_at.desc(), BeliefNote.id.desc())
    if source_type and source_type in SOURCE_TYPE_LABELS:
        stmt = stmt.where(BeliefNote.source_type == source_type)
    rows = (await session.execute(stmt)).scalars().all()
    return [BeliefNoteResponse.model_validate(r) for r in rows]


@router.post(
    "/notes", response_model=BeliefNoteResponse, status_code=status.HTTP_201_CREATED
)
async def create_belief_note(
    payload: BeliefNoteCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> BeliefNoteResponse:
    clean_tags = [t.strip().lstrip("#") for t in payload.tags if t.strip()][:8]
    note = BeliefNote(
        source_type=payload.source_type,
        source_title=payload.source_title.strip(),
        quote_text=payload.quote_text.strip(),
        my_reflection=payload.my_reflection.strip(),
        tags=clean_tags,
        ai_reflection="",
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)

    resp = BeliefNoteResponse.model_validate(note)
    resp.vector_synced = await _sync_belief_note_vector(session, note)
    return resp


@router.put("/notes/{note_id}", response_model=BeliefNoteResponse)
async def update_belief_note(
    note_id: int,
    payload: BeliefNoteUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> BeliefNoteResponse:
    note = await session.get(BeliefNote, note_id)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Belief note {note_id} not found.",
        )

    data = payload.model_dump(exclude_unset=True)
    if "source_type" in data and data["source_type"] is not None:
        note.source_type = data["source_type"]
    if "source_title" in data and data["source_title"] is not None:
        note.source_title = data["source_title"].strip()
    if "quote_text" in data and data["quote_text"] is not None:
        note.quote_text = data["quote_text"].strip()
    if "my_reflection" in data and data["my_reflection"] is not None:
        note.my_reflection = data["my_reflection"].strip()
    if "tags" in data and data["tags"] is not None:
        note.tags = [t.strip().lstrip("#") for t in data["tags"] if t.strip()][:8]

    await session.commit()
    await session.refresh(note)

    resp = BeliefNoteResponse.model_validate(note)
    resp.vector_synced = await _sync_belief_note_vector(session, note)
    return resp


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_belief_note(
    note_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    note = await session.get(BeliefNote, note_id)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Belief note {note_id} not found.",
        )
    await session.delete(note)
    await session.commit()
    await delete_document(
        session, doc_type=DocType.CAREER_IDENTITY, ref_id=f"belief-note-{note_id}"
    )


@router.post("/notes/{note_id}/reflect", response_model=BeliefNoteResponse)
async def ai_reflect_belief_note(
    note_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> BeliefNoteResponse:
    """책/강의 구절·일상 생각을 인간·사회적 커리어 신념 및 프로젝트 문제의식과 연결해 심화 회고 코멘트를 생성한다."""
    note = await session.get(BeliefNote, note_id)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Belief note {note_id} not found.",
        )

    profile = await session.get(UserProfile, 1)
    pillars = (
        (await session.execute(select(BeliefPillar).order_by(BeliefPillar.created_at.desc()).limit(6)))
        .scalars()
        .all()
    )
    projects = (
        (await session.execute(select(Project).order_by(Project.created_at.desc()).limit(6)))
        .scalars()
        .all()
    )
    proj_summary = (
        "\n".join(f"- {p.name} ({p.role}): {p.summary}" for p in projects)
        or "(등록된 프로젝트 없음)"
    )
    pillar_summary = (
        "\n".join(f"- [{PILLAR_CATEGORY_LABELS.get(p.category, p.category)}] {p.title}" for p in pillars)
        or "(등록된 신념 카드 없음)"
    )
    profile_summary = (
        f"비전: {profile.career_vision}\n희망 직무: {profile.target_roles}"
        if profile
        else "(미설정)"
    )

    label = SOURCE_TYPE_LABELS.get(note.source_type, note.source_type)
    system_prompt = (
        "당신은 지원자의 독서·강의 구절과 일상 사유를 AI 시대의 깊이 있는 인간적·사회적 커리어 철학으로 확장해 주는 인문학 사고 파트너입니다.\n"
        "아래 4개 항목으로 간결하고 통찰력 있는 한국어 Markdown 회고 코멘트를 작성하세요:\n"
        "1. **핵심 인문·사회적 통찰** (이 구절·생각이 사람과 사회에 던지는 본질적 질문 1~2문장)\n"
        "2. **나의 커리어 지향·프로젝트와의 연결점** (커리어에서 어떤 일을 하고 싶은지, 기존 프로젝트 문제의식과 어떻게 이어지는지)\n"
        "3. **더 깊이 사유해볼 질문 2개** (업무 스킬이 아닌 인간·사회·가치관 차원의 질문)\n"
        "4. **자소서·지원동기 활용 팁** (기업의 사회적 역할·미션과 자연스럽게 연결하는 한 줄 팁)\n"
        "과장된 칭찬은 피하고 담백하고 사려 깊게 작성하세요."
    )
    user_prompt = (
        f"[노트 유형] {label}\n"
        f"[출처/주제] {note.source_title or '(미입력)'}\n"
        f"[태그] {', '.join(note.tags or []) or '(없음)'}\n"
        f"[인상 깊은 구절]\n{note.quote_text or '(없음)'}\n\n"
        f"[나의 생각·회고]\n{note.my_reflection}\n\n"
        f"[현재 나의 핵심 신념 카드]\n{pillar_summary}\n\n"
        f"[현재 나의 커리어 프로필]\n{profile_summary}\n\n"
        f"[나의 보유 프로젝트]\n{proj_summary}"
    )

    try:
        llm = get_smart_llm(temperature=0.35, max_tokens=2500)
        ai_msg = await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        note.ai_reflection = (
            ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
        ).strip()
    except Exception as exc:
        logger.exception("AI reflection failed for belief note %s: %s", note_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI 생각 심화 회고 생성 실패: {exc}",
        )

    await session.commit()
    await session.refresh(note)
    return BeliefNoteResponse.model_validate(note)


@router.post("/synthesize-identity")
async def synthesize_identity_from_notes(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """신념 카드와 구절·생각 노트들을 종합해 인간·사회적 가치가 담긴 커리어 비전 초안을 제안한다."""
    profile = await session.get(UserProfile, 1)
    pillars = (
        (await session.execute(select(BeliefPillar).order_by(BeliefPillar.created_at.desc()).limit(10)))
        .scalars()
        .all()
    )
    notes = (
        (
            await session.execute(
                select(BeliefNote).order_by(BeliefNote.created_at.desc()).limit(25)
            )
        )
        .scalars()
        .all()
    )
    if not notes and not pillars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="종합할 신념 카드나 회고 노트가 아직 없습니다. 최소 1개 이상 기록한 뒤 시도해 주세요.",
        )

    pillars_dump = "\n".join(
        f"- [{PILLAR_CATEGORY_LABELS.get(p.category, p.category)}] {p.title} | 지향: {p.tradeoff_rule[:180]}"
        for p in pillars
    ) or "(없음)"
    notes_dump = "\n\n".join(
        f"- [{SOURCE_TYPE_LABELS.get(n.source_type, n.source_type)}] {n.source_title or '무제'}\n"
        + (f"  구절: {n.quote_text[:300]}\n" if n.quote_text.strip() else "")
        + f"  내 생각: {n.my_reflection[:500]}"
        for n in notes
    ) or "(없음)"
    cur_profile = (
        f"현재 비전: {profile.career_vision}\n희망 직무: {profile.target_roles}"
        if profile
        else "(기존 프로필 없음)"
    )

    system_prompt = (
        "당신은 지원자의 신념 카드와 독서·강의·일상 회고에서 일관된 인문학적·사회적 문제의식을 길어 올려 "
        "'커리어를 통해 어떤 사람·사회적 가치를 만들고 싶은지'가 선명한 커리어 비전으로 정제하는 에디터입니다.\n"
        "업무 습관이나 뻔한 미사여구('열정적인', '끊임없이 성장하는')를 배제하고, 기록에 담긴 지원자만의 인간적 관점을 살려 제안하세요."
    )
    user_prompt = (
        f"[기존 프로필]\n{cur_profile}\n\n"
        f"[핵심 신념 카드 ({len(pillars)}건)]\n{pillars_dump[:4000]}\n\n"
        f"[축적된 구절 · 생각 노트 ({len(notes)}건)]\n{notes_dump[:12000]}"
    )

    try:
        llm = get_smart_llm(temperature=0.35, max_tokens=2500)
        synthesized = await ainvoke_structured(
            llm,
            IdentitySynthesisSchema,
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            max_retries=2,
        )
        return {
            **synthesized.model_dump(),
            "note_count": len(notes) + len(pillars),
        }
    except Exception as exc:
        logger.exception("Identity synthesis from belief notes failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"비전 정제 중 오류가 발생했습니다: {exc}",
        )
