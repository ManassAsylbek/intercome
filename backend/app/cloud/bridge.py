"""
Cloud WebSocket Bridge — outgoing persistent WebSocket connection to the cloud.

Protocol (LOCAL_BRIDGE_SPEC.md §2-§4):
  Local → Cloud: hello, call_started, call_ended, call_answered,
                 device_snapshot, device_status, door_unlocked,
                 system_health, ack
  Cloud → Local: hello_ack, provision_webrtc_endpoint,
                 revoke_webrtc_endpoint, set_apartment_monitors,
                 unlock_door, reject_call, ping

Messages format:
  { "type": "<event>", "ts": "...", "data": { ... } }

Commands from cloud always contain "cmd_id"; we ACK with:
  { "type": "ack", "cmd_id": "...", "ok": true/false, "result"/{error}: ... }

Reconnect: exponential backoff 1s→60s ±20% jitter.
After reconnect: full snapshot sent automatically.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import random
import time
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, InvalidURI, WebSocketException
except ImportError:
    websockets = None  # type: ignore[assignment]

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jitter(base: float) -> float:
    """±20% jitter."""
    return base * (0.8 + random.random() * 0.4)


class CloudBridge:
    """Persistent outgoing WebSocket connection to the cloud device_service."""

    def __init__(self) -> None:
        self._ws = None
        self._connected = False
        self._task: Optional[asyncio.Task] = None
        self._bridge_id: Optional[int] = None
        self._company_id: Optional[int] = None
        # Queue for messages to send; filled by event handlers and command ACKs.
        self._send_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch background reconnect loop."""
        if not settings.cloud_ws_url or not settings.cloud_bridge_token:
            logger.info("cloud_bridge_disabled", reason="CLOUD_WS_URL or CLOUD_BRIDGE_TOKEN not set")
            return
        if websockets is None:
            logger.warning("cloud_bridge_disabled", reason="websockets library not installed")
            return
        self._task = asyncio.create_task(self._reconnect_loop(), name="cloud-bridge")
        logger.info("cloud_bridge_started", url=settings.cloud_ws_url)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send_event(self, event_type: str, data: dict) -> None:
        """Enqueue an outgoing event (non-blocking; drops when full)."""
        msg = json.dumps({"type": event_type, "ts": _utcnow(), "data": data})
        try:
            self._send_queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("cloud_send_queue_full_drop", event_type=event_type)

    async def send_ack(self, cmd_id: str, ok: bool, result: dict | None = None, error: str | None = None) -> None:
        payload: dict[str, Any] = {"type": "ack", "cmd_id": cmd_id, "ok": ok}
        if ok:
            payload["result"] = result or {}
        else:
            payload["error"] = error or "unknown error"
        msg = json.dumps(payload)
        try:
            self._send_queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("cloud_ack_queue_full_drop", cmd_id=cmd_id)

    # ──────────────────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────────────────

    async def _reconnect_loop(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._run_session()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, OSError, WebSocketException, InvalidURI) as exc:
                logger.warning("cloud_ws_disconnected", error=str(exc), retry_in=round(backoff, 1))
            except Exception as exc:
                logger.error("cloud_ws_unexpected_error", error=str(exc))
            finally:
                self._connected = False
                self._ws = None

            delay = _jitter(backoff)
            logger.info("cloud_ws_reconnecting", in_seconds=round(delay, 1))
            await asyncio.sleep(delay)
            backoff = min(backoff * 2, 60.0)

    async def _run_session(self) -> None:
        url = settings.cloud_ws_url
        logger.info("cloud_ws_connecting", url=url)

        async with websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {settings.cloud_bridge_token}"},
            ping_interval=20,
            ping_timeout=15,
            close_timeout=10,
            max_size=10 * 1024 * 1024,
        ) as ws:
            self._ws = ws

            # ── Handshake ────────────────────────────────────────────────────
            hello = {
                "type": "hello",
                "bridge_token": settings.cloud_bridge_token,
                "version": "1.2.0",
                "asterisk_version": await self._get_asterisk_version(),
                "media_config": _build_media_config(),
            }
            await ws.send(json.dumps(hello))

            raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
            ack = json.loads(raw)
            if ack.get("type") != "hello_ack":
                logger.error("cloud_ws_handshake_failed", response=ack)
                return

            self._bridge_id = ack.get("bridge_id")
            self._company_id = ack.get("company_id")
            self._connected = True
            logger.info("cloud_ws_connected", bridge_id=self._bridge_id, company_id=self._company_id)

            # After reconnect — send full snapshot immediately
            await self._send_full_snapshot()

            # ── Main loop: rx commands + tx events ──────────────────────────
            recv_task = asyncio.create_task(self._recv_loop(ws))
            send_task = asyncio.create_task(self._send_loop(ws))
            health_task = asyncio.create_task(self._health_loop())
            media_cfg_task = asyncio.create_task(self._media_config_loop())

            done, pending = await asyncio.wait(
                [recv_task, send_task, health_task, media_cfg_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            # Re-raise exception from completed task so reconnect loop fires
            for t in done:
                if t.exception():
                    raise t.exception()  # type: ignore[misc]

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("cloud_ws_invalid_json")
                continue
            await self._dispatch_command(msg)

    async def _send_loop(self, ws) -> None:
        while True:
            msg = await self._send_queue.get()
            await ws.send(msg)

    async def _health_loop(self) -> None:
        """Send system_health every 30 s."""
        while True:
            await asyncio.sleep(30)
            await self.send_event("system_health", await self._collect_health())

    async def _media_config_loop(self) -> None:
        """Re-send media_config every 10 min so cloud always has fresh TURN creds."""
        while True:
            await asyncio.sleep(600)  # 10 min < 15 min TTL
            await self.send_event("media_config", _build_media_config())
            logger.debug("cloud_media_config_refreshed")

    # ──────────────────────────────────────────────────────────────────────────
    # Command dispatcher
    # ──────────────────────────────────────────────────────────────────────────

    async def _dispatch_command(self, msg: dict) -> None:
        cmd_type = msg.get("type", "")
        cmd_id = msg.get("cmd_id")
        data = msg.get("data", {})

        logger.info("cloud_ws_cmd_received", type=cmd_type, cmd_id=cmd_id)

        handler = {
            "ping": self._cmd_ping,
            "provision_webrtc_endpoint": self._cmd_provision_endpoint,
            "revoke_webrtc_endpoint": self._cmd_revoke_endpoint,
            "set_apartment_monitors": self._cmd_set_monitors,
            "unlock_door": self._cmd_unlock_door,
            "reject_call": self._cmd_reject_call,
            "answer_call": self._cmd_answer_call,
        }.get(cmd_type)

        if handler is None:
            logger.warning("cloud_ws_unknown_cmd", type=cmd_type)
            if cmd_id:
                await self.send_ack(cmd_id, False, error=f"unknown command: {cmd_type}")
            return

        try:
            result = await handler(data, cmd_id=cmd_id)
            if cmd_id:
                await self.send_ack(cmd_id, True, result=result or {})
        except Exception as exc:
            logger.error("cloud_ws_cmd_error", type=cmd_type, error=str(exc))
            if cmd_id:
                await self.send_ack(cmd_id, False, error=str(exc))

    # ──────────────────────────────────────────────────────────────────────────
    # Command handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _cmd_ping(self, data: dict, **_) -> dict:
        return {"pong": True, "ts": _utcnow()}

    async def _cmd_provision_endpoint(self, data: dict, **_) -> dict:
        from app.db.session import AsyncSessionLocal
        from app.models import WebrtcEndpoint
        from app.services.sip_service import upsert_webrtc_conf

        extension = data["extension"]
        password = data["password"]
        apartment_code = data.get("apartment_code")

        # Upsert in DB
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(WebrtcEndpoint).where(WebrtcEndpoint.extension == extension))
            ep = result.scalar_one_or_none()
            if ep:
                ep.password = password
            else:
                ep = WebrtcEndpoint(extension=extension, password=password)
                db.add(ep)
            await db.commit()

        # Write pjsip_webrtc.conf
        ok, msg = await upsert_webrtc_conf(extension, password)
        if not ok:
            raise RuntimeError(f"pjsip write failed: {msg}")

        # Add to apartment monitor group if apartment_code given
        if apartment_code:
            await self._add_monitor_to_apartment(apartment_code, extension)

        public_host = settings.public_bridge_host or settings.server_ip
        sip_ws_url = settings.sip_ws_url or (
            f"wss://{public_host}/asterisk/ws" if public_host else f"ws://{settings.server_ip}:8088/ws"
        )
        sip_domain = settings.sip_domain or public_host or settings.server_ip
        return {
            "extension": extension,
            "sip_ws_url": sip_ws_url,
            "sip_domain": sip_domain,
            "stun": settings.intercom_stun_url,
        }

    async def _cmd_revoke_endpoint(self, data: dict, **_) -> dict:
        from app.db.session import AsyncSessionLocal
        from app.models import ApartmentMonitor, WebrtcEndpoint
        from app.services.sip_service import schedule_pjsip_reload
        from sqlalchemy import select

        extension = data["extension"]

        # Remove from DB
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(WebrtcEndpoint).where(WebrtcEndpoint.extension == extension))
            ep = result.scalar_one_or_none()
            if ep:
                await db.delete(ep)
            # Also remove from all apartment monitors
            await db.execute(
                ApartmentMonitor.__table__.delete().where(ApartmentMonitor.sip_account == extension)
            )
            await db.commit()

        # Rewrite pjsip_webrtc.conf without this extension
        from app.services.sip_service import regenerate_webrtc_conf_from_db
        await regenerate_webrtc_conf_from_db()

        # Rebuild dialplan for all apartments that had this monitor
        await self._rebuild_all_dialplan()

        return {"extension": extension, "revoked": True}

    async def _cmd_set_monitors(self, data: dict, **_) -> dict:
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment, ApartmentMonitor, WebrtcEndpoint
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        apartment_code = data["apartment_code"]
        monitors: list[str] = data.get("monitors", [])

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Apartment)
                .options(selectinload(Apartment.monitors))
                .where(Apartment.call_code == apartment_code)
            )
            apt = result.scalar_one_or_none()
            if not apt:
                raise ValueError(f"Apartment with call_code={apartment_code} not found")

            # Replace monitors (skip validation — cloud is authoritative)
            await db.execute(
                ApartmentMonitor.__table__.delete().where(ApartmentMonitor.apartment_id == apt.id)
            )
            for ext in monitors:
                db.add(ApartmentMonitor(apartment_id=apt.id, sip_account=ext, label=None))
            await db.commit()

        await self._rebuild_all_dialplan()
        return {"apartment_code": apartment_code, "monitors": monitors}

    async def _cmd_unlock_door(self, data: dict, **_) -> dict:
        """Unlock the panel that placed the active call (or one given by id).

        Returns a structured ack so cloud/Flutter can reason about failures:
            {success: bool, message: str, device_id?: int, device_name?: str,
             method?: str, latency_ms?: float, unlocked?: bool}

        Resolution order for the target panel:
          1. If ``device_local_id`` provided → use that device (must be
             unlock-enabled).
          2. Else, if there's an active call, find the device whose
             ``sip_account`` matches the call's caller — this is the panel
             that's currently ringing, which is what the user actually wants
             to open.
          3. Fallback: first unlock-enabled device in DB.
        """
        from app.db.session import AsyncSessionLocal
        from app.models import Device
        from app.services import unlock_service
        from app.services.call_store import call_store
        from sqlalchemy import select

        call_id = data.get("call_id")
        device_local_id = data.get("device_local_id")
        by_user_id = data.get("user_id")
        actor = f"cloud:user:{by_user_id}" if by_user_id else "cloud"

        async with AsyncSessionLocal() as db:
            door: Device | None = None

            if device_local_id:
                result = await db.execute(
                    select(Device).where(
                        Device.id == device_local_id, Device.unlock_enabled == True  # noqa: E712
                    )
                )
                door = result.scalar_one_or_none()
                if not door:
                    return {
                        "success": False,
                        "message": f"device_local_id={device_local_id} not found or unlock disabled",
                        "device_id": device_local_id,
                    }
            else:
                # Try to resolve the panel that's actually calling now.
                active = call_store.get_active()
                if active and active.caller and (not call_id or active.call_id == call_id):
                    result = await db.execute(
                        select(Device).where(
                            Device.sip_account == active.caller,
                            Device.unlock_enabled == True,  # noqa: E712
                        )
                    )
                    door = result.scalars().first()

                if not door:
                    # Fallback: first unlock-enabled device.
                    result = await db.execute(
                        select(Device).where(
                            Device.enabled == True, Device.unlock_enabled == True  # noqa: E712
                        )
                    )
                    door = result.scalars().first()

            if not door:
                return {
                    "success": False,
                    "message": "no unlock-enabled device available",
                    "device_id": None,
                }

            action = await unlock_service.test_unlock(door, db=db, actor=actor)
            await db.commit()

        response: dict = {
            "success": action.success,
            "message": action.message
            or ("OK" if action.success else "unlock failed (no detail from device)"),
            "device_id": door.id,
            "device_name": door.name,
            "method": door.unlock_method.value if door.unlock_method else None,
            "latency_ms": action.latency_ms,
        }

        if action.success:
            from app.events.bus import event_bus
            active = call_store.get_active()
            await event_bus.publish(
                "door_opened",
                {
                    "call_id": call_id or (active.call_id if active else None),
                    "device_id": door.id,
                    "by": "api",
                },
            )
            response["unlocked"] = True  # legacy/back-compat

        return response

    async def _cmd_reject_call(self, data: dict, **_) -> dict:
        """Hang up the panel's channel — propagates CANCEL to all Dial targets.

        Uses CoreShowChannels to find the actual panel channel name instead of
        guessing PJSIP/{caller}, since the SIP transport prefix may differ.
        """
        from app.ami.client import ami_client

        call_id = data.get("call_id")
        if not call_id:
            raise RuntimeError("call_id is required")

        chan = await _find_call_channel(call_id)
        if not chan:
            raise RuntimeError(f"Channel for call_id={call_id} not found")

        resp = await ami_client.send_action({
            "Action": "Hangup",
            "Channel": chan,
            "Cause": "21",  # Call rejected
        })
        if isinstance(resp, dict) and resp.get("Response") not in ("Success", None):
            raise RuntimeError(f"AMI Hangup failed: {resp.get('Message')}")
        logger.info("cloud_reject_call_hangup", call_id=call_id, channel=chan)
        return {"success": True, "call_id": call_id, "channel": chan}

    async def _cmd_answer_call(self, data: dict, **_) -> dict:
        """User answered in the cloud-side mobile/web client.

        Asterisk handles the actual media bridge automatically: it's already
        Dial()-ing the user's WebRTC endpoint, and the SIP.js client answers
        with 200 OK → Asterisk auto-bridges. The bridge's job here is only to:
          1. Verify the call is still active.
          2. Send call_answered upstream so the cloud cancels notifications
             on the user's other devices.
          3. Ack.
        """
        call_id = data.get("call_id")
        answered_by_sip = data.get("answered_by_sip")
        if not call_id:
            raise RuntimeError("call_id is required")

        chan = await _find_call_channel(call_id)
        if not chan:
            raise RuntimeError(f"Channel for call_id={call_id} not found")

        # Tell cloud to silence the ring on the user's other devices.
        await self.send_event("call_answered", {
            "call_id": call_id,
            "answered_by_sip": answered_by_sip,
        })
        logger.info("cloud_answer_call_ack", call_id=call_id, by=answered_by_sip)
        return {"success": True, "call_id": call_id, "channel": chan}

    # ──────────────────────────────────────────────────────────────────────────
    # Snapshot helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _send_full_snapshot(self) -> None:
        devices = await self._collect_devices()
        await self.send_event("device_snapshot", {"full": True, "devices": devices})

        # Also send current call state
        from app.services.call_store import call_store
        active = call_store.get_active()
        if active:
            await self.send_event("call_started", await _active_call_to_cloud(active))

        logger.info("cloud_ws_snapshot_sent", device_count=len(devices))

    async def _collect_devices(self) -> list[dict]:
        from app.db.session import AsyncSessionLocal
        from app.models import Device
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Device)
                .options(selectinload(Device.apartment))
                .where(Device.enabled == True)  # noqa: E712
            )
            devices = result.scalars().all()

            out = []
            for d in devices:
                out.append({
                    "local_id": d.id,
                    "name": d.name,
                    "device_type": _map_device_type(d.device_type.value if d.device_type else ""),
                    "ip_address": d.ip_address,
                    "mac_address": None,
                    "model": None,
                    "firmware_version": None,
                    "status": "online" if d.is_online else ("offline" if d.is_online is False else "unknown"),
                    "last_heartbeat_at": d.last_seen.strftime("%Y-%m-%dT%H:%M:%SZ") if d.last_seen else None,
                    "sip": {
                        "enabled": d.sip_enabled,
                        "account": d.sip_account,
                        "server": d.sip_server or settings.server_ip,
                        "port": d.sip_port or 5060,
                    } if d.sip_enabled else None,
                    "rtsp": _rtsp_block(d.id, d.rtsp_url) if d.rtsp_enabled and d.rtsp_url else None,
                    "unlock": {
                        "method": _map_unlock_method(d.unlock_method.value if d.unlock_method else "none"),
                        "url": d.unlock_url,
                    } if d.unlock_enabled else {"method": "none"},
                    "apartment_code": d.apartment.call_code if d.apartment else None,
                    "scope": {
                        "building_id": None,
                        "entrance_id": None,
                        "apartment_id": d.apartment_id,
                    },
                })
            return out

    async def _collect_health(self) -> dict:
        import shutil

        import psutil  # optional dep — skip if missing

        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
        except Exception:
            cpu = mem = disk = 0.0

        from app.ami.client import ami_client
        return {
            "asterisk_running": ami_client.is_connected,
            "asterisk_uptime_seconds": None,
            "active_channels": 1 if _has_active_call() else 0,
            "registered_endpoints": None,
            "cpu_percent": cpu,
            "memory_percent": mem,
            "disk_percent": disk,
            "uplink_latency_ms": None,
        }

    async def _get_asterisk_version(self) -> str:
        from app.ami.client import ami_client
        resp = await ami_client.send_action({"Action": "CoreSettings"})
        if isinstance(resp, dict):
            return str(resp.get("AsteriskVersion") or "unknown")
        return "unknown"

    async def _add_monitor_to_apartment(self, apartment_code: str, extension: str) -> None:
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment, ApartmentMonitor
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Apartment)
                .options(selectinload(Apartment.monitors))
                .where(Apartment.call_code == apartment_code)
            )
            apt = result.scalar_one_or_none()
            if not apt:
                return
            existing = {m.sip_account for m in apt.monitors}
            if extension not in existing:
                db.add(ApartmentMonitor(apartment_id=apt.id, sip_account=extension, label=None))
                await db.commit()

        await self._rebuild_all_dialplan()

    async def _rebuild_all_dialplan(self) -> None:
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment, ApartmentMonitor
        from app.services.sip_service import write_apartments_dialplan
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Apartment)
                .options(selectinload(Apartment.monitors))
                .where(Apartment.enabled == True)  # noqa: E712
            )
            apartments = result.scalars().all()

        apt_dicts = [
            {
                "call_code": apt.call_code,
                "monitors": [m.sip_account for m in apt.monitors],
            }
            for apt in apartments
            if apt.call_code
        ]

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, write_apartments_dialplan, apt_dicts)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_turn_credentials(host: str, port: int, ttl: int = 900) -> list[dict]:
    """Build STUN + TURN ice_servers with short-lived HMAC-SHA1 credentials.

    Uses coturn's `use-auth-secret` mechanism:
      username   = "{expiry_unix}:intercom"
      credential = base64( HMAC-SHA1(secret, username) )
    Matches `static-auth-secret` in turnserver.conf.
    """
    expiry = int(time.time()) + ttl
    username = f"{expiry}:intercom"
    raw_hmac = hmac.new(
        settings.coturn_secret.encode(),
        username.encode(),
        hashlib.sha1,
    )
    credential = base64.b64encode(raw_hmac.digest()).decode()
    return [
        {"urls": f"stun:{host}:{port}"},
        {
            "urls": [
                f"turn:{host}:{port}?transport=udp",
                f"turn:{host}:{port}?transport=tcp",
            ],
            "username": username,
            "credential": credential,
        },
    ]


