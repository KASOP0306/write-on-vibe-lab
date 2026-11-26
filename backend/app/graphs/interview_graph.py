"""워크플로우 ①: 경험 채굴 & 연속 역질문 루프 (Active Interviewer v2.0).

핵심 아키텍처:
- 0. load_project_context: 연결된 프로젝트 요약·섹션·직무 트랙 자동 로드 + 최근 사용자 피드백 기반 동적 규칙 주입
- 1. prepare_turn: 답변 병합 · 직전 21지표/점수 스냅샷 · force_save 단축 경로
- 2. extract_star: 프로젝트 맥락 + 누적 Q&A 통합 5축 STAR-L 추출
- 3. grade_gaps: 21개 Atomic 체크포인트 3단계 하이브리드 평가 + ΔSTAR-L/해금 수 DB 기록
- 4. generate_questions: 0점 고배점 체크포인트 정조준 + <user_feedback_rules> + 보수적 루프 A(<70 또는 린트 결함)
- 5. save_experience: experiences(rubric_version + 21지표 스냅샷) & pgvector(doc_type='experience') 영속 저장
"""

from collections import Counter
import logging
from typing import Any, TypedDict

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import AsyncConnection
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.bedrock import ainvoke_structured, get_fast_llm
from app.core.database import (
    Experience,
    Project,
    QuestionFeedbackLog,
    get_psycopg_conninfo,
    get_session_factory,
)
from app.core.question_critic import (
    MAX_QUESTION_REVISIONS,
    PASS_SCORE_THRESHOLD,
    critique_and_refine_questions,
)
from app.core.star_rubric import (
    PROBING_TECHNIQUES,
    STAR_AXIS_ORDER,
    STAR_CHECKPOINTS_BY_ID,
    evaluate_star_experience_rubric,
)
from app.core.vector_store import DocType, try_upsert_document
from app.prompts import build_chat_prompt

logger = logging.getLogger(__name__)

NEGATIVE_REASON_GUIDANCE: dict[str, str] = {
    "already_answered": "이미 프로젝트 요약이나 앞선 답변에 적힌 사실은 절대 다시 묻지 마세요.",
    "too_abstract": "추상적·교과서적 질문 대신 원문의 특정 상황·행동·수치를 직접 지목해 구체적으로 물어보세요.",
    "role_mismatch": "사용자의 직무 트랙(개발/기획/데이터/운영)에 맞지 않는 용어나 억지 지표 질문은 피하세요.",
    "too_complex": "질문은 반드시 핵심 1가지만 묻는 100자 이내 짧은 1문장으로 작성하세요.",
}


class StarExtractionSchema(BaseModel):
    title: str = Field(description="경험을 한눈에 요약하는 구체적 제목 (30자 내외)")
    situation: str = Field(description="배경 및 문제 상황 (Situation)")
    task: str = Field(description="본인이 맡은 과제 및 목표 (Task)")
    action: str = Field(description="본인이 직접 수행한 구체적 행동·의사결정 (Action)")
    result: str = Field(description="결과 및 변화 (Result)")
    learning: str = Field(
        default="",
        description="이 경험에서 배운 점, 한계 성찰, 재발 방지 설계, 다음 프로젝트·직무에 적용할 원칙 (Learning)",
    )
    quantified_metrics: str = Field(
        default="",
        description="확인된 정량 지표/수치만 정리 (없으면 빈 문자열, 절대 추측/날조 금지)",
    )


class StructuredProbeQuestion(BaseModel):
    technique: str = Field(
        default="micro_behavioral",
        description="ownership_drilldown | micro_behavioral | counter_factual | xyz_quantification | learning_transfer",
    )
    target_axis: str = Field(
        default="action",
        description="보강할 STAR-L 핵심 축 (situation | task | action | result | learning)",
    )
    target_checkpoint_id: str = Field(
        default="",
        description="정조준할 21개 체크포인트 ID (예: R1, A2, A3, R2, T2)",
    )
    question: str = Field(
        description="모호한 표현을 파고드는 짧고 날카로운 한국어 개방형 역질문 1문장 (110자 이내)"
    )
    interviewer_intent: str = Field(
        default="",
        description="면접관이 이 역질문으로 무엇을 검증하려는지 1줄 설명",
    )


