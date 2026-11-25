"""Projects CRUD, 조합형 멀티트랙 포트폴리오 워크스페이스, 문서/GitHub 기반 생성·업데이트, AI 노이즈 정리 라우터."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.sse import (
    create_sse_response,
    sse_done,
    sse_error,
    sse_node_end,
    sse_node_start,
)
from app.core.bedrock import get_smart_llm
from app.core.database import (
    Experience,
    Project,
    ProjectDocument,
    ProjectSection,
    UserProfile,
    get_db_session,
)
from app.core.project_templates import (
    ALL_KNOWN_SECTIONS,
    compose_sections_for_types,
    get_combined_ai_guidance,
    get_templates_payload,
    infer_track_for_section_type,
    normalize_project_types,
)
from app.core.star_rubric import (
    compute_average_star_axes,
    evaluate_star_experience_rubric,
    get_rubric_reference_payload,
    normalize_star_scores,
)
from app.core.vector_store import DocType, delete_document, try_upsert_document
from app.schemas.projects import (
    AddTracksRequest,
    AddTracksResponse,
    ApplyProjectUpdatesRequest,
    ApplyProjectUpdatesResponse,
    DocumentIngestProposalResponse,
    DocumentToProjectResponse,
    ExperienceSummary,
    GitHubAnalyzeRequest,
    GitHubAnalyzeResponse,
    GitHubImportResponse,
    GitHubSyncRequest,
    LearningLoopItem,
    LearningLoopResponse,
    PortfolioDiagnosisRequest,
    PortfolioDiagnosisResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectDocumentResponse,
    ProjectRecapResponse,
    ProjectResponse,
    ProjectRetroApplyRequest,
    ProjectRetroApplyResponse,
    ProjectRetroQuestionsRequest,
    ProjectRetroQuestionsResponse,
    ProjectSectionDraft,
    ProjectSectionResponse,
    ProjectSectionUpdateRequest,
    ProjectStarEvaluateResponse,
    ProjectUpdateRequest,
    PruneApplyRequest,
    PruneApplyResponse,
    PruneProposalResponse,
    SectionIngestProposalResponse,
    StarOnboardingApplyRequest,
    StarOnboardingApplyResponse,
    StarOnboardingQuestionsResponse,
    StructuredProjectImportRequest,
)
from app.tools.document_parser import DocumentParseError, parse_uploaded_file
from app.tools.github_analyzer import (
    GitHubAnalyzerError,
    analyze_github_to_portfolio,
    fetch_github_repo_context,
    format_repo_context_as_document,
    synthesize_portfolio_from_context,
)
from app.tools.portfolio_manager import (
    analyze_document_to_portfolio,
    diagnose_portfolio_character,
    generate_project_retro_questions,
    generate_star_onboarding_questions,
    propose_document_updates,
    propose_noise_pruning,
    propose_section_document_update,
    render_portfolio_markdown,
    synthesize_project_retrospective,
    synthesize_star_onboarding_answers,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "period": project.period,
        "role": project.role,
        "summary": project.summary,
        "tech_stack": list(project.tech_stack or []),
        "portfolio_goal_link": project.portfolio_goal_link,
        "repo_url": project.repo_url,
        "project_types": normalize_project_types(project.project_types),
        "artifact_links": list(project.artifact_links or []),
    }


def _section_to_dict(sec: ProjectSection) -> dict[str, Any]:
    return {
        "id": sec.id,
        "project_id": sec.project_id,
        "section_type": sec.section_type,
        "track": sec.track or infer_track_for_section_type(sec.section_type),
        "title": sec.title,
        "content": sec.content,
        "display_order": sec.display_order,
    }


def _clean_artifact_links(links: list[Any] | None) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in links or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        label = str(item.get("label") or "").strip()
        if url:
            cleaned.append({"label": label or url, "url": url})
    return cleaned


def _parse_types_form_field(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return ["engineering"]
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return normalize_project_types([str(x) for x in parsed])
        except json.JSONDecodeError:
            pass
    return normalize_project_types([x.strip() for x in text.split(",") if x.strip()])


async def _sync_section_vector(
    session: AsyncSession, project: Project, section: ProjectSection
) -> bool:
    ref_id = f"proj-{project.id}-sec-{section.id}"
    content = (section.content or "").strip()
    if not content:
        await delete_document(session, doc_type=DocType.EXPERIENCE, ref_id=ref_id)
        return False

    project_types = normalize_project_types(project.project_types)
    track = section.track or infer_track_for_section_type(section.section_type)
    vector_text = (
        f"[프로젝트] {project.name} ({project.role})\n"
        f"[프로젝트 유형] {', '.join(project_types)}\n"
        f"[포트폴리오 섹션 | {track}] {section.title} ({section.section_type})\n"
        f"[기술/역량/도구] {', '.join(project.tech_stack or [])}\n"
        f"{content}"
    )
    return await try_upsert_document(
        session,
        doc_type=DocType.EXPERIENCE,
        ref_id=ref_id,
        content=vector_text,
        metadata={
            "project_id": project.id,
            "project_name": project.name,
            "project_types": project_types,
            "section_id": section.id,
            "section_type": section.section_type,
            "section_track": track,
            "source": "project_section",
        },
    )


async def _load_project_full(session: AsyncSession, project_id: int) -> Project:
    stmt = (
        select(Project)
        .options(
            selectinload(Project.experiences),
            selectinload(Project.sections),
            selectinload(Project.documents),
        )
        .where(Project.id == project_id)
    )
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    return project


async def _ensure_sections_for_project_types(
    session: AsyncSession, project: Project
) -> list[str]:
    existing_types = {s.section_type for s in project.sections}
    composed = compose_sections_for_types(project.project_types)
    added: list[str] = []

    for tpl in composed:
        st = tpl["section_type"]
        if st not in existing_types:
            initial_content = (
                project.summary
                if st == "overview" and project.summary.strip()
                else ""
            )
            session.add(
                ProjectSection(
                    project_id=project.id,
                    section_type=st,
                    track=tpl["track"],
                    title=tpl["title"],
                    content=initial_content,
                    display_order=tpl["display_order"],
                )
            )
            added.append(st)

    if added:
        await session.commit()
    return added


# ==============================================================================
# 1. 템플릿 레지스트리, 프로젝트 목록, 문서/GitHub 기반 멀티트랙 자동 생성
# ==============================================================================
@router.get("/templates")
async def get_project_templates() -> dict[str, Any]:
    """공통 코어 + 5종 조합형 프로젝트 유형 트랙 팩 메타데이터를 반환한다."""
    return get_templates_payload()


@router.get("/rubric-reference")
async def get_rubric_reference() -> dict[str, Any]:
    """5축 STAR-L BARS 및 6축 포트폴리오 캐릭터 진단 레퍼런스 기준표를 반환한다."""
    return get_rubric_reference_payload()


@router.get("/learning-loop", response_model=LearningLoopResponse)
async def get_projects_learning_loop(
    session: AsyncSession = Depends(get_db_session),
) -> LearningLoopResponse:
    """이전 프로젝트들의 회고에서 도출된 Try 규칙(프로젝트 간 학습 루프)을 모아 반환한다."""
    projects = (
        (await session.execute(select(Project).order_by(Project.created_at.desc())))
        .scalars()
        .all()
    )
    items: list[LearningLoopItem] = []
    total_try = 0
    for p in projects:
        retro = p.retrospective or {}
        tries = [str(t).strip() for t in (retro.get("try_items") or []) if str(t).strip()]
        if tries or retro.get("decision_revisit"):
            items.append(
                LearningLoopItem(
                    project_id=p.id,
                    project_name=p.name,
                    framework=str(retro.get("framework") or "kpt"),
                    try_items=tries,
                    decision_revisit=str(retro.get("decision_revisit") or ""),
                    updated_at=str(retro.get("updated_at") or ""),
                )
            )
            total_try += len(tries)
    return LearningLoopResponse(items=items, total_try_count=total_try)


@router.get("/portfolio-diagnosis", response_model=PortfolioDiagnosisResponse)
async def get_portfolio_diagnosis(
    session: AsyncSession = Depends(get_db_session),
) -> PortfolioDiagnosisResponse:
    """캐시된 전체 포트폴리오 캐릭터 진단 + 전체 평균 STAR-L 5축 점수를 반환한다."""
    profile = await session.get(UserProfile, 1)
    projects = (
        (await session.execute(select(Project.id))).scalars().all()
    )
    all_exps = (await session.execute(select(Experience))).scalars().all()
    star_avg = compute_average_star_axes(
        [{"star_scores": e.star_scores} for e in all_exps]
    )
    return PortfolioDiagnosisResponse(
        diagnosis=dict(profile.portfolio_diagnosis or {}) if profile else {},
        external_notes=dict(profile.external_competency_notes or {}) if profile else {},
        overall_star_averages=star_avg,
        project_count=len(projects),
    )


@router.post("/portfolio-diagnosis", response_model=PortfolioDiagnosisResponse)
async def run_portfolio_diagnosis(
    payload: PortfolioDiagnosisRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PortfolioDiagnosisResponse:
    """전체 프로젝트·섹션·STAR·신념·외적 보충 메모를 종합해 6축 육각형 포트폴리오 캐릭터를 진단·저장한다."""
    profile = await session.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)

    merged_ext = dict(profile.external_competency_notes or {})
    if payload.external_notes is not None:
        for k, v in payload.external_notes.items():
            merged_ext[str(k).strip()] = str(v or "").strip()
        profile.external_competency_notes = merged_ext
        await session.commit()

    stmt = (
        select(Project)
        .options(
            selectinload(Project.sections),
            selectinload(Project.experiences),
        )
        .order_by(Project.created_at.desc(), Project.id.desc())
    )
    projects = (await session.execute(stmt)).scalars().all()
    if not projects:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="진단할 프로젝트가 아직 없습니다. 먼저 프로젝트를 1개 이상 등록해 주세요.",
        )

    projects_payload = [
        {
            **_project_to_dict(p),
            "retrospective": dict(p.retrospective or {}),
            "sections": [_section_to_dict(s) for s in p.sections],
            "experiences": [
                {
                    "id": e.id,
                    "title": e.title,
                    "situation": e.situation,
                    "task": e.task,
                    "action": e.action,
                    "result": e.result,
                    "quantified_metrics": e.quantified_metrics,
                    "completeness_score": e.completeness_score,
                    "star_scores": normalize_star_scores(e.star_scores),
                }
                for e in p.experiences
            ],
        }
        for p in projects
    ]
    profile_dict = {
        "career_vision": profile.career_vision,
        "core_beliefs": profile.core_beliefs,
        "target_roles": profile.target_roles,
        "preferred_tone": profile.preferred_tone,
    }

    try:
        diagnosis = await diagnose_portfolio_character(
            profile=profile_dict,
            projects=projects_payload,
            external_notes=merged_ext,
        )
    except Exception as exc:
        logger.exception("Portfolio character diagnosis failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"포트폴리오 캐릭터 진단 중 오류가 발생했습니다: {exc}",
        )

    profile.portfolio_diagnosis = diagnosis
    await session.commit()

    all_exps = (await session.execute(select(Experience))).scalars().all()
    star_avg = compute_average_star_axes(
        [{"star_scores": e.star_scores} for e in all_exps]
    )

    return PortfolioDiagnosisResponse(
        diagnosis=diagnosis,
        external_notes=merged_ext,
        overall_star_averages=star_avg,
        project_count=len(projects),
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    project_type: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectResponse]:
    exp_subq = (
        select(
            Experience.project_id,
            func.count(Experience.id).label("exp_count"),
        )
        .group_by(Experience.project_id)
        .subquery()
    )
    sec_subq = (
        select(
            ProjectSection.project_id,
            func.count(ProjectSection.id).label("total_sec"),
            func.sum(
                case((func.length(func.trim(ProjectSection.content)) > 0, 1), else_=0)
            ).label("filled_sec"),
        )
        .group_by(ProjectSection.project_id)
        .subquery()
    )
    doc_subq = (
        select(
            ProjectDocument.project_id,
            func.count(ProjectDocument.id).label("doc_count"),
        )
        .group_by(ProjectDocument.project_id)
        .subquery()
    )

    stmt = (
        select(
            Project,
            func.coalesce(exp_subq.c.exp_count, 0),
            func.coalesce(sec_subq.c.filled_sec, 0),
            func.coalesce(sec_subq.c.total_sec, 0),
            func.coalesce(doc_subq.c.doc_count, 0),
        )
        .outerjoin(exp_subq, Project.id == exp_subq.c.project_id)
        .outerjoin(sec_subq, Project.id == sec_subq.c.project_id)
        .outerjoin(doc_subq, Project.id == doc_subq.c.project_id)
        .order_by(Project.created_at.desc(), Project.id.desc())
    )
    rows = (await session.execute(stmt)).all()

    results: list[ProjectResponse] = []
    for project, exp_count, filled_sec, total_sec, doc_count in rows:
        norm_types = normalize_project_types(project.project_types)
        if project_type and project_type not in norm_types:
            continue
        item = ProjectResponse.model_validate(project)
        item.project_types = norm_types
        item.artifact_links = list(project.artifact_links or [])
        item.experience_count = int(exp_count)
        item.filled_section_count = int(filled_sec)
        item.total_section_count = int(total_sec)
        item.document_count = int(doc_count)
        results.append(item)
    return results


@router.post("/analyze-document", response_model=DocumentToProjectResponse)
async def analyze_document_new_project(
    file: UploadFile | None = File(default=None),
    pasted_text: str = Form(default=""),
    doc_title: str = Form(default=""),
    project_types: str = Form(default='["product_planning"]'),
    role_hint: str = Form(default=""),
    extra_context: str = Form(default=""),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentToProjectResponse:
    """기획서·발표자료(.pptx/.pdf/.docx/.md/.ipynb) 또는 텍스트에서 선택한 복수 유형의 프로젝트 초안을 자동 생성한다."""
    parsed_types = _parse_types_form_field(project_types)

    if file is not None and file.filename:
        raw_bytes = await file.read()
        try:
            parsed = parse_uploaded_file(file.filename, raw_bytes)
        except DocumentParseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        filename = parsed["filename"]
        file_format = parsed["file_format"]
        doc_text = parsed["text"]
        parse_info = parsed["info"]
        source_type = "file_upload"
    elif pasted_text.strip():
        clean = pasted_text.strip()
        filename = doc_title.strip() or "프로젝트_문서.md"
        file_format = "md"
        doc_text = clean[:28000]
        parse_info = f"{len(clean.splitlines())} lines"
        source_type = "pasted_doc"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="업로드할 파일 또는 문서 텍스트를 입력해 주세요.",
        )

    profile = await session.get(UserProfile, 1)
    profile_context = ""
    if profile:
        profile_context = (
            f"희망 직무: {profile.target_roles}\n"
            f"커리어 비전: {profile.career_vision}\n"
            f"핵심 신념: {profile.core_beliefs}"
        ).strip()

    try:
        result = await analyze_document_to_portfolio(
            doc_text=doc_text,
            filename=filename,
            project_types=parsed_types,
            role_hint=role_hint.strip(),
            extra_context=extra_context.strip(),
            profile_context=profile_context,
        )
    except Exception as exc:
        logger.exception("Document-to-portfolio analysis failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"문서 기반 포트폴리오 생성 중 오류가 발생했습니다: {exc}",
        )

    return DocumentToProjectResponse(
        project=result["project"],
        sections=result["sections"],
        portfolio_markdown=result["portfolio_markdown"],
        suggested_experiences=result["suggested_experiences"],
        source_meta={
            "filename": filename,
            "source_type": source_type,
            "file_format": file_format,
            "parse_info": parse_info,
            "project_types": parsed_types,
        },
    )


@router.post("/analyze-github", response_model=GitHubAnalyzeResponse)
async def analyze_github_repo(
    payload: GitHubAnalyzeRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GitHubAnalyzeResponse:
    """GitHub 저장소 URL을 분석해 선택한 복수 유형의 모듈 섹션과 STAR 초안을 생성한다."""
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
            project_types=payload.project_types,
            github_token=payload.github_token.strip() or None,
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


@router.post("/analyze-github/stream")
async def analyze_github_repo_stream(
    payload: GitHubAnalyzeRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """SSE 스트리밍으로 GitHub 저장소 트리 스캔 → 멀티트랙 섹션 구조화 단계를 실시간 전송한다."""
    profile = await session.get(UserProfile, 1)
    profile_context = ""
    if profile:
        profile_context = (
            f"희망 직무: {profile.target_roles}\n"
            f"커리어 비전: {profile.career_vision}\n"
            f"핵심 신념: {profile.core_beliefs}"
        ).strip()

    normalized_types = normalize_project_types(payload.project_types)

    async def event_stream():
        try:
            yield sse_node_start(
                "fetch_repo",
                "GitHub 저장소 트리, 커밋 이력, 핵심 소스·문서 파일을 수집하는 중...",
            )
            repo_ctx = await fetch_github_repo_context(
                payload.repo_url,
                github_token=payload.github_token.strip() or None,
            )
            analyzed_files = (
                (["README.md"] if repo_ctx.get("readme_text") else [])
                + list((repo_ctx.get("inspected_files") or {}).keys())
            )
            yield sse_node_end(
                "fetch_repo",
                {
                    "full_name": repo_ctx["full_name"],
                    "file_count": len(analyzed_files),
                    "tree_count": len(repo_ctx.get("tree_paths") or []),
                },
            )

            yield sse_node_start(
                "synthesize_sections",
                f"수집한 파일 {len(analyzed_files)}개를 분석해 멀티트랙 포트폴리오 섹션과 STAR 초안을 작성하는 중...",
            )
            result = await synthesize_portfolio_from_context(
                repo_ctx,
                project_types=normalized_types,
                role_hint=payload.role_hint.strip(),
                extra_context=payload.extra_context.strip(),
                profile_context=profile_context,
            )
            yield sse_node_end(
                "synthesize_sections",
                {
                    "section_count": len(result.get("sections") or []),
                    "star_count": len(result.get("suggested_experiences") or []),
                },
            )
            yield sse_done(result)
        except GitHubAnalyzerError as exc:
            yield sse_error(str(exc))
        except Exception as exc:
            logger.exception("GitHub SSE analysis failed: %s", exc)
            yield sse_error(f"GitHub 저장소 분석 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())


async def _import_structured_project_impl(
    payload: StructuredProjectImportRequest,
    session: AsyncSession,
) -> GitHubImportResponse:
    p = payload.project
    normalized_types = normalize_project_types(p.project_types)
    cleaned_links = _clean_artifact_links(p.artifact_links)

    project = Project(
        name=p.name.strip(),
        period=p.period.strip(),
        role=p.role.strip(),
        summary=p.summary.strip(),
        tech_stack=[t.strip() for t in p.tech_stack if t.strip()],
        portfolio_goal_link=p.portfolio_goal_link.strip(),
        repo_url=p.repo_url.strip(),
        project_types=normalized_types,
        artifact_links=cleaned_links,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    vector_synced_count = 0
    saved_sections: list[ProjectSection] = []
    applied_section_types: list[str] = []

    incoming_by_type = {s.section_type: s for s in payload.sections}
    composed_templates = compose_sections_for_types(normalized_types)
    composed_keys = {t["section_type"] for t in composed_templates}

    for tpl in composed_templates:
        st = tpl["section_type"]
        src = incoming_by_type.get(st)
        content = src.content.strip() if src else ""
        title = src.title.strip() if src and src.title.strip() else tpl["title"]
        sec = ProjectSection(
            project_id=project.id,
            section_type=st,
            track=tpl["track"],
            title=title,
            content=content,
            display_order=tpl["display_order"],
        )
        session.add(sec)
        saved_sections.append(sec)
        if content:
            applied_section_types.append(st)

    for s in payload.sections:
        if s.section_type not in composed_keys:
            st = s.section_type.strip()
            sec = ProjectSection(
                project_id=project.id,
                section_type=st,
                track=s.track or infer_track_for_section_type(st),
                title=s.title.strip(),
                content=s.content.strip(),
                display_order=s.display_order or 700,
            )
            session.add(sec)
            saved_sections.append(sec)
            if s.content.strip():
                applied_section_types.append(st)

    source_filename = payload.source_filename.strip() or project.repo_url
    doc_recorded = False
    if source_filename:
        session.add(
            ProjectDocument(
                project_id=project.id,
                filename=source_filename[:300],
                source_type=payload.source_type[:50],
                file_format=payload.source_format[:30],
                extracted_summary=payload.source_summary
                or f"초기 자동 생성 ({len(applied_section_types)}개 섹션 반영)",
                raw_char_count=sum(len(s.content) for s in saved_sections),
                applied_sections=applied_section_types,
            )
        )
        doc_recorded = True

    await session.commit()
    for sec in saved_sections:
        await session.refresh(sec)
        if sec.content.strip():
            if await _sync_section_vector(session, project, sec):
                vector_synced_count += 1

    saved_exp_ids: list[int] = []
    for item in payload.experiences:
        title = item.title.strip()
        if not title:
            continue
        score = 75 if item.quantified_metrics.strip() else 65
        exp = Experience(
            project_id=project.id,
            title=title[:300],
            situation=item.situation.strip(),
            task=item.task.strip(),
            action=item.action.strip(),
            result=item.result.strip(),
            learning=item.learning.strip(),
            quantified_metrics=item.quantified_metrics.strip(),
            completeness_score=score,
            raw_notes=f"[{payload.source_type} 자동 추출] {source_filename}",
        )
        session.add(exp)
        await session.commit()
        await session.refresh(exp)
        saved_exp_ids.append(exp.id)

        vector_content = (
            f"[프로젝트] {project.name} ({', '.join(normalized_types)})\n"
            f"[경험 제목] {exp.title}\n"
            f"[Situation] {exp.situation}\n"
            f"[Task] {exp.task}\n"
            f"[Action] {exp.action}\n"
            f"[Result] {exp.result}\n"
            f"[정량 지표] {exp.quantified_metrics}"
        )
        if await try_upsert_document(
            session,
            doc_type=DocType.EXPERIENCE,
            ref_id=f"exp-{exp.id}",
            content=vector_content,
            metadata={
                "experience_id": exp.id,
                "project_id": project.id,
                "project_types": normalized_types,
                "title": exp.title,
                "source": payload.source_type,
            },
        ):
            vector_synced_count += 1

    proj_resp = ProjectResponse.model_validate(project)
    proj_resp.project_types = normalized_types
    proj_resp.artifact_links = cleaned_links
    proj_resp.experience_count = len(saved_exp_ids)
    proj_resp.filled_section_count = len(applied_section_types)
    proj_resp.total_section_count = len(saved_sections)
    proj_resp.document_count = 1 if doc_recorded else 0

    return GitHubImportResponse(
        project=proj_resp,
        saved_section_count=len(saved_sections),
        saved_experience_ids=saved_exp_ids,
        vector_synced_count=vector_synced_count,
    )


@router.post(
    "/import-structured",
    response_model=GitHubImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_structured_project(
    payload: StructuredProjectImportRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GitHubImportResponse:
    """GitHub 분석 또는 문서 분석으로 생성된 멀티트랙 프로젝트·섹션·STAR를 일괄 저장한다."""
    return await _import_structured_project_impl(payload, session)


@router.post(
    "/import-github",
    response_model=GitHubImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_github_project(
    payload: StructuredProjectImportRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GitHubImportResponse:
    """GitHub 임포트 하위 호환 엔드포인트."""
    payload.source_type = "github_repo"
    payload.source_format = "github"
    return await _import_structured_project_impl(payload, session)


# ==============================================================================
# 2. 단일 프로젝트 CRUD, 동적 트랙 추가 & 상세 워크스페이스 조회
# ==============================================================================
@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectDetailResponse:
    project = await _load_project_full(session, project_id)
    if not project.sections:
        await _ensure_sections_for_project_types(session, project)
        project = await _load_project_full(session, project_id)

    norm_types = normalize_project_types(project.project_types)
    experiences = sorted(project.experiences, key=lambda e: e.created_at, reverse=True)
    sections = list(project.sections)
    documents = list(project.documents)
    filled_count = sum(1 for s in sections if (s.content or "").strip())

    assembled_md = render_portfolio_markdown(
        _project_to_dict(project), [_section_to_dict(s) for s in sections]
    )
    star_avg = compute_average_star_axes(
        [{"star_scores": e.star_scores} for e in experiences]
    )

    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        period=project.period,
        role=project.role,
        summary=project.summary,
        tech_stack=list(project.tech_stack or []),
        portfolio_goal_link=project.portfolio_goal_link,
        repo_url=project.repo_url,
        project_types=norm_types,
        artifact_links=list(project.artifact_links or []),
        created_at=project.created_at,
        experience_count=len(experiences),
        filled_section_count=filled_count,
        total_section_count=len(sections),
        document_count=len(documents),
        experiences=[ExperienceSummary.model_validate(e) for e in experiences],
        sections=[ProjectSectionResponse.model_validate(s) for s in sections],
        documents=[ProjectDocumentResponse.model_validate(d) for d in documents],
        assembled_markdown=assembled_md,
        star_averages=star_avg,
        retrospective=dict(project.retrospective or {}),
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    norm_types = normalize_project_types(payload.project_types)
    cleaned_links = _clean_artifact_links(payload.artifact_links)

    project = Project(
        name=payload.name.strip(),
        period=payload.period.strip(),
        role=payload.role.strip(),
        summary=payload.summary.strip(),
        tech_stack=[t.strip() for t in payload.tech_stack if t.strip()],
        portfolio_goal_link=payload.portfolio_goal_link.strip(),
        repo_url=payload.repo_url.strip(),
        project_types=norm_types,
        artifact_links=cleaned_links,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    composed = compose_sections_for_types(norm_types)
    for tpl in composed:
        content = (
            project.summary
            if tpl["section_type"] == "overview" and project.summary
            else ""
        )
        session.add(
            ProjectSection(
                project_id=project.id,
                section_type=tpl["section_type"],
                track=tpl["track"],
                title=tpl["title"],
                content=content,
                display_order=tpl["display_order"],
            )
        )
    await session.commit()

    resp = ProjectResponse.model_validate(project)
    resp.project_types = norm_types
    resp.artifact_links = cleaned_links
    resp.total_section_count = len(composed)
    resp.filled_section_count = 1 if project.summary else 0
    return resp


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    payload: ProjectUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    project = await _load_project_full(session, project_id)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "tech_stack" and value is not None:
            setattr(project, field, [t.strip() for t in value if t.strip()])
        elif field == "project_types" and value is not None:
            setattr(project, field, normalize_project_types(value))
        elif field == "artifact_links" and value is not None:
            setattr(project, field, _clean_artifact_links(value))
        elif isinstance(value, str):
            setattr(project, field, value.strip())
        elif value is not None:
            setattr(project, field, value)

    await session.commit()
    await session.refresh(project)

    resp = ProjectResponse.model_validate(project)
    resp.project_types = normalize_project_types(project.project_types)
    resp.artifact_links = list(project.artifact_links or [])
    resp.experience_count = len(project.experiences)
    resp.total_section_count = len(project.sections)
    resp.filled_section_count = sum(1 for s in project.sections if (s.content or "").strip())
    resp.document_count = len(project.documents)
    return resp


@router.post("/{project_id}/tracks", response_model=AddTracksResponse)
async def add_project_tracks(
    project_id: int,
    payload: AddTracksRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AddTracksResponse:
    """진행 중인 프로젝트에 새 유형 트랙 팩을 동적으로 추가한다 (기존 섹션 내용 보존)."""
    project = await _load_project_full(session, project_id)
    merged_types = normalize_project_types(
        list(project.project_types or []) + list(payload.add_types)
    )
    project.project_types = merged_types
    await session.commit()

    project = await _load_project_full(session, project_id)
    added_sections = await _ensure_sections_for_project_types(session, project)
    return AddTracksResponse(
        project_types=merged_types,
        added_section_types=added_sections,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    project = await _load_project_full(session, project_id)
    sec_ids = [s.id for s in project.sections]
    await session.delete(project)
    await session.commit()

    for sec_id in sec_ids:
        await delete_document(
            session, doc_type=DocType.EXPERIENCE, ref_id=f"proj-{project_id}-sec-{sec_id}"
        )


# ==============================================================================
# 3. 모듈형 섹션 개별 CRUD (추가·편집·삭제 + 벡터 동기화)
# ==============================================================================
@router.post(
    "/{project_id}/sections",
    response_model=ProjectSectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_section(
    project_id: int,
    payload: ProjectSectionDraft,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectSectionResponse:
    project = await _load_project_full(session, project_id)
    next_order = payload.display_order or (
        max((s.display_order for s in project.sections if s.display_order < 850), default=600)
        + 10
    )
    track = payload.track.strip() or infer_track_for_section_type(payload.section_type)
    sec = ProjectSection(
        project_id=project.id,
        section_type=payload.section_type.strip(),
        track=track,
        title=payload.title.strip(),
        content=payload.content.strip(),
        display_order=next_order,
    )
    session.add(sec)
    await session.commit()
    await session.refresh(sec)

    resp = ProjectSectionResponse.model_validate(sec)
    synced = await _sync_section_vector(session, project, sec)
    resp.vector_synced = synced
    return resp


@router.put("/{project_id}/sections/{section_id}", response_model=ProjectSectionResponse)
async def update_project_section(
    project_id: int,
    section_id: int,
    payload: ProjectSectionUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectSectionResponse:
    project = await _load_project_full(session, project_id)
    sec = next((s for s in project.sections if s.id == section_id), None)
    if sec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Section {section_id} not found in project {project_id}.",
        )

    if payload.title is not None:
        sec.title = payload.title.strip()
    if payload.content is not None:
        sec.content = payload.content.strip()
    if payload.display_order is not None:
        sec.display_order = payload.display_order
    if payload.track is not None:
        sec.track = payload.track.strip()

    await session.commit()
    await session.refresh(sec)

    resp = ProjectSectionResponse.model_validate(sec)
    synced = await _sync_section_vector(session, project, sec)
    resp.vector_synced = synced
    return resp


@router.delete(
    "/{project_id}/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_project_section(
    project_id: int,
    section_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    sec = await session.get(ProjectSection, section_id)
    if sec is None or sec.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Section {section_id} not found in project {project_id}.",
        )
    await session.delete(sec)
    await session.commit()
    await delete_document(
        session, doc_type=DocType.EXPERIENCE, ref_id=f"proj-{project_id}-sec-{section_id}"
    )


# ==============================================================================
# 4. 파일/문서 업로드 & GitHub 재동기화 → 트랙별 자동 분배 Diff 제안/적용
# ==============================================================================
@router.post(
    "/{project_id}/ingest-document",
    response_model=DocumentIngestProposalResponse,
)
async def ingest_project_document(
    project_id: int,
    file: UploadFile | None = File(default=None),
    pasted_text: str = Form(default=""),
    doc_title: str = Form(default=""),
    instruction: str = Form(default=""),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentIngestProposalResponse:
    project = await _load_project_full(session, project_id)
    if not project.sections:
        await _ensure_sections_for_project_types(session, project)
        project = await _load_project_full(session, project_id)

    if file is not None and file.filename:
        raw_bytes = await file.read()
        try:
            parsed = parse_uploaded_file(file.filename, raw_bytes)
        except DocumentParseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        filename = parsed["filename"]
        file_format = parsed["file_format"]
        doc_text = parsed["text"]
        raw_char_count = parsed["raw_char_count"]
        parse_info = parsed["info"]
        source_type = "file_upload"
    elif pasted_text.strip():
        clean = pasted_text.strip()
        filename = doc_title.strip() or "붙여넣은 문서.md"
        file_format = "md"
        doc_text = clean[:28000]
        raw_char_count = len(clean)
        parse_info = f"{len(clean.splitlines())} lines"
        source_type = "pasted_doc"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="업로드할 파일 또는 붙여넣을 문서 텍스트를 입력해 주세요.",
        )

    try:
        proposal = await propose_document_updates(
            project=_project_to_dict(project),
            existing_sections=[_section_to_dict(s) for s in project.sections],
            doc_text=doc_text,
            filename=filename,
            user_instruction=instruction.strip(),
        )
    except Exception as exc:
        logger.exception("Document ingestion analysis failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"문서 기반 업데이트 분석 중 오류가 발생했습니다: {exc}",
        )

    return DocumentIngestProposalResponse(
        filename=filename,
        source_type=source_type,
        file_format=file_format,
        raw_char_count=raw_char_count,
        parse_info=parse_info,
        **proposal,
    )


@router.post(
    "/{project_id}/sync-github",
    response_model=DocumentIngestProposalResponse,
)
async def sync_project_github(
    project_id: int,
    payload: GitHubSyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentIngestProposalResponse:
    project = await _load_project_full(session, project_id)
    if not project.sections:
        await _ensure_sections_for_project_types(session, project)
        project = await _load_project_full(session, project_id)

    repo_url = payload.repo_url.strip() or project.repo_url.strip()
    if not repo_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="프로젝트에 연결된 GitHub 저장소 URL이 없습니다.",
        )

    try:
        repo_ctx = await fetch_github_repo_context(
            repo_url, github_token=payload.github_token.strip() or None
        )
        repo_doc = format_repo_context_as_document(repo_ctx)
        proposal = await propose_document_updates(
            project=_project_to_dict(project),
            existing_sections=[_section_to_dict(s) for s in project.sections],
            doc_text=repo_doc,
            filename=repo_ctx["full_name"],
            user_instruction=payload.instruction.strip()
            or "최신 GitHub 코드·커밋 변경 사항을 알맞은 섹션에 보강해 주세요.",
        )
    except GitHubAnalyzerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:
        logger.exception("GitHub sync failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"GitHub 재동기화 중 오류가 발생했습니다: {exc}",
        )

    return DocumentIngestProposalResponse(
        filename=repo_ctx["html_url"],
        source_type="github_repo",
        file_format="github",
        raw_char_count=len(repo_doc),
        parse_info=f"{len(repo_ctx.get('inspected_files') or {})} files · {len(repo_ctx.get('commits') or [])} commits",
        **proposal,
    )


@router.post(
    "/{project_id}/apply-updates",
    response_model=ApplyProjectUpdatesResponse,
)
async def apply_project_updates(
    project_id: int,
    payload: ApplyProjectUpdatesRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ApplyProjectUpdatesResponse:
    project = await _load_project_full(session, project_id)
    sec_by_id = {s.id: s for s in project.sections}
    sec_by_type = {s.section_type: s for s in project.sections}

    if payload.updated_summary is not None and payload.updated_summary.strip():
        project.summary = payload.updated_summary.strip()

    if payload.tech_stack_additions:
        current = list(project.tech_stack or [])
        lower_set = {t.lower() for t in current}
        for tech in payload.tech_stack_additions:
            clean = tech.strip()
            if clean and clean.lower() not in lower_set:
                current.append(clean)
                lower_set.add(clean.lower())
        project.tech_stack = current

    updated_sections: list[ProjectSection] = []
    updated_types: list[str] = []

    for item in payload.section_updates:
        target = (
            sec_by_id.get(item.section_id)
            if item.section_id is not None
            else sec_by_type.get(item.section_type)
        )
        if target is not None:
            target.title = item.title.strip() or target.title
            target.content = item.content.strip()
            updated_sections.append(target)
        else:
            known = ALL_KNOWN_SECTIONS.get(item.section_type)
            order = (
                known["display_order"]
                if known
                else max((s.display_order for s in project.sections if s.display_order < 850), default=600) + 10
            )
            track = item.track or infer_track_for_section_type(item.section_type)
            new_sec = ProjectSection(
                project_id=project.id,
                section_type=item.section_type.strip(),
                track=track,
                title=item.title.strip(),
                content=item.content.strip(),
                display_order=order,
            )
            session.add(new_sec)
            updated_sections.append(new_sec)
        updated_types.append(item.section_type.strip())

    doc_record = ProjectDocument(
        project_id=project.id,
        filename=payload.filename[:300],
        source_type=payload.source_type[:50],
        file_format=payload.file_format[:30],
        extracted_summary=payload.document_summary,
        raw_char_count=payload.raw_char_count,
        applied_sections=updated_types,
    )
    session.add(doc_record)
    await session.commit()
    await session.refresh(doc_record)

    vector_synced_count = 0
    for sec in updated_sections:
        await session.refresh(sec)
        if await _sync_section_vector(session, project, sec):
            vector_synced_count += 1

    norm_types = normalize_project_types(project.project_types)
    saved_exp_ids: list[int] = []
    for item in payload.experiences:
        title = item.title.strip()
        if not title:
            continue
        score = 75 if item.quantified_metrics.strip() else 65
        exp = Experience(
            project_id=project.id,
            title=title[:300],
            situation=item.situation.strip(),
            task=item.task.strip(),
            action=item.action.strip(),
            result=item.result.strip(),
            learning=item.learning.strip(),
            quantified_metrics=item.quantified_metrics.strip(),
            completeness_score=score,
            raw_notes=f"[문서 자동 추출] {payload.filename}",
        )
        session.add(exp)
        await session.commit()
        await session.refresh(exp)
        saved_exp_ids.append(exp.id)

        vector_content = (
            f"[프로젝트] {project.name} ({', '.join(norm_types)})\n"
            f"[경험 제목] {exp.title}\n"
            f"[Situation] {exp.situation}\n"
            f"[Task] {exp.task}\n"
            f"[Action] {exp.action}\n"
            f"[Result] {exp.result}\n"
            f"[정량 지표] {exp.quantified_metrics}"
        )
        if await try_upsert_document(
            session,
            doc_type=DocType.EXPERIENCE,
            ref_id=f"exp-{exp.id}",
            content=vector_content,
            metadata={
                "experience_id": exp.id,
                "project_id": project.id,
                "project_types": norm_types,
                "title": exp.title,
                "source": "document_ingest",
            },
        ):
            vector_synced_count += 1

    return ApplyProjectUpdatesResponse(
        updated_section_types=updated_types,
        saved_experience_ids=saved_exp_ids,
        document_id=doc_record.id,
        vector_synced_count=vector_synced_count,
    )


@router.delete(
    "/{project_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_project_document(
    project_id: int,
    doc_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    doc = await session.get(ProjectDocument, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {doc_id} not found in project {project_id}.",
        )
    await session.delete(doc)
    await session.commit()


# ==============================================================================
# 5. 쓸데없는 내용 정리 / AI 노이즈 삭제 (Prune & Apply)
# ==============================================================================
@router.post("/{project_id}/prune", response_model=PruneProposalResponse)
async def prune_project_sections(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> PruneProposalResponse:
    project = await _load_project_full(session, project_id)
    try:
        proposal = await propose_noise_pruning(
            project=_project_to_dict(project),
            existing_sections=[_section_to_dict(s) for s in project.sections],
        )
    except Exception as exc:
        logger.exception("Project pruning failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"불필요 내용 정리 분석 중 오류가 발생했습니다: {exc}",
        )
    return PruneProposalResponse.model_validate(proposal)


@router.post("/{project_id}/prune/apply", response_model=PruneApplyResponse)
async def apply_project_prune(
    project_id: int,
    payload: PruneApplyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PruneApplyResponse:
    project = await _load_project_full(session, project_id)
    sec_by_id = {s.id: s for s in project.sections}

    touched: list[ProjectSection] = []
    for upd in payload.updates:
        sec = sec_by_id.get(upd.section_id)
        if sec is None:
            continue
        sec.content = upd.cleaned_content.strip()
        touched.append(sec)

    await session.commit()

    synced = 0
    for sec in touched:
        await session.refresh(sec)
        if await _sync_section_vector(session, project, sec):
            synced += 1

    return PruneApplyResponse(updated_count=len(touched), vector_synced_count=synced)


# ==============================================================================
# 6. 포트폴리오 Markdown 내보내기 & 유형 인지형 AI 리캡
# ==============================================================================
@router.get("/{project_id}/export-markdown", response_model=ProjectRecapResponse)
async def export_project_markdown(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectRecapResponse:
    project = await _load_project_full(session, project_id)
    md = render_portfolio_markdown(
        _project_to_dict(project), [_section_to_dict(s) for s in project.sections]
    )
    return ProjectRecapResponse(
        project_id=project.id,
        project_name=project.name,
        experience_count=len(project.experiences),
        markdown=md,
    )


@router.post("/{project_id}/recap", response_model=ProjectRecapResponse)
async def generate_project_recap(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectRecapResponse:
    project = await _load_project_full(session, project_id)
    profile = await session.get(UserProfile, 1)
    experiences = sorted(project.experiences, key=lambda e: e.created_at)
    guidance = get_combined_ai_guidance(project.project_types)

    sections_blocks = [
        f"### [{s.track}] {s.title}\n{s.content}"
        for s in project.sections
        if (s.content or "").strip()
    ]
    sections_text = "\n\n".join(sections_blocks) or "(작성된 섹션 없음)"

    exp_blocks = []
    for idx, exp in enumerate(experiences, start=1):
        exp_blocks.append(
            f"### 경험 {idx}: {exp.title}\n"
            f"- Situation: {exp.situation}\n"
            f"- Task: {exp.task}\n"
            f"- Action: {exp.action}\n"
            f"- Result: {exp.result}\n"
            f"- 정량 성과: {exp.quantified_metrics}"
        )
    experiences_text = "\n\n".join(exp_blocks) or "(연결된 STAR 경험 없음)"

    profile_text = ""
    if profile:
        profile_text = (
            f"- 커리어 비전: {profile.career_vision}\n"
            f"- 핵심 신념: {profile.core_beliefs}\n"
            f"- 희망 직무: {profile.target_roles}\n"
            f"- 선호 문체: {profile.preferred_tone}"
        )

    system_prompt = (
        f"당신은 {guidance['persona']} 관점의 포트폴리오 에디터입니다.\n"
        f"제공된 사실(멀티트랙 섹션, STAR 경험, 커리어 신념)만을 근거로 [{guidance['labels']}] 프로젝트에 "
        "최적화된 한국어 Markdown 포트폴리오 리캡 문서를 작성하세요.\n"
        "규칙:\n"
        "1. 제공되지 않은 수치, 도구명, 성과를 임의로 지어내지 마세요(환각 엄금).\n"
        "2. 프로젝트의 복수 유형이 자연스럽게 드러나도록 핵심 문제 정의 → 유형별 핵심 기여·의사결정·해결 → 정량/정성 성과 → 커리어 비전 연결 순으로 구성하세요.\n"
        "3. 상투적인 AI 수식어를 배제하고 구체적 행동 동사와 근거 중심으로 간결하게 작성하세요."
    )

    user_prompt = (
        f"[프로젝트 정보]\n"
        f"- 이름: {project.name}\n"
        f"- 유형: {guidance['labels']}\n"
        f"- 기간: {project.period}\n"
        f"- 역할: {project.role}\n"
        f"- 요약: {project.summary}\n"
        f"- 기술/역량/도구: {', '.join(project.tech_stack or [])}\n"
        f"- 포트폴리오 목표 연결점: {project.portfolio_goal_link}\n"
        f"- 저장소 URL: {project.repo_url}\n"
        f"- 참고 링크: {project.artifact_links}\n\n"
        f"[지원자 커리어 신념/문체]\n{profile_text or '(미설정)'}\n\n"
        f"[정리된 모듈형 섹션]\n{sections_text}\n\n"
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


# ==============================================================================
# 7. 섹션 단일 문서 AI 업데이트 · 선택형 STAR 역질문 · 5축 STAR BARS 일괄 채점
# ==============================================================================
@router.post(
    "/{project_id}/sections/{section_id}/ingest-document",
    response_model=SectionIngestProposalResponse,
)
async def ingest_section_document(
    project_id: int,
    section_id: int,
    file: UploadFile | None = File(default=None),
    pasted_text: str = Form(default=""),
    doc_title: str = Form(default=""),
    instruction: str = Form(default=""),
    update_mode: str = Form(default="merge"),
    session: AsyncSession = Depends(get_db_session),
) -> SectionIngestProposalResponse:
    """특정 섹션 1개만을 대상으로 파일 또는 메모를 분석해 정밀 Before/After Diff를 제안한다."""
    project = await _load_project_full(session, project_id)
    target = next((s for s in project.sections if s.id == section_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Section {section_id} not found in project {project_id}.",
        )

    if file is not None and file.filename:
        raw_bytes = await file.read()
        try:
            parsed = parse_uploaded_file(file.filename, raw_bytes)
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        filename = parsed["filename"]
        file_format = parsed["file_format"]
        source_type = "section_file_upload"
        doc_text = parsed["text"]
        parse_info = parsed["extra_info"]
    elif pasted_text.strip():
        filename = doc_title.strip() or f"{target.title}_메모.md"
        file_format = "txt"
        source_type = "section_pasted_note"
        doc_text = pasted_text.strip()
        parse_info = f"{len(doc_text)} chars"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="업로드할 파일 또는 업데이트할 메모 텍스트를 입력해 주세요.",
        )

    safe_mode = update_mode if update_mode in ("merge", "replace", "append") else "merge"
    try:
        proposal = await propose_section_document_update(
            project=_project_to_dict(project),
            target_section=_section_to_dict(target),
            doc_text=doc_text,
            filename=filename,
            instruction=instruction.strip(),
            update_mode=safe_mode,  # type: ignore[arg-type]
        )
    except Exception as exc:
        logger.exception("Section-scoped document ingest failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"섹션 문서 AI 업데이트 분석 실패: {exc}",
        )

    return SectionIngestProposalResponse(
        filename=filename,
        source_type=source_type,
        file_format=file_format,
        raw_char_count=len(doc_text),
        parse_info=parse_info,
        **proposal,
    )


@router.post(
    "/{project_id}/star-onboarding/questions",
    response_model=StarOnboardingQuestionsResponse,
)
async def get_star_onboarding_questions(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> StarOnboardingQuestionsResponse:
    """선택형 프로젝트 STAR 딥다이브 역질문 3~4개를 생성한다."""
    project = await _load_project_full(session, project_id)
    exps_payload = [
        {
            "title": e.title,
            "situation": e.situation,
            "task": e.task,
            "action": e.action,
            "result": e.result,
            "quantified_metrics": e.quantified_metrics,
            "completeness_score": e.completeness_score,
        }
        for e in project.experiences
    ]
    try:
        res = await generate_star_onboarding_questions(
            project=_project_to_dict(project),
            sections=[_section_to_dict(s) for s in project.sections],
            experiences=exps_payload,
        )
    except Exception as exc:
        logger.exception("STAR onboarding questions failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"STAR 보강 역질문 생성 실패: {exc}",
        )
    return StarOnboardingQuestionsResponse(**res)


@router.post(
    "/{project_id}/star-onboarding/apply",
    response_model=StarOnboardingApplyResponse,
)
async def apply_star_onboarding(
    project_id: int,
    payload: StarOnboardingApplyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> StarOnboardingApplyResponse:
    """사용자의 선택형 STAR 역질문 답변을 반영해 5축 평가된 STAR 경험과 섹션 보강을 저장한다."""
    project = await _load_project_full(session, project_id)
    answered = [a.model_dump() for a in payload.answers if a.answer.strip()]
    if not answered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="최소 1개 이상의 질문에 답변을 입력해 주세요.",
        )

    try:
        synthesized = await synthesize_star_onboarding_answers(
            project=_project_to_dict(project),
            sections=[_section_to_dict(s) for s in project.sections],
            qa_pairs=answered,
        )
    except Exception as exc:
        logger.exception("STAR onboarding apply failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"STAR 답변 반영 중 오류가 발생했습니다: {exc}",
        )

    norm_types = normalize_project_types(project.project_types)
    qa_raw = "\n\n".join(f"Q: {a['question']}\nA: {a['answer']}" for a in answered)
    saved_exps: list[Experience] = []
    vector_synced_count = 0

    for item in synthesized["experiences"]:
        exp = Experience(
            project_id=project.id,
            title=str(item.get("title") or "보강된 경험")[:300],
            situation=str(item.get("situation") or ""),
            task=str(item.get("task") or ""),
            action=str(item.get("action") or ""),
            result=str(item.get("result") or ""),
            learning=str(item.get("learning") or ""),
            quantified_metrics=str(item.get("quantified_metrics") or ""),
            completeness_score=int(item.get("completeness_score") or 0),
            star_scores=dict(item.get("star_scores") or {}),
            raw_notes=f"[STAR 보강 역질문]\n{qa_raw}",
        )
        session.add(exp)
        await session.commit()
        await session.refresh(exp)
        saved_exps.append(exp)

        vector_content = (
            f"[프로젝트] {project.name} ({', '.join(norm_types)})\n"
            f"[경험 제목] {exp.title}\n"
            f"[Situation] {exp.situation}\n"
            f"[Task] {exp.task}\n"
            f"[Action] {exp.action}\n"
            f"[Result] {exp.result}\n"
            f"[정량 지표] {exp.quantified_metrics}"
        )
        if await try_upsert_document(
            session,
            doc_type=DocType.EXPERIENCE,
            ref_id=f"exp-{exp.id}",
            content=vector_content,
            metadata={
                "experience_id": exp.id,
                "project_id": project.id,
                "project_types": norm_types,
                "title": exp.title,
                "source": "star_onboarding",
            },
        ):
            vector_synced_count += 1

    applied_section_types: list[str] = []
    section_patches = synthesized.get("section_patches") or []
    if payload.apply_section_patches and section_patches:
        sec_by_id = {s.id: s for s in project.sections}
        patched_secs: list[ProjectSection] = []
        for patch in section_patches:
            target_sec = sec_by_id.get(patch["section_id"])
            if target_sec and patch.get("proposed_content"):
                target_sec.content = patch["proposed_content"].strip()
                patched_secs.append(target_sec)
                applied_section_types.append(target_sec.section_type)
        if patched_secs:
            await session.commit()
            for sec in patched_secs:
                await session.refresh(sec)
                if await _sync_section_vector(session, project, sec):
                    vector_synced_count += 1

    return StarOnboardingApplyResponse(
        saved_experiences=[ExperienceSummary.model_validate(e) for e in saved_exps],
        applied_section_types=applied_section_types,
        section_patches=section_patches,
        vector_synced_count=vector_synced_count,
    )


@router.post(
    "/{project_id}/evaluate-stars",
    response_model=ProjectStarEvaluateResponse,
)
async def evaluate_project_stars(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectStarEvaluateResponse:
    """프로젝트에 연결된 모든 STAR 경험을 5축 STAR-L BARS 루브릭으로 객관 재채점한다."""
    project = await _load_project_full(session, project_id)
    if not project.experiences:
        return ProjectStarEvaluateResponse(
            evaluated_count=0,
            experiences=[],
            star_averages=compute_average_star_axes([]),
        )

    evaluated_count = 0
    for exp in project.experiences:
        grade = await evaluate_star_experience_rubric(
            {
                "title": exp.title,
                "situation": exp.situation,
                "task": exp.task,
                "action": exp.action,
                "result": exp.result,
                "learning": exp.learning,
                "quantified_metrics": exp.quantified_metrics,
            },
            context_text=exp.raw_notes,
        )
        exp.completeness_score = grade["completeness_score"]
        exp.star_scores = grade["star_scores"]
        evaluated_count += 1

    await session.commit()
    project = await _load_project_full(session, project_id)
    exps = sorted(project.experiences, key=lambda e: e.created_at, reverse=True)
    return ProjectStarEvaluateResponse(
        evaluated_count=evaluated_count,
        experiences=[ExperienceSummary.model_validate(e) for e in exps],
        star_averages=compute_average_star_axes(
            [{"star_scores": e.star_scores} for e in exps]
        ),
    )


# ==============================================================================
# 8. 프로젝트 회고 인터뷰 (KPT / 4Ls / Post-Mortem) & 프로젝트 간 학습 루프 저장
# ==============================================================================
@router.post(
    "/{project_id}/retrospective/questions",
    response_model=ProjectRetroQuestionsResponse,
)
async def get_project_retro_questions(
    project_id: int,
    payload: ProjectRetroQuestionsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectRetroQuestionsResponse:
    """프로젝트 기록을 바탕으로 4관점 회고 인터뷰 질문을 생성한다."""
    project = await _load_project_full(session, project_id)
    exps_payload = [
        {
            "title": e.title,
            "action": e.action,
            "result": e.result,
            "learning": e.learning,
        }
        for e in project.experiences
    ]
    try:
        res = await generate_project_retro_questions(
            project=_project_to_dict(project),
            sections=[_section_to_dict(s) for s in project.sections],
            experiences=exps_payload,
            framework=payload.framework,
        )
    except Exception as exc:
        logger.exception("Project retro questions failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"프로젝트 회고 인터뷰 질문 생성 실패: {exc}",
        )
    return ProjectRetroQuestionsResponse(**res)


@router.post(
    "/{project_id}/retrospective/apply",
    response_model=ProjectRetroApplyResponse,
)
async def apply_project_retrospective(
    project_id: int,
    payload: ProjectRetroApplyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectRetroApplyResponse:
    """회고 인터뷰 답변을 구조화해 저장하고, outcomes 섹션 반영 및 코파일럿 학습 루프에 연결한다."""
    project = await _load_project_full(session, project_id)
    answered = [a.model_dump() for a in payload.answers if a.answer.strip()]
    if not answered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="최소 1개 이상의 회고 질문에 답변을 입력해 주세요.",
        )

    try:
        retro = await synthesize_project_retrospective(
            project=_project_to_dict(project),
            sections=[_section_to_dict(s) for s in project.sections],
            qa_pairs=answered,
            framework=payload.framework,
        )
    except Exception as exc:
        logger.exception("Project retrospective synthesis failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"프로젝트 회고 정리 중 오류가 발생했습니다: {exc}",
        )

    project.retrospective = retro
    outcomes_synced = False
    vector_synced = False

    outcomes_addition = (retro.get("outcomes_markdown_addition") or "").strip()
    if payload.sync_to_outcomes_section and outcomes_addition:
        outcomes_sec = next(
            (s for s in project.sections if s.section_type == "outcomes"), None
        )
        if outcomes_sec is not None:
            existing = (outcomes_sec.content or "").strip()
            marker = "### 프로젝트 회고"
            if marker in existing:
                existing = existing.split(marker)[0].strip()
            outcomes_sec.content = (
                f"{existing}\n\n{marker} ({retro.get('framework', 'kpt').upper()})\n{outcomes_addition}".strip()
                if existing
                else f"{marker} ({retro.get('framework', 'kpt').upper()})\n{outcomes_addition}"
            )
            outcomes_synced = True

    await session.commit()

    if outcomes_synced:
        project = await _load_project_full(session, project_id)
        outcomes_sec = next(
            (s for s in project.sections if s.section_type == "outcomes"), None
        )
        if outcomes_sec is not None:
            vector_synced = await _sync_section_vector(session, project, outcomes_sec)

    return ProjectRetroApplyResponse(
        retrospective=retro,
        outcomes_synced=outcomes_synced,
        vector_synced=vector_synced,
    )
