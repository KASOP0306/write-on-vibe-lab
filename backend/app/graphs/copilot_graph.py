"""워크플로우 ④: 프로젝트 코파일럿(Corrective RAG) & 취준 결과 회고 플래너."""

import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.bedrock import ainvoke_structured, get_fast_llm, get_smart_llm
from app.core.database import (
    ApplicationLog,
    Experience,
    Project,
    UserInterest,
    UserProfile,
    get_session_factory,
)
from app.core.vector_store import DocType, search_documents
from app.tools.web_search import search_and_extract

logger = logging.getLogger(__name__)


# ==============================================================================
# 모드 A: 프로젝트 코파일럿 (Corrective RAG — 웹 검색 Fallback 최대 1회)
# ==============================================================================
class RelevanceGradeSchema(BaseModel):
    is_sufficient: bool = Field(
        description="내부 검색 문서(experience + interest_clip)만으로 질문에 충분히 답할 수 있는지 여부"
    )
    reason: str = Field(description="충분성 판단 근거 1문장")
    rewritten_query: str = Field(
        default="",
        description="내부 근거가 부족할 때 웹 검색에 사용할 간결한 재작성 검색 쿼리",
    )


class CopilotChatState(TypedDict, total=False):
    message: str
    chat_history: list[dict[str, str]]
    project_id: int | None
    experience_docs: list[str]
    interest_docs: list[str]
    profile_summary: str
    is_sufficient: bool
    grade_reason: str
    rewritten_query: str
    web_search_count: int
    web_sources: list[dict[str, Any]]
    answer: str
    used_web_fallback: bool


async def _safe_search(session, query: str, doc_type: DocType, top_k: int) -> list[str]:
    try:
        hits = await search_documents(
            session, query=query, doc_types=[doc_type], top_k=top_k
        )
        return [h.content for h in hits]
    except Exception as exc:
        logger.warning("Copilot vector search fallback (%s): %s", doc_type.value, exc)
        return []


async def copilot_retriever(state: CopilotChatState) -> dict[str, Any]:
    """과거 경험(experience)과 관심 분야 클립(interest_clip)을 분리 검색한다."""
    query = state["message"]

    async with get_session_factory()() as session:
        exp_docs = await _safe_search(session, query, DocType.EXPERIENCE, top_k=4)
        clip_docs = await _safe_search(session, query, DocType.INTEREST_CLIP, top_k=4)
        profile = await session.get(UserProfile, 1)

        if not exp_docs:
            stmt = select(Experience).order_by(Experience.created_at.desc()).limit(5)
            if state.get("project_id"):
                stmt = (
                    select(Experience)
                    .where(Experience.project_id == state["project_id"])
                    .order_by(Experience.created_at.desc())
                    .limit(5)
                )
            exps = (await session.execute(stmt)).scalars().all()
            exp_docs = [
                f"[경험] {e.title}\nAction: {e.action}\nResult: {e.result}\n지표: {e.quantified_metrics}"
                for e in exps
            ]

        profile_summary = ""
        if profile:
            profile_summary = (
                f"비전: {profile.career_vision} | 신념: {profile.core_beliefs} | 직무: {profile.target_roles}"
            )

    return {
        "experience_docs": exp_docs,
        "interest_docs": clip_docs,
        "profile_summary": profile_summary,
        "web_search_count": 0,
        "web_sources": [],
        "used_web_fallback": False,
    }


