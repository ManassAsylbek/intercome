"""In-memory store for active call state and SSE subscribers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ActiveCall:
    caller: str
    callee: str
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    call_id: str = ""


class CallStore:
    def __init__(self) -> None:
        self._active: Optional[ActiveCall] = None
        self._queues: list[asyncio.Queue] = []

    def get_active(self) -> Optional[ActiveCall]:
        return self._active

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=20)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def _broadcast(self, event: str, data: dict) -> None:
        msg = json.dumps({"event": event, "data": data})
        dead: list[asyncio.Queue] = []
        for q in self._queues:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    async def call_started(
        self, caller: str, callee: str, call_id: str = ""
    ) -> None:
        self._active = ActiveCall(caller=caller, callee=callee, call_id=call_id)
        await self._broadcast("call_started", asdict(self._active))

    async def call_ended(self, caller: str = "", call_id: str = "") -> None:
        self._active = None
        await self._broadcast("call_ended", {"caller": caller, "call_id": call_id})


call_store = CallStore()
