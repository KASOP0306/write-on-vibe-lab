"""사용자 직접 수집 자소서 레퍼런스 CRUD API (DB/벡터에만 저장, Git 미추적)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import VectorDocument, get_db_session
from app.core.vector_store import DocType, delete_document, upsert_document
from app.schemas.samples import SampleCreateRequest, SampleResponse
from app.seeds.seed_jasoseo import format_sample_content

router = APIRouter(prefix="/api/samples", tags=["jasoseo samples"])


def _extract_raw_text(content: str) -> str:
    marker = "[참고 원문]\n"
    if marker in content:
        return content.split(marker, 1)[1].strip()
    return content


def _to_sample_response(doc: VectorDocument) -> SampleResponse:
    meta = doc.doc_metadata or {}
    return SampleResponse(
        id=doc.id,
        ref_id=doc.ref_id,
        role_category=str(meta.get("role_category") or "직무 공통"),
        question_type=str(meta.get("question_type") or "일반 문항"),
        structure_pattern=str(meta.get("structure_pattern") or ""),
        key_persuasion_points=list(meta.get("key_persuasion_points") or []),
        sample_text=_extract_raw_text(doc.content),
        source=str(meta.get("source") or "user_ui"),
        created_at=doc.created_at,
    )


@router.get("", response_model=list[SampleResponse])
async def list_samples(
    session: AsyncSession = Depends(get_db_session),
) -> list[SampleResponse]:
    stmt = (
        select(VectorDocument)
        .where(VectorDocument.doc_type == DocType.JASOSEO_SAMPLE.value)
        .order_by(VectorDocument.created_at.desc(), VectorDocument.id.desc())
    )
    docs = (await session.execute(stmt)).scalars().all()
    return [_to_sample_response(doc) for doc in docs]


@router.post("", response_model=SampleResponse, status_code=status.HTTP_201_CREATED)
async def create_sample(
    payload: SampleCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SampleResponse:
    ref_id = f"user-{uuid.uuid4().hex[:10]}"
    content = format_sample_content(payload.model_dump())
    metadata = {
        "role_category": payload.role_category.strip(),
        "question_type": payload.question_type.strip(),
        "structure_pattern": payload.structure_pattern.strip(),
        "key_persuasion_points": [
            p.strip() for p in payload.key_persuasion_points if p.strip()
        ],
        "source": "user_ui",
        "reference_only": True,
    }

    try:
        doc_id = await upsert_document(
            session,
            doc_type=DocType.JASOSEO_SAMPLE,
            ref_id=ref_id,
            content=content,
            metadata=metadata,
        )
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to embed and store jasoseo sample: {exc}",
        )

    doc = await session.get(VectorDocument, doc_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored sample could not be reloaded.",
        )
    return _to_sample_response(doc)


@router.delete("/{ref_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sample(
    ref_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    stmt = select(VectorDocument).where(
        VectorDocument.doc_type == DocType.JASOSEO_SAMPLE.value,
        VectorDocument.ref_id == ref_id,
    )
    doc = (await session.execute(stmt)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample '{ref_id}' not found.",
        )
    await delete_document(session, doc_type=DocType.JASOSEO_SAMPLE, ref_id=ref_id)
