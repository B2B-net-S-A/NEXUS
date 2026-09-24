"""Follow-up z kandydatem, gdy klient milczy (migracja 0371, 24.09.2026).

Jedno zadanie na OSOBĘ, nie na proces: kandydat w pięciu procesach dostaje
jeden telefon od jednego rekrutera. Kto dzwoni i kiedy, liczy się przy
odczycie (``services/candidate_followups.py``). Ta tabela to dziennik
wyłącznie tego, czego nie da się wyliczyć z etapów, notatek i kalendarza.

``outcome``:

- ``connected`` — rozmawialiśmy, kandydat dalej czeka (zapisuje notatkę),
- ``changed`` — rozmawialiśmy, coś się zmieniło (notatka + dzwonek do
  właścicieli procesów; flagi per proces w ``details``),
- ``no_answer`` — nie odebrał; NIE jest kontaktem, przypomnienie wraca po
  2 dniach roboczych, bez limitu prób (decyzja Artura 24.09.2026),
- ``callback`` — prosi o kontakt w dniu ``callback_on``,
- ``claim`` — „Zrobię to ja”: przejęcie bieżącej rundy.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

FOLLOWUP_OUTCOMES = ("connected", "changed", "no_answer", "callback", "claim")
# Wyniki, które są rozmową z kandydatem — zerują zegar follow-upu.
CONTACT_OUTCOMES = frozenset({"connected", "changed"})


class CandidateFollowup(Base):
    __tablename__ = "candidate_followups"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('connected','changed','no_answer','callback','claim')",
            name="ck_candidate_followups_outcome",
        ),
        CheckConstraint(
            "(outcome = 'callback') = (callback_on IS NOT NULL)",
            name="ck_candidate_followups_callback",
        ),
        Index(
            "ix_candidate_followups_candidate_created",
            "candidate_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    callback_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
