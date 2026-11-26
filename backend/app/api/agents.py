"""에이전트 ①~③ SSE 스트리밍 및 기업 리서치·관심사 클립 API 라우터 (Day 2)."""

import logging
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sse import (
    create_sse_response,
    sse_done,
    sse_error,
    sse_interrupt,
    sse_node_end,
    sse_node_start,
)
from app.core.bedrock import ainvoke_structured, get_fast_llm, llm_telemetry_scope
from app.core.database import (
    ApplicationLog,
    CompanyProfile,
    CoverLetter,
    Experience,
    ExperienceFeedbackLog,
    Project,
    QuestionFeedbackLog,
    VectorDocument,
    get_db_session,
    get_session_factory,
)
from app.core.star_rubric import (
    CURRENT_RUBRIC_VERSION,
    STAR_CHECKPOINTS,
    evaluate_star_experience_rubric,
    list_rubric_versions,
    normalize_star_scores,
)
from app.core.vector_store import DocType, delete_document, try_upsert_document, upsert_document
from app.graphs.company_graph import build_company_graph
from app.graphs.copilot_agent_graph import (
    get_copilot_thread_history,
    stream_copilot_agent,
)
from app.graphs.copilot_graph import (
    build_retrospect_graph,
    propose_new_project_blueprints,
)
from app.graphs.cover_letter_graph import (
    build_cover_letter_graph,
    recommend_cover_letter_materials,
)
from app.graphs.interview_graph import (
    get_interview_thread_state,
    stream_interview_graph,
)
from app.tools.copilot_tools import delete_career_memory, list_career_memories
from app.schemas.agents import (
    ApplicationLogResponse,
    ApplicationRetrospectRequest,
    CompanyProfileResponse,
    CompanyResearchRequest,
    CopilotChatRequest,
    CoverLetterGenerateRequest,
    CoverLetterRecommendRequest,
    CoverLetterResponse,
    CoverLetterSaveRequest,
    CoverLetterUpdateRequest,
    ExperienceCreateRequest,
    ExperienceFeedbackSubmitRequest,
    ExperienceUpdateRequest,
    InterestClipResponse,
    InterestClipSaveRequest,
    InterestSearchRequest,
    InterviewReplyRequest,
    InterviewStartRequest,
    NewProjectBlueprintsRequest,
    QuestionFeedbackSubmitRequest,
)
from app.schemas.projects import ExperienceSummary
from app.tools.web_search import search_interest_sources

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["agents"])


class InterestClipCandidate(BaseModel):
    title: str
    url: str
    domain: str = ""
    source_type: str = "web"
    published_at: str = ""
    summary: str = Field(description="한국어 2~3문장 핵심 요약")
    key_takeaways: list[str] = Field(
        default_factory=list, description="실무/포트폴리오에 참고할 핵심 포인트 2~3개"
    )


class InterestSummaryBatch(BaseModel):
    clips: list[InterestClipCandidate]


# ==============================================================================
# 워크플로우 ①: 대화형 멀티턴 경험 채굴 (Conversational Active Interviewer v3.0)
# ==============================================================================
async def _stream_interview_sse(thread_id: str, input_state: dict[str, Any]):
    try:
        yield sse_node_start("interview", "대화 의도와 컨텍스트(프로젝트·GitHub Diff)를 분석하는 중...")
        final_state: dict[str, Any] = {}

        async for chunk in stream_interview_graph(
            thread_id=thread_id, input_state=input_state
        ):
            if "__final_state__" in chunk:
                final_state = chunk["__final_state__"]
                continue

            for node_name, update in chunk.items():
                if node_name == "load_project_context":
                    if update.get("project_name") or update.get("focus_context"):
                        yield sse_node_end(
                            "load_project_context",
                            {
                                "project_name": update.get("project_name", ""),
                                "project_types": update.get("project_types", []),
                                "project_context_preview": str(update.get("project_context", ""))[:420],
                                "has_focus_context": bool(update.get("focus_context")),
                            },
                        )
                elif node_name == "prepare_turn":
                    intent = update.get("turn_intent") or "answer"
                    if intent == "replace_question":
                        yield sse_node_start("generate_questions", "요청하신 방향에 맞춰 새 역질문을 생성하는 중...")
                    elif intent == "ask_coach":
                        yield sse_node_start("coach_reply", "코치가 현재 컨텍스트와 21지표 기준으로 답변을 작성하는 중...")
                elif node_name == "extract_star":
                    yield sse_node_end("extract_star", {"star": update.get("star", {})})
                    yield sse_node_start("grade_gaps", "21개 Atomic 체크포인트로 엄격 하이브리드 채점 중...")
                elif node_name == "grade_gaps":
                    yield sse_node_end(
                        "grade_gaps",
                        {
                            "completeness_score": update.get("completeness_score", 0),
                            "initial_score": update.get("initial_score", 0),
                            "last_unlocked_checkpoints": update.get("last_unlocked_checkpoints", 0),
                            "star_scores": update.get("star_scores", {}),
                            "is_sufficient": update.get("is_sufficient", False),
                            "missing_points": update.get("missing_points", []),
                        },
                    )
                elif node_name == "generate_questions":
                    yield sse_node_end(
                        "generate_questions",
                        {
                            "assistant_message": update.get("assistant_message", ""),
                            "questions": update.get("questions", []),
                            "structured_questions": update.get("structured_questions", []),
                            "question_critic_score": update.get("question_critic_score", 0),
                            "question_critic_revisions": update.get("question_critic_revisions", 0),
                        },
                    )
                elif node_name == "coach_reply":
                    yield sse_node_end(
                        "coach_reply",
                        {
                            "assistant_message": update.get("assistant_message", ""),
                        },
                    )
                elif node_name == "save_experience":
                    yield sse_node_end(
                        "save_experience",
                        {
                            "experience_id": update.get("saved_experience_id"),
                            "vector_synced": update.get("vector_synced", False),
                        },
                    )

        turn_count = len(final_state.get("qa_history") or [])
        if final_state.get("saved_experience_id") is not None:
            yield sse_done(
                {
                    "thread_id": thread_id,
                    "experience_id": final_state.get("saved_experience_id"),
                    "project_id": final_state.get("project_id"),
                    "project_name": final_state.get("project_name", ""),
                    "star": final_state.get("star", {}),
                    "completeness_score": final_state.get("completeness_score", 0),
                    "initial_score": final_state.get("initial_score", 0),
                    "turn_count": turn_count,
                    "star_scores": final_state.get("star_scores", {}),
                    "vector_synced": final_state.get("vector_synced", False),
                    "chat_messages": final_state.get("chat_messages", []),
                }
            )
        else:
            turn_intent = final_state.get("turn_intent") or "answer"
            is_coach_only = turn_intent == "ask_coach"
            yield sse_interrupt(
                thread_id,
                {
                    "turn_intent": turn_intent,
                    "assistant_message": final_state.get("assistant_message", ""),
                    "questions": [] if is_coach_only else final_state.get("questions", []),
                    "structured_questions": [] if is_coach_only else final_state.get("structured_questions", []),
                    "completeness_score": final_state.get("completeness_score", 0),
                    "initial_score": final_state.get("initial_score", 0),
                    "last_unlocked_checkpoints": final_state.get("last_unlocked_checkpoints", 0),
                    "turn_count": turn_count,
                    "project_name": final_state.get("project_name", ""),
                    "project_types": final_state.get("project_types", []),
                    "project_context_preview": str(final_state.get("project_context", ""))[:420],
                    "has_focus_context": bool((final_state.get("focus_context") or "").strip()),
                    "focus_context_preview": str(final_state.get("focus_context") or "")[:360],
                    "interview_preferences": final_state.get("interview_preferences") or {},
                    "star_scores": final_state.get("star_scores", {}),
                    "missing_points": final_state.get("missing_points", []),
                    "star": final_state.get("star", {}),
                    "chat_messages": final_state.get("chat_messages", []),
                },
            )
    except Exception as exc:
        logger.exception("Interview graph SSE failed: %s", exc)
        yield sse_error(f"경험 채굴 에이전트 실행 중 오류가 발생했습니다: {exc}")


