"""워크플로우 ③: 자소서 생성 · 비평 · 퇴고 · De-AI 루프 (Critic-Refiner-Humanizer)."""

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
    UserProfile,
    get_session_factory,
)
from app.core.vector_store import DocType, search_documents

logger = logging.getLogger(__name__)

ANTI_HALLUCINATION_RULE = (
    "`jasoseo_sample`은 문단 전개 구조와 설득 논리만 참고한다. "
    "샘플 속 경험·수치·기업명을 지원자의 사실처럼 차용하는 것을 엄격히 금지하며, "
    "모든 사실 근거는 `experience`에서만 가져온다."
)

DE_AI_CLICHE_LIST = (
    '"~을 통해 한 단계 성장", "귀사의 무궁한 발전", "혁신적인 시너지", '
    '"단순한 ~을 넘어", "결론적으로", "이를 바탕으로", "끊임없이 도전하는"'
)


class CriticEvaluationSchema(BaseModel):
    critic_score: int = Field(ge=0, le=100, description="면접관 관점 종합 점수 (0~100)")
    strengths: list[str] = Field(default_factory=list, description="잘 쓰인 강점")
    weaknesses: list[str] = Field(default_factory=list, description="감점 요인 및 개선 필요 지점")
    hallucination_warnings: list[str] = Field(
        default_factory=list,
        description="experience 사실 근거에 없는 수치/경험이 섞였는지 점검 경고",
    )
    actionable_feedback: str = Field(description="Refiner가 즉시 반영할 구체적 수정 지시")


class HumanizerOutputSchema(BaseModel):
    final_text: str = Field(description="AI 문체를 제거하고 지원자 문체로 다듬은 최종 자소서 본문")
    humanizer_changes: list[str] = Field(
        default_factory=list,
        description="단계별·표현별로 무엇을 왜 고쳤는지 요약한 변경 리포트 (Diff Summary)",
    )


class CoverLetterState(TypedDict, total=False):
    company_name: str
    company_profile_id: int | None
    target_role: str
    question: str
    char_limit: int
    extra_instructions: str

    experience_docs: list[str]
    identity_docs: list[str]
    company_docs: list[str]
    sample_docs: list[str]
    preferred_tone: str

    draft: str
    critic_score: int
    critic_feedback: str
    critic_history: list[dict[str, Any]]
    revision_count: int
    final_text: str
    humanizer_changes: list[str]


async def _safe_vector_search(session, query: str, doc_type: DocType, top_k: int) -> list[str]:
    try:
        hits = await search_documents(
            session,
            query=query,
            doc_types=[doc_type],
            top_k=top_k,
        )
        return [hit.content for hit in hits]
    except Exception as exc:
        logger.warning("Vector search fallback for doc_type=%s: %s", doc_type.value, exc)
        return []


async def multi_source_retriever(state: CoverLetterState) -> dict[str, Any]:
    """doc_type 4종(experience, career_identity, company_research, jasoseo_sample)을 엄격 분리 검색한다."""
    query = f"{state['company_name']} {state.get('target_role', '')} {state['question']}".strip()

    async with get_session_factory()() as session:
        exp_docs = await _safe_vector_search(session, query, DocType.EXPERIENCE, top_k=5)
        id_docs = await _safe_vector_search(session, query, DocType.CAREER_IDENTITY, top_k=2)
        comp_docs = await _safe_vector_search(session, query, DocType.COMPANY_RESEARCH, top_k=3)
        sample_docs = await _safe_vector_search(session, query, DocType.JASOSEO_SAMPLE, top_k=3)

        profile = await session.get(UserProfile, 1)
        preferred_tone = profile.preferred_tone if profile else ""

        if not id_docs and profile:
            id_text = (
                f"비전: {profile.career_vision}\n"
                f"신념: {profile.core_beliefs}\n"
                f"희망 직무: {profile.target_roles}"
            ).strip()
            if id_text:
                id_docs = [id_text]

        # 선택된 기업 프로필이 있으면 최우선 컨텍스트로 포함
        company_profile: CompanyProfile | None = None
        if state.get("company_profile_id"):
            company_profile = await session.get(CompanyProfile, state["company_profile_id"])
        if company_profile is None:
            stmt = (
                select(CompanyProfile)
                .where(CompanyProfile.company_name == state["company_name"])
                .order_by(CompanyProfile.created_at.desc())
                .limit(1)
            )
            company_profile = (await session.execute(stmt)).scalar_one_or_none()

        if company_profile:
            comp_summary = (
                f"[저장된 기업 리서치] {company_profile.company_name} ({company_profile.target_role})\n"
                f"미션/비전: {company_profile.mission_vision}\n"
                f"핵심가치: {company_profile.core_values}\n"
                f"최근 동향: {company_profile.recent_trends}\n"
                f"3각 매칭: {company_profile.value_alignment_map}"
            )
            comp_docs = [comp_summary, *comp_docs]

        # 벡터에 경험이 아직 없다면 정형 DB에서 최신 경험 로드
        if not exp_docs:
            exps = (
                (
                    await session.execute(
                        select(Experience)
                        .order_by(Experience.completeness_score.desc(), Experience.created_at.desc())
                        .limit(5)
                    )
                )
                .scalars()
                .all()
            )
            exp_docs = [
                (
                    f"[경험] {e.title}\n"
                    f"S: {e.situation}\nT: {e.task}\nA: {e.action}\nR: {e.result}\n"
                    f"지표: {e.quantified_metrics}"
                )
                for e in exps
            ]

    return {
        "experience_docs": exp_docs,
        "identity_docs": id_docs,
        "company_docs": comp_docs,
        "sample_docs": sample_docs,
        "preferred_tone": preferred_tone,
        "revision_count": 0,
        "critic_history": [],
    }


