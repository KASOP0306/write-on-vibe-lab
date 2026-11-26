"""나의 신념 카드(Belief Pillars) & 책/강의 구절·일상 생각 회고 저널(Belief Notes) API 라우터."""

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
    "work_principle": "일하는 원칙",
    "problem_lens": "문제 정의 관점",
    "collaboration": "협업 · 소통 철학",
    "career_direction": "커리어 방향성",
}

_BELIEF_CLICHE_PATTERNS = (
    "끊임없이 성장",
    "열정적인",
    "최선을 다하",
    "사용자 중심",
    "소통을 중시",
    "도전정신",
    "책임감을 가지",
    "협업을 중요",
    "더 나은 세상",
    "혁신적인 가치",
)

_TRADEOFF_SIGNAL_RE = re.compile(
    r"(보다|대신|우선|먼저|포기|트레이드오프|vs|충돌|기준|않는다|안\s*한다|거부|차라리|먼저\s*검증|최소|절단|타협)",
    re.IGNORECASE,
)


def evaluate_belief_pillar_quality(
    *,
    title: str,
    tradeoff_rule: str = "",
    origin_story: str = "",
    linked_project_ids: list[int] | None = None,
    linked_experience_ids: list[int] | None = None,
) -> dict[str, Any]:
    """신념 카드의 자소서 실전성(트레이드오프 구체성 · 클리셰 여부 · 경험 증명 연결)을 결정론적으로 진단한다."""
    title_clean = (title or "").strip()
    rule_clean = (tradeoff_rule or "").strip()
    origin_clean = (origin_story or "").strip()
    combined = f"{title_clean} {rule_clean} {origin_clean}"

    cliche_hits = [c for c in _BELIEF_CLICHE_PATTERNS if c in combined]
    has_tradeoff = len(rule_clean) >= 12 or bool(_TRADEOFF_SIGNAL_RE.search(title_clean + " " + rule_clean))
    has_origin = len(origin_clean) >= 15
    proof_count = len(linked_project_ids or []) + len(linked_experience_ids or [])
    has_proof = proof_count > 0

    score = 0
    if len(title_clean) >= 10:
        score += 20
    if has_tradeoff:
        score += 30
    if has_origin:
        score += 15
    if has_proof:
        score += min(35, 25 + (proof_count - 1) * 5)
    if cliche_hits and not has_tradeoff:
        score = max(10, score - 20)
    score = max(0, min(100, score))

    if cliche_hits and not has_tradeoff:
        proof_status = "cliche_risk"
        tip = (
            f"추상 표현({', '.join(cliche_hits[:2])})이 감지되었습니다. "
            "'A보다 B를 우선한다' 형태의 구체적 트레이드오프 판단 기준으로 다듬어 보세요."
        )
    elif not has_proof:
        proof_status = "needs_proof"
        tip = (
            "아직 이 신념을 증명하는 프로젝트·STAR 경험이 연결되지 않았습니다. "
            "기존 경험을 연결하거나 코파일럿에서 증명용 새 프로젝트를 설계해 보세요."
        )
    elif not has_tradeoff:
        proof_status = "needs_tradeoff"
        tip = "경험은 연결되었지만 '충돌 시 무엇을 포기하고 무엇을 택하는지' 트레이드오프 기준을 한 줄 보강하면 자소서가 훨씬 날카로워집니다."
    else:
        proof_status = "proven"
        tip = "트레이드오프 판단 기준과 실제 증명 경험이 모두 연결된 자소서 즉시 투입 가능 신념입니다."

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
# 1. 구조화된 핵심 신념 카드 (Belief Pillars) 스키마 & CRUD + AI 발굴/다듬기
# ==============================================================================
class BeliefPillarCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=300, description="핵심 신념 한 줄 선언")
    category: Literal[
        "work_principle", "problem_lens", "collaboration", "career_direction"
    ] = Field(default="work_principle")
    tradeoff_rule: str = Field(
        default="", description="충돌/트레이드오프 시 판단 기준 (A보다 B를 우선하는 이유)"
    )
    origin_story: str = Field(default="", description="이 신념이 형성된 결정적 계기·회고 요약")
    linked_project_ids: list[int] = Field(default_factory=list)
    linked_experience_ids: list[int] = Field(default_factory=list)
    linked_note_ids: list[int] = Field(default_factory=list)


class BeliefPillarUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    category: Literal[
        "work_principle", "problem_lens", "collaboration", "career_direction"
    ] | None = None
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
        default="", description="트레이드오프·실제 겪은 갈등 상황 한 줄 힌트 (선택)"
    )


class SharpenedPillarSchema(BaseModel):
    sharpened_title: str = Field(
        description="클리셰를 제거하고 지원자만의 행동 기준이 선명하게 드러나는 한 줄 신념 선언"
    )
    sharpened_tradeoff_rule: str = Field(
        description="'A vs B 충돌 시 무엇을 우선하고 무엇을 포기/유보하는지' 구체적 판단 기준 (1~2문장)"
    )
    sharpened_origin_story: str = Field(
        description="기존 계기와 연결 프로젝트/경험 맥락을 살려 다듬은 형성 계기 요약 (1~2문장)"
    )
    why_better: str = Field(description="기존 문장 대비 자소서·면접에서 왜 더 설득력이 높은지 1문장")


class DiscoveredPillarCandidate(BaseModel):
    title: str = Field(description="실제 프로젝트·STAR 행동 패턴에서 도출된 차별화된 한 줄 신념 선언")
    category: Literal[
        "work_principle", "problem_lens", "collaboration", "career_direction"
    ] = Field(default="work_principle")
    tradeoff_rule: str = Field(
        description="실제 선택에서 드러난 'A보다 B를 우선하는' 트레이드오프 판단 기준 (1~2문장)"
    )
    origin_story: str = Field(
        description="어떤 프로젝트·경험·회고에서 이 신념이 드러났는지 근거 요약 (1~2문장)"
    )
    linked_project_ids: list[int] = Field(
        default_factory=list, description="이 신념을 직접 증명하는 등록 프로젝트 ID 목록"
    )
    linked_experience_ids: list[int] = Field(
        default_factory=list, description="이 신념을 직접 증명하는 등록 STAR 경험 ID 목록"
    )
    linked_note_ids: list[int] = Field(
        default_factory=list, description="관련 일상 회고 노트 ID 목록"
    )
    evidence_summary: str = Field(description="자소서에서 이 신념을 어떻게 증명할 수 있는지 1문장")


class PortfolioBeliefDiscoverySchema(BaseModel):
    overall_observation: str = Field(
        description="지원자의 프로젝트·경험·노트 전반을 관통하는 일하는 방식의 핵심 패턴 요약 (2문장)"
    )
    candidates: list[DiscoveredPillarCandidate] = Field(
        default_factory=list, description="실제 근거 기반 핵심 신념 카드 후보 3~4개"
    )


