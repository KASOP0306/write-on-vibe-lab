"""워크플로우 ②: 목표 기업 멀티소스 리서치 & 신념 3각 매칭 (Company-Identity Matcher)."""

import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.bedrock import ainvoke_structured, get_fast_llm, get_smart_llm
from app.core.database import (
    CompanyProfile,
    Experience,
    Project,
    UserProfile,
    get_session_factory,
)
from app.core.vector_store import DocType, try_upsert_document
from app.tools.web_search import multi_source_research

logger = logging.getLogger(__name__)


class QueryPlanSchema(BaseModel):
    queries: list[str] = Field(
        default_factory=list,
        description="기업 비전·기술 블로그·최근 뉴스·채용 요건을 다각도로 조사하기 위한 검색 쿼리 4개",
    )
    news_query: str = Field(
        default="",
        description="Google News RSS용 간결한 최신 뉴스 검색 쿼리 (기업명 + 핵심 도메인)",
    )


class TriangularMatchItem(BaseModel):
    company_vision_or_issue: str = Field(
        default="", description="기업의 비전·핵심가치·기술/사업 병목 (출처 번호 [1] 등 표기 가능)"
    )
    my_belief: str = Field(default="", description="연결되는 지원자의 커리어 신념/철학")
    proof_project: str = Field(
        default="", description="이를 증명하는 지원자의 실제 프로젝트·경험 (미등록 시 보완 방향 기재)"
    )
    pitch_angle: str = Field(
        default="", description="자소서/면접에서 설득력 있게 풀어낼 핵심 논리 1~2문장"
    )


class CompanyAlignmentSchema(BaseModel):
    mission_vision: str = Field(
        default="", description="기업의 미션·비전 요약 (참고한 출처 번호 [1] 등 인용)"
    )
    core_values: str = Field(
        default="", description="기업의 핵심가치·인재상·조직문화 요약"
    )
    recent_trends: str = Field(
        default="", description="최근 사업 동향·기술 이슈·도전 과제 요약 (출처 번호 인용)"
    )
    company_bottlenecks: list[str] = Field(
        default_factory=list, description="지원 직무 및 JD 관점에서 추정되는 기업의 핵심 과제"
    )
    triangular_matches: list[TriangularMatchItem] = Field(
        default_factory=list,
        description="[기업 비전/과제 <-> 나의 신념 <-> 증명 프로젝트] 3각 매칭표 (2~3개 권장)",
    )


class CompanyResearchState(TypedDict, total=False):
    company_name: str
    target_role: str
    jd_text: str
    reference_urls: list[str]

    planned_queries: list[str]
    news_query: str
    web_sources: list[dict[str, Any]]
    user_identity: dict[str, str]
    portfolio_items: list[dict[str, Any]]

    mission_vision: str
    core_values: str
    recent_trends: str
    value_alignment_map: dict[str, Any]
    company_profile_id: int | None
    vector_synced: bool


async def query_planner(state: CompanyResearchState) -> dict[str, Any]:
    """Fast LLM이 기업·직무·JD에 최적화된 4관점 리서치 쿼리를 설계한다."""
    company = state["company_name"]
    role = state.get("target_role") or ""
    jd_preview = (state.get("jd_text") or "")[:600]

    default_queries = [
        f"{company} 미션 비전 핵심가치 인재상",
        f"{company} 기술 블로그 {role} 아키텍처".strip(),
        f"{company} 최근 신규 사업 전략 이슈",
        f"{company} {role} 채용 우대사항 기술스택".strip(),
    ]
    default_news_q = f"{company} {role}".strip() if role else company

    try:
        llm = get_fast_llm(temperature=0.1)
        plan = await ainvoke_structured(
            llm,
            QueryPlanSchema,
            [
                SystemMessage(
                    content=(
                        "당신은 기업 리서치 쿼리 플래너입니다. "
                        "목표 기업과 지원 직무를 바탕으로 웹 검색 효율이 높은 간결한 한국어/영어 혼합 쿼리 4개를 설계하세요.\n"
                        "관점 1: 공식 미션·비전·인재상\n"
                        "관점 2: 기업 공식 기술 블로그 및 지원 직무 아키텍처/엔지니어링 사례\n"
                        "관점 3: 최근 6개월 주요 사업 동향·투자·신규 서비스 뉴스\n"
                        "관점 4: 해당 직무 채용 요건·핵심 기술 스택\n"
                        "각 쿼리는 4~7단어 이내로 노이즈 없이 간결하게 작성하세요."
                    )
                ),
                HumanMessage(
                    content=(
                        f"기업명: {company}\n"
                        f"지원 직무: {role or '(미지정)'}\n"
                        f"채용공고(JD) 일부: {jd_preview or '(없음)'}"
                    )
                ),
            ],
            max_retries=1,
        )
        queries = [q.strip() for q in plan.queries if q.strip()][:4] or default_queries
        news_q = (plan.news_query or "").strip() or default_news_q
    except Exception as exc:
        logger.warning("Query planner fell back to defaults: %s", exc)
        queries = default_queries
        news_q = default_news_q

    return {
        "planned_queries": queries,
        "news_query": news_q,
    }


