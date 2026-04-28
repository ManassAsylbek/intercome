"""In-memory store for the currently active call."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ActiveCall:
    call_id: str
    caller: str
    callee: str
    started_at: str = field(default_factory=_utcnow_iso)
    apartment_id: Optional[int] = None


class CallStore:
    """Thread-safe (asyncio) state for the single active call."""

    def __init__(self) -> None:
        self._active: Optional[ActiveCall] = None

    def get_active(self) -> Optional[ActiveCall]:
        return self._active

    def on_call_started(
        self,
        call_id: str,
        caller: str,
        callee: str,
        apartment_id: Optional[int] = None,
    ) -> ActiveCall:
        self._active = ActiveCall(
            call_id=call_id,
            caller=caller,
            callee=callee,
            apartment_id=apartment_id,
        )
        return self._active

    def on_call_ended(self, call_id: str) -> None:
        if self._active and self._active.call_id == call_id:
            self._active = None

    # ── Legacy helpers kept for the webhook fallback path ──────────────────

    async def call_started(
        self, caller: str, callee: str, call_id: str = ""
    ) -> None:
        from app.events.bus import event_bus

        active = self.on_call_started(call_id=call_id, caller=caller, callee=callee)
        await event_bus.publish("call_started", asdict(active))

    async def call_ended(self, caller: str = "", call_id: str = "") -> None:
        from app.events.bus import event_bus

        self.on_call_ended(call_id)
        await event_bus.publish(
            "call_ended",
            {"call_id": call_id, "ended_at": _utcnow_iso(), "reason": "other"},
        )


call_store = CallStore()

