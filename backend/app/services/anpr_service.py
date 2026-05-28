"""ANPR event listener for Dahua ITC cameras (parking module, phase 2).

For every device with ``anpr_enabled`` the service keeps a long-poll HTTP
subscription open to the camera's event channel:

    GET /cgi-bin/eventManager.cgi?action=attach&codes=[TrafficJunction]

Each recognised plate is normalised, checked against [[plate-whitelist]], and
— if allowed — the barrier is opened via ``barrier_service``. Every pass is
written to ``plate_access_log`` and emitted both ways:

  * locally on the event bus as ``plate_recognized`` (consumed by the SSE
    stream for the admin UI);
  * upward via ``cloud_bridge.send_event("plate_recognized", ...)`` so the
    cloud can populate the mobile «история проездов» and fire pushes like
    «ваша машина проехала».

A supervisor task re-scans the device list periodically so cameras toggled
on/off in the admin UI are picked up without a restart.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from app.core.logging import get_logger
from app.events.bus import event_bus

logger = get_logger(__name__)

_RECONNECT_DELAY = 10.0      # seconds to wait before re-attaching after a drop
_RESCAN_INTERVAL = 60.0      # how often the supervisor reconciles the camera set
_DEDUPE_WINDOW = 8.0         # ignore the same plate re-fired within this window
_MAX_BUFFER = 512 * 1024     # reset the parse buffer if it grows unbounded

# device_id -> listener task
_tasks: dict[int, asyncio.Task] = {}
_supervisor_task: asyncio.Task | None = None
# (device_id, plate) -> monotonic timestamp of last handling
_last_seen: dict[tuple[int, str], float] = {}


def _find_plate_number(obj) -> str | None:
    """Recursively search a parsed Dahua event for a non-empty PlateNumber."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "PlateNumber" and isinstance(value, str) and value.strip():
                return value.strip()
            found = _find_plate_number(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_plate_number(item)
            if found:
                return found
    return None


def _extract_event(buffer: str) -> tuple[dict | None, int]:
    """Pull the first complete ``data={...}`` JSON object out of ``buffer``.

    Returns ``(obj, consumed)`` — ``consumed`` is the index the caller should
    trim the buffer to. ``(None, -1)`` means no complete object yet (wait for
    more bytes); ``obj`` may be None with ``consumed >= 0`` when a chunk was
    skipped (non-JSON payload or malformed object).
    """
    di = buffer.find("data=")
    if di < 0:
        return None, -1
    start = buffer.find("{", di)
    if start < 0:
        return None, -1  # JSON not arrived yet
    if start - di > 8:
        # this data= has no JSON of its own (heartbeat etc.) — skip past it
        return None, di + 5
    depth = 0
    for i in range(start, len(buffer)):
        ch = buffer[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(buffer[start : i + 1]), i + 1
                except Exception:
                    return None, i + 1  # malformed — drop and move on
    return None, -1  # object still incomplete


async def _handle_plate(device_id: int, raw_plate: str) -> None:
    """Decide on a recognised plate: check whitelist, open barrier, log."""
    from app.db.session import AsyncSessionLocal
    from app.models import Device, PlateAccessLog
    from app.services import barrier_service, plate_service

    plate = plate_service.normalize_plate(raw_plate)
    if not plate:
        return

    # Dedupe: TrafficJunction fires Start+Stop (and may repeat) for one pass.
    key = (device_id, plate)
    now = time.monotonic()
    last = _last_seen.get(key)
    if last is not None and now - last < _DEDUPE_WINDOW:
        return
    _last_seen[key] = now

    async with AsyncSessionLocal() as db:
        match = await plate_service.find_active_plate(db, plate)
        device = await db.get(Device, device_id)
        matched = match is not None

        action = "denied"
        if matched and device is not None:
            opened = await barrier_service.open_barrier(device)
            action = "opened" if opened else "open_failed"

        db.add(
            PlateAccessLog(
                device_id=device_id,
                plate=plate,
                plate_raw=raw_plate[:32],
                matched=matched,
                whitelist_id=match.id if match else None,
                action=action,
            )
        )
        await db.commit()
        owner = match.owner_name if match else None

    payload = {
        "device_id": device_id,
        "plate": plate,
        "matched": matched,
        "granted": matched,
        "action": action,
        "owner": owner,
    }
    # Local SSE (admin UI signalling).
    await event_bus.publish("plate_recognized", payload)
    # Cloud relay (mobile signalling) — best-effort, skip if bridge is down.
    try:
        from app.cloud.bridge import cloud_bridge

        await cloud_bridge.send_event("plate_recognized", payload)
    except Exception as exc:
        logger.warning("anpr_cloud_publish_failed", error=str(exc))

    logger.info(
        "anpr_plate", device_id=device_id, plate=plate, matched=matched, action=action
    )


async def _listen(device_id: int, host: str, user: str, pwd: str) -> None:
    """Maintain the long-poll event subscription to one camera, forever."""
    url = f"http://{host}/cgi-bin/eventManager.cgi"
    # heartbeat=N → camera sends a keep-alive every N seconds. Combined with a
    # finite read timeout below this turns a silently dead TCP connection into
    # a ReadTimeout we can recover from, instead of hanging forever.
    params = {
        "action": "attach",
        "codes": "[TrafficJunction]",
        "heartbeat": "10",
    }
    auth = httpx.DigestAuth(user, pwd)

    while True:
        try:
            # read timeout (45s) > heartbeat interval (10s): a healthy stream
            # never times out, a stale one raises ReadTimeout and reconnects.
            timeout = httpx.Timeout(10.0, read=45.0)
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                async with client.stream(
                    "GET", url, params=params, auth=auth
                ) as resp:
                    if resp.status_code != 200:
                        logger.warning(
                            "anpr_attach_bad_status",
                            device_id=device_id,
                            status=resp.status_code,
                        )
                        await asyncio.sleep(_RECONNECT_DELAY)
                        continue
                    logger.info("anpr_listening", device_id=device_id, host=host)
                    buffer = ""
                    async for chunk in resp.aiter_bytes():
                        buffer += chunk.decode("utf-8", "ignore")
                        while True:
                            obj, consumed = _extract_event(buffer)
                            if consumed < 0:
                                break
                            buffer = buffer[consumed:]
                            if obj is not None:
                                plate = _find_plate_number(obj)
                                if plate:
                                    asyncio.create_task(
                                        _handle_plate(device_id, plate)
                                    )
                        if len(buffer) > _MAX_BUFFER:
                            buffer = ""
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "anpr_listen_error", device_id=device_id, error=str(exc)
            )
        await asyncio.sleep(_RECONNECT_DELAY)


async def _reconcile() -> None:
    """Sync listener tasks with the current set of anpr_enabled cameras."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models import Device
    from app.services.barrier_service import camera_credentials

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Device).where(
                    Device.anpr_enabled == True,  # noqa: E712
                    Device.enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()
        cameras = {
            d.id: (d.ip_address, camera_credentials(d))
            for d in rows
            if d.ip_address
        }

    # Stop listeners for cameras that are gone or whose task died.
    for device_id in list(_tasks):
        if device_id not in cameras or _tasks[device_id].done():
            _tasks[device_id].cancel()
            del _tasks[device_id]

    # Start listeners for newly enabled cameras.
    for device_id, (host, (user, pwd)) in cameras.items():
        if device_id not in _tasks:
            _tasks[device_id] = asyncio.create_task(
                _listen(device_id, host, user, pwd)
            )
            logger.info("anpr_camera_started", device_id=device_id, host=host)


async def _supervise() -> None:
    while True:
        try:
            await _reconcile()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("anpr_supervisor_error", error=str(exc))
        await asyncio.sleep(_RESCAN_INTERVAL)


async def start() -> None:
    """Launch the ANPR supervisor — called once from the app lifespan."""
    global _supervisor_task
    if _supervisor_task is None or _supervisor_task.done():
        _supervisor_task = asyncio.create_task(_supervise())
        logger.info("anpr_service_started")
