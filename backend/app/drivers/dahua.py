"""Dahua access driver — wraps the existing Dahua HTTP services.

Door open uses the generic HTTP-unlock path (the device's ``unlock_url`` /cgi-bin/
endpoint, Basic→Digest) inherited from :class:`GenericHttpDriver`. Barrier open
pulses the Dahua AlarmOut relay via ``barrier_service``. Event-stream (ANPR /
AccessControl) and face enrolment land in later phases — until then this driver
keeps the existing per-call behaviour, just reached through the registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.drivers.registry import GenericHttpDriver

if TYPE_CHECKING:
    from app.models import Device


class DahuaDriver(GenericHttpDriver):
    vendor = "dahua"

    def capabilities(self) -> set[str]:
        # door inherited (HTTP unlock_url) + Dahua AlarmOut barrier pulse.
        return {"open_door", "open_barrier"}

    async def open(self, device: "Device", *, kind: str = "door", db=None, actor: str = "system"):
        if kind == "barrier":
            from app.services import barrier_service  # lazy

            return await barrier_service.open_barrier(device)  # bool (unchanged contract)
        return await super().open(device, kind=kind, db=db, actor=actor)  # door → ActionResult
