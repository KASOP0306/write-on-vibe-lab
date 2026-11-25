"""기존 DB 레코드(프로젝트 섹션·STAR-L·기업 리서치·신념·자소서 샘플)를 Parent/Child 청킹으로 일괄 재색인하는 스크립트."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import (
    BeliefNote,
    CompanyProfile,
    Experience,
    Project,
    UserProfile,
    VectorDocument,
    close_db,
    get_session_factory,
    init_db,
)
from app.core.vector_store import DocType, upsert_document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def reindex_all() -> dict[str, int]:
    await init_db()
    counts = {
        "profile": 0,
        "belief_notes": 0,
        "project_sections": 0,
        "experiences": 0,
        "companies": 0,
        "jasoseo_samples": 0,
    }

    async with get_session_factory()() as session:
        # 1. UserProfile
        profile = await session.get(UserProfile, 1)
        if profile and any(
            [profile.career_vision, profile.core_beliefs, profile.target_roles]
        ):
            content = (
                f"[커리어 비전] {profile.career_vision}\n"
                f"[핵심 신념] {profile.core_beliefs}\n"
                f"[희망 직무] {profile.target_roles}\n"
                f"[선호 문체] {profile.preferred_tone}"
            )
            await upsert_document(
                session,
                doc_type=DocType.CAREER_IDENTITY,
                ref_id="user-profile-1",
                content=content,
                metadata={"source_label": "커리어 신념·비전"},
            )
            counts["profile"] += 1

        # 2. BeliefNotes
        notes = (await session.execute(select(BeliefNote))).scalars().all()
        for n in notes:
            content = (
                f"[{n.source_type}] {n.source_title}\n"
                f"인용/원문: {n.quote_text}\n"
                f"나의 생각: {n.my_reflection}\n"
                f"AI 회고: {n.ai_reflection}"
            ).strip()
            if content:
                await upsert_document(
                    session,
                    doc_type=DocType.CAREER_IDENTITY,
                    ref_id=f"belief-note-{n.id}",
                    content=content,
                    metadata={
                        "belief_note_id": n.id,
                        "source_type": n.source_type,
                        "source_title": n.source_title,
                    },
                )
                counts["belief_notes"] += 1

        # 3. Project Sections
        projects = (
            (await session.execute(select(Project).options(selectinload(Project.sections))))
            .scalars()
            .all()
        )
        for p in projects:
            for sec in p.sections:
                if not (sec.content or "").strip():
                    continue
                content = (
                    f"[프로젝트] {p.name} ({p.role})\n"
                    f"[섹션] {sec.title} ({sec.track})\n"
                    f"{sec.content.strip()}"
                )
                await upsert_document(
                    session,
                    doc_type=DocType.EXPERIENCE,
                    ref_id=f"proj-{p.id}-sec-{sec.id}",
                    content=content,
                    metadata={
                        "project_id": p.id,
                        "project_name": p.name,
                        "section_id": sec.id,
                        "section_title": sec.title,
                        "track": sec.track,
                    },
                )
                counts["project_sections"] += 1

        # 4. Experiences (STAR-L)
        exps = (await session.execute(select(Experience))).scalars().all()
        for e in exps:
            content = (
                f"[경험 제목] {e.title}\n"
                f"[Situation] {e.situation}\n"
                f"[Task] {e.task}\n"
                f"[Action] {e.action}\n"
                f"[Result] {e.result}\n"
                f"[Learning] {e.learning}\n"
                f"[정량 지표] {e.quantified_metrics}"
            )
            await upsert_document(
                session,
                doc_type=DocType.EXPERIENCE,
                ref_id=f"exp-{e.id}",
                content=content,
                metadata={
                    "experience_id": e.id,
                    "project_id": e.project_id,
                    "title": e.title,
                    "completeness_score": e.completeness_score,
                },
            )
            counts["experiences"] += 1

        # 5. Company Profiles
        companies = (await session.execute(select(CompanyProfile))).scalars().all()
        for c in companies:
            content = (
                f"[기업] {c.company_name} ({c.target_role})\n"
                f"[미션/비전] {c.mission_vision}\n"
                f"[핵심가치] {c.core_values}\n"
                f"[최근 동향] {c.recent_trends}"
            )
            await upsert_document(
                session,
                doc_type=DocType.COMPANY_RESEARCH,
                ref_id=f"company-{c.id}",
                content=content,
                metadata={
                    "company_id": c.id,
                    "company_name": c.company_name,
                    "target_role": c.target_role,
                },
            )
            counts["companies"] += 1

        # 6. Existing unchunked jasoseo_sample rows (>620 chars without ::c)
        sample_rows = (
            (
                await session.execute(
                    select(VectorDocument).where(
                        VectorDocument.doc_type == DocType.JASOSEO_SAMPLE.value
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in sample_rows:
            if "::c" in row.ref_id or len(row.content) <= 620:
                continue
            await upsert_document(
                session,
                doc_type=DocType.JASOSEO_SAMPLE,
                ref_id=row.ref_id,
                content=row.content,
                metadata=dict(row.doc_metadata or {}),
            )
            counts["jasoseo_samples"] += 1

    await close_db()
    logger.info("Reindexing completed: %s", counts)
    return counts


if __name__ == "__main__":
    asyncio.run(reindex_all())
