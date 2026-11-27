"""GitHub 계정 연동(암호화 PAT 저장), 내 레포지토리 브라우저·미연결 감지, 새 레포지토리 자동 생성 API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import Project, UserProfile, get_db_session
from app.core.token_crypto import decrypt_secret, encrypt_secret, mask_token
from app.tools.github_analyzer import (
    GitHubAnalyzerError,
    create_github_repository,
    list_authenticated_github_repos,
    parse_github_url,
    verify_github_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/github", tags=["github"])


async def _get_or_create_profile(session: AsyncSession) -> UserProfile:
    profile = await session.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


async def resolve_effective_github_token(
    session: AsyncSession,
    explicit_token: str | None = None,
) -> tuple[str, str]:
    """사용 가능한 GitHub 토큰과 출처('explicit'|'db'|'env'|'none')를 반환한다."""
    exp = (explicit_token or "").strip()
    if exp:
        return exp, "explicit"

    profile = await session.get(UserProfile, 1)
    if profile and (profile.github_token_encrypted or "").strip():
        decrypted = decrypt_secret(profile.github_token_encrypted)
        if decrypted:
            return decrypted, "db"

    env_tok = (settings.github_token or "").strip()
    if env_tok:
        return env_tok, "env"

    return "", "none"


def _normalize_repo_key(repo_url: str) -> str:
    raw = (repo_url or "").strip()
    if not raw:
        return ""
    try:
        owner, repo = parse_github_url(raw)
        return f"{owner}/{repo}".lower()
    except Exception:
        return ""


class GitHubTokenSaveRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=300, description="GitHub Personal Access Token")


class GitHubCreateRepoRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="새 GitHub 저장소 이름 (한글 시 영문 슬러그 자동 변환)")
    description: str = Field(default="", max_length=350)
    private: bool = Field(default=True, description="Private 저장소 여부")
    readme_content: str = Field(default="", description="초기 README.md 내용 (선택)")
    project_id: int | None = Field(default=None, description="생성 직후 repo_url을 자동 연결할 포트폴리오 프로젝트 ID (선택)")


@router.get("/status")
async def get_github_status(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """현재 GitHub 계정 연결 상태를 반환한다 (원문 토큰은 절대 노출하지 않음)."""
    profile = await session.get(UserProfile, 1)
    token, source = await resolve_effective_github_token(session)
    if not token:
        return {
            "connected": False,
            "source": "none",
            "username": "",
            "avatar_url": "",
            "token_hint": "",
            "scopes": [],
            "rate_remaining": None,
        }

    username = profile.github_username if (profile and source == "db") else ""
    avatar_url = profile.github_avatar_url if (profile and source == "db") else ""
    scopes: list[str] = []
    rate_remaining: int | None = None

    if not username:
        try:
            info = await verify_github_token(token)
            username = info["login"]
            avatar_url = info["avatar_url"]
            scopes = info["scopes"]
            rate_remaining = info["rate_remaining"]
        except GitHubAnalyzerError:
            pass

    return {
        "connected": True,
        "source": source,
        "username": username,
        "avatar_url": avatar_url,
        "token_hint": mask_token(token),
        "scopes": scopes,
        "rate_remaining": rate_remaining,
    }


@router.put("/token")
async def save_github_token(
    payload: GitHubTokenSaveRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """GitHub PAT를 검증한 뒤 서버 측 인증 암호화하여 저장한다."""
    raw_token = payload.token.strip()
    try:
        info = await verify_github_token(raw_token)
    except GitHubAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    profile = await _get_or_create_profile(session)
    profile.github_token_encrypted = encrypt_secret(raw_token)
    profile.github_username = info["login"][:120]
    profile.github_avatar_url = info["avatar_url"][:500]
    await session.commit()

    return {
        "connected": True,
        "source": "db",
        "username": profile.github_username,
        "avatar_url": profile.github_avatar_url,
        "token_hint": mask_token(raw_token),
        "scopes": info["scopes"],
        "rate_remaining": info["rate_remaining"],
    }


@router.delete("/token", status_code=status.HTTP_204_NO_CONTENT)
async def delete_github_token(
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """저장된 GitHub 토큰을 삭제한다."""
    profile = await session.get(UserProfile, 1)
    if profile is not None:
        profile.github_token_encrypted = ""
        profile.github_username = ""
        profile.github_avatar_url = ""
        await session.commit()


@router.get("/repos")
async def list_my_github_repos(
    include_forks: bool = False,
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """연결된 GitHub 계정의 전체 레포지토리 목록을 불러오고 포트폴리오 연결 여부를 매칭한다."""
    token, source = await resolve_effective_github_token(session)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="연결된 GitHub 토큰이 없습니다. 먼저 GitHub 계정을 연결해 주세요.",
        )

    try:
        repos = await list_authenticated_github_repos(
            token, include_forks=include_forks, limit=limit
        )
    except GitHubAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    projects = (await session.execute(select(Project))).scalars().all()
    linked_map: dict[str, Project] = {}
    for p in projects:
        key = _normalize_repo_key(p.repo_url)
        if key:
            linked_map[key] = p

    enriched: list[dict[str, Any]] = []
    linked_count = 0
    for r in repos:
        key = r["full_name"].lower()
        matched_proj = linked_map.get(key)
        is_linked = matched_proj is not None
        if is_linked:
            linked_count += 1
        enriched.append(
            {
                **r,
                "is_linked": is_linked,
                "linked_project_id": matched_proj.id if matched_proj else None,
                "linked_project_name": matched_proj.name if matched_proj else "",
            }
        )

    profile = await session.get(UserProfile, 1)
    return {
        "connected": True,
        "source": source,
        "username": profile.github_username if (profile and source == "db") else "",
        "total_count": len(enriched),
        "linked_count": linked_count,
        "unlinked_count": len(enriched) - linked_count,
        "repos": enriched,
    }


@router.post("/repos", status_code=status.HTTP_201_CREATED)
async def create_new_github_repo(
    payload: GitHubCreateRepoRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """연결된 GitHub 계정에 새 저장소를 생성하고(선택 시 초기 README 커밋), 지정 프로젝트에 repo_url을 자동 연결한다."""
    token, _ = await resolve_effective_github_token(session)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="연결된 GitHub 토큰이 없습니다. 먼저 '2. 포트폴리오'에서 GitHub 계정을 연결해 주세요.",
        )

    try:
        created = await create_github_repository(
            token,
            name=payload.name,
            description=payload.description,
            private=payload.private,
            readme_content=payload.readme_content,
        )
    except GitHubAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    linked_project_id: int | None = None
    if payload.project_id is not None:
        proj = await session.get(Project, payload.project_id)
        if proj is not None:
            proj.repo_url = created["html_url"]
            await session.commit()
            linked_project_id = proj.id

    return {
        **created,
        "linked_project_id": linked_project_id,
    }