class FollowupQuestionsSchema(BaseModel):
    questions: list[StructuredProbeQuestion] = Field(
        default_factory=list,
        description="가장 점수가 낮고 배점이 큰 미충족 체크포인트를 공략하는 역질문 2개",
    )


class InterviewState(TypedDict, total=False):
    thread_id: str
    raw_notes: str
    project_id: int | None
    project_name: str
    project_types: list[str]
    project_context: str
    user_feedback_rules: str
    qa_history: list[dict[str, Any]]
    latest_reply: str
    skip_extraction: bool
    force_save: bool
    star: dict[str, str]
    completeness_score: int
    initial_score: int | None
    star_scores: dict[str, Any]
    is_sufficient: bool
    missing_points: list[str]
    questions: list[str]
    structured_questions: list[dict[str, Any]]
    prev_completeness_score: int | None
    prev_checkpoints: dict[str, int]
    prev_structured_questions: list[dict[str, Any]]
    last_unlocked_checkpoints: int
    question_critic_score: int
    question_critic_revisions: int
    enable_question_critic: bool
    saved_experience_id: int | None
    vector_synced: bool


def _build_context_text(state: InterviewState, max_recent_turns: int = 6) -> str:
    """프로젝트 요약 + 초기 메모 + 최근 Q&A 턴을 조합한다."""
    lines: list[str] = []
    project_ctx = str(state.get("project_context") or "").strip()
    if project_ctx:
        lines.append(f"[연결된 프로젝트 요약 컨텍스트]\n{project_ctx}")

    raw_notes = str(state.get("raw_notes") or "").strip()
    if raw_notes:
        lines.append(f"\n[초기 경험 메모]\n{raw_notes}")
    elif project_ctx:
        lines.append("\n[초기 경험 메모]\n(프로젝트 요약 전체를 기반으로 핵심 경험을 채굴합니다.)")

    qa_history = state.get("qa_history") or []
    if qa_history:
        older = qa_history[:-max_recent_turns] if len(qa_history) > max_recent_turns else []
        recent = qa_history[-max_recent_turns:]
        if older:
            lines.append("\n[이전 턴 요약 (압축)]")
            for idx, turn in enumerate(older, start=1):
                ans = str(turn.get("answer", "")).strip()
                lines.append(f"- 턴 {idx} 핵심 답변: {ans[:180]}{'...' if len(ans) > 180 else ''}")
        lines.append("\n[최근 질의응답 누적]")
        offset = len(older)
        for idx, turn in enumerate(recent, start=offset + 1):
            qs = " / ".join(turn.get("questions") or [])
            ans = turn.get("answer", "")
            lines.append(f"턴 {idx} 질문: {qs}\n턴 {idx} 답변: {ans}")
    return "\n".join(lines).strip()


async def _load_dynamic_feedback_rules() -> str:
    """최근 사용자 👍/👎 피드백과 ΔSTAR-L 로그를 집계해 동적 질문 규칙 문자열을 생성한다."""
    try:
        async with get_session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(QuestionFeedbackLog)
                        .order_by(QuestionFeedbackLog.created_at.desc())
                        .limit(80)
                    )
                )
                .scalars()
                .all()
            )
    except Exception as exc:
        logger.debug("Skipping dynamic feedback rules load: %s", exc)
        return "(누적 사용자 피드백 없음 — 기본 프로빙 규칙을 준수하세요.)"

    if not rows:
        return "(누적 사용자 피드백 없음 — 기본 프로빙 규칙을 준수하세요.)"

    neg_reasons = Counter(
        r.user_reason for r in rows if r.user_vote == -1 and r.user_reason
    )
    tech_deltas: dict[str, list[int]] = {}
    for r in rows:
        if r.delta_score > 0 or r.user_vote == 1:
            tech_deltas.setdefault(r.technique, []).append(int(r.delta_score))

    rules: list[str] = []
    if neg_reasons:
        for reason_key, cnt in neg_reasons.most_common(3):
            guidance = NEGATIVE_REASON_GUIDANCE.get(reason_key)
            if guidance:
                rules.append(f"- [최근 사용자 👎 최다 지적({cnt}회)] {guidance}")

    if tech_deltas:
        ranked_techs = sorted(
            tech_deltas.items(),
            key=lambda kv: (sum(kv[1]) / max(1, len(kv[1])), len(kv[1])),
            reverse=True,
        )[:2]
        best_desc = ", ".join(
            f"{k}(평균 +{round(sum(v)/max(1,len(v)), 1)}점)" for k, v in ranked_techs
        )
        rules.append(f"- [실제 ΔSTAR-L 효과가 높았던 기법] {best_desc} 스타일을 우선 활용하세요.")

    return "\n".join(rules) if rules else "(특이 피드백 패턴 없음 — 기본 프로빙 규칙을 준수하세요.)"