async def relevance_grader(state: CopilotChatState) -> dict[str, Any]:
    """내부 RAG 자료의 충분성을 평가하고, 부족 시 웹 검색 쿼리를 재작성한다."""
    llm = get_fast_llm(temperature=0.1)
    exp_text = "\n---\n".join(state.get("experience_docs") or []) or "(없음)"
    clip_text = "\n---\n".join(state.get("interest_docs") or []) or "(없음)"

    messages = [
        SystemMessage(
            content=(
                "당신은 Corrective RAG의 관련성 평가기입니다.\n"
                "사용자 질문에 답하기 위해 내부 자료(과거 프로젝트 경험 + 저장된 관심 기술 클립)가 충분한지 판단하세요.\n"
                "최신 라이브러리/트렌드/외부 사례가 필요하거나 내부 자료가 부족하면 is_sufficient=false로 설정하고 "
                "구체적인 한국어/영어 혼합 웹 검색 쿼리를 rewritten_query에 작성하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[사용자 질문]\n{state['message']}\n\n"
                f"[과거 경험 자료]\n{exp_text}\n\n"
                f"[관심 기술 클립 자료]\n{clip_text}"
            )
        ),
    ]
    grade = await ainvoke_structured(llm, RelevanceGradeSchema, messages, max_retries=1)
    return {
        "is_sufficient": grade.is_sufficient,
        "grade_reason": grade.reason,
        "rewritten_query": grade.rewritten_query or state["message"],
    }


def route_after_relevance(state: CopilotChatState) -> str:
    """Guardrail (agents_md.md 5.1): 웹 검색 Fallback은 요청당 최대 1회로 제한."""
    if not state.get("is_sufficient") and state.get("web_search_count", 0) < 1:
        return "web_search_fallback"
    return "copilot_answer"


async def web_search_fallback(state: CopilotChatState) -> dict[str, Any]:
    """재작성된 쿼리로 DuckDuckGo + BS4 웹 검색을 최대 1회 수행한다."""
    query = state.get("rewritten_query") or state["message"]
    sources = await search_and_extract(query, max_results=4, fetch_top_n=2)
    return {
        "web_sources": sources,
        "web_search_count": int(state.get("web_search_count", 0)) + 1,
        "used_web_fallback": True,
    }


