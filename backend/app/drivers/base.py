"""Vendor access-driver abstraction (multi-vendor support, phase 1).

One bridge serves door devices from DIFFERENT vendors (Dahua over HTTP, Leelen
over MQTT, more later). Each vendor gets an ``AccessDriver``; the registry
(``app.drivers.registry``) picks one per ``Device`` by ``device.vendor``. The
cloud stays vendor-agnostic — it issues unlock_door / enroll_face / ... and the
driver translates to the vendor's wire protocol, while EVERY driver emits
identical normalized events via the shared ``_emit``.

Drivers are stateless singletons: all per-device state lives on the Device row,
so one instance serves every device of that vendor.

A driver advertises what it can do via ``capabilities()`` so the bridge degrades
gracefully (clean "unsupported" ack) instead of crashing on an op the vendor
doesn't implement. Unimplemented methods here default to that "unsupported" ack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.core.logging import get_logger

if TYPE_CHECKING:  # avoid importing the ORM at module load
    from app.models import Device

logger = get_logger(__name__)


def unsupported(op: str, vendor: str | None) -> dict:
    """Standard 'this vendor can't do that' ack (never raises → no 500s)."""
    return {
        "success": False,
        "message": f"{op} unsupported on vendor '{vendor or 'generic'}'",
    }


class AccessDriver:
    """Base access driver. Subclasses override the ops they support and list
    them in ``capabilities()``."""

    #: vendor key this driver is registered under (subclasses set it).
    vendor: str = "generic"

    def capabilities(self) -> set[str]:
        """Operations this driver supports, e.g.
        ``{'open_door', 'open_barrier', 'enroll_face', 'delete_face',
        'enroll_credential', 'delete_credential', 'event_stream'}``.
        Empty by default — subclasses widen it. Pure/sync, no I/O."""
        return set()

    async def open(
        self, device: "Device", *, kind: str = "door", db=None, actor: str = "system"
    ) -> dict:
        """Physically open a door (``kind='door'``) or barrier (``kind='barrier'``).
        Returns an ack-shaped dict ``{success, message, method, latency_ms}`` — the
        command handler adds device_id/device_name."""
        return unsupported(f"open_{kind}", getattr(device, "vendor", None))

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
        """Push a face credential onto the device (faces live on-device)."""
        return unsupported("enroll_face", getattr(device, "vendor", None))

    async def delete_face(self, device: "Device", *, person_id: str) -> dict:
        """Remove an enrolled face by person/credential id. Idempotent."""
        return unsupported("delete_face", getattr(device, "vendor", None))

    async def enroll_credential(
        self,
        device: "Device",
        *,
        kind: str,
        value: str,
        person_id: str,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
    ) -> dict:
        """Push a QR token / RFID card onto the device (``kind`` = 'qr'|'card')."""
        return unsupported("enroll_credential", getattr(device, "vendor", None))

    async def delete_credential(
        self,
        device: "Device",
        *,
        kind: str,
        value: Optional[str] = None,
        person_id: Optional[str] = None,
    ) -> dict:
        """Remove a QR/card credential by value or person_id. Idempotent."""
        return unsupported("delete_credential", getattr(device, "vendor", None))

    async def run_event_stream(self, device: "Device") -> None:
        """Long-lived coroutine (runs until cancelled) that subscribes to the
        vendor's event source and emits NORMALIZED events via ``_emit``.
        Must re-raise ``CancelledError`` and self-reconnect on other errors.
        Default: no event source."""
        return None

    async def _emit(self, device: "Device", name: str, payload: dict) -> None:
        """Publish a normalized event both ways — local SSE (admin UI) and the
        cloud bridge (mobile) — with ``device_local_id`` + ``vendor`` injected so
        every vendor produces an identical envelope. Best-effort: never raises."""
        data = {
            **payload,
            "device_local_id": device.id,
            "vendor": getattr(device, "vendor", None),
        }
        try:
            from app.events.bus import event_bus

            await event_bus.publish(name, data)
        except Exception as exc:  # best-effort local SSE
            logger.warning("driver_emit_local_failed", event=name, error=str(exc))
        try:
            from app.cloud.bridge import cloud_bridge

            await cloud_bridge.send_event(name, data)
        except Exception as exc:  # best-effort cloud relay
            logger.warning("driver_emit_cloud_failed", event=name, error=str(exc))
