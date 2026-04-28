"""GET /api/events/stream — Server-Sent Events for real-time intercom events."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.events.bus import MAX_SSE_SUBS, event_bus
from app.models import User
from app.services.call_store import call_store

router = APIRouter(tags=["events"])

_KEEPALIVE_MSG = 'data: {"event":"idle","data":{}}\n\n'
_KEEPALIVE_INTERVAL = 25.0  # seconds — must be < typical nginx/proxy idle timeout


async def _user_from_token(token: Optional[str], db: AsyncSession) -> User:
    """Validate query-param JWT (EventSource cannot send Authorization headers)."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token required")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    username: Optional[str] = payload.get("sub")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.get("/events/stream")
async def sse_stream(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Long-lived SSE stream.

    Connect: GET /api/events/stream?token=<jwt>
    Content-Type: text/event-stream

    Message format (every line):
        data: {"event":"<name>","data":{...}}\\n\\n

    Keep-alive every 25 s:
        data: {"event":"idle","data":{}}\\n\\n
    """
    await _user_from_token(token, db)

    if event_bus.subscriber_count >= MAX_SSE_SUBS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Max SSE connections ({MAX_SSE_SUBS}) reached",
        )

    q = event_bus.subscribe()

    async def generator():
        # Send current state immediately so the client is in sync.
        active = call_store.get_active()
        if active:
            msg = json.dumps({"event": "call_started", "data": asdict(active)})
            yield f"data: {msg}\n\n"
        else:
            yield _KEEPALIVE_MSG

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_INTERVAL)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield _KEEPALIVE_MSG
        finally:
            event_bus.unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
