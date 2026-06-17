"""SQLAlchemy ORM models for the intercom management server."""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Enums ────────────────────────────────────────────────────────────────────


class DeviceType(str, enum.Enum):
    DOOR_STATION = "door_station"
    HOME_STATION = "home_station"
    GUARD_STATION = "guard_station"
    SIP_CLIENT = "sip_client"
    CAMERA = "camera"


class UnlockMethod(str, enum.Enum):
    HTTP_GET = "http_get"
    HTTP_POST = "http_post"
    SIP_DTMF = "sip_dtmf"
    NONE = "none"


class ActivityAction(str, enum.Enum):
    DEVICE_CREATED = "device_created"
    DEVICE_UPDATED = "device_updated"
    DEVICE_DELETED = "device_deleted"
    UNLOCK_TEST = "unlock_test"
    CONNECTION_TEST = "connection_test"
    LOGIN = "login"
    RULE_CREATED = "rule_created"
    RULE_UPDATED = "rule_updated"
    RULE_DELETED = "rule_deleted"
    PLATE_CREATED = "plate_created"
    PLATE_UPDATED = "plate_updated"
    PLATE_DELETED = "plate_deleted"
    DOOR_CALL = "door_call"
    DOOR_CALL_END = "door_call_end"


# ─── Models ───────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    device_type: Mapped[DeviceType] = mapped_column(
        Enum(DeviceType, native_enum=False), nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    web_port: Mapped[int | None] = mapped_column(Integer, nullable=True, default=80)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cloud mirror: identity + sync state. mac_address is the natural key
    # cloud uses to track the same physical device across moves; cloud_id is
    # the authoritative cloud-side id we cache so we don't re-create rows.
    mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Access-integration driver selector: 'dahua' | 'leelen' | ... (None → generic
    # HTTP-unlock default). Distinct from `model` (free-text hardware name); this
    # picks which AccessDriver the bridge uses for open / enroll / event-stream.
    vendor: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entrance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("entrances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cloud_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    cloud_synced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_cloud_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SIP
    sip_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sip_account: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sip_password: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sip_server: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sip_port: Mapped[int | None] = mapped_column(Integer, nullable=True, default=5060)
    sip_proxy: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # RTSP
    rtsp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rtsp_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ANPR / parking barrier — set on Dahua ITC ANPR cameras. When true the
    # anpr_service keeps a long-poll event subscription to this camera and
    # opens the barrier (AlarmOut[0] relay) on a whitelisted plate.
    anpr_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # HTTP unlock
    unlock_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    unlock_method: Mapped[UnlockMethod] = mapped_column(
        Enum(UnlockMethod, native_enum=False), default=UnlockMethod.NONE
    )
    unlock_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    unlock_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    unlock_password: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Status (updated by background polling)
    is_online: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Link to apartment this device calls (for source devices: doors, gates, barriers)
    apartment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("apartments.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    # Relationships
    routing_rules_as_source: Mapped[list["RoutingRule"]] = relationship(
        "RoutingRule",
        foreign_keys="RoutingRule.source_device_id",
        back_populates="source_device",
        lazy="select",
    )
    routing_rules_as_target: Mapped[list["RoutingRule"]] = relationship(
        "RoutingRule",
        foreign_keys="RoutingRule.target_device_id",
        back_populates="target_device",
        lazy="select",
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        "ActivityLog", back_populates="device", lazy="select"
    )
    apartment: Mapped["Apartment | None"] = relationship(
        "Apartment", foreign_keys=[apartment_id], back_populates="source_devices", lazy="select"
    )


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    call_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_device_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    target_device_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    target_sip_account: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    source_device: Mapped["Device | None"] = relationship(
        "Device", foreign_keys=[source_device_id], back_populates="routing_rules_as_source"
    )
    target_device: Mapped["Device | None"] = relationship(
        "Device", foreign_keys=[target_device_id], back_populates="routing_rules_as_target"
    )


# ─── Plate whitelist (parking ANPR) ──────────────────────────────────────────


class PlateWhitelist(Base):
    """Разрешённый автомобильный номер для парковочного шлагбаума.

    ``plate`` хранится в нормализованном виде (верхний регистр, без пробелов
    и дефисов, кириллические двойники свёрнуты в латиницу) — см.
    ``plate_service.normalize_plate``. ANPR-камера присылает распознанный
    номер, бэкенд нормализует его так же и ищет точное совпадение здесь.
    """

    __tablename__ = "plate_whitelist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plate: Mapped[str] = mapped_column(
        String(16), nullable=False, unique=True, index=True
    )
    owner_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    apartment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("apartments.id", ondelete="SET NULL"), nullable=True
    )
    entrance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("entrances.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PlateAccessLog(Base):
    """Журнал проездов — одна запись на каждое распознавание номера ANPR-камерой.

    Пишется ``anpr_service``: распознан номер → проверка по [[plate-whitelist]]
    → открытие шлагбаума или отказ. ``action`` = opened | denied | open_failed.
    """

    __tablename__ = "plate_access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    device_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    plate: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    plate_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)
    whitelist_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("plate_whitelist.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    action: Mapped[ActivityAction] = mapped_column(
        Enum(ActivityAction, native_enum=False), nullable=False
    )
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    device: Mapped["Device | None"] = relationship("Device", back_populates="activity_logs")


# ─── Entrance (mirrored from cloud bootstrap_snapshot) ───────────────────────


class Entrance(Base):
    """Подъезд (entrance) — cloud-defined, cached locally.

    Bridge does NOT manage entrances itself; they arrive in cloud's
    ``bootstrap_snapshot`` after every reconnect. We just need to know they
    exist so we can attach apartments/devices to them when sending the
    reverse ``apartment_upserted`` / ``device_upserted`` events.
    """

    __tablename__ = "entrances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cloud_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    building_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    building_address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# ─── Apartment ────────────────────────────────────────────────────────────────


class Apartment(Base):
    """Represents one apartment / unit. Rings all its monitors when door calls."""

    __tablename__ = "apartments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    call_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    floor: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Cloud mirror: belongs-to entrance + cached cloud-side id + sync status.
    entrance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("entrances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cloud_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    cloud_synced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_cloud_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cloud relay: forward call to cloud SIP trunk → mobile app users
    cloud_relay_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cloud_sip_account: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    monitors: Mapped[list["ApartmentMonitor"]] = relationship(
        "ApartmentMonitor",
        back_populates="apartment",
        cascade="all, delete-orphan",
        lazy="select",
    )
    source_devices: Mapped[list["Device"]] = relationship(
        "Device",
        foreign_keys="Device.apartment_id",
        back_populates="apartment",
        lazy="select",
    )


class ApartmentMonitor(Base):
    """A single SIP account (monitor/phone) belonging to an apartment.

    Stores the device-side attributes (mac/model/name) needed by the cloud
    apartment_upserted event when this is a hardware monitor rather than a
    pure SIP account (e.g. mobile WebRTC).
    """

    __tablename__ = "apartment_monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    apartment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sip_account: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cloud_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    apartment: Mapped["Apartment"] = relationship("Apartment", back_populates="monitors")


# ─── WebRTC Endpoints ─────────────────────────────────────────────────────────


class WebrtcEndpoint(Base):
    """WebRTC SIP endpoint provisioned into pjsip_webrtc.conf for mobile clients."""

    __tablename__ = "webrtc_endpoints"

    extension: Mapped[str] = mapped_column(String(16), primary_key=True)
    # Stored plaintext — Asterisk needs it for REGISTER authentication.
    # Access restricted by OS permissions on the DB file / directory.
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
