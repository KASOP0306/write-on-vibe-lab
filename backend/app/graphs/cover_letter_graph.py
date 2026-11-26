"""워크플로우 ③: 자소서 생성 · 비평 · 퇴고 · De-AI 루프 (Critic-Refiner-Humanizer) + 신념 1급 연동."""

import logging
import re
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.bedrock import ainvoke_structured, ainvoke_tracked, get_smart_llm
from app.core.database import (
    BeliefNote,
    BeliefPillar,
    CompanyProfile,
    Experience,
    Project,
    UserProfile,
    get_session_factory,
)
from app.core.project_templates import get_track_labels, normalize_project_types
from app.core.star_rubric import normalize_star_scores
from app.core.vector_store import DocType, format_hits_with_citations, search_documents
from app.prompts import build_chat_prompt

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

DE_AI_CLICHE_SUBSTRINGS = (
    "한 단계 성장",
    "귀사의 무궁한 발전",
    "혁신적인 시너지",
    "결론적으로",
    "끊임없이 도전하는",
)

_METRIC_TOKEN_RE = re.compile(
    r"(?<!\d)\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%p|%|배|ms|초|분|시간|만\s*명|만\s*건|억|건|명)"
)

PILLAR_CAT_LABELS = {
    "human_value": "인간·인문학 가치",
    "social_impact": "사회적 문제의식",
    "career_calling": "커리어 지향",
    "tech_and_people": "기술과 사람의 관계",
    "work_principle": "커리어 지향",
    "problem_lens": "사회적 문제의식",
    "collaboration": "인간·인문학 가치",
    "career_direction": "커리어 지향",
}


def validate_cover_letter_post_checks(
    final_text: str,
    experience_docs: list[str] | None = None,
    sample_docs: list[str] | None = None,
) -> list[str]:
    """코드 레벨 사후 검증 (Unit 2): 금지 AI 클리셰 잔존 및 jasoseo_sample 수치 유입을 자동 탐지한다."""
    warnings: list[str] = []
    text = (final_text or "").strip()
    if not text:
        return ["최종 자소서 본문이 비어 있습니다."]

    found_cliches = [c for c in DE_AI_CLICHE_SUBSTRINGS if c in text]
    if found_cliches:
        warnings.append(f"AI 상투어 잔존 감지: {', '.join(found_cliches)}")

    exp_joined = "\n".join(experience_docs or [])
    sample_joined = "\n".join(sample_docs or [])
    if sample_joined:
        exp_metrics = {m.replace(" ", "") for m in _METRIC_TOKEN_RE.findall(exp_joined)}
        sample_metrics = {m.replace(" ", "") for m in _METRIC_TOKEN_RE.findall(sample_joined)}
        final_metrics = {m.replace(" ", "") for m in _METRIC_TOKEN_RE.findall(text)}
        leaked = sorted((final_metrics & sample_metrics) - exp_metrics)
        if leaked:
            warnings.append(
                f"레퍼런스 샘플 전용 수치 혼입 의심(experience 미확인): {', '.join(leaked)}"
            )
    return warnings


