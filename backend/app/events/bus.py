"""In-memory pub/sub event bus for SSE fan-out."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_SSE_SUBS = 50


class EventBus:
    """Fan-out message bus: AMI consumer publishes, each SSE connection subscribes."""

    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    async def publish(self, event: str, data: dict) -> None:
        msg = json.dumps({"event": event, "data": data})
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Slow subscriber — drop message, don't close connection.
                # On reconnect, subscriber fetches /calls/active to resync.
                logger.warning("sse_queue_full_drop", event=event, subs=len(self._subs))

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)


# Module-level singleton — imported by consumer and SSE routes.
event_bus = EventBus()
