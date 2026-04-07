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


async def _seed_sample_devices() -> None:
    """Seed sample door station and home station on first run."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models import Device, DeviceType, UnlockMethod

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Device))
        if result.scalars().first() is not None:
            return  # Already seeded

        door_station = Device(
            name="Front Door Station",
            device_type=DeviceType.DOOR_STATION,
            ip_address="192.168.31.31",
            web_port=8000,
            enabled=True,
            notes="Leelen-compatible door station at front entrance",
            sip_enabled=True,
            sip_account="door001",
            sip_password="sip123456",
            sip_server="192.168.31.132",
            sip_port=5060,
            rtsp_enabled=True,
            rtsp_url="rtsp://admin:123456@192.168.31.31:554/h264",
            unlock_enabled=True,
            unlock_method=UnlockMethod.HTTP_GET,
            unlock_url="http://192.168.31.31:8000/unlock",
            unlock_username="admin",
            unlock_password="123456",
        )
        home_station = Device(
            name="Living Room Home Station",
            device_type=DeviceType.HOME_STATION,
            ip_address="192.168.31.100",
            web_port=80,
            enabled=True,
            notes="Leelen-compatible home station in living room",
            sip_enabled=True,
            sip_account="home001",
            sip_password="sip123456",
            sip_server="192.168.31.132",
            sip_port=5060,
        )
        db.add(door_station)
        db.add(home_station)
        await db.commit()
        logger.info("sample_devices_seeded")


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
