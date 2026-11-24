"""Profile(신념·비전·선호 문체) 및 Interests(관심 분야) CRUD 라우터."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import UserInterest, UserProfile, get_db_session
from app.core.vector_store import DocType, try_upsert_document
from app.schemas.profile import (
    InterestCreateRequest,
    InterestResponse,
    ProfileResponse,
    ProfileUpdateRequest,
)

router = APIRouter(prefix="/api", tags=["profile & interests"])


async def _get_or_create_profile(session: AsyncSession) -> UserProfile:
    profile = await session.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


def _build_identity_document(profile: UserProfile) -> str:
    parts = [
        f"희망 직무: {profile.target_roles}".strip() if profile.target_roles else "",
        f"커리어 비전(궁극적 포트폴리오 목표): {profile.career_vision}".strip()
        if profile.career_vision
        else "",
        f"핵심 신념 및 철학: {profile.core_beliefs}".strip()
        if profile.core_beliefs
        else "",
        f"선호 문체 및 어휘 스타일: {profile.preferred_tone}".strip()
        if profile.preferred_tone
        else "",
    ]
    return "\n\n".join(part for part in parts if part)


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    profile = await _get_or_create_profile(session)
    return ProfileResponse.model_validate(profile)


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    profile = await _get_or_create_profile(session)
    profile.career_vision = payload.career_vision.strip()
    profile.core_beliefs = payload.core_beliefs.strip()
    profile.target_roles = payload.target_roles.strip()
    profile.preferred_tone = payload.preferred_tone.strip()

    await session.commit()
    await session.refresh(profile)

    identity_text = _build_identity_document(profile)
    vector_synced = await try_upsert_document(
        session,
        doc_type=DocType.CAREER_IDENTITY,
        ref_id="profile-1",
        content=identity_text,
        metadata={
            "target_roles": profile.target_roles,
            "updated_at": profile.updated_at.isoformat(),
        },
    )

    response = ProfileResponse.model_validate(profile)
    response.vector_synced = vector_synced
    return response


@router.get("/interests", response_model=list[InterestResponse])
async def list_interests(
    session: AsyncSession = Depends(get_db_session),
) -> list[InterestResponse]:
    stmt = select(UserInterest).order_by(UserInterest.created_at.desc(), UserInterest.id.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [InterestResponse.model_validate(row) for row in rows]


@router.post(
    "/interests",
    response_model=InterestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_interest(
    payload: InterestCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> InterestResponse:
    keyword = payload.keyword.strip()
    if not keyword:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="keyword must not be blank.",
        )

    interest = UserInterest(keyword=keyword, source=payload.source)
    session.add(interest)
    try:
        await session.commit()
        await session.refresh(interest)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Interest keyword '{keyword}' already exists.",
        )

    return InterestResponse.model_validate(interest)


@router.delete("/interests/{interest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interest(
    interest_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    interest = await session.get(UserInterest, interest_id)
    if interest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interest {interest_id} not found.",
        )
    await session.delete(interest)
    await session.commit()
