"""AMI event consumer: maps Asterisk events → EventBus + CloudBridge."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.events.bus import event_bus
from app.services.call_store import call_store

logger = get_logger(__name__)


async def _lookup_caller_device(sip_account: str) -> tuple[int | None, str | None]:
    """Resolve caller SIP → (device_id, rtsp_url) for cloud call_started event.

    SIP account *should* be unique, but duplicates exist historically. Calls
    only originate from panels, so prefer DOOR_STATION + rtsp_enabled. Falls
    back through DOOR_STATION → rtsp_enabled → anything, with smallest id as
    a deterministic tiebreaker.
    """
    if not sip_account:
        return None, None
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models import Device, DeviceType

    try:
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
    except Exception as exc:
        logger.warning("caller_device_lookup_failed", sip=sip_account, error=str(exc))
        return None, None


def _duration_since(iso_started_at: str) -> int | None:
    """Compute call duration in seconds from ISO-8601 start timestamp."""
    if not iso_started_at:
        return None
    try:
        # call_store writes "%Y-%m-%dT%H:%M:%SZ" → strip trailing Z, parse UTC
        started = datetime.strptime(iso_started_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        return int((datetime.now(timezone.utc) - started).total_seconds())
    except ValueError:
        return None

_DIAL_STATUS_MAP = {
    "ANSWER": "answered",
    "NOANSWER": "missed",
    "BUSY": "busy",
    "CANCEL": "missed",
    "CONGESTION": "busy",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _push_cloud(event_type: str, data: dict) -> None:
    """Push event to cloud bridge if connected (non-blocking, best-effort)."""
    try:
        from app.cloud.bridge import cloud_bridge
        if cloud_bridge.is_connected:
            await cloud_bridge.send_event(event_type, data)
    except Exception as exc:
        logger.warning("cloud_push_failed", event_type=event_type, error=str(exc))


async def on_dial_begin(manager, event) -> None:
    """DialBegin → call_started (local SSE + cloud WS).

    Asterisk fires DialBegin once per dial target when using parallel hunt
    (e.g. Dial(PJSIP/1001&PJSIP/1002)).  All legs share the same Linkedid, so
    we guard against publishing the same call_id more than once.
    """
    call_id = event.get("Linkedid") or event.get("Uniqueid", "")
    caller = event.get("CallerIDNum", "")
    callee = event.get("DestExten") or event.get("Exten", "")

    if not call_id:
        return

    # Deduplicate: skip if this call_id is already being tracked.
    existing = call_store.get_active()
    if existing and existing.call_id == call_id:
        logger.debug("ami_dial_begin_duplicate_skipped", call_id=call_id)
        return

    active = call_store.on_call_started(call_id=call_id, caller=caller, callee=callee)

    # Resolve caller device once — used in both local SSE and cloud event.
    caller_device_id, video_rtsp = await _lookup_caller_device(caller)
    video_src = f"panel-{caller_device_id}" if caller_device_id else None

    local_data = {
        "call_id": call_id,
        "caller": caller,
        "callee": callee,
        "apartment_id": active.apartment_id,
        "started_at": active.started_at,
        "video_src": video_src,   # go2rtc stream name, e.g. "panel-1"
    }
    await event_bus.publish("call_started", local_data)

    # Cloud uses different field names per spec.
    from app.cloud.bridge import _build_video_urls
    video_webrtc_url, video_hls_url = _build_video_urls(caller_device_id)
    await _push_cloud("call_started", {
        "call_id": call_id,
        "caller_device_id": caller_device_id,
        "caller_sip": caller,
        "apartment_code": callee,
        "video_rtsp": video_rtsp,
        "video_webrtc_url": video_webrtc_url,
        "video_hls_url": video_hls_url,
        "started_at": active.started_at,
    })
    logger.info("ami_call_started", call_id=call_id, caller=caller, callee=callee)


async def on_dial_end(manager, event) -> None:
    """DialEnd → marks one Dial-leg ending. We do NOT fire call_ended here.

    Asterisk emits DialEnd *per dial leg*. With parallel hunt
    ``Dial(PJSIP/1003&PJSIP/200002)`` the leg that gets CANCEL'd (because
    another leg answered first) also fires DialEnd — we used to treat that as
    "call over" and prematurely deleted the active call_store entry, which
    surfaced to the cloud as a phantom ``call_ended`` SSE ~3 seconds after
    ``call_started`` while the answered leg was still in bridge.

    The real end of the call group is the Hangup of the originating panel
    channel (``Uniqueid == Linkedid``) — handled in on_hangup.
    """
    call_id = event.get("Linkedid") or event.get("Uniqueid", "")
    dial_status = (event.get("DialStatus") or "").upper()
    logger.debug("ami_dial_end_observed", call_id=call_id, status=dial_status)


async def on_bridge_enter(manager, event) -> None:
    """BridgeEnter — someone answered the call (bridge created = answered).

    Sent per channel; emit call_answered once when the non-originating endpoint
    bridges in (i.e. DestChannel ≠ caller channel).
    """
    call_id = event.get("Linkedid") or event.get("Uniqueid", "")
    channel = event.get("Channel", "")
    active = call_store.get_active()

    if not active or active.call_id != call_id:
        return

    extension = _extract_extension(channel)
    if extension and extension != active.caller:
        await _push_cloud("call_answered", {
            "call_id": call_id,
            "answered_by_sip": extension,
        })
        logger.info("ami_call_answered", call_id=call_id, extension=extension)


async def on_hangup(manager, event) -> None:
    """Hangup → call_ended, but only for the originating panel channel.

    In Asterisk a call group shares a single Linkedid; the first channel
    (the panel's SIP leg) has ``Uniqueid == Linkedid``. Dial legs created
    later (``PJSIP/200002-...``, ``PJSIP/1003-...``) have a fresh Uniqueid
    but inherit the same Linkedid. Hangup of those dial legs fires while
    the call continues on the answered leg in the bridge — we must not
    treat them as the end of the call. Acting only on the originating
    channel's Hangup gives us exactly one call_ended per call group.
    """
    call_id = event.get("Linkedid") or event.get("Uniqueid", "")
    uniqueid = event.get("Uniqueid", "")

    # Skip non-originating channels (dial legs). Their Hangup is part of
    # CANCEL-on-other-leg-answered or normal post-bridge teardown.
    if uniqueid != call_id:
        return

    active = call_store.get_active()
    if not active or active.call_id != call_id:
        return

    cause_txt = (event.get("Cause-txt") or "").lower()
    if "normal" in cause_txt:
        reason = "answered"
    elif "no answer" in cause_txt or "no_answer" in cause_txt:
        reason = "missed"
    elif "busy" in cause_txt:
        reason = "busy"
    else:
        reason = "other"

    duration = _duration_since(active.started_at)
    call_store.on_call_ended(call_id)
    ended_data = {"call_id": call_id, "ended_at": _utcnow(), "reason": reason}
    await event_bus.publish("call_ended", ended_data)
    await _push_cloud("call_ended", {
        **ended_data,
        "answered_by_sip": None,
        "duration_seconds": duration,
    })
    logger.info("ami_call_ended_hangup", call_id=call_id, reason=reason)


async def on_user_event(manager, event) -> None:
    """UserEvent DoorOpened → door_opened (local SSE + cloud WS)."""
    if event.get("UserEvent") != "DoorOpened":
        return

    call_id = event.get("Callid") or event.get("CallId") or None
    by = (event.get("By") or "panel").lower()

    await event_bus.publish("door_opened", {"call_id": call_id, "device_id": None, "by": by})
    await _push_cloud("door_unlocked", {
        "device_local_id": None,
        "actor": by,
        "method": "dtmf" if by == "dtmf" else "panel",
    })
    logger.info("ami_door_opened", call_id=call_id, by=by)


def _extract_extension(channel: str) -> str:
    """Extract SIP extension from channel name like 'PJSIP/1003007-00000001'."""
    if "/" in channel:
        ext_part = channel.split("/", 1)[1]
        return ext_part.split("-")[0]
    return ""


async def on_newchannel(manager, event) -> None:
    """Newchannel fallback for call_started.

    Fires when Asterisk creates any new channel. Used as a safety net when
    DialBegin is not delivered (e.g. direct-media flows, certain dialplan paths).
    Only triggers call_started if no active call is already tracked.
    Filters to inbound channels only (Context = from-sip or similar panel context).
    """
    # Only inbound channels from panels (context contains "from" or "intercom").
    context = (event.get("Context") or "").lower()
    if not any(k in context for k in ("from-sip", "from-internal", "intercom", "panels")):
        return

    channel_state = (event.get("ChannelStateDesc") or "").lower()
    if channel_state not in ("ring", "ringing", "up"):
        return

    call_id = event.get("Linkedid") or event.get("Uniqueid", "")
    caller = event.get("CallerIDNum", "")
    callee = event.get("Exten", "")

    if not call_id or not caller:
        return

    # Only fire if DialBegin hasn't already registered this call.
    existing = call_store.get_active()
    if existing and existing.call_id == call_id:
        return

    logger.info("ami_call_started_newchannel_fallback", call_id=call_id, caller=caller, callee=callee)

    active = call_store.on_call_started(call_id=call_id, caller=caller, callee=callee)
    caller_device_id, video_rtsp = await _lookup_caller_device(caller)
    video_src = f"panel-{caller_device_id}" if caller_device_id else None

    await event_bus.publish("call_started", {
        "call_id": call_id,
        "caller": caller,
        "callee": callee,
        "apartment_id": active.apartment_id,
        "started_at": active.started_at,
        "video_src": video_src,
    })

    from app.cloud.bridge import _build_video_urls
    video_webrtc_url, video_hls_url = _build_video_urls(caller_device_id)
    await _push_cloud("call_started", {
        "call_id": call_id,
        "caller_device_id": caller_device_id,
        "caller_sip": caller,
        "apartment_code": callee,
        "video_rtsp": video_rtsp,
        "video_webrtc_url": video_webrtc_url,
        "video_hls_url": video_hls_url,
        "started_at": active.started_at,
    })


def register_all(ami) -> None:
    """Register all handlers on the given AMIClient instance."""
    ami.register_event("DialBegin", on_dial_begin)
    ami.register_event("DialEnd", on_dial_end)
    ami.register_event("BridgeEnter", on_bridge_enter)
    ami.register_event("Hangup", on_hangup)
    ami.register_event("UserEvent", on_user_event)
    ami.register_event("Newchannel", on_newchannel)

