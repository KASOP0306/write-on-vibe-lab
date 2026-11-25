"""AWS Bedrock Fast/Smart LLM 및 Embeddings 팩토리, 관측성(Telemetry) 추적 및 Structured Output 폴백 래퍼."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
import json
import logging
import re
import time
from typing import Any, Iterator, TypeVar

import boto3
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ==============================================================================
# LLM Observability & Telemetry (Unit 2: usage_metadata / stopReason / latencyMs)
# ==============================================================================
@dataclass(slots=True)
class LLMCallRecord:
    caller: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    stop_reason: str = ""
    latency_ms: int = 0
    truncated: bool = False


@dataclass
class LLMTelemetryTracker:
    request_name: str = "request"
    calls: list[LLMCallRecord] = field(default_factory=list)

    def add(self, record: LLMCallRecord) -> None:
        self.calls.append(record)

    def summary(self) -> dict[str, Any]:
        total_in = sum(c.input_tokens for c in self.calls)
        total_out = sum(c.output_tokens for c in self.calls)
        total_tok = sum(c.total_tokens for c in self.calls)
        total_ms = sum(c.latency_ms for c in self.calls)
        truncated_calls = [c.caller for c in self.calls if c.truncated]
        return {
            "request_name": self.request_name,
            "call_count": len(self.calls),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_tok,
            "total_latency_ms": total_ms,
            "truncated_callers": truncated_calls,
            "calls": [asdict(c) for c in self.calls],
        }


_CURRENT_TELEMETRY: ContextVar[LLMTelemetryTracker | None] = ContextVar(
    "current_llm_telemetry", default=None
)


@contextmanager
def llm_telemetry_scope(request_name: str = "request") -> Iterator[LLMTelemetryTracker]:
    """요청·그래프 단위 LLM 호출 텔레메트리를 수집하는 컨텍스트 매니저."""
    tracker = LLMTelemetryTracker(request_name=request_name)
    token = _CURRENT_TELEMETRY.set(tracker)
    try:
        yield tracker
    finally:
        _CURRENT_TELEMETRY.reset(token)
        if tracker.calls:
            summary = tracker.summary()
            logger.info(
                "LLM telemetry [%s]: calls=%d tokens=%d (in=%d, out=%d) latency=%dms truncated=%s",
                summary["request_name"],
                summary["call_count"],
                summary["total_tokens"],
                summary["input_tokens"],
                summary["output_tokens"],
                summary["total_latency_ms"],
                summary["truncated_callers"] or "none",
            )


def get_current_telemetry_tracker() -> LLMTelemetryTracker | None:
    return _CURRENT_TELEMETRY.get()


def extract_llm_telemetry(
    ai_msg: Any,
    *,
    model_id: str = "",
    caller: str = "llm_call",
    elapsed_ms: int = 0,
) -> LLMCallRecord:
    """AIMessage의 usage_metadata / response_metadata.stopReason / metrics.latencyMs를 안전하게 추출한다."""
    usage = getattr(ai_msg, "usage_metadata", None) or {}
    resp_meta = getattr(ai_msg, "response_metadata", None) or {}
    metrics = resp_meta.get("metrics") or {}
    token_usage = resp_meta.get("usage") or {}

    input_tokens = int(
        usage.get("input_tokens")
        or token_usage.get("inputTokens")
        or token_usage.get("prompt_tokens")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or token_usage.get("outputTokens")
        or token_usage.get("completion_tokens")
        or 0
    )
    total_tokens = int(
        usage.get("total_tokens")
        or token_usage.get("totalTokens")
        or (input_tokens + output_tokens)
    )

    stop_reason = str(
        resp_meta.get("stopReason")
        or resp_meta.get("stop_reason")
        or resp_meta.get("finish_reason")
        or ""
    )

    # Bedrock Converse metrics.latencyMs는 리스트 또는 int일 수 있음
    raw_latency = metrics.get("latencyMs")
    if isinstance(raw_latency, list) and raw_latency:
        latency_ms = int(raw_latency[0])
    elif isinstance(raw_latency, (int, float)):
        latency_ms = int(raw_latency)
    else:
        latency_ms = int(elapsed_ms)

    resolved_model = str(
        model_id
        or resp_meta.get("model_name")
        or resp_meta.get("model_id")
        or ""
    )
    truncated = stop_reason.lower() in {"max_tokens", "length"}

    record = LLMCallRecord(
        caller=caller,
        model_id=resolved_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        stop_reason=stop_reason,
        latency_ms=latency_ms,
        truncated=truncated,
    )

    tracker = _CURRENT_TELEMETRY.get()
    if tracker is not None:
        tracker.add(record)

    if truncated:
        logger.warning(
            "LLM output truncated (stopReason=%s) caller=%s model=%s in=%d out=%d latency=%dms",
            stop_reason,
            caller,
            resolved_model,
            input_tokens,
            output_tokens,
            latency_ms,
        )
    else:
        logger.debug(
            "LLM call caller=%s model=%s stop=%s in=%d out=%d latency=%dms",
            caller,
            resolved_model,
            stop_reason or "unknown",
            input_tokens,
            output_tokens,
            latency_ms,
        )
    return record


async def ainvoke_tracked(
    llm: ChatBedrockConverse,
    messages: list[BaseMessage] | list[Any],
    *,
    caller: str = "llm_call",
) -> AIMessage:
    """일반 AIMessage 호출을 지연시간·토큰·stopReason 텔레메트리와 함께 실행한다."""
    model_id = str(getattr(llm, "model_id", "") or getattr(llm, "model", ""))
    t0 = time.perf_counter()
    ai_msg = await llm.ainvoke(messages)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    extract_llm_telemetry(ai_msg, model_id=model_id, caller=caller, elapsed_ms=elapsed_ms)
    return ai_msg


# ==============================================================================
# AWS Bedrock Factory
# ==============================================================================
def _create_boto_session() -> boto3.Session:
    """boto3 기본 자격 증명 체인(EC2 IAM Role 또는 로컬 ~/.aws 프로파일)에 위임."""
    if settings.aws_profile:
        return boto3.Session(
            profile_name=settings.aws_profile,
            region_name=settings.aws_region,
        )
    return boto3.Session(region_name=settings.aws_region)


def get_fast_llm(temperature: float = 0.2, max_tokens: int = 2048) -> ChatBedrockConverse:
    """라우팅, STAR-L 추출, 완성도 평가, 관련성 평가, 쿼리 재작성용 Fast Tier LLM."""
    client = _create_boto_session().client("bedrock-runtime")
    return ChatBedrockConverse(
        model=settings.bedrock_fast_model_id,
        client=client,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def get_smart_llm(temperature: float = 0.4, max_tokens: int = 5000) -> ChatBedrockConverse:
    """기업 3각 매칭, 자소서 초안/비평/퇴고, De-AI, 코파일럿, 회고 분석용 Smart Tier LLM.

    Amazon Nova Pro의 최대 출력 토큰(5,120) 범위 내에서 넉넉하게 5,000을 기본 확보한다.
    """
    client = _create_boto_session().client("bedrock-runtime")
    return ChatBedrockConverse(
        model=settings.bedrock_smart_model_id,
        client=client,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def get_embeddings() -> BedrockEmbeddings:
    """1024차원 한국어/다국어 임베딩 모델."""
    client = _create_boto_session().client("bedrock-runtime")
    extra_kwargs: dict[str, Any] = {}
    if settings.bedrock_embed_model_id.startswith("cohere."):
        extra_kwargs["model_kwargs"] = {"truncate": "END"}
    return BedrockEmbeddings(
        model_id=settings.bedrock_embed_model_id,
        client=client,
        **extra_kwargs,
    )


async def embed_text(text_content: str) -> list[float]:
    """동기 boto3 BedrockEmbeddings 호출을 워커 스레드에서 비동기 실행."""
    embeddings = get_embeddings()
    safe_input = (
        text_content[:2000]
        if settings.bedrock_embed_model_id.startswith("cohere.")
        else text_content
    )
    vector = await asyncio.to_thread(embeddings.embed_query, safe_input)
    if len(vector) != settings.embedding_dim:
        raise ValueError(
            f"Expected embedding dim {settings.embedding_dim}, got {len(vector)}."
        )
    return vector


def _extract_json_object(raw_text: str) -> str:
    """LLM 응답 텍스트에서 JSON 코드블록 또는 최외곽 JSON 객체를 추출한다."""
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    start = text.find("{")
    if start != -1:
        end = text.rfind("}")
        if end > start:
            tail = text[end + 1 :].strip()
            if tail and not tail.startswith("```"):
                return text[start:].strip()
            return text[start : end + 1]
        return text[start:].strip()
    return text


def _repair_truncated_json(raw_json: str) -> str:
    """max_tokens로 끝부분이 살짝 잘린 JSON의 미닫힘 문자열/배열/객체를 안전하게 닫아 복구를 시도한다."""
    s = raw_json.strip()
    if not s.startswith("{"):
        return s

    stack: list[str] = []
    in_string = False
    escape = False
    for ch in s:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in ("}", "]") and stack and stack[-1] == ch:
                stack.pop()

    if not in_string and not stack:
        return s

    repaired = s
    if in_string:
        if escape:
            repaired = repaired[:-1]
        repaired += '"'
    repaired = re.sub(r",\s*$", "", repaired)
    repaired = re.sub(r":\s*$", ": null", repaired)
    repaired += "".join(reversed(stack))
    return repaired


async def ainvoke_structured(
    llm: ChatBedrockConverse,
    schema: type[T],
    messages: list[Any],
    max_retries: int = 2,
    caller: str | None = None,
) -> T:
    """Structured Output 안정성 래퍼 (텔레메트리 수집 + JSON Schema 폴백 + 잘림 자동 복구).

    1차: Bedrock Converse Tool-Calling 기반 with_structured_output(include_raw=True) 시도
    2차(폴백): Nova 등 모델에서 중첩 스키마 누락/ToolUse 오류 시 명시적 JSON Schema 프롬프트로 재시도
    """
    call_label = caller or f"structured:{schema.__name__}"
    model_id = str(getattr(llm, "model_id", "") or getattr(llm, "model", ""))
    last_error: Exception | None = None

    # 1차: native structured output (include_raw=True로 usage_metadata/stopReason 함께 수집)
    try:
        try:
            structured_llm = llm.with_structured_output(schema, include_raw=True)
            t0 = time.perf_counter()
            raw_bundle = await structured_llm.ainvoke(messages)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            if isinstance(raw_bundle, dict) and "raw" in raw_bundle:
                extract_llm_telemetry(
                    raw_bundle["raw"],
                    model_id=model_id,
                    caller=call_label,
                    elapsed_ms=elapsed_ms,
                )
                if raw_bundle.get("parsing_error"):
                    raise ValueError(f"Parsing error: {raw_bundle['parsing_error']}")
                parsed = raw_bundle.get("parsed")
            else:
                parsed = raw_bundle
        except TypeError:
            # include_raw를 지원하지 않는 mock/커스텀 LLM 호환
            structured_llm = llm.with_structured_output(schema)
            parsed = await structured_llm.ainvoke(messages)

        if isinstance(parsed, schema):
            return parsed
        if parsed is not None:
            return schema.model_validate(parsed)
        raise ValueError("Structured output returned None.")
    except Exception as exc:
        last_error = exc
        logger.warning(
            "Structured output (tool-call) failed for %s: %s. Falling back to JSON schema prompt.",
            schema.__name__,
            exc,
        )

    # 2차 이후: JSON Schema 명시 폴백 (최대 max_retries회)
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    for attempt in range(max(1, max_retries)):
        try:
            brevity_hint = (
                "응답이 너무 길어 중간에 잘리지 않도록 각 항목 본문을 핵심 불릿 3~4줄로 간결하게 압축해 완전한 JSON으로 닫아 출력하세요.\n"
                if attempt > 0 or "EOF" in str(last_error) or "ToolUse" in str(last_error)
                else ""
            )
            fallback_instruction = HumanMessage(
                content=(
                    "이전 응답에서 JSON 스키마 검증 오류가 발생했습니다. "
                    "설명 문장이나 마크다운 코드펜스 없이 반드시 아래 JSON Schema에 정확히 일치하는 단일 JSON 객체만 출력하세요.\n"
                    f"{brevity_hint}"
                    f"이전 오류: {last_error}\n"
                    f"JSON Schema:\n{schema_json}"
                )
            )
            ai_msg = await ainvoke_tracked(
                llm,
                [*messages, fallback_instruction],
                caller=f"{call_label}:fallback_{attempt + 1}",
            )
            raw_content = (
                ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
            )
            json_str = _extract_json_object(raw_content)
            try:
                return schema.model_validate_json(json_str)
            except Exception as parse_exc:
                repaired = _repair_truncated_json(json_str)
                if repaired != json_str:
                    logger.info(
                        "Attempting truncated JSON auto-repair for %s", schema.__name__
                    )
                    return schema.model_validate_json(repaired)
                raise parse_exc
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Structured output JSON fallback failed for %s (attempt %d/%d): %s",
                schema.__name__,
                attempt + 1,
                max(1, max_retries),
                exc,
            )

    raise RuntimeError(
        f"Structured output parsing failed for {schema.__name__}: {last_error}"
    ) from last_error
