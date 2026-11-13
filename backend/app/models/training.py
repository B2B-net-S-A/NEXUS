"""Szkolenia i trenerzy — modele (0694).

CHECK-i i indeksy muszą być identyczne z ``app/services/trainings_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
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
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import trainings_schema as schema


def _fee() -> Mapped[Optional[Decimal]]:
    return mapped_column(Numeric(12, 2), nullable=True)


def _text(length: int) -> Mapped[str]:
    return mapped_column(String(length), nullable=False, server_default="", default="")


def _user_fk() -> Mapped[Optional[int]]:
    return mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Training(Base):
    __tablename__ = "trainings"
    __table_args__ = (
        CheckConstraint(schema.CK_STATUS, name="ck_trainings_status"),
        CheckConstraint(schema.CK_TRAINER_KIND, name="ck_trainings_trainer_kind"),
        CheckConstraint(schema.CK_TRAINER, name="ck_trainings_trainer"),
        CheckConstraint(schema.CK_JSON_ARRAYS, name="ck_trainings_json"),
        CheckConstraint(schema.CK_PARTNER, name="ck_trainings_partner"),
        CheckConstraint(schema.CK_FEES, name="ck_trainings_fees"),
        Index(
            "ix_trainings_trainer_contract",
            "trainer_contract_id",
            postgresql_where=text("trainer_contract_id IS NOT NULL"),
        ),
        Index("ix_trainings_status", "status"),
        Index(
            "ix_trainings_published",
            "published_at",
            postgresql_where=text("published_at IS NOT NULL"),
        ),
        Index(
            "ix_trainings_recording_due",
            "recording_next_at",
            postgresql_where=text("recording_status = 'waiting'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(schema.TITLE_MAX), nullable=False)
    topic: Mapped[str] = _text(schema.TITLE_MAX)
    description: Mapped[str] = _text(schema.DESCRIPTION_MAX)
    trainer_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="consultant", default="consultant"
    )
    trainer_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    trainer_user_id: Mapped[Optional[int]] = _user_fk()
    application_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cp_trainer_applications.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft", default="draft"
    )
    session_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    time_from: Mapped[str] = _text(5)
    time_to: Mapped[str] = _text(5)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    platform: Mapped[str] = mapped_column(
        String(schema.TITLE_MAX),
        nullable=False,
        server_default="Microsoft Teams",
        default="Microsoft Teams",
    )
    join_url: Mapped[str] = _text(schema.PATH_MAX)
    expected_participants: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quote_due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    participant_materials: Mapped[str] = _text(schema.TEXT_MAX)
    deliverables: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    agenda: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    own_materials: Mapped[str] = _text(schema.TEXT_MAX)
    third_party_materials: Mapped[str] = _text(schema.TEXT_MAX)
    extra_terms: Mapped[str] = _text(schema.TEXT_MAX)
    knowledge_test: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    fee_prep: Mapped[Optional[Decimal]] = _fee()
    fee_delivery: Mapped[Optional[Decimal]] = _fee()
    fee_presentation: Mapped[Optional[Decimal]] = _fee()
    fee_audio: Mapped[Optional[Decimal]] = _fee()
    fee_rights: Mapped[Optional[Decimal]] = _fee()
    quote_note: Mapped[str] = _text(schema.TEXT_MAX)
    return_note: Mapped[str] = _text(schema.TEXT_MAX)
    ordered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quoted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[Optional[int]] = _user_fk()
    agreement_number: Mapped[str] = _text(50)
    partner: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    agreement_pdf_path: Mapped[Optional[str]] = mapped_column(
        String(schema.PATH_MAX), nullable=True
    )
    agreement_pdf_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    agreement_generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trainer_signed_pdf_path: Mapped[Optional[str]] = mapped_column(
        String(schema.PATH_MAX), nullable=True
    )
    trainer_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    company_signed_pdf_path: Mapped[Optional[str]] = mapped_column(
        String(schema.PATH_MAX), nullable=True
    )
    company_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    company_signed_by: Mapped[Optional[int]] = _user_fk()
    invoice_ready_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_marked_by: Mapped[Optional[int]] = _user_fk()
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by: Mapped[Optional[int]] = _user_fk()
    case_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admin_cases.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[Optional[int]] = _user_fk()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_reason: Mapped[str] = _text(schema.NOTE_MAX)
    # 0697: spotkanie Teams z NEXUSA, nagranie z Graph, udostępnienie zapisanym.
    seat_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    teams_event_id: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    teams_meeting_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    teams_status: Mapped[str] = _text(20)
    teams_error: Mapped[str] = _text(schema.NOTE_MAX)
    teams_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recording_status: Mapped[str] = _text(20)
    recording_next_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    shared_registered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    shared_registered_by: Mapped[Optional[int]] = _user_fk()
    reminder_day_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_soon_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TrainingFile(Base):
    __tablename__ = "training_files"
    __table_args__ = (
        CheckConstraint(schema.CK_FILE_KIND, name="ck_training_files_kind"),
        CheckConstraint(schema.CK_FILE_STATUS, name="ck_training_files_status"),
        CheckConstraint(schema.CK_FILE_KEY, name="ck_training_files_key"),
        CheckConstraint(schema.CK_FILE_STORAGE, name="ck_training_files_storage"),
        Index("ix_training_files_training", "training_id", "kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_id: Mapped[int] = mapped_column(
        ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    deliverable_key: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="submitted", default="submitted"
    )
    file_name: Mapped[str] = mapped_column(String(schema.FILE_NAME_MAX), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        server_default="application/octet-stream",
        default="application/octet-stream",
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0"), default=0
    )
    sha256: Mapped[str] = _text(64)
    storage: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="local", default="local"
    )
    storage_key: Mapped[str] = mapped_column(String(schema.PATH_MAX), nullable=False)
    sp_drive_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    uploaded_by_user_id: Mapped[Optional[int]] = _user_fk()
    uploaded_by_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    review_note: Mapped[str] = _text(schema.NOTE_MAX)
    reviewed_by: Mapped[Optional[int]] = _user_fk()
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fix_due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    for_participants: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )


class TrainingRegistration(Base):
    __tablename__ = "training_registrations"
    __table_args__ = (
        CheckConstraint(
            schema.CK_REGISTRATION_WHO, name="ck_training_registrations_who"
        ),
        Index(
            "uq_training_registrations_user",
            "training_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_training_registrations_contract",
            "training_id",
            "contract_id",
            unique=True,
            postgresql_where=text("contract_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_id: Mapped[int] = mapped_column(
        ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    invite_event_id: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    invite_status: Mapped[str] = _text(20)


class TrainingAttendance(Base):
    __tablename__ = "training_attendance"
    __table_args__ = (Index("ix_training_attendance_training", "training_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_id: Mapped[int] = mapped_column(
        ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = _text(schema.FILE_NAME_MAX)
    email: Mapped[str] = _text(255)
    minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_id: Mapped[Optional[int]] = _user_fk()
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrainingTranscript(Base):
    """Transkrypt VTT spotkania (0697); osobna tabela, żeby lista szkoleń go nie ładowała."""

    __tablename__ = "training_transcripts"

    training_id: Mapped[int] = mapped_column(
        ForeignKey("trainings.id", ondelete="CASCADE"), primary_key=True
    )
    vtt: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="", default=""
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrainingFeedback(Base):
    """Ocena szkolenia 1–5 od zapisanego albo obecnego (0697)."""

    __tablename__ = "training_feedback"
    __table_args__ = (
        CheckConstraint(schema.CK_FEEDBACK_RATING, name="ck_training_feedback_rating"),
        CheckConstraint(schema.CK_FEEDBACK_WHO, name="ck_training_feedback_who"),
        Index(
            "uq_training_feedback_user",
            "training_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_training_feedback_contract",
            "training_id",
            "contract_id",
            unique=True,
            postgresql_where=text("contract_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_id: Mapped[int] = mapped_column(
        ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str] = _text(schema.FEEDBACK_COMMENT_MAX)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
