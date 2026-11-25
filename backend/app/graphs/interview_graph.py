"""워크플로우 ①: 경험 채굴 & 연속 역질문 루프 (Active Interviewer, agents_md.md 5.1)."""

import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_fast_llm
from app.core.database import Experience, get_psycopg_conninfo, get_session_factory
from app.core.star_rubric import evaluate_star_experience_rubric
from app.core.vector_store import DocType, try_upsert_document

logger = logging.getLogger(__name__)


class StarExtractionSchema(BaseModel):
    title: str = Field(description="경험을 한눈에 요약하는 구체적 제목 (30자 내외)")
    situation: str = Field(description="배경 및 문제 상황 (Situation)")
    task: str = Field(description="본인이 맡은 과제 및 목표 (Task)")
    action: str = Field(description="본인이 직접 수행한 구체적 행동·기술적 의사결정 (Action)")
    result: str = Field(description="결과 및 변화 (Result)")
    quantified_metrics: str = Field(
        default="",
        description="확인된 정량 지표/수치만 정리 (없으면 빈 문자열, 절대 추측/날조 금지)",
    )


class GapGradeSchema(BaseModel):
    completeness_score: int = Field(
        ge=0, le=100, description="STAR 구조, 기여도, 정량 근거 종합 완성도 점수 (0~100)"
    )
    is_sufficient: bool = Field(
        description="자소서·포트폴리오에 바로 활용할 수 있을 만큼 근거가 충분한지 여부"
    )
    missing_points: list[str] = Field(
        default_factory=list,
        description="부족한 구체 정보 항목 (예: 트러블슈팅 원인, 본인 기여 비율, 정량 지표)",
    )


class FollowupQuestionsSchema(BaseModel):
    questions: list[str] = Field(
        default_factory=list,
        description="빈틈을 채우기 위해 사용자에게 던질 날카롭고 구체적인 역질문 1~2개",
    )


class InterviewState(TypedDict, total=False):
    raw_notes: str
    project_id: int | None
    qa_history: list[dict[str, Any]]
    latest_reply: str
    skip_extraction: bool
    force_save: bool
    star: dict[str, str]
    completeness_score: int
    star_scores: dict[str, Any]
    is_sufficient: bool
    missing_points: list[str]
    questions: list[str]
    saved_experience_id: int | None
    vector_synced: bool


def _build_context_text(state: InterviewState) -> str:
    lines = [f"[초기 메모]\n{state.get('raw_notes', '')}"]
    qa_history = state.get("qa_history") or []
    if qa_history:
        lines.append("\n[추가 질의응답 누적]")
        for idx, turn in enumerate(qa_history, start=1):
            qs = " / ".join(turn.get("questions") or [])
            ans = turn.get("answer", "")
            lines.append(f"턴 {idx} 질문: {qs}\n턴 {idx} 답변: {ans}")
    return "\n".join(lines)


async def prepare_turn(state: InterviewState) -> dict[str, Any]:
    """사용자 추가 답변을 누적 이력에 병합하고, force_save 단축 경로 여부를 결정한다."""
    qa_history = list(state.get("qa_history") or [])
    latest_reply = (state.get("latest_reply") or "").strip()

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
    }


def route_after_prepare(state: InterviewState) -> str:
    if state.get("skip_extraction"):
        return "save_experience"
    return "extract_star"


async def extract_star(state: InterviewState) -> dict[str, Any]:
    """누적된 메모와 Q&A에서 STAR 구조와 정량 지표를 추출한다."""
    llm = get_fast_llm(temperature=0.1)
    context_text = _build_context_text(state)

    messages = [
        SystemMessage(
            content=(
                "당신은 지원자의 거친 메모를 STAR(Situation, Task, Action, Result) 구조로 정리하는 "
                "커리어 인터뷰 분석가입니다. 사용자가 언급하지 않은 수치, 기술, 성과는 절대 지어내지 마세요."
            )
        ),
        HumanMessage(content=f"아래 내용을 바탕으로 STAR 구조를 추출해 주세요.\n\n{context_text}"),
    ]
    extracted = await ainvoke_structured(llm, StarExtractionSchema, messages, max_retries=1)
    return {"star": extracted.model_dump()}


async def grade_gaps(state: InterviewState) -> dict[str, Any]:
    """추출된 STAR 경험을 DDI BARS × Amazon Bar Raiser × Google XYZ 5축 루브릭으로 객관 채점한다."""
    star = state.get("star") or {}
    context_text = _build_context_text(state)
    result = await evaluate_star_experience_rubric(star, context_text=context_text)
    return {
        "completeness_score": result["completeness_score"],
        "star_scores": result["star_scores"],
        "is_sufficient": result["is_sufficient"],
        "missing_points": result["missing_points"],
    }


def route_after_grade(state: InterviewState) -> str:
    if state.get("force_save"):
        return "save_experience"
    if state.get("completeness_score", 0) >= 80 and state.get("is_sufficient"):
        return "save_experience"
    return "generate_questions"


async def generate_questions(state: InterviewState) -> dict[str, Any]:
    """부족한 빈틈을 메우기 위한 핵심 역질문 1~2개를 생성한다."""
    llm = get_fast_llm(temperature=0.3)
    star = state.get("star") or {}
    missing_points = state.get("missing_points") or []
    qa_history = state.get("qa_history") or []

    messages = [
        SystemMessage(
            content=(
                "당신은 지원자의 경험 밀도를 끌어올리는 능동적 커리어 인터뷰어입니다.\n"
                "이미 물어본 질문을 반복하지 말고, 빠진 정량 지표·트러블슈팅 원인·본인 기여도 중 "
                "가장 중요한 빈틈을 찌르는 짧고 답변하기 쉬운 역질문 1~2개만 한국어로 작성하세요."
            )
        ),
        HumanMessage(
            content=(
                f"[현재 STAR 요약]\n{star}\n\n"
                f"[탐지된 빈틈]\n{missing_points}\n\n"
                f"[이전 질문 횟수]\n{len(qa_history)}회"
            )
        ),
    ]
    followup = await ainvoke_structured(llm, FollowupQuestionsSchema, messages, max_retries=1)
    questions = [q.strip() for q in followup.questions if q.strip()][:2] or [
        "이 경험에서 본인이 직접 해결한 핵심 기술적 과제와 정량적 성과(전후 비교 등)를 조금 더 구체적으로 알려주시겠어요?"
    ]
    return {"questions": questions}


async def save_experience(state: InterviewState) -> dict[str, Any]:
    """구조화된 STAR 경험을 experiences 테이블과 experience 벡터 DB에 동시 저장한다."""
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
            },
        )

    return {
        "saved_experience_id": exp.id,
        "vector_synced": vector_synced,
        "questions": [],
    }


def build_interview_workflow() -> StateGraph:
    workflow = StateGraph(InterviewState)
    workflow.add_node("prepare_turn", prepare_turn)
    workflow.add_node("extract_star", extract_star)
    workflow.add_node("grade_gaps", grade_gaps)
    workflow.add_node("generate_questions", generate_questions)
    workflow.add_node("save_experience", save_experience)

    workflow.add_edge(START, "prepare_turn")
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

    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        checkpointer = AsyncPostgresSaver(aconn)
        graph = workflow.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        async for chunk in graph.astream(input_state, config=config, stream_mode="updates"):
            yield chunk

        snapshot = await graph.aget_state(config)
        yield {"__final_state__": dict(snapshot.values)}
