"""Call events, SSE stream and Asterisk webhook routes."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import ActivityAction, ActivityLog, Device, User
from app.services import unlock_service
from app.services.call_store import call_store

router = APIRouter(tags=["calls"])

# ─── Internal helpers ─────────────────────────────────────────────────────────

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
    q = call_store.subscribe()

    async def generator():
        # Immediately send current state on connect
        active = call_store.get_active()
        if active:
            yield f"data: {json.dumps({'event': 'call_started', 'data': asdict(active)})}\n\n"
        else:
            yield f"data: {json.dumps({'event': 'idle', 'data': {}})}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # SSE comment keepalive
        finally:
            call_store.unsubscribe(q)

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
    await _user_from_token(token, db)
    active = call_store.get_active()
    if not active:
        return {"active": False, "call": None}
    return {"active": True, "call": asdict(active)}


# ─── Unlock during call ───────────────────────────────────────────────────────

@router.post("/calls/unlock")
async def unlock_during_call(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unlock the first unlock-enabled door station."""
    result = await db.execute(
        select(Device).where(Device.enabled == True, Device.unlock_enabled == True)
    )
    door = result.scalars().first()
    if not door:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No unlock-enabled device found",
        )
    action = await unlock_service.test_unlock(door, db=db, actor=current_user.username)
    await db.commit()
    return action
