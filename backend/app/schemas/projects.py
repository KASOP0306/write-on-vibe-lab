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


class ProjectDetailResponse(ProjectResponse):
    experiences: list[ExperienceSummary] = Field(default_factory=list)


class ProjectRecapResponse(BaseModel):
    project_id: int
    project_name: str
    experience_count: int
    markdown: str


class GitHubAnalyzeRequest(BaseModel):
    repo_url: str = Field(..., min_length=10, description="GitHub 저장소 URL")
    role_hint: str = Field(default="", max_length=200, description="본인 담당 역할 힌트 (선택)")
    extra_context: str = Field(default="", description="강조하고 싶은 추가 맥락 (선택)")


class SuggestedExperienceDraft(BaseModel):
    title: str
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    quantified_metrics: str = ""


class GitHubAnalyzeResponse(BaseModel):
    project: ProjectCreateRequest
    portfolio_markdown: str
    suggested_experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)
    repo_meta: dict = Field(default_factory=dict)


class GitHubImportRequest(BaseModel):
    project: ProjectCreateRequest
    experiences: list[SuggestedExperienceDraft] = Field(default_factory=list)


class GitHubImportResponse(BaseModel):
    project: ProjectResponse
    saved_experience_ids: list[int] = Field(default_factory=list)
    vector_synced_count: int = 0
