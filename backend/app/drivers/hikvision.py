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

import asyncio
import base64
import hashlib
import json
import os
import re
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

#: alertStream audit (face recognition → door_unlocked). subEventType 75 = face
#: access GRANTED (carries employeeNoString); 76 = denied. Stream is multipart/mixed
#: with literal boundary "MIME_boundary", JSON parts, plus videoloss keepalives.
_ALERTSTREAM_PATH = "/ISAPI/Event/notification/alertStream"
_ALERTSTREAM_BOUNDARY = b"--MIME_boundary"
_RECONNECT_DELAY = 10.0
_MAX_BUFFER = 524288  # 512KB guard against unbounded growth on a never-boundaried part
#: On (re)connect the device REPLAYS recent backlog immediately. We suppress that
#: burst clock-independently: on the FIRST connect, ignore grants for the first
#: _WARMUP_S seconds (the device clock is often badly skewed from ours, so an
#: absolute-time "is it old?" check is unreliable). serialNo dedupe handles replays
#: on later reconnects.
_WARMUP_S = 8.0
#: dedupe (device_id, serialNo) — module-level so it survives listener respawns.
_seen_grants: set[tuple[int, object]] = set()
#: device_ids that already passed their first-connect warmup (process lifetime).
_warmed: set[int] = set()


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