async def load_project_context(state: InterviewState) -> dict[str, Any]:
    """연결된 프로젝트의 요약·섹션·직무 트랙과 최근 사용자 피드백 규칙을 상태에 로드한다."""
    updates: dict[str, Any] = {}
    project_id = state.get("project_id")

    # 프로젝트 컨텍스트는 최초 로드 또는 project_id 변경 시 갱신
    if project_id is not None and not state.get("project_context"):
        try:
            async with get_session_factory()() as session:
                stmt = (
                    select(Project)
                    .options(selectinload(Project.sections))
                    .where(Project.id == int(project_id))
                )
                project = (await session.execute(stmt)).scalar_one_or_none()
                if project is not None:
                    lines = [
                        f"프로젝트명: {project.name}",
                        f"기간: {project.period or '(미기재)'} | 역할: {project.role or '(미기재)'}",
                        f"직무 트랙: {', '.join(project.project_types or ['engineering'])}",
                    ]
                    if project.tech_stack:
                        lines.append(f"기술/도구: {', '.join(str(t) for t in project.tech_stack[:15])}")
                    if project.summary:
                        lines.append(f"한줄/전체 요약: {project.summary[:700]}")
                    filled_sections = [
                        s for s in project.sections if (s.content or "").strip()
                    ]
                    if filled_sections:
                        lines.append("주요 작성 섹션 요약:")
                        budget = 2200
                        used = 0
                        for sec in filled_sections:
                            snippet = sec.content.strip()[:450]
                            entry = f"- [{sec.title}] {snippet}"
                            if used + len(entry) > budget:
                                break
                            lines.append(entry)
                            used += len(entry)
                    updates["project_name"] = project.name
                    updates["project_types"] = list(project.project_types or ["engineering"])
                    updates["project_context"] = "\n".join(lines)
        except Exception as exc:
            logger.warning("Failed to load project context for project_id=%s: %s", project_id, exc)

    updates["user_feedback_rules"] = await _load_dynamic_feedback_rules()
    return updates


async def prepare_turn(state: InterviewState) -> dict[str, Any]:
    """사용자 추가 답변을 누적 이력에 병합하고, 직전 점수·21지표 스냅샷과 force_save 단축 경로를 판별한다."""
    qa_history = list(state.get("qa_history") or [])
    latest_reply = (state.get("latest_reply") or "").strip()

    prev_score = state.get("completeness_score") if latest_reply else None
    prev_qs = list(state.get("structured_questions") or []) if latest_reply else []
    prev_cps_raw = (state.get("star_scores") or {}).get("checkpoints") or {}
    prev_checkpoints = (
        {cid: int(item.get("status", 0)) for cid, item in prev_cps_raw.items() if isinstance(item, dict)}
        if latest_reply and isinstance(prev_cps_raw, dict)
        else {}
    )

    if latest_reply:
        qa_history.append(
            {
                "questions": list(state.get("questions") or []),
                "answer": latest_reply,
            }
        )

    has_existing_star = bool((state.get("star") or {}).get("title"))
    skip_extraction = bool(state.get("force_save")) and has_existing_star and not latest_reply

    return {
        "qa_history": qa_history,
        "latest_reply": "",
        "skip_extraction": skip_extraction,
        "prev_completeness_score": prev_score,
        "prev_checkpoints": prev_checkpoints,
        "prev_structured_questions": prev_qs,
    }


def route_after_prepare(state: InterviewState) -> str:
    if state.get("skip_extraction"):
        return "save_experience"
    return "extract_star"