async def drafter(state: CoverLetterState) -> dict[str, Any]:
    """분리 검색된 4종 소스를 결합해 1차 자소서 초안을 작성한다."""
    llm = get_smart_llm(temperature=0.45)
    char_limit = state.get("char_limit") or 800

    system_prompt = (
        "당신은 지원자의 실제 경험과 커리어 신념을 목표 기업의 비전과 자연스럽게 엮는 한국어 자기소개서 전문가입니다.\n"
        f"[필수 환각 방지 규칙]\n{ANTI_HALLUCINATION_RULE}\n\n"
        "작성 원칙:\n"
        f"1. 공백 포함 약 {char_limit}자 내외(±10%) 분량으로 작성하세요.\n"
        "2. 두괄식 핵심 메시지로 시작하고, 구체적 행동(Action)·기술명·정량 근거(Result)를 중심에 두세요.\n"
        "3. `experience`에 없는 수치·기간·성과·기술명은 절대 추가하지 마세요.\n"
        "4. 소제목 1줄 + 자연스러운 본문 단락 형태로 깔끔하게 출력하세요."
    )

    user_prompt = (
        f"[지원 기업] {state['company_name']} / [지원 직무] {state.get('target_role') or '(미지정)'}\n"
        f"[자소서 문항]\n{state['question']}\n"
        f"[추가 요청] {state.get('extra_instructions') or '없음'}\n\n"
        f"=== 1. 지원자 실제 경험 팩트 (experience - 유일한 사실 근거) ===\n"
        f"{chr(10).join(state.get('experience_docs') or ['(등록된 경험 없음)'])}\n\n"
        f"=== 2. 지원자 신념·비전 (career_identity) ===\n"
        f"{chr(10).join(state.get('identity_docs') or ['(미등록)'])}\n\n"
        f"=== 3. 목표 기업 리서치 & 3각 매칭 (company_research) ===\n"
        f"{chr(10).join(state.get('company_docs') or ['(미등록)'])}\n\n"
        f"=== 4. 전개 구조 참고용 레퍼런스 (jasoseo_sample - 구조·논리만 참고, 사실 차용 절대 금지) ===\n"
        f"{chr(10).join(state.get('sample_docs') or ['(등록된 레퍼런스 없음)'])}"
    )

    response = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    draft_text = response.content if isinstance(response.content, str) else str(response.content)
    return {"draft": draft_text.strip()}


async def critic(state: CoverLetterState) -> dict[str, Any]:
    """면접관 관점에서 초안의 문항 적합성, 기업 연결성, 정량 근거, 환각 여부를 엄격 채점한다."""
    llm = get_smart_llm(temperature=0.15)

    messages = [
        SystemMessage(
            content=(
                "당신은 대기업·유니콘 테크 기업 현업 실무 면접관입니다.\n"
                f"환각 검증 기준: {ANTI_HALLUCINATION_RULE}\n"
                "아래 기준으로 초안을 냉정하게 0~100점으로 평가하세요:\n"
                "- 문항 의도 적중도 (25점)\n"
                "- 지원자 사실(`experience`) 기반 정량 근거 및 트러블슈팅 구체성 (30점)\n"
                "- 기업 비전·직무와 지원자 신념의 자연스러운 연결 (25점)\n"
                "- 글자 수 적합성 및 가독성/설득력 (20점)\n"
                "만약 `experience`에 없는 수치·기업명·경험이 섞였다면 반드시 hallucination_warnings에 적고 크게 감점하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[지원 기업] {state['company_name']} / [직무] {state.get('target_role', '')}\n"
                f"[문항] {state['question']} (목표 글자 수: {state.get('char_limit', 800)}자)\n\n"
                f"[원본 사실 근거 (experience)]\n{chr(10).join(state.get('experience_docs') or [])}\n\n"
                f"[평가 대상 초안 (수정 {state.get('revision_count', 0)}회차)]\n{state.get('draft', '')}"
            )
        ),
    ]
    evaluation = await ainvoke_structured(llm, CriticEvaluationSchema, messages, max_retries=1)

    history = list(state.get("critic_history") or [])
    history.append(
        {
            "revision": state.get("revision_count", 0),
            "score": evaluation.critic_score,
            "strengths": evaluation.strengths,
            "weaknesses": evaluation.weaknesses,
            "hallucination_warnings": evaluation.hallucination_warnings,
            "feedback": evaluation.actionable_feedback,
        }
    )

    return {
        "critic_score": evaluation.critic_score,
        "critic_feedback": evaluation.actionable_feedback,
        "critic_history": history,
    }


