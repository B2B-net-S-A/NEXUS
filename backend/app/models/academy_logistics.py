"""Edycja Akademii od strony recepcji (etap 5) — lista edycji i logistyka uczestnika.

Edycja = program i miesiąc startu (``academy_applications.cohort_month``).
Zestaw i protokół uczestnika wynikają z wydań sprzętu (``equipment_assignments.
academy_application_id``); tu tylko check lista edycji oraz hotel i bilet.
Tabele i CHECK-i: ``app/services/equipment_extras_schema.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import equipment_extras_schema as schema


class AcademyEditionChecklistItem(Base, TimestampMixin):
    """Punkt check listy edycji (program + miesiąc startu; ``item_key`` stały)."""

    __tablename__ = "academy_edition_checklist"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "cohort_month",
            "item_key",
            name="uq_academy_edition_checklist_item",
        ),
        CheckConstraint(
            schema.CK_CHECKLIST_LABEL, name="ck_academy_edition_checklist_label"
        ),
        CheckConstraint(
            schema.CK_CHECKLIST_COHORT, name="ck_academy_edition_checklist_cohort"
        ),
        Index(
            "ix_academy_edition_checklist_edition",
            "program_id",
            "cohort_month",
            "position",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("academy_programs.id", ondelete="CASCADE"), nullable=False
    )
    cohort_month: Mapped[date] = mapped_column(Date, nullable=False)
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
        String(16),
        nullable=False,
        default="do_zrobienia",
        server_default="do_zrobienia",
    )
    ticket: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="do_zrobienia",
        server_default="do_zrobienia",
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
