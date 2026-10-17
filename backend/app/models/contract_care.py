"""„Ludzie w NEXUSIE” — modele: Opieka nad konsultantami, technologie i opinie klienta (0459).

CHECK-i i indeksy muszą być identyczne z ``app/services/*_schema.py`` modułu
(strażnik dryfu schematu porównuje model z bazą po migracji).

Kolumny dołożone do istniejących tabel (``contracts.care_owner_user_id``,
``clients.default_care_owner_user_id``, ``contacts.reports_to_contact_id``,
``contacts.client_area_id``) nie są polami modeli ``Contract``, ``Client``
i ``Contact`` — serwisy opieki czytają je przez lekkie odwzorowania
``CONTRACTS_CARE``, ``CLIENTS_CARE`` i ``CONTACTS_ORG`` niżej. Gdyby DDL modułu
nie wszedł przy starcie, padają wtedy ekrany opieki, a nie każdy odczyt
kontraktu, klienta i kontaktu w aplikacji.
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
    Text,
    UniqueConstraint,
    column,
    func,
    table,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import contract_care_schema as schema

#: Kolumny opieki w istniejących tabelach (``COLUMN_DDL`` migracji 0459).
CONTRACTS_CARE = table("contracts", column("id"), column("care_owner_user_id"))
CLIENTS_CARE = table("clients", column("id"), column("default_care_owner_user_id"))
#: Struktura u klienta (przełożony i dział kontaktu).
CONTACTS_ORG = table(
    "contacts",
    column("id"),
    column("client_id"),
    column("reports_to_contact_id"),
    column("client_area_id"),
)


class ClientArea(Base):
    """Obszar u klienta (np. Płatności) — słownik per klient."""

    __tablename__ = "client_areas"
    __table_args__ = (
        UniqueConstraint("client_id", "name_key", name="uq_client_areas_client_name"),
        Index("ix_client_areas_client", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    name_key: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TechVendor(Base):
    """Dostawca u klienta (firma zewnętrzna w zespole)."""

    __tablename__ = "tech_vendors"
    __table_args__ = (UniqueConstraint("name_key", name="uq_tech_vendors_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    name_key: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CareConversation(Base, TimestampMixin):
    """Rozmowa opiekuna z konsultantem (bez danych zdrowotnych i stawek)."""

    __tablename__ = "care_conversations"
    __table_args__ = (
        UniqueConstraint("compass_source_id", name="uq_care_conversations_compass"),
        CheckConstraint(schema.CK_CONV_CHANNEL, name="ck_care_conversations_channel"),
        CheckConstraint(
            schema.CK_CONV_SATISFACTION, name="ck_care_conversations_satisfaction"
        ),
        CheckConstraint(schema.CK_CONV_NOTE, name="ck_care_conversations_note"),
        CheckConstraint(
            schema.CK_CONV_FOLLOW_UP, name="ck_care_conversations_follow_up"
        ),
        Index("ix_care_conversations_contract", "contract_id", "occurred_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="phone", server_default="phone"
    )
    satisfaction: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attrition_risk: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    wants_change: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    project_end_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    client_hiring: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    client_hiring_note: Mapped[Optional[str]] = mapped_column(
        String(schema.SHORT_TEXT_MAX), nullable=True
    )
    follow_up_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    compass_source_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class CarePlanItem(Base):
    """Punkt planu kontaktów kontraktu (``seq`` rozróżnia kwartały i daty końca)."""

    __tablename__ = "contract_care_plan_items"
    __table_args__ = (
        UniqueConstraint(
            "contract_id", "kind", "seq", name="uq_contract_care_plan_items_slot"
        ),
        CheckConstraint(schema.CK_PLAN_KIND, name="ck_contract_care_plan_items_kind"),
        CheckConstraint(
            schema.CK_PLAN_STATUS, name="ck_contract_care_plan_items_status"
        ),
        CheckConstraint(
            schema.CK_PLAN_RESOLUTION, name="ck_contract_care_plan_items_resolution"
        ),
        Index("ix_contract_care_plan_items_due", "status", "due_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    seq: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    done_conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("care_conversations.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TechCard(Base, TimestampMixin):
    """Karta technologiczna kontraktu (projektu u klienta)."""

    __tablename__ = "tech_cards"
    __table_args__ = (
        UniqueConstraint("compass_card_id", name="uq_tech_cards_compass"),
        CheckConstraint(schema.CK_CARD_STATUS, name="ck_tech_cards_status"),
        CheckConstraint(schema.CK_CARD_FINAL, name="ck_tech_cards_final"),
        CheckConstraint(
            schema.CK_CARD_HIRING_SOURCE, name="ck_tech_cards_hiring_source"
        ),
        CheckConstraint(schema.CK_CARD_SATISFACTION, name="ck_tech_cards_satisfaction"),
        CheckConstraint(schema.CK_CARD_EXTERNALS, name="ck_tech_cards_externals"),
        CheckConstraint(schema.CK_CARD_SALES_STATUS, name="ck_tech_cards_sales_status"),
        Index("ix_tech_cards_client", "client_id", "interview_on"),
        Index("ix_tech_cards_contract", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    client_area_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_areas.id", ondelete="SET NULL"), nullable=True
    )
    author_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    interview_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    is_draft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    finalized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    satisfaction: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    hiring: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    hiring_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    hiring_roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    project_end_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    project_end_unknown: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    team_size: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    team_externals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    initiatives: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    memorable_quote: Mapped[Optional[str]] = mapped_column(
        String(schema.SHORT_TEXT_MAX), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unrecognized_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    sales_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sales_deal_title: Mapped[Optional[str]] = mapped_column(
        String(schema.SHORT_TEXT_MAX), nullable=True
    )
    sales_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sales_handled_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sales_handled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    compass_card_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class TechCardSkill(Base):
    __tablename__ = "tech_card_skills"
    __table_args__ = (Index("ix_tech_card_skills_skill", "skill_id"),)

    card_id: Mapped[int] = mapped_column(
        ForeignKey("tech_cards.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )


class TechCardVendor(Base):
    __tablename__ = "tech_card_vendors"
    __table_args__ = (Index("ix_tech_card_vendors_vendor", "vendor_id"),)

    card_id: Mapped[int] = mapped_column(
        ForeignKey("tech_cards.id", ondelete="CASCADE"), primary_key=True
    )
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("tech_vendors.id", ondelete="CASCADE"), primary_key=True
    )


class SkillReviewItem(Base, TimestampMixin):
    """Nazwa technologii spoza słownika ``skills`` — do zmapowania albo dodania."""

    __tablename__ = "skill_review_queue"
    __table_args__ = (
        UniqueConstraint("name_key", name="uq_skill_review_queue_name"),
        CheckConstraint(schema.CK_REVIEW_STATUS, name="ck_skill_review_queue_status"),
        CheckConstraint(schema.CK_REVIEW_SKILL, name="ck_skill_review_queue_skill"),
        CheckConstraint(
            schema.CK_REVIEW_OCCURRENCES, name="ck_skill_review_queue_occurrences"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    name_key: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    skill_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    occurrences: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    reported_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RedeployQueueItem(Base, TimestampMixin):
    """Wpis „Do przepięcia” (konsultant = kontrakt → kandydat)."""

    __tablename__ = "redeploy_queue_items"
    __table_args__ = (
        CheckConstraint(
            schema.CK_REDEPLOY_REASON, name="ck_redeploy_queue_items_reason"
        ),
        CheckConstraint(
            schema.CK_REDEPLOY_STATUS, name="ck_redeploy_queue_items_status"
        ),
        CheckConstraint(
            schema.CK_REDEPLOY_SOURCE, name="ck_redeploy_queue_items_source"
        ),
        CheckConstraint(schema.CK_REDEPLOY_NOTE, name="ck_redeploy_queue_items_note"),
        Index(
            "uq_redeploy_queue_items_active",
            "contract_id",
            "reason",
            unique=True,
            postgresql_where=text(schema.REDEPLOY_ACTIVE_WHERE),
        ),
        Index("ix_redeploy_queue_items_status", "status", "due_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ClientFeedbackSession(Base):
    """Rozmowa z menedżerem u klienta o pracy konsultantów (D9–D11).

    Zapisuje ją opiekun albo Delivery Lead po telefonie czy spotkaniu —
    formularza wysyłanego do klienta nie ma (D10). Konsultant opinii nie widzi.
    """

    __tablename__ = "client_feedback_sessions"
    __table_args__ = (
        CheckConstraint(
            schema.CK_FEEDBACK_CHANNEL, name="ck_client_feedback_sessions_channel"
        ),
        CheckConstraint(
            schema.CK_FEEDBACK_EXTENSION, name="ck_client_feedback_sessions_extension"
        ),
        CheckConstraint(
            schema.CK_FEEDBACK_NOTE, name="ck_client_feedback_sessions_note"
        ),
        Index("ix_client_feedback_sessions_client", "client_id", "held_on"),
        Index("ix_client_feedback_sessions_contact", "contact_id", "held_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    held_on: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="phone", server_default="phone"
    )
    extension_outlook: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClientFeedbackScore(Base):
    """Oceny konsultanta (kontraktu) w jednej rozmowie z menedżerem, 1–5."""

    __tablename__ = "client_feedback_scores"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "contract_id",
            name="uq_client_feedback_scores_session_contract",
        ),
        CheckConstraint(
            schema.CK_SCORE_QUALITY, name="ck_client_feedback_scores_quality"
        ),
        CheckConstraint(
            schema.CK_SCORE_COMMUNICATION,
            name="ck_client_feedback_scores_communication",
        ),
        CheckConstraint(
            schema.CK_SCORE_AUTONOMY, name="ck_client_feedback_scores_autonomy"
        ),
        CheckConstraint(schema.CK_SCORE_ANY, name="ck_client_feedback_scores_any"),
        Index("ix_client_feedback_scores_contract", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("client_feedback_sessions.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    quality: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    communication: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    autonomy: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
