"""Device management routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas import (
    ActionResult,
    DeviceCreate,
    DeviceListOut,
    DeviceOut,
    DeviceUpdate,
    SipApplyRequest,
)
from app.services import connectivity_service, device_service, go2rtc_service, unlock_service
from app.services.sip_service import sip_service

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=DeviceListOut)
async def list_devices(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    device_type: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    items, total = await device_service.get_devices(
        db, skip=skip, limit=limit, device_type=device_type, enabled=enabled
    )
    return DeviceListOut(items=items, total=total)


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def create_device(
    payload: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await device_service.create_device(db, payload, actor=current_user.username)
    # Commit before side effects: emit_device_upserted opens its own session and
    # writes devices.cloud_synced — if the request transaction is still open
    # it holds a row lock on this device and the two sessions self-deadlock.
    # Committing first also makes the row visible so the device actually
    # mirrors to cloud / appears in the go2rtc rebuild (both open fresh
    # sessions). go2rtc.write_config() is a full DB rebuild — calling it
    # unconditionally keeps go2rtc.yaml in sync for any device change.
    await db.commit()
    await go2rtc_service.write_config()
    from app.cloud.bridge import cloud_bridge
    await cloud_bridge.emit_device_upserted(device.id)
    return device


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    device = await device_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.put("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await device_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    device = await device_service.update_device(db, device, payload, actor=current_user.username)
    # Commit before side effects — see create_device: emit and the go2rtc
    # rebuild both open second sessions and need the committed row.
    await db.commit()
    await go2rtc_service.write_config()
    from app.cloud.bridge import cloud_bridge
    await cloud_bridge.emit_device_upserted(device.id)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await device_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await device_service.delete_device(db, device, actor=current_user.username)
    # Commit before the go2rtc rebuild: write_config() opens a fresh session
    # and must not see the just-deleted row.
    await db.commit()
    await go2rtc_service.write_config()


@router.post("/{device_id}/barrier/open", response_model=ActionResult)
async def open_barrier(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Manually open the parking barrier — pulses the camera's AlarmOut relay.

    The whitelist auto-opens via anpr_service; this is the operator override.
    """
    device = await device_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    from app.services import barrier_service
    ok = await barrier_service.open_barrier(device)
    return ActionResult(
        success=ok,
        message="Шлагбаум открыт" if ok else "Не удалось открыть шлагбаум",
    )


@router.post("/{device_id}/test-connection", response_model=ActionResult)
async def test_connection(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await device_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return await connectivity_service.test_connection(device, db=db, actor=current_user.username)


@router.post("/{device_id}/test-unlock", response_model=ActionResult)
async def test_unlock(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await device_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return await unlock_service.test_unlock(device, db=db, actor=current_user.username)


@router.post("/{device_id}/sip-apply", response_model=ActionResult)
async def sip_apply(
    device_id: int,
    payload: SipApplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Применяет SIP-аккаунт в pjsip.conf на сервере Asterisk и перезагружает его.
    Если update_device=true — также сохраняет sip_account/sip_password в БД устройства.
    """
    device = await device_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    result = sip_service.apply_credentials(
        acct=payload.sip_account,
        password=payload.sip_password,
    )

    if result.success and payload.update_device:
        await device_service.update_device(
            db,
            device,
            DeviceUpdate(
                sip_enabled=True,
                sip_account=payload.sip_account,
                sip_password=payload.sip_password,
            ),
            actor=current_user.username,
        )

    return result


@router.get("/{device_id}/sip-status", response_model=dict)
async def sip_status(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Возвращает статус SIP-пира из Asterisk (пока заглушка)."""
    device = await device_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return await sip_service.get_peer_status(device.sip_account or str(device_id))
