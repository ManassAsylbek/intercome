"""Read-only routes for cloud-defined entrances.

Bridge does NOT create or edit entrances locally — they are owned by cloud
and pushed via the ``bootstrap_snapshot`` event. We expose a list endpoint
so that the admin UI can populate an entrance picker when creating
apartments and devices (each apartment/device must reference one
``entrance_id`` for the cloud mirror to accept it).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Entrance, User
from app.schemas import EntranceOut

router = APIRouter(prefix="/entrances", tags=["entrances"])


@router.get("", response_model=list[EntranceOut])
async def list_entrances(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Entrance).order_by(Entrance.id))
    return list(result.scalars().all())
