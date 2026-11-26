"""PostgreSQL + pgvector ORM 모델, 비동기 연결 풀, 스키마 및 LangGraph Checkpointer 초기화."""

from collections.abc import AsyncGenerator
from datetime import datetime
import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from pgvector.sqlalchemy import Vector
from psycopg import AsyncConnection
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    career_vision: Mapped[str] = mapped_column(Text, default="", nullable=False)
    core_beliefs: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target_roles: Mapped[str] = mapped_column(Text, default="", nullable=False)
    preferred_tone: Mapped[str] = mapped_column(Text, default="", nullable=False)
    portfolio_diagnosis: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    external_competency_notes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserInterest(Base):
    __tablename__ = "user_interests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BeliefNote(Base):
    """책·강의 구절, 아티클, 일상 생각·회고를 축적하는 신념 저널 테이블."""

    __tablename__ = "belief_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(
        String(40), default="thought", nullable=False, index=True
    )  # book | lecture | article | thought
    source_title: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    quote_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    my_reflection: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    ai_reflection: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    period: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tech_stack: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    portfolio_goal_link: Mapped[str] = mapped_column(Text, default="", nullable=False)
    repo_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    project_types: Mapped[list] = mapped_column(
        JSONB, default=lambda: ["engineering"], nullable=False
    )
    artifact_links: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    retrospective: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_portfolio_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    experiences: Mapped[list["Experience"]] = relationship(
        back_populates="project",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    sections: Mapped[list["ProjectSection"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectSection.display_order.asc(), ProjectSection.id.asc()",
    )
    documents: Mapped[list["ProjectDocument"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectDocument.created_at.desc(), ProjectDocument.id.desc()",
    )


class ProjectSection(Base):
    __tablename__ = "project_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    track: Mapped[str] = mapped_column(String(40), default="core", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="sections")


class ProjectDocument(Base):
    __tablename__ = "project_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50), default="file_upload", nullable=False
    )
    file_format: Mapped[str] = mapped_column(String(30), default="txt", nullable=False)
    extracted_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applied_sections: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="documents")


class Experience(Base):
    __tablename__ = "experiences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    situation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    task: Mapped[str] = mapped_column(Text, default="", nullable=False)
    action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    learning: Mapped[str] = mapped_column(Text, default="", nullable=False)
    quantified_metrics: Mapped[str] = mapped_column(Text, default="", nullable=False)
    completeness_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    star_scores: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    raw_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project | None] = relationship(back_populates="experiences")


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    target_role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    mission_vision: Mapped[str] = mapped_column(Text, default="", nullable=False)
    core_values: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recent_trends: Mapped[str] = mapped_column(Text, default="", nullable=False)
    value_alignment_map: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApplicationLog(Base):
    __tablename__ = "application_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    stage: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    feedback_memo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    gap_analysis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    action_plan: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QuestionFeedbackLog(Base):
    """루프 A(질문 퀄리티 상승 루프): 역질문 기법·축·21지표별 ΔSTAR-L 효용 & 사용자 👍/👎 피드백 누적 로그."""

    __tablename__ = "question_feedback_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_flow: Mapped[str] = mapped_column(String(50), default="interview", nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(120), default="", nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    technique: Mapped[str] = mapped_column(String(50), default="micro_behavioral", nullable=False, index=True)
    target_axis: Mapped[str] = mapped_column(String(30), default="action", nullable=False, index=True)
    target_checkpoints: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    score_before: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score_after: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delta_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unlocked_checkpoints: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critic_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critic_revisions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user_vote: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 (👍) | -1 (👎) | None
    user_reason: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExperienceFeedbackLog(Base):
    """경험 채굴 완료 시 사용자 만족도(1~5★) 및 점수 체감 캘리브레이션(후함/적절/박함) 로그."""

    __tablename__ = "experience_feedback_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experience_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("experiences.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(120), default="", nullable=False, index=True)
    rubric_version: Mapped[str] = mapped_column(String(20), default="v2.0", nullable=False)
    satisfaction_rating: Mapped[int] = mapped_column(Integer, default=5, nullable=False)  # 1..5
    score_perception: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # -1(박함) | 0(적절) | 1(후함)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    initial_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    final_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score_gain: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CoverLetter(Base):
    """생성 자소서 보관함 테이블 (QA #2)."""

    __tablename__ = "cover_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    target_role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    char_limit: Mapped[int] = mapped_column(Integer, default=800, nullable=False)
    final_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    critic_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_projects: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    used_experiences: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    diff_summary: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    checkpoint_checks: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    memo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VectorDocument(Base):
    __tablename__ = "vector_documents"
    __table_args__ = (
        UniqueConstraint(
            "doc_type", "ref_id", name="uq_vector_documents_doc_type_ref_id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    ref_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    doc_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dim), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_sqlalchemy_database_url() -> str:
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Copy .env.example to .env and set DATABASE_URL."
        )
    if settings.database_url.startswith("postgresql://"):
        return settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return settings.database_url


def get_psycopg_conninfo() -> str:
    url = get_sqlalchemy_database_url()
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_sqlalchemy_database_url(),
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def init_db() -> None:
    """pgvector 확장, 정형 테이블 + vector_documents, 멱등 컬럼 마이그레이션, LangGraph Checkpointer 초기화."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # 기존 pgdata 볼륨 무중단 호환을 위한 멱등 스키마 확장
        await conn.execute(
            text(
                "ALTER TABLE projects "
                "ADD COLUMN IF NOT EXISTS project_types JSONB NOT NULL DEFAULT '[\"engineering\"]'::jsonb"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE projects "
                "ADD COLUMN IF NOT EXISTS artifact_links JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE projects "
                "ADD COLUMN IF NOT EXISTS retrospective JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE projects "
                "ADD COLUMN IF NOT EXISTS is_portfolio_selected BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE project_sections "
                "ADD COLUMN IF NOT EXISTS track VARCHAR(40) NOT NULL DEFAULT 'core'"
            )
        )
        await conn.execute(
            text(
                "UPDATE project_sections SET track = 'engineering' "
                "WHERE track = 'core' AND section_type IN ('architecture', 'decisions', 'implementation', 'troubleshooting')"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE experiences "
                "ADD COLUMN IF NOT EXISTS star_scores JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE experiences "
                "ADD COLUMN IF NOT EXISTS learning TEXT NOT NULL DEFAULT ''"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE user_profile "
                "ADD COLUMN IF NOT EXISTS portfolio_diagnosis JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE user_profile "
                "ADD COLUMN IF NOT EXISTS external_competency_notes JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE question_feedback_logs "
                "ADD COLUMN IF NOT EXISTS thread_id VARCHAR(120) NOT NULL DEFAULT ''"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE question_feedback_logs "
                "ADD COLUMN IF NOT EXISTS project_id INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE question_feedback_logs "
                "ADD COLUMN IF NOT EXISTS target_checkpoints JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE question_feedback_logs "
                "ADD COLUMN IF NOT EXISTS unlocked_checkpoints INTEGER NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE question_feedback_logs "
                "ADD COLUMN IF NOT EXISTS user_vote INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE question_feedback_logs "
                "ADD COLUMN IF NOT EXISTS user_reason VARCHAR(80) NOT NULL DEFAULT ''"
            )
        )
        # Unit 5: pgvector HNSW 코사인 유사도 인덱스 (검색 속도·확장성 확보)
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_vector_documents_embedding_hnsw "
                "ON vector_documents USING hnsw (embedding vector_cosine_ops)"
            )
        )
    logger.info("PostgreSQL tables, pgvector extension, and HNSW index initialized.")

    conninfo = get_psycopg_conninfo()
    async with await AsyncConnection.connect(conninfo, autocommit=True) as aconn:
        checkpointer = AsyncPostgresSaver(aconn)
        await checkpointer.setup()
        store = AsyncPostgresStore(
            aconn,
            index={
                "dims": settings.embedding_dim,
                "embed": _store_embed_texts,
                "fields": ["text"],
            },
        )
        await store.setup()
    logger.info("LangGraph AsyncPostgresSaver & AsyncPostgresStore tables initialized.")


async def _store_embed_texts(texts: list[str]) -> list[list[float]]:
    """AsyncPostgresStore 장기 기억용 비동기 임베딩 어댑터 (Titan Embed v2 1024차원)."""
    from app.core.bedrock import embed_text

    vectors: list[list[float]] = []
    for item in texts:
        vectors.append(await embed_text(str(item)))
    return vectors


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
