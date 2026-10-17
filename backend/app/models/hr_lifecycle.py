"""„Ludzie w NEXUSIE” — modele: Wejście i odejście (0460).

CHECK-i i indeksy muszą być identyczne z ``app/services/*_schema.py`` modułu
(strażnik dryfu schematu porównuje model z bazą po migracji).

* ``LifecycleTemplate`` / ``LifecycleTemplateItem`` — ścieżki wejścia
  i odejścia (zespół wewnętrzny i konsultant u klienta, z wersją),
* ``LifecycleCase`` — wejście albo odejście osoby (odejście: ostatni dzień
  pracy, przekazanie pracy o 18:00, wyłączenie konta w ``deactivate_on``),
* ``LifecycleTask`` — zadanie sprawy dla przełożonego, Kadr, recepcji, IT
  albo samej osoby,
* ``WorkHandover`` — przekazanie jednego rodzaju pracy przejmującemu.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_lifecycle_schema as schema


class LifecycleTemplate(Base, TimestampMixin):
    __tablename__ = "lifecycle_templates"
    __table_args__ = (
        CheckConstraint(schema.CK_TEMPLATE_KIND, name="ck_lifecycle_templates_kind"),
        CheckConstraint(
            schema.CK_TEMPLATE_EMPLOYMENT_TYPE,
            name="ck_lifecycle_templates_employment_type",
        ),
        CheckConstraint(
            schema.CK_TEMPLATE_AUDIENCE, name="ck_lifecycle_templates_audience"
        ),
        CheckConstraint(
            schema.CK_TEMPLATE_VERSION, name="ck_lifecycle_templates_version"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    employment_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    #: Zespół wewnętrzny albo konsultant u klienta (etap 3, O1).
    audience: Mapped[str] = mapped_column(
        String(16), nullable=False, default="team", server_default="team"
    )
    #: Każdy zapis ścieżki to nowa wersja; sprawa pamięta swoją (O5).
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class LifecycleTemplateItem(Base, TimestampMixin):
    __tablename__ = "lifecycle_template_items"
    __table_args__ = (
        CheckConstraint(
            schema.CK_ITEM_CATEGORY, name="ck_lifecycle_template_items_category"
        ),
        CheckConstraint(
            schema.CK_ITEM_ASSIGNEE, name="ck_lifecycle_template_items_assignee"
        ),
        CheckConstraint(
            schema.CK_ITEM_OFFSET, name="ck_lifecycle_template_items_offset"
        ),
        CheckConstraint(
            schema.CK_ITEM_CONDITIONS, name="ck_lifecycle_template_items_conditions"
        ),
        CheckConstraint(
            schema.CK_ITEM_ADDED_IN_VERSION,
            name="ck_lifecycle_template_items_added_in",
        ),
        Index("ix_lifecycle_template_items_template", "template_id", "position"),
        Index(
            "uq_lifecycle_template_items_key",
            "template_id",
            "key",
            unique=True,
            postgresql_where=text(schema.ITEM_KEY_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_templates.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, default="other", server_default="other"
    )
    assignee_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="people_admin",
        server_default="people_admin",
    )
    due_offset_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(schema.DESCRIPTION_MAX), nullable=True
    )
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    requires_file: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Warunki pozycji: ``employment_types`` (lista form), ``equipment``
    #: (``ours``/``client``), ``student`` (``true``). Pusty = zawsze.
    conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    #: Stały klucz pozycji (np. ``welcome_mail``) — czytają go inne moduły.
    key: Mapped[Optional[str]] = mapped_column(String(schema.KEY_MAX), nullable=True)
    #: Wersja ścieżki, w której pozycja się pojawiła („Dociągnij”).
    added_in_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class LifecycleCase(Base, TimestampMixin):
    __tablename__ = "lifecycle_cases"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_lifecycle_cases_source_key"),
        UniqueConstraint("compass_id", name="uq_lifecycle_cases_compass_id"),
        CheckConstraint(schema.CK_CASE_KIND, name="ck_lifecycle_cases_kind"),
        CheckConstraint(schema.CK_CASE_STATUS, name="ck_lifecycle_cases_status"),
        CheckConstraint(schema.CK_CASE_DATES, name="ck_lifecycle_cases_dates"),
        CheckConstraint(
            schema.CK_CASE_DEACTIVATE_ON, name="ck_lifecycle_cases_deactivate_on"
        ),
        CheckConstraint(schema.CK_CASE_PERSON, name="ck_lifecycle_cases_person"),
        CheckConstraint(
            schema.CK_CASE_EXIT_INITIATOR, name="ck_lifecycle_cases_exit_initiator"
        ),
        CheckConstraint(
            schema.CK_CASE_EXIT_REASON, name="ck_lifecycle_cases_exit_reason"
        ),
        CheckConstraint(
            schema.CK_CASE_EXIT_ONLY_OFFBOARDING,
            name="ck_lifecycle_cases_exit_only_offboarding",
        ),
        CheckConstraint(
            schema.CK_CASE_ACCOUNT_RESULT, name="ck_lifecycle_cases_account_result"
        ),
        Index(
            "uq_lifecycle_cases_live",
            "user_id",
            "kind",
            unique=True,
            postgresql_where=text(schema.LIVE_CASE_WHERE),
        ),
        Index(
            "uq_lifecycle_cases_pending_email",
            "pending_email",
            unique=True,
            postgresql_where=text(schema.PENDING_EMAIL_WHERE),
        ),
        CheckConstraint(schema.CK_CASE_AUDIENCE, name="ck_lifecycle_cases_audience"),
        CheckConstraint(
            schema.CK_CASE_CONSULTANT_CONTRACT,
            name="ck_lifecycle_cases_consultant_contract",
        ),
        CheckConstraint(
            schema.CK_CASE_TEMPLATE_VERSION,
            name="ck_lifecycle_cases_template_version",
        ),
        Index(
            "uq_lifecycle_cases_contract_live",
            "contract_id",
            "kind",
            unique=True,
            postgresql_where=text(schema.LIVE_CONTRACT_CASE_WHERE),
        ),
        Index("ix_lifecycle_cases_status_deactivate", "status", "deactivate_on"),
        Index("ix_lifecycle_cases_user", "user_id"),
        Index(
            "ix_lifecycle_cases_contract",
            "contract_id",
            postgresql_where=text(schema.CONTRACT_CASE_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    pending_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pending_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lifecycle_templates.id", ondelete="SET NULL"), nullable=True
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_working_day: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    deactivate_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    manager_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Pola kartoteki z kreatora wejścia (zapisywane w kartotece przy starcie).
    profile_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    exit_initiator: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    exit_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    handover_executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    account_closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    account_close_result: Mapped[Optional[str]] = mapped_column(
        String(24), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    compass_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    audience: Mapped[str] = mapped_column(
        String(16), nullable=False, default="team", server_default="team"
    )
    #: Kontrakt wejścia konsultanta (bez FK — scalenie i trwałe usunięcie
    #: kontraktu obsługują haki ``contract_hooks``).
    contract_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: Wersja ścieżki, z której powstały zadania sprawy.
    template_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class LifecycleTask(Base, TimestampMixin):
    __tablename__ = "lifecycle_tasks"
    __table_args__ = (
        CheckConstraint(schema.CK_TASK_CATEGORY, name="ck_lifecycle_tasks_category"),
        CheckConstraint(schema.CK_TASK_ASSIGNEE, name="ck_lifecycle_tasks_assignee"),
        CheckConstraint(schema.CK_TASK_STATUS, name="ck_lifecycle_tasks_status"),
        CheckConstraint(schema.CK_TASK_DONE_AT, name="ck_lifecycle_tasks_done_at"),
        CheckConstraint(schema.CK_TASK_SOURCE, name="ck_lifecycle_tasks_source"),
        Index("ix_lifecycle_tasks_case", "case_id", "position"),
        Index(
            "ix_lifecycle_tasks_assignee_open",
            "assignee_user_id",
            "due_date",
            postgresql_where=text(schema.OPEN_TASK_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_cases.id", ondelete="CASCADE"), nullable=False
    )
    template_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lifecycle_template_items.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, default="other", server_default="other"
    )
    assignee_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    done_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(
        String(schema.DESCRIPTION_MAX), nullable=True
    )
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    requires_file: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    key: Mapped[Optional[str]] = mapped_column(String(schema.KEY_MAX), nullable=True)
    #: ``path`` / ``client`` / ``form`` / ``manual`` (kolumna „Skąd”).
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    #: Nazwa klienta albo forma współpracy przy zadaniu z pakietu lub formy.
    source_label: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    #: Przesunięcie od startu (dni robocze) — pakiet klienta przelicza termin
    #: po zmianie daty startu kontraktu.
    due_offset_days: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)


class WorkHandover(Base, TimestampMixin):
    __tablename__ = "work_handovers"
    __table_args__ = (
        UniqueConstraint("case_id", "work_kind", name="uq_work_handovers_case_kind"),
        CheckConstraint(schema.CK_HANDOVER_KIND, name="ck_work_handovers_kind"),
        CheckConstraint(schema.CK_HANDOVER_STATUS, name="ck_work_handovers_status"),
        CheckConstraint(schema.CK_HANDOVER_COUNT, name="ck_work_handovers_count"),
        CheckConstraint(schema.CK_HANDOVER_EXECUTED, name="ck_work_handovers_executed"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_cases.id", ondelete="CASCADE"), nullable=False
    )
    work_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    receiver_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    item_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="planned", server_default="planned"
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    error: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
