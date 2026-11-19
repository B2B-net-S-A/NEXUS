"""Dokumenty Rady nadzorczej, odpisy KRS spółki (0727, R1) budżet (0733, R3), sprawozdania roczne (0734, R4)
posiedzenia (0735, R5), uchwały w trybie pisemnym (0736, R6) oraz gotówka i archiwum
raportów (0737, R7).

CHECK-i i indeksy muszą być identyczne z ``app/services/board_documents_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import board_budget_schema as budget_schema
from app.services import board_documents_schema as schema
from app.services import board_meetings_schema as meetings_schema
from app.services import board_reports_schema as reports_schema
from app.services import board_statements_schema as statements_schema
from app.services import board_votes_schema as votes_schema


class BoardDocument(Base):
    """Dokument korporacyjny: plik od Zarządu albo wiersz z wzmianki KRS."""

    __tablename__ = "board_documents"
    __table_args__ = (
        CheckConstraint(schema.CK_CATEGORY, name="ck_board_documents_category"),
        CheckConstraint(schema.CK_ORGAN, name="ck_board_documents_organ"),
        CheckConstraint(schema.CK_SOURCE, name="ck_board_documents_source"),
        CheckConstraint(
            schema.CK_EXTRACTION_STATUS, name="ck_board_documents_extraction_status"
        ),
        CheckConstraint(schema.CK_EXTRACTION, name="ck_board_documents_extraction"),
        Index(
            "uq_board_documents_krs_key",
            "krs_key",
            unique=True,
            postgresql_where=text("krs_key IS NOT NULL"),
        ),
        Index(
            "ix_board_documents_category_date",
            "category",
            text("doc_date DESC NULLS LAST"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    organ: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    number: Mapped[Optional[str]] = mapped_column(
        String(schema.NUMBER_MAX), nullable=True
    )
    title: Mapped[str] = mapped_column(String(schema.TITLE_MAX), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doc_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(
        String(8), nullable=False, default="upload", server_default="upload"
    )
    krs_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    krs_entry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    krs_entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(
        String(schema.NAME_MAX), nullable=True
    )
    file_path: Mapped[Optional[str]] = mapped_column(
        String(schema.NAME_MAX), nullable=True
    )
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extraction_status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="none", server_default="none"
    )
    extraction: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoardKrsSnapshot(Base):
    """Odpis pełny KRS spółki; nowy wiersz tylko przy zmianie treści."""

    __tablename__ = "board_krs_snapshots"
    __table_args__ = (
        CheckConstraint(schema.CK_PAYLOAD, name="ck_board_krs_snapshots_payload"),
        Index("uq_board_krs_snapshots_krs_sha", "krs", "sha256", unique=True),
        Index("ix_board_krs_snapshots_krs_fetched", "krs", text("fetched_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    krs: Mapped[str] = mapped_column(String(10), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entries_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_entry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoardBudget(Base):
    """Budżet roku (0733, R3): status i uchwała Rady, która go przyjęła."""

    __tablename__ = "board_budgets"
    __table_args__ = (
        CheckConstraint(budget_schema.CK_STATUS, name="ck_board_budgets_status"),
        CheckConstraint(budget_schema.CK_YEAR, name="ck_board_budgets_year"),
        Index("uq_board_budgets_year", "year", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="draft", server_default="draft"
    )
    resolution_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("board_documents.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoardBudgetLine(Base):
    """Plan miesiąca: sprzedaż albo koszty z faktur, PLN netto."""

    __tablename__ = "board_budget_lines"
    __table_args__ = (
        CheckConstraint(budget_schema.CK_MONTH, name="ck_board_budget_lines_month"),
        CheckConstraint(budget_schema.CK_LINE, name="ck_board_budget_lines_line"),
        CheckConstraint(budget_schema.CK_AMOUNT, name="ck_board_budget_lines_amount"),
        Index(
            "uq_board_budget_lines_month_line",
            "budget_id",
            "month",
            "line",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("board_budgets.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    line: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class BoardFinancialStatement(Base):
    """Sprawozdanie roczne (0734, R4): wspólne pola bilansu i RZiS w PLN."""

    __tablename__ = "board_financial_statements"
    __table_args__ = (
        CheckConstraint(
            statements_schema.CK_SOURCE, name="ck_board_financial_statements_source"
        ),
        CheckConstraint(
            statements_schema.CK_YEAR, name="ck_board_financial_statements_year"
        ),
        CheckConstraint(
            statements_schema.CK_AMOUNTS,
            name="ck_board_financial_statements_amounts",
        ),
        CheckConstraint(
            statements_schema.CK_RAW, name="ck_board_financial_statements_raw"
        ),
        Index("uq_board_financial_statements_year", "year", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    schema_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("board_documents.id", ondelete="SET NULL"), nullable=True
    )
    amounts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoardMeeting(Base):
    """Posiedzenie Rady (0735, R5) z porządkiem obrad i zamrożonym pakietem."""

    __tablename__ = "board_meetings"
    __table_args__ = (
        CheckConstraint(meetings_schema.CK_KIND, name="ck_board_meetings_kind"),
        CheckConstraint(meetings_schema.CK_STATUS, name="ck_board_meetings_status"),
        CheckConstraint(meetings_schema.CK_AGENDA, name="ck_board_meetings_agenda"),
        CheckConstraint(meetings_schema.CK_PACK, name="ck_board_meetings_pack"),
        Index("ix_board_meetings_held_on", text("held_on DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    held_on: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(12), nullable=False, default="meeting", server_default="meeting"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="planned", server_default="planned"
    )
    title: Mapped[str] = mapped_column(
        String(meetings_schema.TITLE_MAX), nullable=False
    )
    place: Mapped[Optional[str]] = mapped_column(
        String(meetings_schema.PLACE_MAX), nullable=True
    )
    agenda: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    minutes_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("board_documents.id", ondelete="SET NULL"), nullable=True
    )
    pack: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    pack_frozen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pack_frozen_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoardVote(Base):
    """Uchwała Rady w trybie pisemnym (0736, R6) — § 25 ust. 4 projektu statutu."""

    __tablename__ = "board_votes"
    __table_args__ = (
        CheckConstraint(votes_schema.CK_STATUS, name="ck_board_votes_status"),
        CheckConstraint(votes_schema.CK_MEMBERS, name="ck_board_votes_members"),
        CheckConstraint(votes_schema.CK_RESULT, name="ck_board_votes_result"),
        Index("ix_board_votes_status_deadline", "status", "deadline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[Optional[str]] = mapped_column(
        String(votes_schema.NUMBER_MAX), nullable=True
    )
    title: Mapped[str] = mapped_column(String(votes_schema.TITLE_MAX), nullable=False)
    draft: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("board_documents.id", ondelete="SET NULL"), nullable=True
    )
    meeting_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("board_meetings.id", ondelete="SET NULL"), nullable=True
    )
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="open", server_default="open"
    )
    member_ids: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    chair_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    resolution_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("board_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BoardVoteBallot(Base):
    """Głos członka Rady w uchwale pisemnej."""

    __tablename__ = "board_vote_ballots"
    __table_args__ = (
        CheckConstraint(votes_schema.CK_CHOICE, name="ck_board_vote_ballots_choice"),
        Index("uq_board_vote_ballots_vote_user", "vote_id", "user_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vote_id: Mapped[int] = mapped_column(
        ForeignKey("board_votes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    choice: Mapped[str] = mapped_column(String(8), nullable=False)
    cast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoardCashPosition(Base):
    """Stan gotówki na dzień (0737, R7) — wpis admina z wyciągów."""

    __tablename__ = "board_cash_positions"
    __table_args__ = (Index("uq_board_cash_positions_as_of", "as_of", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(
        String(reports_schema.NOTE_MAX), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoardReport(Base):
    """Raport PDF zapisany w archiwum Rady (0737, R7)."""

    __tablename__ = "board_reports"
    __table_args__ = (
        CheckConstraint(reports_schema.CK_KIND, name="ck_board_reports_kind"),
        CheckConstraint(reports_schema.CK_YEAR, name="ck_board_reports_year"),
        CheckConstraint(reports_schema.CK_MONTH, name="ck_board_reports_month"),
        CheckConstraint(
            reports_schema.CK_MONTHLY_HAS_MONTH,
            name="ck_board_reports_monthly_has_month",
        ),
        Index("ix_board_reports_period", "kind", "year", "month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