class CriticEvaluationSchema(BaseModel):
    critic_score: int = Field(ge=0, le=100, description="면접관 관점 종합 점수 (0~100)")
    strengths: list[str] = Field(default_factory=list, description="잘 쓰인 강점")
    weaknesses: list[str] = Field(default_factory=list, description="감점 요인 및 개선 필요 지점")
    checkpoint_checks: list[str] = Field(
        default_factory=list,
        description="기업 문항 필수 체크포인트 및 [신념 연결] 충족 여부 요약 (예: '[충족] 문제 해결 대안 비교', '[충족] 신념 연결: ...')",
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
# Step 1: 기업 문항 심층 해부 & 최적 프로젝트·STAR·신념 카드·회고 노트 추천 (HITL)
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


class RecommendedBeliefPillarItem(BaseModel):
    belief_id: int = Field(description="등록된 핵심 신념 카드(BeliefPillar) ID")
    title: str = Field(default="")
    fit_reason: str = Field(description="이 문항에서 왜 이 신념 카드가 강력한 중심축이 되는지 1문장")
    belief_to_company_bridge: str = Field(
        description="이 신념이 목표 기업의 핵심가치·비전 및 추천 프로젝트 행동과 어떻게 맞물리는지 1문장"
    )


class RecommendedBeliefNoteItem(BaseModel):
    note_id: int = Field(description="등록된 일상 회고·구절 노트(BeliefNote) ID")
    source_title: str = Field(default="")
    fit_reason: str = Field(description="이 구절·회고를 자소서에 어떻게 진정성 있게 녹일지 1문장")


class CoverLetterRecommendationSchema(BaseModel):
    question_analysis: QuestionAnalysisSchema
    recommended_projects: list[RecommendedProjectItem] = Field(
        default_factory=list, description="적합도 순으로 정렬된 추천 프로젝트 목록 (상위 1~2개 is_primary=true)"
    )
    recommended_experiences: list[RecommendedExperienceItem] = Field(
        default_factory=list, description="함께 녹이면 설득력이 높아지는 핵심 STAR 경험 최대 4개"
    )
    recommended_belief_pillars: list[RecommendedBeliefPillarItem] = Field(
        default_factory=list, description="이 문항과 기업 인재상에 가장 잘 맞물리는 핵심 신념 카드 1~2개"
    )
    recommended_belief_notes: list[RecommendedBeliefNoteItem] = Field(
        default_factory=list, description="진정성과 차별화를 더해줄 일상 회고·독서 구절 노트 최대 2개"
    )
    overall_strategy: str = Field(
        description="기업 신념 + 나의 신념 카드 + 추천 프로젝트를 한 줄기로 엮는 전체 작성 전략 (2~3문장)"
    )


async def recommend_cover_letter_materials(
    *,
    company_name: str,
    company_profile_id: int | None = None,
    target_role: str = "",
    question: str,
    char_limit: int = 800,
) -> dict[str, Any]:
    """기업이 제공한 자소서 문항을 먼저 심층 분석하고, 프로젝트·STAR·신념 카드·회고 노트 중 최적 조합을 추천한다."""
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
        all_pillars = (
            (
                await session.execute(
                    select(BeliefPillar).order_by(
                        BeliefPillar.created_at.desc(), BeliefPillar.id.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        all_notes = (
            (
                await session.execute(
                    select(BeliefNote).order_by(
                        BeliefNote.created_at.desc(), BeliefNote.id.desc()
                    ).limit(15)
                )
            )
            .scalars()
            .all()
        )

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
    available_belief_pillars = [
        {
            "id": b.id,
            "title": b.title,
            "category": b.category,
            "tradeoff_rule": b.tradeoff_rule,
            "linked_project_ids": list(b.linked_project_ids or []),
            "linked_experience_ids": list(b.linked_experience_ids or []),
        }
        for b in all_pillars
    ]
    available_belief_notes = [
        {
            "id": n.id,
            "source_type": n.source_type,
            "source_title": n.source_title,
            "quote_text": n.quote_text[:180],
            "my_reflection": n.my_reflection[:220],
            "tags": list(n.tags or []),
        }
        for n in all_notes
    ]

    profile_text = (
        f"- 커리어 비전: {profile.career_vision}\n"
        f"- 핵심 신념 요약: {profile.core_beliefs}\n"
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

    pillar_catalog_blocks = [
        f"  [belief_id={b.id}] ({PILLAR_CAT_LABELS.get(b.category, b.category)}) {b.title}\n"
        f"    · 커리어 지향·가치: {b.tradeoff_rule or '(미입력)'}\n"
        f"    · 연결 프로젝트 ID: {list(b.linked_project_ids or [])} / 연결 STAR ID: {list(b.linked_experience_ids or [])}"
        for b in all_pillars
    ]
    note_catalog_blocks = [
        f"  [note_id={n.id}] ({n.source_type}) {n.source_title or '생각 노트'} | "
        f"구절: {(n.quote_text or '')[:110]} | 회고: {n.my_reflection[:180]}"
        for n in all_notes
    ]

    system_prompt = (
        "당신은 대한민국 주요 기업·빅테크 채용 서류 심사위원 출신 자소서 전략 컨설턴트입니다.\n"
        "사용자가 입력한 **기업 제공 자소서 문항**을 최우선 중심에 두고 다음 3가지를 정밀 수행하세요:\n"
        "1. `question_analysis`: 이 문항이 표면적으로 묻는 말 너머에 **기업이 진짜 검증하려는 평가 역량·숨은 의도·필수 체크포인트·피해야 할 실수·글자수 배분**을 날카롭게 해부하세요.\n"
        "2. `recommended_projects` & `recommended_experiences`: 등록된 지원자 프로젝트와 STAR 목록 중에서 "
        "이 문항과 기업 신념/인재상에 가장 강력하게 맞물리는 **핵심 프로젝트 1~2개(`is_primary=true`)**와 보조 STAR 경험을 추천하고, "
        "`fusion_angle`에 기업 신념 × 지원자 신념 × 프로젝트 행동의 융합 각도를 제시하세요.\n"
        "3. `recommended_belief_pillars` & `recommended_belief_notes`: 등록된 **핵심 신념 카드(`belief_id`)** 중 1~2개와 "
        "**일상 회고·구절 노트(`note_id`)** 중 최대 2개를 골라, 이 문항에서 어떻게 진정성 있는 중심 철학으로 녹일지 제안하세요.\n"
        "규칙:\n"
        "- 반드시 제공된 `project_id`, `experience_id`, `belief_id`, `note_id` 정수 ID만 정확히 사용하세요. 없는 ID를 만들지 마세요.\n"
        "- 해당 풀이 비어 있으면 빈 리스트로 두세요."
    )

    user_prompt = (
        f"[지원 기업 & 직무]\n{company_text}\n\n"
        f"[기업 제공 자소서 문항 (목표 분량: 공백 포함 {char_limit}자)]\n{question}\n\n"
        f"[지원자 커리어 프로필 요약]\n{profile_text}\n\n"
        f"[지원자 핵심 신념 카드 풀 ({len(all_pillars)}건)]\n"
        + ("\n".join(pillar_catalog_blocks)[:3500] if pillar_catalog_blocks else "(등록된 신념 카드 없음)")
        + f"\n\n[지원자 일상 회고·구절 저널 풀 ({len(all_notes)}건)]\n"
        + ("\n".join(note_catalog_blocks)[:2800] if note_catalog_blocks else "(등록된 회고 노트 없음)")
        + f"\n\n[등록된 포트폴리오 프로젝트 풀 ({len(projects)}건)]\n"
        + ("\n\n".join(project_catalog_blocks)[:10000] if project_catalog_blocks else "(등록된 프로젝트 없음)")
        + f"\n\n[등록된 STAR 경험 풀 ({len(all_experiences)}건)]\n"
        + ("\n".join(exp_catalog_blocks)[:3500] if exp_catalog_blocks else "(등록된 STAR 경험 없음)")
    )

    llm = get_smart_llm(temperature=0.25, max_tokens=4500)
    rec = await ainvoke_structured(
        llm,
        CoverLetterRecommendationSchema,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_retries=2,
        caller="cover_letter:recommend",
    )

    valid_proj_ids = {p["id"]: p["name"] for p in available_projects}
    valid_exp_ids = {e["id"]: e for e in available_experiences}
    valid_pillar_ids = {b["id"]: b for b in available_belief_pillars}
    valid_note_ids = {n["id"]: n for n in available_belief_notes}

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

    clean_rec_pillars = []
    for item in rec.recommended_belief_pillars:
        if item.belief_id in valid_pillar_ids:
            b_meta = valid_pillar_ids[item.belief_id]
            d = item.model_dump()
            d["title"] = b_meta["title"]
            clean_rec_pillars.append(d)

    clean_rec_notes = []
    for item in rec.recommended_belief_notes:
        if item.note_id in valid_note_ids:
            n_meta = valid_note_ids[item.note_id]
            d = item.model_dump()
            d["source_title"] = n_meta["source_title"] or "일상 회고 노트"
            clean_rec_notes.append(d)

    return {
        "question_analysis": rec.question_analysis.model_dump(),
        "recommended_projects": clean_rec_projects,
        "recommended_experiences": clean_rec_exps,
        "recommended_belief_pillars": clean_rec_pillars,
        "recommended_belief_notes": clean_rec_notes,
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
        "profile_identity_summary": {
            "career_vision": profile.career_vision if profile else "",
            "core_beliefs": profile.core_beliefs if profile else "",
            "pillar_count": len(available_belief_pillars),
            "note_count": len(available_belief_notes),
        },
        "available_projects": available_projects,
        "available_experiences": available_experiences,
        "available_belief_pillars": available_belief_pillars,
        "available_belief_notes": available_belief_notes,
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
    selected_belief_ids: list[int]
    selected_belief_note_ids: list[int]
    question_analysis: dict[str, Any]
    fusion_angle: str

    selected_portfolio_docs: list[str]
    used_projects: list[dict[str, Any]]
    used_experiences: list[dict[str, Any]]
    used_beliefs: list[dict[str, Any]]
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
    post_check_warnings: list[str]


async def _safe_vector_search(session, query: str, doc_type: DocType, top_k: int) -> list[str]:
    try:
        hits = await search_documents(
            session,
            query=query,
            doc_types=[doc_type],
            top_k=top_k,
            strategy="hybrid",
            use_mmr=True,
            max_distance=0.84,
        )
        if not hits:
            return []
        return [format_hits_with_citations(hits, max_chars_per_hit=700)]
    except Exception as exc:
        logger.warning("Vector search fallback for doc_type=%s: %s", doc_type.value, exc)
        return []


async def multi_source_retriever(state: CoverLetterState) -> dict[str, Any]:
    """선택 프로젝트·STAR·신념 카드·회고 노트를 DB에서 직접 1급 팩트로 로드하고, doc_type 4종을 엄격 분리 검색한다."""
    query = f"{state['company_name']} {state.get('target_role', '')} {state['question']}".strip()
    sel_proj_ids = [int(i) for i in (state.get("selected_project_ids") or []) if str(i).isdigit()]
    sel_exp_ids = [int(i) for i in (state.get("selected_experience_ids") or []) if str(i).isdigit()]
    sel_belief_ids = [int(i) for i in (state.get("selected_belief_ids") or []) if str(i).isdigit()]
    sel_note_ids = [int(i) for i in (state.get("selected_belief_note_ids") or []) if str(i).isdigit()]

    selected_portfolio_docs: list[str] = []
    used_projects: list[dict[str, Any]] = []
    used_experiences: list[dict[str, Any]] = []
    used_beliefs: list[dict[str, Any]] = []
    direct_identity_docs: list[str] = []

    async with get_session_factory()() as session:
        # 0-A. 선택 프로젝트 & STAR 경험 직접 로드
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

        # 0-B. 선택 핵심 신념 카드(BeliefPillar) & 회고 노트(BeliefNote) DB 직접 1급 로드 (벡터 누락 방지!)
        if sel_belief_ids:
            chosen_pillars = (
                (await session.execute(select(BeliefPillar).where(BeliefPillar.id.in_(sel_belief_ids))))
                .scalars()
                .all()
            )
        else:
            # 명시 선택이 없더라도 등록된 신념 카드 상위 3개를 자동 기본 주입
            chosen_pillars = (
                (
                    await session.execute(
                        select(BeliefPillar).order_by(BeliefPillar.created_at.desc()).limit(3)
                    )
                )
                .scalars()
                .all()
            )

        for b in chosen_pillars:
            cat_label = PILLAR_CAT_LABELS.get(b.category, b.category)
            used_beliefs.append(
                {"kind": "pillar", "id": b.id, "title": b.title, "category": cat_label}
            )
            direct_identity_docs.append(
                f"[선택 핵심 신념 카드 #{b.id} | {cat_label}] {b.title}\n"
                f"- 커리어 지향 · 지키는 가치: {b.tradeoff_rule or '(미입력)'}\n"
                f"- 형성 계기 · 사유: {b.origin_story or '(미입력)'}"
            )

        if sel_note_ids:
            chosen_notes = (
                (await session.execute(select(BeliefNote).where(BeliefNote.id.in_(sel_note_ids))))
                .scalars()
                .all()
            )
        elif not chosen_pillars:
            chosen_notes = (
                (
                    await session.execute(
                        select(BeliefNote).order_by(BeliefNote.created_at.desc()).limit(2)
                    )
                )
                .scalars()
                .all()
            )
        else:
            chosen_notes = []

        for n in chosen_notes:
            title = n.source_title or "일상 회고 노트"
            used_beliefs.append(
                {"kind": "note", "id": n.id, "title": title, "category": n.source_type}
            )
            direct_identity_docs.append(
                f"[선택 일상 회고·구절 #{n.id}] {title}\n"
                + (f"- 인상 깊은 구절: {n.quote_text}\n" if n.quote_text.strip() else "")
                + f"- 나의 생각·회고: {n.my_reflection}"
            )

        # 1. 보조 벡터 검색 (doc_type 4종 엄격 격리)
        rag_exp_docs = await _safe_vector_search(session, query, DocType.EXPERIENCE, top_k=4)
        rag_id_docs = await _safe_vector_search(session, query, DocType.CAREER_IDENTITY, top_k=2)
        comp_docs = await _safe_vector_search(session, query, DocType.COMPANY_RESEARCH, top_k=3)
        sample_docs = await _safe_vector_search(session, query, DocType.JASOSEO_SAMPLE, top_k=3)

        profile = await session.get(UserProfile, 1)
        preferred_tone = profile.preferred_tone if profile else ""

        id_docs: list[str] = []
        if profile and (profile.career_vision or profile.core_beliefs or profile.target_roles):
            id_text = (
                f"[지원자 커리어 정체성 요약]\n"
                f"- 커리어 비전: {profile.career_vision}\n"
                f"- 핵심 신념 요약: {profile.core_beliefs}\n"
                f"- 희망 직무: {profile.target_roles}"
            ).strip()
            id_docs.append(id_text)
        id_docs.extend(direct_identity_docs)
        if not direct_identity_docs and rag_id_docs:
            id_docs.extend(rag_id_docs)

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
        "used_beliefs": used_beliefs,
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
    """기업 문항 핵심 의도 × 선택 프로젝트·STAR-L × 선택 신념 카드·기업 가치 3축을 융합해 1차 초안을 작성한다."""
    llm = get_smart_llm(temperature=0.45, max_tokens=4000)
    char_limit = state.get("char_limit") or 800
    qa_block = _format_question_analysis_block(state.get("question_analysis"))

    messages = build_chat_prompt(
        "cover_letter_draft",
        (
            "[지원 기업] {company_name} / [지원 직무] {target_role}\n"
            "[기업 제공 자소서 문항]\n{question}\n\n"
            "[문항 심층 분석 & 필수 체크포인트]\n{qa_block}\n\n"
            "[기업 신념 × 나의 신념 × 프로젝트 융합 방향]\n{fusion_angle}\n"
            "[사용자 추가 요청] {extra_instructions}\n\n"
            "=== 1. 지원자 선택 프로젝트 · STAR-L 실제 팩트 (experience - 유일한 사실 근거) ===\n"
            "{experience_block}\n\n"
            "=== 2. 지원자 핵심 신념 카드 · 회고 노트 · 비전 (career_identity - 반드시 행동의 이유와 연결) ===\n"
            "{identity_block}\n\n"
            "=== 3. 목표 기업 리서치 & 3각 매칭 (company_research) ===\n"
            "{company_block}\n\n"
            "=== 4. 전개 구조 참고용 레퍼런스 (jasoseo_sample - 구조·논리만 참고, 사실 차용 절대 금지) ===\n"
            "{sample_block}"
        ),
        system_vars={
            "anti_hallucination_rule": ANTI_HALLUCINATION_RULE,
            "char_limit": char_limit,
        },
        human_vars={
            "company_name": state["company_name"],
            "target_role": state.get("target_role") or "(미지정)",
            "question": state["question"],
            "qa_block": qa_block,
            "fusion_angle": state.get("fusion_angle") or "(제공된 신념 카드와 프로젝트 행동의 교집합을 자연스럽게 도출)",
            "extra_instructions": state.get("extra_instructions") or "없음",
            "experience_block": "\n".join(state.get("experience_docs") or ["(등록된 경험 없음)"])[:12000],
            "identity_block": "\n\n".join(state.get("identity_docs") or ["(미등록)"])[:4000],
            "company_block": "\n".join(state.get("company_docs") or ["(미등록)"])[:3500],
            "sample_block": "\n".join(state.get("sample_docs") or ["(등록된 레퍼런스 없음)"]),
        },
    )

    response = await ainvoke_tracked(llm, messages, caller="cover_letter:drafter")
    draft_text = response.content if isinstance(response.content, str) else str(response.content)
    return {"draft": draft_text.strip()}


async def critic(state: CoverLetterState) -> dict[str, Any]:
    """면접관 관점에서 문항 체크포인트 충족도, 선택 소재 팩트 밀도, 기업·내 신념 융합도, 환각 여부를 엄격 채점한다."""
    llm = get_smart_llm(temperature=0.15, max_tokens=3000)
    qa_block = _format_question_analysis_block(state.get("question_analysis"))

    messages = build_chat_prompt(
        "cover_letter_critic",
        (
            "[지원 기업] {company_name} / [직무] {target_role}\n"
            "[문항] {question} (목표 글자 수: {char_limit}자, 현재 초안 글자 수: {draft_len}자)\n\n"
            "[문항 분석 & 필수 체크포인트]\n{qa_block}\n\n"
            "[지원자 핵심 신념 카드 · 회고 노트]\n{identity_block}\n\n"
            "[기업 정보]\n{company_block}\n\n"
            "[원본 사실 근거 (experience)]\n{experience_block}\n\n"
            "[평가 대상 초안 (수정 {revision_count}회차)]\n{draft}"
        ),
        system_vars={"anti_hallucination_rule": ANTI_HALLUCINATION_RULE},
        human_vars={
            "company_name": state["company_name"],
            "target_role": state.get("target_role", ""),
            "question": state["question"],
            "char_limit": state.get("char_limit", 800),
            "draft_len": len(state.get("draft", "")),
            "qa_block": qa_block,
            "identity_block": "\n\n".join(state.get("identity_docs") or ["(미등록)"])[:3000],
            "company_block": "\n".join(state.get("company_docs") or [])[:2500],
            "experience_block": "\n".join(state.get("experience_docs") or [])[:9000],
            "revision_count": state.get("revision_count", 0),
            "draft": state.get("draft", ""),
        },
    )
    evaluation = await ainvoke_structured(
        llm,
        CriticEvaluationSchema,
        messages,
        max_retries=2,
        caller=f"cover_letter:critic_r{state.get('revision_count', 0)}",
    )

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


def build_refiner_messages(state: CoverLetterState):
    """Refiner 프롬프트 조립 헬퍼 (신념 카드·기업 정보 유지 검증 테스트 가능하도록 분리)."""
    return build_chat_prompt(
        "cover_letter_refiner",
        (
            "[문항] {question} (목표 글자 수: {char_limit}자)\n\n"
            "[현재 초안]\n{draft}\n\n"
            "[면접관 비평 (점수: {critic_score}/100)]\n{critic_feedback}\n\n"
            "[지원자 핵심 신념·회고 (퇴고 시 반드시 유지·강화)]\n{identity_block}\n\n"
            "[기업 정보 (핵심가치·비전 연결 유지)]\n{company_block}\n\n"
            "[원본 사실 근거 (experience)]\n{experience_block}"
        ),
        system_vars={"anti_hallucination_rule": ANTI_HALLUCINATION_RULE},
        human_vars={
            "question": state["question"],
            "char_limit": state.get("char_limit", 800),
            "draft": state.get("draft", ""),
            "critic_score": state.get("critic_score", 0),
            "critic_feedback": state.get("critic_feedback", ""),
            "identity_block": "\n\n".join(state.get("identity_docs") or ["(미등록)"])[:2800],
            "company_block": "\n".join(state.get("company_docs") or ["(미등록)"])[:2200],
            "experience_block": "\n".join(state.get("experience_docs") or [])[:9000],
        },
    )


async def refiner(state: CoverLetterState) -> dict[str, Any]:
    """면접관 비평 피드백을 반영해 신념·기업 연결을 유지하며 초안을 퇴고한다."""
    llm = get_smart_llm(temperature=0.35)
    next_rev = int(state.get("revision_count", 0)) + 1
    messages = build_refiner_messages(state)
    response = await ainvoke_tracked(llm, messages, caller=f"cover_letter:refiner_r{next_rev}")
    revised_text = response.content if isinstance(response.content, str) else str(response.content)

    return {
        "draft": revised_text.strip(),
        "revision_count": next_rev,
    }


async def de_ai_humanizer(state: CoverLetterState) -> dict[str, Any]:
    """De-AI Humanizer (agents_md.md 5.2) + 코드 레벨 사후 검증(Unit 2)."""
    llm = get_smart_llm(temperature=0.35)
    preferred_tone = state.get("preferred_tone") or "담백하고 구체적인 실무 엔지니어 문체"

    messages = build_chat_prompt(
        "cover_letter_humanizer",
        (
            "[목표 글자 수] 약 {char_limit}자\n"
            "[지원자 선호 문체 (preferred_tone)]\n{preferred_tone}\n\n"
            "[보존해야 할 지원자 핵심 신념]\n{identity_block}\n\n"
            "[퇴고 완료 초안]\n{draft}"
        ),
        system_vars={"de_ai_cliche_list": DE_AI_CLICHE_LIST},
        human_vars={
            "char_limit": state.get("char_limit", 800),
            "preferred_tone": preferred_tone,
            "identity_block": "\n\n".join(state.get("identity_docs") or ["(없음)"])[:1500],
            "draft": state.get("draft", ""),
        },
    )
    result = await ainvoke_structured(
        llm,
        HumanizerOutputSchema,
        messages,
        max_retries=1,
        caller="cover_letter:de_ai_humanizer",
    )
    final_text = result.final_text.strip()
    post_warnings = validate_cover_letter_post_checks(
        final_text,
        experience_docs=state.get("experience_docs"),
        sample_docs=state.get("sample_docs"),
    )
    if post_warnings:
        logger.warning("Cover letter post-check warnings: %s", post_warnings)

    return {
        "final_text": final_text,
        "humanizer_changes": result.humanizer_changes,
        "post_check_warnings": post_warnings,
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
