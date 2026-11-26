from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactLink(BaseModel):
    label: str = Field(default="", max_length=100)
    url: str = Field(..., min_length=1, max_length=1000)


class ExperienceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    title: str
    situation: str
    task: str
    action: str
    result: str
    learning: str = ""
    quantified_metrics: str
    completeness_score: int
    star_scores: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ProjectSectionDraft(BaseModel):
    section_type: str = Field(..., min_length=1, max_length=60)
    track: str = Field(default="custom", max_length=40)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(default="")
    display_order: int = Field(default=0)


class ProjectSectionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    display_order: int | None = None
    track: str | None = Field(default=None, max_length=40)


class ProjectSectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    section_type: str
    track: str = "core"
    title: str
    content: str
    display_order: int
    updated_at: datetime
    vector_synced: bool | None = None


class ProjectDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    filename: str
    source_type: str
    file_format: str
    extracted_summary: str
    raw_char_count: int
    applied_sections: list[str]
    created_at: datetime


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    period: str = Field(default="", max_length=100)
    role: str = Field(default="", max_length=200)
    summary: str = Field(default="")
    tech_stack: list[str] = Field(default_factory=list)
    portfolio_goal_link: str = Field(default="")
    repo_url: str = Field(default="", max_length=500)
    project_types: list[str] = Field(
        default_factory=lambda: ["engineering"],
        description="복수 선택 가능한 프로젝트 유형 트랙 배열",
    )
    artifact_links: list[ArtifactLink] = Field(
        default_factory=list,
        description="참고 결과물 링크 (Figma, Notion, 발표자료, 블로그 등)",
    )


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    period: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, max_length=200)
    summary: str | None = None
    tech_stack: list[str] | None = None
    portfolio_goal_link: str | None = None
    repo_url: str | None = Field(default=None, max_length=500)
    project_types: list[str] | None = None
    artifact_links: list[ArtifactLink] | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    period: str
    role: str
    summary: str
    tech_stack: list[str]
    portfolio_goal_link: str
    repo_url: str
    project_types: list[str] = Field(default_factory=lambda: ["engineering"])
    artifact_links: list[dict[str, str]] = Field(default_factory=list)
    is_portfolio_selected: bool = False
    created_at: datetime
    experience_count: int = 0
    filled_section_count: int = 0
    total_section_count: int = 0
    document_count: int = 0


class ProjectDetailResponse(ProjectResponse):
    experiences: list[ExperienceSummary] = Field(default_factory=list)
    sections: list[ProjectSectionResponse] = Field(default_factory=list)
    documents: list[ProjectDocumentResponse] = Field(default_factory=list)
    assembled_markdown: str = ""
    star_averages: dict[str, Any] = Field(default_factory=dict)
    retrospective: dict[str, Any] = Field(default_factory=dict)


class ProjectRecapResponse(BaseModel):
    project_id: int
    project_name: str
    experience_count: int
    markdown: str


class AddTracksRequest(BaseModel):
    add_types: list[str] = Field(..., min_length=1, description="추가할 프로젝트 유형 트랙 ID 목록")


class AddTracksResponse(BaseModel):
    project_types: list[str]
    added_section_types: list[str]


class GitHubAnalyzeRequest(BaseModel):
    repo_url: str = Field(..., min_length=3, description="GitHub 저장소 URL 또는 owner/repo")
    project_types: list[str] = Field(
        default_factory=lambda: ["engineering"],
        description="조합할 프로젝트 유형 트랙 목록",
    )
    github_token: str = Field(
        default="",
        description="선택: Private 저장소 또는 Rate Limit 우회용 1회용 PAT (DB 미저장)",
    )
    role_hint: str = Field(default="", max_length=200, description="본인 담당 역할 힌트 (선택)")
    extra_context: str = Field(default="", description="강조하고 싶은 추가 맥락 (선택)")


class GitHubSyncRequest(BaseModel):
    repo_url: str = Field(default="", description="미입력 시 프로젝트에 저장된 repo_url 사용")
    github_token: str = Field(default="", description="선택: 1회용 PAT (DB 미저장)")
    instruction: str = Field(default="", description="선택: 반영 시 강조할 지시사항")


