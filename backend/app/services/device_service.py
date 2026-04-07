"""Device CRUD service."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ActivityAction, Device, RoutingRule
from app.schemas import DeviceCreate, DeviceUpdate


async def get_device(db: AsyncSession, device_id: int) -> Optional[Device]:
    result = await db.execute(select(Device).where(Device.id == device_id))
    return result.scalar_one_or_none()


async def get_devices(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    device_type: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> tuple[list[Device], int]:
    query = select(Device)
    count_query = select(func.count(Device.id))

    if device_type:
        query = query.where(Device.device_type == device_type)
        count_query = count_query.where(Device.device_type == device_type)
    if enabled is not None:
        query = query.where(Device.enabled == enabled)
        count_query = count_query.where(Device.enabled == enabled)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    query = query.offset(skip).limit(limit).order_by(Device.name)
    result = await db.execute(query)
    devices = result.scalars().all()
    return list(devices), total


async def create_device(db: AsyncSession, data: DeviceCreate, actor: str = "system") -> Device:
    from app.models import ActivityLog

    device = Device(**data.model_dump())
    db.add(device)
    await db.flush()

    log = ActivityLog(
        action=ActivityAction.DEVICE_CREATED,
        actor=actor,
        device_id=device.id,
        detail=f"Device '{device.name}' ({device.device_type}) created",
        success=True,
    )
    db.add(log)
    await db.flush()
    return device


async def update_device(
    db: AsyncSession, device: Device, data: DeviceUpdate, actor: str = "system"
) -> Device:
    from app.models import ActivityLog

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(device, field, value)

    log = ActivityLog(
        action=ActivityAction.DEVICE_UPDATED,
        actor=actor,
        device_id=device.id,
        detail=f"Updated fields: {list(update_data.keys())}",
        success=True,
    )
    db.add(log)
    await db.flush()
    return device


async def delete_device(db: AsyncSession, device: Device, actor: str = "system") -> None:
    from app.models import ActivityLog

    log = ActivityLog(
        action=ActivityAction.DEVICE_DELETED,
        actor=actor,
        device_id=None,
        detail=f"Device '{device.name}' (id={device.id}) deleted",
        success=True,
    )
    db.add(log)
    await db.delete(device)
    await db.flush()
