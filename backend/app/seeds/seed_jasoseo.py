"""우수 자소서 레퍼런스 시딩 스크립트 (로컬 전용 파일 우선 + 멱등성 보장).

우선순위:
1. backend/app/seeds/jasoseo_samples.local.json (gitignore 대상 — 사용자가 직접 수집한 실제 합격 자소서)
2. backend/app/seeds/jasoseo_samples.json (Git 추적용 최소 형식 예시 템플릿)

실행 예시:
    python -m app.seeds.seed_jasoseo
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import VectorDocument, close_db, get_session_factory, init_db
from app.core.vector_store import DocType, upsert_document

logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).parent
LOCAL_SAMPLES_PATH = SEEDS_DIR / "jasoseo_samples.local.json"
DEFAULT_SAMPLES_PATH = SEEDS_DIR / "jasoseo_samples.json"


def resolve_samples_path() -> tuple[Path, str]:
    if LOCAL_SAMPLES_PATH.exists():
        return LOCAL_SAMPLES_PATH, "local"
    return DEFAULT_SAMPLES_PATH, "default_template"


def load_jasoseo_samples(path: Path | None = None) -> tuple[list[dict[str, Any]], str]:
    target_path, source = (path, "custom") if path is not None else resolve_samples_path()
    with target_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{target_path.name} must contain a JSON array.")
    return data, source


def format_sample_content(sample: dict[str, Any]) -> str:
    role_category = str(sample.get("role_category") or "직무 공통").strip()
    question_type = str(sample.get("question_type") or "일반 문항").strip()
    structure_pattern = str(sample.get("structure_pattern") or "").strip()
    points_list = sample.get("key_persuasion_points") or []
    sample_text = str(sample.get("sample_text") or "").strip()

    if not sample_text:
        raise ValueError("sample_text must not be empty.")

    blocks = [
        f"[직무군] {role_category}",
        f"[문항 유형] {question_type}",
    ]
    if structure_pattern:
        blocks.append(f"[전개 구조] {structure_pattern}")
    if points_list:
        points = "\n".join(f"- {str(p).strip()}" for p in points_list if str(p).strip())
        if points:
            blocks.append(f"[핵심 설득 포인트]\n{points}")
    blocks.append(f"[참고 원문]\n{sample_text}")
    return "\n".join(blocks)


def _resolve_ref_id(sample: dict[str, Any], idx: int) -> str:
    explicit_id = str(sample.get("id") or "").strip()
    if explicit_id:
        return explicit_id
    digest = hashlib.sha1(
        f"{sample.get('role_category', '')}|{sample.get('question_type', '')}|{sample.get('sample_text', '')}".encode(
            "utf-8"
        )
    ).hexdigest()[:10]
    return f"local-{idx:02d}-{digest}"


async def seed_jasoseo_samples(
    session: AsyncSession, *, force: bool = False
) -> dict[str, Any]:
    """jasoseo_samples.local.json(우선) 또는 기본 템플릿을 vector_documents에 멱등 업서트한다."""
    samples, source = load_jasoseo_samples()

    existing_ids: set[str] = set()
    if not force:
        stmt = select(VectorDocument.ref_id).where(
            VectorDocument.doc_type == DocType.JASOSEO_SAMPLE.value
        )
        existing_ids = set((await session.execute(stmt)).scalars().all())

    seeded = 0
    skipped = 0

    for idx, sample in enumerate(samples, start=1):
        ref_id = _resolve_ref_id(sample, idx)
        if not force and ref_id in existing_ids:
            skipped += 1
            continue

        content = format_sample_content(sample)
        metadata = {
            "role_category": str(sample.get("role_category") or "직무 공통").strip(),
            "question_type": str(sample.get("question_type") or "일반 문항").strip(),
            "structure_pattern": str(sample.get("structure_pattern") or "").strip(),
            "key_persuasion_points": list(sample.get("key_persuasion_points") or []),
            "source": source,
            "reference_only": True,
        }
        await upsert_document(
            session,
            doc_type=DocType.JASOSEO_SAMPLE,
            ref_id=ref_id,
            content=content,
            metadata=metadata,
        )
        seeded += 1
        logger.info("Seeded jasoseo sample [%s]: %s", source, ref_id)

    return {
        "source": source,
        "total": len(samples),
        "seeded": seeded,
        "skipped": skipped,
    }


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    await init_db()
    try:
        async with get_session_factory()() as session:
            summary = await seed_jasoseo_samples(session)
            logger.info("Jasoseo seeding complete: %s", summary)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(_main())
