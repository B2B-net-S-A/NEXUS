"""Edycja Akademii od strony recepcji (etap 5) — lista edycji i logistyka uczestnika.

Zestaw i protokół uczestnika wynikają z wydań sprzętu (``equipment_assignments.
academy_application_id``); tu tylko check lista edycji oraz hotel i bilet.
Tabele i CHECK-i: ``app/services/equipment_extras_schema.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import equipment_extras_schema as schema


class AcademySessionChecklistItem(Base, TimestampMixin):
    """Punkt check listy edycji (``item_key`` stały, etykieta ze wzoru)."""

    __tablename__ = "academy_session_checklist"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "item_key", name="uq_academy_session_checklist_item"
        ),
        CheckConstraint(
            schema.CK_CHECKLIST_LABEL, name="ck_academy_session_checklist_label"
        ),
        Index("ix_academy_session_checklist_session", "session_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("academy_sessions.id", ondelete="CASCADE"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(40), nullable=False)
    item_key: Mapped[str] = mapped_column(String(60), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AcademyParticipantLogistics(Base, TimestampMixin):
    """Hotel i bilet uczestnika edycji (rezygnacja = „do_anulowania”)."""

    __tablename__ = "academy_participant_logistics"
    __table_args__ = (
        CheckConstraint(
            schema.CK_LOGISTICS_HOTEL, name="ck_academy_participant_logistics_hotel"
        ),
        CheckConstraint(
            schema.CK_LOGISTICS_TICKET, name="ck_academy_participant_logistics_ticket"
        ),
    )

    application_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("academy_applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    hotel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="do_zrobienia", server_default="do_zrobienia"
    )
    ticket: Mapped[str] = mapped_column(
        String(16), nullable=False, default="do_zrobienia", server_default="do_zrobienia"
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
