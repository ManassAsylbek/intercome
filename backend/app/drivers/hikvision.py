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

import base64
import json
import time
from typing import TYPE_CHECKING, Optional
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
#: On-device face library (GET /ISAPI/Intelligent/FDLib?format=json → FDID "1", blackFD).
_FACE_LIB_TYPE = "blackFD"
_FACE_FDID = "1"


def _admin_credentials(device: "Device") -> tuple[str, str]:
    """Device admin user/pass for ISAPI: from rtsp_url creds → unlock_* → admin/''."""
    if device.rtsp_url:
        parsed = urlparse(device.rtsp_url)
        if parsed.username:
            return parsed.username, parsed.password or ""
    if device.unlock_username:
        return device.unlock_username, device.unlock_password or ""
    return "admin", ""


def _isapi_json_ok(resp) -> bool:
    """Hikvision JSON ack success: HTTP 200 + statusCode == 1."""
    if resp.status_code != 200:
        return False
    try:
        return resp.json().get("statusCode") == 1
    except Exception:
        return False


class HikvisionDriver(AccessDriver):
    vendor = "hikvision"

    def capabilities(self) -> set[str]:
        # Door open + on-device face credential management via ISAPI.
        # Barrier / QR / event-stream come later.
        return {"open_door", "enroll_face", "delete_face"}

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

    async def enroll_face(
        self,
        device: "Device",
        *,
        person_id: str,
        image_b64: Optional[str] = None,
        name: Optional[str] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
    ) -> dict:
        """Enroll a face so the door station recognizes it LOCALLY and opens.

        Two ISAPI writes (Digest): (1) create the person — UserInfo/Record with
        ``doorRight:"1"`` (RightPlan is finicky; doorRight grants door 1) and a
        Valid window; (2) upload the photo to the on-device face library —
        FaceDataRecord multipart (JSON meta part + JPEG). Recognition then opens
        the door with no cloud round-trip. Best-effort: never raises; returns an
        ack dict. ``image_b64`` is the cloud-supplied face JPEG (base64).
        """
        if not device.ip_address:
            return {"success": False, "message": "Hikvision: no ip_address configured"}
        if "_" in person_id:
            # firmware bug: an employeeNo with '_' enrolls but can't be deleted later
            return {"success": False, "message": "person_id must not contain '_'"}
        if not image_b64:
            return {"success": False, "message": "image_b64 (face photo) is required"}
        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception as exc:
            return {"success": False, "message": f"bad image_b64: {exc}"}

        user, pwd = _admin_credentials(device)
        base_url = f"http://{device.ip_address}:{device.web_port or 80}"
        auth = httpx.DigestAuth(user, pwd)
        user_body = {
            "UserInfo": {
                "employeeNo": person_id,
                "name": name or person_id,
                "userType": "normal",
                "doorRight": "1",
                "Valid": {
                    "enable": True,
                    "beginTime": valid_from or "2020-01-01T00:00:00",
                    "endTime": valid_to or "2037-12-31T23:59:59",
                    "timeType": "local",
                },
            }
        }
        face_meta = json.dumps(
            {"faceLibType": _FACE_LIB_TYPE, "FDID": _FACE_FDID, "FPID": person_id}
        )
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
                r1 = await client.post(
                    f"{base_url}/ISAPI/AccessControl/UserInfo/Record?format=json",
                    json=user_body, auth=auth,
                )
                # already-exists is fine — we still (re)bind the face below
                if not _isapi_json_ok(r1) and "exist" not in r1.text.lower():
                    logger.warning(
                        "hikvision_face_user_failed", device_id=device.id,
                        person_id=person_id, status_code=r1.status_code, body=r1.text[:200],
                    )
                    return {
                        "success": False,
                        "message": f"UserInfo create failed (HTTP {r1.status_code})",
                        "detail": r1.text[:300], "person_id": person_id,
                    }
                r2 = await client.post(
                    f"{base_url}/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json",
                    files={
                        "FaceDataRecord": (None, face_meta, "application/json"),
                        "FaceImage": ("face.jpg", image_bytes, "image/jpeg"),
                    },
                    auth=auth,
                )
        except Exception as exc:  # connect/timeout/etc — never crash
            logger.warning("hikvision_face_enroll_error", device_id=device.id, error=str(exc))
            return {
                "success": False, "message": f"Hikvision enroll_face error: {exc}",
                "person_id": person_id,
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }

        latency_ms = round((time.monotonic() - start) * 1000, 2)
        ok = _isapi_json_ok(r2)
        logger.info(
            "hikvision_face_enroll", device_id=device.id, device_name=device.name,
            person_id=person_id, status_code=r2.status_code, success=ok, latency_ms=latency_ms,
        )
        return {
            "success": ok,
            "message": "OK" if ok else f"face modeling failed (HTTP {r2.status_code})",
            "detail": r2.text[:300] if r2.text else None,
            "person_id": person_id,
            "device_id": device.id,
            "device_name": device.name,
            "latency_ms": latency_ms,
        }

    async def delete_face(self, device: "Device", *, person_id: str) -> dict:
        """Revoke a face by deleting the person (UserInfo/Delete) — this removes the
        bound face too (verified). Idempotent: a missing person returns success."""
        if not device.ip_address:
            return {"success": False, "message": "Hikvision: no ip_address configured"}
        if "_" in person_id:
            return {"success": False, "message": "person_id must not contain '_'"}
        user, pwd = _admin_credentials(device)
        url = (
            f"http://{device.ip_address}:{device.web_port or 80}"
            "/ISAPI/AccessControl/UserInfo/Delete?format=json"
        )
        body = {"UserInfoDelCond": {"EmployeeNoList": [{"employeeNo": person_id}]}}
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=12.0, verify=False) as client:
                resp = await client.put(url, json=body, auth=httpx.DigestAuth(user, pwd))
        except Exception as exc:
            logger.warning("hikvision_face_delete_error", device_id=device.id, error=str(exc))
            return {
                "success": False, "message": f"Hikvision delete_face error: {exc}",
                "person_id": person_id,
            }
        ok = _isapi_json_ok(resp)
        logger.info(
            "hikvision_face_delete", device_id=device.id, person_id=person_id,
            status_code=resp.status_code, success=ok,
            latency_ms=round((time.monotonic() - start) * 1000, 2),
        )
        return {
            "success": ok,
            "message": "OK" if ok else f"delete failed (HTTP {resp.status_code})",
            "detail": resp.text[:300] if resp.text else None,
            "person_id": person_id,
        }
