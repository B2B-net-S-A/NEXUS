"""Intune w ewidencji sprzętu (etap 4, D9) — migawka urządzeń i stan pętli.

Tylko odczyt z Graph; rozjazdy z ewidencją liczy ``services/equipment/intune.py``
przy odczycie. Tabele i CHECK-i: ``app/services/equipment_extras_schema.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import equipment_extras_schema as schema


class EquipmentIntuneDevice(Base, TimestampMixin):
    """Urządzenie z Intune widziane przy ostatnim przebiegu (albo zniknięte)."""

    __tablename__ = "equipment_intune_devices"
    __table_args__ = (
        UniqueConstraint("intune_device_id", name="uq_equipment_intune_devices_device"),
        CheckConstraint(
            schema.CK_INTUNE_RESOLUTION, name="ck_equipment_intune_devices_resolution"
        ),
        CheckConstraint(
            schema.CK_INTUNE_RESOLVED, name="ck_equipment_intune_devices_resolved"
        ),
        Index("ix_equipment_intune_devices_serial", "serial_number"),
        Index("ix_equipment_intune_devices_item", "item_id"),
        Index("ix_equipment_intune_devices_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intune_device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    operating_system: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    user_principal_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_items.id", ondelete="SET NULL"), nullable=True
    )
    compliance_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    intune_last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    missing_since: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EquipmentIntuneSyncState(Base):
    """Jeden wiersz (``id = 1``): ostatni przebieg pętli Intune — sonda health."""

    __tablename__ = "equipment_intune_sync_state"
    __table_args__ = (
        CheckConstraint(
            schema.CK_INTUNE_STATE_SINGLETON,
            name="ck_equipment_intune_sync_state_singleton",
        ),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, default=1, server_default="1"
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    device_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
