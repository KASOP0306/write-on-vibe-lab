"""워크플로우 ①: 대화형 멀티턴 경험 채굴 에이전트 (Conversational Active Interviewer v3.0).

핵심 아키텍처:
- 0. load_project_context: 연결된 프로젝트 요약·섹션·직무 트랙 + 동적 사용자 피드백 규칙 로드
- 1. classify_and_prepare: 멀티턴 의도 분류 (answer | replace_question | ask_coach | save) + 사용자 선호(제외 항목·집중 주제·질문 수) 영속화
- 2a. extract_star -> grade_gaps (answer 경로): focus_context(GitHub PR/커밋 Diff 등) + 누적 대화 통합 추출 & 21지표 v2.1 엄격 하이브리드 채점
- 2b. generate_questions (answer 미충족 OR replace_question 경로): focus_context(실제 PR/파일/Diff)에 직접 앵커링된 대화형 역질문 생성 + 보수적 루프 A(<70 또는 린트 결함)
- 2c. coach_reply (ask_coach 경로): 설문 강제 없이 사용자의 자유 요청·질문에 1:1 코치처럼 대화 응답
- 3. save_experience: experiences(rubric_version + 21지표 스냅샷) & pgvector(doc_type='experience') 영속 저장
"""

from collections import Counter
import logging
from typing import Any, Literal, TypedDict

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
    "too_abstract": "추상적·교과서적 질문 대신 원문/코드 Diff의 특정 파일·기능·행동을 직접 지목해 구체적으로 물어보세요.",
    "role_mismatch": "사용자의 직무 트랙(개발/기획/데이터/운영)에 맞지 않는 용어나 억지 지표 질문은 피하세요.",
    "too_complex": "질문은 반드시 핵심 1가지만 묻는 100자 이내 짧은 1문장으로 작성하세요.",
}


class TurnIntentSchema(BaseModel):
    intent: Literal["answer", "replace_question", "ask_coach", "save"] = Field(
        default="answer",
        description="사용자 발화 의도: answer | replace_question | ask_coach | save",
    )
    focus_instruction: str = Field(
        default="",
        description="사용자가 특정 PR/파일/주제/관점에 집중해 달라고 요청한 경우 요약",
    )
    add_excluded_checkpoints: list[str] = Field(
        default_factory=list,
        description="제외 요청된 21지표 체크포인트 ID 목록 (예: ['A6'])",
    )
    preferred_question_count: int = Field(
        default=0,
        ge=0,
        le=2,
        description="사용자가 질문 개수를 명시한 경우 1 또는 2 (미언급 시 0)",
    )
    reason: str = Field(default="", description="의도 판별 1줄 근거")


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
    code_anchor: str = Field(
        default="",
        description="집중 컨텍스트(GitHub PR/커밋/파일명/핵심 사실)에서 이 질문이 겨냥한 구체 앵커 (없으면 빈 문자열)",
    )
    question: str = Field(
        description="코드 변경점 또는 맥락을 직접 짚어 파고드는 짧고 날카로운 한국어 개방형 역질문 1문장 (115자 이내)"
    )
    interviewer_intent: str = Field(
        default="",
        description="면접관이 이 역질문으로 무엇을 검증하려는지 1줄 설명",
    )


class FollowupQuestionsSchema(BaseModel):
    assistant_message: str = Field(
        default="",
        description="사용자와 자연스럽게 대화를 이어가는 1~2문장 코치 응답 (직전 답변 반응 또는 질문 교체 안내)",
    )
    questions: list[StructuredProbeQuestion] = Field(
        default_factory=list,
        description="집중 컨텍스트(GitHub PR/Diff 등)에 직접 앵커링된 역질문 목록",
    )


class CoachReplySchema(BaseModel):
    reply: str = Field(
        description="사용자의 자유 질문·요청에 대한 명확하고 실용적인 한국어 코치 응답 (3~6문장)"
    )


