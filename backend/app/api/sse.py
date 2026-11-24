"""공통 SSE(Server-Sent Events) 포맷 유틸 (agents_md.md 5.3)."""

import json
from typing import Any

from fastapi.responses import StreamingResponse

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def sse_node_start(node: str, message: str) -> str:
    return format_sse({"event": "node_start", "node": node, "message": message})


def sse_node_end(node: str, data: dict[str, Any]) -> str:
    return format_sse({"event": "node_end", "node": node, "data": data})


def sse_interrupt(thread_id: str, data: dict[str, Any]) -> str:
    return format_sse({"event": "interrupt", "thread_id": thread_id, "data": data})


def sse_done(data: dict[str, Any]) -> str:
    return format_sse({"event": "done", "data": data})


def sse_error(message: str) -> str:
    return format_sse({"event": "error", "message": message})


def create_sse_response(generator) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
