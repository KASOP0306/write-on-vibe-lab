"""AWS Bedrock Fast/Smart LLM 및 Embeddings 팩토리 모듈 (Day 1 구현 예정)."""

import boto3
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse

from app.config import settings


def _create_boto_session() -> boto3.Session:
    if settings.aws_profile:
        return boto3.Session(
            profile_name=settings.aws_profile,
            region_name=settings.aws_region,
        )
    return boto3.Session(region_name=settings.aws_region)


def get_fast_llm() -> ChatBedrockConverse:
    client = _create_boto_session().client("bedrock-runtime")
    return ChatBedrockConverse(
        model=settings.bedrock_fast_model_id,
        client=client,
        temperature=0.2,
    )


def get_smart_llm() -> ChatBedrockConverse:
    client = _create_boto_session().client("bedrock-runtime")
    return ChatBedrockConverse(
        model=settings.bedrock_smart_model_id,
        client=client,
        temperature=0.4,
    )


def get_embeddings() -> BedrockEmbeddings:
    client = _create_boto_session().client("bedrock-runtime")
    return BedrockEmbeddings(
        model_id=settings.bedrock_embed_model_id,
        client=client,
    )