class InterviewState(TypedDict, total=False):
    thread_id: str
    raw_notes: str
    focus_context: str  # GitHub PR/Commit Diff 또는 집중 에피소드 (턴 전체 영속)
    project_id: int | None
    project_name: str
    project_types: list[str]
    project_context: str
    user_feedback_rules: str
    interview_preferences: dict[str, Any]  # {focus_instruction, excluded_checkpoints, question_count}
    chat_messages: list[dict[str, Any]]  # 멀티턴 전체 대화 로그 (영속)
    qa_history: list[dict[str, Any]]  # 경험 사실 답변만 누적
    rejected_questions: list[str]  # 교체·거절된 질문 목록 (재출제 차단)
    latest_reply: str
    turn_action: str  # "auto" | "replace_question" | "save"
    replace_question_index: int | None
    turn_intent: str  # "answer" | "replace_question" | "ask_coach" | "save"
    assistant_message: str
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


def _is_github_diff_text(text: str) -> bool:
    t = text or ""
    return (
        "[GitHub" in t
        or "```diff" in t
        or "### GitHub 변경 이력" in t
        or "[PR #" in t
        or "[Commit `" in t
    )


def _build_context_text(state: InterviewState, max_recent_turns: int = 8) -> str:
    """집중 채굴 컨텍스트(GitHub PR/Diff) + 프로젝트 요약 + 초기 메모 + 누적 Q&A를 조합한다."""
    lines: list[str] = []
    focus_ctx = str(state.get("focus_context") or "").strip()
    raw_notes = str(state.get("raw_notes") or "").strip()
    project_ctx = str(state.get("project_context") or "").strip()

    if focus_ctx:
        lines.append(f"[집중 채굴 컨텍스트 (최우선 기준 — PR/커밋/코드 변경점)]\n{focus_ctx}")
    if project_ctx:
        lines.append(f"\n[연결된 프로젝트 배경 요약]\n{project_ctx}")
    if raw_notes and raw_notes != focus_ctx:
        lines.append(f"\n[초기 경험 메모]\n{raw_notes}")
    elif not focus_ctx and not raw_notes and project_ctx:
        lines.append("\n[초기 경험 메모]\n(프로젝트 요약 전체를 기반으로 핵심 경험을 채굴합니다.)")

    qa_history = state.get("qa_history") or []
    if qa_history:
        older = qa_history[:-max_recent_turns] if len(qa_history) > max_recent_turns else []
        recent = qa_history[-max_recent_turns:]
        if older:
            lines.append("\n[이전 턴 요약 (압축)]")
            for idx, turn in enumerate(older, start=1):
                ans = str(turn.get("answer", "")).strip()
                lines.append(f"- 턴 {idx} 핵심 답변: {ans[:200]}{'...' if len(ans) > 200 else ''}")
        lines.append("\n[최근 질의응답 누적]")
        offset = len(older)
        for idx, turn in enumerate(recent, start=offset + 1):
            qs = " / ".join(turn.get("questions") or [])
            ans = turn.get("answer", "")
            lines.append(f"턴 {idx} 질문: {qs}\n턴 {idx} 답변: {ans}")
    return "\n".join(lines).strip()


def _format_recent_chat(chat_messages: list[dict[str, Any]], limit: int = 8) -> str:
    recent = (chat_messages or [])[-limit:]
    if not recent:
        return "(대화 시작)"
    out: list[str] = []
    for msg in recent:
        role = "사용자" if msg.get("role") == "user" else "AI 인터뷰어"
        content = str(msg.get("content") or "").strip()
        qs = msg.get("questions") or []
        if content:
            out.append(f"{role}: {content[:320]}")
        if qs and role == "AI 인터뷰어":
            out.append("  [제시된 질문] " + " / ".join(str(q)[:120] for q in qs))
    return "\n".join(out)


