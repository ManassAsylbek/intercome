"""Plate whitelist routes (parking ANPR).

The cloud is the sole writer for the whitelist — plates are managed from
the mobile app / CRM and propagated to bridges via WS (``plate_upsert`` /
``plate_delete``) and the ``bootstrap_snapshot``'s ``plates`` block. The
local bridge stores a read-only mirror so ``anpr_service`` can match in
real time without round-tripping on every camera event.

Local CRUD (POST/PUT/DELETE) is intentionally **disabled** here — those
verbs return ``423 Locked`` with a message pointing the operator at the
cloud-managed surface. ``GET`` endpoints stay open for debug and admin UI.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ActivityAction, ActivityLog, PlateAccessLog, PlateWhitelist, User
from app.schemas import (
    PlateAccessLogListOut,
    PlateCreate,
    PlateListOut,
    PlateOut,
    PlateUpdate,
)
from app.services import plate_service

router = APIRouter(prefix="/plates", tags=["plates"])

_DUPLICATE = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Этот номер уже в списке"
)

_CLOUD_MANAGED = HTTPException(
    status_code=status.HTTP_423_LOCKED,
    detail=(
        "Номера управляются из облака — добавляйте/редактируйте через мобильное "
        "приложение или CRM. Локальное редактирование на бридже отключено."
    ),
)


async def _get_plate(db: AsyncSession, plate_id: int) -> PlateWhitelist | None:
    result = await db.execute(
        select(PlateWhitelist).where(PlateWhitelist.id == plate_id)
    )
    return result.scalar_one_or_none()


def _normalized_or_422(raw: str) -> str:
    plate = plate_service.normalize_plate(raw)
    if not plate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Номер пустой после нормализации",
        )
    return plate


@router.get("", response_model=PlateListOut)
async def list_plates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    total = (await db.execute(select(func.count(PlateWhitelist.id)))).scalar_one()
    result = await db.execute(
        select(PlateWhitelist).order_by(PlateWhitelist.plate)
    )
    return PlateListOut(items=list(result.scalars().all()), total=total)


@router.post("", response_model=PlateOut, status_code=status.HTTP_201_CREATED)
async def create_plate(
    payload: PlateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cloud-managed — see module docstring. Always raises 423."""
    raise _CLOUD_MANAGED


@router.get("/log", response_model=PlateAccessLogListOut)
async def list_access_log(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Журнал проездов — последние распознавания номеров ANPR-камерами.

    Declared before ``/{plate_id}`` so the literal path wins over the int
    path-param.
    """
    total = (await db.execute(select(func.count(PlateAccessLog.id)))).scalar_one()
    result = await db.execute(
        select(PlateAccessLog)
        .order_by(PlateAccessLog.created_at.desc())
        .limit(limit)
    )
    return PlateAccessLogListOut(items=list(result.scalars().all()), total=total)


@router.get("/{plate_id}", response_model=PlateOut)
async def get_plate(
    plate_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    plate = await _get_plate(db, plate_id)
    if not plate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plate not found")
    return plate


@router.put("/{plate_id}", response_model=PlateOut)
async def update_plate(
    plate_id: int,
    payload: PlateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cloud-managed — see module docstring. Always raises 423."""
    raise _CLOUD_MANAGED


@router.delete("/{plate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plate(
    plate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cloud-managed — see module docstring. Always raises 423."""
    raise _CLOUD_MANAGED
