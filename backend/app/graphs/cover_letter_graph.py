"""워크플로우 ③: 자소서 생성 · 비평 · 퇴고 · De-AI 루프 (Critic-Refiner-Humanizer)."""

import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.bedrock import ainvoke_structured, get_smart_llm
from app.core.database import (
    CompanyProfile,
    Experience,
    Project,
    UserProfile,
    get_session_factory,
)
from app.core.project_templates import get_track_labels, normalize_project_types
from app.core.star_rubric import normalize_star_scores
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
    checkpoint_checks: list[str] = Field(
        default_factory=list,
        description="기업 문항 필수 체크포인트별 충족 여부 요약 (예: '[충족] 문제 해결 대안 비교', '[미흡] 기업 비전 연결')",
    )
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


# ==============================================================================
# Step 1: 기업 문항 심층 해부 & 최적 프로젝트·STAR 추천 (Human-in-the-Loop)
# ==============================================================================
class QuestionAnalysisSchema(BaseModel):
    question_type: str = Field(
        description="문항 유형 (예: 직무 역량 / 문제 해결 / 지원동기·가치관 / 협업·갈등 / 성장 경험)"
    )
    hidden_intent: str = Field(
        description="기업이 이 문항을 통해 실제로 확인하려는 핵심 평가 의도 (2문장)"
    )
    core_competencies: list[str] = Field(
        default_factory=list, description="이 문항에서 반드시 어필해야 할 핵심 역량 3가지"
    )
    mandatory_checkpoints: list[str] = Field(
        default_factory=list, description="자소서 본문에 반드시 포함되어야 할 필수 요소 3~4개"
    )
    pitfalls_to_avoid: list[str] = Field(
        default_factory=list, description="이 문항에서 지원자들이 흔히 저지르는 감점 실수 2~3개"
    )
    recommended_structure: list[str] = Field(
        default_factory=list,
        description="목표 글자수에 맞춘 권장 단락 구성 및 글자수 배분 (예: '1단락 두괄식 핵심 주장 (~120자)')",
    )


class RecommendedProjectItem(BaseModel):
    project_id: int = Field(description="등록된 프로젝트 ID")
    project_name: str = Field(default="", description="프로젝트명")
    fit_score: int = Field(ge=0, le=100, description="이 문항 및 기업과의 적합도 점수 (0~100)")
    is_primary: bool = Field(
        default=False, description="최우선 추천 프로젝트 1~2개에 해당하면 true"
    )
    reason: str = Field(description="왜 이 프로젝트가 이 문항에 최적인지 구체적 추천 사유")
    recommended_sections: list[str] = Field(
        default_factory=list, description="특히 활용하면 좋은 섹션 제목 목록"
    )
    fusion_angle: str = Field(
        description="이 프로젝트 사실 × 기업 신념/동향 × 지원자 신념을 어떻게 엮을지 구체 스토리 각도 (2문장)"
    )


class RecommendedExperienceItem(BaseModel):
    experience_id: int = Field(description="등록된 STAR 경험 ID")
    project_id: int | None = Field(default=None)
    title: str = Field(default="")
    fit_reason: str = Field(description="이 문항의 어떤 포인트를 증명하는 데 쓸 수 있는지 1문장")


class CoverLetterRecommendationSchema(BaseModel):
    question_analysis: QuestionAnalysisSchema
    recommended_projects: list[RecommendedProjectItem] = Field(
        default_factory=list, description="적합도 순으로 정렬된 추천 프로젝트 목록 (상위 1~2개 is_primary=true)"
    )
    recommended_experiences: list[RecommendedExperienceItem] = Field(
        default_factory=list, description="함께 녹이면 설득력이 높아지는 핵심 STAR 경험 최대 4개"
    )
    overall_strategy: str = Field(
        description="기업 신념 + 나의 신념 + 추천 프로젝트를 한 줄기로 엮는 전체 작성 전략 (2~3문장)"
    )