def _format_preferences_guide(prefs: dict[str, Any] | None) -> str:
    p = prefs or {}
    parts: list[str] = []
    if p.get("focus_instruction"):
        parts.append(f"- 사용자 요청 초점: {p['focus_instruction']}")
    excluded = p.get("excluded_checkpoints") or []
    if excluded:
        parts.append(f"- 제외할 체크포인트(절대 묻지 말 것): {', '.join(excluded)}")
    q_cnt = int(p.get("question_count") or 0)
    if q_cnt in (1, 2):
        parts.append(f"- 선호 질문 개수: 턴당 {q_cnt}개")
    return "\n".join(parts) if parts else "(특별 지정 없음 — 집중 컨텍스트와 핵심 빈틈 기준으로 진행)"


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
    """연결된 프로젝트의 요약·섹션·직무 트랙과 focus_context(GitHub Diff 등), 동적 피드백 규칙을 로드한다."""
    updates: dict[str, Any] = {}
    project_id = state.get("project_id")

    # 최초 시작 시 raw_notes에 GitHub Diff가 들어왔다면 focus_context로 자동 승격·고정
    raw_notes = str(state.get("raw_notes") or "").strip()
    if not state.get("focus_context") and raw_notes and _is_github_diff_text(raw_notes):
        updates["focus_context"] = raw_notes

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
                        budget = 2000
                        used = 0
                        for sec in filled_sections:
                            snippet = sec.content.strip()[:420]
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
    """멀티턴 사용자 발화 의도를 분류하고(answer / replace_question / ask_coach / save), 대화 로그·선호를 갱신한다."""
    qa_history = list(state.get("qa_history") or [])
    chat_messages = list(state.get("chat_messages") or [])
    rejected_questions = list(state.get("rejected_questions") or [])
    prefs = dict(state.get("interview_preferences") or {})
    excluded_set = set(prefs.get("excluded_checkpoints") or [])

    latest_reply = (state.get("latest_reply") or "").strip()
    turn_action = str(state.get("turn_action") or "auto").strip().lower()
    replace_idx = state.get("replace_question_index")
    has_existing_star = bool((state.get("star") or {}).get("title"))

    # 최초 턴 시작 (star 없음, latest_reply 없음)
    if not latest_reply and not has_existing_star and not state.get("force_save"):
        opening_text = str(state.get("raw_notes") or "").strip()
        if not chat_messages:
            if _is_github_diff_text(opening_text):
                chat_messages.append(
                    {
                        "role": "user",
                        "content": "[GitHub PR·커밋 실제 코드 Diff 컨텍스트로 경험 채굴 시작]",
                        "kind": "github_diff_start",
                    }
                )
            elif opening_text:
                chat_messages.append({"role": "user", "content": opening_text, "kind": "start"})
            else:
                chat_messages.append(
                    {
                        "role": "user",
                        "content": f"[프로젝트 '{state.get('project_name') or ''}' 요약 기반으로 경험 채굴 시작]",
                        "kind": "project_start",
                    }
                )
        return {
            "qa_history": qa_history,
            "chat_messages": chat_messages,
            "latest_reply": "",
            "turn_action": "auto",
            "replace_question_index": None,
            "turn_intent": "answer",
            "skip_extraction": False,
            "prev_completeness_score": None,
            "prev_checkpoints": {},
            "prev_structured_questions": [],
        }

    # 명시적 저장 요청 (버튼 클릭)
    if state.get("force_save") and has_existing_star and not latest_reply:
        return {
            "qa_history": qa_history,
            "chat_messages": chat_messages,
            "latest_reply": "",
            "turn_action": "auto",
            "replace_question_index": None,
            "turn_intent": "save",
            "skip_extraction": True,
        }

    # 명시적 질문 교체 버튼 클릭 (🔄 다른 질문)
    if turn_action == "replace_question" and has_existing_star:
        current_qs = list(state.get("questions") or [])
        if replace_idx is not None and 0 <= int(replace_idx) < len(current_qs):
            target_q = current_qs[int(replace_idx)]
            if target_q and target_q not in rejected_questions:
                rejected_questions.append(target_q)
            user_note = latest_reply or f"Q{int(replace_idx) + 1} 질문이 마음에 안 들어서 다른 각도의 질문으로 바꿔주세요."
        else:
            for q in current_qs:
                if q and q not in rejected_questions:
                    rejected_questions.append(q)
            user_note = latest_reply or "현재 질문 말고 다른 각도의 질문으로 바꿔주세요."

        chat_messages.append({"role": "user", "content": user_note, "kind": "replace_question"})
        if latest_reply:
            prefs["focus_instruction"] = latest_reply[:200]

        return {
            "qa_history": qa_history,
            "chat_messages": chat_messages,
            "rejected_questions": rejected_questions,
            "interview_preferences": prefs,
            "latest_reply": "",
            "turn_action": "replace_question",
            "replace_question_index": replace_idx,
            "turn_intent": "replace_question",
            "skip_extraction": False,
            "prev_completeness_score": None,
            "prev_checkpoints": {},
            "prev_structured_questions": [],
        }

    # 일반 채팅 메시지 입력 → Intent Router로 의도 판별
    if latest_reply:
        chat_messages.append({"role": "user", "content": latest_reply, "kind": "chat"})

    intent: str = "answer"
    if latest_reply and has_existing_star and not state.get("force_save"):
        try:
            llm = get_fast_llm(temperature=0.0, max_tokens=500)
            intent_msgs = build_chat_prompt(
                "interview_intent",
                (
                    "[직전에 AI가 제시한 역질문]\n{prev_questions}\n\n"
                    "[사용자의 최신 메시지]\n{user_message}"
                ),
                human_vars={
                    "prev_questions": "\n".join(state.get("questions") or []) or "(없음)",
                    "user_message": latest_reply,
                },
            )
            classified = await ainvoke_structured(
                llm,
                TurnIntentSchema,
                intent_msgs,
                max_retries=1,
                caller="interview:classify_intent",
            )
            intent = classified.intent
            if classified.focus_instruction.strip():
                prefs["focus_instruction"] = classified.focus_instruction.strip()[:240]
            for cid in classified.add_excluded_checkpoints or []:
                up = str(cid).strip().upper()
                if up in STAR_CHECKPOINTS_BY_ID:
                    excluded_set.add(up)
            if excluded_set:
                prefs["excluded_checkpoints"] = sorted(excluded_set)
            if classified.preferred_question_count in (1, 2):
                prefs["question_count"] = int(classified.preferred_question_count)
        except Exception as exc:
            logger.debug("Intent classification fallback to 'answer': %s", exc)
            intent = "answer"

    if intent == "save" and has_existing_star:
        return {
            "qa_history": qa_history,
            "chat_messages": chat_messages,
            "interview_preferences": prefs,
            "latest_reply": "",
            "turn_action": "auto",
            "replace_question_index": None,
            "turn_intent": "save",
            "force_save": True,
            "skip_extraction": True,
        }

    if intent == "replace_question" and has_existing_star:
        for q in state.get("questions") or []:
            if q and q not in rejected_questions:
                rejected_questions.append(q)
        return {
            "qa_history": qa_history,
            "chat_messages": chat_messages,
            "rejected_questions": rejected_questions,
            "interview_preferences": prefs,
            "latest_reply": "",
            "turn_action": "replace_question",
            "replace_question_index": None,
            "turn_intent": "replace_question",
            "skip_extraction": False,
            "prev_completeness_score": None,
            "prev_checkpoints": {},
            "prev_structured_questions": [],
        }

    if intent == "ask_coach" and has_existing_star:
        return {
            "qa_history": qa_history,
            "chat_messages": chat_messages,
            "interview_preferences": prefs,
            "latest_reply": latest_reply,  # coach_reply가 참조할 수 있도록 전달
            "turn_action": "auto",
            "replace_question_index": None,
            "turn_intent": "ask_coach",
            "skip_extraction": False,
            "prev_completeness_score": None,
            "prev_checkpoints": {},
            "prev_structured_questions": [],
        }

    # 기본 경로: intent == "answer" (경험 사실 답변으로 병합)
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

    return {
        "qa_history": qa_history,
        "chat_messages": chat_messages,
        "interview_preferences": prefs,
        "latest_reply": "",
        "turn_action": "auto",
        "replace_question_index": None,
        "turn_intent": "answer",
        "skip_extraction": False,
        "prev_completeness_score": prev_score,
        "prev_checkpoints": prev_checkpoints,
        "prev_structured_questions": prev_qs,
    }