def _build_media_config() -> dict:
    """Build the media_config payload advertised to the cloud in the hello frame.

    Cloud caches this and serves it to mobile clients via
    GET /api/mobile/media-config. Refreshed on each WS reconnect and every
    10 min via _media_config_loop so TURN credentials never expire mid-session.
    """
    cfg: dict[str, Any] = {}

    # WHEP basic-auth (go2rtc) — only include if both creds are set.
    if settings.go2rtc_user and settings.go2rtc_pass:
        cfg["whep"] = {
            "basic_auth": {
                "user": settings.go2rtc_user,
                "pass": settings.go2rtc_pass,
            }
        }

    # ICE servers — prefer short-lived HMAC creds (coturn use-auth-secret);
    # fall back to static creds; empty list if coturn not configured.
    ice: list[dict[str, Any]] = []
    if settings.coturn_public_host:
        host = settings.coturn_public_host
        port = settings.coturn_port
        if settings.coturn_secret:
            # Short-lived credentials, TTL 15 min.
            ice = _build_turn_credentials(host, port, ttl=900)
        elif settings.coturn_user and settings.coturn_cred:
            # Static fallback.
            ice = [
                {"urls": f"stun:{host}:{port}"},
                {
                    "urls": [
                        f"turn:{host}:{port}?transport=udp",
                        f"turn:{host}:{port}?transport=tcp",
                    ],
                    "username": settings.coturn_user,
                    "credential": settings.coturn_cred,
                },
            ]
    cfg["ice_servers"] = ice

    # SIP-over-WSS endpoint for mobile SIP.js clients.
    public_host = settings.public_bridge_host or settings.server_ip
    sip_ws_url = settings.sip_ws_url or (
        f"wss://{public_host}/asterisk/ws" if public_host else ""
    )
    sip_domain = settings.sip_domain or public_host or ""
    sip_block: dict[str, Any] = {}
    if sip_ws_url:
        sip_block["ws_url"] = sip_ws_url
    if sip_domain:
        sip_block["domain"] = sip_domain
    if settings.intercom_stun_url:
        sip_block["stun_url"] = settings.intercom_stun_url
    else:
        sip_block["stun_url"] = "stun:stun.l.google.com:19302"
    if sip_block:
        cfg["sip"] = sip_block

    return cfg


