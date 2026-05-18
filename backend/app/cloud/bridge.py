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
import contextvars
import hashlib
import hmac
import json
import random
import time
from datetime import datetime, timezone
from typing import Any, Optional


# Set inside cloud-command handlers (_cmd_*) so that any DB write they perform
# does NOT trigger an outbound apartment_upserted/device_upserted event back
# to the cloud — cloud already knows what it just told us to do. API endpoints
# that admin uses to mutate local state leave this False and DO fire events.
_skip_outbound_mirror: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "cloud_mirror_skip_outbound", default=False
)


def is_mirror_suppressed() -> bool:
    """True if the current async task should skip outbound mirroring events."""
    return _skip_outbound_mirror.get()

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
            "create_apartment": self._cmd_create_apartment,
            "rename_apartment": self._cmd_rename_apartment,
            "delete_apartment": self._cmd_delete_apartment,
            "set_apartment_monitors": self._cmd_set_monitors,
            "unlock_door": self._cmd_unlock_door,
            "reject_call": self._cmd_reject_call,
            "answer_call": self._cmd_answer_call,
            "re_invite_apartment": self._cmd_re_invite_apartment,
            "update_bridge_token": self._cmd_update_bridge_token,
            # Cloud → bridge mirror state. No cmd_id, no ack required.
            "bootstrap_snapshot": self._cmd_bootstrap_snapshot,
            "apartment_upserted_ack": self._cmd_apartment_upserted_ack,
            "device_upserted_ack": self._cmd_device_upserted_ack,
        }.get(cmd_type)

        if handler is None:
            logger.warning("cloud_ws_unknown_cmd", type=cmd_type)
            if cmd_id:
                await self.send_ack(cmd_id, False, error=f"unknown command: {cmd_type}")
            return

        # Cloud-initiated commands must NOT trigger outbound apartment_upserted /
        # device_upserted echoes. Set the context var for the duration of this
        # handler — API endpoints (admin) leave it unset and DO fire echoes.
        token = _skip_outbound_mirror.set(True)
        try:
            result = await handler(data, cmd_id=cmd_id)
            if cmd_id:
                await self.send_ack(cmd_id, True, result=result or {})
        except Exception as exc:
            logger.error("cloud_ws_cmd_error", type=cmd_type, error=str(exc))
            if cmd_id:
                await self.send_ack(cmd_id, False, error=str(exc))
        finally:
            _skip_outbound_mirror.reset(token)

    # ──────────────────────────────────────────────────────────────────────────
    # Command handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _cmd_ping(self, data: dict, **_) -> dict:
        return {"pong": True, "ts": _utcnow()}

    async def _cmd_update_bridge_token(self, data: dict, **_) -> dict:
        """Cloud is rotating our bridge token.

        Persist the new token to disk (so the next process start picks it up
        from /app/data/cloud_bridge_token) and mutate ``settings`` in memory
        so the reconnect loop, which reads ``settings.cloud_bridge_token`` on
        every WS connect, uses the new token immediately. Cloud closes the
        current WS with code 4005 right after our ack — our ``_reconnect_loop``
        re-dials with the freshly persisted token.
        """
        new_token = (data or {}).get("new_token")
        if not isinstance(new_token, str) or not new_token.strip():
            raise RuntimeError("new_token is required and must be a non-empty string")
        new_token = new_token.strip()

        from app.core.runtime_token import persist_token
        try:
            persist_token(new_token)
        except Exception as exc:
            raise RuntimeError(f"Failed to persist token: {exc}") from exc

        settings.cloud_bridge_token = new_token
        logger.info(
            "cloud_bridge_token_rotated",
            new_token_prefix=new_token[:6] + "…",
        )
        return {}

    # ──────────────────────────────────────────────────────────────────────────
    # Cloud → bridge mirror state (events, not commands — no ack required)
    # ──────────────────────────────────────────────────────────────────────────

    async def _cmd_bootstrap_snapshot(self, data: dict, **_) -> None:
        """Cache cloud's view of entrances + devices for this bridge.

        Sent fire-and-forget by cloud right after ``hello_ack`` (and after any
        push_provisioning round). We use it for two things:

          1. Populate the local ``entrances`` table so admin UI can show a
             dropdown of valid entrance_ids when creating apartments/devices.
          2. Backfill ``Device.cloud_id`` / ``Device.mac_address`` /
             ``Device.entrance_id`` on existing local rows that cloud has
             already onboarded — keyed by ``local_id`` (our own primary key
             that cloud remembers from prior ``device_snapshot`` events).

        Orphan devices (cloud has them, we don't) are logged but NOT auto-
        created — bridge admin must register them locally first. Orphan
        entrances ARE inserted: they're cloud-defined.
        """
        from app.db.session import AsyncSessionLocal
        from app.models import Device, Entrance
        from sqlalchemy import select

        entrances = (data or {}).get("entrances") or []
        devices = (data or {}).get("devices") or []
        if not isinstance(entrances, list) or not isinstance(devices, list):
            logger.warning("bootstrap_snapshot_invalid_shape", entrances=type(entrances).__name__)
            return

        async with AsyncSessionLocal() as db:
            # ── Entrances: upsert by cloud_id ────────────────────────────
            for ent in entrances:
                if not isinstance(ent, dict):
                    continue
                cid = ent.get("id")
                if cid is None:
                    continue
                result = await db.execute(
                    select(Entrance).where(Entrance.cloud_id == cid)
                )
                row = result.scalar_one_or_none()
                if row:
                    row.number = str(ent.get("number") or row.number)
                    row.building_id = ent.get("building_id")
                    row.building_address = ent.get("building_address")
                else:
                    db.add(
                        Entrance(
                            cloud_id=cid,
                            number=str(ent.get("number") or ""),
                            building_id=ent.get("building_id"),
                            building_address=ent.get("building_address"),
                        )
                    )

            # ── Devices: backfill cloud_id / entrance_id / mac on local rows ──
            matched, orphans = 0, 0
            for d in devices:
                if not isinstance(d, dict):
                    continue
                local_id = d.get("local_id")
                cloud_dev_id = d.get("device_id")
                if local_id is None:
                    continue
                dev = await db.get(Device, local_id)
                if not dev:
                    orphans += 1
                    logger.info(
                        "bootstrap_orphan_device",
                        cloud_device_id=cloud_dev_id,
                        local_id=local_id,
                        mac=d.get("mac_address"),
                        sip=d.get("sip_account"),
                    )
                    continue
                if cloud_dev_id and dev.cloud_id != cloud_dev_id:
                    dev.cloud_id = cloud_dev_id
                if d.get("mac_address") and not dev.mac_address:
                    dev.mac_address = d["mac_address"]
                scope = d.get("scope") or {}
                cloud_entrance_id = scope.get("entrance_id")
                if cloud_entrance_id:
                    # Resolve to our local FK via cloud_id we just upserted.
                    er = await db.execute(
                        select(Entrance).where(Entrance.cloud_id == cloud_entrance_id)
                    )
                    e_row = er.scalar_one_or_none()
                    if e_row and dev.entrance_id != e_row.id:
                        dev.entrance_id = e_row.id
                dev.cloud_synced = True
                dev.last_cloud_sync_error = None
                matched += 1

            await db.commit()

        logger.info(
            "bootstrap_snapshot_applied",
            entrances=len(entrances),
            devices_matched=matched,
            devices_orphan=orphans,
        )

    async def _cmd_apartment_upserted_ack(self, data: dict, **_) -> None:
        """Cloud confirms our apartment_upserted; persist returned IDs.

        Matching key: (entrance_id, apartment_code). Cloud returns its own
        ``apartment_id`` and (optionally) ``monitor_ids`` mapping
        ``mac_address → device_id`` for hardware monitors.
        """
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment, ApartmentMonitor, Entrance
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        apt_code = (data or {}).get("apartment_code")
        cloud_apt_id = (data or {}).get("apartment_id")
        cloud_entrance_id = (data or {}).get("entrance_id")
        monitor_ids: dict = (data or {}).get("monitor_ids") or {}
        if not apt_code:
            logger.warning("apartment_upserted_ack_no_code", data=data)
            return

        async with AsyncSessionLocal() as db:
            # Find the apartment. Prefer (entrance_id, call_code) when cloud
            # echoes back entrance_id; otherwise fall back to call_code only.
            stmt = (
                select(Apartment)
                .options(selectinload(Apartment.monitors))
                .where(Apartment.call_code == apt_code)
            )
            if cloud_entrance_id:
                er = await db.execute(
                    select(Entrance).where(Entrance.cloud_id == cloud_entrance_id)
                )
                e_row = er.scalar_one_or_none()
                if e_row:
                    stmt = stmt.where(Apartment.entrance_id == e_row.id)

            apt = (await db.execute(stmt)).scalars().first()
            if not apt:
                logger.warning(
                    "apartment_upserted_ack_no_local_match",
                    apt_code=apt_code,
                    cloud_apt_id=cloud_apt_id,
                )
                return

            if cloud_apt_id and apt.cloud_id != cloud_apt_id:
                apt.cloud_id = cloud_apt_id
            apt.cloud_synced = True
            apt.last_cloud_sync_error = None

            # Backfill cloud_id on monitors. Cloud keys monitor_ids by MAC
            # when we sent one, else by sip_account (per cloud contract).
            if monitor_ids and apt.monitors:
                for mon in apt.monitors:
                    cid = None
                    if mon.mac_address and mon.mac_address in monitor_ids:
                        cid = monitor_ids[mon.mac_address]
                    elif mon.sip_account and mon.sip_account in monitor_ids:
                        cid = monitor_ids[mon.sip_account]
                    if cid is not None:
                        mon.cloud_id = cid

            await db.commit()
            logger.info(
                "apartment_upserted_ack_applied",
                apt_code=apt_code,
                cloud_apt_id=cloud_apt_id,
                monitor_ids=monitor_ids,
            )

    async def _cmd_device_upserted_ack(self, data: dict, **_) -> None:
        """Cloud confirms our device_upserted. Persist ``device_id``."""
        from app.db.session import AsyncSessionLocal
        from app.models import Device
        from sqlalchemy import select

        mac = (data or {}).get("mac_address")
        local_id = (data or {}).get("local_id")
        cloud_dev_id = (data or {}).get("device_id")
        if not cloud_dev_id:
            logger.warning("device_upserted_ack_no_device_id", data=data)
            return

        async with AsyncSessionLocal() as db:
            dev: Device | None = None
            if local_id:
                dev = await db.get(Device, local_id)
            if not dev and mac:
                result = await db.execute(select(Device).where(Device.mac_address == mac))
                dev = result.scalar_one_or_none()
            if not dev:
                logger.warning(
                    "device_upserted_ack_no_local_match",
                    mac=mac,
                    local_id=local_id,
                    cloud_dev_id=cloud_dev_id,
                )
                return

            if dev.cloud_id != cloud_dev_id:
                dev.cloud_id = cloud_dev_id
            dev.cloud_synced = True
            dev.last_cloud_sync_error = None
            await db.commit()
            logger.info(
                "device_upserted_ack_applied",
                local_id=dev.id,
                mac=mac,
                cloud_dev_id=cloud_dev_id,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Outbound mirror — called from API endpoints (admin actions)
    # ──────────────────────────────────────────────────────────────────────────

    async def emit_apartment_upserted(self, apartment_id: int) -> None:
        """Send apartment_upserted for the given local apartment id.

        Skipped automatically when called from inside a cloud command handler
        (see _skip_outbound_mirror). Failure paths persist the error on the
        apartment row so admin can see what went wrong and retry-on-startup
        can pick it up next reboot.
        """
        if is_mirror_suppressed():
            return
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment, Entrance
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with AsyncSessionLocal() as db:
            apt = (
                await db.execute(
                    select(Apartment)
                    .options(selectinload(Apartment.monitors))
                    .where(Apartment.id == apartment_id)
                )
            ).scalar_one_or_none()
            if not apt:
                return

            # We need a cloud-side entrance_id to send.
            cloud_entrance_id: int | None = None
            if apt.entrance_id:
                er = await db.get(Entrance, apt.entrance_id)
                if er:
                    cloud_entrance_id = er.cloud_id

            if cloud_entrance_id is None:
                apt.cloud_synced = False
                apt.last_cloud_sync_error = (
                    "no entrance assigned — cannot mirror to cloud"
                )
                await db.commit()
                logger.warning(
                    "apartment_upsert_skipped_no_entrance",
                    local_id=apt.id,
                    call_code=apt.call_code,
                )
                return

            payload = {
                "entrance_id": cloud_entrance_id,
                "apartment_code": apt.call_code,
                "apartment_id": apt.cloud_id,
                "number": apt.number,
                "floor": apt.floor,
                "monitors": [
                    {
                        "local_id": m.id,  # stable PK on our side — preferred matching key
                        "sip_account": m.sip_account,
                        "mac_address": m.mac_address,
                        "model": m.model,
                        "name": m.name,
                    }
                    for m in apt.monitors
                ],
            }

            # Mark dirty BEFORE the network send — flip back to true only
            # when the ack actually arrives. If we crash before ack, startup
            # resync will re-fire.
            apt.cloud_synced = False
            await db.commit()

        await self.send_event("apartment_upserted", payload)
        logger.info(
            "apartment_upsert_emitted",
            local_id=apartment_id,
            call_code=payload["apartment_code"],
        )

    async def emit_device_upserted(self, device_id: int) -> None:
        """Send device_upserted for the given local device id. See above for
        suppression and error-persistence semantics."""
        if is_mirror_suppressed():
            return
        from app.db.session import AsyncSessionLocal
        from app.models import Device, Entrance
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            dev = await db.get(Device, device_id)
            if not dev:
                return

            cloud_entrance_id: int | None = None
            if dev.entrance_id:
                er = await db.get(Entrance, dev.entrance_id)
                if er:
                    cloud_entrance_id = er.cloud_id

            if cloud_entrance_id is None:
                dev.cloud_synced = False
                dev.last_cloud_sync_error = (
                    "no entrance assigned — cannot mirror to cloud"
                )
                await db.commit()
                logger.warning(
                    "device_upsert_skipped_no_entrance",
                    local_id=dev.id,
                    name=dev.name,
                )
                return

            payload = {
                "entrance_id": cloud_entrance_id,
                "device": {
                    "type": _map_device_type(
                        dev.device_type.value if dev.device_type else ""
                    ),
                    "sip_account": dev.sip_account,
                    "mac_address": dev.mac_address,
                    "model": dev.model,
                    "name": dev.name,
                    "local_id": dev.id,
                },
            }

            dev.cloud_synced = False
            await db.commit()

        await self.send_event("device_upserted", payload)
        logger.info(
            "device_upsert_emitted",
            local_id=device_id,
            mac=dev.mac_address,
            name=dev.name,
        )

    async def resync_pending(self) -> None:
        """Re-fire apartment_upserted / device_upserted for any rows where
        ``cloud_synced=false`` AND no permanent error is set.

        Called once on startup. Idempotent on cloud side, so safe to re-deliver.
        """
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment, Device
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            apt_ids = (
                await db.execute(
                    select(Apartment.id).where(
                        Apartment.cloud_synced == False,  # noqa: E712
                        Apartment.entrance_id.is_not(None),
                    )
                )
            ).scalars().all()
            dev_ids = (
                await db.execute(
                    select(Device.id).where(
                        Device.cloud_synced == False,  # noqa: E712
                        Device.entrance_id.is_not(None),
                    )
                )
            ).scalars().all()

        for aid in apt_ids:
            await self.emit_apartment_upserted(aid)
        for did in dev_ids:
            await self.emit_device_upserted(did)

        if apt_ids or dev_ids:
            logger.info(
                "cloud_mirror_resync_pending",
                apartments=len(apt_ids),
                devices=len(dev_ids),
            )

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

    async def _cmd_create_apartment(self, data: dict, **_) -> dict:
        """Idempotent INSERT apartment.

        Sent by cloud right after admin creates an apartment in CRM, BEFORE
        the corresponding ``set_apartment_monitors``. We just ensure the row
        exists. If an admin races us (unlikely) and the row is already here,
        we no-op and report ``created: false``.
        """
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment
        from sqlalchemy import select

        apartment_code = (data or {}).get("apartment_code")
        if not apartment_code or not isinstance(apartment_code, str):
            return {"success": False, "message": "apartment_code is required"}

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Apartment).where(Apartment.call_code == apartment_code)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return {
                    "success": True,
                    "message": f"apartment {apartment_code} already exists",
                    "apartment_local_id": existing.id,
                    "created": False,
                }

            apt = Apartment(
                number=apartment_code,
                call_code=apartment_code,
                enabled=True,
            )
            db.add(apt)
            await db.commit()
            await db.refresh(apt)
            logger.info("apartment_created_via_ws", call_code=apartment_code, local_id=apt.id)
            return {
                "success": True,
                "message": f"apartment {apartment_code} created",
                "apartment_local_id": apt.id,
                "created": True,
            }

    async def _cmd_rename_apartment(self, data: dict, **_) -> dict:
        """UPDATE apartments.call_code and regenerate dialplan.

        Old call_code disappears from the dialplan (panel calling the old
        number now lands in extension-not-found), new call_code shows up
        with the same monitor list — cloud will follow up with a fresh
        ``set_apartment_monitors`` if monitors change too.
        """
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment
        from sqlalchemy import select

        old_code = (data or {}).get("old_apartment_code")
        new_code = (data or {}).get("new_apartment_code")
        if not old_code or not new_code:
            return {
                "success": False,
                "message": "old_apartment_code and new_apartment_code are required",
            }
        if old_code == new_code:
            return {
                "success": True,
                "message": "old and new code are identical, no-op",
            }

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Apartment).where(Apartment.call_code == old_code)
            )
            apt = result.scalar_one_or_none()
            if not apt:
                return {
                    "success": False,
                    "message": f"apartment with call_code={old_code} not found",
                }

            # Reject if new code already taken by another apartment.
            result = await db.execute(
                select(Apartment).where(Apartment.call_code == new_code)
            )
            collision = result.scalar_one_or_none()
            if collision and collision.id != apt.id:
                return {
                    "success": False,
                    "message": f"apartment with call_code={new_code} already exists (id={collision.id})",
                }

            apt.call_code = new_code
            # number defaults to old call_code if user never customized it;
            # don't surprise the operator, leave as is.
            await db.commit()
            local_id = apt.id

        await self._rebuild_all_dialplan()
        logger.info(
            "apartment_renamed_via_ws",
            old=old_code,
            new=new_code,
            local_id=local_id,
        )
        return {
            "success": True,
            "message": f"apartment renamed {old_code} → {new_code}",
            "apartment_local_id": local_id,
        }

    async def _cmd_delete_apartment(self, data: dict, **_) -> dict:
        """DELETE apartment (with monitor cascade) and regenerate dialplan.

        Idempotent: missing apartment is treated as a successful no-op so
        cloud's drain-then-delete sequence is safe to re-deliver.
        """
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment, ApartmentMonitor
        from sqlalchemy import select

        apartment_code = (data or {}).get("apartment_code")
        if not apartment_code:
            return {"success": False, "message": "apartment_code is required"}

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Apartment).where(Apartment.call_code == apartment_code)
            )
            apt = result.scalar_one_or_none()
            if not apt:
                return {
                    "success": True,
                    "message": f"apartment {apartment_code} not found (no-op)",
                    "deleted": False,
                }

            # Explicit cascade — Apartment FKs may not declare ON DELETE.
            await db.execute(
                ApartmentMonitor.__table__.delete().where(
                    ApartmentMonitor.apartment_id == apt.id
                )
            )
            local_id = apt.id
            await db.delete(apt)
            await db.commit()

        await self._rebuild_all_dialplan()
        logger.info(
            "apartment_deleted_via_ws",
            call_code=apartment_code,
            local_id=local_id,
        )
        return {
            "success": True,
            "message": f"apartment {apartment_code} deleted",
            "apartment_local_id": local_id,
            "deleted": True,
        }

    async def _cmd_set_monitors(self, data: dict, **_) -> dict:
        """Replace monitors for an apartment. Idempotent — auto-creates apt.

        Cloud's standard sequence is ``create_apartment`` then
        ``set_apartment_monitors``, but Kafka-event ordering and reconnect
        races mean we may see ``set_apartment_monitors`` first. In that case
        we create the row on the fly so monitor sync never blocks on a
        missing parent.
        """
        from app.db.session import AsyncSessionLocal
        from app.models import Apartment, ApartmentMonitor
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        apartment_code = (data or {}).get("apartment_code")
        if not apartment_code:
            return {"success": False, "message": "apartment_code is required"}
        monitors: list[str] = (data or {}).get("monitors", []) or []

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Apartment)
                .options(selectinload(Apartment.monitors))
                .where(Apartment.call_code == apartment_code)
            )
            apt = result.scalar_one_or_none()
            created = False
            if not apt:
                apt = Apartment(
                    number=apartment_code,
                    call_code=apartment_code,
                    enabled=True,
                )
                db.add(apt)
                await db.flush()
                created = True
                logger.info(
                    "apartment_auto_created",
                    call_code=apartment_code,
                    reason="unknown_in_set_monitors",
                )

            await db.execute(
                ApartmentMonitor.__table__.delete().where(
                    ApartmentMonitor.apartment_id == apt.id
                )
            )
            for ext in monitors:
                db.add(ApartmentMonitor(apartment_id=apt.id, sip_account=ext, label=None))
            await db.commit()

        await self._rebuild_all_dialplan()
        return {
            "success": True,
            "message": (
                f"monitors set for {apartment_code} ({len(monitors)} entries)"
                + (", apartment auto-created" if created else "")
            ),
            "apartment_code": apartment_code,
            "monitors": monitors,
            "apartment_created": created,
        }

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
        """Hang up EVERY channel in the call group.

        Previously: we Hangup'd just the originating panel channel and relied
        on Asterisk's Dial() to auto-CANCEL its outgoing legs. Reality (seen
        on call_id 1778680452.254): Dial() exits when the parent is hung up,
        but in some early-media / ringing states the outgoing legs do NOT
        receive CANCEL — the panel UA stops, but the called endpoints keep
        ringing until their own dial-timeout. From cloud's perspective the
        user pressed Reject and the gate keeps shouting.

        Now we enumerate all channels in the call group (matched by
        ``Linkedid == call_id``) and issue an AMI Hangup against every one.
        Idempotent: any leg already gone returns harmlessly. We report which
        channels we touched so cloud can correlate with Asterisk events.
        """
        from app.ami.client import ami_client

        call_id = data.get("call_id")
        if not call_id:
            raise RuntimeError("call_id is required")

        # Find ALL channels in the call group.
        resp = await ami_client.send_action({"Action": "CoreShowChannels"})
        events = resp if isinstance(resp, list) else [resp] if resp else []
        chans_to_kill: list[str] = []
        for ev in events:
            if not hasattr(ev, "keys"):
                continue
            lid = _ami_field(ev, "Linkedid", "LinkedID")
            uid = _ami_field(ev, "Uniqueid", "UniqueID")
            if lid != call_id and uid != call_id:
                continue
            chan = _ami_field(ev, "Channel")
            if chan and chan not in chans_to_kill:
                chans_to_kill.append(chan)

        if not chans_to_kill:
            raise RuntimeError("channel_gone")

        # Hangup each leg explicitly. Partial errors are non-fatal — a leg
        # already gone is fine, we only fail hard if literally none accepted.
        hangup_results: list[dict] = []
        for chan in chans_to_kill:
            resp = await ami_client.send_action(
                {
                    "Action": "Hangup",
                    "Channel": chan,
                    "Cause": "21",  # Call rejected (Q.850)
                }
            )
            ok = False
            msg = ""
            if isinstance(resp, dict):
                status = _ami_field(resp, "Response") or ""
                ok = status == "Success"
                msg = _ami_field(resp, "Message") or ""
            elif resp is None:
                msg = "no AMI response"
            else:
                # panoramisk Message object that is dict-like
                try:
                    status = _ami_field(resp, "Response") or ""
                    ok = status == "Success"
                    msg = _ami_field(resp, "Message") or ""
                except Exception:
                    msg = repr(resp)[:100]
            hangup_results.append({"channel": chan, "ok": ok, "message": msg})

        any_ok = any(r["ok"] for r in hangup_results)
        if not any_ok:
            logger.error(
                "cloud_reject_call_all_hangups_failed",
                call_id=call_id,
                results=hangup_results,
            )
            raise RuntimeError(
                "hangup_failed: " + "; ".join(
                    f"{r['channel']}={r['message']}" for r in hangup_results
                )
            )

        logger.info(
            "cloud_reject_call_dispatched",
            call_id=call_id,
            channels=[r["channel"] for r in hangup_results],
            results=hangup_results,
        )
        return {
            "success": True,
            "call_id": call_id,
            "channels": [r["channel"] for r in hangup_results],
            "hangup_results": hangup_results,
        }

    async def _cmd_answer_call(self, data: dict, **_) -> dict:
        """User answered in the cloud-side mobile/web client.

        We verify TWO things before reporting success:

          1. The originating panel channel is still alive (Linkedid match).
             If not → ``channel_gone`` → cloud falls back to re_invite_apartment.
          2. A channel for ``answered_by_sip`` exists in the same call group.
             This catches the Doze-race case where the mobile contact was
             missing at Dial() time so Asterisk never sent an INVITE to it
             (we'd see `Could not create dialog to invalid URI '<ext>'` in
             the Asterisk log). The panel ringback came from the hardware
             monitor leg, the mobile leg never got created — answering on
             the mobile UI in this state means "I want audio but there is
             no SIP session". Returning success here misleads cloud into
             reporting audio_status=established, mobile waits for an INVITE
             that will never arrive.
             If absent → ``callee_leg_missing`` → cloud uses
             re_invite_apartment to Originate a fresh leg to the mobile.

        Otherwise just send ``call_answered`` upstream (silences the user's
        other devices) and ack success.
        """
        from app.ami.client import ami_client

        call_id = data.get("call_id")
        answered_by_sip = data.get("answered_by_sip")
        if not call_id:
            raise RuntimeError("call_id is required")

        panel_chan = await _find_call_channel(call_id)
        if not panel_chan:
            raise RuntimeError("channel_gone")

        # Hunt for an actual leg matching answered_by_sip in this call group.
        if answered_by_sip:
            resp = await ami_client.send_action({"Action": "CoreShowChannels"})
            events = resp if isinstance(resp, list) else [resp] if resp else []
            callee_leg_chan: str | None = None
            for ev in events:
                if not isinstance(ev, (dict,)) and not hasattr(ev, "keys"):
                    continue
                lid = _ami_field(ev, "Linkedid", "LinkedID")
                if lid != call_id:
                    continue
                chan = _ami_field(ev, "Channel") or ""
                # PJSIP channel names look like "PJSIP/200001-0000abcd". The
                # extension is the part between "PJSIP/" and the trailing "-…".
                if not chan.startswith("PJSIP/"):
                    continue
                ext = chan.split("/", 1)[1].split("-")[0]
                if ext == str(answered_by_sip):
                    callee_leg_chan = chan
                    break

            if not callee_leg_chan:
                logger.warning(
                    "answer_call_callee_leg_missing",
                    call_id=call_id,
                    answered_by_sip=answered_by_sip,
                    panel_chan=panel_chan,
                )
                raise RuntimeError("callee_leg_missing")

        await self.send_event(
            "call_answered",
            {"call_id": call_id, "answered_by_sip": answered_by_sip},
        )
        logger.info(
            "cloud_answer_call_ack",
            call_id=call_id,
            by=answered_by_sip,
            panel_chan=panel_chan,
        )
        return {
            "success": True,
            "audio_status": "established",
            "call_id": call_id,
            "channel": panel_chan,
        }

    async def _cmd_re_invite_apartment(self, data: dict, **_) -> dict:
        """Re-Originate a fresh leg to the callee and bridge it into a
        still-alive panel channel.

        Used by cloud as a fallback after ``answer_call`` fails because the
        callee's contact expired during mobile Doze. Flow:

          1. Look up the panel channel by ``call_id`` (Uniqueid/Linkedid).
          2. Poll AMI for ``PJSIPShowEndpoint`` (or equivalent) until the
             callee has at least one live contact, up to ``timeout_seconds``.
          3. Issue AMI ``Originate`` with ``Application=Bridge``,
             ``Data=<panel_chan>`` — when the callee picks up, Asterisk
             bridges them into the existing panel call. No new dialplan,
             no fresh INVITE-from-panel.
          4. Ack ``{ok: true, result: {audio_status: "established"}}`` on
             Originate=Success; otherwise structured error.

        Returns shape per cloud spec:
          ok=true  → result={audio_status: "established", channel: <panel>}
          ok=false → raise RuntimeError("channel_gone"|"callee_not_registered")
                     ; cloud's ack handler maps error string to audio_status.
        """
        from app.ami.client import ami_client

        call_id = (data or {}).get("call_id")
        callee = (data or {}).get("callee_sip_extension")
        timeout_s = float((data or {}).get("timeout_seconds") or 10)
        if not call_id or not callee:
            raise RuntimeError("call_id and callee_sip_extension are required")

        # 1) Is the panel channel still alive?
        panel_chan = await _find_call_channel(call_id)
        if not panel_chan:
            logger.warning("re_invite_apartment_panel_gone", call_id=call_id)
            raise RuntimeError("channel_gone")

        # 2) Poll for the callee's contact. We previously tried
        #    PJSIPShowEndpoint and parsed ContactStatusDetail events, but
        #    panoramisk's send_action returns a different shape for some
        #    EventList actions and that parser was missing real contacts.
        #
        #    Switch to AMI Command action with the CLI output — the text
        #    format ``aor/sip:...:port;transport=ws  <hash>  <Status>`` is
        #    stable across Asterisk versions, and "any line for our AOR with
        #    Status != 'Removed'" is a robust readiness check. We collect a
        #    diagnostic sample on first miss so the next failure is debuggable.
        async def _has_callee_contact() -> tuple[bool, str]:
            resp = await ami_client.send_action(
                {"Action": "Command", "Command": f"pjsip show contacts"}
            )
            if not resp:
                return False, "no AMI response"
            items = resp if isinstance(resp, list) else [resp]
            blob = ""
            for it in items:
                for key in ("Output", "CmdData", "Response", "Message", "data"):
                    val = _ami_field(it, key)
                    if isinstance(val, str) and val:
                        blob += val + "\n"
                    elif isinstance(val, list):
                        blob += "\n".join(str(x) for x in val) + "\n"
            if not blob:
                # panoramisk may merge CLI output across many lines/events as
                # separate dict entries — flatten everything stringy.
                try:
                    blob = "\n".join(
                        "\n".join(str(v) for v in dict(it).values() if isinstance(v, str))
                        for it in items
                    )
                except Exception:
                    blob = ""
            for line in blob.splitlines():
                if "Contact:" not in line:
                    continue
                # Lines look like:
                #   Contact:  200001/sip:abc@host:port;transport=ws ... <Status>
                if f" {callee}/sip:" not in line and f"{callee}/sip:" not in line:
                    continue
                lower = line.lower()
                if "removed" in lower or "unreach" in lower:
                    continue
                return True, line.strip()
            return False, blob[:400] if blob else "no output"

        deadline = asyncio.get_event_loop().time() + timeout_s
        last_diag = ""
        while True:
            ok, diag = await _has_callee_contact()
            if ok:
                logger.info(
                    "re_invite_apartment_contact_seen",
                    call_id=call_id,
                    callee=callee,
                    contact=diag,
                )
                break
            last_diag = diag
            if asyncio.get_event_loop().time() >= deadline:
                logger.warning(
                    "re_invite_apartment_callee_not_registered",
                    call_id=call_id,
                    callee=callee,
                    waited_s=timeout_s,
                    last_probe_output=last_diag,
                )
                raise RuntimeError("callee_not_registered")
            await asyncio.sleep(0.5)

        # 3) Originate the new leg, bridging into the panel's existing channel
        #    on answer. Async=true so we don't block on the dial timeout —
        #    Asterisk will fire OriginateResponse when it has news.
        action_id = f"reinvite-{call_id}-{int(time.time() * 1000)}"
        resp = await ami_client.send_action(
            {
                "Action": "Originate",
                "ActionID": action_id,
                "Channel": f"PJSIP/{callee}",
                "Application": "Bridge",
                "Data": panel_chan,
                "CallerID": f"reinvite <{callee}>",
                "Async": "true",
                "Timeout": str(int(timeout_s * 1000)),
            }
        )
        # Originate Async returns Response: Success immediately if accepted.
        # OriginateResponse arrives later — we don't block on it here; cloud
        # will infer failure via subsequent call_ended event if dial fails.
        if isinstance(resp, dict):
            ok = (resp.get("Response") or resp.get("response")) == "Success"
            msg = resp.get("Message") or resp.get("message") or ""
            if not ok:
                logger.error(
                    "re_invite_apartment_originate_failed",
                    call_id=call_id,
                    callee=callee,
                    detail=msg,
                )
                raise RuntimeError(f"originate_failed: {msg}")

        logger.info(
            "re_invite_apartment_dispatched",
            call_id=call_id,
            callee=callee,
            panel_chan=panel_chan,
            action_id=action_id,
        )
        return {
            "success": True,
            "audio_status": "established",
            "channel": panel_chan,
            "callee": callee,
        }

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
    """Map our local DeviceType to cloud's device_type enum.

    Cloud enum (as of migration c7e1a2f4b8d3): panel | monitor | camera |
    reader | barrier | controller | sensor. ``monitor`` exists only after
    cloud has applied that migration; before then cloud will collapse it to
    the default ``panel`` — that's fine, we send the semantically correct
    value and cloud upgrades on its own schedule.
    """
    mapping = {
        "door_station": "panel",
        "home_station": "monitor",
        "guard_station": "monitor",
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