def route_after_prepare(state: InterviewState) -> str:
    if state.get("skip_extraction") or state.get("turn_intent") == "save":
        return "save_experience"
    if state.get("turn_intent") == "replace_question":
        return "generate_questions"
    if state.get("turn_intent") == "ask_coach":
        return "coach_reply"
    return "extract_star"


async def coach_reply(state: InterviewState) -> dict[str, Any]:
    """사용자의 자유 질문·조언·설명 요청에 설문 강제 없이 1:1 코치처럼 대화 응답한다."""
    llm = get_fast_llm(temperature=0.35, max_tokens=1200)
    user_msg = str(state.get("latest_reply") or "").strip()
    chat_messages = list(state.get("chat_messages") or [])
    star = state.get("star") or {}
    star_scores = state.get("star_scores") or {}
    priority_targets = list(star_scores.get("priority_targets") or [])
    focus_ctx = str(state.get("focus_context") or "").strip()
    project_ctx = str(state.get("project_context") or "").strip()

    targets_text = "\n".join(
        f"- [{t['id']} {t['label']} · {t['weight']}점, 상태 {t['status']}/2] {t.get('tip', '')}"
        for t in priority_targets[:5]
    ) or "(없음)"

    messages = build_chat_prompt(
        "interview_coach",
        (
            "[집중 채굴 컨텍스트 (GitHub PR/Diff 등)]\n{focus_context}\n\n"
            "[연결된 프로젝트 요약]\n{project_context}\n\n"
            "[현재 STAR-L 정리본 (현재 점수: {score}점)]\n{star}\n\n"
            "[현재 부족한 핵심 체크포인트 TOP 5]\n{targets_text}\n\n"
            "[최근 대화 흐름]\n{recent_chat}\n\n"
            "[사용자의 최신 질문/요청]\n{user_msg}"
        ),
        human_vars={
            "focus_context": focus_ctx[:2600] if focus_ctx else "(없음)",
            "project_context": project_ctx[:1400] if project_ctx else "(없음)",
            "score": str(state.get("completeness_score") or 0),
            "star": str(star),
            "targets_text": targets_text,
            "recent_chat": _format_recent_chat(chat_messages, limit=6),
            "user_msg": user_msg,
        },
    )
    res = await ainvoke_structured(
        llm,
        CoachReplySchema,
        messages,
        max_retries=1,
        caller="interview:coach_reply",
    )
    reply_text = res.reply.strip()
    chat_messages.append(
        {
            "role": "assistant",
            "content": reply_text,
            "kind": "coach_reply",
            "questions": [],
            "structured_questions": [],
        }
    )
    return {
        "latest_reply": "",
        "assistant_message": reply_text,
        "chat_messages": chat_messages,
    }