def _map_unlock_method(method: str) -> str:
    """Map local unlock_method values to cloud schema values."""
    return {
        "http_get": "http",
        "http_post": "http",
        "sip_dtmf": "relay",
        "none": "none",
    }.get(method, "none")


def _map_device_type(dt: str) -> str:
    mapping = {
        "door_station": "panel",
        "home_station": "controller",
        "guard_station": "controller",
        "sip_client": "controller",
        "camera": "camera",
    }
    return mapping.get(dt, "panel")


def _has_active_call() -> bool:
    from app.services.call_store import call_store
    return call_store.get_active() is not None


async def _active_call_to_cloud(active) -> dict:
    """Build call_started payload — looks up caller device by SIP account."""
    caller_device_id, video_rtsp = await _resolve_caller_device(active.caller)
    video_webrtc_url, video_hls_url = _build_video_urls(caller_device_id)
    return {
        "call_id": active.call_id,
        "caller_device_id": caller_device_id,
        "caller_sip": active.caller,
        "apartment_code": active.callee,
        "video_rtsp": video_rtsp,
        "video_webrtc_url": video_webrtc_url,
        "video_hls_url": video_hls_url,
        "started_at": active.started_at,
    }


def _ami_field(ev, *names: str) -> str | None:
    """Case-insensitive header lookup for AMI events.

    panoramisk's ``Message`` lowercases keys (so ``ev["channel"]`` works,
    ``ev["Channel"]`` does NOT). AMI/SIP-on-the-wire field names are case
    sensitive in spec but Asterisk and panoramisk play loose, so do the same.
    """
    try:
        keys = list(ev.keys())
    except Exception:
        return None
    targets = {n.lower() for n in names}
    for k in keys:
        if k.lower() in targets:
            try:
                val = ev[k]
            except Exception:
                continue
            if val is not None and val != "":
                return val
    return None