def _digest_header(user: str, pwd: str, method: str, uri: str, www_authenticate: str) -> str:
    """Build an HTTP Digest Authorization header from a WWW-Authenticate challenge.

    httpx.DigestAuth works for normal ISAPI calls but misbehaves on the long-poll
    alertStream (returns 401/500), so the event listener does the digest handshake
    by hand (qop=auth, MD5) exactly like curl --digest."""
    p = dict(re.findall(r'(\w+)="?([^",]*)"?', www_authenticate))
    realm, nonce = p.get("realm", ""), p.get("nonce", "")
    qop, opaque = p.get("qop", "auth"), p.get("opaque", "")
    ha1 = hashlib.md5(f"{user}:{realm}:{pwd}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    nc, cnonce = "00000001", hashlib.md5(os.urandom(8)).hexdigest()[:16]
    resp = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
    h = (
        f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
        f'response="{resp}", qop={qop}, nc={nc}, cnonce="{cnonce}"'
    )
    if opaque:
        h += f', opaque="{opaque}"'
    return h


class HikvisionDriver(AccessDriver):
    vendor = "hikvision"

    def capabilities(self) -> set[str]:
        # Door open + on-device face credential management + access-event audit.
        return {"open_door", "enroll_face", "delete_face", "event_stream"}

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
        # Guard before the synchronous decode: an oversized/malformed payload must
        # not block the bridge event loop. A face JPEG is well under this (~70KB).
        if len(image_b64) > 10_000_000:
            return {"success": False, "message": "image_b64 too large (>10MB)"}
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

    async def run_event_stream(self, device: "Device") -> None:
        """Long-poll the ISAPI alertStream and emit ``door_unlocked`` on face grants.

        Mirrors ``anpr_service._listen``: infinite reconnect loop, a finite read
        timeout (> the device heartbeat) turns a dead TCP into a recoverable
        ReadTimeout, and CancelledError is re-raised so the supervisor can stop it.

        The stream is multipart/mixed (boundary ``MIME_boundary``) of JSON parts.
        A face access-GRANT is ``AccessControllerEvent.majorEventType==5`` and
        ``subEventType==75`` (76 = denied; videoloss parts are keepalives). The
        device REPLAYS recent backlog on every (re)connect, so we dedupe by
        serialNo AND skip grants older than ``_BACKLOG_GRACE_S`` to avoid
        re-emitting old opens after a restart.
        """
        if not device.ip_address:
            return
        user, pwd = _admin_credentials(device)
        url = f"http://{device.ip_address}:{device.web_port or 80}{_ALERTSTREAM_PATH}"

        while True:
            try:
                timeout = httpx.Timeout(10.0, read=45.0)
                async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                    # Manual digest: httpx.DigestAuth fails on this long-poll stream
                    # (401/500) though it works for normal ISAPI calls. Fetch the 401
                    # challenge, then open the stream with a computed Authorization.
                    challenge = await client.get(url)
                    www = challenge.headers.get("WWW-Authenticate", "")
                    if challenge.status_code != 401 or not www:
                        logger.warning(
                            "hik_alertstream_no_challenge",
                            device_id=device.id, status=challenge.status_code,
                        )
                        await asyncio.sleep(_RECONNECT_DELAY)
                        continue
                    authz = _digest_header(user, pwd, "GET", _ALERTSTREAM_PATH, www)
                    async with client.stream(
                        "GET", url, headers={"Authorization": authz}
                    ) as resp:
                        if resp.status_code != 200:
                            logger.warning(
                                "hik_alertstream_bad_status",
                                device_id=device.id, status=resp.status_code,
                            )
                            await asyncio.sleep(_RECONNECT_DELAY)
                            continue
                        logger.info(
                            "hik_alertstream_listening", device_id=device.id, host=device.ip_address
                        )
                        # First connect of this process: suppress the replayed
                        # backlog burst for a short window (clock-independent).
                        first = device.id not in _warmed
                        _warmed.add(device.id)
                        suppress_until = (time.monotonic() + _WARMUP_S) if first else 0.0
                        buf = b""
                        async for chunk in resp.aiter_bytes():
                            buf += chunk
                            # split on boundary; the last segment may be a partial part
                            segments = buf.split(_ALERTSTREAM_BOUNDARY)
                            buf = segments.pop()
                            for seg in segments:
                                await self._handle_alertstream_segment(device, seg, suppress_until)
                            if len(buf) > _MAX_BUFFER:  # never-boundaried garbage/binary
                                buf = b""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("hik_alertstream_error", device_id=device.id, error=str(exc))
            await asyncio.sleep(_RECONNECT_DELAY)

    async def _handle_alertstream_segment(
        self, device: "Device", seg: bytes, suppress_until: float
    ) -> None:
        """Parse one multipart segment; emit door_unlocked iff it is a fresh face grant.

        ``suppress_until`` is a ``time.monotonic()`` deadline: grants seen before it
        are treated as replayed backlog (first-connect warmup) — recorded as seen but
        not emitted. serialNo dedupe suppresses replays on later reconnects."""
        i = seg.find(b"{")
        if i < 0:
            return
        try:
            obj, _ = json.JSONDecoder().raw_decode(seg[i:].decode("utf-8", "replace"))
        except Exception:
            return
        if not isinstance(obj, dict) or obj.get("eventType") != "AccessControllerEvent":
            return  # videoloss/inactive keepalive or non-access part
        ace = obj.get("AccessControllerEvent") or {}
        if ace.get("majorEventType") != 5 or ace.get("subEventType") != 75:
            return  # not a face access-GRANT (76 = denied; door-state codes; ...)

        serial = ace.get("serialNo")
        key = (device.id, serial)
        if serial is not None and key in _seen_grants:
            return  # already handled (stream replays backlog on reconnect)
        if serial is not None:
            if len(_seen_grants) > 2000:
                _seen_grants.clear()
            _seen_grants.add(key)

        if time.monotonic() < suppress_until:
            return  # first-connect backlog burst — recorded as seen, not emitted

        employee = ace.get("employeeNoString") or obj.get("employeeNoString") or ""
        name = ace.get("name") or obj.get("name") or None
        ts = obj.get("dateTime")  # device-clock timestamp (may be skewed; informational)
        await self._emit(
            device,
            "door_unlocked",
            {
                "actor": employee or "unknown",
                "method": "face",
                "person_id": employee or None,
                "name": name,
                "ts": ts,
            },
        )
        logger.info(
            "hik_face_door_unlocked", device_id=device.id, person_id=employee or None, ts=ts
        )