async def extract_star(state: InterviewState) -> dict[str, Any]:
    """집중 컨텍스트(GitHub PR/Diff 등) + 프로젝트 요약 + 누적 Q&A에서 5축 STAR-L 구조를 추출한다."""
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
    """21개 Atomic 체크포인트 3단계 엄격 하이브리드 평가를 수행하고, 직전 역질문의 ΔSTAR-L과 해금 수를 DB에 기록한다."""
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
    """focus_context(GitHub PR/Diff 등)에 직접 앵커링된 대화형 역질문을 생성하고 보수적 루프 A로 검수한다."""
    llm = get_fast_llm(temperature=0.35, max_tokens=1600)
    star = state.get("star") or {}
    star_scores = state.get("star_scores") or {}
    axes = star_scores.get("axes") or {}
    prefs = dict(state.get("interview_preferences") or {})
    excluded_cps = set(prefs.get("excluded_checkpoints") or [])
    is_replace_mode = state.get("turn_intent") == "replace_question"
    replace_idx = state.get("replace_question_index")

    raw_targets = list(star_scores.get("priority_targets") or [])
    priority_targets = [t for t in raw_targets if t.get("id") not in excluded_cps]
    if not priority_targets:
        priority_targets = raw_targets

    missing_points = state.get("missing_points") or []
    qa_history = state.get("qa_history") or []
    chat_messages = list(state.get("chat_messages") or [])
    rejected_qs = list(state.get("rejected_questions") or [])
    turn_idx = len(qa_history)

    # 요청된 질문 개수 결정 (단일 질문 교체 모드면 1개, 사용자 선호가 1이면 1개, 기본 2개)
    if is_replace_mode and replace_idx is not None:
        question_count = 1
    elif int(prefs.get("question_count") or 0) == 1:
        question_count = 1
    else:
        question_count = 2

    sorted_axes = sorted(
        STAR_AXIS_ORDER,
        key=lambda ax: int((axes.get(ax) or {}).get("score") or 0),
    )
    weakest_summary = "\n".join(
        f"- {ax}: {(axes.get(ax) or {}).get('earned', 0)}/{(axes.get(ax) or {}).get('max_points', 20)}점 "
        f"({(axes.get(ax) or {}).get('score', 0)}%)"
        for ax in sorted_axes
    )
    targets_summary = "\n".join(
        f"- [{t['id']} | {t['axis']} | 배점 {t['weight']}점 | 상태={t['status']}/2 | 추천기법={t['technique']}] "
        f"{t['label']} — {t.get('tip', '')}"
        for t in priority_targets[:5]
    ) or "(우선 타겟 미지정)"

    focus_ctx = str(state.get("focus_context") or "").strip()
    project_ctx = str(state.get("project_context") or "").strip()

    if is_replace_mode:
        depth_guide = (
            "질문 교체 모드: 사용자가 직전 질문을 거절하거나 방향 전환을 요청했습니다. "
            "거절된 질문과 완전히 다른 각도·체크포인트·파일/사례를 짚어 더 구체적이고 답하기 쉬운 새 질문을 제시하세요."
        )
    elif focus_ctx:
        depth_guide = (
            "코드/PR 변경점 집중 프로빙 모드: 반드시 [집중 채굴 컨텍스트]의 실제 PR/커밋/파일명/Diff 변경 사항을 직접 인용하며, "
            "코드에 드러나지 않은 의사결정 이유·포기한 대안(A2)·장애물(A4)·전후 수치(R1/R2)·배운 원칙(L)을 끌어내세요."
        )
    elif turn_idx == 0:
        depth_guide = (
            "1단계(Directed Probe): 프로젝트 요약에 이미 적힌 배경은 건너뛰고, 0점 고배점 체크포인트부터 핵심 사실을 끌어내세요."
        )
    else:
        depth_guide = (
            "2단계 이상(Micro-Behavioral & Counter-Factual Drill-Down): 직전 답변에서 이어지는 맥락으로 "
            "대안 비교·트레이드오프(A2), 전후 수치(R1/R2), 장애물 돌파(A4), 재발 방지 원칙(L2/L3)을 자연스럽게 파고드세요."
        )

    prev_qs = list(
        dict.fromkeys(
            [q for turn in qa_history for q in (turn.get("questions") or [])]
            + rejected_qs
        )
    )

    messages = build_chat_prompt(
        "interview_probe",
        (
            "[집중 채굴 컨텍스트 (GitHub PR·커밋 Diff 또는 핵심 에피소드 — 최우선 질문 근거!)]\n{focus_context}\n\n"
            "[연결된 프로젝트 배경 요약 (이미 알려진 사실 — 다시 묻지 말 것)]\n{project_context}\n\n"
            "[최근 멀티턴 대화 흐름]\n{recent_chat}\n\n"
            "[현재 STAR-L 요약]\n{star}\n\n"
            "[우선 공략할 미충족 체크포인트 (제외 항목 필터링 완료)]\n{targets_summary}\n\n"
            "[현재 5축 점수 (낮은 순)]\n{weakest_summary}\n\n"
            "[이미 물어본 질문 & 거절된 질문 (절대 반복 금지)]\n{prev_qs}"
        ),
        system_vars={
            "depth_guide": depth_guide,
            "preferences_guide": _format_preferences_guide(prefs),
            "user_feedback_rules": state.get("user_feedback_rules") or "(기본 규칙 준수)",
            "question_count": str(question_count),
        },
        human_vars={
            "focus_context": focus_ctx[:3200] if focus_ctx else "(별도 PR/Diff 없음 — 초기 메모와 STAR 요약 기준으로 질문)",
            "project_context": project_ctx[:1400] if project_ctx else "(연결된 프로젝트 없음)",
            "recent_chat": _format_recent_chat(chat_messages, limit=6),
            "star": str(star),
            "targets_summary": targets_summary,
            "weakest_summary": weakest_summary,
            "prev_qs": "\n".join(f"- {q}" for q in prev_qs) if prev_qs else "(없음)",
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
    for idx, item in enumerate((followup.questions or [])[:question_count]):
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
        if cp_id not in STAR_CHECKPOINTS_BY_ID or cp_id in excluded_cps:
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
                "code_anchor": item.code_anchor.strip()[:80],
                "question": q_text,
                "interviewer_intent": item.interviewer_intent.strip() or tech_meta["purpose"],
            }
        )

    if not structured:
        top_t = priority_targets[0] if priority_targets else {}
        fallback_cp_id = top_t.get("id", "A2")
        fallback_cp = STAR_CHECKPOINTS_BY_ID.get(fallback_cp_id, {})
        fallback_q = "이 변경을 진행할 때 고민했던 다른 대안과, 적용 전후로 확인된 구체적 변화(수치 또는 동작 차이)를 알려주시겠어요?"
        structured = [
            {
                "technique": "counter_factual",
                "technique_label": PROBING_TECHNIQUES["counter_factual"]["label"],
                "target_axis": fallback_cp.get("axis", sorted_axes[0] if sorted_axes else "action"),
                "target_checkpoint_id": fallback_cp_id,
                "target_checkpoint_label": fallback_cp.get("label", "대안 비교"),
                "target_checkpoint_weight": int(fallback_cp.get("weight", 6)),
                "code_anchor": "",
                "question": fallback_q,
                "interviewer_intent": PROBING_TECHNIQUES["counter_factual"]["purpose"],
            }
        ]

    critic_score = 100
    critic_revisions = 0
    if state.get("enable_question_critic", True):
        critic_out = await critique_and_refine_questions(
            structured,
            context_text=_build_context_text(state),
            weakest_axes=sorted_axes[:2] if not focus_ctx else None,
            prev_questions=prev_qs,
            max_revisions=MAX_QUESTION_REVISIONS,
            pass_threshold=PASS_SCORE_THRESHOLD,
            flow_name="interview",
        )
        refined_qs = critic_out.get("questions") or structured
        normalized_refined: list[dict[str, Any]] = []
        for idx, item in enumerate(refined_qs[:question_count]):
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
                    "code_anchor": base.get("code_anchor", ""),
                    "question": str(item.get("question") or "").strip(),
                    "interviewer_intent": str(item.get("interviewer_intent") or "").strip()
                    or tech_meta["purpose"],
                }
            )
        if normalized_refined:
            structured = normalized_refined
        critic_score = int(critic_out.get("critic_score") or 0)
        critic_revisions = int(critic_out.get("revisions") or 0)

    # 단일 질문 교체(replace_idx)일 경우 나머지 기존 질문은 유지하고 해당 슬롯만 교체
    if is_replace_mode and replace_idx is not None and structured:
        existing_sq = list(state.get("structured_questions") or [])
        idx_int = int(replace_idx)
        if 0 <= idx_int < len(existing_sq):
            existing_sq[idx_int] = structured[0]
            structured = existing_sq

    # 질문 생성 시점에 QuestionFeedbackLog 레코드를 선행 생성
    cur_score = int(state.get("completeness_score") or 0)
    try:
        async with get_session_factory()() as session:
            created_logs: list[tuple[dict[str, Any], QuestionFeedbackLog]] = []
            for q_item in structured:
                if q_item.get("feedback_log_id"):
                    continue
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
                created_logs.append((q_item, log_row))
            if created_logs:
                await session.commit()
                for q_item, log_row in created_logs:
                    await session.refresh(log_row)
                    q_item["feedback_log_id"] = log_row.id
    except Exception as exc:
        logger.debug("Skipping pre-creating QuestionFeedbackLog rows: %s", exc)

    assistant_msg = (followup.assistant_message or "").strip()
    if not assistant_msg:
        if is_replace_mode:
            assistant_msg = "요청하신 방향에 맞춰 다른 각도의 질문으로 바꿨습니다. 편하게 답하시거나 원하시는 초점을 말씀해 주세요!"
        elif focus_ctx and turn_idx == 0:
            assistant_msg = "불러온 GitHub PR·커밋 코드 변경점을 확인했습니다! 코드에 드러나지 않은 의사결정과 검증 근거를 몇 가지만 여쭤볼게요."
        elif state.get("last_unlocked_checkpoints", 0) > 0:
            assistant_msg = f"방금 답변으로 체크포인트 {state['last_unlocked_checkpoints']}개가 보강되었습니다! 이어서 아래 핵심 포인트를 조금만 더 짚어볼게요."
        else:
            assistant_msg = "현재 내용을 정리했습니다. 아래 포인트가 채워지면 면접에서도 바로 방어할 수 있는 강한 경험이 됩니다."

    chat_messages.append(
        {
            "role": "assistant",
            "content": assistant_msg,
            "kind": "probe",
            "questions": [s["question"] for s in structured],
            "structured_questions": structured,
        }
    )

    return {
        "assistant_message": assistant_msg,
        "chat_messages": chat_messages,
        "questions": [s["question"] for s in structured],
        "structured_questions": structured,
        "question_critic_score": critic_score,
        "question_critic_revisions": critic_revisions,
        "turn_action": "auto",
        "replace_question_index": None,
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
                "rubric_version": str((exp.star_scores or {}).get("rubric_version") or "v2.1"),
            },
        )

    chat_messages = list(state.get("chat_messages") or [])
    chat_messages.append(
        {
            "role": "assistant",
            "content": f"경험 #{exp.id} '{exp.title}'({completeness_score}점)을 저장했습니다! 필요하면 상세 보기에서 수정하거나 프로젝트 섹션에 다시 정리할 수 있습니다.",
            "kind": "saved",
            "questions": [],
            "structured_questions": [],
        }
    )

    return {
        "saved_experience_id": exp.id,
        "vector_synced": vector_synced,
        "chat_messages": chat_messages,
        "questions": [],
    }


