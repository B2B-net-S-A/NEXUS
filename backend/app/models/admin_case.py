"""„Ludzie w NEXUSIE” — modele: Sprawy administracja@ (0462).

CHECK-i i indeksy muszą być identyczne z ``app/services/*_schema.py`` modułu
(strażnik dryfu schematu porównuje model z bazą po migracji).

* ``AdminCase`` — sprawa na kanbanie skrzynki administracja@ (ręczna, z maila,
  z nowego kontraktu, z odejścia, z importu Compassa),
* ``AdminCaseMessage`` — mail przypięty do sprawy (tekst po oczyszczeniu,
  załączniki tylko jako metadane — bez treści plików),
* ``AdminCaseComment`` — notatka obsługi,
* ``AdminMailIngestState`` — jeden wiersz stanu czytnika skrzynki.
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
from app.services import admin_cases_schema as schema


class AdminCase(Base, TimestampMixin):
    __tablename__ = "admin_cases"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_admin_cases_source_key"),
        CheckConstraint(schema.CK_CASE_AREA, name="ck_admin_cases_area"),
        CheckConstraint(schema.CK_CASE_PRIORITY, name="ck_admin_cases_priority"),
        CheckConstraint(schema.CK_CASE_STATUS, name="ck_admin_cases_status"),
        CheckConstraint(schema.CK_CASE_SOURCE, name="ck_admin_cases_source"),
        CheckConstraint(schema.CK_CASE_TITLE, name="ck_admin_cases_title"),
        CheckConstraint(schema.CK_CASE_CHECKLIST, name="ck_admin_cases_checklist"),
        CheckConstraint(schema.CK_CASE_CLOSED, name="ck_admin_cases_closed"),
        CheckConstraint(schema.CK_CASE_SOURCE_KEY, name="ck_admin_cases_source_key"),
        Index("ix_admin_cases_status", "status", "updated_at"),
        Index("ix_admin_cases_assignee", "assignee_user_id", "status"),
        Index("ix_admin_cases_contract", "contract_id"),
        Index("ix_admin_cases_subject", "subject_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    area: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="administration",
        server_default="administration",
    )
    priority: Mapped[str] = mapped_column(
        String(2), nullable=False, default="P2", server_default="P2"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="new", server_default="new"
    )
    due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    follow_up_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default="manual"
    )
    source_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    subject_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Bez FK: tabela spraw wejścia/odejścia (moduł cyklu życia) powstaje osobno.
    lifecycle_case_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AdminCaseMessage(Base):
    __tablename__ = "admin_case_messages"
    __table_args__ = (
        UniqueConstraint("graph_message_id", name="uq_admin_case_messages_graph"),
        CheckConstraint(
            schema.CK_MESSAGE_ATTACHMENTS, name="ck_admin_case_messages_attachments"
        ),
        Index("ix_admin_case_messages_case", "case_id", "received_at"),
        Index("ix_admin_case_messages_conversation", "conversation_id"),
        Index("ix_admin_case_messages_internet", "internet_message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("admin_cases.id", ondelete="CASCADE"), nullable=False
    )
    graph_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    internet_message_id: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    conversation_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    sender_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    body_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdminCaseComment(Base):
    __tablename__ = "admin_case_comments"
    __table_args__ = (
        CheckConstraint(schema.CK_COMMENT_BODY, name="ck_admin_case_comments_body"),
        Index("ix_admin_case_comments_case", "case_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("admin_cases.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdminMailIngestState(Base):
    __tablename__ = "admin_mail_ingest_state"
    __table_args__ = (
        CheckConstraint(
            schema.CK_STATE_SINGLETON, name="ck_admin_mail_ingest_state_singleton"
        ),
        CheckConstraint(
            schema.CK_STATE_STATUS, name="ck_admin_mail_ingest_state_status"
        ),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, default=1, server_default="1"
    )
    mailbox: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    last_received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
