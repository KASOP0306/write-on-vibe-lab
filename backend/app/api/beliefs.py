"""나의 신념 · 책/강의 구절 · 일상 생각 회고 저널 (Belief Notes) API 라우터."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bedrock import ainvoke_structured, get_smart_llm
from app.core.database import BeliefNote, Project, UserProfile, get_db_session
from app.core.vector_store import DocType, delete_document, try_upsert_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/beliefs", tags=["beliefs"])

SOURCE_TYPE_LABELS = {
    "book": "책 / 독서 구절",
    "lecture": "강의 / 세미나",
    "article": "아티클 / 영상",
    "thought": "일상 생각 / 회고",
}


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
    projects = (
        (await session.execute(select(Project).order_by(Project.created_at.desc()).limit(6)))
        .scalars()
        .all()
    )
    proj_summary = (
        "\n".join(f"- {p.name} ({p.role}): {p.summary}" for p in projects)
        or "(등록된 프로젝트 없음)"
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
        "2. **나의 커리어 신념·프로젝트와의 연결점** (기존 신념이나 실제 프로젝트 경험과 어떻게 맞닿아 있는지)\n"
        "3. **더 깊이 생각해볼 회고 질문 2개** (스스로의 행동 원칙으로 구체화하도록 돕는 질문)\n"
        "4. **자소서·면접 활용 팁** (지원동기나 가치관 문항에서 진정성 있게 녹이는 한 줄 팁)\n"
        "과장된 칭찬은 피하고 담백하고 통찰력 있게 작성하세요."
    )
    user_prompt = (
        f"[노트 유형] {label}\n"
        f"[출처/주제] {note.source_title or '(미입력)'}\n"
        f"[태그] {', '.join(note.tags or []) or '(없음)'}\n"
        f"[인상 깊은 구절]\n{note.quote_text or '(없음)'}\n\n"
        f"[나의 생각·회고]\n{note.my_reflection}\n\n"
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
    """지금까지 기록한 구절·생각 노트들을 종합해 더 선명한 커리어 비전·핵심 신념 초안을 제안한다."""
    profile = await session.get(UserProfile, 1)
    notes = (
        (
            await session.execute(
                select(BeliefNote).order_by(BeliefNote.created_at.desc()).limit(25)
            )
        )
        .scalars()
        .all()
    )
    if not notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="종합할 구절·생각 노트가 아직 없습니다. 최소 1개 이상 기록한 뒤 시도해 주세요.",
        )

    notes_dump = "\n\n".join(
        f"- [{SOURCE_TYPE_LABELS.get(n.source_type, n.source_type)}] {n.source_title or '무제'}\n"
        + (f"  구절: {n.quote_text[:300]}\n" if n.quote_text.strip() else "")
        + f"  내 생각: {n.my_reflection[:500]}"
        for n in notes
    )
    cur_profile = (
        f"현재 비전: {profile.career_vision}\n현재 신념: {profile.core_beliefs}\n희망 직무: {profile.target_roles}"
        if profile
        else "(기존 프로필 없음)"
    )

    system_prompt = (
        "당신은 지원자가 직접 모은 책·강의 구절과 일상 생각 기록에서 일관된 철학을 길어 올려 "
        "진정성 있는 커리어 비전과 핵심 신념 문장으로 정제하는 에디터입니다.\n"
        "뻔한 미사여구('열정적인', '끊임없이 성장하는')를 배제하고, 실제 기록에 담긴 지원자만의 관점과 언어를 살려 제안하세요."
    )
    user_prompt = (
        f"[기존 프로필]\n{cur_profile}\n\n"
        f"[축적된 구절 · 생각 노트 ({len(notes)}건)]\n{notes_dump[:14000]}"
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
            "note_count": len(notes),
        }
    except Exception as exc:
        logger.exception("Identity synthesis from belief notes failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"신념·비전 정제 중 오류가 발생했습니다: {exc}",
        )
