"""„Ludzie w NEXUSIE” — modele: komunikaty do konsultantów (0465, O12).

CHECK-i i indeksy muszą być identyczne z ``app/services/care_announcements_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).

* ``CareAnnouncement`` — komunikat (szkic → zatwierdzenie → kolejka → raport),
* ``CareAnnouncementRecipient`` — odbiorca z zamrożonej listy i stan jego maila,
* ``CareAnnouncementOptOut`` — wypis z komunikatów informacyjnych,
* ``CareAnnouncementReply`` — sprawa administracja@ z odpowiedzią albo odbitym mailem.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from app.services import care_announcements_schema as schema


class CareAnnouncement(Base, TimestampMixin):
    __tablename__ = "care_announcements"
    __table_args__ = (
        CheckConstraint(schema.CK_KIND, name="ck_care_announcements_kind"),
        CheckConstraint(schema.CK_STATUS, name="ck_care_announcements_status"),
        CheckConstraint(schema.CK_SUBJECT, name="ck_care_announcements_subject"),
        CheckConstraint(schema.CK_BODY, name="ck_care_announcements_body"),
        CheckConstraint(schema.CK_CODE, name="ck_care_announcements_code"),
        CheckConstraint(schema.CK_AUDIENCE, name="ck_care_announcements_audience"),
        CheckConstraint(schema.CK_TESTED, name="ck_care_announcements_tested"),
        CheckConstraint(schema.CK_VERSIONS, name="ck_care_announcements_versions"),
        CheckConstraint(schema.CK_APPROVER, name="ck_care_announcements_approver"),
        CheckConstraint(schema.CK_APPROVED, name="ck_care_announcements_approved"),
        CheckConstraint(schema.CK_QUEUED, name="ck_care_announcements_queued"),
        Index("ix_care_announcements_status", "status", "created_at"),
        Index("ix_care_announcements_author", "created_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="mandatory", server_default="mandatory"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    subject: Mapped[str] = mapped_column(String(schema.SUBJECT_MAX), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    content_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    tested_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    recipient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    return_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    queued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    send_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    send_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CareAnnouncementRecipient(Base, TimestampMixin):
    __tablename__ = "care_announcement_recipients"
    __table_args__ = (
        UniqueConstraint(
            "announcement_id",
            "candidate_id",
            name="uq_care_announcement_recipients_person",
        ),
        UniqueConstraint(
            "unsubscribe_token_sha256", name="uq_care_announcement_recipients_token"
        ),
        CheckConstraint(
            schema.CK_RECIPIENT_STATUS, name="ck_care_announcement_recipients_status"
        ),
        CheckConstraint(
            schema.CK_RECIPIENT_EMAIL, name="ck_care_announcement_recipients_email"
        ),
        CheckConstraint(
            schema.CK_RECIPIENT_SENT, name="ck_care_announcement_recipients_sent"
        ),
        CheckConstraint(
            schema.CK_RECIPIENT_ATTEMPTS,
            name="ck_care_announcement_recipients_attempts",
        ),
        CheckConstraint(
            schema.CK_RECIPIENT_TOKEN, name="ck_care_announcement_recipients_token"
        ),
        CheckConstraint(
            schema.CK_RECIPIENT_UNSUBSCRIBED,
            name="ck_care_announcement_recipients_unsubscribed",
        ),
        Index("ix_care_announcement_recipients_queue", "status", "announcement_id"),
        Index("ix_care_announcement_recipients_candidate", "candidate_id"),
        Index("ix_care_announcement_recipients_contract", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("care_announcements.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unsubscribe_token_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    unsubscribed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bounced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CareAnnouncementOptOut(Base):
    __tablename__ = "care_announcement_opt_outs"

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True
    )
    recipient_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("care_announcement_recipients.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CareAnnouncementReply(Base):
    __tablename__ = "care_announcement_replies"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_care_announcement_replies_case"),
        CheckConstraint(schema.CK_REPLY_KIND, name="ck_care_announcement_replies_kind"),
        Index("ix_care_announcement_replies_announcement", "announcement_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("care_announcements.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[int] = mapped_column(
        ForeignKey("admin_cases.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("care_announcement_recipients.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(
        String(10), nullable=False, default="reply", server_default="reply"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
