"""
Intercom Management Server – FastAPI Application entry point.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_tables
from app.services.polling_service import start_polling

configure_logging()
logger = get_logger(__name__)


async def _seed_admin() -> None:
    """Create the default admin user if it does not exist."""
    from sqlalchemy import select

    from app.core.security import get_password_hash
    from app.db.session import AsyncSessionLocal
    from app.models import User

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == settings.admin_username))
        user = result.scalar_one_or_none()
        if not user:
            admin = User(
                username=settings.admin_username,
                email=settings.admin_email,
                hashed_password=get_password_hash(settings.admin_password),
                is_active=True,
                is_superuser=True,
            )
            db.add(admin)
            await db.commit()
            logger.info("admin_user_created", username=settings.admin_username)
        else:
            logger.info("admin_user_exists", username=settings.admin_username)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", env=settings.app_env)
    await create_tables()
    await _seed_admin()
    # Sample devices removed — add real devices via UI

    # Start background polling
    polling_task = asyncio.create_task(start_polling())

    yield

    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass
    logger.info("shutdown")


app = FastAPI(
    title="Intercom Management Server",
    description="Local server for managing IP intercom devices (Leelen-compatible)",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Intercom Management Server", "docs": "/api/docs"}
