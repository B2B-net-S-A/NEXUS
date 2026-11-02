"""Portal konsultanta — modele (0638).

CHECK-i i indeksy muszą być identyczne z ``app/services/consultant_portal_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import consultant_portal_schema as schema


class CpMeeting(Base):
    __tablename__ = "cp_meetings"
    __table_args__ = (
        UniqueConstraint("client_request_id", name="uq_cp_meetings_request"),
        CheckConstraint(schema.CK_MEETING_TOPIC, name="ck_cp_meetings_topic"),
        CheckConstraint(schema.CK_MEETING_STATUS, name="ck_cp_meetings_status"),
        CheckConstraint(schema.CK_MEETING_TRANSCRIPT, name="ck_cp_meetings_transcript"),
        CheckConstraint(schema.CK_MEETING_SUMMARY, name="ck_cp_meetings_summary"),
        CheckConstraint(schema.CK_MEETING_SPAN, name="ck_cp_meetings_span"),
        CheckConstraint(schema.CK_MEETING_ITEMS, name="ck_cp_meetings_items"),
        Index(
            "uq_cp_meetings_host_slot",
            "host_user_id",
            "start_at",
            unique=True,
            postgresql_where=text("status IN ('pending', 'booked')"),
        ),
        Index("ix_cp_meetings_contract", "contract_id", "start_at"),
        Index(
            "ix_cp_meetings_fetch",
            "next_fetch_at",
            postgresql_where=text("next_fetch_at IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    host_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    case_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("admin_cases.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str] = mapped_column(
        String(schema.REASON_MAX), nullable=False, server_default="", default=""
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="pending", default="pending"
    )
    client_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    organizer_upn: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    graph_event_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    join_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organizer_aad_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    online_meeting_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    transcript_status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="waiting", default="waiting"
    )
    next_fetch_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetch_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    last_error: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    transcript_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transcript_purged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    summary_status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="pending", default="pending"
    )
    rating_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CpLink(Base):
    __tablename__ = "cp_links"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_cp_links_token"),
        CheckConstraint(schema.CK_LINK_PURPOSE, name="ck_cp_links_purpose"),
        CheckConstraint(schema.CK_LINK_MEETING, name="ck_cp_links_meeting"),
        Index("ix_cp_links_contract", "contract_id", "purpose", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="login", default="login"
    )
    meeting_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("cp_meetings.id", ondelete="CASCADE"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CpSession(Base):
    __tablename__ = "cp_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_cp_sessions_token"),
        Index("ix_cp_sessions_contract", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sms_verified_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CpSmsCode(Base):
    __tablename__ = "cp_sms_codes"
    __table_args__ = (
        CheckConstraint(schema.CK_SMS_ATTEMPTS, name="ck_cp_sms_codes_attempts"),
        Index("ix_cp_sms_codes_contract", "contract_id", "created_at"),
        Index("ix_cp_sms_codes_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cp_sessions.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), default=0
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CpFaqItem(Base):
    __tablename__ = "cp_faq_items"
    __table_args__ = (
        CheckConstraint(schema.CK_FAQ_TOPIC, name="ck_cp_faq_items_topic"),
        CheckConstraint(schema.CK_FAQ_QUESTION, name="ck_cp_faq_items_question"),
        CheckConstraint(schema.CK_FAQ_ANSWER, name="ck_cp_faq_items_answer"),
        Index("ix_cp_faq_items_topic", "topic", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(12), nullable=False)
    question: Mapped[str] = mapped_column(String(schema.QUESTION_MAX), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), default=0
    )
    published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CpRating(Base):
    __tablename__ = "cp_ratings"
    __table_args__ = (
        UniqueConstraint("meeting_id", name="uq_cp_ratings_meeting"),
        CheckConstraint(schema.CK_RATING_SCORE, name="ck_cp_ratings_score"),
        CheckConstraint(schema.CK_RATING_FOLLOWUP, name="ck_cp_ratings_followup"),
        CheckConstraint(schema.CK_RATING_LOW, name="ck_cp_ratings_low"),
        Index("ix_cp_ratings_host", "host_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cp_meetings.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    host_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    resolved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(
        String(schema.COMMENT_MAX), nullable=True
    )
    followup_status: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="none", default="none"
    )
    followup_due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    followup_note: Mapped[Optional[str]] = mapped_column(
        String(schema.COMMENT_MAX), nullable=True
    )
    followup_done_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    followup_done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CpDocument(Base):
    __tablename__ = "cp_documents"
    __table_args__ = (
        CheckConstraint(schema.CK_DOCUMENT_KIND, name="ck_cp_documents_kind"),
        CheckConstraint(schema.CK_DOCUMENT_CHANNEL, name="ck_cp_documents_channel"),
        CheckConstraint(schema.CK_DOCUMENT_STATUS, name="ck_cp_documents_status"),
        CheckConstraint(schema.CK_DOCUMENT_MONTH, name="ck_cp_documents_month"),
        CheckConstraint(schema.CK_DOCUMENT_SIZE, name="ck_cp_documents_size"),
        Index(
            "uq_cp_documents_file",
            "contract_id",
            "kind",
            "period_year",
            "period_month",
            "sha256",
            unique=True,
            postgresql_where=text("contract_id IS NOT NULL"),
        ),
        Index(
            "uq_cp_documents_mail_file",
            "graph_message_id",
            "sha256",
            unique=True,
            postgresql_where=text("graph_message_id IS NOT NULL"),
        ),
        Index("ix_cp_documents_contract", "contract_id", "period_year", "period_month"),
        Index("ix_cp_documents_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    period_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_guessed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="received", default="received"
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(
        String(schema.FILE_NAME_MAX), nullable=True
    )
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_message_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    sender_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    decided_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reject_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.COMMENT_MAX), nullable=True
    )
    invoice_signal_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CpMailboxState(Base):
    __tablename__ = "cp_mailbox_state"
    __table_args__ = (
        CheckConstraint(
            schema.CK_STATE_SINGLETON, name="ck_cp_mailbox_state_singleton"
        ),
        CheckConstraint(schema.CK_STATE_STATUS, name="ck_cp_mailbox_state_status"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, server_default=text("1"), default=1
    )
    last_seen_received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
