"""Projects CRUD 및 프로젝트 기반 포트폴리오 Markdown 리캡 생성 라우터."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.bedrock import get_smart_llm
from app.core.database import Experience, Project, UserProfile, get_db_session
from app.core.vector_store import DocType, try_upsert_document
from app.schemas.projects import (
    ExperienceSummary,
    GitHubAnalyzeRequest,
    GitHubAnalyzeResponse,
    GitHubImportRequest,
    GitHubImportResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectRecapResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.tools.github_analyzer import (
    GitHubAnalyzerError,
    analyze_github_to_portfolio,
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


@router.post("/analyze-github", response_model=GitHubAnalyzeResponse)
async def analyze_github_repo(
    payload: GitHubAnalyzeRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GitHubAnalyzeResponse:
    """GitHub 저장소 URL을 분석해 프로젝트 정보, 포트폴리오 Markdown, STAR 경험 초안을 자동 생성한다."""
    profile = await session.get(UserProfile, 1)
    profile_context = ""
    if profile:
        profile_context = (
            f"희망 직무: {profile.target_roles}\n"
            f"커리어 비전: {profile.career_vision}\n"
            f"핵심 신념: {profile.core_beliefs}"
        ).strip()

    try:
        result = await analyze_github_to_portfolio(
            payload.repo_url,
            role_hint=payload.role_hint.strip(),
            extra_context=payload.extra_context.strip(),
            profile_context=profile_context,
        )
    except GitHubAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:
        logger.exception("GitHub portfolio analysis failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"GitHub 저장소 분석 중 오류가 발생했습니다: {exc}",
        )

    return GitHubAnalyzeResponse.model_validate(result)


@router.post(
    "/import-github",
    response_model=GitHubImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_github_project(
    payload: GitHubImportRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GitHubImportResponse:
    """분석·편집된 GitHub 프로젝트와 선택한 STAR 경험 초안을 DB 및 벡터 저장소에 일괄 저장한다."""
    p = payload.project
    project = Project(
        name=p.name.strip(),
        period=p.period.strip(),
        role=p.role.strip(),
        summary=p.summary.strip(),
        tech_stack=[t.strip() for t in p.tech_stack if t.strip()],
        portfolio_goal_link=p.portfolio_goal_link.strip(),
        repo_url=p.repo_url.strip(),
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    saved_exp_ids: list[int] = []
    vector_synced_count = 0

    for item in payload.experiences:
        title = item.title.strip()
        if not title:
            continue
        score = 75 if item.quantified_metrics.strip() else 60
        exp = Experience(
            project_id=project.id,
            title=title[:300],
            situation=item.situation.strip(),
            task=item.task.strip(),
            action=item.action.strip(),
            result=item.result.strip(),
            quantified_metrics=item.quantified_metrics.strip(),
            completeness_score=score,
            raw_notes=f"[GitHub 자동 추출] {project.repo_url}",
        )
        session.add(exp)
        await session.commit()
        await session.refresh(exp)
        saved_exp_ids.append(exp.id)

        vector_content = (
            f"[프로젝트] {project.name}\n"
            f"[경험 제목] {exp.title}\n"
            f"[Situation] {exp.situation}\n"
            f"[Task] {exp.task}\n"
            f"[Action] {exp.action}\n"
            f"[Result] {exp.result}\n"
            f"[정량 지표] {exp.quantified_metrics}"
        )
        synced = await try_upsert_document(
            session,
            doc_type=DocType.EXPERIENCE,
            ref_id=f"exp-{exp.id}",
            content=vector_content,
            metadata={
                "experience_id": exp.id,
                "project_id": project.id,
                "title": exp.title,
                "source": "github_import",
                "repo_url": project.repo_url,
            },
        )
        if synced:
            vector_synced_count += 1

    proj_resp = ProjectResponse.model_validate(project)
    proj_resp.experience_count = len(saved_exp_ids)
    return GitHubImportResponse(
        project=proj_resp,
        saved_experience_ids=saved_exp_ids,
        vector_synced_count=vector_synced_count,
    )


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