async def extract_star(state: InterviewState) -> dict[str, Any]:
    """연결된 프로젝트 요약 + 초기 메모 + 누적 Q&A에서 5축 STAR-L 구조와 정량 지표를 추출한다."""
    llm = get_fast_llm(temperature=0.1)
    context_text = _build_context_text(state)

    messages = build_chat_prompt(
        "interview_extract",
        "아래 내용을 바탕으로 5축 STAR-L 구조를 추출해 주세요.\n\n{context_text}",
        human_vars={"context_text": context_text},
    )
    extracted = await ainvoke_structured(
        llm,
        StarExtractionSchema,
        messages,
        max_retries=1,
        caller="interview:extract_star",
    )
    return {"star": extracted.model_dump()}


async def grade_gaps(state: InterviewState) -> dict[str, Any]:
    """21개 Atomic 체크포인트 3단계 하이브리드 평가를 수행하고, 직전 역질문의 ΔSTAR-L과 해금 수를 DB에 기록한다."""
    star = state.get("star") or {}
    context_text = _build_context_text(state)
    result = await evaluate_star_experience_rubric(
        star,
        context_text=context_text,
        project_types=state.get("project_types"),
    )

    new_score = int(result["completeness_score"])
    new_cps = (result.get("star_scores") or {}).get("checkpoints") or {}
    prev_score = state.get("prev_completeness_score")
    prev_cps = state.get("prev_checkpoints") or {}
    prev_qs = state.get("prev_structured_questions") or []

    unlocked_count = 0
    if prev_cps and isinstance(new_cps, dict):
        for cid, item in new_cps.items():
            if isinstance(item, dict) and int(item.get("status", 0)) > int(prev_cps.get(cid, 0)):
                unlocked_count += 1

    if prev_score is not None and prev_qs:
        delta = new_score - int(prev_score)
        try:
            async with get_session_factory()() as session:
                for q_item in prev_qs:
                    log_id = q_item.get("feedback_log_id")
                    existing = (
                        await session.get(QuestionFeedbackLog, int(log_id))
                        if log_id
                        else None
                    )
                    if existing is not None:
                        existing.score_before = int(prev_score)
                        existing.score_after = new_score
                        existing.delta_score = delta
                        existing.unlocked_checkpoints = unlocked_count
                    else:
                        cp_id = str(q_item.get("target_checkpoint_id") or "").strip()
                        session.add(
                            QuestionFeedbackLog(
                                source_flow="interview",
                                thread_id=str(state.get("thread_id") or "")[:120],
                                project_id=state.get("project_id"),
                                technique=str(q_item.get("technique") or "micro_behavioral")[:50],
                                target_axis=str(q_item.get("target_axis") or "action")[:30],
                                target_checkpoints=[cp_id] if cp_id else [],
                                question_text=str(q_item.get("question") or ""),
                                score_before=int(prev_score),
                                score_after=new_score,
                                delta_score=delta,
                                unlocked_checkpoints=unlocked_count,
                                critic_score=int(state.get("question_critic_score") or 0),
                                critic_revisions=int(state.get("question_critic_revisions") or 0),
                            )
                        )
                await session.commit()
        except Exception as exc:
            logger.debug("Skipping ΔSTAR-L feedback log write: %s", exc)

    initial_score = state.get("initial_score")
    if initial_score is None:
        initial_score = new_score

    return {
        "completeness_score": new_score,
        "initial_score": initial_score,
        "star_scores": result["star_scores"],
        "is_sufficient": result["is_sufficient"],
        "missing_points": result["missing_points"],
        "last_unlocked_checkpoints": unlocked_count,
    }


def route_after_grade(state: InterviewState) -> str:
    if state.get("force_save"):
        return "save_experience"
    if state.get("completeness_score", 0) >= 80 and state.get("is_sufficient"):
        return "save_experience"
    return "generate_questions"


