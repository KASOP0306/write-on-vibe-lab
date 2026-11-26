"""워크플로우 ④: 새 프로젝트 코파일럿 (캐릭터 약점 보완 + 기업 리서치 + 웹 검색) & 지원·취준 회고."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.bedrock import ainvoke_structured, get_fast_llm, get_smart_llm
from app.core.database import (
    ApplicationLog,
    BeliefNote,
    BeliefPillar,
    CompanyProfile,
    Experience,
    Project,
    UserProfile,
    get_session_factory,
)
from app.core.project_templates import normalize_project_types
from app.core.star_rubric import compute_cumulative_portfolio_xp
from app.core.vector_store import DocType, search_documents
from app.tools.copilot_tools import format_star_mastery_summary
from app.tools.web_search import search_and_extract

logger = logging.getLogger(__name__)


async def _load_copilot_rich_context(
    *,
    company_profile_id: int | None = None,
    project_id: int | None = None,
) -> dict[str, Any]:
    """STAR-L 21지표 마스터리(1,000 XP) + 핵심 신념 카드 + 회고 노트 + 기업 리서치 + 기존 프로젝트/STAR를 종합 로드한다."""
    async with get_session_factory()() as session:
        profile = await session.get(UserProfile, 1)
        projects = (
            (await session.execute(select(Project).order_by(Project.created_at.desc()).limit(15)))
            .scalars()
            .all()
        )
        all_experiences = (
            (await session.execute(select(Experience).order_by(Experience.completeness_score.desc())))
            .scalars()
            .all()
        )
        belief_pillars = (
            (await session.execute(select(BeliefPillar).order_by(BeliefPillar.created_at.desc())))
            .scalars()
            .all()
        )
        belief_notes = (
            (await session.execute(select(BeliefNote).order_by(BeliefNote.created_at.desc()).limit(6)))
            .scalars()
            .all()
        )

        company_profiles: list[CompanyProfile] = []
        if company_profile_id:
            chosen = await session.get(CompanyProfile, company_profile_id)
            if chosen:
                company_profiles.append(chosen)
        if not company_profiles:
            company_profiles = (
                (
                    await session.execute(
                        select(CompanyProfile).order_by(CompanyProfile.created_at.desc()).limit(3)
                    )
                )
                .scalars()
                .all()
            )

    experiences = (
        [e for e in all_experiences if e.project_id == project_id][:6]
        if project_id
        else all_experiences[:6]
    )

    proj_dicts = [
        {
            "id": p.id,
            "name": p.name,
            "period": p.period,
            "project_types": normalize_project_types(p.project_types),
            "is_portfolio_selected": bool(p.is_portfolio_selected),
        }
        for p in projects
    ]
    exp_dicts = [
        {
            "id": e.id,
            "project_id": e.project_id,
            "title": e.title,
            "completeness_score": e.completeness_score,
            "star_scores": e.star_scores or {},
        }
        for e in all_experiences
    ]
    pillar_dicts = [
        {
            "id": b.id,
            "title": b.title,
            "category": b.category,
            "tradeoff_rule": b.tradeoff_rule,
            "linked_project_ids": list(b.linked_project_ids or []),
            "linked_experience_ids": list(b.linked_experience_ids or []),
        }
        for b in belief_pillars
    ]
    mastery = compute_cumulative_portfolio_xp(proj_dicts, exp_dicts)

    profile_summary = (
        f"커리어 비전: {profile.career_vision}\n"
        f"핵심 신념 요약: {profile.core_beliefs}\n"
        f"희망 직무: {profile.target_roles}"
        if profile
        else "(미설정)"
    )
    character_context = format_star_mastery_summary(mastery, pillar_dicts)
    belief_notes_context = (
        "\n".join(
            f"- [{n.source_type}] {n.source_title or '생각'}: {(n.quote_text or '')[:120]} / 생각: {n.my_reflection[:180]}"
            for n in belief_notes
        )
        or "(등록된 생각 노트 없음)"
    )
    company_context = (
        "\n\n".join(
            f"### {c.company_name} ({c.target_role or '직무 미지정'})\n"
            f"- 미션/비전: {c.mission_vision}\n"
            f"- 핵심가치: {c.core_values}\n"
            f"- 최근 동향: {c.recent_trends}"
            for c in company_profiles
        )
        or "(저장된 기업 리서치 없음)"
    )
    existing_projects_context = (
        "\n".join(
            f"- {p.name} ({', '.join(normalize_project_types(p.project_types))}) | 역할: {p.role} | 스택: {', '.join(p.tech_stack or [])} | 요약: {p.summary}"
            for p in projects
        )
        or "(등록된 프로젝트 없음)"
    )
    loop_lines: list[str] = []
    for p in projects:
        retro = p.retrospective or {}
        tries = [str(t).strip() for t in (retro.get("try_items") or []) if str(t).strip()]
        if tries:
            loop_lines.append(
                f"- [{p.name} 회고 Try 규칙] " + " / ".join(tries)
            )
    learning_loop_context = (
        "\n".join(loop_lines)
        or "(아직 이전 프로젝트 회고에서 인계된 Try 규칙 없음)"
    )
    exp_docs = [
        f"[경험] {e.title} ({e.completeness_score}점)\nAction: {e.action}\nResult: {e.result}\nLearning: {e.learning}\n지표: {e.quantified_metrics}"
        for e in experiences
    ]

    return {
        "profile_summary": profile_summary,
        "character_context": character_context,
        "belief_notes_context": belief_notes_context,
        "company_context": company_context,
        "existing_projects_context": existing_projects_context,
        "learning_loop_context": learning_loop_context,
        "experience_docs": exp_docs,
        "target_roles": profile.target_roles if profile else "",
        "company_names": [c.company_name for c in company_profiles],
    }


# ==============================================================================
# 모드 A-1: STAR-L 21지표 취약 보완 & 미증명 신념 증명용 '새 프로젝트 청사진' 추천 (웹 검색 포함)
# ==============================================================================
class BlueprintQuerySchema(BaseModel):
    queries: list[str] = Field(
        default_factory=list,
        description="최신 기술·오픈소스·실무 사례·벤치마크를 찾기 위한 웹 검색 쿼리 1~2개",
    )


class NewProjectBlueprintItem(BaseModel):
    name: str = Field(description="새 프로젝트 제안 제목 (간결하고 임팩트 있게)")
    tagline: str = Field(description="프로젝트 핵심 가치 한 줄 요약")
    project_types: list[str] = Field(
        default_factory=lambda: ["engineering"],
        description="권장 멀티트랙 조합 ID (engineering / product_planning / data_research / operations_leadership / general 중 1~2개)",
    )
    target_weaknesses: list[str] = Field(
        default_factory=list,
        description="이 새 프로젝트가 정면으로 보완해 줄 STAR-L 21지표 취약 체크포인트(예: '[R1] 정량 수치', '[A2] 대안 비교') 또는 미증명 신념 카드",
    )
    company_alignment: str = Field(
        description="리서치한 목표 기업(들)의 비전·최근 동향과 어떻게 맞물려 어필되는지 (2문장)"
    )
    problem_and_solution: str = Field(
        description="해결할 구체적 문제와 차별화 솔루션 아이디어 (3~4문장)"
    )
    recommended_stack_and_tools: list[str] = Field(
        default_factory=list,
        description="추천 기술 스택·기획/분석/협업 도구 (최대 8개)",
    )
    execution_roadmap: list[str] = Field(
        default_factory=list,
        description="실제 진행 방법 4단계 로드맵 (예: '1주차: 문제 정의 & MVP 범위 절단 ...')",
    )
    evidence_plan: list[str] = Field(
        default_factory=list,
        description="STAR-L 21지표 하드캡을 통과하기 위해 반드시 남길 정량 벤치마크(R1/R2)·대안비교 ADR(A2)·장애복구/협업 증거 2~3가지",
    )


class NewProjectBlueprintsSchema(BaseModel):
    character_focus_summary: str = Field(
        description="현재 STAR-L 21지표 마스터리(총 XP·취약 체크포인트)와 미증명 신념 기준으로 왜 이런 새 프로젝트가 가장 효과적인지 2문장 전략 요약"
    )
    blueprints: list[NewProjectBlueprintItem] = Field(
        default_factory=list,
        description="서로 다른 각도의 보완형 새 프로젝트 청사진 2~3개",
    )


async def propose_new_project_blueprints(
    *,
    company_profile_id: int | None = None,
    focus_weakness: str = "",
    topic_hint: str = "",
    use_web_search: bool = True,
) -> dict[str, Any]:
    """STAR-L 21지표 취약 체크포인트 + 미증명 신념 카드 + 기업 리서치 + 실시간 웹 검색을 결합해 새 프로젝트 청사진 2~3개를 추천한다."""
    ctx = await _load_copilot_rich_context(company_profile_id=company_profile_id)

    web_sources: list[dict[str, Any]] = []
    if use_web_search:
        try:
            q_llm = get_fast_llm(temperature=0.2, max_tokens=512)
            q_res = await ainvoke_structured(
                q_llm,
                BlueprintQuerySchema,
                [
                    SystemMessage(
                        content=(
                            "지원자의 새 포트폴리오 프로젝트 기획에 참고할 최신 실무 사례, 오픈소스 아키텍처, "
                            "또는 도메인 트렌드를 찾기 위한 간결한 웹 검색 쿼리 1~2개를 만드세요."
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"희망 직무: {ctx['target_roles']}\n"
                            f"목표 기업: {', '.join(ctx['company_names']) or '(미지정)'}\n"
                            f"보완 포커스(STAR-L 지표/신념): {focus_weakness or '(STAR-L 21지표 취약 체크포인트 전반)'}\n"
                            f"사용자 아이디어 힌트: {topic_hint or '(없음)'}\n"
                            f"기업 동향 요약:\n{ctx['company_context'][:1500]}"
                        )
                    ),
                ],
                max_retries=1,
            )
            seen_urls: set[str] = set()
            for q in (q_res.queries or [])[:2]:
                hits = await search_and_extract(q, max_results=3, fetch_top_n=1)
                for h in hits:
                    u = h.get("url") or ""
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        web_sources.append(h)
        except Exception as exc:
            logger.warning("Blueprint web search skipped/failed: %s", exc)

    web_dump = (
        "\n\n".join(
            f"- {s.get('title', '')} ({s.get('url', '')})\n  {(s.get('content') or s.get('snippet') or '')[:500]}"
            for s in web_sources[:5]
        )
        or "(웹 검색 참고 자료 없음)"
    )

    system_prompt = (
        "당신은 지원자의 **STAR-L 21지표 마스터리(총 1,000 XP · 대표 4슬롯 · 취약 체크포인트 TOP)**, "
        "**핵심 신념 카드(특히 증명 경험이 없는 신념)**, **리서치한 목표 기업 동향**, 그리고 **최신 웹 리서치 사례**를 결합해 "
        "가장 전략적인 **새로운 프로젝트 청사진 2~3개**를 설계하는 커리어 프로덕트 아키텍트입니다.\n\n"
        "핵심 설계 원칙:\n"
        "1. 기존 프로젝트와 겹치는 식상한 토이 프로젝트는 배제하고, **STAR-L 21지표 취약 체크포인트(R1 정량수치, R2 Before/After, A2 대안비교, A4 장애물돌파, A6 협업 등)**와 **미증명 신념 카드**를 정면으로 증명해 대표 프로젝트 XP(+250 XP)를 채울 수 있는 프로젝트를 제안하세요.\n"
        "2. `project_types`는 `engineering`, `product_planning`, `data_research`, `operations_leadership`, `general` 중 가장 알맞은 1~2개 트랙 ID만 사용하세요.\n"
        "3. `execution_roadmap`은 지원자가 오늘 바로 시작할 수 있도록 4단계(주차별) 구체적 실행 가이드를 제시하세요.\n"
        "4. `evidence_plan`에는 프로젝트 완료 후 21지표 엄격 채점에서 만점을 받기 위해 반드시 남길 정량 벤치마크·대안 비교 ADR·운영/협업 증거 계획을 구체적으로 포함하세요."
    )

    user_prompt = (
        f"[보완에 집중하고 싶은 STAR-L 취약 지표 / 미증명 신념] {focus_weakness or '(21지표 취약 체크포인트 TOP 5 및 미증명 신념 우선 반영)'}\n"
        f"[사용자가 떠올린 관심 주제 힌트] {topic_hint or '(자유 추천)'}\n\n"
        f"=== 1. 나의 STAR-L 21지표 마스터리 & 핵심 신념 현황 ===\n{ctx['character_context']}\n\n"
        f"=== 2. 나의 커리어 프로필 & 최근 회고 노트 ===\n{ctx['profile_summary']}\n{ctx['belief_notes_context']}\n\n"
        f"=== 3. 리서치해둔 목표 기업 동향 ===\n{ctx['company_context'][:3000]}\n\n"
        f"=== 4. 기존 보유 프로젝트 (중복 방지용) ===\n{ctx['existing_projects_context'][:2500]}\n\n"
        f"=== 5. 이전 프로젝트 회고에서 인계된 Try 규칙 (프로젝트 간 학습 루프 — 반드시 새 프로젝트 실행 로드맵에 반영!) ===\n{ctx['learning_loop_context']}\n\n"
        f"=== 6. 최신 웹 검색 레퍼런스 ===\n{web_dump[:4000]}"
    )

    llm = get_smart_llm(temperature=0.35, max_tokens=5000)
    res = await ainvoke_structured(
        llm,
        NewProjectBlueprintsSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
    )

    blueprints = []
    for bp in res.blueprints[:3]:
        d = bp.model_dump()
        d["project_types"] = normalize_project_types(d.get("project_types"))
        blueprints.append(d)

    return {
        "character_focus_summary": res.character_focus_summary.strip(),
        "blueprints": blueprints,
        "web_references": [
            {
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "snippet": (s.get("snippet") or s.get("content") or "")[:220],
            }
            for s in web_sources[:5]
        ],
    }


# ==============================================================================
# 모드 A-2: 새 프로젝트 설계 코파일럿 채팅 (Corrective RAG — 웹 검색 Fallback 최대 1회)
# ==============================================================================
class RelevanceGradeSchema(BaseModel):
    is_sufficient: bool = Field(
        description="내부 컨텍스트(캐릭터 진단·기업 리서치·보유 경험)만으로 새 프로젝트 진행 조언을 충분히 할 수 있는지 여부"
    )
    reason: str = Field(description="충분성 판단 근거 1문장")
    rewritten_query: str = Field(
        default="",
        description="최신 도구·레퍼런스·트렌드·사례 보강이 필요할 때 웹 검색에 사용할 간결한 검색 쿼리",
    )


class CopilotChatState(TypedDict, total=False):
    message: str
    chat_history: list[dict[str, str]]
    project_id: int | None
    company_profile_id: int | None
    focus_weakness: str

    experience_docs: list[str]
    character_context: str
    company_context: str
    belief_notes_context: str
    existing_projects_context: str
    learning_loop_context: str
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
    """포트폴리오 캐릭터 + 기업 리서치 + 신념/생각 노트 + 보유 프로젝트/경험을 종합 로드한다."""
    query = state["message"]
    rich = await _load_copilot_rich_context(
        company_profile_id=state.get("company_profile_id"),
        project_id=state.get("project_id"),
    )

    async with get_session_factory()() as session:
        rag_exp = await _safe_search(session, query, DocType.EXPERIENCE, top_k=4)

    exp_docs = rag_exp or rich["experience_docs"]
    return {
        "experience_docs": exp_docs,
        "character_context": rich["character_context"],
        "company_context": rich["company_context"],
        "belief_notes_context": rich["belief_notes_context"],
        "existing_projects_context": rich["existing_projects_context"],
        "learning_loop_context": rich["learning_loop_context"],
        "profile_summary": rich["profile_summary"],
        "web_search_count": 0,
        "web_sources": [],
        "used_web_fallback": False,
    }


async def relevance_grader(state: CopilotChatState) -> dict[str, Any]:
    """새 프로젝트 설계·진행 질문에 최신 외부 기술/사례 웹 검색이 필요한지 평가한다."""
    llm = get_fast_llm(temperature=0.1, max_tokens=512)

    messages = [
        SystemMessage(
            content=(
                "당신은 새 프로젝트 기획 코파일럿의 Corrective RAG 평가기입니다.\n"
                "사용자가 최신 기술 스택 비교, 오픈소스 레퍼런스, 시장/기업 트렌드, 구체적 구현 사례나 "
                "새 프로젝트 진행 방법을 묻고 있다면 is_sufficient=false로 설정해 최신 웹 검색을 1회 트리거하고 "
                "구체적인 검색 쿼리를 rewritten_query에 작성하세요.\n"
                "순전히 보유 경험 정리나 간단한 구조화 질문이라면 is_sufficient=true로 설정하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[사용자 질문]\n{state['message']}\n\n"
                f"[포커스 약점] {state.get('focus_weakness') or '(없음)'}\n\n"
                f"[리서치된 기업 컨텍스트]\n{(state.get('company_context') or '')[:1200]}\n\n"
                f"[보유 경험 요약]\n{chr(10).join(state.get('experience_docs') or [])[:1500]}"
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
    """재작성된 쿼리로 DuckDuckGo + 본문 추출 웹 검색을 최대 1회 수행한다."""
    query = state.get("rewritten_query") or state["message"]
    sources = await search_and_extract(query, max_results=4, fetch_top_n=2)
    return {
        "web_sources": sources,
        "web_search_count": int(state.get("web_search_count", 0)) + 1,
        "used_web_fallback": True,
    }


async def copilot_answer(state: CopilotChatState) -> dict[str, Any]:
    """캐릭터 약점 + 기업 리서치 + 웹 검색을 종합해 새 프로젝트 기획·진행 가이드를 생성한다."""
    llm = get_smart_llm(temperature=0.35, max_tokens=4000)

    history_lines = []
    for turn in (state.get("chat_history") or [])[-6:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        history_lines.append(f"{role}: {content}")
    history_text = "\n".join(history_lines) or "(이전 대화 없음)"

    web_text = "\n\n".join(
        f"- {s.get('title', '')} ({s.get('url', '')})\n  {(s.get('content') or s.get('snippet') or '')[:700]}"
        for s in (state.get("web_sources") or [])
    ) or "(웹 검색 미사용)"

    messages = [
        SystemMessage(
            content=(
                "당신은 지원자의 **포트폴리오 캐릭터(강점·약점·외적 사각지대)**와 **리서치해둔 목표 기업 동향**을 꿰뚫고, "
                "**새로운 프로젝트를 어떻게 기획·설계·진행하면 가장 강력하게 약점을 보완하고 차별화할 수 있는지** 코칭하는 시니어 프로젝트 코파일럿입니다.\n\n"
                "답변 원칙:\n"
                "1. 새 프로젝트를 기준으로 답하되, 지원자의 **캐릭터 약점/사각지대**를 구체적으로 어떻게 메울지(정량 지표, 일정·우선순위, 협업/운영 증거 포함) 반드시 짚어주세요.\n"
                "2. 저장된 **기업 리서치 내용**과 **웹 검색 최신 레퍼런스**가 있다면 실제 진행 방법(아키텍처·기능·검증 방식)에 구체적으로 연결하고, 웹 출처 링크를 하단에 명시하세요.\n"
                "3. 한국어 Markdown으로 구조화해 바로 실행할 수 있는 단계별 체크리스트를 포함하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[지원자 커리어 신념·프로필]\n{state.get('profile_summary') or '(미설정)'}\n"
                f"[최근 생각 노트]\n{state.get('belief_notes_context') or '(없음)'}\n\n"
                f"[포트폴리오 캐릭터 진단 & 보완 약점]\n{state.get('character_context') or '(미진단)'}\n"
                f"[사용자가 선택한 집중 약점] {state.get('focus_weakness') or '(전체 약점 참고)'}\n\n"
                f"[리서치된 목표 기업 정보]\n{(state.get('company_context') or '(없음)')[:2500]}\n\n"
                f"[기존 보유 프로젝트]\n{(state.get('existing_projects_context') or '(없음)')[:1800]}\n\n"
                f"[이전 프로젝트 회고 Try 학습 루프 (새 프로젝트에 꼭 적용할 개선 규칙)]\n{state.get('learning_loop_context') or '(없음)'}\n\n"
                f"[최근 대화]\n{history_text}\n\n"
                f"[현재 질문]\n{state['message']}\n\n"
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
# 모드 B: 지원 결과 & 취준 회고 (캐릭터 약점 대조 Gap 분석 + 코파일럿 연계)
# ==============================================================================
class RetrospectivePlanSchema(BaseModel):
    gap_analysis: str = Field(
        default="",
        description="보유 포트폴리오·캐릭터 약점·경험 대비 이번 지원 결과에서 드러난 핵심 격차(Gap) 진단 (한국어 Markdown)",
    )
    short_term_plan: list[str] = Field(
        default_factory=list,
        description="단기(1~2주) 자소서·포트폴리오·면접 답변 보강 액션 아이템 2~4개",
    )
    mid_term_plan: list[str] = Field(
        default_factory=list,
        description="중기(1~2개월) 보완형 신규 프로젝트·역량 강화 액션 아이템 2~3개",
    )
    recommended_copilot_topic: str = Field(
        default="",
        description="이 Gap을 메우기 위해 '새 프로젝트 코파일럿'에 바로 넘길 구체적인 보완 프로젝트 기획 주제 (1문장)",
    )


class RetrospectState(TypedDict, total=False):
    company_name: str
    role: str
    stage: str
    status: str
    feedback_memo: str

    portfolio_context: str
    character_context: str
    past_logs_context: str

    gap_analysis: str
    short_term_plan: list[str]
    mid_term_plan: list[str]
    action_plan: str
    recommended_copilot_topic: str
    application_log_id: int | None


async def load_retro_context(state: RetrospectState) -> dict[str, Any]:
    """보유 프로젝트, STAR 경험, 포트폴리오 캐릭터 진단, 과거 취준 회고 이력을 로드한다."""
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
    character_context = _format_character_diagnosis(
        profile.portfolio_diagnosis if profile else None
    )
    past_logs_context = "\n".join(
        f"- {log.company_name} / {log.role} / {log.stage} / {log.status}: {log.feedback_memo[:200]}"
        for log in past_logs
    ) or "(이전 지원 회고 없음)"

    return {
        "portfolio_context": portfolio_context,
        "character_context": character_context,
        "past_logs_context": past_logs_context,
    }


async def analyze_gap_and_plan(state: RetrospectState) -> dict[str, Any]:
    """지원 결과를 포트폴리오 캐릭터·경험과 대조해 Gap 진단, 단기/중기 플랜, 코파일럿 연계 주제를 도출한다."""
    llm = get_smart_llm(temperature=0.3, max_tokens=3500)

    messages = [
        SystemMessage(
            content=(
                "당신은 데이터 기반으로 취준 전략을 코칭하는 냉철한 커리어 회고 플래너입니다.\n"
                "지원 결과와 피드백을 지원자의 현재 포트폴리오·캐릭터 약점·과거 회고와 대조하여:\n"
                "1. 냉정하고 구체적인 Gap 분석(직무 역량·증거·외적 운영·표현 격차)\n"
                "2. 단기 보완 플랜(1~2주 내 자소서/포폴/면접 답변 개선)\n"
                "3. 중기 보완 플랜(1~2개월 내 보완형 신규 프로젝트/역량 강화)\n"
                "4. 이 Gap을 정면으로 메우기 위해 '새 프로젝트 코파일럿'에서 바로 기획할 수 있는 주제 1문장(`recommended_copilot_topic`)을 도출하세요."
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
                f"[나의 포트폴리오 캐릭터 진단]\n{state.get('character_context', '')}\n\n"
                f"[현재 보유 포트폴리오]\n{state.get('portfolio_context', '')}\n\n"
                f"[과거 지원 이력]\n{state.get('past_logs_context', '')}"
            )
        ),
    ]
    plan = await ainvoke_structured(llm, RetrospectivePlanSchema, messages, max_retries=2)

    short_md = "\n".join(f"- {item}" for item in plan.short_term_plan)
    mid_md = "\n".join(f"- {item}" for item in plan.mid_term_plan)
    action_plan_md = (
        f"### 단기 보완 플랜 (자소서·포폴·면접)\n{short_md}\n\n"
        f"### 중기 보완 플랜 (신규 프로젝트·역량 강화)\n{mid_md}"
    )

    return {
        "gap_analysis": plan.gap_analysis,
        "short_term_plan": plan.short_term_plan,
        "mid_term_plan": plan.mid_term_plan,
        "action_plan": action_plan_md,
        "recommended_copilot_topic": plan.recommended_copilot_topic.strip(),
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
