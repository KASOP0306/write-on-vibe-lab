"""AWS Bedrock Fast/Smart LLM 및 Embeddings 팩토리와 Structured Output 재시도 래퍼."""

import asyncio
import logging
from typing import Any, TypeVar

import boto3
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
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


async def ainvoke_structured(
    llm: ChatBedrockConverse,
    schema: type[T],
    messages: list[Any],
    max_retries: int = 1,
) -> T:
    """Structured Output JSON 파싱 실패 대비 최대 1회 재시도 래퍼 (agents_md.md 3.3)."""
    structured_llm = llm.with_structured_output(schema)
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            result = await structured_llm.ainvoke(messages)
            if isinstance(result, schema):
                return result
            return schema.model_validate(result)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Structured output failed for %s (attempt %d/%d): %s",
                schema.__name__,
                attempt + 1,
                max_retries + 1,
                exc,
            )

    raise RuntimeError(
        f"Structured output parsing failed after {max_retries + 1} attempts for {schema.__name__}"
    ) from last_error
