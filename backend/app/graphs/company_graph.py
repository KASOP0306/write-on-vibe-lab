"""워크플로우 ②: 목표 기업 리서치 & 신념 3각 매칭 (Company-Identity Matcher)."""

import asyncio
import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.bedrock import ainvoke_structured, get_smart_llm
from app.core.database import (
    CompanyProfile,
    Experience,
    Project,
    UserProfile,
    get_session_factory,
)
from app.core.vector_store import DocType, try_upsert_document
from app.tools.web_search import search_and_extract

logger = logging.getLogger(__name__)


class TriangularMatchItem(BaseModel):
    company_vision_or_issue: str = Field(
        default="", description="기업의 비전·핵심가치·기술/사업 병목"
    )
    my_belief: str = Field(default="", description="연결되는 지원자의 커리어 신념/철학")
    proof_project: str = Field(
        default="", description="이를 증명하는 지원자의 실제 프로젝트·경험 (미등록 시 보완 방향 기재)"
    )
    pitch_angle: str = Field(
        default="", description="자소서/면접에서 설득력 있게 풀어낼 핵심 논리 1~2문장"
    )


class CompanyAlignmentSchema(BaseModel):
    mission_vision: str = Field(default="", description="기업의 미션·비전 요약")
    core_values: str = Field(default="", description="기업의 핵심가치·인재상 요약")
    recent_trends: str = Field(
        default="", description="최근 사업 동향·기술 이슈·도전 과제 요약"
    )
    company_bottlenecks: list[str] = Field(
        default_factory=list, description="지원 직무 관점에서 추정되는 기업의 핵심 과제"
    )
    triangular_matches: list[TriangularMatchItem] = Field(
        default_factory=list,
        description="[기업 비전/과제 <-> 나의 신념 <-> 증명 프로젝트] 3각 매칭표 (2~3개 권장)",
    )


class CompanyResearchState(TypedDict, total=False):
    company_name: str
    target_role: str
    web_sources: list[dict[str, Any]]
    user_identity: dict[str, str]
    portfolio_items: list[dict[str, Any]]
    mission_vision: str
    core_values: str
    recent_trends: str
    value_alignment_map: dict[str, Any]
    company_profile_id: int | None
    vector_synced: bool


async def company_searcher(state: CompanyResearchState) -> dict[str, Any]:
    """DuckDuckGo + BS4로 목표 기업의 이념·비전·최근 이슈를 병렬 수집한다."""
    company = state["company_name"]
    role = state.get("target_role", "")

    queries = [
        f"{company} 미션 비전 핵심가치 인재상",
        f"{company} {role} 기술 블로그 최근 전략 이슈".strip(),
    ]
    results_per_query = await asyncio.gather(
        *(search_and_extract(q, max_results=3, fetch_top_n=2) for q in queries)
    )

    seen_urls: set[str] = set()
    merged: list[dict[str, Any]] = []
    for batch in results_per_query:
        for item in batch:
            url = item.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            merged.append(item)

    return {"web_sources": merged[:6]}


async def identity_portfolio_loader(state: CompanyResearchState) -> dict[str, Any]:
    """지원자의 신념(user_profile), 프로젝트(projects), STAR 경험(experiences)을 로드한다."""
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
    """기업 리서치 결과와 지원자 신념·프로젝트를 3각 매칭한다."""
    llm = get_smart_llm(temperature=0.3)

    sources_text = "\n\n".join(
        f"- [{idx}] {s['title']} ({s['url']})\n  내용: {s['content'][:900]}"
        for idx, s in enumerate(state.get("web_sources") or [], start=1)
    ) or "(웹 검색 결과가 부족합니다. 확인된 범위 내에서만 보수적으로 정리하세요.)"

    messages = [
        SystemMessage(
            content=(
                "당신은 지원자의 커리어 신념·프로젝트 경험과 목표 기업의 비전·과제를 논리적으로 연결하는 "
                "전략 커리어 컨설턴트입니다.\n"
                "규칙:\n"
                "1. 제공된 지원자 프로젝트/경험에 없는 사실을 절대 지어내지 마세요.\n"
                "2. 지원자의 프로젝트나 신념이 아직 등록되지 않은 경우에도 `triangular_matches`에 2~3건의 매칭 항목을 작성하되, "
                "`proof_project`에는 '(미등록 — 포트폴리오에 관련 프로젝트/경험 등록 추천)'처럼 솔직히 표기하고 "
                "해당 기업·직무에 어필할 수 있는 연결 전략을 `pitch_angle`에 제시하세요.\n"
                "3. 기업에 대한 막연한 칭찬 대신 실제 비전·사업 과제와 지원 직무의 접점을 도출하세요.\n"
                "4. 모든 출력은 한국어로 작성하고, 스키마의 모든 필드(`mission_vision`, `core_values`, `recent_trends`, `company_bottlenecks`, `triangular_matches`)를 빠짐없이 채우세요."
            )
        ),
        HumanMessage(
            content=(
                f"[목표 기업] {state['company_name']}\n"
                f"[지원 직무] {state.get('target_role') or '(미지정)'}\n\n"
                f"[웹 리서치 수집 자료]\n{sources_text}\n\n"
                f"[지원자 커리어 신념]\n{state.get('user_identity')}\n\n"
                f"[지원자 프로젝트 및 경험]\n{state.get('portfolio_items')}"
            )
        ),
    ]
    result = await ainvoke_structured(llm, CompanyAlignmentSchema, messages, max_retries=1)

    alignment_map = {
        "company_bottlenecks": result.company_bottlenecks,
        "triangular_matches": [m.model_dump() for m in result.triangular_matches],
        "sources": [
            {"title": s.get("title", ""), "url": s.get("url", "")}
            for s in (state.get("web_sources") or [])
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
        vector_content = (
            f"[기업명] {profile.company_name} ({profile.target_role})\n"
            f"[미션/비전] {profile.mission_vision}\n"
            f"[핵심가치] {profile.core_values}\n"
            f"[최근 동향] {profile.recent_trends}\n"
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
    workflow.add_node("company_searcher", company_searcher)
    workflow.add_node("identity_portfolio_loader", identity_portfolio_loader)
    workflow.add_node("alignment_synthesizer", alignment_synthesizer)
    workflow.add_node("save_company_profile", save_company_profile)

    workflow.add_edge(START, "company_searcher")
    workflow.add_edge("company_searcher", "identity_portfolio_loader")
    workflow.add_edge("identity_portfolio_loader", "alignment_synthesizer")
    workflow.add_edge("alignment_synthesizer", "save_company_profile")
    workflow.add_edge("save_company_profile", END)
    return workflow.compile()
