"""Projects CRUD 및 프로젝트 기반 포트폴리오 Markdown 리캡 생성 라우터."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.bedrock import get_smart_llm
from app.core.database import Experience, Project, UserProfile, get_db_session
from app.schemas.projects import (
    ExperienceSummary,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectRecapResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectResponse]:
    count_subq = (
        select(
            Experience.project_id,
            func.count(Experience.id).label("exp_count"),
        )
        .group_by(Experience.project_id)
        .subquery()
    )

    stmt = (
        select(Project, func.coalesce(count_subq.c.exp_count, 0))
        .outerjoin(count_subq, Project.id == count_subq.c.project_id)
        .order_by(Project.created_at.desc(), Project.id.desc())
    )
    rows = (await session.execute(stmt)).all()

    results: list[ProjectResponse] = []
    for project, exp_count in rows:
        item = ProjectResponse.model_validate(project)
        item.experience_count = int(exp_count)
        results.append(item)
    return results


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectDetailResponse:
    stmt = (
        select(Project)
        .options(selectinload(Project.experiences))
        .where(Project.id == project_id)
    )
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    experiences = sorted(project.experiences, key=lambda e: e.created_at, reverse=True)
    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        period=project.period,
        role=project.role,
        summary=project.summary,
        tech_stack=list(project.tech_stack or []),
        portfolio_goal_link=project.portfolio_goal_link,
        repo_url=project.repo_url,
        created_at=project.created_at,
        experience_count=len(experiences),
        experiences=[ExperienceSummary.model_validate(e) for e in experiences],
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    project = Project(
        name=payload.name.strip(),
        period=payload.period.strip(),
        role=payload.role.strip(),
        summary=payload.summary.strip(),
        tech_stack=[t.strip() for t in payload.tech_stack if t.strip()],
        portfolio_goal_link=payload.portfolio_goal_link.strip(),
        repo_url=payload.repo_url.strip(),
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    payload: ProjectUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "tech_stack" and value is not None:
            setattr(project, field, [t.strip() for t in value if t.strip()])
        elif isinstance(value, str):
            setattr(project, field, value.strip())
        elif value is not None:
            setattr(project, field, value)

    await session.commit()
    await session.refresh(project)

    exp_count_stmt = select(func.count(Experience.id)).where(
        Experience.project_id == project.id
    )
    exp_count = int((await session.execute(exp_count_stmt)).scalar_one())

    response = ProjectResponse.model_validate(project)
    response.experience_count = exp_count
    return response


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    await session.delete(project)
    await session.commit()


@router.post("/{project_id}/recap", response_model=ProjectRecapResponse)
async def generate_project_recap(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectRecapResponse:
    """프로젝트 메타정보 + 소속 STAR 경험 + 커리어 신념을 종합해 포트폴리오 Markdown 리캡을 생성한다."""
    stmt = (
        select(Project)
        .options(selectinload(Project.experiences))
        .where(Project.id == project_id)
    )
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    profile = await session.get(UserProfile, 1)
    experiences = sorted(project.experiences, key=lambda e: e.created_at)

    exp_blocks = []
    for idx, exp in enumerate(experiences, start=1):
        exp_blocks.append(
            f"### 경험 {idx}: {exp.title}\n"
            f"- Situation: {exp.situation}\n"
            f"- Task: {exp.task}\n"
            f"- Action: {exp.action}\n"
            f"- Result: {exp.result}\n"
            f"- 정량 성과: {exp.quantified_metrics}\n"
            f"- 완성도 점수: {exp.completeness_score}/100"
        )
    experiences_text = (
        "\n\n".join(exp_blocks)
        if exp_blocks
        else "(아직 연결된 STAR 경험이 없습니다. 프로젝트 개요를 바탕으로 초안 구조와 보완 필요 항목을 정리해 주세요.)"
    )

    profile_text = ""
    if profile:
        profile_text = (
            f"- 커리어 비전: {profile.career_vision}\n"
            f"- 핵심 신념: {profile.core_beliefs}\n"
            f"- 희망 직무: {profile.target_roles}\n"
            f"- 선호 문체: {profile.preferred_tone}"
        )

    system_prompt = (
        "당신은 시니어 테크 리크루터이자 포트폴리오 에디터입니다. "
        "제공된 사실(프로젝트 정보, STAR 경험, 커리어 신념)만을 근거로 "
        "이력서/노션 포트폴리오에 바로 붙여넣을 수 있는 깔끔한 한국어 Markdown 리캡 문서를 작성하세요.\n"
        "규칙:\n"
        "1. 제공되지 않은 수치, 기술명, 성과를 임의로 지어내지 마세요(환각 엄금).\n"
        "2. 섹션 구성: `# 프로젝트명`, `## 개요 및 역할`, `## 기술 스택`, `## 핵심 문제 해결 및 성과(STAR 기반)`, `## 커리어 비전과의 연결`, `## 보완 추천 항목`.\n"
        "3. 상투적인 AI 수식어를 배제하고 구체적인 행동 동사와 실제 기술명 위주로 간결하게 작성하세요."
    )

    user_prompt = (
        f"[프로젝트 정보]\n"
        f"- 이름: {project.name}\n"
        f"- 기간: {project.period}\n"
        f"- 역할: {project.role}\n"
        f"- 요약: {project.summary}\n"
        f"- 기술 스택: {', '.join(project.tech_stack or [])}\n"
        f"- 포트폴리오 목표 연결점: {project.portfolio_goal_link}\n"
        f"- 저장소 URL: {project.repo_url}\n\n"
        f"[지원자 커리어 신념/문체]\n{profile_text or '(미설정)'}\n\n"
        f"[연결된 STAR 경험 목록 ({len(experiences)}건)]\n{experiences_text}"
    )

    try:
        llm = get_smart_llm(temperature=0.3)
        ai_msg = await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        markdown_text = (
            ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
        )
    except Exception as exc:
        logger.exception("Failed to generate project recap via AWS Bedrock: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AWS Bedrock recap generation failed: {exc}",
        )

    return ProjectRecapResponse(
        project_id=project.id,
        project_name=project.name,
        experience_count=len(experiences),
        markdown=markdown_text,
    )
