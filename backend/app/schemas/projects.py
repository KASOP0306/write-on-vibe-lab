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
