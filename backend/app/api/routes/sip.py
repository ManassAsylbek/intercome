"""POST /api/sip/webrtc-endpoint — provision a WebRTC SIP endpoint in Asterisk."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, WebrtcEndpoint
from app.services.sip_service import upsert_webrtc_conf

router = APIRouter(prefix="/sip", tags=["sip"])


class WebrtcEndpointRequest(BaseModel):
    extension: str = Field(..., min_length=4, max_length=10)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("extension")
    @classmethod
    def extension_digits_only(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("extension must contain digits only (4–10 chars)")
        return v

    @field_validator("password")
    @classmethod
    def password_printable_ascii(cls, v: str) -> str:
        if not all(32 <= ord(c) <= 126 for c in v):
            raise ValueError("password must contain printable ASCII characters only")
        return v


@router.post("/webrtc-endpoint", status_code=status.HTTP_200_OK)
async def create_webrtc_endpoint(
    payload: WebrtcEndpointRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Provision (or reprovision) a WebRTC SIP endpoint for a mobile client.

    Always idempotent — safe to call again on password rotation.
    Writes to pjsip_webrtc.conf (NOT the main pjsip.conf) and triggers
    a debounced res_pjsip.so reload.
    """
    # Upsert in DB (audit + self-healing at startup).
    result = await db.execute(
        select(WebrtcEndpoint).where(WebrtcEndpoint.extension == payload.extension)
    )
    endpoint = result.scalar_one_or_none()
    if endpoint:
        endpoint.password = payload.password
    else:
        endpoint = WebrtcEndpoint(extension=payload.extension, password=payload.password)
        db.add(endpoint)
    await db.commit()

    # Update pjsip_webrtc.conf and schedule debounced reload.
    ok, msg = await upsert_webrtc_conf(payload.extension, payload.password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Asterisk reload failed: {msg}",
        )

    return {"success": True, "extension": payload.extension}
