"""AMI event consumer: maps Asterisk events → EventBus + CloudBridge."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.events.bus import event_bus
from app.services.call_store import call_store

logger = get_logger(__name__)


async def _lookup_caller_device(sip_account: str) -> tuple[int | None, str | None]:
    """Resolve caller SIP → (device_id, rtsp_url) for cloud call_started event."""
    if not sip_account:
        return None, None
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models import Device

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Device).where(
                    Device.sip_account == sip_account, Device.enabled == True  # noqa: E712
                )
            )
            dev = result.scalars().first()
            if not dev:
                return None, None
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
    """DialBegin → call_started (local SSE + cloud WS)."""
    call_id = event.get("Linkedid") or event.get("Uniqueid", "")
    caller = event.get("CallerIDNum", "")
    callee = event.get("DestExten") or event.get("Exten", "")

    if not call_id:
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
    """DialEnd → call_ended."""
    call_id = event.get("Linkedid") or event.get("Uniqueid", "")
    dial_status = (event.get("DialStatus") or "").upper()
    reason = _DIAL_STATUS_MAP.get(dial_status, "other")
    answered_by = event.get("DestChannel", "")  # channel that answered

    active = call_store.get_active()
    duration = _duration_since(active.started_at) if active and active.call_id == call_id else None
    call_store.on_call_ended(call_id)

    ended_data = {"call_id": call_id, "ended_at": _utcnow(), "reason": reason}
    await event_bus.publish("call_ended", ended_data)
    await _push_cloud("call_ended", {
        **ended_data,
        "answered_by_sip": _extract_extension(answered_by) if reason == "answered" else None,
        "duration_seconds": duration,
    })
    logger.info("ami_call_ended_dial_end", call_id=call_id, reason=reason)


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
    """Hangup fallback — fires only when this call_id is still active."""
    call_id = event.get("Linkedid") or event.get("Uniqueid", "")
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


def register_all(ami) -> None:
    """Register all handlers on the given AMIClient instance."""
    ami.register_event("DialBegin", on_dial_begin)
    ami.register_event("DialEnd", on_dial_end)
    ami.register_event("BridgeEnter", on_bridge_enter)
    ami.register_event("Hangup", on_hangup)
    ami.register_event("UserEvent", on_user_event)