def _serialize_pillar(pillar: BeliefPillar, *, vector_synced: bool | None = None) -> BeliefPillarResponse:
    qual = evaluate_belief_pillar_quality(
        title=pillar.title,
        tradeoff_rule=pillar.tradeoff_rule,
        origin_story=pillar.origin_story,
        linked_project_ids=list(pillar.linked_project_ids or []),
        linked_experience_ids=list(pillar.linked_experience_ids or []),
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
        parts.append(f"[트레이드오프 판단 기준] {pillar.tradeoff_rule.strip()}")
    if pillar.origin_story.strip():
        parts.append(f"[형성 계기·회고] {pillar.origin_story.strip()}")
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


@router.get("/pillars", response_model=list[BeliefPillarResponse])
async def list_belief_pillars(
    session: AsyncSession = Depends(get_db_session),
) -> list[BeliefPillarResponse]:
    stmt = select(BeliefPillar).order_by(BeliefPillar.created_at.desc(), BeliefPillar.id.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize_pillar(r) for r in rows]


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
            line += f" (기준: {p.tradeoff_rule.strip()})"
        lines.append(line)
    profile.core_beliefs = "\n".join(lines)
    await session.commit()


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
    """추상적이거나 뻔한 신념 카드를 트레이드오프 판단 기준이 살아 있는 차별화 문장으로 다듬어 제안한다."""
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
            f"- [STAR 경험] {e.title}: Action={(e.action or '')[:180]} | Learning={(e.learning or '')[:140]}"
            for e in linked_exps
        ]
    ) or "(연결된 증명 경험 없음)"

    system_prompt = (
        "당신은 빅테크·대기업 서류 심사위원 출신 커리어 철학 에디터입니다.\n"
        "지원자의 신념 문장에서 누구나 쓸 수 있는 뻔한 클리셰('끊임없이 성장', '사용자 중심', '소통 중시', '최선')를 모두 제거하고, "
        "'A와 B가 충돌할 때 나는 왜 B를 선택하는가'가 또렷하게 드러나는 실전형 신념 선언과 트레이드오프 기준으로 날카롭게 다듬어 주세요.\n"
        "규칙: 제공된 프로젝트·경험·힌트에 없는 사실이나 수치는 절대 지어내지 마세요."
    )
    user_prompt = (
        f"[현재 신념 카드]\n"
        f"- 카테고리: {PILLAR_CATEGORY_LABELS.get(pillar.category, pillar.category)}\n"
        f"- 선언문: {pillar.title}\n"
        f"- 트레이드오프 기준: {pillar.tradeoff_rule or '(미입력)'}\n"
        f"- 형성 계기: {pillar.origin_story or '(미입력)'}\n\n"
        f"[연결된 증명 프로젝트·STAR]\n{proof_dump}\n\n"
        f"[사용자 추가 컨텍스트 힌트]\n{payload.context_hint.strip() or '(없음)'}"
    )

    try:
        llm = get_smart_llm(temperature=0.3, max_tokens=1800)
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
    """등록된 프로젝트·STAR-L 경험·일상 회고 노트에서 실제 행동 기반 핵심 신념 카드 후보 3~4개를 자동 역추출한다."""
    profile = await session.get(UserProfile, 1)
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
                .limit(15)
            )
        )
        .scalars()
        .all()
    )
    notes = (
        (
            await session.execute(
                select(BeliefNote).order_by(BeliefNote.created_at.desc()).limit(15)
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
            detail="신념을 역추출할 프로젝트, STAR-L 경험, 또는 회고 노트가 아직 없습니다. 하나 이상 등록한 뒤 시도해 주세요.",
        )

    proj_blocks = []
    for p in projects:
        sec_preview = " / ".join(
            f"[{s.title}] {(s.content or '').strip()[:160]}"
            for s in p.sections
            if (s.content or "").strip()
        )[:500]
        proj_blocks.append(
            f"- [project_id={p.id}] {p.name} (역할: {p.role or '미입력'}) | 요약: {p.summary[:220]}\n"
            f"  섹션 발췌: {sec_preview or '(없음)'}"
        )

    exp_blocks = [
        f"- [experience_id={e.id}, project_id={e.project_id}] {e.title} ({e.completeness_score}점)\n"
        f"  Action: {(e.action or '')[:220]} | Result: {(e.result or '')[:140]} | Learning: {(e.learning or '')[:180]}"
        for e in experiences
    ]
    note_blocks = [
        f"- [note_id={n.id}] [{SOURCE_TYPE_LABELS.get(n.source_type, n.source_type)}] {n.source_title or '무제'}\n"
        f"  구절: {(n.quote_text or '')[:140]} | 생각: {n.my_reflection[:220]}"
        for n in notes
    ]
    existing_dump = "\n".join(f"- {ep.title}" for ep in existing_pillars) or "(없음)"

    system_prompt = (
        "당신은 지원자의 실제 프로젝트 결정, STAR-L 행동·회고(Action/Learning), 그리고 일상 회고 노트에서 "
        "**말뿐인 구호가 아니라 이미 행동으로 증명된 핵심 신념 카드(`BeliefPillar`) 3~4개**를 역추출하는 커리어 철학 아키텍트입니다.\n\n"
        "핵심 규칙:\n"
        "1. '열정적인', '끊임없이 성장하는', '사용자 중심' 같은 뻔한 클리셰를 절대 쓰지 마세요.\n"
        "2. 각 후보는 반드시 **'A보다 B를 우선한다' 형태의 구체적 트레이드오프 판단 기준(`tradeoff_rule`)**을 포함하세요.\n"
        "3. `linked_project_ids`, `linked_experience_ids`, `linked_note_ids`에는 반드시 아래 목록에 실존하는 정수 ID만 넣으세요.\n"
        "4. 이미 등록된 신념 카드와 겹치지 않는 새로운 관점을 우선 제안하세요."
    )
    user_prompt = (
        f"[현재 프로필]\n"
        f"비전: {profile.career_vision if profile else '(미설정)'}\n"
        f"기존 신념 메모: {profile.core_beliefs if profile else '(미설정)'}\n"
        f"희망 직무: {profile.target_roles if profile else '(미설정)'}\n\n"
        f"[이미 등록된 신념 카드 (중복 방지)]\n{existing_dump}\n\n"
        f"[보유 프로젝트 ({len(projects)}건)]\n" + ("\n".join(proj_blocks)[:5000] or "(없음)") + "\n\n"
        f"[채굴된 STAR-L 경험 ({len(experiences)}건)]\n" + ("\n".join(exp_blocks)[:4500] or "(없음)") + "\n\n"
        f"[일상 회고 저널 ({len(notes)}건)]\n" + ("\n".join(note_blocks)[:3000] or "(없음)")
    )

    try:
        llm = get_smart_llm(temperature=0.3, max_tokens=3200)
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
            detail=f"포트폴리오 기반 신념 역추출 실패: {exc}",
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

    profile = await session.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1)
        session.add(profile)

    summary_lines = []
    for idx, p in enumerate(pillars, start=1):
        cat = PILLAR_CATEGORY_LABELS.get(p.category, p.category)
        line = f"{idx}. [{cat}] {p.title}"
        if p.tradeoff_rule.strip():
            line += f" (기준: {p.tradeoff_rule.strip()})"
        summary_lines.append(line)

    profile.core_beliefs = "\n".join(summary_lines)
    await session.commit()
    await session.refresh(profile)

    identity_text = "\n\n".join(
        part
        for part in [
            f"희망 직무: {profile.target_roles}" if profile.target_roles else "",
            f"커리어 비전: {profile.career_vision}" if profile.career_vision else "",
            f"핵심 신념 및 철학:\n{profile.core_beliefs}" if profile.core_beliefs else "",
            f"선호 문체: {profile.preferred_tone}" if profile.preferred_tone else "",
        ]
        if part
    )
    synced = await try_upsert_document(
        session,
        doc_type=DocType.CAREER_IDENTITY,
        ref_id="profile-1",
        content=identity_text,
        metadata={"target_roles": profile.target_roles, "pillar_count": len(pillars)},
    )
    return {
        "core_beliefs": profile.core_beliefs,
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
        description="축적된 구절·생각 노트와 기존 프로필을 통합해 한층 선명하게 다듬은 커리어 비전 (2~3문장)"
    )
    suggested_core_beliefs: str = Field(
        description="반복되는 가치관과 독서/강의 인사이트를 응축한 핵심 신념·일하는 원칙 (3~4문장)"
    )
    key_themes: list[str] = Field(
        default_factory=list, description="노트 전반을 관통하는 핵심 가치관 키워드 3~5개"
    )
    synthesis_rationale: str = Field(
        description="어떤 노트와 구절에서 이 정체성이 도출되었는지 설명 (2문장)"
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
    """책/강의 구절·일상 생각을 나의 커리어 신념 및 프로젝트 경험과 연결해 심화 회고 코멘트를 생성한다."""
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
        f"비전: {profile.career_vision}\n신념: {profile.core_beliefs}\n희망 직무: {profile.target_roles}"
        if profile
        else "(미설정)"
    )

    label = SOURCE_TYPE_LABELS.get(note.source_type, note.source_type)
    system_prompt = (
        "당신은 지원자의 독서·강의 구절과 일상 생각을 깊이 있는 커리어 철학으로 승화시켜 주는 사고 파트너입니다.\n"
        "아래 4개 항목으로 간결하고 날카로운 한국어 Markdown 회고 코멘트를 작성하세요:\n"
        "1. **핵심 통찰 정리** (이 구절·생각이 가리키는 본질 1~2문장)\n"
        "2. **나의 신념 카드·프로젝트와의 연결점** (기존 신념 카드나 실제 프로젝트 경험과 어떻게 맞닿아 있는지)\n"
        "3. **더 깊이 생각해볼 회고 질문 2개** (스스로의 트레이드오프 행동 원칙으로 구체화하도록 돕는 질문)\n"
        "4. **자소서·면접 활용 팁** (지원동기나 가치관 문항에서 진정성 있게 녹이는 한 줄 팁)\n"
        "과장된 칭찬은 피하고 담백하고 통찰력 있게 작성하세요."
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
    """지금까지 기록한 신념 카드와 구절·생각 노트들을 종합해 더 선명한 커리어 비전·핵심 신념 초안을 제안한다."""
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
            detail="종합할 신념 카드나 구절·생각 노트가 아직 없습니다. 최소 1개 이상 기록한 뒤 시도해 주세요.",
        )

    pillars_dump = "\n".join(
        f"- [{PILLAR_CATEGORY_LABELS.get(p.category, p.category)}] {p.title} | 기준: {p.tradeoff_rule[:180]}"
        for p in pillars
    ) or "(없음)"
    notes_dump = "\n\n".join(
        f"- [{SOURCE_TYPE_LABELS.get(n.source_type, n.source_type)}] {n.source_title or '무제'}\n"
        + (f"  구절: {n.quote_text[:300]}\n" if n.quote_text.strip() else "")
        + f"  내 생각: {n.my_reflection[:500]}"
        for n in notes
    ) or "(없음)"
    cur_profile = (
        f"현재 비전: {profile.career_vision}\n현재 신념: {profile.core_beliefs}\n희망 직무: {profile.target_roles}"
        if profile
        else "(기존 프로필 없음)"
    )

    system_prompt = (
        "당신은 지원자가 직접 모은 핵심 신념 카드와 책·강의 구절·일상 생각 기록에서 일관된 철학을 길어 올려 "
        "진정성 있는 커리어 비전과 핵심 신념 문장으로 정제하는 에디터입니다.\n"
        "뻔한 미사여구('열정적인', '끊임없이 성장하는')를 배제하고, 실제 기록에 담긴 지원자만의 관점과 언어를 살려 제안하세요."
    )
    user_prompt = (
        f"[기존 프로필]\n{cur_profile}\n\n"
        f"[핵심 신념 카드 ({len(pillars)}건)]\n{pillars_dump[:4000]}\n\n"
        f"[축적된 구절 · 생각 노트 ({len(notes)}건)]\n{notes_dump[:12000]}"
    )

    try:
        llm = get_smart_llm(temperature=0.3, max_tokens=2500)
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
            detail=f"신념·비전 정제 중 오류가 발생했습니다: {exc}",
        )
