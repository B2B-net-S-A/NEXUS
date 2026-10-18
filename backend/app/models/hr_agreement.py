"""„Ludzie w NEXUSIE” — modele: umowy z ludźmi (0469, etap 5, E5).

CHECK-i i indeksy muszą być identyczne z ``app/services/hr_agreements_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji). Opis tabel
i stanów — w docstringu modułu schematu.

* ``HrAgreementTemplate`` — wzór umowy (rodzaj, nazwa, w użyciu),
* ``HrAgreementTemplateVersion`` — wersja pliku wzoru (treść DOCX, pola),
* ``HrAgreement`` — umowa albo aneks z osobą (szkic → wysłana → podpisana /
  odrzucona / anulowana) i przepisanie do kartoteki po podpisie.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_agreements_schema as schema


class HrAgreementTemplate(Base, TimestampMixin):
    """Wzór umowy wgrany przez Kadry — wersje pliku w ``HrAgreementTemplateVersion``."""

    __tablename__ = "hr_agreement_templates"
    __table_args__ = (
        CheckConstraint(schema.CK_TEMPLATE_KIND, name="ck_hr_agreement_templates_kind"),
        CheckConstraint(schema.CK_TEMPLATE_NAME, name="ck_hr_agreement_templates_name"),
        Index(
            "ux_hr_agreement_templates_active_name",
            "kind",
            "name",
            unique=True,
            postgresql_where=text(schema.TEMPLATE_ACTIVE_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(schema.NAME_MAX_LENGTH), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(
        String(schema.DESCRIPTION_MAX_LENGTH), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrAgreementTemplateVersion(Base):
    """Wersja pliku wzoru — niezmienna; treść ładowana dopiero na żądanie."""

    __tablename__ = "hr_agreement_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "version", name="uq_hr_agreement_template_versions_number"
        ),
        CheckConstraint(
            schema.CK_VERSION_NUMBER, name="ck_hr_agreement_template_versions_number"
        ),
        CheckConstraint(
            schema.CK_VERSION_SIZE, name="ck_hr_agreement_template_versions_size"
        ),
        CheckConstraint(
            schema.CK_VERSION_SHA, name="ck_hr_agreement_template_versions_sha"
        ),
        CheckConstraint(
            schema.CK_VERSION_FIELDS, name="ck_hr_agreement_template_versions_fields"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("hr_agreement_templates.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HrAgreement(Base, TimestampMixin):
    """Umowa albo aneks z osobą zespołu."""

    __tablename__ = "hr_agreements"
    __table_args__ = (
        CheckConstraint(schema.CK_AGREEMENT_KIND, name="ck_hr_agreements_kind"),
        CheckConstraint(schema.CK_AGREEMENT_TYPE, name="ck_hr_agreements_type"),
        CheckConstraint(schema.CK_AGREEMENT_STATUS, name="ck_hr_agreements_status"),
        CheckConstraint(schema.CK_AGREEMENT_CURRENCY, name="ck_hr_agreements_currency"),
        CheckConstraint(schema.CK_AGREEMENT_RATE, name="ck_hr_agreements_rate"),
        CheckConstraint(schema.CK_AGREEMENT_DATES, name="ck_hr_agreements_dates"),
        CheckConstraint(
            schema.CK_AGREEMENT_PAYOUT_DAY, name="ck_hr_agreements_payout_day"
        ),
        CheckConstraint(schema.CK_AGREEMENT_BASE, name="ck_hr_agreements_base"),
        CheckConstraint(
            schema.CK_AGREEMENT_MANDATE_HOURS, name="ck_hr_agreements_mandate_hours"
        ),
        CheckConstraint(schema.CK_AGREEMENT_CHANNEL, name="ck_hr_agreements_channel"),
        CheckConstraint(schema.CK_AGREEMENT_SENT, name="ck_hr_agreements_sent"),
        CheckConstraint(schema.CK_AGREEMENT_SIGNED, name="ck_hr_agreements_signed"),
        CheckConstraint(schema.CK_AGREEMENT_MANUAL, name="ck_hr_agreements_manual"),
        CheckConstraint(schema.CK_AGREEMENT_REJECTED, name="ck_hr_agreements_rejected"),
        CheckConstraint(
            schema.CK_AGREEMENT_CANCELLED, name="ck_hr_agreements_cancelled"
        ),
        CheckConstraint(schema.CK_AGREEMENT_FIELDS, name="ck_hr_agreements_fields"),
        CheckConstraint(schema.CK_AGREEMENT_APPLIED, name="ck_hr_agreements_applied"),
        CheckConstraint(schema.CK_AGREEMENT_SYMFONIA, name="ck_hr_agreements_symfonia"),
        CheckConstraint(schema.CK_AGREEMENT_HASHES, name="ck_hr_agreements_hashes"),
        CheckConstraint(schema.CK_AGREEMENT_ATTEMPTS, name="ck_hr_agreements_attempts"),
        Index(
            "ux_hr_agreements_live",
            "user_id",
            "kind",
            unique=True,
            postgresql_where=text(schema.LIVE_AGREEMENT_WHERE),
        ),
        Index(
            "ux_hr_agreements_autenti_process",
            "autenti_process_id",
            unique=True,
            postgresql_where=text(schema.AUTENTI_PROCESS_WHERE),
        ),
        Index("ix_hr_agreements_user", "user_id", "created_at"),
        Index("ix_hr_agreements_status", "status", "applied_at"),
        Index("ix_hr_agreements_template_version", "template_version_id"),
        Index(
            "ix_hr_agreements_symfonia",
            "user_id",
            postgresql_where=text(schema.SYMFONIA_PENDING_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(16), nullable=False)
    template_version_id: Mapped[int] = mapped_column(
        ForeignKey("hr_agreement_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    base_agreement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hr_agreements.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    agreement_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: Potwierdzanie godzin (art. 8b) = miesięczny raport w NEXUSIE
    #: (``employee_profiles.timesheet_required`` po podpisie).
    hours_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    payout_day: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    coordinator_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Wartości pól wzoru zamrożone przy wysyłce albo ręcznym podpisie.
    document_fields: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    sent_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    document_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signing_channel: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    autenti_process_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    send_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    signer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    signed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    manual_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX_LENGTH), nullable=True
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX_LENGTH), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        String(schema.ERROR_MAX_LENGTH), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    apply_error: Mapped[Optional[str]] = mapped_column(
        String(schema.ERROR_MAX_LENGTH), nullable=True
    )
    #: Dokument w e-teczce osoby (moduł dokumentów osoby, E4).
    document_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    symfonia_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    symfonia_exported_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
