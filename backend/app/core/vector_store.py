"""doc_type 필터 강제 RAG 저장/검색 래퍼 모듈 (Day 1 구현 예정)."""

from enum import StrEnum


class DocType(StrEnum):
    EXPERIENCE = "experience"
    CAREER_IDENTITY = "career_identity"
    COMPANY_RESEARCH = "company_research"
    INTEREST_CLIP = "interest_clip"
    JASOSEO_SAMPLE = "jasoseo_sample"


def validate_doc_types(doc_types: list[str]) -> list[DocType]:
    if not doc_types:
        raise ValueError("doc_types must be a non-empty list to enforce RAG isolation.")
    return [DocType(dt) for dt in doc_types]
