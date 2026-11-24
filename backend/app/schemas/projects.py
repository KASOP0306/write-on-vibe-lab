from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExperienceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    title: str
    situation: str
    task: str
    action: str
    result: str
    quantified_metrics: str
    completeness_score: int
    created_at: datetime


class ProjectSectionDraft(BaseModel):
    section_type: str = Field(..., min_length=1, max_length=60)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(default="")
    display_order: int = Field(default=0)


class ProjectSectionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    display_order: int | None = None


class ProjectSectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    section_type: str
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


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    period: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, max_length=200)
    summary: str | None = None
    tech_stack: list[str] | None = None
    portfolio_goal_link: str | None = None
    repo_url: str | None = Field(default=None, max_length=500)


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


class ProjectRecapResponse(BaseModel):
    project_id: int
    project_name: str
    experience_count: int
    markdown: str


class GitHubAnalyzeRequest(BaseModel):
    repo_url: str = Field(..., min_length=3, description="GitHub 저장소 URL 또는 owner/repo")
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
    quantified_metrics: str = ""


class GitHubAnalyzeResponse(BaseModel):
    project: ProjectCreateRequest
    sections: list[ProjectSectionDraft] = Field(default_factory=list)
    portfolio_markdown: str
    suggested_experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)
    repo_meta: dict = Field(default_factory=dict)


class GitHubImportRequest(BaseModel):
    project: ProjectCreateRequest
    sections: list[ProjectSectionDraft] = Field(default_factory=list)
    experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)


class GitHubImportResponse(BaseModel):
    project: ProjectResponse
    saved_section_count: int = 0
    saved_experience_ids: list[int] = Field(default_factory=list)
    vector_synced_count: int = 0


class SectionDiffItem(BaseModel):
    section_id: int | None = None
    section_type: str
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
