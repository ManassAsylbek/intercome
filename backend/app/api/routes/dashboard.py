"""Dashboard and system info routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import ActivityLog, Device, DeviceType, RoutingRule, User
from app.schemas import (
    ActivityLogOut,
    DashboardSummary,
    HealthOut,
    SystemInfoOut,
)
from app.services.sip_service import sip_service, reload_asterisk_ami

router = APIRouter(tags=["dashboard"])


@router.get("/health", response_model=HealthOut, include_in_schema=True)
async def health():
    return HealthOut(
        status="ok",
        version="0.1.0",
        environment=settings.app_env,
    )


@router.get("/system/info", response_model=SystemInfoOut)
async def system_info(_: User = Depends(get_current_user)):
    safe_db = settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url
    return SystemInfoOut(
        server_ip=settings.server_ip,
        database_url_safe=safe_db,
        app_env=settings.app_env,
        version="0.1.0",
    )


@router.get("/system/asterisk-health")
async def asterisk_health(_: User = Depends(get_current_user)):
    """Возвращает статус подключения к Asterisk (pjsip.conf доступен?)."""
    return await sip_service.health_check()


@router.post("/system/asterisk-reload")
async def asterisk_reload(_: User = Depends(get_current_user)):
    """Перезагружает модули Asterisk через AMI: res_pjsip + dialplan."""
    return reload_asterisk_ami()


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Device counts
    total_result = await db.execute(select(func.count(Device.id)))
    total_devices = total_result.scalar_one()

    online_result = await db.execute(
        select(func.count(Device.id)).where(Device.is_online == True)
    )
    online_devices = online_result.scalar_one()

    offline_result = await db.execute(
        select(func.count(Device.id)).where(Device.is_online == False)
    )
    offline_devices = offline_result.scalar_one()

    unknown_devices = total_devices - online_devices - offline_devices

    # By type
    async def count_type(dt: DeviceType) -> int:
        r = await db.execute(select(func.count(Device.id)).where(Device.device_type == dt.value))
        return r.scalar_one()

    door_stations = await count_type(DeviceType.DOOR_STATION)
    home_stations = await count_type(DeviceType.HOME_STATION)
    guard_stations = await count_type(DeviceType.GUARD_STATION)
    sip_clients = await count_type(DeviceType.SIP_CLIENT)
    cameras = await count_type(DeviceType.CAMERA)

    # Routing rules
    total_rules_r = await db.execute(select(func.count(RoutingRule.id)))
    total_rules = total_rules_r.scalar_one()

    active_rules_r = await db.execute(
        select(func.count(RoutingRule.id)).where(RoutingRule.enabled == True)
    )
    active_rules = active_rules_r.scalar_one()

    # Recent activity
    recent_r = await db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(10)
    )
    recent_logs = recent_r.scalars().all()

    return DashboardSummary(
        total_devices=total_devices,
        online_devices=online_devices,
        offline_devices=offline_devices,
        unknown_devices=unknown_devices,
        door_stations=door_stations,
        home_stations=home_stations,
        guard_stations=guard_stations,
        sip_clients=sip_clients,
        cameras=cameras,
        total_routing_rules=total_rules,
        active_routing_rules=active_rules,
        recent_activity=[ActivityLogOut.model_validate(l) for l in recent_logs],
    )