async def recommend_cover_letter_materials(
    *,
    company_name: str,
    company_profile_id: int | None = None,
    target_role: str = "",
    question: str,
    char_limit: int = 800,
) -> dict[str, Any]:
    """기업이 제공한 자소서 문항을 먼저 심층 분석하고, 등록된 프로젝트·STAR 중 최적 1~2개를 추천한다."""
    async with get_session_factory()() as session:
        profile = await session.get(UserProfile, 1)

        company_profile: CompanyProfile | None = None
        if company_profile_id:
            company_profile = await session.get(CompanyProfile, company_profile_id)
        if company_profile is None and company_name.strip():
            stmt = (
                select(CompanyProfile)
                .where(CompanyProfile.company_name == company_name.strip())
                .order_by(CompanyProfile.created_at.desc())
                .limit(1)
            )
            company_profile = (await session.execute(stmt)).scalar_one_or_none()

        projects = (
            (
                await session.execute(
                    select(Project)
                    .options(
                        selectinload(Project.sections),
                        selectinload(Project.experiences),
                    )
                    .order_by(Project.created_at.desc(), Project.id.desc())
                )
            )
            .scalars()
            .all()
        )
        all_experiences = (
            (
                await session.execute(
                    select(Experience).order_by(
                        Experience.completeness_score.desc(),
                        Experience.created_at.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    # 프론트엔드 선택기용 전체 카탈로그 구성
    available_projects = [
        {
            "id": p.id,
            "name": p.name,
            "period": p.period,
            "role": p.role,
            "summary": p.summary,
            "project_types": normalize_project_types(p.project_types),
            "tech_stack": list(p.tech_stack or []),
            "filled_section_count": sum(
                1 for s in p.sections if (s.content or "").strip()
            ),
            "experience_count": len(p.experiences),
        }
        for p in projects
    ]
    available_experiences = [
        {
            "id": e.id,
            "project_id": e.project_id,
            "title": e.title,
            "completeness_score": e.completeness_score,
            "quantified_metrics": e.quantified_metrics,
            "star_scores": normalize_star_scores(e.star_scores),
        }
        for e in all_experiences
    ]

    profile_text = (
        f"- 커리어 비전: {profile.career_vision}\n"
        f"- 핵심 신념: {profile.core_beliefs}\n"
        f"- 희망 직무: {profile.target_roles}\n"
        f"- 선호 문체: {profile.preferred_tone}"
        if profile
        else "(미등록)"
    )

    company_text = (
        f"- 기업명: {company_profile.company_name} ({company_profile.target_role})\n"
        f"- 미션/비전: {company_profile.mission_vision}\n"
        f"- 핵심가치/인재상: {company_profile.core_values}\n"
        f"- 최근 동향: {company_profile.recent_trends}\n"
        f"- 3각 매칭 분석: {company_profile.value_alignment_map}"
        if company_profile
        else f"- 기업명: {company_name} / 직무: {target_role or '(미지정)'} (저장된 기업 리서치 없음 — 문항 자체와 직무 기준으로 심층 분석)"
    )

    project_catalog_blocks = []
    for p in projects:
        types = ", ".join(get_track_labels(p.project_types))
        sec_summaries = "\n".join(
            f"    · [{s.title}] {(s.content or '').strip()[:260]}"
            for s in p.sections
            if (s.content or "").strip()
        )
        project_catalog_blocks.append(
            f"  [project_id={p.id}] {p.name} | 유형: {types} | 역할: {p.role or '미입력'} | 기간: {p.period or '미입력'}\n"
            f"  기술·역량: {', '.join(p.tech_stack or [])}\n"
            f"  요약: {p.summary or '(없음)'}\n"
            f"  주요 섹션:\n{sec_summaries or '    (비어 있음)'}"
        )

    exp_catalog_blocks = [
        f"  [experience_id={e.id}, project_id={e.project_id}] {e.title} (STAR 점수 {e.completeness_score}) | "
        f"A={(e.action or '')[:140]} | R={(e.result or '')[:120]} | 지표={e.quantified_metrics}"
        for e in all_experiences[:20]
    ]

    system_prompt = (
        "당신은 대한민국 주요 기업·빅테크 채용 서류 심사위원 출신 자소서 전략 컨설턴트입니다.\n"
        "사용자가 입력한 **기업 제공 자소서 문항**을 최우선 중심에 두고 다음 2가지를 정밀 수행하세요:\n"
        "1. `question_analysis`: 이 문항이 표면적으로 묻는 말 너머에 **기업이 진짜 검증하려는 평가 역량·숨은 의도·필수 체크포인트·피해야 할 실수·글자수 배분**을 날카롭게 해부하세요.\n"
        "2. `recommended_projects` & `recommended_experiences`: 등록된 지원자 프로젝트와 STAR 목록 중에서 "
        "이 문항과 기업 신념/인재상에 가장 강력하게 맞물리는 **핵심 프로젝트 1~2개(`is_primary=true`)**와 보조 STAR 경험을 추천하고, "
        "각 프로젝트를 **기업 신념 × 지원자 신념**과 어떻게 엮어야 설득력이 극대화되는지 `fusion_angle`을 제시하세요.\n"
        "규칙:\n"
        "- 반드시 제공된 `project_id`와 `experience_id` 정수 ID만 정확히 사용하세요. 없는 ID를 만들지 마세요.\n"
        "- 등록된 프로젝트가 없으면 `recommended_projects`는 빈 리스트로 두고 문항 분석에 집중하세요."
    )

    user_prompt = (
        f"[지원 기업 & 직무]\n{company_text}\n\n"
        f"[기업 제공 자소서 문항 (목표 분량: 공백 포함 {char_limit}자)]\n{question}\n\n"
        f"[지원자 커리어 신념 & 비전]\n{profile_text}\n\n"
        f"[등록된 포트폴리오 프로젝트 풀 ({len(projects)}건)]\n"
        + ("\n\n".join(project_catalog_blocks)[:12000] if project_catalog_blocks else "(등록된 프로젝트 없음)")
        + f"\n\n[등록된 STAR 경험 풀 ({len(all_experiences)}건)]\n"
        + ("\n".join(exp_catalog_blocks)[:4000] if exp_catalog_blocks else "(등록된 STAR 경험 없음)")
    )

    llm = get_smart_llm(temperature=0.25, max_tokens=4500)
    rec = await ainvoke_structured(
        llm,
        CoverLetterRecommendationSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
    )

    valid_proj_ids = {p["id"]: p["name"] for p in available_projects}
    valid_exp_ids = {e["id"]: e for e in available_experiences}

    clean_rec_projects = []
    for item in rec.recommended_projects:
        if item.project_id in valid_proj_ids:
            d = item.model_dump()
            d["project_name"] = valid_proj_ids[item.project_id]
            clean_rec_projects.append(d)
    clean_rec_projects.sort(key=lambda x: (not x["is_primary"], -x["fit_score"]))

    clean_rec_exps = []
    for item in rec.recommended_experiences:
        if item.experience_id in valid_exp_ids:
            e_meta = valid_exp_ids[item.experience_id]
            d = item.model_dump()
            d["title"] = e_meta["title"]
            d["project_id"] = e_meta["project_id"]
            clean_rec_exps.append(d)

    return {
        "question_analysis": rec.question_analysis.model_dump(),
        "recommended_projects": clean_rec_projects,
        "recommended_experiences": clean_rec_exps,
        "overall_strategy": rec.overall_strategy.strip(),
        "company_matched": bool(company_profile),
        "company_summary": (
            {
                "id": company_profile.id,
                "company_name": company_profile.company_name,
                "mission_vision": company_profile.mission_vision,
                "core_values": company_profile.core_values,
            }
            if company_profile
            else None
        ),
        "available_projects": available_projects,
        "available_experiences": available_experiences,
    }


class CoverLetterState(TypedDict, total=False):
    company_name: str
    company_profile_id: int | None
    target_role: str
    question: str
    char_limit: int
    extra_instructions: str
    selected_project_ids: list[int]
    selected_experience_ids: list[int]
    question_analysis: dict[str, Any]
    fusion_angle: str

    selected_portfolio_docs: list[str]
    used_projects: list[dict[str, Any]]
    used_experiences: list[dict[str, Any]]
    experience_docs: list[str]
    identity_docs: list[str]
    company_docs: list[str]
    sample_docs: list[str]
    preferred_tone: str

    draft: str
    critic_score: int
    critic_feedback: str
    critic_history: list[dict[str, Any]]
    checkpoint_checks: list[str]
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
    """사용자 선택 프로젝트/STAR를 1급 팩트로 직접 로드하고, doc_type 4종을 엄격 분리 검색한다."""
    query = f"{state['company_name']} {state.get('target_role', '')} {state['question']}".strip()
    sel_proj_ids = [int(i) for i in (state.get("selected_project_ids") or []) if str(i).isdigit()]
    sel_exp_ids = [int(i) for i in (state.get("selected_experience_ids") or []) if str(i).isdigit()]

    selected_portfolio_docs: list[str] = []
    used_projects: list[dict[str, Any]] = []
    used_experiences: list[dict[str, Any]] = []

    async with get_session_factory()() as session:
        # 0. 사용자가 직접 선택한 프로젝트(전체 섹션 + 연결 STAR) 및 선택 STAR를 DB에서 직접 1급 팩트로 로드
        seen_exp_ids: set[int] = set()
        if sel_proj_ids:
            proj_stmt = (
                select(Project)
                .where(Project.id.in_(sel_proj_ids))
                .options(
                    selectinload(Project.sections),
                    selectinload(Project.experiences),
                )
            )
            sel_projects = (await session.execute(proj_stmt)).scalars().all()
            for p in sel_projects:
                used_projects.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "project_types": normalize_project_types(p.project_types),
                        "role": p.role,
                    }
                )
                sec_lines = "\n".join(
                    f"  - [{s.track}/{s.title}]\n    {s.content.strip()}"
                    for s in sorted(p.sections, key=lambda x: x.display_order)
                    if (s.content or "").strip()
                )
                block = (
                    f"[선택 핵심 프로젝트 #{p.id}] {p.name} ({p.period or '기간 미입력'} | 역할: {p.role or '미입력'})\n"
                    f"유형: {', '.join(get_track_labels(p.project_types))}\n"
                    f"기술·역량: {', '.join(p.tech_stack or [])}\n"
                    f"요약: {p.summary}\n"
                    f"커리어 목표 연결: {p.portfolio_goal_link}\n"
                    f"[상세 섹션 원문]\n{sec_lines or '  (작성된 섹션 없음)'}"
                )
                selected_portfolio_docs.append(block)
                # 선택 프로젝트에 연결된 STAR 경험도 함께 주입 (명시 선택 목록이 따로 없을 때)
                if not sel_exp_ids:
                    for e in p.experiences:
                        seen_exp_ids.add(e.id)
                        used_experiences.append({"id": e.id, "title": e.title, "project_id": e.project_id})
                        selected_portfolio_docs.append(
                            f"[연결 STAR-L 경험] {e.title} (완성도 {e.completeness_score})\n"
                            f"S: {e.situation}\nT: {e.task}\nA: {e.action}\nR: {e.result}\n"
                            f"L: {e.learning}\n정량 지표: {e.quantified_metrics}"
                        )

        if sel_exp_ids:
            exp_stmt = select(Experience).where(Experience.id.in_(sel_exp_ids))
            sel_exps = (await session.execute(exp_stmt)).scalars().all()
            for e in sel_exps:
                if e.id in seen_exp_ids:
                    continue
                seen_exp_ids.add(e.id)
                used_experiences.append({"id": e.id, "title": e.title, "project_id": e.project_id})
                selected_portfolio_docs.append(
                    f"[선택 핵심 STAR-L 경험] {e.title} (완성도 {e.completeness_score})\n"
                    f"S: {e.situation}\nT: {e.task}\nA: {e.action}\nR: {e.result}\n"
                    f"L: {e.learning}\n정량 지표: {e.quantified_metrics}"
                )

        # 1. 보조 벡터 검색 (doc_type 4종 엄격 격리)
        rag_exp_docs = await _safe_vector_search(session, query, DocType.EXPERIENCE, top_k=4)
        id_docs = await _safe_vector_search(session, query, DocType.CAREER_IDENTITY, top_k=2)
        comp_docs = await _safe_vector_search(session, query, DocType.COMPANY_RESEARCH, top_k=3)
        sample_docs = await _safe_vector_search(session, query, DocType.JASOSEO_SAMPLE, top_k=3)

        profile = await session.get(UserProfile, 1)
        preferred_tone = profile.preferred_tone if profile else ""

        if profile:
            id_text = (
                f"[지원자 커리어 정체성 원문]\n"
                f"- 커리어 비전: {profile.career_vision}\n"
                f"- 핵심 신념: {profile.core_beliefs}\n"
                f"- 희망 직무: {profile.target_roles}"
            ).strip()
            if id_text:
                id_docs = [id_text, *id_docs]

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
                f"핵심가치/인재상: {company_profile.core_values}\n"
                f"최근 동향: {company_profile.recent_trends}\n"
                f"3각 매칭: {company_profile.value_alignment_map}"
            )
            comp_docs = [comp_summary, *comp_docs]

        # 사용자가 프로젝트를 선택했다면 선택 팩트를 최우선으로, 아니면 RAG + DB 폴백 결합
        if selected_portfolio_docs:
            exp_docs = selected_portfolio_docs
        elif rag_exp_docs:
            exp_docs = rag_exp_docs
        else:
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
        "selected_portfolio_docs": selected_portfolio_docs,
        "used_projects": used_projects,
        "used_experiences": used_experiences,
        "experience_docs": exp_docs,
        "identity_docs": id_docs,
        "company_docs": comp_docs,
        "sample_docs": sample_docs,
        "preferred_tone": preferred_tone,
        "revision_count": 0,
        "critic_history": [],
        "checkpoint_checks": [],
    }