class SuggestedExperienceDraft(BaseModel):
    title: str
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    learning: str = ""
    quantified_metrics: str = ""


class GitHubAnalyzeResponse(BaseModel):
    project: ProjectCreateRequest
    sections: list[ProjectSectionDraft] = Field(default_factory=list)
    portfolio_markdown: str
    suggested_experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)
    repo_meta: dict[str, Any] = Field(default_factory=dict)


class DocumentToProjectResponse(BaseModel):
    project: ProjectCreateRequest
    sections: list[ProjectSectionDraft] = Field(default_factory=list)
    portfolio_markdown: str
    suggested_experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)
    source_meta: dict[str, Any] = Field(default_factory=dict)


class StructuredProjectImportRequest(BaseModel):
    project: ProjectCreateRequest
    sections: list[ProjectSectionDraft] = Field(default_factory=list)
    experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)
    source_filename: str = Field(default="")
    source_type: str = Field(default="github_repo")
    source_format: str = Field(default="github")
    source_summary: str = Field(default="")


# 하위 호환 alias
GitHubImportRequest = StructuredProjectImportRequest


class GitHubImportResponse(BaseModel):
    project: ProjectResponse
    saved_section_count: int = 0
    saved_experience_ids: list[int] = Field(default_factory=list)
    vector_synced_count: int = 0


class SectionDiffItem(BaseModel):
    section_id: int | None = None
    section_type: str
    track: str = "core"
    title: str
    action: str = "update"
    change_summary: str = ""
    before_content: str = ""
    proposed_content: str = ""


class DocumentIngestProposalResponse(BaseModel):
    filename: str
    source_type: str
    file_format: str
    raw_char_count: int
    parse_info: str = ""
    document_summary: str = ""
    suggested_summary: str = ""
    suggested_tech_stack_additions: list[str] = Field(default_factory=list)
    section_updates: list[SectionDiffItem] = Field(default_factory=list)
    suggested_experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)


class SectionUpdateApplyItem(BaseModel):
    section_id: int | None = None
    section_type: str
    track: str = "core"
    title: str
    content: str


class ApplyProjectUpdatesRequest(BaseModel):
    filename: str = Field(default="manual-update.md")
    source_type: str = Field(default="file_upload")
    file_format: str = Field(default="md")
    document_summary: str = Field(default="")
    raw_char_count: int = Field(default=0)
    updated_summary: str | None = None
    tech_stack_additions: list[str] = Field(default_factory=list)
    section_updates: list[SectionUpdateApplyItem] = Field(default_factory=list)
    experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)


class ApplyProjectUpdatesResponse(BaseModel):
    updated_section_types: list[str] = Field(default_factory=list)
    saved_experience_ids: list[int] = Field(default_factory=list)
    document_id: int | None = None
    vector_synced_count: int = 0


class SectionPruneDiffItem(BaseModel):
    section_id: int
    section_type: str
    title: str
    removed_items: list[str] = Field(default_factory=list)
    reason: str = ""
    before_content: str = ""
    cleaned_content: str = ""


class PruneProposalResponse(BaseModel):
    overall_assessment: str = ""
    section_prunes: list[SectionPruneDiffItem] = Field(default_factory=list)


class PruneApplyItem(BaseModel):
    section_id: int
    cleaned_content: str


class PruneApplyRequest(BaseModel):
    updates: list[PruneApplyItem] = Field(default_factory=list)


class PruneApplyResponse(BaseModel):
    updated_count: int = 0
    vector_synced_count: int = 0


# ==============================================================================
# 섹션 단일 문서 AI 업데이트 · 선택형 STAR 역질문 · 5축 STAR 채점 · 6축 캐릭터 진단
# ==============================================================================
class SectionIngestProposalResponse(BaseModel):
    section_id: int
    section_type: str
    track: str = "core"
    title: str
    filename: str
    source_type: str
    file_format: str
    raw_char_count: int
    parse_info: str = ""
    document_summary: str = ""
    change_summary: str = ""
    before_content: str = ""
    proposed_content: str = ""
    added_facts: list[str] = Field(default_factory=list)
    suggested_tech_stack_additions: list[str] = Field(default_factory=list)


