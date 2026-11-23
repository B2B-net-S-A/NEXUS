"""Wypowiedzenia z poczty (0757) — modele.

CHECK-i i indeksy muszą być identyczne z ``app/services/notice_mail_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).

* ``NoticeMailProposal`` — co czytnik rozpoznał w mailu i co proponuje karta,
* ``KnownSenderEmail`` — potwierdzony adres konsultanta spoza kontraktu i profilu,
* ``ArchivedMail`` — mail z archiwum administracja@ (home.pl) przy kontrakcie.
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
from sqlalchemy.dialects.postgresql import CHAR, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import notice_mail_schema as schema


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class NoticeMailProposal(Base):
    __tablename__ = "notice_mail_proposals"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_notice_mail_proposals_message"),
        CheckConstraint(
            f"kind IN ({_quoted(schema.KINDS)})", name="ck_notice_mail_proposals_kind"
        ),
        CheckConstraint(
            f"status IN ({_quoted(schema.STATUSES)})",
            name="ck_notice_mail_proposals_status",
        ),
        CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)",
            name="ck_notice_mail_proposals_decided",
        ),
        Index("ix_notice_mail_proposals_case", "case_id", "status"),
        Index(
            "ix_notice_mail_proposals_contract",
            "contract_id",
            postgresql_where=text("contract_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_cases.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_case_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=text("'pending'")
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("client_orders.id", ondelete="SET NULL"), nullable=True
    )
    delivered_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    proposed_last_day: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    client_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    contract_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    cpro_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    match: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    decision: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    decided_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KnownSenderEmail(Base):
    __tablename__ = "known_sender_emails"
    __table_args__ = (
        CheckConstraint(
            "email = lower(btrim(email))", name="ck_known_sender_emails_lower"
        ),
        CheckConstraint(
            f"source IN ({_quoted(schema.SENDER_SOURCES)})",
            name="ck_known_sender_emails_source",
        ),
        Index("ix_known_sender_emails_candidate", "candidate_id"),
    )

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    confirmed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ArchivedMail(Base):
    __tablename__ = "archived_mails"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_archived_mails_sha256"),
        Index(
            "ix_archived_mails_contract",
            "contract_id",
            "received_at",
            postgresql_where=text("contract_id IS NOT NULL"),
        ),
        Index(
            "ix_archived_mails_candidate",
            "candidate_id",
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(32), nullable=False)
    folder: Mapped[str] = mapped_column(String(200), nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    message_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    sender_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    to_emails: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body_text: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    eml_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    match_reason: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
