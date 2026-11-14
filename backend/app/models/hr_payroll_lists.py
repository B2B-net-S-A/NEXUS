"""Płace liczone w NEXUSIE (K7a, 0703) — modele.

CHECK-i i indeksy jak w ``app/services/hr_payroll_lists_schema.py`` (strażnik
dryfu schematu porównuje model z bazą po migracji); opis tabel w docstringu
modułu schematu.
"""

from __future__ import annotations

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_payroll_lists_schema as schema


class PayrollPersonData(Base, TimestampMixin):
    """Dane kadrowo-płacowe osoby — widzą Kadry, Płace i admin; treść zaszyfrowana."""

    __tablename__ = "payroll_person_data"
    __table_args__ = (
        CheckConstraint(
            schema.CK_PERSON_SUBJECT, name="ck_payroll_person_data_subject"
        ),
        CheckConstraint(
            schema.CK_CANDIDATE_REF, name="ck_payroll_person_data_candidate_ref"
        ),
        CheckConstraint(
            schema.CK_LAST4_PESEL, name="ck_payroll_person_data_pesel_last4"
        ),
        CheckConstraint(
            schema.CK_LAST4_ACCOUNT, name="ck_payroll_person_data_account_last4"
        ),
        CheckConstraint(schema.CK_MISSING, name="ck_payroll_person_data_missing"),
        Index(
            "uq_payroll_person_data_user",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_payroll_person_data_candidate",
            "candidate_id",
            unique=True,
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
        Index(
            "uq_payroll_person_data_candidate_ref",
            "candidate_ref",
            unique=True,
            postgresql_where=text("candidate_ref IS NOT NULL"),
        ),
        Index(
            "uq_payroll_person_data_pesel",
            "pesel_hmac",
            unique=True,
            postgresql_where=text("pesel_hmac IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    candidate_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    data_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    pesel_hmac: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pesel_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    account_hmac: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    account_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    missing: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PayrollParameterVersion(Base):
    """Parametry płac od daty — pełny zestaw; zastąpiona wersja zostaje w historii."""

    __tablename__ = "payroll_parameter_versions"
    __table_args__ = (
        CheckConstraint(
            schema.CK_PARAM_STATUS, name="ck_payroll_parameter_versions_status"
        ),
        CheckConstraint(
            schema.CK_PARAM_SOURCE, name="ck_payroll_parameter_versions_source"
        ),
        CheckConstraint(
            schema.CK_PARAM_OBJECT, name="ck_payroll_parameter_versions_params"
        ),
        CheckConstraint(
            schema.CK_PARAM_FIRST_DAY, name="ck_payroll_parameter_versions_first_day"
        ),
        CheckConstraint(
            schema.CK_PARAM_CONFIRMED, name="ck_payroll_parameter_versions_confirmed"
        ),
        CheckConstraint(
            schema.CK_PARAM_NOTE, name="ck_payroll_parameter_versions_note"
        ),
        Index(
            "uq_payroll_parameter_versions_live",
            "effective_from",
            unique=True,
            postgresql_where=text(schema.PARAM_LIVE_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="to_confirm", server_default="to_confirm"
    )
    source: Mapped[str] = mapped_column(
        String(8), nullable=False, default="manual", server_default="manual"
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    confirmed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    replaced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PayrollList(Base):
    """Lista płac miesiąca pracy — szkic, zatwierdzona albo anulowana."""

    __tablename__ = "payroll_lists"
    __table_args__ = (
        UniqueConstraint("number", name="uq_payroll_lists_number"),
        CheckConstraint(schema.CK_LIST_STATUS, name="ck_payroll_lists_status"),
        CheckConstraint(schema.CK_LIST_YEAR, name="ck_payroll_lists_year"),
        CheckConstraint(schema.CK_LIST_MONTH, name="ck_payroll_lists_month"),
        CheckConstraint(schema.CK_LIST_TOTALS, name="ck_payroll_lists_totals"),
        CheckConstraint(schema.CK_LIST_PROBLEMS, name="ck_payroll_lists_problems"),
        CheckConstraint(schema.CK_LIST_APPROVED, name="ck_payroll_lists_approved"),
        CheckConstraint(schema.CK_LIST_CANCELLED, name="ck_payroll_lists_cancelled"),
        CheckConstraint(
            schema.CK_LIST_SECOND_PERSON, name="ck_payroll_lists_second_person"
        ),
        CheckConstraint(schema.CK_LIST_REASON, name="ck_payroll_lists_reason"),
        Index(
            "uq_payroll_lists_live",
            "period_id",
            unique=True,
            postgresql_where=text(schema.LIST_LIVE_WHERE),
        ),
        Index(
            "ix_payroll_lists_pay_date",
            "pay_date",
            postgresql_where=text("status = 'approved'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="RESTRICT"), nullable=False
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    number: Mapped[str] = mapped_column(String(schema.NUMBER_MAX), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", server_default="draft"
    )
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    parameter_version_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_parameter_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    totals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    problems: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=text("''")
    )
    computed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transfers_created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    transfers_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PayrollListLine(Base):
    """Pozycja listy: osoba × tytuł z wynikiem silnika."""

    __tablename__ = "payroll_list_lines"
    __table_args__ = (
        CheckConstraint(schema.CK_LINE_SUBJECT, name="ck_payroll_list_lines_subject"),
        CheckConstraint(
            schema.CK_CANDIDATE_REF, name="ck_payroll_list_lines_candidate_ref"
        ),
        CheckConstraint(schema.CK_LINE_KIND, name="ck_payroll_list_lines_kind"),
        CheckConstraint(schema.CK_LINE_SOURCE, name="ck_payroll_list_lines_source"),
        CheckConstraint(schema.CK_LINE_GROSS, name="ck_payroll_list_lines_gross"),
        CheckConstraint(schema.CK_LINE_BASIS, name="ck_payroll_list_lines_basis"),
        CheckConstraint(schema.CK_LINE_RESULT, name="ck_payroll_list_lines_result"),
        CheckConstraint(schema.CK_LINE_PROBLEMS, name="ck_payroll_list_lines_problems"),
        CheckConstraint(schema.CK_LINE_PAYEE, name="ck_payroll_list_lines_payee"),
        Index("ix_payroll_list_lines_list", "list_id"),
        Index(
            "uq_payroll_list_lines_user",
            "list_id",
            "user_id",
            "kind",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_payroll_list_lines_contract",
            "list_id",
            "contract_id",
            unique=True,
            postgresql_where=text("contract_id IS NOT NULL"),
        ),
        Index(
            "ix_payroll_list_lines_user",
            "user_id",
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "ix_payroll_list_lines_candidate",
            "candidate_ref",
            postgresql_where=text("candidate_ref IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_lists.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    candidate_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    person_name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    gross: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    net: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    pit: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    social_employee: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    health: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    employer_social: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    employer_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    basis: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    problems: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    payee_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    payee_hmac: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PayrollGrossInput(Base):
    """Kwota brutto wpisana przez Płace na miesiąc (osoba z zespołu albo kontrakt)."""

    __tablename__ = "payroll_gross_inputs"
    __table_args__ = (
        CheckConstraint(
            schema.CK_INPUT_SUBJECT, name="ck_payroll_gross_inputs_subject"
        ),
        CheckConstraint(schema.CK_INPUT_KIND, name="ck_payroll_gross_inputs_kind"),
        CheckConstraint(schema.CK_INPUT_GROSS, name="ck_payroll_gross_inputs_gross"),
        CheckConstraint(schema.CK_INPUT_FUND, name="ck_payroll_gross_inputs_fund"),
        CheckConstraint(schema.CK_INPUT_NOTE, name="ck_payroll_gross_inputs_note"),
        Index(
            "uq_payroll_gross_inputs_user",
            "period_id",
            "user_id",
            "kind",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_payroll_gross_inputs_contract",
            "period_id",
            "contract_id",
            unique=True,
            postgresql_where=text("contract_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    gross: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    fund_basis: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    note: Mapped[str] = mapped_column(String(schema.NOTE_MAX), nullable=False)
    entered_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PayrollYearOpening(Base):
    """Stan roku sprzed NEXUSA (z Enovy) — narastające podstawy i sumy do PIT-11."""

    __tablename__ = "payroll_year_openings"
    __table_args__ = (
        CheckConstraint(
            schema.CK_OPENING_SUBJECT, name="ck_payroll_year_openings_subject"
        ),
        CheckConstraint(
            schema.CK_CANDIDATE_REF, name="ck_payroll_year_openings_candidate_ref"
        ),
        CheckConstraint(schema.CK_OPENING_YEAR, name="ck_payroll_year_openings_year"),
        CheckConstraint(schema.CK_OPENING_MONTH, name="ck_payroll_year_openings_month"),
        CheckConstraint(
            schema.CK_OPENING_AMOUNTS, name="ck_payroll_year_openings_amounts"
        ),
        CheckConstraint(schema.CK_OPENING_NOTE, name="ck_payroll_year_openings_note"),
        Index(
            "uq_payroll_year_openings_user",
            "user_id",
            "year",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_payroll_year_openings_candidate",
            "candidate_ref",
            "year",
            unique=True,
            postgresql_where=text("candidate_ref IS NOT NULL"),
        ),
        Index(
            "uq_payroll_year_openings_candidate_id",
            "candidate_id",
            "year",
            unique=True,
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    candidate_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    through_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    amounts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(schema.NOTE_MAX), nullable=True)
    entered_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "PayrollGrossInput",
    "PayrollList",
    "PayrollListLine",
    "PayrollParameterVersion",
    "PayrollPersonData",
    "PayrollYearOpening",
]