async def company_searcher(state: CompanyResearchState) -> dict[str, Any]:
    """ddgs + Google News RSS + 사용자 제공 URL을 병렬 수집하고 trafilatura로 정제한다."""
    company = state["company_name"]
    role = state.get("target_role") or ""
    queries = state.get("planned_queries") or [
        f"{company} 미션 비전 핵심가치",
        f"{company} {role} 기술 블로그 최근 이슈".strip(),
    ]
    news_query = state.get("news_query") or company
    ref_urls = [u.strip() for u in (state.get("reference_urls") or []) if u.strip()]

    focus_keywords = [company, *role.split()]
    sources = await multi_source_research(
        queries,
        focus_keywords=focus_keywords,
        include_news_rss=True,
        news_query=news_query,
        reference_urls=ref_urls,
        max_total=8,
        fetch_top_n=5,
        max_chars=1800,
    )
    return {"web_sources": sources}


async def identity_portfolio_loader(state: CompanyResearchState) -> dict[str, Any]:
    """지원자의 신념(user_profile + belief_pillars + belief_notes), 프로젝트, STAR 경험을 로드한다."""
    from app.core.database import BeliefNote, BeliefPillar

    async with get_session_factory()() as session:
        profile = await session.get(UserProfile, 1)
        pillars = (
            (await session.execute(select(BeliefPillar).order_by(BeliefPillar.created_at.desc())))
            .scalars()
            .all()
        )
        notes = (
            (await session.execute(select(BeliefNote).order_by(BeliefNote.created_at.desc()).limit(8)))
            .scalars()
            .all()
        )
        projects = (
            (await session.execute(select(Project).order_by(Project.created_at.desc())))
            .scalars()
            .all()
        )
        experiences = (
            (
                await session.execute(
                    select(Experience).order_by(Experience.completeness_score.desc()).limit(10)
                )
            )
            .scalars()
            .all()
        )

    user_identity = {
        "career_vision": profile.career_vision if profile else "",
        "core_beliefs": profile.core_beliefs if profile else "",
        "target_roles": profile.target_roles if profile else "",
        "belief_pillars": [
            {
                "id": b.id,
                "category": b.category,
                "title": b.title,
                "tradeoff_rule": b.tradeoff_rule,
                "origin_story": b.origin_story[:200],
                "linked_project_ids": list(b.linked_project_ids or []),
                "linked_experience_ids": list(b.linked_experience_ids or []),
            }
            for b in pillars
        ],
        "belief_notes": [
            {
                "source_type": n.source_type,
                "source_title": n.source_title,
                "quote_text": n.quote_text[:140],
                "my_reflection": n.my_reflection[:200],
            }
            for n in notes
        ],
    }
    portfolio_items = [
        {
            "type": "project",
            "id": p.id,
            "name": p.name,
            "role": p.role,
            "summary": p.summary,
            "tech_stack": p.tech_stack,
            "portfolio_goal_link": p.portfolio_goal_link,
        }
        for p in projects
    ]
    portfolio_items.extend(
        [
            {
                "type": "experience",
                "id": e.id,
                "project_id": e.project_id,
                "title": e.title,
                "action": e.action,
                "result": e.result,
                "quantified_metrics": e.quantified_metrics,
            }
            for e in experiences
        ]
    )

    return {
        "user_identity": user_identity,
        "portfolio_items": portfolio_items,
    }


