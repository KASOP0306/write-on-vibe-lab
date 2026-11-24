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
from app.core.database import CompanyProfile, VectorDocument, get_db_session
from app.core.vector_store import DocType, upsert_document
from app.graphs.company_graph import build_company_graph
from app.graphs.cover_letter_graph import build_cover_letter_graph
from app.graphs.interview_graph import stream_interview_graph
from app.schemas.agents import (
    CompanyProfileResponse,
    CompanyResearchRequest,
    CoverLetterGenerateRequest,
    InterestClipResponse,
    InterestClipSaveRequest,
    InterestSearchRequest,
    InterviewReplyRequest,
    InterviewStartRequest,
)
from app.tools.web_search import search_and_extract

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["agents"])


class InterestClipCandidate(BaseModel):
    title: str
    url: str
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
                    "vector_synced": final_state.get("vector_synced", False),
                }
            )
        else:
            yield sse_interrupt(
                thread_id,
                {
                    "questions": final_state.get("questions", []),
                    "completeness_score": final_state.get("completeness_score", 0),
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


@router.post("/agents/company/research")
async def research_company(payload: CompanyResearchRequest):
    async def event_stream():
        try:
            graph = build_company_graph()
            initial_state = {
                "company_name": payload.company_name.strip(),
                "target_role": payload.target_role.strip(),
            }
            accumulated: dict[str, Any] = dict(initial_state)

            yield sse_node_start(
                "company_searcher",
                f"'{payload.company_name}'의 이념·비전·최근 이슈를 웹에서 수집하는 중...",
            )

            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    accumulated.update(update)
                    if node_name == "company_searcher":
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
                            "기업 비전 × 나의 신념 × 증명 프로젝트 3각 매칭을 생성하는 중...",
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
            yield sse_node_start(
                "web_search", f"'{keyword}' 관련 최신 기술·트렌드 자료를 검색하는 중..."
            )
            raw_docs = await search_and_extract(
                f"{keyword} 최신 기술 트렌드 아키텍처 사례",
                max_results=payload.max_results,
                fetch_top_n=min(3, payload.max_results),
            )
            yield sse_node_end("web_search", {"found_count": len(raw_docs)})

            if not raw_docs:
                yield sse_done({"keyword": keyword, "clips": []})
                return

            yield sse_node_start(
                "summarizer", "검색 결과를 선별 저장할 수 있도록 핵심 요약 카드로 정리하는 중..."
            )
            docs_text = "\n\n".join(
                f"[{idx}] 제목: {d['title']}\nURL: {d['url']}\n내용: {d['content'][:1000]}"
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
                            "제공된 검색 결과만 바탕으로 각 항목의 제목, URL, 한국어 2~3문장 핵심 요약, "
                            "실무/포트폴리오 적용 포인트 2~3개를 정리하세요."
                        )
                    ),
                    HumanMessage(content=f"[관심 키워드] {keyword}\n\n[검색 자료]\n{docs_text}"),
                ],
                max_retries=1,
            )
            clips = [c.model_dump() for c in summary_batch.clips]
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
# 워크플로우 ③: 자소서 생성 · 비평 · 퇴고 · De-AI 루프 (SSE)
# ==============================================================================
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
            }
            accumulated: dict[str, Any] = dict(initial_state)

            yield sse_node_start(
                "multi_source_retriever",
                "경험·신념·기업 리서치·자소서 레퍼런스를 doc_type별로 격리 검색하는 중...",
            )

            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    accumulated.update(update)

                    if node_name == "multi_source_retriever":
                        yield sse_node_end(
                            "multi_source_retriever",
                            {
                                "experience_count": len(update.get("experience_docs") or []),
                                "identity_count": len(update.get("identity_docs") or []),
                                "company_count": len(update.get("company_docs") or []),
                                "sample_count": len(update.get("sample_docs") or []),
                            },
                        )
                        yield sse_node_start(
                            "drafter",
                            "지원자 경험 팩트와 기업 비전을 결합해 1차 초안을 작성하는 중...",
                        )
                    elif node_name == "drafter":
                        yield sse_node_end(
                            "drafter",
                            {"char_count": len(update.get("draft") or "")},
                        )
                        yield sse_node_start(
                            "critic", "면접관 관점에서 초안을 엄격하게 평가하는 중..."
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
                }
            )
        except Exception as exc:
            logger.exception("Cover letter generation SSE failed: %s", exc)
            yield sse_error(f"자소서 공방 에이전트 실행 중 오류가 발생했습니다: {exc}")

    return create_sse_response(event_stream())