@router.post("/agents/interview/start")
async def start_interview(payload: InterviewStartRequest):
    thread_id = payload.thread_id or f"exp-{uuid.uuid4().hex[:10]}"
    input_state: dict[str, Any] = {
        "raw_notes": payload.raw_notes.strip(),
        "focus_context": payload.focus_context.strip(),
        "project_id": payload.project_id,
        "qa_history": [],
        "chat_messages": [],
        "rejected_questions": [],
        "interview_preferences": {},
        "latest_reply": "",
        "turn_action": "auto",
        "replace_question_index": None,
        "force_save": payload.force_save,
        "questions": [],
        "saved_experience_id": None,
    }
    return create_sse_response(_stream_interview_sse(thread_id, input_state))


@router.post("/agents/interview/reply")
async def reply_interview(payload: InterviewReplyRequest):
    input_state: dict[str, Any] = {
        "latest_reply": payload.user_reply.strip(),
        "turn_action": payload.action,
        "replace_question_index": payload.replace_question_index,
        "force_save": payload.force_save or payload.action == "save",
    }
    if payload.project_id is not None:
        input_state["project_id"] = payload.project_id
    return create_sse_response(_stream_interview_sse(payload.thread_id, input_state))


@router.get("/agents/interview/history/{thread_id}")
async def get_interview_history(thread_id: str) -> dict[str, Any]:
    """PostgreSQL Checkpointer에 영속 저장된 멀티턴 경험 채굴 대화 세션 및 컨텍스트를 복원한다."""
    try:
        state = await get_interview_thread_state(thread_id)
    except Exception as exc:
        logger.warning("Failed to load interview thread %s: %s", thread_id, exc)
        state = None
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview thread '{thread_id}' not found.",
        )
    return state