def route_after_critic(state: CoverLetterState) -> str:
    """루프 안전장치 (agents_md.md 5.1): revision_count >= 2 또는 critic_score >= 85이면 무조건 De-AI로 이동."""
    if state.get("revision_count", 0) >= 2 or state.get("critic_score", 0) >= 85:
        return "de_ai_humanizer"
    return "refiner"


async def refiner(state: CoverLetterState) -> dict[str, Any]:
    """면접관 비평 피드백을 반영해 초안을 퇴고한다."""
    llm = get_smart_llm(temperature=0.35)
    next_rev = int(state.get("revision_count", 0)) + 1

    messages = [
        SystemMessage(
            content=(
                "당신은 면접관의 비평을 반영해 자소서의 설득력과 밀도를 끌어올리는 시니어 에디터입니다.\n"
                f"[필수 환각 방지 규칙]\n{ANTI_HALLUCINATION_RULE}\n"
                "사실 근거에 없는 내용을 지어내지 말고, 지적된 약점과 환각 경고를 정확히 수정해 본문 전체를 다시 작성하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[문항] {state['question']} (목표 글자 수: {state.get('char_limit', 800)}자)\n\n"
                f"[현재 초안]\n{state.get('draft', '')}\n\n"
                f"[면접관 비평 (점수: {state.get('critic_score', 0)}/100)]\n{state.get('critic_feedback', '')}\n\n"
                f"[원본 사실 근거 (experience)]\n{chr(10).join(state.get('experience_docs') or [])}"
            )
        ),
    ]
    response = await llm.ainvoke(messages)
    revised_text = response.content if isinstance(response.content, str) else str(response.content)

    return {
        "draft": revised_text.strip(),
        "revision_count": next_rev,
    }


async def de_ai_humanizer(state: CoverLetterState) -> dict[str, Any]:
    """De-AI Humanizer (agents_md.md 5.2): AI 상투어 제거, 추상 수식어 축소, 문장 리듬 & 선호 문체 반영."""
    llm = get_smart_llm(temperature=0.35)
    preferred_tone = state.get("preferred_tone") or "담백하고 구체적인 실무 엔지니어 문체"

    messages = [
        SystemMessage(
            content=(
                "당신은 AI가 쓴 티를 완전히 지우고 실제 지원자가 직접 쓴 듯한 자연스러운 글로 다듬는 "
                "De-AI Humanizer입니다.\n"
                "필수 체크리스트:\n"
                f"1. 상투적 AI 표현을 모두 제거·치환하세요 ({DE_AI_CLICHE_LIST}).\n"
                "2. 과도한 추상 명사·수식어를 줄이고 실제 기술명, 수치, 행동 동사 중심으로 고치세요.\n"
                "3. 단문과 중문을 섞어 문장 길이 리듬을 다양화하고, 지원자의 선호 문체를 자연스럽게 반영하세요.\n"
                "4. 원문에 없는 새로운 사실/수치를 절대 추가하지 마세요.\n"
                "5. 무엇을 어떻게 고쳤는지 `humanizer_changes` 리스트에 구체적으로 기록하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[목표 글자 수] 약 {state.get('char_limit', 800)}자\n"
                f"[지원자 선호 문체 (preferred_tone)]\n{preferred_tone}\n\n"
                f"[퇴고 완료 초안]\n{state.get('draft', '')}"
            )
        ),
    ]
    result = await ainvoke_structured(llm, HumanizerOutputSchema, messages, max_retries=1)
    return {
        "final_text": result.final_text.strip(),
        "humanizer_changes": result.humanizer_changes,
    }


def build_cover_letter_graph():
    workflow = StateGraph(CoverLetterState)
    workflow.add_node("multi_source_retriever", multi_source_retriever)
    workflow.add_node("drafter", drafter)
    workflow.add_node("critic", critic)
    workflow.add_node("refiner", refiner)
    workflow.add_node("de_ai_humanizer", de_ai_humanizer)

    workflow.add_edge(START, "multi_source_retriever")
    workflow.add_edge("multi_source_retriever", "drafter")
    workflow.add_edge("drafter", "critic")
    workflow.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "refiner": "refiner",
            "de_ai_humanizer": "de_ai_humanizer",
        },
    )
    workflow.add_edge("refiner", "critic")
    workflow.add_edge("de_ai_humanizer", END)
    return workflow.compile()
