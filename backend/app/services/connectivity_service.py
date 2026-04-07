"""Connectivity check service - verifies a device is reachable on the network."""

from __future__ import annotations

import asyncio
import time

import httpx

from app.core.logging import get_logger
from app.models import ActivityAction, Device
from app.schemas import ActionResult

logger = get_logger(__name__)


async def _tcp_ping(host: str, port: int, timeout: float = 5.0) -> tuple[bool, float]:
    """Try to open a TCP connection to host:port. Returns (reachable, latency_ms)."""
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        latency_ms = (time.monotonic() - start) * 1000
        return True, round(latency_ms, 2)
    except (asyncio.TimeoutError, OSError):
        return False, -1.0


async def test_connection(device: Device, db=None, actor: str = "system") -> ActionResult:
    """
    Attempt to reach a device.
    Strategy:
      1. If the device has a web port: try HTTP GET to http://ip:port
      2. Else: TCP ping to port 80
    Updates device.is_online and device.last_seen in the DB if db is provided.
    """
    from datetime import datetime, timezone

    if not device.ip_address:
        return ActionResult(success=False, message="No IP address configured")

    port = device.web_port or 80
    start = time.monotonic()

    # First try HTTP
    try:
        url = f"http://{device.ip_address}:{port}"
        auth = None
        if device.unlock_username and device.unlock_password:
            auth = httpx.BasicAuth(device.unlock_username, device.unlock_password)

        async with httpx.AsyncClient(timeout=6.0, verify=False) as client:
            response = await client.get(url, auth=auth, follow_redirects=True)

        latency_ms = (time.monotonic() - start) * 1000
        success = response.status_code < 500

        if db:
            from app.models import ActivityLog
            from sqlalchemy import update as sqlupdate
            from app.models import Device as DeviceModel

            device.is_online = success
            device.last_seen = datetime.now(timezone.utc)

            log = ActivityLog(
                action=ActivityAction.CONNECTION_TEST,
                actor=actor,
                device_id=device.id,
                detail=f"HTTP GET {url} → {response.status_code} ({round(latency_ms,1)} ms)",
                success=success,
            )
            db.add(log)
            await db.flush()

        logger.info(
            "connection_test_http",
            device_id=device.id,
            url=url,
            status=response.status_code,
            latency_ms=round(latency_ms, 2),
        )
        return ActionResult(
            success=success,
            message=f"Device responded with HTTP {response.status_code}",
            detail=f"URL: {url}",
            latency_ms=round(latency_ms, 2),
        )

    except (httpx.ConnectError, httpx.TimeoutException):
        pass
    except Exception as e:
        logger.warning("connection_test_http_error", device_id=device.id, error=str(e))

    # Fallback: TCP ping
    reachable, latency_ms = await _tcp_ping(device.ip_address, port)

    if db:
        from datetime import datetime, timezone
        from app.models import ActivityLog

        device.is_online = reachable
        device.last_seen = datetime.now(timezone.utc) if reachable else device.last_seen

        log = ActivityLog(
            action=ActivityAction.CONNECTION_TEST,
            actor=actor,
            device_id=device.id,
            detail=f"TCP ping {device.ip_address}:{port} → {'reachable' if reachable else 'unreachable'}",
            success=reachable,
        )
        db.add(log)
        await db.flush()

    return ActionResult(
        success=reachable,
        message="Device is reachable (TCP)" if reachable else "Device is unreachable",
        detail=f"{device.ip_address}:{port}",
        latency_ms=latency_ms if latency_ms >= 0 else None,
    )
