"""Kartoteka pracownika, pule urlopowe i dni wolne firmy (migracja 0452).

„Ludzie w NEXUSIE” (16.10.2026). Dane kadrowe NIE są kolumnami ``users`` —
osobna tabela 1:1 z kontem, osobne uprawnienia (Kadry, Płace). Konsultanci
B2B u klientów nie mają tu wierszy.

CHECK-i i indeksy są tu powtórzone z ``services/hr_foundation_schema.py``
(strażnik dryfu porównuje model z bazą po migracji).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_foundation_schema as schema


class EmployeeProfile(Base, TimestampMixin):
    """Kartoteka osoby zatrudnionej w firmie (pracownik, B2B, zlecenie)."""

    __tablename__ = "employee_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_employee_profiles_user"),
        UniqueConstraint("public_id", name="uq_employee_profiles_public_id"),
        UniqueConstraint("compass_profile_id", name="uq_employee_profiles_compass"),
        CheckConstraint(schema.CK_EMPLOYMENT_TYPE, name="ck_employee_profiles_type"),
        CheckConstraint(
            schema.CK_EMPLOYMENT_STATUS, name="ck_employee_profiles_status"
        ),
        CheckConstraint(schema.CK_LOCATION, name="ck_employee_profiles_location"),
        CheckConstraint(
            schema.CK_NO_SELF_MANAGER, name="ck_employee_profiles_no_self_manager"
        ),
        CheckConstraint(schema.CK_DIVISION, name="ck_employee_profiles_division"),
        Index("ix_employee_profiles_manager", "manager_user_id"),
        Index("ix_employee_profiles_status", "employment_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    manager_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    employment_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="b2b", server_default="b2b"
    )
    employment_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    hired_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    work_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_working_day: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    exited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    default_location: Mapped[str] = mapped_column(
        String(16), nullable=False, default="onsite", server_default="onsite"
    )
    timesheet_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    can_log_overtime: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    job_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    m365_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Przełożony z katalogu Microsoft 365 (UPN) — tylko podpowiedź rozjazdu
    #: w „Ludzie → Struktura” (D7); o przełożonym decyduje ``manager_user_id``.
    m365_manager_upn: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    #: Pion firmy: ``front_office`` / ``back_office`` (``None`` = bez pionu).
    division: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    compass_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class LeaveEntitlement(Base, TimestampMixin):
    """Pula urlopowa osoby na rok (``entitlement_days`` NULL = bez puli)."""

    __tablename__ = "leave_entitlements"
    __table_args__ = (
        UniqueConstraint("user_id", "year", name="uq_leave_entitlements_user_year"),
        CheckConstraint(schema.CK_ENTITLEMENT_YEAR, name="ck_leave_entitlements_year"),
        CheckConstraint(schema.CK_ENTITLEMENT_DAYS, name="ck_leave_entitlements_days"),
        CheckConstraint(schema.CK_CARRIED_DAYS, name="ck_leave_entitlements_carried"),
        CheckConstraint(
            schema.CK_USED_INITIAL_DAYS, name="ck_leave_entitlements_used_initial"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    entitlement_days: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 1), nullable=True
    )
    carried_over_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0"), server_default="0"
    )
    used_initial_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0"), server_default="0"
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    set_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CompanyDayOff(Base):
    """Dzień wolny firmy poza świętami ustawowymi."""

    __tablename__ = "company_days_off"
    __table_args__ = (
        UniqueConstraint("day", name="uq_company_days_off_day"),
        CheckConstraint(schema.CK_DAY_OFF_KIND, name="ck_company_days_off_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="company", server_default="company"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
