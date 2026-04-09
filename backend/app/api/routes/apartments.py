"""Apartment management routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Apartment, ApartmentMonitor, User
from app.schemas import (
    ActionResult,
    ApartmentCreate,
    ApartmentListOut,
    ApartmentOut,
    ApartmentUpdate,
)
from app.services.sip_service import sip_service

router = APIRouter(prefix="/apartments", tags=["apartments"])


async def _get_apartment(db: AsyncSession, apt_id: int) -> Apartment | None:
    result = await db.execute(
        select(Apartment)
        .options(selectinload(Apartment.monitors))
        .where(Apartment.id == apt_id)
    )
    return result.scalar_one_or_none()


async def _rebuild_dialplan(db: AsyncSession) -> None:
    """Regenerate extensions.conf from all enabled apartments."""
    result = await db.execute(
        select(Apartment)
        .options(selectinload(Apartment.monitors))
        .where(Apartment.enabled == True)  # noqa: E712
        .order_by(Apartment.number)
    )
    apartments = result.scalars().all()

    rules_by_code: dict[str, list[str]] = {}
    for apt in apartments:
        if not apt.call_code:
            continue
        rules_by_code[apt.call_code] = [m.sip_account for m in apt.monitors]

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sip_service.generate_extensions_conf, rules_by_code)


@router.get("", response_model=ApartmentListOut)
async def list_apartments(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    total = (await db.execute(select(func.count(Apartment.id)))).scalar_one()
    result = await db.execute(
        select(Apartment)
        .options(selectinload(Apartment.monitors))
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
