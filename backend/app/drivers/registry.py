"""Access-driver registry — picks an :class:`AccessDriver` for a Device.

Routing is by ``device.vendor``. A NULL/unknown vendor falls back to
:class:`GenericHttpDriver` (today's ``unlock_url`` HTTP-open path), so legacy
rows and not-yet-classified devices keep working with ZERO behaviour change.

Vendor drivers register themselves as they land:
  • phase 2 — ``register_driver('dahua', DahuaDriver())``
  • phase 3 — ``register_driver('leelen', LeelenDriver())``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.drivers.base import AccessDriver, unsupported

if TYPE_CHECKING:
    from app.models import Device

logger = get_logger(__name__)


class GenericHttpDriver(AccessDriver):
    """Default driver: open via the device's admin-configured ``unlock_url`` /
    ``unlock_method`` using ``unlock_service`` (Basic→Digest fallback). No enroll,
    no event stream. Covers any plain-HTTP door — including the Leelen
    ``:8000/unlock`` panel — until a vendor-specific driver is registered."""

    vendor = "generic"

    def capabilities(self) -> set[str]:
        return {"open_door"}

    async def open(self, device: "Device", *, kind: str = "door", db=None, actor: str = "system"):
        """Door open via the device's unlock_url, returning the unlock_service
        ActionResult unchanged so the door call-sites are a drop-in swap. Non-door
        kinds are unsupported on the generic driver (gate via capabilities())."""
        if kind != "door":
            return unsupported(f"open_{kind}", getattr(device, "vendor", None))
        from app.services import unlock_service  # lazy: avoid services graph at import

        return await unlock_service.test_unlock(device, db=db, actor=actor)


#: Shared default for vendor NULL / unknown.
_DEFAULT = GenericHttpDriver()

#: vendor key (lowercased) → driver singleton. Populated by ``register_driver``.
_DRIVERS: dict[str, AccessDriver] = {}


def register_driver(vendor: str, driver: AccessDriver) -> None:
    """Register a driver for a vendor key (idempotent overwrite)."""
    _DRIVERS[vendor.strip().lower()] = driver
    logger.info("access_driver_registered", vendor=vendor.strip().lower())


def get_driver(device: "Device") -> AccessDriver:
    """Return the AccessDriver for ``device`` by its ``vendor`` (case-insensitive),
    or the generic HTTP default for NULL/unknown vendors."""
    vendor = (getattr(device, "vendor", None) or "").strip().lower()
    return _DRIVERS.get(vendor, _DEFAULT)
