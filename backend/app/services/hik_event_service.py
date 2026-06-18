"""Hikvision access-event audit supervisor.

Spawns one long-poll ``alertStream`` listener per enabled Hikvision device so a
face-recognition door open emits a normalized ``door_unlocked`` event to the
local SSE bus AND the cloud bridge (the audit trail of who entered, when). The
actual stream parsing lives in ``HikvisionDriver.run_event_stream``; this module
just reconciles which devices should have a listener and (re)starts them — the
same shape as ``anpr_service`` for ANPR cameras.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger

logger = get_logger(__name__)

_RESCAN_INTERVAL = 60.0
_tasks: dict[int, asyncio.Task] = {}  # device_id -> listener task
_supervisor_task: asyncio.Task | None = None


async def _reconcile() -> None:
    """Start listeners for enabled event-stream-capable Hikvision devices; stop
    listeners whose device went away or whose task died."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.drivers import get_driver
    from app.models import Device

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Device).where(
                    Device.vendor == "hikvision",
                    Device.enabled.is_(True),
                )
            )
        ).scalars().all()
        # gate on capability so only event-stream-capable drivers get a listener.
        # AsyncSessionLocal is expire_on_commit=False and we never commit, so the
        # detached Device's scalar attrs stay readable in the listener coroutine.
        wanted = {
            d.id: d
            for d in rows
            if d.ip_address and "event_stream" in get_driver(d).capabilities()
        }

    # stop listeners that are gone or finished
    for device_id in list(_tasks):
        if device_id not in wanted or _tasks[device_id].done():
            _tasks[device_id].cancel()
            del _tasks[device_id]

    # start listeners for newly-eligible devices
    for device_id, device in wanted.items():
        if device_id not in _tasks:
            driver = get_driver(device)
            _tasks[device_id] = asyncio.create_task(driver.run_event_stream(device))
            logger.info("hik_event_started", device_id=device_id, host=device.ip_address)


async def _supervise() -> None:
    while True:
        try:
            await _reconcile()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("hik_event_supervisor_error", error=str(exc))
        await asyncio.sleep(_RESCAN_INTERVAL)


async def start() -> None:
    """Kick off the supervisor (idempotent). Called from the app lifespan."""
    global _supervisor_task
    if _supervisor_task is None or _supervisor_task.done():
        _supervisor_task = asyncio.create_task(_supervise())
        logger.info("hik_event_service_started")


async def stop() -> None:
    """Cancel the supervisor and all listeners."""
    global _supervisor_task
    if _supervisor_task is not None:
        _supervisor_task.cancel()
        _supervisor_task = None
    for device_id in list(_tasks):
        _tasks[device_id].cancel()
        del _tasks[device_id]
