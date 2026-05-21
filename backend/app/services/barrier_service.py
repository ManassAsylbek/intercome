"""Parking-barrier control for Dahua ITC ANPR cameras.

Opens the gate by pulsing the camera's ``AlarmOut[0]`` relay over the HTTP
CGI API:  setConfig AlarmOut[0].Mode=1  (close contact)  →  wait  →  Mode=0
(release).  The relay outputs were confirmed switchable over HTTP on the
ITC413 on 2026-05-21.

NOTE: this physically opens the barrier only once its open-control input is
wired to the camera's AlarmOut[0] dry contact. On the current install the
barrier sits on the camera's RS-485 bus instead, so until the wiring is
added open_barrier() will click the relay with no mechanical effect.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

# AlarmOut channel wired (or to be wired) to the barrier's open input.
BARRIER_RELAY_CHANNEL = 0
# How long the relay stays closed — long enough for the barrier controller
# to latch the open command, short enough to behave as a pulse.
_HOLD_SECONDS = 2.0


def camera_credentials(device) -> tuple[str, str]:
    """HTTP digest credentials for a Dahua camera.

    Dahua uses one account for both RTSP and the HTTP CGI API, so the creds
    embedded in ``rtsp_url`` work for configManager.cgi too. Falls back to the
    device's unlock_username/password, then to ``admin`` with no password.
    """
    if device.rtsp_url:
        parsed = urlparse(device.rtsp_url)
        if parsed.username:
            return parsed.username, (parsed.password or "")
    return (device.unlock_username or "admin", device.unlock_password or "")


async def open_barrier(
    device,
    *,
    channel: int = BARRIER_RELAY_CHANNEL,
    hold_seconds: float = _HOLD_SECONDS,
) -> bool:
    """Pulse the camera's AlarmOut relay to open the barrier. Returns success."""
    host = device.ip_address
    if not host:
        logger.warning("barrier_open_no_host", device_id=device.id)
        return False

    user, pwd = camera_credentials(device)
    url = f"http://{host}/cgi-bin/configManager.cgi"
    auth = httpx.DigestAuth(user, pwd)

    def _params(mode: int) -> dict:
        return {"action": "setConfig", f"AlarmOut[{channel}].Mode": str(mode)}

    try:
        async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
            on = await client.get(url, params=_params(1), auth=auth)
            if on.status_code != 200 or "OK" not in on.text:
                logger.warning(
                    "barrier_relay_on_failed",
                    device_id=device.id,
                    status=on.status_code,
                )
                return False
            await asyncio.sleep(hold_seconds)
            await client.get(url, params=_params(0), auth=auth)
        logger.info("barrier_opened", device_id=device.id, channel=channel)
        return True
    except Exception as exc:
        logger.warning("barrier_open_error", device_id=device.id, error=str(exc))
        # Best-effort: never leave the relay latched closed.
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                await client.get(url, params=_params(0), auth=auth)
        except Exception:
            pass
        return False
