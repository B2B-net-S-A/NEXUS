"""„Ludzie w NEXUSIE” — modele: Płace i premie (0460).

CHECK-i i indeksy muszą być identyczne z ``app/services/*_schema.py`` modułu
(strażnik dryfu schematu porównuje model z bazą po migracji).

* ``EmployeeRate`` — stawka godzinowa od 1. dnia miesiąca (historia),
* ``HrBonus`` — premia ręczna albo propozycja automatu (placement, Liga),
* ``PayrollPeriod`` — miesiąc płac otwarty albo zamknięty,
* ``PayrollLine`` — zamrożona linia zamkniętego miesiąca (osoba × waluta),
* ``HrBonusClawback`` / ``HrBonusClawbackOffset`` — gwarancja premii DL (0650):
  dług za premię i potrącenia zamrożone przy zamknięciu miesiąca.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_bonus_guarantee_schema as guarantee_schema
from app.services import hr_payroll_schema as schema


class EmployeeRate(Base, TimestampMixin):
    """Stawka godzinowa pracownika obowiązująca od ``effective_from``."""

    __tablename__ = "employee_rates"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "effective_from", name="uq_employee_rates_user_from"
        ),
        UniqueConstraint("compass_id", name="uq_employee_rates_compass"),
        CheckConstraint(schema.CK_RATE_VALUE, name="ck_employee_rates_value"),
        CheckConstraint(schema.CK_RATE_CURRENCY, name="ck_employee_rates_currency"),
        CheckConstraint(schema.CK_RATE_FIRST_DAY, name="ck_employee_rates_first_day"),
        CheckConstraint(schema.CK_RATE_RANGE, name="ck_employee_rates_range"),
        CheckConstraint(schema.CK_RATE_REASON, name="ck_employee_rates_reason"),
        Index(
            "uq_employee_rates_open",
            "user_id",
            unique=True,
            postgresql_where=text(schema.OPEN_RATE_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    set_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    compass_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class HrBonus(Base, TimestampMixin):
    """Premia: ręczna, propozycja automatu albo import z Compassa."""

    __tablename__ = "hr_bonuses"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_hr_bonuses_source_key"),
        UniqueConstraint("compass_id", name="uq_hr_bonuses_compass"),
        CheckConstraint(
            schema.CK_BONUS_NOT_SELF_PROPOSED, name="ck_hr_bonuses_not_self_proposed"
        ),
        CheckConstraint(
            schema.CK_BONUS_NOT_SELF_ASSIGNED, name="ck_hr_bonuses_not_self_assigned"
        ),
        CheckConstraint(schema.CK_BONUS_AMOUNT, name="ck_hr_bonuses_amount"),
        CheckConstraint(schema.CK_BONUS_CURRENCY, name="ck_hr_bonuses_currency"),
        CheckConstraint(schema.CK_BONUS_CATEGORY, name="ck_hr_bonuses_category"),
        CheckConstraint(schema.CK_BONUS_STATUS, name="ck_hr_bonuses_status"),
        CheckConstraint(schema.CK_BONUS_SOURCE, name="ck_hr_bonuses_source"),
        CheckConstraint(schema.CK_BONUS_YEAR, name="ck_hr_bonuses_year"),
        CheckConstraint(schema.CK_BONUS_MONTH, name="ck_hr_bonuses_month"),
        CheckConstraint(
            schema.CK_BONUS_AUTOMATED_KEY, name="ck_hr_bonuses_automated_key"
        ),
        CheckConstraint(schema.CK_BONUS_ASSIGNED_AT, name="ck_hr_bonuses_assigned_at"),
        CheckConstraint(schema.CK_BONUS_DESCRIPTION, name="ck_hr_bonuses_description"),
        Index("ix_hr_bonuses_period", "period_year", "period_month", "status"),
        Index(
            "ix_hr_bonuses_recipient",
            "recipient_user_id",
            "period_year",
            "period_month",
        ),
        Index("ix_hr_bonuses_contract", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    proposed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    period_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="proposed", server_default="proposed"
    )
    source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="manual", server_default="manual"
    )
    source_key: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    eligible_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assigned_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    cancel_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compass_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class PayrollPeriod(Base, TimestampMixin):
    """Miesiąc płac; zamknięty = linie zamrożone, zmiany tego miesiąca → 409."""

    __tablename__ = "payroll_periods"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_payroll_periods_year_month"),
        CheckConstraint(schema.CK_PERIOD_YEAR, name="ck_payroll_periods_year"),
        CheckConstraint(schema.CK_PERIOD_MONTH, name="ck_payroll_periods_month"),
        CheckConstraint(schema.CK_PERIOD_STATUS, name="ck_payroll_periods_status"),
        CheckConstraint(
            schema.CK_PERIOD_CLOSED_AT, name="ck_payroll_periods_closed_at"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    closed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reopened_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reopened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reopen_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    close_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )


class PayrollLine(Base):
    """Linia zamkniętego miesiąca: osoba × waluta, kwoty zamrożone."""

    __tablename__ = "payroll_lines"
    __table_args__ = (
        UniqueConstraint(
            "period_id",
            "user_id",
            "currency",
            name="uq_payroll_lines_period_user_currency",
        ),
        CheckConstraint(schema.CK_LINE_CURRENCY, name="ck_payroll_lines_currency"),
        CheckConstraint(
            schema.CK_LINE_NON_NEGATIVE, name="ck_payroll_lines_non_negative"
        ),
        CheckConstraint(
            schema.CK_LINE_TIMESHEET_STATUS, name="ck_payroll_lines_timesheet_status"
        ),
        CheckConstraint(
            guarantee_schema.CK_LINE_CLAWBACK, name="ck_payroll_lines_clawback"
        ),
        Index("ix_payroll_lines_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    person_name: Mapped[str] = mapped_column(String(255), nullable=False)
    employment_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    hours: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    hourly_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    hours_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    bonus_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    #: Potrącenie z gwarancji premii DL; ``bonus_total`` jest już po nim (0650).
    clawback_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    paid_leave_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0"), server_default="0"
    )
    other_leave_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0"), server_default="0"
    )
    timesheet_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HrBonusClawback(Base, TimestampMixin):
    """Dług za przyznaną premię DL: konsultant odszedł przed 12 miesiącami (0650)."""

    __tablename__ = "hr_bonus_clawbacks"
    __table_args__ = (
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_AMOUNT, name="ck_hr_bonus_clawbacks_amount"
        ),
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_CURRENCY,
            name="ck_hr_bonus_clawbacks_currency",
        ),
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_ORIGIN, name="ck_hr_bonus_clawbacks_origin"
        ),
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_STATUS, name="ck_hr_bonus_clawbacks_status"
        ),
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_NOT_SELF_CREATED,
            name="ck_hr_bonus_clawbacks_not_self_created",
        ),
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_NOT_SELF_CANCELLED,
            name="ck_hr_bonus_clawbacks_not_self_cancelled",
        ),
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_CANCELLED_AT,
            name="ck_hr_bonus_clawbacks_cancelled_at",
        ),
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_NOTE, name="ck_hr_bonus_clawbacks_note"
        ),
        CheckConstraint(
            guarantee_schema.CK_CLAWBACK_CANCEL_NOTE,
            name="ck_hr_bonus_clawbacks_cancel_note",
        ),
        Index(
            "uq_hr_bonus_clawbacks_live",
            "bonus_id",
            unique=True,
            postgresql_where=text(guarantee_schema.LIVE_CLAWBACK_WHERE),
        ),
        Index("ix_hr_bonus_clawbacks_recipient", "recipient_user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bonus_id: Mapped[int] = mapped_column(
        ForeignKey("hr_bonuses.id", ondelete="CASCADE"), nullable=False
    )
    recipient_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    contract_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ended_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    guarantee_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    cancel_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class HrBonusClawbackOffset(Base):
    """Potrącenie długu zamrożone przy zamknięciu miesiąca płac (dług × okres)."""

    __tablename__ = "hr_bonus_clawback_offsets"
    __table_args__ = (
        UniqueConstraint(
            "clawback_id", "period_id", name="uq_hr_bonus_clawback_offsets_period"
        ),
        CheckConstraint(
            guarantee_schema.CK_OFFSET_AMOUNT,
            name="ck_hr_bonus_clawback_offsets_amount",
        ),
        Index("ix_hr_bonus_clawback_offsets_period", "period_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clawback_id: Mapped[int] = mapped_column(
        ForeignKey("hr_bonus_clawbacks.id", ondelete="CASCADE"), nullable=False
    )
    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
