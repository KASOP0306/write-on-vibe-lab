"""에이전트 ①~③ API 입출력 및 기업 리서치/관심사 클립 Pydantic 스키마."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --- 워크플로우 ①: 경험 채굴 (Active Interviewer) ---
class InterviewStartRequest(BaseModel):
    raw_notes: str = Field(..., min_length=5, description="경험 메모 원문")
    project_id: int | None = Field(default=None, description="연결할 프로젝트 ID (선택)")
    thread_id: str | None = Field(default=None, description="세션 식별자 (미지정 시 자동 생성)")
    force_save: bool = Field(default=False, description="즉시 저장 여부")


class InterviewReplyRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, description="진행 중인 인터뷰 thread_id")
    user_reply: str = Field(default="", description="역질문에 대한 사용자 답변")
    project_id: int | None = Field(default=None, description="프로젝트 매핑 변경/지정 (선택)")
    force_save: bool = Field(
        default=False, description="true이면 완성도와 무관하게 즉시 저장 노드로 라우팅"
    )


# --- 워크플로우 ②: 목표 기업 리서치 & 신념 3각 매칭 ---
class CompanyResearchRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    target_role: str = Field(default="", max_length=200)
    jd_text: str = Field(
        default="", description="선택: 채용공고(JD) 본문 붙여넣기 (최우선 근거로 반영)"
    )
    reference_urls: list[str] = Field(
        default_factory=list,
        description="선택: 공식 기술 블로그·채용 페이지 등 직접 분석할 URL 목록",
    )


class CompanyProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    target_role: str
    mission_vision: str
    core_values: str
    recent_trends: str
    value_alignment_map: dict[str, Any]
    created_at: datetime


# --- 관심사 검색 & 선별 클립 저장 ---
class InterestSearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)
    scope: Literal["ko", "global", "all"] = Field(
        default="ko", description="검색 범위: ko(한국어 뉴스/블로그), global(영문/HN/GitHub), all(통합)"
    )
    recency: Literal["recent", "all"] = Field(
        default="recent", description="기간 필터: recent(최신 우선), all(전체)"
    )
    max_results: int = Field(default=6, ge=1, le=8)


class InterestClipSaveRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1, max_length=300)
    url: str = Field(default="", max_length=1000)
    summary: str = Field(..., min_length=10)
    key_takeaways: list[str] = Field(default_factory=list)


class InterestClipResponse(BaseModel):
    id: int
    ref_id: str
    keyword: str
    title: str
    url: str
    summary: str
    key_takeaways: list[str]
    created_at: datetime


# --- 워크플로우 ③: 자소서 문항 분석 · 소재 추천 · 생성 · 비평 · 퇴고 · De-AI ---
class CoverLetterRecommendRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    company_profile_id: int | None = Field(default=None)
    target_role: str = Field(default="", max_length=200)
    question: str = Field(..., min_length=5, description="기업 제공 자기소개서 문항")
    char_limit: int = Field(default=800, ge=200, le=3000, description="목표 글자 수")


class CoverLetterGenerateRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    company_profile_id: int | None = Field(default=None)
    target_role: str = Field(default="", max_length=200)
    question: str = Field(..., min_length=5, description="자기소개서 문항")
    char_limit: int = Field(default=800, ge=200, le=3000, description="목표 글자 수")
    extra_instructions: str = Field(default="", description="추가 강조 요청 (선택)")
    selected_project_ids: list[int] = Field(
        default_factory=list,
        description="사용자가 선택한 핵심 프로젝트 ID 목록 (최우선 1급 팩트로 주입)",
    )
    selected_experience_ids: list[int] = Field(
        default_factory=list,
        description="사용자가 선택한 핵심 STAR 경험 ID 목록",
    )
    question_analysis: dict[str, Any] = Field(
        default_factory=dict,
        description="1단계 문항 심층 분석 결과 (체크포인트·권장 구조 등)",
    )
    fusion_angle: str = Field(
        default="",
        description="기업 신념 × 나의 신념 × 선택 프로젝트 융합 스토리 각도",
    )


# --- 워크플로우 ④: 새 프로젝트 코파일럿 & 지원·취준 회고 ---
class NewProjectBlueprintsRequest(BaseModel):
    company_profile_id: int | None = Field(
        default=None, description="연결할 리서치 목표 기업 ID (선택)"
    )
    focus_weakness: str = Field(
        default="", description="집중 보완하고 싶은 캐릭터 약점/외적 축 (선택)"
    )
    topic_hint: str = Field(
        default="", description="관심 주제나 아이디어 힌트 (선택)"
    )
    use_web_search: bool = Field(
        default=True, description="최신 실무 사례·트렌드 웹 검색 포함 여부"
    )


class CopilotChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class CopilotChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="새 프로젝트 코파일럿 질문")
    thread_id: str | None = Field(
        default=None, description="단기 기억(AsyncPostgresSaver) 대화 스레드 ID (미지정 시 자동 생성)"
    )
    project_id: int | None = Field(default=None, description="참고할 기존 프로젝트 ID (선택)")
    company_profile_id: int | None = Field(
        default=None, description="연결할 리서치 목표 기업 ID (선택)"
    )
    focus_weakness: str = Field(
        default="", description="보완하고 싶은 포트폴리오 캐릭터 약점 (선택)"
    )
    chat_history: list[CopilotChatMessage] = Field(default_factory=list)


class ApplicationRetrospectRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    role: str = Field(default="", max_length=200)
    stage: str = Field(default="서류", max_length=50, description="서류 / 코테 / 면접")
    status: str = Field(default="불합격", max_length=50, description="합격 / 불합격 / 진행중")
    feedback_memo: str = Field(..., min_length=5, description="지원 결과 및 복기 메모")


class ApplicationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    role: str
    stage: str
    status: str
    feedback_memo: str
    gap_analysis: str
    action_plan: str
    created_at: datetime
