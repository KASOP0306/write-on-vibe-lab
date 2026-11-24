from contextlib import asynccontextmanager
import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import agents, profile, projects, samples
from app.core.database import close_db, get_db_session, init_db
from app.seeds.seed_jasoseo import seed_jasoseo_samples

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="Career & Portfolio AI Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile.router)
app.include_router(projects.router)
app.include_router(samples.router)
app.include_router(agents.router)


@app.get("/api/health")
async def health_check(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database health check failed: {exc}",
        )


@app.post("/api/seeds/jasoseo")
async def trigger_jasoseo_seed(
    force: bool = False,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """우수 자소서 레퍼런스를 vector_documents에 멱등 시딩한다 (jasoseo_samples.local.json 우선)."""
    try:
        return await seed_jasoseo_samples(session, force=force)
    except Exception as exc:
        logger.exception("Jasoseo seeding failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Jasoseo seeding failed (check AWS Bedrock credentials): {exc}",
        )
