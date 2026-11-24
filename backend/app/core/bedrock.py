"""AWS Bedrock Fast/Smart LLM 및 Embeddings 팩토리와 Structured Output 재시도/JSON 폴백 래퍼."""

import asyncio
import json
import logging
import re
from typing import Any, TypeVar

import boto3
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _create_boto_session() -> boto3.Session:
    """boto3 기본 자격 증명 체인(EC2 IAM Role 또는 로컬 ~/.aws 프로파일)에 위임."""
    if settings.aws_profile:
        return boto3.Session(
            profile_name=settings.aws_profile,
            region_name=settings.aws_region,
        )
    return boto3.Session(region_name=settings.aws_region)


def get_fast_llm(temperature: float = 0.2) -> ChatBedrockConverse:
    """라우팅, STAR 추출, 완성도 평가, 관련성 평가용 Fast Tier LLM."""
    client = _create_boto_session().client("bedrock-runtime")
    return ChatBedrockConverse(
        model=settings.bedrock_fast_model_id,
        client=client,
        temperature=temperature,
    )


def get_smart_llm(temperature: float = 0.4) -> ChatBedrockConverse:
    """기업 3각 매칭, 자소서 초안/비평/퇴고, De-AI, 회고 분석용 Smart Tier LLM."""
    client = _create_boto_session().client("bedrock-runtime")
    return ChatBedrockConverse(
        model=settings.bedrock_smart_model_id,
        client=client,
        temperature=temperature,
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
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


async def ainvoke_structured(
    llm: ChatBedrockConverse,
    schema: type[T],
    messages: list[Any],
    max_retries: int = 1,
) -> T:
    """Structured Output 안정성 래퍼 (agents_md.md 3.3).

    1차: Bedrock Converse Tool-Calling 기반 with_structured_output 시도
    2차(폴백): Nova 등 모델에서 중첩 스키마 누락 시 명시적 JSON Schema 프롬프트로 재시도
    """
    structured_llm = llm.with_structured_output(schema)
    last_error: Exception | None = None

    # 1차: native structured output (tool calling)
    try:
        result = await structured_llm.ainvoke(messages)
        if isinstance(result, schema):
            return result
        if result is not None:
            return schema.model_validate(result)
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
            fallback_instruction = HumanMessage(
                content=(
                    "이전 응답에서 JSON 스키마 검증 오류가 발생했습니다. "
                    "설명 문장 없이 반드시 아래 JSON Schema에 정확히 일치하는 단일 JSON 객체만 출력하세요.\n"
                    f"이전 오류: {last_error}\n"
                    f"JSON Schema:\n{schema_json}"
                )
            )
            ai_msg = await llm.ainvoke([*messages, fallback_instruction])
            raw_content = (
                ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
            )
            json_str = _extract_json_object(raw_content)
            return schema.model_validate_json(json_str)
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
