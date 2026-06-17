"""One-time guest-QR door unlock — bridge → cloud relay (producer side).

Scenario: a resident generates a single-use guest QR in the app; the guest shows
it to a door panel; the panel decodes it and we forward the decoded text to the
cloud as a ``qr_scanned`` event. The cloud holds all validation (TTL / single-use /
scope) and, when valid, sends back the EXISTING ``unlock_door`` command which opens
the door as usual (see app.cloud.bridge._cmd_unlock_door). We validate nothing here.

Only codes carrying our prefix ``DMF1:`` are forwarded — any other QR is foreign
and is dropped so the cloud only ever sees our tokens.

PRODUCER NOTE (stub): there is no in-repo path yet that pulls a decoded QR off a
panel. A real producer must subscribe to the panel's scan/access event stream,
which depends on the panel model (cf. anpr_service's Dahua eventManager long-poll
in app/services/anpr_service.py). Until that exists, ``handle_scan`` is driven by
the test endpoint ``POST /devices/{id}/qr-scan``; a real panel listener should call
this same ``handle_scan`` once the device integration is built.

Wire envelope: cloud_bridge.send_event emits {"type":"qr_scanned","ts":...,"data":
{code, device_local_id, scanned_at}} — the event name is the top-level ``type``,
NOT a nested {"type":"event","event":"qr_scanned"} wrapper.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Prefix the cloud puts on our QR tokens so a panel can tell our QR from any other.
QR_PREFIX = "DMF1:"

#: Hard cap on the decoded QR text we will forward. The REST schema also enforces
#: this, but a future real panel listener may call ``handle_scan`` directly, so we
#: re-check here. Drop (do not truncate) — a truncated token is a corrupted token.
MAX_QR_LEN = 512


def _utcnow() -> str:
    """UTC ISO-8601 with trailing Z (matches app.cloud.bridge._utcnow)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def handle_scan(
    code: str,
    device_local_id: int,
    scanned_at: str | None = None,
) -> dict:
    """Forward a panel-scanned QR to the cloud iff it is one of ours (DMF1:).

    Best-effort cloud relay: if the bridge is offline the call does not raise — it
    returns ``forwarded=False`` so the caller (panel/test) can react.

    Args:
        code: decoded QR text exactly as the panel read it.
        device_local_id: bridge-local id of the panel/door that scanned.
        scanned_at: ISO-8601 UTC; filled in by us if omitted.
    """
    code = (code or "").strip()

    # Drop foreign QRs here so the cloud only ever receives DMF1: tokens.
    if not code.startswith(QR_PREFIX):
        logger.info(
            "qr_scan_ignored_foreign",
            device_local_id=device_local_id,
            sample=code[:12],
        )
        return {"forwarded": False, "reason": "not_a_dmf_code"}

    # Bare prefix with no token, or implausibly long input — drop without bothering
    # the cloud (both are guaranteed-invalid; the cloud holds real validation).
    if len(code) <= len(QR_PREFIX):
        logger.info("qr_scan_empty_token", device_local_id=device_local_id)
        return {"forwarded": False, "reason": "empty_token"}
    if len(code) > MAX_QR_LEN:
        logger.info("qr_scan_too_long", device_local_id=device_local_id, code_len=len(code))
        return {"forwarded": False, "reason": "too_long"}

    payload = {
        "code": code,
        "device_local_id": device_local_id,
        "scanned_at": scanned_at or _utcnow(),
    }

    forwarded = False
    reason: str | None = None
    try:
        # Lazy import (matches anpr_service) to avoid a circular import at module
        # load: bridge imports services; services import bridge only at call time.
        from app.cloud.bridge import cloud_bridge

        connected = cloud_bridge.is_connected  # @property, not a method
        await cloud_bridge.send_event("qr_scanned", payload)
        # send_event only enqueues; report delivery honestly — True only when the
        # bridge is connected right now (this feature needs a live link to validate
        # in time). If offline the event is still queued (best-effort) but the panel
        # must treat it as not-delivered.
        forwarded = connected
        if not connected:
            reason = "bridge_offline"
    except Exception as exc:  # best-effort relay; never break the scan path
        reason = "publish_failed"
        logger.warning(
            "qr_scan_cloud_publish_failed",
            error=str(exc),
            device_local_id=device_local_id,
        )

    logger.info(
        "qr_scanned",
        device_local_id=device_local_id,
        forwarded=forwarded,
        code_len=len(code),
    )
    result = {
        "forwarded": forwarded,
        "code": payload["code"],
        "device_local_id": device_local_id,
        "scanned_at": payload["scanned_at"],
    }
    if reason:
        result["reason"] = reason
    return result