def build_interview_workflow() -> StateGraph:
    workflow = StateGraph(InterviewState)
    workflow.add_node("load_project_context", load_project_context)
    workflow.add_node("prepare_turn", prepare_turn)
    workflow.add_node("extract_star", extract_star)
    workflow.add_node("grade_gaps", grade_gaps)
    workflow.add_node("generate_questions", generate_questions)
    workflow.add_node("coach_reply", coach_reply)
    workflow.add_node("save_experience", save_experience)

    workflow.add_edge(START, "load_project_context")
    workflow.add_edge("load_project_context", "prepare_turn")
    workflow.add_conditional_edges(
        "prepare_turn",
        route_after_prepare,
        {
            "extract_star": "extract_star",
            "generate_questions": "generate_questions",
            "coach_reply": "coach_reply",
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
    workflow.add_edge("coach_reply", END)
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


async def get_interview_thread_state(thread_id: str) -> dict[str, Any] | None:
    """AsyncPostgresSaver에 영속 저장된 멀티턴 인터뷰 컨텍스트 및 대화 로그를 복원한다."""
    conninfo = get_psycopg_conninfo()
    workflow = build_interview_workflow()
    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        checkpointer = AsyncPostgresSaver(aconn)
        graph = workflow.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        if not snapshot or not snapshot.values:
            return None
        vals = dict(snapshot.values)
        return {
            "thread_id": thread_id,
            "project_id": vals.get("project_id"),
            "project_name": vals.get("project_name", ""),
            "has_focus_context": bool((vals.get("focus_context") or "").strip()),
            "focus_context_preview": str(vals.get("focus_context") or "")[:360],
            "interview_preferences": vals.get("interview_preferences") or {},
            "chat_messages": vals.get("chat_messages") or [],
            "star": vals.get("star") or {},
            "completeness_score": vals.get("completeness_score", 0),
            "initial_score": vals.get("initial_score", 0),
            "star_scores": vals.get("star_scores") or {},
            "missing_points": vals.get("missing_points") or [],
            "questions": vals.get("questions") or [],
            "structured_questions": vals.get("structured_questions") or [],
            "saved_experience_id": vals.get("saved_experience_id"),
            "turn_count": len(vals.get("qa_history") or []),
        }
