"""Radar przepisów: biegi botów, surowe pozycje, zmiany w prawie (0714).

CHECK-i i indeksy jak w ``app/services/law_radar/schema.py`` (strażnik dryfu
schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services.law_radar import schema


class LawRadarRun(Base):
    """Bieg Zbieracza albo Analityka: jednorazowy token, zlecenie, podsumowanie."""

    __tablename__ = "law_radar_runs"
    __table_args__ = (
        CheckConstraint(schema.CK_RUN_KIND, name="ck_law_radar_runs_kind"),
        CheckConstraint(schema.CK_RUN_STATUS, name="ck_law_radar_runs_status"),
        Index("ix_law_radar_runs_kind_started", "kind", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="started", server_default="started"
    )
    token_hash: Mapped[Optional[str]] = mapped_column(String(64))
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    #: Zlecenie wysłane botowi (dane publiczne i profil tematów, bez danych firmy).
    request: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    #: Same liczby z przyjęcia raportu (logi i ekran biegów).
    report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[Optional[str]] = mapped_column(String(255))
    #: Bieg Analityka wie, po którym biegu Zbieracza wystartował.
    parent_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("law_radar_runs.id", ondelete="SET NULL")
    )
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class LawChange(Base):
    """Zmiana w prawie. Treść i etap od Analityka, status i decyzja od człowieka."""

    __tablename__ = "law_changes"
    __table_args__ = (
        CheckConstraint(schema.CK_CHANGE_URGENCY, name="ck_law_changes_urgency"),
        CheckConstraint(schema.CK_CHANGE_STAGE, name="ck_law_changes_stage"),
        CheckConstraint(schema.CK_CHANGE_STATUS, name="ck_law_changes_status"),
        CheckConstraint(
            schema.CK_CHANGE_NOT_APPLICABLE, name="ck_law_changes_not_applicable"
        ),
        CheckConstraint(schema.CK_CHANGE_ARRAYS, name="ck_law_changes_arrays"),
        Index("ix_law_changes_status_deadline", "status", "deadline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(schema.CHANGE_TITLE_MAX), nullable=False)
    summary: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    urgency: Mapped[str] = mapped_column(String(8), nullable=False)
    stage: Mapped[str] = mapped_column(String(12), nullable=False)
    effective_on: Mapped[Optional[date]] = mapped_column(Date)
    deadline: Mapped[Optional[date]] = mapped_column(Date)
    legal_ref: Mapped[Optional[str]] = mapped_column(String(schema.LEGAL_REF_MAX))
    probe_keys: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="new", server_default="new"
    )
    decision_note: Mapped[Optional[str]] = mapped_column(Text)
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("law_radar_runs.id", ondelete="SET NULL")
    )
    last_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("law_radar_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LawChangeTask(Base):
    __tablename__ = "law_change_tasks"
    __table_args__ = (
        CheckConstraint(schema.CK_TASK_ROLE, name="ck_law_change_tasks_role"),
        CheckConstraint(schema.CK_TASK_SOURCE, name="ck_law_change_tasks_source"),
        Index("ix_law_change_tasks_change", "change_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("law_changes.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(String(schema.TASK_TEXT_MAX), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(
        String(4), nullable=False, default="bot", server_default="bot"
    )
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    due_on: Mapped[Optional[date]] = mapped_column(Date)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    done_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LawChangeEvent(Base):
    """Dziennik zmiany: założenie, etap, decyzja z powodem, zadania."""

    __tablename__ = "law_change_events"
    __table_args__ = (
        CheckConstraint(schema.CK_EVENT_KIND, name="ck_law_change_events_kind"),
        Index("ix_law_change_events_change", "change_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("law_changes.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    from_value: Mapped[Optional[str]] = mapped_column(String(schema.EVENT_VALUE_MAX))
    to_value: Mapped[Optional[str]] = mapped_column(String(schema.EVENT_VALUE_MAX))
    note: Mapped[Optional[str]] = mapped_column(Text)
    task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("law_change_tasks.id", ondelete="SET NULL")
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("law_radar_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LawChangeProbe(Base):
    """Wynik sondy „u nas” przy zmianie: liczba, tekst, link, czas."""

    __tablename__ = "law_change_probes"
    __table_args__ = (
        UniqueConstraint(
            "change_id", "probe_key", name="uq_law_change_probes_change_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("law_changes.id", ondelete="CASCADE"), nullable=False
    )
    probe_key: Mapped[str] = mapped_column(String(schema.PROBE_KEY_MAX), nullable=False)
    value: Mapped[Optional[int]] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(
        String(schema.PROBE_TEXT_MAX), nullable=False, default="", server_default=""
    )
    link: Mapped[Optional[str]] = mapped_column(String(schema.LINK_MAX))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LawRadarItem(Base):
    """Surowa pozycja Zbieracza po bramce NEXUSA."""

    __tablename__ = "law_radar_items"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_law_radar_items_fingerprint"),
        CheckConstraint(schema.CK_ITEM_SOURCE, name="ck_law_radar_items_source"),
        CheckConstraint(schema.CK_ITEM_CLASS, name="ck_law_radar_items_klass"),
        CheckConstraint(schema.CK_ITEM_GATE, name="ck_law_radar_items_gate"),
        CheckConstraint(schema.CK_ITEM_LEX, name="ck_law_radar_items_lex"),
        CheckConstraint(schema.CK_ITEM_ACT_REF, name="ck_law_radar_items_act_ref"),
        CheckConstraint(schema.CK_ITEM_PRINT_NO, name="ck_law_radar_items_print_no"),
        Index("ix_law_radar_items_run", "run_id"),
        Index("ix_law_radar_items_change", "change_id"),
        Index("ix_law_radar_items_gate", "gate", "analyzed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("law_radar_runs.id", ondelete="SET NULL")
    )
    #: Bieg Analityka, który dostał pozycję (``analyzed_at`` = raport przyjęty).
    analyze_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("law_radar_runs.id", ondelete="SET NULL")
    )
    change_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("law_changes.id", ondelete="SET NULL")
    )
    fingerprint: Mapped[str] = mapped_column(
        String(schema.FINGERPRINT_MAX), nullable=False
    )
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    klass: Mapped[str] = mapped_column(String(8), nullable=False)
    gate: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", server_default="pending"
    )
    gate_reason: Mapped[Optional[str]] = mapped_column(String(schema.GATE_REASON_MAX))
    title: Mapped[str] = mapped_column(String(schema.ITEM_TITLE_MAX), nullable=False)
    url: Mapped[str] = mapped_column(String(schema.URL_MAX), nullable=False)
    published: Mapped[date] = mapped_column(Date, nullable=False)
    act_ref: Mapped[Optional[str]] = mapped_column(String(schema.ACT_REF_MAX))
    print_no: Mapped[Optional[str]] = mapped_column(String(schema.PRINT_NO_MAX))
    stage: Mapped[Optional[str]] = mapped_column(String(schema.STAGE_TEXT_MAX))
    quote: Mapped[Optional[str]] = mapped_column(String(schema.QUOTE_MAX))
    #: Dane z API Sejmu: tytuł, wejście w życie, ostatni etap procesu.
    official: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