async def generate_questions(state: InterviewState) -> dict[str, Any]:
    """21지표 중 0점 고배점 체크포인트 TOP 2를 정조준하고 보수적 루프 A(<70 또는 린트 결함)로 검수한 역질문 2개를 생성한다."""
    llm = get_fast_llm(temperature=0.3, max_tokens=1500)
    star = state.get("star") or {}
    star_scores = state.get("star_scores") or {}
    axes = star_scores.get("axes") or {}
    priority_targets = list(star_scores.get("priority_targets") or [])
    missing_points = state.get("missing_points") or []
    qa_history = state.get("qa_history") or []
    turn_idx = len(qa_history)

    sorted_axes = sorted(
        STAR_AXIS_ORDER,
        key=lambda ax: int((axes.get(ax) or {}).get("score") or 0),
    )
    weakest_summary = "\n".join(
        f"- {ax}: {(axes.get(ax) or {}).get('earned', 0)}/{(axes.get(ax) or {}).get('max_points', 20)}점 "
        f"({(axes.get(ax) or {}).get('score', 0)}%) — {(axes.get(ax) or {}).get('tip', '')}"
        for ax in sorted_axes
    )
    targets_summary = "\n".join(
        f"- [{t['id']} | {t['axis']} | 배점 {t['weight']}점 | 현재상태={t['status']}/2 | 추천기법={t['technique']}] "
        f"{t['label']} — {t.get('tip', '')}"
        for t in priority_targets[:4]
    ) or "(우선 타겟 미지정 — 가장 점수가 낮은 2개 축 공략)"

    depth_guide = (
        "1단계(Directed Probe): 프로젝트 요약에 이미 적힌 배경은 건너뛰고, 0점 고배점 체크포인트(특히 개인 주도성 A3·구체 실행 A1·정량 수치 R1)부터 핵심 사실을 끌어내세요."
        if turn_idx == 0
        else "2단계 이상(Micro-Behavioral & Counter-Factual Drill-Down): 직전 답변에서 아직 미충족(0~1점)인 체크포인트의 대안 비교·트레이드오프(A2), 전후 비교 수치(R2), 장애물 돌파(A4), 재발 방지 원칙(L2/L3)을 정밀 검증하세요."
    )
    prev_qs = [
        q for turn in qa_history for q in (turn.get("questions") or [])
    ]
    project_ctx = str(state.get("project_context") or "").strip()

    messages = build_chat_prompt(
        "interview_probe",
        (
            "[연결된 프로젝트 요약 (이미 알려진 사실 — 다시 묻지 말 것)]\n{project_context}\n\n"
            "[현재 STAR-L 요약]\n{star}\n\n"
            "[우선 공략할 미충족 체크포인트 (배점 높은 순)]\n{targets_summary}\n\n"
            "[현재 5축 점수 (낮은 순)]\n{weakest_summary}\n\n"
            "[탐지된 빈틈]\n{missing_points}\n\n"
            "[이미 물어본 질문 (반복 금지)]\n{prev_qs}"
        ),
        system_vars={
            "depth_guide": depth_guide,
            "user_feedback_rules": state.get("user_feedback_rules") or "(기본 규칙 준수)",
        },
        human_vars={
            "project_context": project_ctx[:1800] if project_ctx else "(연결된 프로젝트 없음)",
            "star": str(star),
            "targets_summary": targets_summary,
            "weakest_summary": weakest_summary,
            "missing_points": str(missing_points),
            "prev_qs": str(prev_qs or "(없음)"),
        },
    )
    followup = await ainvoke_structured(
        llm,
        FollowupQuestionsSchema,
        messages,
        max_retries=2,
        caller="interview:generate_questions",
    )

    structured: list[dict[str, Any]] = []
    for idx, item in enumerate((followup.questions or [])[:2]):
        q_text = item.question.strip()
        if not q_text:
            continue
        tech_key = (
            item.technique
            if item.technique in PROBING_TECHNIQUES
            else "micro_behavioral"
        )
        tech_meta = PROBING_TECHNIQUES[tech_key]
        cp_id = item.target_checkpoint_id.strip().upper()
        if cp_id not in STAR_CHECKPOINTS_BY_ID:
            cp_id = priority_targets[idx]["id"] if idx < len(priority_targets) else ""
        cp_meta = STAR_CHECKPOINTS_BY_ID.get(cp_id) or {}
        axis = cp_meta.get("axis") or item.target_axis or (sorted_axes[0] if sorted_axes else "action")
        structured.append(
            {
                "technique": tech_key,
                "technique_label": tech_meta["label"],
                "target_axis": axis,
                "target_checkpoint_id": cp_id,
                "target_checkpoint_label": cp_meta.get("label", ""),
                "target_checkpoint_weight": int(cp_meta.get("weight", 0)),
                "question": q_text,
                "interviewer_intent": item.interviewer_intent.strip() or tech_meta["purpose"],
            }
        )

    if not structured:
        top_t = priority_targets[0] if priority_targets else {}
        fallback_cp_id = top_t.get("id", "A3")
        fallback_cp = STAR_CHECKPOINTS_BY_ID.get(fallback_cp_id, {})
        fallback_q = "이 경험에서 팀이 아니라 본인이 직접 내린 핵심 의사결정과, 적용 전/후로 확인된 구체적 수치 변화를 알려주시겠어요?"
        structured = [
            {
                "technique": "ownership_drilldown",
                "technique_label": PROBING_TECHNIQUES["ownership_drilldown"]["label"],
                "target_axis": fallback_cp.get("axis", sorted_axes[0] if sorted_axes else "action"),
                "target_checkpoint_id": fallback_cp_id,
                "target_checkpoint_label": fallback_cp.get("label", "본인 주도성"),
                "target_checkpoint_weight": int(fallback_cp.get("weight", 6)),
                "question": fallback_q,
                "interviewer_intent": PROBING_TECHNIQUES["ownership_drilldown"]["purpose"],
            }
        ]

    critic_score = 100
    critic_revisions = 0
    if state.get("enable_question_critic", True):
        critic_out = await critique_and_refine_questions(
            structured,
            context_text=_build_context_text(state),
            weakest_axes=sorted_axes[:2],
            prev_questions=prev_qs,
            max_revisions=MAX_QUESTION_REVISIONS,
            pass_threshold=PASS_SCORE_THRESHOLD,
            flow_name="interview",
        )
        refined_qs = critic_out.get("questions") or structured
        normalized_refined: list[dict[str, Any]] = []
        for idx, item in enumerate(refined_qs[:2]):
            base = structured[idx] if idx < len(structured) else {}
            tech_key = (
                item.get("technique")
                if item.get("technique") in PROBING_TECHNIQUES
                else base.get("technique", "micro_behavioral")
            )
            tech_meta = PROBING_TECHNIQUES[tech_key]
            cp_id = str(item.get("target_checkpoint_id") or base.get("target_checkpoint_id") or "").upper()
            cp_meta = STAR_CHECKPOINTS_BY_ID.get(cp_id) or {}
            normalized_refined.append(
                {
                    "technique": tech_key,
                    "technique_label": tech_meta["label"],
                    "target_axis": str(item.get("target_axis") or cp_meta.get("axis") or sorted_axes[0]),
                    "target_checkpoint_id": cp_id,
                    "target_checkpoint_label": cp_meta.get("label") or base.get("target_checkpoint_label", ""),
                    "target_checkpoint_weight": int(cp_meta.get("weight") or base.get("target_checkpoint_weight", 0)),
                    "question": str(item.get("question") or "").strip(),
                    "interviewer_intent": str(item.get("interviewer_intent") or "").strip()
                    or tech_meta["purpose"],
                }
            )
        if normalized_refined:
            structured = normalized_refined
        critic_score = int(critic_out.get("critic_score") or 0)
        critic_revisions = int(critic_out.get("revisions") or 0)

    # 질문 생성 시점에 QuestionFeedbackLog 레코드를 선행 생성해 UI 👍/👎 투표와 다음 턴 ΔSTAR-L을 1:1 연결
    cur_score = int(state.get("completeness_score") or 0)
    try:
        async with get_session_factory()() as session:
            created_logs: list[QuestionFeedbackLog] = []
            for q_item in structured:
                cp_id = str(q_item.get("target_checkpoint_id") or "").strip()
                log_row = QuestionFeedbackLog(
                    source_flow="interview",
                    thread_id=str(state.get("thread_id") or "")[:120],
                    project_id=state.get("project_id"),
                    technique=str(q_item.get("technique") or "micro_behavioral")[:50],
                    target_axis=str(q_item.get("target_axis") or "action")[:30],
                    target_checkpoints=[cp_id] if cp_id else [],
                    question_text=str(q_item.get("question") or ""),
                    score_before=cur_score,
                    score_after=cur_score,
                    delta_score=0,
                    unlocked_checkpoints=0,
                    critic_score=critic_score,
                    critic_revisions=critic_revisions,
                )
                session.add(log_row)
                created_logs.append(log_row)
            await session.commit()
            for q_item, log_row in zip(structured, created_logs):
                await session.refresh(log_row)
                q_item["feedback_log_id"] = log_row.id
    except Exception as exc:
        logger.debug("Skipping pre-creating QuestionFeedbackLog rows: %s", exc)

    return {
        "questions": [s["question"] for s in structured],
        "structured_questions": structured,
        "question_critic_score": critic_score,
        "question_critic_revisions": critic_revisions,
    }


