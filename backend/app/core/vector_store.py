"""doc_type 필터 강제 RAG 저장/검색 래퍼 모듈 (agents_md.md Section 4)."""

from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bedrock import embed_text
from app.core.database import VectorDocument

logger = logging.getLogger(__name__)


class DocType(StrEnum):
    EXPERIENCE = "experience"
    CAREER_IDENTITY = "career_identity"
    COMPANY_RESEARCH = "company_research"
    INTEREST_CLIP = "interest_clip"
    JASOSEO_SAMPLE = "jasoseo_sample"


@dataclass(slots=True)
class VectorSearchHit:
    id: int
    doc_type: str
    ref_id: str
    content: str
    metadata: dict[str, Any]
    distance: float
    similarity: float


def validate_doc_types(doc_types: list[str] | list[DocType]) -> list[str]:
    """필터 없는 전체 벡터 검색을 원천 차단하고 허용된 5종 Enum만 통과시킨다."""
    if not doc_types:
        raise ValueError("doc_types must be a non-empty list to enforce RAG isolation.")
    validated: list[str] = []
    for dt in doc_types:
        validated.append(DocType(dt).value)
    return validated


async def upsert_document(
    session: AsyncSession,
    *,
    doc_type: str | DocType,
    ref_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
) -> int:
    """(doc_type, ref_id) 기준으로 벡터 문서를 원자적으로 업서트하고 문서 ID를 반환한다."""
    validated_type = DocType(doc_type).value
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("Cannot upsert empty content into vector_documents.")

    vector = embedding if embedding is not None else await embed_text(clean_content)
    doc_meta = metadata or {}

    table = VectorDocument.__table__
    insert_stmt = pg_insert(table).values(
        doc_type=validated_type,
        ref_id=str(ref_id),
        content=clean_content,
        metadata=doc_meta,
        embedding=vector,
    )
    stmt = insert_stmt.on_conflict_do_update(
        constraint="uq_vector_documents_doc_type_ref_id",
        set_={
            "content": insert_stmt.excluded.content,
            "metadata": insert_stmt.excluded.metadata,
            "embedding": insert_stmt.excluded.embedding,
        },
    ).returning(table.c.id)
    result = await session.execute(stmt)
    await session.commit()
    return int(result.scalar_one())


async def try_upsert_document(
    session: AsyncSession,
    *,
    doc_type: str | DocType,
    ref_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """정형 DB 저장 후 벡터 동기화를 시도하고 성공 여부를 반환한다.

    임베딩 호출을 DB 트랜잭션보다 먼저 수행해 Bedrock 장애 시
    호출자의 SQLAlchemy 세션(ORM 인스턴스)이 rollback으로 만료되지 않게 보호한다.
    """
    clean_content = content.strip()
    if not clean_content:
        return False

    try:
        vector = await embed_text(clean_content)
    except Exception as exc:
        logger.warning(
            "Vector embedding skipped/failed for (%s, %s): %s", doc_type, ref_id, exc
        )
        return False

    try:
        await upsert_document(
            session,
            doc_type=doc_type,
            ref_id=ref_id,
            content=clean_content,
            metadata=metadata,
            embedding=vector,
        )
        return True
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "Vector upsert DB write failed for (%s, %s): %s", doc_type, ref_id, exc
        )
        return False


async def delete_document(
    session: AsyncSession,
    *,
    doc_type: str | DocType,
    ref_id: str,
) -> None:
    """정형 데이터 삭제 시 연결된 벡터 문서를 함께 정리한다."""
    validated_type = DocType(doc_type).value
    stmt = delete(VectorDocument).where(
        VectorDocument.doc_type == validated_type,
        VectorDocument.ref_id == str(ref_id),
    )
    await session.execute(stmt)
    await session.commit()


async def search_documents(
    session: AsyncSession,
    *,
    query: str,
    doc_types: list[str] | list[DocType],
    top_k: int = 5,
    metadata_filter: dict[str, Any] | None = None,
) -> list[VectorSearchHit]:
    """doc_types 필터를 강제한 코사인 유사도 기반 벡터 검색."""
    validated_types = validate_doc_types(doc_types)
    query_vector = await embed_text(query)

    distance_expr = VectorDocument.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(VectorDocument, distance_expr)
        .where(VectorDocument.doc_type.in_(validated_types))
        .order_by(distance_expr.asc())
        .limit(top_k)
    )

    if metadata_filter:
        stmt = stmt.where(VectorDocument.doc_metadata.contains(metadata_filter))

    rows = (await session.execute(stmt)).all()
    hits: list[VectorSearchHit] = []
    for doc, distance in rows:
        dist_val = float(distance) if distance is not None else 1.0
        hits.append(
            VectorSearchHit(
                id=doc.id,
                doc_type=doc.doc_type,
                ref_id=doc.ref_id,
                content=doc.content,
                metadata=doc.doc_metadata or {},
                distance=dist_val,
                similarity=max(0.0, 1.0 - dist_val),
            )
        )
    return hits
