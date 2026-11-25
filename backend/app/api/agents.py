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
from app.core.bedrock import ainvoke_structured, get_fast_llm
from app.core.database import (
    ApplicationLog,
    CompanyProfile,
    Experience,
    VectorDocument,
    get_db_session,
)
from app.core.vector_store import DocType, delete_document, upsert_document
from app.graphs.company_graph import build_company_graph
from app.graphs.copilot_graph import build_copilot_chat_graph, build_retrospect_graph
from app.graphs.cover_letter_graph import (
    build_cover_letter_graph,
    recommend_cover_letter_materials,
)
from app.graphs.interview_graph import stream_interview_graph
from app.schemas.agents import (
    ApplicationLogResponse,
    ApplicationRetrospectRequest,
    CompanyProfileResponse,
    CompanyResearchRequest,
    CopilotChatRequest,
    CoverLetterGenerateRequest,
    CoverLetterRecommendRequest,
    InterestClipResponse,
    InterestClipSaveRequest,
    InterestSearchRequest,
    InterviewReplyRequest,
    InterviewStartRequest,
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
# 워크플로우 ①: 경험 채굴 & 연속 역질문 루프 (SSE)
# ==============================================================================
async def _stream_interview_sse(thread_id: str, input_state: dict[str, Any]):
    try:
        yield sse_node_start("interview", "경험 메모를 분석하고 STAR 구조를 추출하는 중...")
        final_state: dict[str, Any] = {}

        async for chunk in stream_interview_graph(
            thread_id=thread_id, input_state=input_state
        ):
            if "__final_state__" in chunk:
                final_state = chunk["__final_state__"]
                continue

            for node_name, update in chunk.items():
                if node_name == "extract_star":
                    yield sse_node_end("extract_star", {"star": update.get("star", {})})
                    yield sse_node_start("grade_gaps", "STAR 완성도와 정량 근거 빈틈을 평가하는 중...")
                elif node_name == "grade_gaps":
                    yield sse_node_end(
                        "grade_gaps",
                        {
                            "completeness_score": update.get("completeness_score", 0),
                            "star_scores": update.get("star_scores", {}),
                            "is_sufficient": update.get("is_sufficient", False),
                            "missing_points": update.get("missing_points", []),
                        },
                    )
                elif node_name == "generate_questions":
                    yield sse_node_end(
                        "generate_questions",
                        {"questions": update.get("questions", [])},
                    )
                elif node_name == "save_experience":
                    yield sse_node_end(
                        "save_experience",
                        {
                            "experience_id": update.get("saved_experience_id"),
                            "vector_synced": update.get("vector_synced", False),
                        },
                    )

        if final_state.get("saved_experience_id") is not None:
            yield sse_done(
                {
                    "thread_id": thread_id,
                    "experience_id": final_state.get("saved_experience_id"),
                    "star": final_state.get("star", {}),
                    "completeness_score": final_state.get("completeness_score", 0),
                    "star_scores": final_state.get("star_scores", {}),
                    "vector_synced": final_state.get("vector_synced", False),
                }
            )
        else:
            yield sse_interrupt(
                thread_id,
                {
                    "questions": final_state.get("questions", []),
                    "completeness_score": final_state.get("completeness_score", 0),
                    "star_scores": final_state.get("star_scores", {}),
                    "missing_points": final_state.get("missing_points", []),
                    "star": final_state.get("star", {}),
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
        "project_id": payload.project_id,
        "qa_history": [],
        "latest_reply": "",
        "force_save": payload.force_save,
        "questions": [],
        "saved_experience_id": None,
    }
    return create_sse_response(_stream_interview_sse(thread_id, input_state))


@router.post("/agents/interview/reply")
async def reply_interview(payload: InterviewReplyRequest):
    input_state: dict[str, Any] = {
        "latest_reply": payload.user_reply.strip(),
        "force_save": payload.force_save,
    }
    if payload.project_id is not None:
        input_state["project_id"] = payload.project_id
    return create_sse_response(_stream_interview_sse(payload.thread_id, input_state))


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
                "question_analysis": dict(payload.question_analysis or {}),
                "fusion_angle": payload.fusion_angle.strip(),
            }
            accumulated: dict[str, Any] = dict(initial_state)

            yield sse_node_start(
                "multi_source_retriever",
                "선택한 프로젝트·STAR 원문과 신념·기업 리서치·레퍼런스를 격리 로드하는 중...",
            )

            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    accumulated.update(update)

                    if node_name == "multi_source_retriever":
                        yield sse_node_end(
                            "multi_source_retriever",
                            {
                                "selected_project_count": len(update.get("used_projects") or []),
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

            yield sse_done(
                {
                    "final_text": accumulated.get("final_text", ""),
                    "diff_summary": accumulated.get("humanizer_changes", []),
                    "critic_score": accumulated.get("critic_score", 0),
                    "revision_count": accumulated.get("revision_count", 0),
                    "critic_history": accumulated.get("critic_history", []),
                    "checkpoint_checks": accumulated.get("checkpoint_checks", []),
                    "used_projects": accumulated.get("used_projects", []),
                    "used_experiences": accumulated.get("used_experiences", []),
                    "question_analysis": accumulated.get("question_analysis", {}),
                }
            )
        except Exception as exc:
            logger.exception("Cover letter generation SSE failed: %s", exc)
            yield sse_error(f"자소서 공방 에이전트 실행 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())


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
# 워크플로우 ④: 프로젝트 코파일럿 (Corrective RAG) & 취준 회고 (SSE + REST)
# ==============================================================================
@router.post("/agents/copilot/chat")
async def copilot_chat(payload: CopilotChatRequest):
    async def event_stream():
        try:
            graph = build_copilot_chat_graph()
            initial_state = {
                "message": payload.message.strip(),
                "project_id": payload.project_id,
                "chat_history": [m.model_dump() for m in payload.chat_history],
            }
            accumulated: dict[str, Any] = dict(initial_state)

            yield sse_node_start(
                "copilot_retriever",
                "과거 프로젝트 경험과 저장된 관심 기술 클립을 검색하는 중...",
            )

            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    accumulated.update(update)

                    if node_name == "copilot_retriever":
                        yield sse_node_end(
                            "copilot_retriever",
                            {
                                "experience_count": len(update.get("experience_docs") or []),
                                "interest_count": len(update.get("interest_docs") or []),
                            },
                        )
                        yield sse_node_start(
                            "relevance_grader",
                            "내부 자료만으로 답변이 충분한지 평가하는 중...",
                        )
                    elif node_name == "relevance_grader":
                        is_suff = bool(update.get("is_sufficient"))
                        yield sse_node_end(
                            "relevance_grader",
                            {
                                "is_sufficient": is_suff,
                                "reason": update.get("grade_reason", ""),
                                "rewritten_query": update.get("rewritten_query", ""),
                            },
                        )
                        if not is_suff:
                            yield sse_node_start(
                                "web_search_fallback",
                                f"최신 외부 자료를 보강 검색하는 중: '{update.get('rewritten_query', '')}'",
                            )
                        else:
                            yield sse_node_start(
                                "copilot_answer",
                                "과거 경험과 관심 지식을 바탕으로 조언을 정리하는 중...",
                            )
                    elif node_name == "web_search_fallback":
                        yield sse_node_end(
                            "web_search_fallback",
                            {"web_source_count": len(update.get("web_sources") or [])},
                        )
                        yield sse_node_start(
                            "copilot_answer",
                            "내부 경험과 웹 검색 결과를 결합해 답변을 작성하는 중...",
                        )
                    elif node_name == "copilot_answer":
                        yield sse_node_end(
                            "copilot_answer",
                            {"char_count": len(update.get("answer") or "")},
                        )

            yield sse_done(
                {
                    "answer": accumulated.get("answer", ""),
                    "used_web_fallback": bool(accumulated.get("used_web_fallback")),
                    "web_sources": [
                        {"title": s.get("title", ""), "url": s.get("url", "")}
                        for s in (accumulated.get("web_sources") or [])
                    ],
                }
            )
        except Exception as exc:
            logger.exception("Copilot chat SSE failed: %s", exc)
            yield sse_error(f"프로젝트 코파일럿 실행 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())


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
                        yield sse_node_end(
                            "load_retro_context",
                            {
                                "existing_interests_count": len(
                                    update.get("existing_interests") or []
                                )
                            },
                        )
                        yield sse_node_start(
                            "analyze_gap_and_plan",
                            "포트폴리오 대비 격차(Gap)를 진단하고 단기/중기 보완 플랜을 수립하는 중...",
                        )
                    elif node_name == "analyze_gap_and_plan":
                        yield sse_node_end(
                            "analyze_gap_and_plan",
                            {
                                "suggested_interests": update.get(
                                    "suggested_interests", []
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
                    "suggested_interests": accumulated.get("suggested_interests", []),
                }
            )
        except Exception as exc:
            logger.exception("Application retrospect SSE failed: %s", exc)
            yield sse_error(f"취준 회고 플래너 실행 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())