async def alignment_synthesizer(state: CompanyResearchState) -> dict[str, Any]:
    """채용공고(JD) + 출처 번호가 매겨진 멀티소스 리서치 + 지원자 신념·프로젝트를 3각 매칭한다."""
    llm = get_smart_llm(temperature=0.3)
    web_sources = state.get("web_sources") or []
    jd_text = (state.get("jd_text") or "").strip()

    sources_text = "\n\n".join(
        f"[{idx}] ({s.get('source_type', 'web')} · {s.get('domain', '')}"
        f"{' · ' + s['published_at'] if s.get('published_at') else ''})\n"
        f"제목: {s.get('title', '')}\n"
        f"URL: {s.get('url', '')}\n"
        f"발췌: {s.get('content', '')[:1100]}"
        for idx, s in enumerate(web_sources, start=1)
    ) or "(웹 검색 결과가 부족합니다. 확인된 범위 내에서만 보수적으로 정리하세요.)"

    jd_section = (
        f"[지원자가 직접 제공한 채용공고(JD) — 최우선 1급 근거]\n{jd_text[:3000]}\n\n"
        if jd_text
        else ""
    )

    messages = [
        SystemMessage(
            content=(
                "당신은 지원자의 커리어 신념·프로젝트 경험과 목표 기업의 비전·과제를 근거 기반으로 연결하는 "
                "전략 커리어 컨설턴트입니다.\n"
                "규칙:\n"
                "1. 제공된 지원자 프로젝트/경험에 없는 사실을 절대 지어내지 마세요.\n"
                "2. 채용공고(JD)나 사용자 제공 참고 자료가 있다면 최우선 근거로 반영하고, "
                "웹 리서치 내용을 인용할 때는 해당 출처 번호(예: [1], [2])를 본문에 표기하세요.\n"
                "3. 지원자의 프로젝트나 신념이 아직 등록되지 않은 경우에도 `triangular_matches`에 2~3건의 매칭 항목을 작성하되, "
                "`proof_project`에는 '(미등록 — 포트폴리오에 관련 프로젝트/경험 등록 추천)'처럼 솔직히 표기하고 "
                "해당 기업·직무에 어필할 수 있는 연결 전략을 `pitch_angle`에 제시하세요.\n"
                "4. 기업에 대한 막연한 칭찬 대신 실제 비전·사업 과제·기술 병목과 지원 직무의 접점을 도출하세요.\n"
                "5. 모든 출력은 한국어로 작성하고 스키마의 모든 필드를 빠짐없이 채우세요."
            )
        ),
        HumanMessage(
            content=(
                f"[목표 기업] {state['company_name']}\n"
                f"[지원 직무] {state.get('target_role') or '(미지정)'}\n\n"
                f"{jd_section}"
                f"[멀티소스 웹 리서치 수집 자료 ({len(web_sources)}건)]\n{sources_text}\n\n"
                f"[지원자 커리어 신념]\n{state.get('user_identity')}\n\n"
                f"[지원자 프로젝트 및 경험]\n{state.get('portfolio_items')}"
            )
        ),
    ]
    result = await ainvoke_structured(llm, CompanyAlignmentSchema, messages, max_retries=1)

    alignment_map = {
        "company_bottlenecks": result.company_bottlenecks,
        "triangular_matches": [m.model_dump() for m in result.triangular_matches],
        "planned_queries": state.get("planned_queries") or [],
        "has_jd_input": bool(jd_text),
        "sources": [
            {
                "idx": idx,
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "domain": s.get("domain", ""),
                "source_type": s.get("source_type", "web"),
                "published_at": s.get("published_at", ""),
                "excerpt": (s.get("content") or s.get("snippet") or "")[:220],
            }
            for idx, s in enumerate(web_sources, start=1)
        ],
    }

    return {
        "mission_vision": result.mission_vision,
        "core_values": result.core_values,
        "recent_trends": result.recent_trends,
        "value_alignment_map": alignment_map,
    }


async def save_company_profile(state: CompanyResearchState) -> dict[str, Any]:
    """기업 리서치 결과와 3각 매칭표를 company_profiles + company_research 벡터에 저장한다."""
    async with get_session_factory()() as session:
        profile = CompanyProfile(
            company_name=state["company_name"].strip(),
            target_role=(state.get("target_role") or "").strip(),
            mission_vision=state.get("mission_vision", ""),
            core_values=state.get("core_values", ""),
            recent_trends=state.get("recent_trends", ""),
            value_alignment_map=state.get("value_alignment_map") or {},
        )
        session.add(profile)
        await session.commit()
        await session.refresh(profile)

        matches_text = "\n".join(
            f"- 기업과제: {m['company_vision_or_issue']} | 신념: {m['my_belief']} | 증명: {m['proof_project']} | 포인트: {m['pitch_angle']}"
            for m in (profile.value_alignment_map.get("triangular_matches") or [])
        )
        bottlenecks_text = "\n".join(
            f"- {b}" for b in (profile.value_alignment_map.get("company_bottlenecks") or [])
        )
        vector_content = (
            f"[기업명] {profile.company_name} ({profile.target_role})\n"
            f"[미션/비전] {profile.mission_vision}\n"
            f"[핵심가치] {profile.core_values}\n"
            f"[최근 동향] {profile.recent_trends}\n"
            f"[핵심 과제]\n{bottlenecks_text}\n"
            f"[신념-기업-프로젝트 3각 매칭]\n{matches_text}"
        )
        vector_synced = await try_upsert_document(
            session,
            doc_type=DocType.COMPANY_RESEARCH,
            ref_id=f"company-{profile.id}",
            content=vector_content,
            metadata={
                "company_profile_id": profile.id,
                "company_name": profile.company_name,
                "target_role": profile.target_role,
            },
        )

    return {
        "company_profile_id": profile.id,
        "vector_synced": vector_synced,
    }


def build_company_graph():
    workflow = StateGraph(CompanyResearchState)
    workflow.add_node("query_planner", query_planner)
    workflow.add_node("company_searcher", company_searcher)
    workflow.add_node("identity_portfolio_loader", identity_portfolio_loader)
    workflow.add_node("alignment_synthesizer", alignment_synthesizer)
    workflow.add_node("save_company_profile", save_company_profile)

    workflow.add_edge(START, "query_planner")
    workflow.add_edge("query_planner", "company_searcher")
    workflow.add_edge("company_searcher", "identity_portfolio_loader")
    workflow.add_edge("identity_portfolio_loader", "alignment_synthesizer")
    workflow.add_edge("alignment_synthesizer", "save_company_profile")
    workflow.add_edge("save_company_profile", END)
    return workflow.compile()