async def copilot_answer(state: CopilotChatState) -> dict[str, Any]:
    """내부 경험·관심 클립·(선택적) 웹 검색 결과를 종합해 실전 프로젝트 조언을 생성한다."""
    llm = get_smart_llm(temperature=0.35)

    history_lines = []
    for turn in (state.get("chat_history") or [])[-6:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        history_lines.append(f"{role}: {content}")
    history_text = "\n".join(history_lines) or "(이전 대화 없음)"

    web_text = "\n\n".join(
        f"- {s.get('title', '')} ({s.get('url', '')})\n  {s.get('content', '')[:800]}"
        for s in (state.get("web_sources") or [])
    ) or "(웹 검색 미사용)"

    messages = [
        SystemMessage(
            content=(
                "당신은 지원자의 과거 프로젝트 경험과 관심 기술 스택을 완벽히 기억하는 시니어 아키텍트 코파일럿입니다.\n"
                "규칙:\n"
                "1. 지원자의 과거 경험/트러블슈팅을 자연스럽게 연결해 실전적인 설계·구현·포트폴리오 전략을 제안하세요.\n"
                "2. 웹 검색 자료를 참고했다면 핵심 출처 링크를 답변 하단에 간결히 표시하세요.\n"
                "3. 한국어 Markdown으로 구조화해 바로 실행 가능한 액션 아이템을 포함하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[지원자 커리어 프로필]\n{state.get('profile_summary') or '(미설정)'}\n\n"
                f"[최근 대화]\n{history_text}\n\n"
                f"[현재 질문]\n{state['message']}\n\n"
                f"[관련 과거 경험 (experience)]\n{chr(10).join(state.get('experience_docs') or ['(없음)'])}\n\n"
                f"[관련 관심 클립 (interest_clip)]\n{chr(10).join(state.get('interest_docs') or ['(없음)'])}\n\n"
                f"[웹 검색 보강 자료]\n{web_text}"
            )
        ),
    ]
    response = await llm.ainvoke(messages)
    answer_text = response.content if isinstance(response.content, str) else str(response.content)
    return {"answer": answer_text.strip()}


def build_copilot_chat_graph():
    workflow = StateGraph(CopilotChatState)
    workflow.add_node("copilot_retriever", copilot_retriever)
    workflow.add_node("relevance_grader", relevance_grader)
    workflow.add_node("web_search_fallback", web_search_fallback)
    workflow.add_node("copilot_answer", copilot_answer)

    workflow.add_edge(START, "copilot_retriever")
    workflow.add_edge("copilot_retriever", "relevance_grader")
    workflow.add_conditional_edges(
        "relevance_grader",
        route_after_relevance,
        {
            "web_search_fallback": "web_search_fallback",
            "copilot_answer": "copilot_answer",
        },
    )
    workflow.add_edge("web_search_fallback", "copilot_answer")
    workflow.add_edge("copilot_answer", END)
    return workflow.compile()


# ==============================================================================
# 모드 B: 취준 결과 회고 & Gap 분석 · 보완 액션 플랜
# ==============================================================================
class RetrospectivePlanSchema(BaseModel):
    gap_analysis: str = Field(
        default="",
        description="보유 포트폴리오·경험 대비 이번 지원 결과에서 드러난 핵심 격차(Gap) 진단 (한국어 Markdown)",
    )
    short_term_plan: list[str] = Field(
        default_factory=list,
        description="단기(1~2주) 자소서·포트폴리오·면접 보강 액션 아이템",
    )
    mid_term_plan: list[str] = Field(
        default_factory=list,
        description="중기(1~2개월) 신규 프로젝트·기술 심화·학습 액션 아이템",
    )
    suggested_interests: list[str] = Field(
        default_factory=list,
        description="보완이 필요한 신규 기술/도메인 관심 키워드 (user_interests 원클릭 추가용)",
    )


class RetrospectState(TypedDict, total=False):
    company_name: str
    role: str
    stage: str
    status: str
    feedback_memo: str

    portfolio_context: str
    past_logs_context: str
    existing_interests: list[str]

    gap_analysis: str
    short_term_plan: list[str]
    mid_term_plan: list[str]
    action_plan: str
    suggested_interests: list[str]
    application_log_id: int | None


async def load_retro_context(state: RetrospectState) -> dict[str, Any]:
    """보유 프로젝트, STAR 경험, 관심사, 과거 취준 회고 이력을 로드한다."""
    async with get_session_factory()() as session:
        profile = await session.get(UserProfile, 1)
        projects = (
            (await session.execute(select(Project).order_by(Project.created_at.desc())))
            .scalars()
            .all()
        )
        experiences = (
            (
                await session.execute(
                    select(Experience).order_by(Experience.completeness_score.desc()).limit(12)
                )
            )
            .scalars()
            .all()
        )
        interests = (
            (await session.execute(select(UserInterest).order_by(UserInterest.created_at.desc())))
            .scalars()
            .all()
        )
        past_logs = (
            (
                await session.execute(
                    select(ApplicationLog).order_by(ApplicationLog.created_at.desc()).limit(8)
                )
            )
            .scalars()
            .all()
        )

    project_lines = [
        f"- {p.name} ({p.role}) | 스택: {', '.join(p.tech_stack or [])} | 요약: {p.summary}"
        for p in projects
    ]
    exp_lines = [
        f"- {e.title} (완성도 {e.completeness_score}점) | 성과: {e.quantified_metrics or e.result}"
        for e in experiences
    ]
    portfolio_context = (
        f"[커리어 비전/신념] {(profile.career_vision if profile else '')} / {(profile.core_beliefs if profile else '')}\n"
        f"[보유 프로젝트 ({len(projects)}건)]\n" + ("\n".join(project_lines) or "(없음)") + "\n"
        f"[보유 STAR 경험 ({len(experiences)}건)]\n" + ("\n".join(exp_lines) or "(없음)")
    )
    past_logs_context = "\n".join(
        f"- {log.company_name} / {log.role} / {log.stage} / {log.status}: {log.feedback_memo[:200]}"
        for log in past_logs
    ) or "(이전 지원 회고 없음)"

    return {
        "portfolio_context": portfolio_context,
        "past_logs_context": past_logs_context,
        "existing_interests": [i.keyword for i in interests],
    }


async def analyze_gap_and_plan(state: RetrospectState) -> dict[str, Any]:
    """지원 결과와 포트폴리오를 대조해 Gap 진단, 단기/중기 보완 계획, 추천 관심 키워드를 도출한다."""
    llm = get_smart_llm(temperature=0.3)

    messages = [
        SystemMessage(
            content=(
                "당신은 데이터 기반으로 취준 전략을 코칭하는 커리어 회고 플래너입니다.\n"
                "지원 결과와 피드백을 지원자의 현재 포트폴리오·과거 회고와 대조하여:\n"
                "1. 냉정하고 구체적인 Gap 분석(역량·경험·표현·기술 스택 격차)\n"
                "2. 단기 보완 플랜(자소서/포폴/면접 답변 개선)\n"
                "3. 중기 보완 플랜(다음 프로젝트 주제/학습 로드맵)\n"
                "4. 기존 관심사와 겹치지 않는 핵심 보완 키워드(`suggested_interests`)를 도출하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[이번 지원 결과]\n"
                f"- 기업명: {state['company_name']}\n"
                f"- 직무: {state.get('role', '')}\n"
                f"- 전형 단계: {state.get('stage', '')}\n"
                f"- 결과: {state.get('status', '')}\n"
                f"- 피드백/회고 메모:\n{state.get('feedback_memo', '')}\n\n"
                f"[현재 보유 포트폴리오]\n{state.get('portfolio_context', '')}\n\n"
                f"[과거 지원 이력]\n{state.get('past_logs_context', '')}\n\n"
                f"[기존 등록된 관심 키워드]\n{state.get('existing_interests', [])}"
            )
        ),
    ]
    plan = await ainvoke_structured(llm, RetrospectivePlanSchema, messages, max_retries=1)

    short_md = "\n".join(f"- {item}" for item in plan.short_term_plan)
    mid_md = "\n".join(f"- {item}" for item in plan.mid_term_plan)
    action_plan_md = f"### 단기 보완 플랜 (자소서·포폴)\n{short_md}\n\n### 중기 보완 플랜 (신규 프로젝트·학습)\n{mid_md}"

    existing_lower = {k.lower() for k in (state.get("existing_interests") or [])}
    deduped_suggestions = [
        kw.strip()
        for kw in plan.suggested_interests
        if kw.strip() and kw.strip().lower() not in existing_lower
    ]

    return {
        "gap_analysis": plan.gap_analysis,
        "short_term_plan": plan.short_term_plan,
        "mid_term_plan": plan.mid_term_plan,
        "action_plan": action_plan_md,
        "suggested_interests": deduped_suggestions,
    }


async def save_application_log(state: RetrospectState) -> dict[str, Any]:
    """취준 결과와 Gap 분석·액션 플랜을 application_logs 테이블에 영속 저장한다."""
    async with get_session_factory()() as session:
        log = ApplicationLog(
            company_name=state["company_name"].strip(),
            role=(state.get("role") or "").strip(),
            stage=(state.get("stage") or "").strip(),
            status=(state.get("status") or "").strip(),
            feedback_memo=(state.get("feedback_memo") or "").strip(),
            gap_analysis=state.get("gap_analysis", ""),
            action_plan=state.get("action_plan", ""),
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)

    return {"application_log_id": log.id}


def build_retrospect_graph():
    workflow = StateGraph(RetrospectState)
    workflow.add_node("load_retro_context", load_retro_context)
    workflow.add_node("analyze_gap_and_plan", analyze_gap_and_plan)
    workflow.add_node("save_application_log", save_application_log)

    workflow.add_edge(START, "load_retro_context")
    workflow.add_edge("load_retro_context", "analyze_gap_and_plan")
    workflow.add_edge("analyze_gap_and_plan", "save_application_log")
    workflow.add_edge("save_application_log", END)
    return workflow.compile()
