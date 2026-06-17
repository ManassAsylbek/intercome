"""Hikvision access driver — door stations / access devices over ISAPI.

Door open uses ISAPI ``PUT /ISAPI/AccessControl/RemoteControl/door/1`` with body
``<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>`` and HTTP Digest auth —
NOT the generic GET/POST unlock_url path, hence its own driver. Device admin creds
come from the device's rtsp_url (embedded user:pass) → unlock_username/password →
admin/'' (mirrors the Dahua camera-credential convention). Video is handled
separately by go2rtc (RTSP); face/QR access events would come from the ISAPI
alertStream (``GET /ISAPI/Event/notification/alertStream``) — not implemented yet.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger
from app.drivers.base import AccessDriver, unsupported

if TYPE_CHECKING:
    from app.models import Device

logger = get_logger(__name__)

#: ISAPI door-open. Door index 1 (single-door stations like DS-KD9203).
_DOOR_OPEN_URL = "http://{host}:{port}/ISAPI/AccessControl/RemoteControl/door/1"
_DOOR_OPEN_BODY = "<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>"


def _admin_credentials(device: "Device") -> tuple[str, str]:
    """Device admin user/pass for ISAPI: from rtsp_url creds → unlock_* → admin/''."""
    if device.rtsp_url:
        parsed = urlparse(device.rtsp_url)
        if parsed.username:
            return parsed.username, parsed.password or ""
    if device.unlock_username:
        return device.unlock_username, device.unlock_password or ""
    return "admin", ""


class HikvisionDriver(AccessDriver):
    vendor = "hikvision"

    def capabilities(self) -> set[str]:
        # Door open via ISAPI. Barrier / event-stream / face-enroll come later.
        return {"open_door"}

    async def open(self, device: "Device", *, kind: str = "door", db=None, actor: str = "system"):
        from app.schemas import ActionResult  # lazy: avoid pulling schemas at import

        if kind != "door":
            return unsupported(f"open_{kind}", "hikvision")
        if not device.unlock_enabled:
            return ActionResult(success=False, message="Unlock not enabled for this device")
        if not device.ip_address:
            return ActionResult(success=False, message="Hikvision: no ip_address configured")

        user, pwd = _admin_credentials(device)
        url = _DOOR_OPEN_URL.format(host=device.ip_address, port=device.web_port or 80)
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
                resp = await client.put(
                    url,
                    content=_DOOR_OPEN_BODY,
                    headers={"Content-Type": "application/xml"},
                    auth=httpx.DigestAuth(user, pwd),
                )
        except Exception as exc:  # connect/timeout/etc — never crash the open path
            logger.warning("hikvision_unlock_error", device_id=device.id, error=str(exc))
            return ActionResult(
                success=False,
                message=f"Hikvision unlock error: {exc}",
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )

        latency_ms = round((time.monotonic() - start) * 1000, 2)
        # Hikvision: <ResponseStatus><statusCode>1</statusCode><statusString>OK</statusString>
        success = resp.status_code == 200 and (
            "<statusCode>1" in resp.text or "statusString>OK" in resp.text
        )

        if db:
            from app.models import ActivityAction, ActivityLog

            db.add(ActivityLog(
                action=ActivityAction.UNLOCK_TEST,
                actor=actor,
                device_id=device.id,
                detail=f"Hikvision ISAPI door/1 open | status={resp.status_code}",
                success=success,
            ))
            await db.flush()

        logger.info(
            "hikvision_unlock",
            device_id=device.id,
            device_name=device.name,
            status_code=resp.status_code,
            success=success,
            latency_ms=latency_ms,
        )
        return ActionResult(
            success=success,
            message="OK" if success else f"Hikvision unlock failed (HTTP {resp.status_code})",
            detail=resp.text[:300] if resp.text else None,
            latency_ms=latency_ms,
        )
