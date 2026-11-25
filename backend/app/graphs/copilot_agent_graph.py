"""워크플로우 ④-A2 (v2): 스스로 찾고, 전략을 바꾸고, 멈추고, 기억하는 Agentic RAG 코파일럿 (Unit 7~8).

핵심 구조:
- State: MessagesState 확장 (`tool_count`, `web_search_count`, `used_tools`, `focus_weakness`, `company_profile_id`)
- Node:
  1) `model`: `trim_messages(..., strategy="last", max_tokens=10, start_on="human")` + `bind_tools(COPILOT_TOOLS)`
  2) `tools`: 요청된 도구 실행 + 턴당 웹 검색 1회 상한 + `tool_count` 누적 + SSE 시각화 기록
  3) `stop`: `tool_count >= 4` 도달 시 도구 없이 지금까지의 근거로 정직하게 최종 답변 생성
- Edge & 2중 상한:
  START -> model -> (tool_calls 있으면 tools, 없으면 END)
  tools -> (tool_count < 4 이면 model, 4 이상이면 stop) -> END
  + 실행 config에 `recursion_limit=14` 이중 가드레일
- 2계층 기억:
  - 단기 기억: `AsyncPostgresSaver` (`thread_id`)
  - 장기 기억: `AsyncPostgresStore` (`save_career_memory` / `recall_career_memory` 도구)
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    trim_messages,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from psycopg import AsyncConnection

from app.core.bedrock import ainvoke_tracked, get_smart_llm
from app.core.database import get_psycopg_conninfo
from app.prompts import load_prompt
from app.tools.copilot_tools import COPILOT_TOOLS, COPILOT_TOOLS_BY_NAME

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_TURN = 4
MAX_WEB_SEARCH_PER_TURN = 1
AGENT_RECURSION_LIMIT = 14


class CopilotAgentState(MessagesState):
    tool_count: int
    web_search_count: int
    focus_weakness: str
    company_profile_id: int | None
    used_tools: list[dict[str, Any]]
    used_web_fallback: bool


def safe_trim_agent_messages(
    messages: list[BaseMessage],
    *,
    max_messages: int = 10,
) -> list[BaseMessage]:
    """체크포인트 전체 State는 유지하고, 모델에 보낼 최근 메시지만 tool_call 짝을 깨지 않게 자른다 (Unit 8 [s16])."""
    if not messages:
        return []

    trimmed = trim_messages(
        messages,
        strategy="last",
        token_counter=len,
        max_tokens=max_messages,
        start_on="human",
        include_system=False,
        allow_partial=False,
    )
    if trimmed:
        return list(trimmed)

    # 현재 턴의 도구 호출이 많아 max_messages를 초과한 경우, 마지막 HumanMessage부터 끝까지 전부 유지
    for idx in range(len(messages) - 1, -1, -1):
        if isinstance(messages[idx], HumanMessage):
            return list(messages[idx:])
    return list(messages[-max_messages:])


def _build_runtime_system_prompt(state: CopilotAgentState) -> str:
    base_prompt = load_prompt("copilot_agent_system")
    extras: list[str] = []
    focus = (state.get("focus_weakness") or "").strip()
    if focus:
        extras.append(f"- 사용자가 지정한 집중 보완 약점: {focus}")
    comp_id = state.get("company_profile_id")
    if comp_id:
        extras.append(f"- 사용자가 선택한 목표 기업 ID가 지정되어 있습니다 (필요 시 get_company_research 호출).")
    if extras:
        return f"{base_prompt}\n\n<session_context>\n" + "\n".join(extras) + "\n</session_context>"
    return base_prompt


async def call_model(state: CopilotAgentState) -> dict[str, Any]:
    """model Node: 최근 메시지만 잘라 도구 바인딩된 Smart LLM을 호출한다."""
    llm = get_smart_llm(temperature=0.3, max_tokens=3500)
    llm_with_tools = llm.bind_tools(COPILOT_TOOLS)

    recent = safe_trim_agent_messages(list(state.get("messages") or []), max_messages=10)
    system_msg = SystemMessage(content=_build_runtime_system_prompt(state))
    ai_msg = await ainvoke_tracked(
        llm_with_tools,
        [system_msg, *recent],
        caller=f"copilot_agent:model_t{state.get('tool_count', 0)}",
    )
    return {"messages": [ai_msg]}


async def run_tools(state: CopilotAgentState) -> dict[str, Any]:
    """tools Node: 모델이 요청한 도구를 실행하고 tool_count·웹 검색 상한·도구 로그를 갱신한다."""
    messages = list(state.get("messages") or [])
    last_msg = messages[-1] if messages else None
    tool_calls = getattr(last_msg, "tool_calls", None) or []

    tool_count = int(state.get("tool_count") or 0)
    web_search_count = int(state.get("web_search_count") or 0)
    used_tools = list(state.get("used_tools") or [])
    used_web = bool(state.get("used_web_fallback"))

    tool_messages: list[ToolMessage] = []

    for call in tool_calls:
        name = str(call.get("name") or "")
        args = dict(call.get("args") or {})
        call_id = str(call.get("id") or f"call_{tool_count}")

        if name == "web_search_reference" and web_search_count >= MAX_WEB_SEARCH_PER_TURN:
            output_text = (
                "이번 턴의 웹 검색 상한(최대 1회)에 도달했습니다. "
                "이미 수집한 내부·웹 근거만으로 답변을 마무리하세요."
            )
            tool_messages.append(
                ToolMessage(content=output_text, tool_call_id=call_id, name=name)
            )
            used_tools.append(
                {"name": name, "args": args, "preview": output_text[:140], "capped": True}
            )
            tool_count += 1
            continue

        selected_tool = COPILOT_TOOLS_BY_NAME.get(name)
        if selected_tool is None:
            output_text = f"알 수 없는 도구입니다: {name}. 사용 가능한 도구: {list(COPILOT_TOOLS_BY_NAME.keys())}"
            tool_messages.append(
                ToolMessage(content=output_text, tool_call_id=call_id, name=name)
            )
            tool_count += 1
            continue

        try:
            raw_res = await selected_tool.ainvoke(args)
            output_text = raw_res if isinstance(raw_res, str) else str(raw_res)
        except Exception as exc:
            logger.warning("Copilot tool '%s' failed: %s", name, exc)
            output_text = f"도구 '{name}' 실행 중 오류가 발생했습니다: {exc}"

        if name == "web_search_reference":
            web_search_count += 1
            used_web = True

        tool_count += 1
        used_tools.append(
            {
                "name": name,
                "args": args,
                "preview": output_text.replace("\n", " ")[:160],
                "capped": False,
            }
        )
        tool_messages.append(
            ToolMessage(content=output_text, tool_call_id=call_id, name=name)
        )

    return {
        "messages": tool_messages,
        "tool_count": tool_count,
        "web_search_count": web_search_count,
        "used_tools": used_tools,
        "used_web_fallback": used_web,
    }


async def stop_and_answer(state: CopilotAgentState) -> dict[str, Any]:
    """stop Node: 도구 호출 상한(MAX_TOOL_CALLS_PER_TURN) 도달 시 추가 도구 없이 최종 답을 생성한다 (Unit 8 [s10])."""
    logger.warning(
        "Copilot agent reached tool limit (%d >= %d); stopping cleanly.",
        state.get("tool_count", 0),
        MAX_TOOL_CALLS_PER_TURN,
    )
    llm = get_smart_llm(temperature=0.3, max_tokens=3000)
    recent = safe_trim_agent_messages(list(state.get("messages") or []), max_messages=12)
    stop_system = SystemMessage(
        content=(
            _build_runtime_system_prompt(state)
            + "\n\n[중요] 도구 호출 상한에 도달했습니다. 더 이상 도구를 요청하지 말고, "
            "지금까지 확보한 도구 결과만을 근거로 사용자에게 가장 명확하고 정직한 최종 답변을 작성하세요. "
            "확인되지 않은 사실은 지어내지 말고 부족한 부분을 솔직히 안내하세요."
        )
    )
    ai_msg = await ainvoke_tracked(
        llm,
        [stop_system, *recent],
        caller="copilot_agent:stop",
    )
    return {"messages": [ai_msg]}


def route_after_model(state: CopilotAgentState) -> str:
    messages = state.get("messages") or []
    last_msg = messages[-1] if messages else None
    if last_msg is not None and getattr(last_msg, "tool_calls", None):
        return "tools"
    return END


def route_after_tools(state: CopilotAgentState) -> str:
    if int(state.get("tool_count") or 0) >= MAX_TOOL_CALLS_PER_TURN:
        return "stop"
    return "model"


def build_copilot_agent_workflow() -> StateGraph:
    workflow = StateGraph(CopilotAgentState)
    workflow.add_node("model", call_model)
    workflow.add_node("tools", run_tools)
    workflow.add_node("stop", stop_and_answer)

    workflow.add_edge(START, "model")
    workflow.add_conditional_edges(
        "model",
        route_after_model,
        {
            "tools": "tools",
            END: END,
        },
    )
    workflow.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "model": "model",
            "stop": "stop",
        },
    )
    workflow.add_edge("stop", END)
    return workflow


def _extract_text_from_ai_message(msg: BaseMessage | None) -> str:
    if msg is None:
        return ""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                text_parts.append(block)
        return "\n".join(p for p in text_parts if p).strip()
    return str(content).strip()


async def stream_copilot_agent(
    *,
    thread_id: str,
    message: str,
    focus_weakness: str = "",
    company_profile_id: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """AsyncPostgresSaver Checkpointer + recursion_limit=14로 코파일럿 에이전트를 스트리밍 실행한다."""
    conninfo = get_psycopg_conninfo()
    workflow = build_copilot_agent_workflow()

    input_state: dict[str, Any] = {
        "messages": [HumanMessage(content=message.strip())],
        "tool_count": 0,
        "web_search_count": 0,
        "used_tools": [],
        "used_web_fallback": False,
        "focus_weakness": focus_weakness.strip(),
        "company_profile_id": company_profile_id,
    }
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": AGENT_RECURSION_LIMIT,
    }

    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        checkpointer = AsyncPostgresSaver(aconn)
        graph = workflow.compile(checkpointer=checkpointer)

        async for chunk in graph.astream(input_state, config=config, stream_mode="updates"):
            yield chunk

        snapshot = await graph.aget_state(config)
        final_values = dict(snapshot.values or {})
        all_msgs = list(final_values.get("messages") or [])
        final_ai = next(
            (m for m in reversed(all_msgs) if isinstance(m, AIMessage) and _extract_text_from_ai_message(m)),
            None,
        )
        yield {
            "__final_result__": {
                "thread_id": thread_id,
                "answer": _extract_text_from_ai_message(final_ai),
                "tool_count": int(final_values.get("tool_count") or 0),
                "used_tools": list(final_values.get("used_tools") or []),
                "used_web_fallback": bool(final_values.get("used_web_fallback")),
                "message_count": len(all_msgs),
            }
        }


async def get_copilot_thread_history(thread_id: str) -> list[dict[str, Any]]:
    """AsyncPostgresSaver에 저장된 특정 thread_id의 사람/AI 대화 히스토리를 반환한다."""
    conninfo = get_psycopg_conninfo()
    workflow = build_copilot_agent_workflow()
    config = {"configurable": {"thread_id": thread_id}}

    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        checkpointer = AsyncPostgresSaver(aconn)
        graph = workflow.compile(checkpointer=checkpointer)
        snapshot = await graph.aget_state(config)
        msgs = list((snapshot.values or {}).get("messages") or [])

    history: list[dict[str, Any]] = []
    for m in msgs:
        if isinstance(m, HumanMessage):
            text = _extract_text_from_ai_message(m)
            if text:
                history.append({"role": "user", "content": text})
        elif isinstance(m, AIMessage):
            text = _extract_text_from_ai_message(m)
            if text:
                history.append({"role": "assistant", "content": text})
    return history
