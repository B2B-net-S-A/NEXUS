"""Back office na sprawach — modele kart, historii i zespołów (0642).

CHECK-i i indeksy muszą być identyczne z ``app/services/back_office_schema.py``
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import back_office_schema as schema


class BoCard(Base):
    __tablename__ = "bo_cards"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_bo_cards_source_key"),
        CheckConstraint(schema.CK_CARD_TEAM, name="ck_bo_cards_team"),
        CheckConstraint(schema.CK_CARD_LANE, name="ck_bo_cards_lane"),
        CheckConstraint(schema.CK_CARD_STATE, name="ck_bo_cards_state"),
        CheckConstraint(schema.CK_CARD_SOURCE_KIND, name="ck_bo_cards_source_kind"),
        CheckConstraint(schema.CK_CARD_TITLE, name="ck_bo_cards_title"),
        CheckConstraint(schema.CK_CARD_CLOSED, name="ck_bo_cards_closed"),
        CheckConstraint(schema.CK_CARD_META, name="ck_bo_cards_meta"),
        Index(
            "ix_bo_cards_board",
            "team",
            "lane",
            "state",
            postgresql_where=text("state <> 'done'"),
        ),
        Index("ix_bo_cards_kind", "source_kind", "state"),
        Index("ix_bo_cards_assignee", "assignee_user_id", "state"),
        Index("ix_bo_cards_parent", "parent_card_id"),
        Index("ix_bo_cards_case", "case_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team: Mapped[str] = mapped_column(String(12), nullable=False)
    lane: Mapped[str] = mapped_column(String(12), nullable=False)
    lane_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    source_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    source_key: Mapped[str] = mapped_column(
        String(schema.SOURCE_KEY_MAX), nullable=False
    )
    parent_card_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bo_cards.id", ondelete="CASCADE"), nullable=True
    )
    step_order: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    case_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("admin_cases.id", ondelete="SET NULL"), nullable=True
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    subject_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(schema.TITLE_MAX), nullable=False)
    person: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    client_label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    state: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="new", default="new"
    )
    waiting_on: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    substituting: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    href: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    taken_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    escalated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    priority_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    priority_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BoCardEvent(Base):
    __tablename__ = "bo_card_events"
    __table_args__ = (
        CheckConstraint(schema.CK_EVENT_DETAILS, name="ck_bo_card_events_details"),
        Index("ix_bo_card_events_card", "card_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bo_cards.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoTeamMember(Base):
    __tablename__ = "bo_team_members"
    __table_args__ = (
        CheckConstraint(schema.CK_MEMBER_TEAM, name="ck_bo_team_members_team"),
        Index("ix_bo_team_members_user", "user_id"),
    )

    team: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