class StarOnboardingQuestion(BaseModel):
    id: str
    target_axis: str
    question: str
    rationale: str = ""
    example_hint: str = ""


class StarOnboardingQuestionsResponse(BaseModel):
    diagnosis_summary: str = ""
    weak_axes: list[str] = Field(default_factory=list)
    questions: list[StarOnboardingQuestion] = Field(default_factory=list)


class StarOnboardingAnswerItem(BaseModel):
    target_axis: str = ""
    question: str
    answer: str = ""


class StarOnboardingApplyRequest(BaseModel):
    answers: list[StarOnboardingAnswerItem] = Field(default_factory=list)
    apply_section_patches: bool = Field(
        default=True, description="답변에서 도출된 프로젝트 섹션 보강안도 자동 반영할지 여부"
    )


class StarOnboardingApplyResponse(BaseModel):
    saved_experiences: list[ExperienceSummary] = Field(default_factory=list)
    applied_section_types: list[str] = Field(default_factory=list)
    section_patches: list[dict[str, Any]] = Field(default_factory=list)
    vector_synced_count: int = 0


class ProjectStarEvaluateResponse(BaseModel):
    evaluated_count: int = 0
    experiences: list[ExperienceSummary] = Field(default_factory=list)
    star_averages: dict[str, Any] = Field(default_factory=dict)


class PortfolioDiagnosisRequest(BaseModel):
    external_notes: dict[str, str] | None = Field(
        default=None,
        description="선택: 외적 역량 보충 메모 (time_execution / people_collaboration / adaptability_growth)",
    )


class PortfolioSelectionRequest(BaseModel):
    project_ids: list[int] = Field(
        default_factory=list,
        max_length=4,
        description="대표 포트폴리오 600 XP 산정에 포함할 프로젝트 ID 목록 (최대 4개)",
    )


class PortfolioDiagnosisResponse(BaseModel):
    diagnosis: dict[str, Any] = Field(default_factory=dict)
    external_notes: dict[str, str] = Field(default_factory=dict)
    overall_star_averages: dict[str, Any] = Field(default_factory=dict)
    portfolio_xp: dict[str, Any] = Field(default_factory=dict)
    project_count: int = 0


# ==============================================================================
# 프로젝트 회고 인터뷰 & 프로젝트 간 학습 루프 (Try 인계)
# ==============================================================================
class ProjectRetroQuestionsRequest(BaseModel):
    framework: str = Field(
        default="kpt", description="kpt | 4ls | postmortem"
    )


class ProjectRetroQuestion(BaseModel):
    id: str
    dimension: str
    question: str
    why_ask: str = ""
    example_hint: str = ""


class ProjectRetroQuestionsResponse(BaseModel):
    framework: str = "kpt"
    opening_note: str = ""
    questions: list[ProjectRetroQuestion] = Field(default_factory=list)


class ProjectRetroAnswerItem(BaseModel):
    dimension: str = ""
    question: str
    answer: str = ""


class ProjectRetroApplyRequest(BaseModel):
    framework: str = Field(default="kpt")
    answers: list[ProjectRetroAnswerItem] = Field(default_factory=list)
    sync_to_outcomes_section: bool = Field(
        default=True,
        description="정리된 회고 요약을 프로젝트의 '성과, 지표 & 회고(outcomes)' 섹션에도 자동 반영",
    )


class ProjectRetroApplyResponse(BaseModel):
    retrospective: dict[str, Any] = Field(default_factory=dict)
    outcomes_synced: bool = False
    vector_synced: bool = False


class LearningLoopItem(BaseModel):
    project_id: int
    project_name: str
    framework: str = "kpt"
    try_items: list[str] = Field(default_factory=list)
    decision_revisit: str = ""
    updated_at: str = ""


class LearningLoopResponse(BaseModel):
    items: list[LearningLoopItem] = Field(default_factory=list)
    total_try_count: int = 0
