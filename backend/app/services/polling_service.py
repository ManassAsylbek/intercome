"""
Background polling service for device availability.

Periodically checks each enabled device's online status
and updates Device.is_online / Device.last_seen in the database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models import Device
from app.services.connectivity_service import test_connection

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 60  # how often to poll all devices


async def _poll_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Device).where(Device.enabled == True))
        devices = result.scalars().all()

        for device in devices:
            if not device.ip_address:
                continue
            try:
                action = await test_connection(device, db=db, actor="polling")
                device.is_online = action.success
                if action.success:
                    device.last_seen = datetime.now(timezone.utc)
            except Exception:
                logger.exception("poll_device_error", device_id=device.id)

        await db.commit()
        logger.info("poll_cycle_complete", total_polled=len(devices))


async def start_polling() -> None:
    """Run the polling loop forever. Should be started as a background task."""
    logger.info("device_polling_started", interval_seconds=POLL_INTERVAL_SECONDS)
    while True:
        try:
            await _poll_once()
        except Exception:
            logger.exception("poll_cycle_error")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
