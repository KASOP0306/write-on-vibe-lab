"""AWS Bedrock Fast LLM, Smart LLM, Structured Output, Embeddings 단위 검증 스크립트.

실행 예시:
    python -m app.scripts.verify_bedrock
"""

import asyncio
import logging

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.core.bedrock import (
    ainvoke_structured,
    embed_text,
    get_fast_llm,
    get_smart_llm,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class PingSchema(BaseModel):
    status: str = Field(description="응답 상태 (예: ok)")
    summary: str = Field(description="한 문장 요약")


async def verify_all() -> None:
    logger.info("AWS Region: %s", settings.aws_region)
    logger.info("Fast Model: %s", settings.bedrock_fast_model_id)
    logger.info("Smart Model: %s", settings.bedrock_smart_model_id)
    logger.info("Embed Model: %s (dim=%d)", settings.bedrock_embed_model_id, settings.embedding_dim)

    # 1. Fast LLM + Structured Output 검증
    fast_llm = get_fast_llm()
    fast_res = await ainvoke_structured(
        fast_llm,
        PingSchema,
        [HumanMessage(content="연결 테스트입니다. status를 'ok'로, 한국어 한 문장으로 summary를 작성해 주세요.")],
    )
    logger.info("[PASS] Fast LLM Structured Output: %s", fast_res.model_dump())

    # 2. Smart LLM 검증
    smart_llm = get_smart_llm()
    smart_msg = await smart_llm.ainvoke(
        [HumanMessage(content="AWS Bedrock Smart Tier 연결 확인입니다. 한국어로 15자 이내 인사만 답해 주세요.")]
    )
    logger.info("[PASS] Smart LLM Response: %s", smart_msg.content)

    # 3. Embeddings 검증
    vector = await embed_text("개인화 커리어 포트폴리오 AI 에이전트 임베딩 검증 문장")
    logger.info(
        "[PASS] Embeddings Response: len=%d, sample=%s",
        len(vector),
        [round(v, 4) for v in vector[:5]],
    )


if __name__ == "__main__":
    asyncio.run(verify_all())
