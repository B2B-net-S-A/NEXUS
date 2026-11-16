"""Płace K7b (0716) — pensje UoP, składniki miesiąca, oznaczenia L4, historia podstaw.

CHECK-i i indeksy jak w ``app/services/hr_payroll_k7b_schema.py`` (strażnik
dryfu schematu porównuje model z bazą po migracji); opis tabel w docstringu
modułu schematu.
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import hr_payroll_k7b_schema as schema
from app.services.hr_payroll_lists_schema import NOTE_MAX


class PayrollSalary(Base):
    """Pensja zasadnicza UoP za pełny miesiąc i etat, od 1. dnia miesiąca."""

    __tablename__ = "payroll_salaries"
    __table_args__ = (
        CheckConstraint(schema.CK_SALARY_AMOUNT, name="ck_payroll_salaries_amount"),
        CheckConstraint(schema.CK_SALARY_FTE, name="ck_payroll_salaries_fte"),
        CheckConstraint(
            schema.CK_SALARY_FIRST_DAY, name="ck_payroll_salaries_first_day"
        ),
        CheckConstraint(schema.CK_SALARY_RANGE, name="ck_payroll_salaries_range"),
        CheckConstraint(schema.CK_SALARY_NOTE, name="ck_payroll_salaries_note"),
        Index(
            "uq_payroll_salaries_user_from", "user_id", "effective_from", unique=True
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fte: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("1"), server_default="1"
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(NOTE_MAX), nullable=True)
    set_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PayrollComponent(Base):
    """Składnik miesiąca wpisany przez Płace (zmienne, inne, podstawa, dni ekwiwalentu)."""

    __tablename__ = "payroll_components"
    __table_args__ = (
        CheckConstraint(schema.CK_COMPONENT_KIND, name="ck_payroll_components_kind"),
        CheckConstraint(
            schema.CK_COMPONENT_AMOUNT, name="ck_payroll_components_amount"
        ),
        CheckConstraint(schema.CK_COMPONENT_NOTE, name="ck_payroll_components_note"),
        Index(
            "uq_payroll_components_period_user_kind",
            "period_id",
            "user_id",
            "kind",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str] = mapped_column(String(NOTE_MAX), nullable=False)
    entered_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PayrollAbsenceMark(Base):
    """Oznaczenie Płac przy L4: 80% / 100% / zasiłek ZUS, zwolnienie z wyczekiwania."""

    __tablename__ = "payroll_absence_marks"
    __table_args__ = (
        CheckConstraint(schema.CK_MARK_RATE, name="ck_payroll_absence_marks_rate"),
        CheckConstraint(schema.CK_MARK_NOTE, name="ck_payroll_absence_marks_note"),
        Index("ix_payroll_absence_marks_user", "user_id"),
    )

    leave_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_requests.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    sick_rate: Mapped[str] = mapped_column(
        String(4), nullable=False, default="80", server_default=text("'80'")
    )
    waiting_exempt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    note: Mapped[Optional[str]] = mapped_column(String(NOTE_MAX), nullable=True)
    set_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PayrollBasisMonth(Base):
    """Miesiąc historii podstaw sprzed NEXUSA (import z Enovy)."""

    __tablename__ = "payroll_basis_months"
    __table_args__ = (
        CheckConstraint(schema.CK_BASIS_YEAR, name="ck_payroll_basis_months_year"),
        CheckConstraint(schema.CK_BASIS_MONTH, name="ck_payroll_basis_months_month"),
        CheckConstraint(
            schema.CK_BASIS_AMOUNTS, name="ck_payroll_basis_months_amounts"
        ),
        CheckConstraint(schema.CK_BASIS_HOURS, name="ck_payroll_basis_months_hours"),
        CheckConstraint(schema.CK_BASIS_SOURCE, name="ck_payroll_basis_months_source"),
        Index(
            "uq_payroll_basis_months_user_month",
            "user_id",
            "year",
            "month",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fixed_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    fixed_full: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    variable: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    leave_variable: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    nominal_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    worked_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    paid_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    full_month: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    source: Mapped[str] = mapped_column(
        String(8), nullable=False, default="enova", server_default=text("'enova'")
    )
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entered_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "PayrollAbsenceMark",
    "PayrollBasisMonth",
    "PayrollComponent",
    "PayrollSalary",
]