async def _find_call_channel(call_id: str) -> str | None:
    """Find the panel/originating channel for *call_id* via AMI.

    Matches on Uniqueid first (the originating channel of an inbound call),
    falls back to Linkedid for any channel in the same call group. Field
    names from panoramisk are lowercased, so we use case-insensitive lookup.

    Logs a diagnostic on miss with a real sample of message dicts so we can
    see why the channel wasn't found.
    """
    from app.ami.client import ami_client

    resp = await ami_client.send_action({"Action": "CoreShowChannels"})
    if not resp:
        logger.warning("find_call_channel_no_response", call_id=call_id)
        return None
    events = resp if isinstance(resp, list) else [resp]

    # Prefer exact Uniqueid match (= originating panel channel).
    for ev in events:
        uid = _ami_field(ev, "Uniqueid", "UniqueID")
        if uid == call_id:
            chan = _ami_field(ev, "Channel")
            if chan:
                return chan

    # Fallback: Linkedid match (any channel sharing this call's group).
    for ev in events:
        lid = _ami_field(ev, "Linkedid", "LinkedID")
        if lid == call_id:
            chan = _ami_field(ev, "Channel")
            if chan:
                return chan

    # Miss: dump real headers so we can debug.
    sample = []
    for ev in events[:6]:
        try:
            sample.append({k: ev[k] for k in list(ev.keys())[:12]})
        except Exception:
            sample.append(repr(ev)[:200])
    logger.warning(
        "find_call_channel_miss",
        call_id=call_id,
        total_channels=len(events),
        sample=sample,
    )
    return None


