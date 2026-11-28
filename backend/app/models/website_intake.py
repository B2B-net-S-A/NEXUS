"""Zgłoszenia trenera i polecenia ze strony B2B Network (0806) — modele.

CHECK-i i indeksy muszą być identyczne z ``app/services/website_intake_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import market_trainer_portal_schema as portal_schema
from app.services import website_intake_schema as schema


def _user_fk() -> Mapped[Optional[int]]:
    return mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _created() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def _json_list() -> Mapped[list[Any]]:
    return mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )


class MarketTrainerApplication(Base):
    """„Kandydat na trenera” spoza B2B — zgłoszenie z /dla-specjalistow."""

    __tablename__ = schema.TRAINERS
    __table_args__ = (
        CheckConstraint(schema.CK_TRAINER_STATUS, name=f"ck_{schema.TRAINERS}_status"),
        CheckConstraint(schema.CK_TRAINER_JSON, name=f"ck_{schema.TRAINERS}_json"),
        Index(f"uq_{schema.TRAINERS}_email", text("lower(email)"), unique=True),
        Index(f"ix_{schema.TRAINERS}_status", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    email: Mapped[str] = mapped_column(String(schema.EMAIL_MAX), nullable=False)
    linkedin: Mapped[Optional[str]] = mapped_column(
        String(schema.LINKEDIN_MAX), nullable=True
    )
    topics: Mapped[list[Any]] = _json_list()
    other_topic: Mapped[Optional[str]] = mapped_column(
        String(schema.TOPIC_MAX), nullable=True
    )
    first_training: Mapped[str] = mapped_column(
        String(schema.FIRST_TRAINING_MAX), nullable=False
    )
    experience: Mapped[str] = mapped_column(
        String(schema.EXPERIENCE_MAX), nullable=False
    )
    sample_url: Mapped[Optional[str]] = mapped_column(
        String(schema.URL_MAX), nullable=True
    )
    consents: Mapped[list[Any]] = _json_list()
    consented_at: Mapped[datetime] = _created()
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="new", default="new"
    )
    status_note: Mapped[str] = mapped_column(
        String(schema.NOTE_MAX), nullable=False, server_default="", default=""
    )
    status_changed_by: Mapped[Optional[int]] = _user_fk()
    status_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submissions: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", default=1
    )
    # 0808: panel trenera z rynku — dane firmy do umowy (TCM z Białej Listy),
    # adres logowania i kto/kiedy otworzył albo zamknął panel.
    company_name: Mapped[str] = mapped_column(
        String(portal_schema.COMPANY_MAX), nullable=False, server_default="", default=""
    )
    nip: Mapped[Optional[str]] = mapped_column(
        String(portal_schema.NIP_MAX), nullable=True
    )
    regon: Mapped[str] = mapped_column(
        String(portal_schema.REGON_MAX), nullable=False, server_default="", default=""
    )
    company_address: Mapped[str] = mapped_column(
        String(portal_schema.ADDRESS_MAX), nullable=False, server_default="", default=""
    )
    panel_email: Mapped[Optional[str]] = mapped_column(
        String(schema.EMAIL_MAX), nullable=True
    )
    panel_opened_by: Mapped[Optional[int]] = _user_fk()
    panel_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    panel_closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    @property
    def panel_open(self) -> bool:
        return (
            self.status == "accepted"
            and self.panel_opened_at is not None
            and self.panel_closed_at is None
            and bool(self.panel_email)
        )


class MtPortalLink(Base):
    """Jednorazowy link logowania trenera z rynku (hash tokenu, 30 minut)."""

    __tablename__ = portal_schema.LINKS
    __table_args__ = (
        UniqueConstraint("token_hash", name=f"uq_{portal_schema.LINKS}_token"),
        Index(f"ix_{portal_schema.LINKS}_application", "application_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey(f"{schema.TRAINERS}.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(schema.EMAIL_MAX), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created()


class MtPortalSession(Base):
    """Sesja trenera z rynku (nagłówek ``X-Portal-Session``, hash tokenu)."""

    __tablename__ = portal_schema.SESSIONS
    __table_args__ = (
        UniqueConstraint("token_hash", name=f"uq_{portal_schema.SESSIONS}_token"),
        Index(f"ix_{portal_schema.SESSIONS}_application", "application_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey(f"{schema.TRAINERS}.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(schema.EMAIL_MAX), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created()


class CandidateReferral(Base):
    """Polecenie inżyniera — od kogokolwiek, z premią 1–5 tys. zł."""

    __tablename__ = schema.REFERRALS
    __table_args__ = (
        CheckConstraint(
            schema.CK_REFERRAL_STATUS, name=f"ck_{schema.REFERRALS}_status"
        ),
        CheckConstraint(
            schema.CK_REFERRAL_CONTACT, name=f"ck_{schema.REFERRALS}_contact"
        ),
        CheckConstraint(schema.CK_REFERRAL_BONUS, name=f"ck_{schema.REFERRALS}_bonus"),
        CheckConstraint(schema.CK_REFERRAL_JSON, name=f"ck_{schema.REFERRALS}_json"),
        Index(f"ix_{schema.REFERRALS}_status", "status", "created_at"),
        Index(
            f"ix_{schema.REFERRALS}_candidate",
            "candidate_id",
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
        Index(f"ix_{schema.REFERRALS}_referrer_email", text("lower(referrer_email)")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    referrer_email: Mapped[str] = mapped_column(
        String(schema.EMAIL_MAX), nullable=False
    )
    referrer_candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    referrer_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    referred_name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    referred_email: Mapped[Optional[str]] = mapped_column(
        String(schema.EMAIL_MAX), nullable=True
    )
    referred_linkedin: Mapped[Optional[str]] = mapped_column(
        String(schema.LINKEDIN_MAX), nullable=True
    )
    referred_role: Mapped[Optional[str]] = mapped_column(
        String(schema.ROLE_MAX), nullable=True
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    submission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("application_submissions.id", ondelete="SET NULL"), nullable=True
    )
    was_in_database: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    statement_text: Mapped[str] = mapped_column(
        String(schema.CONSENT_MAX), nullable=False
    )
    consents: Mapped[list[Any]] = _json_list()
    consented_at: Mapped[datetime] = _created()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="new", default="new"
    )
    bonus_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    status_note: Mapped[str] = mapped_column(
        String(schema.NOTE_MAX), nullable=False, server_default="", default=""
    )
    status_changed_by: Mapped[Optional[int]] = _user_fk()
    status_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
