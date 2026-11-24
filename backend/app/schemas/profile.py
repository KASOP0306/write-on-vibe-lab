from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdateRequest(BaseModel):
    career_vision: str = Field(default="", description="궁극적 포트폴리오 목표 및 커리어 비전")
    core_beliefs: str = Field(default="", description="업계 신념 및 엔지니어링 철학")
    target_roles: str = Field(default="", description="희망 직무 (예: 백엔드 / AI 에이전트 엔지니어)")
    preferred_tone: str = Field(default="", description="실제 문체 및 선호 어휘 샘플")


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    career_vision: str
    core_beliefs: str
    target_roles: str
    preferred_tone: str
    updated_at: datetime
    vector_synced: bool | None = None


class InterestCreateRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200, description="관심 분야 키워드")
    source: Literal["manual", "retrospective_suggested"] = Field(
        default="manual", description="등록 경로"
    )


class InterestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    source: str
    created_at: datetime
