from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.database import get_engine
from app.auth import router as auth_router
from app.admin import router as admin_router
from app.plans import router as plans_router
from app.notifications import router as notifications_router
from app.dictionaries import router as dictionaries_router
from app.schedule import router as schedule_router
from app.public_data import router as public_data_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    get_engine().dispose()


app = FastAPI(title="Запара API", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(plans_router)
app.include_router(notifications_router)
app.include_router(schedule_router)
app.include_router(dictionaries_router)
app.include_router(public_data_router)


@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "ok"}


@lru_cache
def expected_revisions() -> set[str]:
    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    return set(ScriptDirectory.from_config(config).get_heads())


def check_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
        # Missing migrations make the service unready rather than silently healthy.
        versions = set(connection.execute(
            text("SELECT version_num FROM zapara.alembic_version")
        ).scalars())
        if versions != expected_revisions():
            raise RuntimeError("Database migrations are not at the expected version")


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, str]:
    try:
        await run_in_threadpool(check_database)
    except (SQLAlchemyError, RuntimeError):
        raise HTTPException(status_code=503, detail="Database is not ready") from None
    return {"status": "ok"}
