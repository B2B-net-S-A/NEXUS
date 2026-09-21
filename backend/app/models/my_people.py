"""„Moi ludzie" — stała lista rekrutera.

Lista sama się buduje z historii pipeline'u (patrz ``services/my_people.py``):
właścicielem osoby jest PIERWSZY WERYFIKATOR pary (kandydat, rekrutacja), która
potem doszła do „CV Wysłane". Te dwie tabele trzymają wyłącznie to, czego
z historii wyliczyć się nie da:

- ``my_people_overrides`` — ręczne decyzje rekrutera: „Uśpij" (osoba znika
  z listy, np. znalazła pracę) i „Przypnij" (osoba spoza wyliczenia trafia na
  listę). Jeden wiersz na (użytkownik, kandydat) — nowsza decyzja nadpisuje.
- ``my_people_job_matches`` — dopasowania „nowa rekrutacja ↔ moi ludzie"
  policzone przy publikacji rekrutacji. Na nich stoi licznik awatara
  (``seen_at IS NULL``) i zakładka „Do tej rekrutacji" bez ponownego liczenia.

Obie tabele mają CASCADE po kandydacie: twarde usunięcie osoby (art. 17 RODO)
zabiera też jej ślady z list rekruterów.
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
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MY_PEOPLE_OVERRIDE_KINDS = ("snoozed", "pinned")
MY_PEOPLE_SNOOZE_REASONS = ("found_job", "not_interested", "no_contact", "other")


class MyPeopleOverride(Base):
    __tablename__ = "my_people_overrides"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "candidate_id", name="uq_my_people_overrides_user_candidate"
        ),
        CheckConstraint(
            "kind IN ('snoozed', 'pinned')", name="ck_my_people_overrides_kind"
        ),
        CheckConstraint(
            "kind <> 'snoozed' OR reason IS NOT NULL",
            name="ck_my_people_overrides_snooze_reason",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MyPeopleJobMatch(Base):
    __tablename__ = "my_people_job_matches"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "job_id",
            "candidate_id",
            name="uq_my_people_job_matches_user_job_candidate",
        ),
        Index("ix_my_people_job_matches_user_seen", "user_id", "seen_at"),
        Index("ix_my_people_job_matches_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