async def save_experience(state: InterviewState) -> dict[str, Any]:
    """구조화된 STAR-L 경험(rubric_version + 21지표 스냅샷)을 experiences 테이블과 pgvector에 저장한다."""
    star = state.get("star") or {}
    raw_notes = _build_context_text(state)
    completeness_score = int(state.get("completeness_score") or 0)
    project_id = state.get("project_id")

    async with get_session_factory()() as session:
        exp = Experience(
            project_id=project_id,
            title=str(star.get("title") or "제목 없는 경험")[:300],
            situation=str(star.get("situation") or ""),
            task=str(star.get("task") or ""),
            action=str(star.get("action") or ""),
            result=str(star.get("result") or ""),
            learning=str(star.get("learning") or ""),
            quantified_metrics=str(star.get("quantified_metrics") or ""),
            completeness_score=completeness_score,
            star_scores=dict(state.get("star_scores") or {}),
            raw_notes=raw_notes,
        )
        session.add(exp)
        await session.commit()
        await session.refresh(exp)

        vector_content = (
            f"[경험 제목] {exp.title}\n"
            f"[Situation] {exp.situation}\n"
            f"[Task] {exp.task}\n"
            f"[Action] {exp.action}\n"
            f"[Result] {exp.result}\n"
            f"[Learning] {exp.learning}\n"
            f"[정량 지표] {exp.quantified_metrics}"
        )
        vector_synced = await try_upsert_document(
            session,
            doc_type=DocType.EXPERIENCE,
            ref_id=f"exp-{exp.id}",
            content=vector_content,
            metadata={
                "experience_id": exp.id,
                "project_id": exp.project_id,
                "title": exp.title,
                "completeness_score": exp.completeness_score,
                "rubric_version": str((exp.star_scores or {}).get("rubric_version") or "v2.0"),
            },
        )

    return {
        "saved_experience_id": exp.id,
        "vector_synced": vector_synced,
        "questions": [],
    }


