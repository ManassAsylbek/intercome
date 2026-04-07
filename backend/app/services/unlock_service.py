"""HTTP unlock service - sends unlock requests to door station devices."""

from __future__ import annotations

import time
from typing import Optional

import httpx

from app.core.logging import get_logger
from app.models import ActivityAction, Device, UnlockMethod
from app.schemas import ActionResult

logger = get_logger(__name__)


async def test_unlock(
    device: Device,
    db=None,
    actor: str = "system",
) -> ActionResult:
    """
    Send an HTTP unlock request to the device and return the result.
    Supports HTTP GET and HTTP POST methods.
    """
    if not device.unlock_enabled:
        return ActionResult(success=False, message="Unlock not enabled for this device")

    if device.unlock_method == UnlockMethod.NONE:
        return ActionResult(success=False, message="No unlock method configured")

    if not device.unlock_url:
        return ActionResult(success=False, message="No unlock URL configured")

    start = time.monotonic()
    try:
        auth = None
        if device.unlock_username and device.unlock_password:
            auth = httpx.BasicAuth(device.unlock_username, device.unlock_password)

        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            if device.unlock_method == UnlockMethod.HTTP_GET:
                response = await client.get(device.unlock_url, auth=auth)
            elif device.unlock_method == UnlockMethod.HTTP_POST:
                response = await client.post(device.unlock_url, auth=auth)
            else:
                return ActionResult(
                    success=False, message=f"Unsupported unlock method: {device.unlock_method}"
                )

        latency_ms = (time.monotonic() - start) * 1000
        success = response.status_code < 400

        if db:
            from app.models import ActivityLog

            log = ActivityLog(
                action=ActivityAction.UNLOCK_TEST,
                actor=actor,
                device_id=device.id,
                detail=f"HTTP {device.unlock_method.value} → {device.unlock_url} | status={response.status_code}",
                success=success,
            )
            db.add(log)
            await db.flush()

        logger.info(
            "unlock_test",
            device_id=device.id,
            device_name=device.name,
            url=device.unlock_url,
            status_code=response.status_code,
            latency_ms=round(latency_ms, 2),
        )
        return ActionResult(
            success=success,
            message=f"HTTP {response.status_code}" if success else f"HTTP error {response.status_code}",
            detail=response.text[:500] if response.text else None,
            latency_ms=round(latency_ms, 2),
        )

    except httpx.ConnectError as e:
        logger.warning("unlock_connect_error", device_id=device.id, error=str(e))
        return ActionResult(success=False, message="Connection refused", detail=str(e))
    except httpx.TimeoutException:
        return ActionResult(success=False, message="Connection timed out")
    except Exception as e:
        logger.exception("unlock_unexpected_error", device_id=device.id)
        return ActionResult(success=False, message="Unexpected error", detail=str(e))
