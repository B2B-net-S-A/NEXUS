"""„Ludzie w NEXUSIE” — modele: Mój miesiąc (0455).

CHECK-i i indeksy muszą być identyczne z ``app/services/*_schema.py`` modułu
(strażnik dryfu schematu porównuje model z bazą po migracji).

* ``AttendanceDay`` — wyjątek od domyślnego miejsca pracy (urlopu tu nie ma).
* ``Timesheet`` — osoba i miesiąc: szkic → wysłany → zaakceptowany.
* ``TimesheetEntry`` — wpis dnia (godziny, projekt, opis, źródło, nadgodziny).
* ``TimesheetTemplate`` — osobisty fragment opisu.
* ``TimesheetRoleDefault`` — domyślny opis Kadr dla roli i projektu.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_time_schema as schema


class AttendanceDay(Base, TimestampMixin):
    """Dzień inny niż domyślne miejsce pracy z kartoteki."""

    __tablename__ = "attendance_days"
    __table_args__ = (
        UniqueConstraint("user_id", "day", name="uq_attendance_days_user_day"),
        CheckConstraint(schema.CK_ATTENDANCE_STATUS, name="ck_attendance_days_status"),
        CheckConstraint(
            schema.CK_ATTENDANCE_LOCATION, name="ck_attendance_days_location"
        ),
        CheckConstraint(schema.CK_ATTENDANCE_NOTE, name="ck_attendance_days_note"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    location: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Timesheet(Base, TimestampMixin):
    """Timesheet osoby za miesiąc."""

    __tablename__ = "timesheets"
    __table_args__ = (
        UniqueConstraint("user_id", "year", "month", name="uq_timesheets_user_period"),
        UniqueConstraint("compass_id", name="uq_timesheets_compass"),
        CheckConstraint(schema.CK_TIMESHEET_YEAR, name="ck_timesheets_year"),
        CheckConstraint(schema.CK_TIMESHEET_MONTH, name="ck_timesheets_month"),
        CheckConstraint(schema.CK_TIMESHEET_STATUS, name="ck_timesheets_status"),
        CheckConstraint(
            schema.CK_TIMESHEET_NO_SELF_APPROVAL,
            name="ck_timesheets_no_self_approval",
        ),
        CheckConstraint(schema.CK_TIMESHEET_PDF_HASH, name="ck_timesheets_pdf_hash"),
        Index("ix_timesheets_period_status", "year", "month", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    return_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    returned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pdf_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payroll_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    compass_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class TimesheetEntry(Base, TimestampMixin):
    """Wpis godzin jednego dnia."""

    __tablename__ = "timesheet_entries"
    __table_args__ = (
        CheckConstraint(schema.CK_ENTRY_HOURS, name="ck_timesheet_entries_hours"),
        CheckConstraint(
            schema.CK_ENTRY_DESCRIPTION, name="ck_timesheet_entries_description"
        ),
        CheckConstraint(schema.CK_ENTRY_SOURCE, name="ck_timesheet_entries_source"),
        CheckConstraint(schema.CK_ENTRY_OVERTIME, name="ck_timesheet_entries_overtime"),
        Index("ix_timesheet_entries_timesheet_date", "timesheet_id", "work_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timesheet_id: Mapped[int] = mapped_column(
        ForeignKey("timesheets.id", ondelete="CASCADE"), nullable=False
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    project: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    is_overtime: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    overtime_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overtime_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TimesheetTemplate(Base, TimestampMixin):
    """Osobisty fragment opisu („Konsultacje”, „Przegląd kodu”)."""

    __tablename__ = "timesheet_templates"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_timesheet_templates_user_name"),
        CheckConstraint(schema.CK_TEMPLATE_NAME, name="ck_timesheet_templates_name"),
        CheckConstraint(
            schema.CK_TEMPLATE_DESCRIPTION, name="ck_timesheet_templates_description"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    project: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class TimesheetRoleDefault(Base, TimestampMixin):
    """Domyślny opis dnia dla roli i projektu (ustawiają Kadry)."""

    __tablename__ = "timesheet_role_defaults"
    __table_args__ = (
        CheckConstraint(
            schema.CK_ROLE_DEFAULT_LABEL, name="ck_timesheet_role_defaults_label"
        ),
        CheckConstraint(
            schema.CK_ROLE_DEFAULT_DESCRIPTION,
            name="ck_timesheet_role_defaults_description",
        ),
        Index("ix_timesheet_role_defaults_active", "is_active", "applies_to_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    applies_to_role: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    project: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    default_description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