# ==============================================================================
# 워크플로우 ②: 목표 기업 리서치 & 신념 3각 매칭 (SSE + 조회 REST)
# ==============================================================================
@router.get("/companies", response_model=list[CompanyProfileResponse])
async def list_companies(
    session: AsyncSession = Depends(get_db_session),
) -> list[CompanyProfileResponse]:
    stmt = select(CompanyProfile).order_by(
        CompanyProfile.created_at.desc(), CompanyProfile.id.desc()
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [CompanyProfileResponse.model_validate(row) for row in rows]


@router.delete("/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    company_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    company = await session.get(CompanyProfile, company_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company profile {company_id} not found.",
        )
    await session.delete(company)
    await session.commit()
    await delete_document(
        session, doc_type=DocType.COMPANY_RESEARCH, ref_id=f"company-{company_id}"
    )


@router.post("/agents/company/research")
async def research_company(payload: CompanyResearchRequest):
    async def event_stream():
        try:
            graph = build_company_graph()
            initial_state = {
                "company_name": payload.company_name.strip(),
                "target_role": payload.target_role.strip(),
                "jd_text": payload.jd_text.strip(),
                "reference_urls": [u.strip() for u in payload.reference_urls if u.strip()],
            }
            accumulated: dict[str, Any] = dict(initial_state)

            yield sse_node_start(
                "query_planner",
                f"'{payload.company_name}' 맞춤 4관점 리서치 쿼리를 설계하는 중...",
            )

            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    accumulated.update(update)
                    if node_name == "query_planner":
                        queries = update.get("planned_queries") or []
                        yield sse_node_end(
                            "query_planner",
                            {"query_count": len(queries), "queries": queries},
                        )
                        yield sse_node_start(
                            "company_searcher",
                            "웹 검색·Google News RSS·참고 URL에서 본문을 수집하고 정제하는 중...",
                        )
                    elif node_name == "company_searcher":
                        yield sse_node_end(
                            "company_searcher",
                            {"source_count": len(update.get("web_sources") or [])},
                        )
                        yield sse_node_start(
                            "identity_portfolio_loader",
                            "지원자의 커리어 신념과 프로젝트 경험을 불러오는 중...",
                        )
                    elif node_name == "identity_portfolio_loader":
                        yield sse_node_end(
                            "identity_portfolio_loader",
                            {"portfolio_count": len(update.get("portfolio_items") or [])},
                        )
                        yield sse_node_start(
                            "alignment_synthesizer",
                            "출처 근거 기반으로 기업 비전 × 나의 신념 × 프로젝트 3각 매칭을 생성하는 중...",
                        )
                    elif node_name == "alignment_synthesizer":
                        yield sse_node_end(
                            "alignment_synthesizer",
                            {
                                "mission_vision": update.get("mission_vision", ""),
                                "core_values": update.get("core_values", ""),
                                "recent_trends": update.get("recent_trends", ""),
                                "value_alignment_map": update.get("value_alignment_map", {}),
                            },
                        )
                        yield sse_node_start(
                            "save_company_profile",
                            "기업 리서치 결과와 3각 매칭표를 DB 및 벡터 저장소에 저장하는 중...",
                        )
                    elif node_name == "save_company_profile":
                        yield sse_node_end(
                            "save_company_profile",
                            {
                                "company_profile_id": update.get("company_profile_id"),
                                "vector_synced": update.get("vector_synced", False),
                            },
                        )

            yield sse_done(
                {
                    "id": accumulated.get("company_profile_id"),
                    "company_profile_id": accumulated.get("company_profile_id"),
                    "company_name": accumulated.get("company_name"),
                    "target_role": accumulated.get("target_role"),
                    "mission_vision": accumulated.get("mission_vision", ""),
                    "core_values": accumulated.get("core_values", ""),
                    "recent_trends": accumulated.get("recent_trends", ""),
                    "value_alignment_map": accumulated.get("value_alignment_map", {}),
                    "vector_synced": accumulated.get("vector_synced", False),
                }
            )
        except Exception as exc:
            logger.exception("Company research SSE failed: %s", exc)
            yield sse_error(f"기업 리서치 에이전트 실행 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())


# ==============================================================================
# 관심사 웹 리서치 (SSE) & 선별 클립 저장 (REST)
# ==============================================================================
@router.post("/agents/interests/search")
async def search_interests(payload: InterestSearchRequest):
    async def event_stream():
        try:
            keyword = payload.keyword.strip()
            scope_label = {
                "ko": "한국어 뉴스·기술 블로그",
                "global": "글로벌 기술(HN·GitHub·영문 뉴스)",
                "all": "한국어 + 글로벌 통합",
            }.get(payload.scope, payload.scope)

            yield sse_node_start(
                "web_search",
                f"'{keyword}' ({scope_label}) 최신 자료를 멀티소스로 수집하는 중...",
            )
            raw_docs = await search_interest_sources(
                keyword,
                scope=payload.scope,
                recency=payload.recency,
                max_results=payload.max_results,
            )
            yield sse_node_end("web_search", {"found_count": len(raw_docs)})

            if not raw_docs:
                yield sse_done({"keyword": keyword, "clips": []})
                return

            yield sse_node_start(
                "summarizer", "수집된 원문을 선별 저장할 수 있도록 핵심 요약 카드로 정리하는 중..."
            )
            docs_text = "\n\n".join(
                f"[{idx}] ({d.get('source_type', 'web')} · {d.get('domain', '')}"
                f"{' · ' + d['published_at'] if d.get('published_at') else ''})\n"
                f"제목: {d['title']}\nURL: {d['url']}\n내용: {d['content'][:1100]}"
                for idx, d in enumerate(raw_docs, start=1)
            )
            llm = get_fast_llm(temperature=0.2)
            summary_batch = await ainvoke_structured(
                llm,
                InterestSummaryBatch,
                [
                    SystemMessage(
                        content=(
                            "당신은 개발자의 기술 리서치 어시스턴트입니다. "
                            "제공된 검색 결과만 바탕으로 각 항목의 title, url, domain, source_type, published_at을 유지하고 "
                            "한국어 2~3문장 핵심 요약(summary)과 실무/포트폴리오 적용 포인트 2~3개(key_takeaways)를 정리하세요."
                        )
                    ),
                    HumanMessage(content=f"[관심 키워드] {keyword}\n\n[검색 자료]\n{docs_text}"),
                ],
                max_retries=1,
            )
            raw_by_url = {d.get("url"): d for d in raw_docs if d.get("url")}
            clips = []
            for c in summary_batch.clips:
                item = c.model_dump()
                src = raw_by_url.get(item.get("url")) or {}
                if not item.get("domain"):
                    item["domain"] = src.get("domain", "")
                if not item.get("source_type") or item["source_type"] == "web":
                    item["source_type"] = src.get("source_type", "web")
                if not item.get("published_at"):
                    item["published_at"] = src.get("published_at", "")
                clips.append(item)

            yield sse_node_end("summarizer", {"clip_count": len(clips)})
            yield sse_done({"keyword": keyword, "clips": clips})
        except Exception as exc:
            logger.exception("Interest search SSE failed: %s", exc)
            yield sse_error(f"관심사 리서치 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())


@router.post(
    "/agents/interests/clip",
    response_model=InterestClipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_interest_clip(
    payload: InterestClipSaveRequest,
    session: AsyncSession = Depends(get_db_session),
) -> InterestClipResponse:
    ref_id = f"clip-{uuid.uuid4().hex[:10]}"
    takeaways = [t.strip() for t in payload.key_takeaways if t.strip()]
    takeaways_text = "\n".join(f"- {t}" for t in takeaways)
    content = (
        f"[관심 키워드] {payload.keyword.strip()}\n"
        f"[제목] {payload.title.strip()}\n"
        f"[URL] {payload.url.strip()}\n"
        f"[요약] {payload.summary.strip()}\n"
        f"[핵심 포인트]\n{takeaways_text}"
    ).strip()
    metadata = {
        "keyword": payload.keyword.strip(),
        "title": payload.title.strip(),
        "url": payload.url.strip(),
        "summary": payload.summary.strip(),
        "key_takeaways": takeaways,
    }

    try:
        doc_id = await upsert_document(
            session,
            doc_type=DocType.INTEREST_CLIP,
            ref_id=ref_id,
            content=content,
            metadata=metadata,
        )
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to embed and save interest clip: {exc}",
        )

    doc = await session.get(VectorDocument, doc_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Saved clip could not be reloaded.",
        )

    return InterestClipResponse(
        id=doc.id,
        ref_id=doc.ref_id,
        keyword=metadata["keyword"],
        title=metadata["title"],
        url=metadata["url"],
        summary=metadata["summary"],
        key_takeaways=metadata["key_takeaways"],
        created_at=doc.created_at,
    )


@router.get("/interests/clips", response_model=list[InterestClipResponse])
async def list_interest_clips(
    session: AsyncSession = Depends(get_db_session),
) -> list[InterestClipResponse]:
    stmt = (
        select(VectorDocument)
        .where(VectorDocument.doc_type == DocType.INTEREST_CLIP.value)
        .order_by(VectorDocument.created_at.desc(), VectorDocument.id.desc())
    )
    docs = (await session.execute(stmt)).scalars().all()
    results: list[InterestClipResponse] = []
    for doc in docs:
        meta = doc.doc_metadata or {}
        results.append(
            InterestClipResponse(
                id=doc.id,
                ref_id=doc.ref_id,
                keyword=str(meta.get("keyword") or ""),
                title=str(meta.get("title") or ""),
                url=str(meta.get("url") or ""),
                summary=str(meta.get("summary") or doc.content),
                key_takeaways=list(meta.get("key_takeaways") or []),
                created_at=doc.created_at,
            )
        )
    return results


# ==============================================================================
# 워크플로우 ③: 자소서 문항 심층 분석 · 추천 (REST) & 생성 · 비평 · 퇴고 · De-AI (SSE)
# ==============================================================================
@router.post("/agents/cover-letter/recommend")
async def recommend_cover_letter(
    payload: CoverLetterRecommendRequest,
) -> dict[str, Any]:
    """Step 1: 기업 제공 문항을 심층 해부하고 등록된 프로젝트·STAR 중 최적 1~2개를 추천한다."""
    try:
        return await recommend_cover_letter_materials(
            company_name=payload.company_name.strip(),
            company_profile_id=payload.company_profile_id,
            target_role=payload.target_role.strip(),
            question=payload.question.strip(),
            char_limit=payload.char_limit,
        )
    except Exception as exc:
        logger.exception("Cover letter material recommendation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"문항 분석 및 프로젝트 추천 중 오류가 발생했습니다: {exc}",
        )


@router.post("/agents/cover-letter/generate")
async def generate_cover_letter(payload: CoverLetterGenerateRequest):
    async def event_stream():
        try:
            graph = build_cover_letter_graph()
            initial_state = {
                "company_name": payload.company_name.strip(),
                "company_profile_id": payload.company_profile_id,
                "target_role": payload.target_role.strip(),
                "question": payload.question.strip(),
                "char_limit": payload.char_limit,
                "extra_instructions": payload.extra_instructions.strip(),
                "selected_project_ids": list(payload.selected_project_ids or []),
                "selected_experience_ids": list(payload.selected_experience_ids or []),
                "selected_belief_ids": list(payload.selected_belief_ids or []),
                "selected_belief_note_ids": list(payload.selected_belief_note_ids or []),
                "question_analysis": dict(payload.question_analysis or {}),
                "fusion_angle": payload.fusion_angle.strip(),
            }
            accumulated: dict[str, Any] = dict(initial_state)

            yield sse_node_start(
                "multi_source_retriever",
                "선택한 프로젝트·STAR 원문과 핵심 신념 카드·회고·기업 리서치를 1급 소재로 로드하는 중...",
            )

            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    accumulated.update(update)

                    if node_name == "multi_source_retriever":
                        yield sse_node_end(
                            "multi_source_retriever",
                            {
                                "selected_project_count": len(update.get("used_projects") or []),
                                "selected_belief_count": len(update.get("used_beliefs") or []),
                                "experience_count": len(update.get("experience_docs") or []),
                                "identity_count": len(update.get("identity_docs") or []),
                                "company_count": len(update.get("company_docs") or []),
                                "sample_count": len(update.get("sample_docs") or []),
                            },
                        )
                        yield sse_node_start(
                            "drafter",
                            "문항 핵심 의도 × 선택 프로젝트·STAR × 기업·내 신념 3축 융합 초안을 작성하는 중...",
                        )
                    elif node_name == "drafter":
                        yield sse_node_end(
                            "drafter",
                            {"char_count": len(update.get("draft") or "")},
                        )
                        yield sse_node_start(
                            "critic", "면접관 관점에서 문항 체크포인트·팩트·신념 융합도를 엄격 평가하는 중..."
                        )
                    elif node_name == "critic":
                        score = update.get("critic_score", 0)
                        rev = accumulated.get("revision_count", 0)
                        yield sse_node_end(
                            "critic",
                            {
                                "score": score,
                                "revision": rev,
                                "feedback": update.get("critic_feedback", ""),
                                "checkpoint_checks": update.get("checkpoint_checks", []),
                            },
                        )
                        if rev >= 2 or score >= 85:
                            yield sse_node_start(
                                "de_ai_humanizer",
                                "AI 상투어를 제거하고 지원자 문체로 최종 다듬는 중...",
                            )
                        else:
                            yield sse_node_start(
                                "refiner",
                                f"면접관 피드백을 반영해 {rev + 1}차 퇴고를 진행하는 중...",
                            )
                    elif node_name == "refiner":
                        yield sse_node_end(
                            "refiner",
                            {
                                "revision": update.get("revision_count", 0),
                                "char_count": len(update.get("draft") or ""),
                            },
                        )
                        yield sse_node_start(
                            "critic", "퇴고본을 면접관 관점에서 재평가하는 중..."
                        )
                    elif node_name == "de_ai_humanizer":
                        yield sse_node_end(
                            "de_ai_humanizer",
                            {
                                "char_count": len(update.get("final_text") or ""),
                                "changes_count": len(update.get("humanizer_changes") or []),
                            },
                        )

            # 생성 완료된 자소서를 보관함(cover_letters)에 자동 영속 저장 (QA #2)
            saved_cover_letter_id: int | None = None
            final_text_clean = str(accumulated.get("final_text") or "").strip()
            if final_text_clean:
                try:
                    async with get_session_factory()() as save_session:
                        cl = CoverLetter(
                            company_name=payload.company_name.strip(),
                            target_role=payload.target_role.strip(),
                            question=payload.question.strip(),
                            char_limit=int(payload.char_limit or 800),
                            final_text=final_text_clean,
                            critic_score=int(accumulated.get("critic_score") or 0),
                            revision_count=int(accumulated.get("revision_count") or 0),
                            used_projects=list(accumulated.get("used_projects") or []),
                            used_experiences=list(accumulated.get("used_experiences") or []),
                            used_beliefs=list(accumulated.get("used_beliefs") or []),
                            diff_summary=list(accumulated.get("humanizer_changes") or []),
                            checkpoint_checks=list(accumulated.get("checkpoint_checks") or []),
                            memo="",
                        )
                        save_session.add(cl)
                        await save_session.commit()
                        await save_session.refresh(cl)
                        saved_cover_letter_id = cl.id
                except Exception as save_exc:
                    logger.warning("Auto-save cover letter archive failed: %s", save_exc)

            yield sse_done(
                {
                    "saved_cover_letter_id": saved_cover_letter_id,
                    "final_text": final_text_clean,
                    "diff_summary": accumulated.get("humanizer_changes", []),
                    "post_check_warnings": accumulated.get("post_check_warnings", []),
                    "critic_score": accumulated.get("critic_score", 0),
                    "revision_count": accumulated.get("revision_count", 0),
                    "critic_history": accumulated.get("critic_history", []),
                    "checkpoint_checks": accumulated.get("checkpoint_checks", []),
                    "used_projects": accumulated.get("used_projects", []),
                    "used_experiences": accumulated.get("used_experiences", []),
                    "used_beliefs": accumulated.get("used_beliefs", []),
                    "question_analysis": accumulated.get("question_analysis", {}),
                }
            )
        except Exception as exc:
            logger.exception("Cover letter generation SSE failed: %s", exc)
            yield sse_error(f"자소서 공방 에이전트 실행 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())


# ==============================================================================
# 생성 자소서 보관함 CRUD (REST — QA #2)
# ==============================================================================
@router.get("/cover-letters", response_model=list[CoverLetterResponse])
async def list_cover_letters(
    company_name: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[CoverLetterResponse]:
    stmt = select(CoverLetter).order_by(
        CoverLetter.updated_at.desc(), CoverLetter.id.desc()
    )
    if company_name and company_name.strip():
        stmt = stmt.where(CoverLetter.company_name.ilike(f"%{company_name.strip()}%"))
    rows = (await session.execute(stmt)).scalars().all()
    return [CoverLetterResponse.model_validate(row) for row in rows]


@router.post(
    "/cover-letters",
    response_model=CoverLetterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_cover_letter(
    payload: CoverLetterSaveRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CoverLetterResponse:
    cl = CoverLetter(
        company_name=payload.company_name.strip(),
        target_role=payload.target_role.strip(),
        question=payload.question.strip(),
        char_limit=payload.char_limit,
        final_text=payload.final_text.strip(),
        critic_score=payload.critic_score,
        revision_count=payload.revision_count,
        used_projects=list(payload.used_projects),
        used_experiences=list(payload.used_experiences),
        used_beliefs=list(payload.used_beliefs),
        diff_summary=list(payload.diff_summary),
        checkpoint_checks=list(payload.checkpoint_checks),
        memo=payload.memo.strip(),
    )
    session.add(cl)
    await session.commit()
    await session.refresh(cl)
    return CoverLetterResponse.model_validate(cl)


@router.put("/cover-letters/{cover_letter_id}", response_model=CoverLetterResponse)
async def update_cover_letter(
    cover_letter_id: int,
    payload: CoverLetterUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CoverLetterResponse:
    cl = await session.get(CoverLetter, cover_letter_id)
    if cl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cover letter {cover_letter_id} not found.",
        )
    if payload.company_name is not None:
        cl.company_name = payload.company_name.strip()
    if payload.target_role is not None:
        cl.target_role = payload.target_role.strip()
    if payload.question is not None:
        cl.question = payload.question.strip()
    if payload.final_text is not None:
        cl.final_text = payload.final_text.strip()
    if payload.memo is not None:
        cl.memo = payload.memo.strip()
    await session.commit()
    await session.refresh(cl)
    return CoverLetterResponse.model_validate(cl)


@router.delete(
    "/cover-letters/{cover_letter_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_cover_letter(
    cover_letter_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    cl = await session.get(CoverLetter, cover_letter_id)
    if cl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cover letter {cover_letter_id} not found.",
        )
    await session.delete(cl)
    await session.commit()


# ==============================================================================
# 저장된 경험 아카이브 조회/삭제 (REST)
# ==============================================================================
@router.get("/experiences", response_model=list[ExperienceSummary])
async def list_experiences(
    project_id: int | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[ExperienceSummary]:
    stmt = select(Experience).order_by(Experience.created_at.desc(), Experience.id.desc())
    if project_id is not None:
        stmt = stmt.where(Experience.project_id == project_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [ExperienceSummary.model_validate(row) for row in rows]


async def _sync_experience_vector(session: AsyncSession, exp: Experience) -> bool:
    vector_content = (
        f"[경험 제목] {exp.title}\n"
        f"[Situation] {exp.situation}\n"
        f"[Task] {exp.task}\n"
        f"[Action] {exp.action}\n"
        f"[Result] {exp.result}\n"
        f"[Learning] {exp.learning}\n"
        f"[정량 지표] {exp.quantified_metrics}"
    )
    return await try_upsert_document(
        session,
        doc_type=DocType.EXPERIENCE,
        ref_id=f"exp-{exp.id}",
        content=vector_content,
        metadata={
            "experience_id": exp.id,
            "project_id": exp.project_id,
            "title": exp.title,
            "completeness_score": exp.completeness_score,
            "rubric_version": str((exp.star_scores or {}).get("rubric_version") or CURRENT_RUBRIC_VERSION),
        },
    )


@router.post("/experiences", response_model=ExperienceSummary, status_code=status.HTTP_201_CREATED)
async def create_experience_manual(
    payload: ExperienceCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ExperienceSummary:
    """사용자가 직접 작성한 STAR-L 경험을 21지표 하이브리드 평가 엔진으로 채점·저장한다."""
    project_types: list[str] | None = None
    if payload.project_id is not None:
        proj = await session.get(Project, payload.project_id)
        if proj is not None:
            project_types = list(proj.project_types or ["engineering"])

    star_dict = {
        "title": payload.title.strip(),
        "situation": payload.situation.strip(),
        "task": payload.task.strip(),
        "action": payload.action.strip(),
        "result": payload.result.strip(),
        "learning": payload.learning.strip(),
        "quantified_metrics": payload.quantified_metrics.strip(),
    }
    grade = await evaluate_star_experience_rubric(
        star_dict,
        context_text=payload.raw_notes.strip(),
        project_types=project_types,
    )
    exp = Experience(
        project_id=payload.project_id,
        title=star_dict["title"][:300],
        situation=star_dict["situation"],
        task=star_dict["task"],
        action=star_dict["action"],
        result=star_dict["result"],
        learning=star_dict["learning"],
        quantified_metrics=star_dict["quantified_metrics"],
        completeness_score=int(grade["completeness_score"]),
        star_scores=dict(grade["star_scores"]),
        raw_notes=payload.raw_notes.strip() or "[직접 입력된 STAR-L 경험]",
    )
    session.add(exp)
    await session.commit()
    await session.refresh(exp)
    await _sync_experience_vector(session, exp)
    return ExperienceSummary.model_validate(exp)


@router.put("/experiences/{experience_id}", response_model=ExperienceSummary)
async def update_experience(
    experience_id: int,
    payload: ExperienceUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ExperienceSummary:
    """저장된 STAR-L 경험을 수정하고 21지표 하이브리드 평가 엔진으로 즉시 재채점·벡터 재동기화한다."""
    exp = await session.get(Experience, experience_id)
    if exp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experience {experience_id} not found.",
        )

    if payload.clear_project_id:
        exp.project_id = None
    elif payload.project_id is not None:
        exp.project_id = payload.project_id

    if payload.title is not None:
        exp.title = payload.title.strip()[:300]
    if payload.situation is not None:
        exp.situation = payload.situation.strip()
    if payload.task is not None:
        exp.task = payload.task.strip()
    if payload.action is not None:
        exp.action = payload.action.strip()
    if payload.result is not None:
        exp.result = payload.result.strip()
    if payload.learning is not None:
        exp.learning = payload.learning.strip()
    if payload.quantified_metrics is not None:
        exp.quantified_metrics = payload.quantified_metrics.strip()

    if payload.re_evaluate:
        project_types: list[str] | None = None
        if exp.project_id is not None:
            proj = await session.get(Project, exp.project_id)
            if proj is not None:
                project_types = list(proj.project_types or ["engineering"])
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
            project_types=project_types,
        )
        exp.completeness_score = int(grade["completeness_score"])
        exp.star_scores = dict(grade["star_scores"])

    await session.commit()
    await session.refresh(exp)
    await _sync_experience_vector(session, exp)
    return ExperienceSummary.model_validate(exp)


@router.delete("/experiences/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experience(
    experience_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    exp = await session.get(Experience, experience_id)
    if exp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experience {experience_id} not found.",
        )
    await session.delete(exp)
    await session.commit()
    await delete_document(session, doc_type=DocType.EXPERIENCE, ref_id=f"exp-{experience_id}")


# ==============================================================================
# 워크플로우 ④: 새 프로젝트 코파일럿 (캐릭터 약점 보완 + 기업 리서치 + 웹 검색) & 회고
# ==============================================================================
@router.post("/agents/copilot/propose-projects")
async def propose_copilot_projects(
    payload: NewProjectBlueprintsRequest,
) -> dict[str, Any]:
    """포트폴리오 캐릭터 약점 + 기업 리서치 + 실시간 웹 검색으로 보완형 새 프로젝트 청사진 2~3개를 추천한다."""
    try:
        return await propose_new_project_blueprints(
            company_profile_id=payload.company_profile_id,
            focus_weakness=payload.focus_weakness.strip(),
            topic_hint=payload.topic_hint.strip(),
            use_web_search=payload.use_web_search,
        )
    except Exception as exc:
        logger.exception("New project blueprint proposal failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"새 프로젝트 청사진 추천 중 오류가 발생했습니다: {exc}",
        )


@router.post("/agents/copilot/chat")
async def copilot_chat(payload: CopilotChatRequest):
    """Agentic RAG 코파일럿 (ReAct 도구 호출 + 검색 전략 에스컬레이션 + 단기/장기 기억)."""
    thread_id = (payload.thread_id or "").strip() or f"copilot-{uuid.uuid4().hex[:10]}"

    async def event_stream():
        try:
            with llm_telemetry_scope(f"copilot_agent:{thread_id}") as telemetry:
                yield sse_node_start(
                    "model",
                    "질문을 분석하고 필요한 도구(포트폴리오 검색·캐릭터·기업·웹·장기기억)를 판단하는 중...",
                )
                final_res: dict[str, Any] = {}

                async for chunk in stream_copilot_agent(
                    thread_id=thread_id,
                    message=payload.message.strip(),
                    focus_weakness=payload.focus_weakness.strip(),
                    company_profile_id=payload.company_profile_id,
                ):
                    if "__final_result__" in chunk:
                        final_res = chunk["__final_result__"]
                        continue

                    for node_name, update in chunk.items():
                        if node_name == "model":
                            msgs = update.get("messages") or []
                            last_ai = msgs[-1] if msgs else None
                            t_calls = getattr(last_ai, "tool_calls", None) or []
                            if t_calls:
                                call_summaries = [
                                    {
                                        "name": c.get("name"),
                                        "args": c.get("args") or {},
                                    }
                                    for c in t_calls
                                ]
                                yield sse_node_end(
                                    "model",
                                    {"decision": "tool_call", "tool_calls": call_summaries},
                                )
                                labels = ", ".join(c.get("name", "") for c in t_calls)
                                yield sse_node_start(
                                    "tools",
                                    f"에이전트가 선택한 도구를 실행하는 중: {labels}",
                                )
                            else:
                                yield sse_node_end("model", {"decision": "final_answer"})
                        elif node_name == "tools":
                            used_tools = update.get("used_tools") or []
                            yield sse_node_end(
                                "tools",
                                {
                                    "tool_count": update.get("tool_count", 0),
                                    "latest_tools": used_tools[-2:],
                                },
                            )
                            yield sse_node_start(
                                "model",
                                "도구 결과를 검토해 추가 검색이 필요한지 판단하고 답변을 정리하는 중...",
                            )
                        elif node_name == "stop":
                            yield sse_node_start(
                                "stop",
                                "도구 호출 상한에 도달해 수집된 근거로 최종 답변을 마무리하는 중...",
                            )
                            yield sse_node_end("stop", {"capped": True})

                yield sse_done(
                    {
                        "thread_id": final_res.get("thread_id", thread_id),
                        "answer": final_res.get("answer", ""),
                        "tool_count": final_res.get("tool_count", 0),
                        "used_tools": final_res.get("used_tools", []),
                        "used_web_fallback": bool(final_res.get("used_web_fallback")),
                        "telemetry": telemetry.summary(),
                    }
                )
        except Exception as exc:
            logger.exception("Copilot agent SSE failed: %s", exc)
            yield sse_error(f"새 프로젝트 코파일럿 실행 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())


@router.get("/agents/copilot/history/{thread_id}")
async def get_copilot_history(thread_id: str) -> dict[str, Any]:
    """단기 기억 체크포인터(AsyncPostgresSaver)에 저장된 특정 대화 스레드 기록을 반환한다."""
    try:
        messages = await get_copilot_thread_history(thread_id)
        return {"thread_id": thread_id, "messages": messages}
    except Exception as exc:
        logger.warning("Failed to load copilot thread history %s: %s", thread_id, exc)
        return {"thread_id": thread_id, "messages": []}


@router.get("/agents/copilot/memories")
async def get_copilot_memories() -> list[dict[str, Any]]:
    """장기 기억 Store(AsyncPostgresStore)에 저장된 사용자 커리어 메모 목록을 조회한다."""
    try:
        return await list_career_memories(limit=30)
    except Exception as exc:
        logger.warning("Failed to list career memories: %s", exc)
        return []


@router.delete("/agents/copilot/memories/{memory_key}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_copilot_memory(memory_key: str) -> None:
    """장기 기억 Store에서 특정 메모를 삭제한다."""
    await delete_career_memory(memory_key)


@router.get("/agents/question-quality/stats")
async def get_question_quality_stats(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """루프 A(질문 퀄리티 상승 루프): 기법별·축별 ΔSTAR-L 효용 및 비평 통계를 집계한다."""
    rows = (
        (
            await session.execute(
                select(QuestionFeedbackLog)
                .order_by(QuestionFeedbackLog.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    by_technique: dict[str, list[int]] = {}
    by_axis: dict[str, list[int]] = {}
    for r in rows:
        by_technique.setdefault(r.technique, []).append(int(r.delta_score))
        by_axis.setdefault(r.target_axis, []).append(int(r.delta_score))

    def _agg(bucket: dict[str, list[int]]) -> dict[str, Any]:
        return {
            k: {
                "count": len(vals),
                "avg_delta_score": round(sum(vals) / max(1, len(vals)), 2),
                "positive_rate": round(
                    sum(1 for v in vals if v > 0) / max(1, len(vals)), 3
                ),
            }
            for k, vals in bucket.items()
        }

    return {
        "total_samples": len(rows),
        "avg_delta_score": round(
            sum(r.delta_score for r in rows) / max(1, len(rows)), 2
        )
        if rows
        else 0.0,
        "by_technique": _agg(by_technique),
        "by_axis": _agg(by_axis),
    }


@router.post("/agents/question-feedback")
async def submit_question_feedback(
    payload: QuestionFeedbackSubmitRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """턴별 역질문 사용자 평가(👍/👎 + 사유 칩)를 기록한다."""
    log_row = await session.get(QuestionFeedbackLog, payload.feedback_log_id)
    if log_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question feedback log {payload.feedback_log_id} not found.",
        )
    log_row.user_vote = int(payload.vote)
    log_row.user_reason = str(payload.reason or "").strip()[:80] if payload.vote == -1 else ""
    await session.commit()
    return {
        "id": log_row.id,
        "vote": log_row.user_vote,
        "reason": log_row.user_reason,
    }


@router.post("/agents/experience-feedback")
async def submit_experience_feedback(
    payload: ExperienceFeedbackSubmitRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """경험 채굴 완료 후 만족도(1~5★) 및 점수 체감(박함/적절/후함) 피드백을 저장한다."""
    rubric_ver = CURRENT_RUBRIC_VERSION
    cp_snapshot: dict[str, Any] = {}
    final_score = int(payload.final_score)

    if payload.experience_id is not None:
        exp = await session.get(Experience, payload.experience_id)
        if exp is not None:
            norm = normalize_star_scores(exp.star_scores)
            rubric_ver = str(norm.get("rubric_version") or CURRENT_RUBRIC_VERSION)
            final_score = int(exp.completeness_score or final_score)
            cps = norm.get("checkpoints") if isinstance(norm, dict) else None
            if isinstance(cps, dict):
                cp_snapshot = {
                    cid: int(item.get("status", 0))
                    for cid, item in cps.items()
                    if isinstance(item, dict)
                }

    row = ExperienceFeedbackLog(
        experience_id=payload.experience_id,
        project_id=payload.project_id,
        thread_id=payload.thread_id.strip()[:120],
        rubric_version=rubric_ver,
        satisfaction_rating=int(payload.satisfaction_rating),
        score_perception=int(payload.score_perception),
        comment=payload.comment.strip(),
        initial_score=int(payload.initial_score),
        final_score=final_score,
        score_gain=final_score - int(payload.initial_score),
        turn_count=int(payload.turn_count),
        checkpoint_snapshot=cp_snapshot,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        "id": row.id,
        "rubric_version": row.rubric_version,
        "satisfaction_rating": row.satisfaction_rating,
        "score_perception": row.score_perception,
        "score_gain": row.score_gain,
    }


@router.get("/agents/experience-mining/metrics")
async def get_experience_mining_metrics(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """경험 채굴 품질·성장·캘리브레이션 및 21개 체크포인트 문항 분석(Item Analysis) 통합 지표."""
    q_rows = (
        (
            await session.execute(
                select(QuestionFeedbackLog)
                .order_by(QuestionFeedbackLog.created_at.desc())
                .limit(300)
            )
        )
        .scalars()
        .all()
    )
    e_rows = (
        (
            await session.execute(
                select(ExperienceFeedbackLog)
                .order_by(ExperienceFeedbackLog.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    all_exps = (
        (
            await session.execute(
                select(Experience).order_by(Experience.created_at.desc()).limit(200)
            )
        )
        .scalars()
        .all()
    )

    # 1) 질문 품질 지표
    voted = [r for r in q_rows if r.user_vote in (1, -1)]
    thumbs_up = sum(1 for r in voted if r.user_vote == 1)
    answered_qs = [r for r in q_rows if r.score_after != r.score_before or r.delta_score != 0 or r.unlocked_checkpoints > 0]
    neg_reason_counts: dict[str, int] = {}
    by_technique: dict[str, dict[str, Any]] = {}
    cp_neg_votes: dict[str, int] = {}
    cp_total_votes: dict[str, int] = {}

    for r in q_rows:
        t_bucket = by_technique.setdefault(
            r.technique,
            {"count": 0, "deltas": [], "up": 0, "down": 0},
        )
        t_bucket["count"] += 1
        t_bucket["deltas"].append(int(r.delta_score))
        if r.user_vote == 1:
            t_bucket["up"] += 1
        elif r.user_vote == -1:
            t_bucket["down"] += 1
            if r.user_reason:
                neg_reason_counts[r.user_reason] = neg_reason_counts.get(r.user_reason, 0) + 1
        for cid in (r.target_checkpoints or []):
            if r.user_vote in (1, -1):
                cp_total_votes[cid] = cp_total_votes.get(cid, 0) + 1
                if r.user_vote == -1:
                    cp_neg_votes[cid] = cp_neg_votes.get(cid, 0) + 1

    tech_summary = {
        tech: {
            "count": b["count"],
            "avg_delta_score": round(sum(b["deltas"]) / max(1, len(b["deltas"])), 2),
            "thumbs_up_rate": round((b["up"] / (b["up"] + b["down"])) * 100, 1)
            if (b["up"] + b["down"]) > 0
            else None,
        }
        for tech, b in by_technique.items()
    }
    top_neg_reasons = [
        {"reason": k, "count": v}
        for k, v in sorted(neg_reason_counts.items(), key=lambda x: -x[1])[:4]
    ]

    # 2) 경험 만족도 & 성장 지표
    harsh_cnt = sum(1 for r in e_rows if r.score_perception == -1)
    fair_cnt = sum(1 for r in e_rows if r.score_perception == 0)
    lenient_cnt = sum(1 for r in e_rows if r.score_perception == 1)
    fb_total = len(e_rows)

    # 3) 21개 체크포인트 문항 분석 (Item Analysis) & 코드 하드 캡 집계
    hard_cap_counts: dict[str, int] = {}
    cp_statuses: dict[str, list[int]] = {cp["id"]: [] for cp in STAR_CHECKPOINTS}
    for exp in all_exps:
        norm = normalize_star_scores(exp.star_scores)
        if not norm:
            continue
        for ev in (norm.get("cap_events") or []):
            reason = str(ev.get("reason") or "unknown")
            hard_cap_counts[reason] = hard_cap_counts.get(reason, 0) + 1
        cps_map = norm.get("checkpoints")
        if isinstance(cps_map, dict):
            for cid, item in cps_map.items():
                if cid in cp_statuses and isinstance(item, dict):
                    cp_statuses[cid].append(int(item.get("status", 0)))

    item_analysis: list[dict[str, Any]] = []
    for cp in STAR_CHECKPOINTS:
        cid = cp["id"]
        vals = cp_statuses[cid]
        n = len(vals)
        pass_rate = round((sum(1 for v in vals if v == 2) / n) * 100, 1) if n else 0.0
        partial_rate = round((sum(1 for v in vals if v == 1) / n) * 100, 1) if n else 0.0
        miss_rate = round((sum(1 for v in vals if v == 0) / n) * 100, 1) if n else 0.0
        v_tot = cp_total_votes.get(cid, 0)
        neg_rate = round((cp_neg_votes.get(cid, 0) / v_tot) * 100, 1) if v_tot else 0.0

        health = "healthy"
        if v_tot >= 3 and neg_rate >= 40.0:
            health = "high_friction"
        elif n >= 5 and pass_rate >= 90.0:
            health = "too_easy"
        elif n >= 5 and pass_rate <= 10.0 and miss_rate >= 80.0:
            health = "too_hard"

        item_analysis.append(
            {
                "id": cid,
                "axis": cp["axis"],
                "label": cp["label"],
                "weight": int(cp["weight"]),
                "sample_count": n,
                "pass_rate": pass_rate,
                "partial_rate": partial_rate,
                "miss_rate": miss_rate,
                "negative_vote_rate": neg_rate,
                "vote_count": v_tot,
                "health": health,
            }
        )

    return {
        "rubric_version": CURRENT_RUBRIC_VERSION,
        "available_versions": list_rubric_versions(),
        "question_quality": {
            "total_questions": len(q_rows),
            "voted_count": len(voted),
            "thumbs_up_count": thumbs_up,
            "thumbs_up_rate": round((thumbs_up / len(voted)) * 100, 1) if voted else None,
            "avg_delta_score": round(
                sum(r.delta_score for r in answered_qs) / max(1, len(answered_qs)), 2
            )
            if answered_qs
            else 0.0,
            "avg_unlocked_checkpoints": round(
                sum(r.unlocked_checkpoints for r in answered_qs) / max(1, len(answered_qs)), 2
            )
            if answered_qs
            else 0.0,
            "by_technique": tech_summary,
            "top_negative_reasons": top_neg_reasons,
        },
        "experience_growth": {
            "total_feedback_count": fb_total,
            "avg_satisfaction": round(
                sum(r.satisfaction_rating for r in e_rows) / max(1, fb_total), 2
            )
            if fb_total
            else None,
            "avg_initial_score": round(
                sum(r.initial_score for r in e_rows) / max(1, fb_total), 1
            )
            if fb_total
            else 0.0,
            "avg_final_score": round(
                sum(r.final_score for r in e_rows) / max(1, fb_total), 1
            )
            if fb_total
            else 0.0,
            "avg_score_gain": round(
                sum(r.score_gain for r in e_rows) / max(1, fb_total), 1
            )
            if fb_total
            else 0.0,
            "avg_turns": round(
                sum(r.turn_count for r in e_rows) / max(1, fb_total), 1
            )
            if fb_total
            else 0.0,
        },
        "rubric_calibration": {
            "perception_counts": {
                "harsh": harsh_cnt,
                "fair": fair_cnt,
                "lenient": lenient_cnt,
            },
            "perception_rates": {
                "harsh": round((harsh_cnt / fb_total) * 100, 1) if fb_total else 0.0,
                "fair": round((fair_cnt / fb_total) * 100, 1) if fb_total else 0.0,
                "lenient": round((lenient_cnt / fb_total) * 100, 1) if fb_total else 0.0,
            },
            "hard_cap_triggers": [
                {"reason": k, "count": v}
                for k, v in sorted(hard_cap_counts.items(), key=lambda x: -x[1])[:8]
            ],
            "item_analysis": item_analysis,
        },
    }


@router.get("/applications", response_model=list[ApplicationLogResponse])
async def list_applications(
    session: AsyncSession = Depends(get_db_session),
) -> list[ApplicationLogResponse]:
    stmt = select(ApplicationLog).order_by(
        ApplicationLog.created_at.desc(), ApplicationLog.id.desc()
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [ApplicationLogResponse.model_validate(row) for row in rows]


@router.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    application_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    log = await session.get(ApplicationLog, application_id)
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application log {application_id} not found.",
        )
    await session.delete(log)
    await session.commit()


@router.post("/agents/applications/retrospect")
async def retrospect_application(payload: ApplicationRetrospectRequest):
    async def event_stream():
        try:
            graph = build_retrospect_graph()
            initial_state = {
                "company_name": payload.company_name.strip(),
                "role": payload.role.strip(),
                "stage": payload.stage.strip(),
                "status": payload.status.strip(),
                "feedback_memo": payload.feedback_memo.strip(),
            }
            accumulated: dict[str, Any] = dict(initial_state)

            yield sse_node_start(
                "load_retro_context",
                "보유 프로젝트·경험·과거 지원 이력을 불러오는 중...",
            )

            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    accumulated.update(update)

                    if node_name == "load_retro_context":
                        yield sse_node_end("load_retro_context", {})
                        yield sse_node_start(
                            "analyze_gap_and_plan",
                            "포트폴리오 캐릭터·경험 대비 격차(Gap)를 진단하고 보완 플랜을 수립하는 중...",
                        )
                    elif node_name == "analyze_gap_and_plan":
                        yield sse_node_end(
                            "analyze_gap_and_plan",
                            {
                                "recommended_copilot_topic": update.get(
                                    "recommended_copilot_topic", ""
                                ),
                            },
                        )
                        yield sse_node_start(
                            "save_application_log",
                            "지원 결과 및 보완 액션 플랜을 DB에 저장하는 중...",
                        )
                    elif node_name == "save_application_log":
                        yield sse_node_end(
                            "save_application_log",
                            {"application_log_id": update.get("application_log_id")},
                        )

            yield sse_done(
                {
                    "application_log_id": accumulated.get("application_log_id"),
                    "gap_analysis": accumulated.get("gap_analysis", ""),
                    "action_plan": accumulated.get("action_plan", ""),
                    "short_term_plan": accumulated.get("short_term_plan", []),
                    "mid_term_plan": accumulated.get("mid_term_plan", []),
                    "recommended_copilot_topic": accumulated.get(
                        "recommended_copilot_topic", ""
                    ),
                }
            )
        except Exception as exc:
            logger.exception("Application retrospect SSE failed: %s", exc)
            yield sse_error(f"취준 회고 플래너 실행 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())
