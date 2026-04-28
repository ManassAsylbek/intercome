"""Apartment management routes."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.events.bus import event_bus
from app.models import Apartment, ApartmentMonitor, Device, User, WebrtcEndpoint
from app.schemas import (
    ActionResult,
    ApartmentCreate,
    ApartmentListOut,
    ApartmentOut,
    ApartmentUpdate,
)
from app.services.sip_service import sip_service, write_apartments_dialplan

router = APIRouter(prefix="/apartments", tags=["apartments"])


async def _get_apartment(db: AsyncSession, apt_id: int) -> Apartment | None:
    result = await db.execute(
        select(Apartment)
        .options(selectinload(Apartment.monitors), selectinload(Apartment.source_devices))
        .where(Apartment.id == apt_id)
    )
    return result.scalar_one_or_none()


async def _rebuild_dialplan(db: AsyncSession) -> None:
    """Regenerate extensions.conf (main) AND extensions_apartments.conf from all enabled apartments."""
    result = await db.execute(
        select(Apartment)
        .options(selectinload(Apartment.monitors))
        .where(Apartment.enabled == True)  # noqa: E712
        .order_by(Apartment.number)
    )
    apartments = result.scalars().all()

    apt_dicts = [
        {
            "call_code": apt.call_code,
            "monitors": [m.sip_account for m in apt.monitors],
            "cloud_relay_enabled": apt.cloud_relay_enabled,
            "cloud_sip_account": apt.cloud_sip_account,
        }
        for apt in apartments
        if apt.call_code
    ]

    loop = asyncio.get_event_loop()
    # Main extensions.conf (legacy webhooks dialplan)
    await loop.run_in_executor(None, sip_service.generate_extensions_conf, apt_dicts)
    # WebRTC-aware extensions_apartments.conf (spec section 5)
    await loop.run_in_executor(None, write_apartments_dialplan, apt_dicts)


@router.get("", response_model=ApartmentListOut)
async def list_apartments(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    total = (await db.execute(select(func.count(Apartment.id)))).scalar_one()
    result = await db.execute(
        select(Apartment)
        .options(selectinload(Apartment.monitors), selectinload(Apartment.source_devices))
        .order_by(Apartment.number)
    )
    items = result.scalars().all()
    return ApartmentListOut(items=list(items), total=total)


@router.post("", response_model=ApartmentOut, status_code=status.HTTP_201_CREATED)
async def create_apartment(
    payload: ApartmentCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    apt = Apartment(
        number=payload.number,
        call_code=payload.call_code,
        notes=payload.notes,
        enabled=payload.enabled,
        cloud_relay_enabled=payload.cloud_relay_enabled,
        cloud_sip_account=payload.cloud_sip_account,
    )
    db.add(apt)
    await db.flush()

    for m in payload.monitors:
        db.add(ApartmentMonitor(apartment_id=apt.id, sip_account=m.sip_account, label=m.label))

    await db.commit()
    apt = await _get_apartment(db, apt.id)
    await _rebuild_dialplan(db)
    return apt


@router.get("/{apt_id}", response_model=ApartmentOut)
async def get_apartment(
    apt_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    apt = await _get_apartment(db, apt_id)
    if not apt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apartment not found")
    return apt


@router.put("/{apt_id}", response_model=ApartmentOut)
async def update_apartment(
    apt_id: int,
    payload: ApartmentUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    apt = await _get_apartment(db, apt_id)
    if not apt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apartment not found")

    if payload.number is not None:
        apt.number = payload.number
    if payload.call_code is not None:
        apt.call_code = payload.call_code
    if payload.notes is not None:
        apt.notes = payload.notes
    if payload.enabled is not None:
        apt.enabled = payload.enabled
    if payload.cloud_relay_enabled is not None:
        apt.cloud_relay_enabled = payload.cloud_relay_enabled
    if payload.cloud_sip_account is not None:
        apt.cloud_sip_account = payload.cloud_sip_account

    # Replace monitors if provided
    if payload.monitors is not None:
        await db.execute(
            ApartmentMonitor.__table__.delete().where(
                ApartmentMonitor.apartment_id == apt_id
            )
        )
        for m in payload.monitors:
            db.add(ApartmentMonitor(apartment_id=apt_id, sip_account=m.sip_account, label=m.label))

    await db.commit()
    apt = await _get_apartment(db, apt_id)
    await _rebuild_dialplan(db)
    return apt


@router.delete("/{apt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_apartment(
    apt_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    apt = await _get_apartment(db, apt_id)
    if not apt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apartment not found")
    await db.delete(apt)
    await db.commit()
    await _rebuild_dialplan(db)


@router.post("/sync-dialplan", response_model=ActionResult)
async def sync_dialplan(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Manually regenerate extensions.conf from current apartments."""
    await _rebuild_dialplan(db)
    return ActionResult(success=True, message="Dialplan синхронизирован")


# ─── POST /api/apartments/{call_code}/monitors ────────────────────────────────


class MonitorsRequest(BaseModel):
    monitors: list[str]


@router.post("/{call_code}/monitors")
async def set_apartment_monitors(
    call_code: str,
    payload: MonitorsRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Set the list of WebRTC extension(s) that ring when *call_code* is dialled.

    Idempotent — replaces the existing monitor list completely.
    Validates that every extension exists in webrtc_endpoints.
    Regenerates extensions_apartments.conf and reloads dialplan.
    """
    result = await db.execute(
        select(Apartment)
        .options(selectinload(Apartment.monitors))
        .where(Apartment.call_code == call_code)
    )
    apt = result.scalar_one_or_none()
    if not apt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Квартира не найдена")

    # Validate all extensions exist in webrtc_endpoints table.
    unknown: list[str] = []
    for ext in payload.monitors:
        res = await db.execute(
            select(WebrtcEndpoint).where(WebrtcEndpoint.extension == ext)
        )
        if not res.scalar_one_or_none():
            unknown.append(ext)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown extensions (not provisioned): {', '.join(unknown)}",
        )

    # Replace monitor list.
    await db.execute(
        ApartmentMonitor.__table__.delete().where(ApartmentMonitor.apartment_id == apt.id)
    )
    for ext in payload.monitors:
        db.add(ApartmentMonitor(apartment_id=apt.id, sip_account=ext, label=None))
    await db.commit()

    # Regenerate dialplan files.
    await _rebuild_dialplan(db)

    # Optional SSE notification for CRM UI.
    await event_bus.publish(
        "monitors_changed",
        {"apartment": call_code, "monitors": payload.monitors},
    )

    return {
        "success": True,
        "apartment": call_code,
        "monitors": payload.monitors,
    }