def build_interview_workflow() -> StateGraph:
    workflow = StateGraph(InterviewState)
    workflow.add_node("load_project_context", load_project_context)
    workflow.add_node("prepare_turn", prepare_turn)
    workflow.add_node("extract_star", extract_star)
    workflow.add_node("grade_gaps", grade_gaps)
    workflow.add_node("generate_questions", generate_questions)
    workflow.add_node("save_experience", save_experience)

    workflow.add_edge(START, "load_project_context")
    workflow.add_edge("load_project_context", "prepare_turn")
    workflow.add_conditional_edges(
        "prepare_turn",
        route_after_prepare,
        {
            "extract_star": "extract_star",
            "save_experience": "save_experience",
        },
    )
    workflow.add_edge("extract_star", "grade_gaps")
    workflow.add_conditional_edges(
        "grade_gaps",
        route_after_grade,
        {
            "generate_questions": "generate_questions",
            "save_experience": "save_experience",
        },
    )
    workflow.add_edge("generate_questions", END)
    workflow.add_edge("save_experience", END)
    return workflow


async def stream_interview_graph(
    *,
    thread_id: str,
    input_state: dict[str, Any],
):
    """AsyncPostgresSaver Checkpointer를 연결해 노드별 업데이트를 비동기 스트리밍한다."""
    conninfo = get_psycopg_conninfo()
    workflow = build_interview_workflow()
    payload = {**input_state, "thread_id": thread_id}

    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        checkpointer = AsyncPostgresSaver(aconn)
        graph = workflow.compile(checkpointer=checkpointer)
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 12,
        }

        async for chunk in graph.astream(payload, config=config, stream_mode="updates"):
            yield chunk

        snapshot = await graph.aget_state(config)
        yield {"__final_state__": dict(snapshot.values)}