def _rtsp_block(device_id: int, rtsp_url: str) -> dict:
    """Build the rtsp dict for device_snapshot — includes webrtc/hls URLs."""
    webrtc_url, hls_url = _build_video_urls(device_id)
    return {
        "enabled": True,
        "url": rtsp_url,
        "webrtc_url": webrtc_url,
        "hls_url": hls_url,
    }


def _build_video_urls(device_id: int | None) -> tuple[str | None, str | None]:
    """Build go2rtc WHEP + HLS URLs for the given panel device.

    Uses PUBLIC_BRIDGE_HOST so mobile clients reach the bridge from outside the
    LAN. Falls back to intercom_public_base_url, then server_ip.
    """
    if not device_id:
        return None, None
    host = (
        settings.public_bridge_host
        or (settings.intercom_public_base_url.replace("https://", "").replace("http://", "").rstrip("/"))
        or settings.server_ip
    )
    base = f"https://{host}" if not host.startswith(("http://", "https://")) else host
    src = f"panel-{device_id}"
    return (
        f"{base}/go2rtc/api/webrtc?src={src}",
        f"{base}/go2rtc/api/stream.m3u8?src={src}",
    )


async def _resolve_caller_device(sip_account: str) -> tuple[int | None, str | None]:
    """Find the Device that placed an incoming call — return (id, rtsp_url).

    A SIP account *should* be unique across devices, but historic data can have
    duplicates (e.g. a Home Monitor row sharing the panel's SIP account).
    Since calls only originate from panels, prefer in this order:

        1. DOOR_STATION devices with rtsp_enabled (the real calling panel).
        2. Any DOOR_STATION matching the SIP account.
        3. Any device with rtsp_enabled.
        4. Whatever else matches.

    Tiebreaker: smallest device id (deterministic).
    """
    if not sip_account:
        return None, None
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models import Device, DeviceType

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Device)
            .where(Device.sip_account == sip_account, Device.enabled == True)  # noqa: E712
            .order_by(Device.id)
        )
        candidates = list(result.scalars().all())
        if not candidates:
            return None, None

        def _rank(d: Device) -> int:
            if d.device_type == DeviceType.DOOR_STATION and d.rtsp_enabled:
                return 0
            if d.device_type == DeviceType.DOOR_STATION:
                return 1
            if d.rtsp_enabled:
                return 2
            return 3

        dev = min(candidates, key=_rank)
        return dev.id, (dev.rtsp_url if dev.rtsp_enabled else None)


# Module-level singleton
cloud_bridge = CloudBridge()
