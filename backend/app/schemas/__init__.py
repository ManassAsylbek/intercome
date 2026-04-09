"""Pydantic schemas for the intercom management server."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import ActivityAction, DeviceType, UnlockMethod


# ─── Auth ─────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    is_superuser: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Device ───────────────────────────────────────────────────────────────────


class DeviceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    device_type: DeviceType
    ip_address: Optional[str] = Field(None, max_length=45)
    web_port: Optional[int] = Field(None, ge=1, le=65535)
    enabled: bool = True
    notes: Optional[str] = None

    # SIP
    sip_enabled: bool = False
    sip_account: Optional[str] = None
    sip_password: Optional[str] = None
    sip_server: Optional[str] = None
    sip_port: Optional[int] = Field(None, ge=1, le=65535)
    sip_proxy: Optional[str] = None

    # RTSP
    rtsp_enabled: bool = False
    rtsp_url: Optional[str] = None

    # Unlock
    unlock_enabled: bool = False
    unlock_method: UnlockMethod = UnlockMethod.NONE
    unlock_url: Optional[str] = None
    unlock_username: Optional[str] = None
    unlock_password: Optional[str] = None


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    device_type: Optional[DeviceType] = None
    ip_address: Optional[str] = None
    web_port: Optional[int] = Field(None, ge=1, le=65535)
    enabled: Optional[bool] = None
    notes: Optional[str] = None
    sip_enabled: Optional[bool] = None
    sip_account: Optional[str] = None
    sip_password: Optional[str] = None
    sip_server: Optional[str] = None
    sip_port: Optional[int] = Field(None, ge=1, le=65535)
    sip_proxy: Optional[str] = None
    rtsp_enabled: Optional[bool] = None
    rtsp_url: Optional[str] = None
    unlock_enabled: Optional[bool] = None
    unlock_method: Optional[UnlockMethod] = None
    unlock_url: Optional[str] = None
    unlock_username: Optional[str] = None
    unlock_password: Optional[str] = None


class DeviceOut(DeviceBase):
    id: int
    is_online: Optional[bool] = None
    last_seen: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeviceListOut(BaseModel):
    items: list[DeviceOut]
    total: int


# ─── Routing Rules ────────────────────────────────────────────────────────────


class RoutingRuleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    call_code: str = Field(..., min_length=1, max_length=64)
    source_device_id: Optional[int] = None
    target_device_id: Optional[int] = None
    target_sip_account: Optional[str] = None
    enabled: bool = True
    priority: int = 0
    notes: Optional[str] = None


class RoutingRuleCreate(RoutingRuleBase):
    pass


class RoutingRuleUpdate(BaseModel):
    name: Optional[str] = None
    call_code: Optional[str] = None
    source_device_id: Optional[int] = None
    target_device_id: Optional[int] = None
    target_sip_account: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    notes: Optional[str] = None


class RoutingRuleOut(RoutingRuleBase):
    id: int
    source_device: Optional[DeviceOut] = None
    target_device: Optional[DeviceOut] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoutingRuleListOut(BaseModel):
    items: list[RoutingRuleOut]
    total: int


# ─── Apartment ────────────────────────────────────────────────────────────────


class ApartmentMonitorIn(BaseModel):
    sip_account: str = Field(..., min_length=1, max_length=128)
    label: Optional[str] = Field(None, max_length=128)


class ApartmentMonitorOut(BaseModel):
    id: int
    sip_account: str
    label: Optional[str] = None

    model_config = {"from_attributes": True}


class ApartmentCreate(BaseModel):
    number: str = Field(..., min_length=1, max_length=32)
    call_code: str = Field(..., min_length=1, max_length=64)
    notes: Optional[str] = None
    enabled: bool = True
    monitors: list[ApartmentMonitorIn] = []


class ApartmentUpdate(BaseModel):
    number: Optional[str] = Field(None, min_length=1, max_length=32)
    call_code: Optional[str] = Field(None, min_length=1, max_length=64)
    notes: Optional[str] = None
    enabled: Optional[bool] = None
    monitors: Optional[list[ApartmentMonitorIn]] = None


class ApartmentOut(BaseModel):
    id: int
    number: str
    call_code: str
    notes: Optional[str] = None
    enabled: bool
    monitors: list[ApartmentMonitorOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApartmentListOut(BaseModel):
    items: list[ApartmentOut]
    total: int


# ─── Activity Log ─────────────────────────────────────────────────────────────


class ActivityLogOut(BaseModel):
    id: int
    action: ActivityAction
    actor: Optional[str] = None
    device_id: Optional[int] = None
    detail: Optional[str] = None
    success: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Dashboard ────────────────────────────────────────────────────────────────


class DashboardSummary(BaseModel):
    total_devices: int
    online_devices: int
    offline_devices: int
    unknown_devices: int
    door_stations: int
    home_stations: int
    guard_stations: int
    sip_clients: int
    cameras: int
    total_routing_rules: int
    active_routing_rules: int
    recent_activity: list[ActivityLogOut]


# ─── Health / System ──────────────────────────────────────────────────────────


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    environment: str


class SystemInfoOut(BaseModel):
    server_ip: str
    database_url_safe: str
    app_env: str
    version: str
    asterisk_integration: str = "not_configured"
    rtsp_integration: str = "not_configured"


# ─── Test action results ──────────────────────────────────────────────────────


class ActionResult(BaseModel):
    success: bool
    message: str
    detail: Optional[str] = None
    latency_ms: Optional[float] = None


# ─── SIP apply ────────────────────────────────────────────────────────────────


class SipApplyRequest(BaseModel):
    """Запрос на применение SIP-аккаунта в pjsip.conf."""
    sip_account: str = Field(..., min_length=1, max_length=64,
                             description="Номер аккаунта, например 1001 или 1002")
    sip_password: str = Field(..., min_length=1, max_length=128,
                              description="Пароль, который будет записан в pjsip.conf")
    update_device: bool = Field(
        True,
        description="Если true — сохраняет sip_account и sip_password в записи устройства в БД",
    )
