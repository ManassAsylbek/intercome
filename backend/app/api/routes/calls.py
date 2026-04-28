"""Call state, unlock, and Asterisk webhook routes."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import decode_access_token
from app.db.session import get_db
from app.events.bus import event_bus
from app.models import ActivityAction, ActivityLog, Device, User
from app.services import unlock_service
from app.services.call_store import call_store

router = APIRouter(tags=["calls"])

# ─── Internal helpers ──────

_INTERNAL_PREFIXES = ("127.", "::1", "172.", "10.", "192.168.")


def _is_internal(ip: str) -> bool:
    return any(ip.startswith(p) for p in _INTERNAL_PREFIXES)


async def _user_from_token(token: Optional[str], db: AsyncSession) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    username: Optional[str] = payload.get("sub")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


# ─── Asterisk webhook (no auth — internal network only) ───────────────────────

@router.get("/webhooks/asterisk", include_in_schema=False)
async def asterisk_webhook(
    event: str,
    request: Request,
    caller: str = "",
    callee: str = "",
    call_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Called by Asterisk dialplan via CURL(). Restricted to internal IPs."""
    client_ip = request.client.host if request.client else ""
    if not _is_internal(client_ip):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    if event == "call_start":
        await call_store.call_started(caller=caller, callee=callee, call_id=call_id)
        db.add(ActivityLog(
            action=ActivityAction.DOOR_CALL,
            actor="asterisk",
            detail=f"{caller} → {callee} | uid={call_id}",
            success=True,
        ))
        await db.commit()

    elif event == "call_end":
        await call_store.call_ended(caller=caller, call_id=call_id)
        db.add(ActivityLog(
            action=ActivityAction.DOOR_CALL_END,
            actor="asterisk",
            detail=f"call ended | caller={caller} uid={call_id}",
            success=True,
        ))
        await db.commit()

    return {"ok": True}


# ─── SSE stream ───────────────────────────────────────────────────────────────

@router.get("/events/stream")
async def sse_stream(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events stream for real-time call notifications.

    EventSource API cannot set Authorization headers, so token is passed
    as a query parameter: /api/events/stream?token=<jwt>
    """
    await _user_from_token(token, db)

    from app.events.bus import MAX_SSE_SUBS

    if event_bus.subscriber_count >= MAX_SSE_SUBS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Max SSE connections ({MAX_SSE_SUBS}) reached",
        )

    q = event_bus.subscribe()

    async def generator():
        active = call_store.get_active()
        if active:
            yield f"data: {json.dumps({'event': 'call_started', 'data': asdict(active)})}\n\n"
        else:
            yield 'data: {"event":"idle","data":{}}\n\n'

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"event":"idle","data":{}}\n\n'
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


# ─── Active call status (poll fallback) ───────────────────────────────────────

@router.get("/calls/active")
async def get_active_call(
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently active call, or {active: false} if none."""
    await _user_from_token(token, db)
    active = call_store.get_active()
    if not active:
        return {"active": False}
    return {
        "active": True,
        "call_id": active.call_id,
        "caller": active.caller,
        "callee": active.callee,
        "started_at": active.started_at,
        "apartment_id": active.apartment_id,
    }


# ─── Unlock during call ───────────────────────────────────────────────────────

@router.post("/calls/unlock")
async def unlock_during_call(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unlock the door during an active call.

    1. Verify there is an active call.
    2. Find the first unlock-enabled device.
    3. Trigger unlock via HTTP.
    4. Publish door_opened event so cloud and UI see it.
    """
    active = call_store.get_active()
    if not active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Активный звонок не найден",
        )

    result_q = await db.execute(
        select(Device).where(Device.enabled == True, Device.unlock_enabled == True)
    )
    door = result_q.scalars().first()
    if not door:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Asterisk не ответил",
        )

    action = await unlock_service.test_unlock(door, db=db, actor=current_user.username)
    await db.commit()

    if action.success:
        await event_bus.publish(
            "door_opened",
            {
                "call_id": active.call_id,
                "device_id": door.id,
                "by": "api",
            },
        )
        return {"success": True, "message": "Дверь открыта"}

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Asterisk не ответил",
    )