def _format_question_analysis_block(qa: dict[str, Any] | None) -> str:
    if not qa:
        return "(사전 문항 분석 없음 — 문항 원문의 핵심 요구사항을 직접 충족하세요)"
    lines = []
    if qa.get("question_type"):
        lines.append(f"- 문항 유형: {qa['question_type']}")
    if qa.get("hidden_intent"):
        lines.append(f"- 기업 숨은 평가 의도: {qa['hidden_intent']}")
    if qa.get("core_competencies"):
        lines.append(f"- 필수 어필 역량: {', '.join(qa['core_competencies'])}")
    if qa.get("mandatory_checkpoints"):
        lines.append(
            "- 본문 필수 체크포인트:\n  "
            + "\n  ".join(f"• {c}" for c in qa["mandatory_checkpoints"])
        )
    if qa.get("recommended_structure"):
        lines.append(
            "- 권장 단락/글자수 배분:\n  "
            + "\n  ".join(f"• {s}" for s in qa["recommended_structure"])
        )
    return "\n".join(lines)


async def drafter(state: CoverLetterState) -> dict[str, Any]:
    """기업 문항 핵심 의도 × 선택 프로젝트·STAR × 기업·나의 신념 3축을 융합해 1차 초안을 작성한다."""
    llm = get_smart_llm(temperature=0.45, max_tokens=4000)
    char_limit = state.get("char_limit") or 800
    qa_block = _format_question_analysis_block(state.get("question_analysis"))

    system_prompt = (
        "당신은 기업이 제공한 자소서 문항의 숨은 평가 의도를 정확히 관통하면서, "
        "지원자가 선택한 실제 프로젝트·STAR 경험과 커리어 신념, 그리고 목표 기업의 이념을 하나의 설득력 있는 서사로 엮는 한국어 자기소개서 전문가입니다.\n"
        f"[필수 환각 방지 규칙]\n{ANTI_HALLUCINATION_RULE}\n\n"
        "작성 원칙:\n"
        f"1. **문항 최우선:** 기업이 제시한 문항의 모든 질문 요소와 필수 체크포인트에 빠짐없이 답하세요.\n"
        f"2. **분량 엄수:** 공백 포함 약 {char_limit}자 내외(±10%) 분량으로 작성하세요.\n"
        "3. **선택 소재 활용:** 아래 1번에 제공된 지원자의 선택 프로젝트·STAR 팩트를 스토리의 뼈대로 삼되, 구체적 행동(Action)·기술/방법론·정량 근거(Result)를 중심에 두세요.\n"
        "4. **신념 융합:** 지원자의 커리어 신념이 어떻게 해당 프로젝트 행동으로 증명되었고, 그것이 왜 목표 기업의 비전·핵심가치와 맞닿아 있는지 자연스럽게 연결하세요.\n"
        "5. `experience`에 없는 수치·기간·성과·기술명은 절대 추가하지 마세요.\n"
        "6. 소제목 1줄 + 자연스러운 본문 단락 형태로 깔끔하게 출력하세요."
    )

    user_prompt = (
        f"[지원 기업] {state['company_name']} / [지원 직무] {state.get('target_role') or '(미지정)'}\n"
        f"[기업 제공 자소서 문항]\n{state['question']}\n\n"
        f"[문항 심층 분석 & 필수 체크포인트]\n{qa_block}\n\n"
        f"[기업 신념 × 나의 신념 × 프로젝트 융합 방향]\n{state.get('fusion_angle') or '(제공된 신념과 프로젝트의 교집합을 자연스럽게 도출)'}\n"
        f"[사용자 추가 요청] {state.get('extra_instructions') or '없음'}\n\n"
        f"=== 1. 지원자 선택 프로젝트 · STAR 실제 팩트 (experience - 유일한 사실 근거) ===\n"
        f"{chr(10).join(state.get('experience_docs') or ['(등록된 경험 없음)'])[:12000]}\n\n"
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
    """면접관 관점에서 문항 체크포인트 충족도, 선택 소재 팩트 밀도, 기업·내 신념 융합도, 환각 여부를 엄격 채점한다."""
    llm = get_smart_llm(temperature=0.15, max_tokens=3000)
    qa_block = _format_question_analysis_block(state.get("question_analysis"))

    messages = [
        SystemMessage(
            content=(
                "당신은 대기업·유니콘 테크 기업 현업 실무 면접관입니다.\n"
                f"환각 검증 기준: {ANTI_HALLUCINATION_RULE}\n"
                "아래 기준으로 초안을 냉정하게 0~100점으로 평가하세요:\n"
                "- **기업 문항 의도 및 필수 체크포인트 충족도 (30점)** — 문항이 묻는 본질에서 벗어나면 크게 감점\n"
                "- **지원자 선택 프로젝트/STAR(`experience`) 기반 행동·정량 근거 구체성 (30점)**\n"
                "- **기업 비전·가치와 지원자 신념의 자연스러운 3축 융합 (25점)**\n"
                "- **목표 글자 수 준수 및 가독성/설득력 (15점)**\n"
                "필수: `checkpoint_checks`에 각 문항 체크포인트의 `[충족]`/`[미흡]` 여부를 기록하고, "
                "`experience`에 없는 수치·기업명·경험이 섞였다면 반드시 `hallucination_warnings`에 적고 크게 감점하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[지원 기업] {state['company_name']} / [직무] {state.get('target_role', '')}\n"
                f"[문항] {state['question']} (목표 글자 수: {state.get('char_limit', 800)}자, 현재 초안 글자 수: {len(state.get('draft', ''))}자)\n\n"
                f"[문항 분석 & 필수 체크포인트]\n{qa_block}\n\n"
                f"[지원자 신념]\n{chr(10).join(state.get('identity_docs') or [])[:1500]}\n\n"
                f"[기업 정보]\n{chr(10).join(state.get('company_docs') or [])[:2000]}\n\n"
                f"[원본 사실 근거 (experience)]\n{chr(10).join(state.get('experience_docs') or [])[:9000]}\n\n"
                f"[평가 대상 초안 (수정 {state.get('revision_count', 0)}회차)]\n{state.get('draft', '')}"
            )
        ),
    ]
    evaluation = await ainvoke_structured(llm, CriticEvaluationSchema, messages, max_retries=2)

    history = list(state.get("critic_history") or [])
    history.append(
        {
            "revision": state.get("revision_count", 0),
            "score": evaluation.critic_score,
            "strengths": evaluation.strengths,
            "weaknesses": evaluation.weaknesses,
            "checkpoint_checks": evaluation.checkpoint_checks,
            "hallucination_warnings": evaluation.hallucination_warnings,
            "feedback": evaluation.actionable_feedback,
        }
    )

    return {
        "critic_score": evaluation.critic_score,
        "critic_feedback": evaluation.actionable_feedback,
        "critic_history": history,
        "checkpoint_checks": evaluation.checkpoint_checks,
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
