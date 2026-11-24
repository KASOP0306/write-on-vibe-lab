from datetime import datetime

from pydantic import BaseModel, Field


class SampleCreateRequest(BaseModel):
    role_category: str = Field(
        default="직무 공통", max_length=100, description="직무군 (예: 백엔드 개발, AI 엔지니어)"
    )
    question_type: str = Field(
        ..., min_length=1, max_length=150, description="문항 유형 (예: 지원동기, 문제해결, 협업)"
    )
    sample_text: str = Field(
        ..., min_length=20, description="참고할 합격 자소서 본문 (전개 구조·논리 참고 전용)"
    )
    structure_pattern: str = Field(
        default="", max_length=300, description="선택: 문단 전개 구조 요약"
    )
    key_persuasion_points: list[str] = Field(
        default_factory=list, description="선택: 핵심 설득 포인트 리스트"
    )


class SampleResponse(BaseModel):
    id: int
    ref_id: str
    role_category: str
    question_type: str
    structure_pattern: str
    key_persuasion_points: list[str]
    sample_text: str
    source: str
    created_at: datetime
