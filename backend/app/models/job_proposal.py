"""Propozycje kandydatów do rekrutacji (skrzynka „Propozycje", migracja 0330).

Dwie tabele:

- ``job_proposals`` — kandydat zaproponowany do rekrutacji przez JEDNO źródło
  (pełny przegląd bazy, nowe CV, podobne projekty, rekomendacje, targ).
  UNIQUE ``(job_id, candidate_id, source)``: ta sama osoba z dwóch źródeł to dwa
  wiersze, a odczyt składa je w jedną pozycję z listą źródeł. ``status`` jest
  zapadką: ``dismissed`` nie wraca na ``proposed`` przy kolejnym przeglądzie,
  ``added`` nigdy się nie cofa.
- ``job_proposal_seen`` — znacznik „widziałem do tej chwili" per (osoba,
  rekrutacja). Licznik „nowe" to propozycje z ``first_seen_at`` późniejszym niż
  ten znacznik.

``evidence`` niesie WYŁĄCZNIE nazwy/identyfikatory wymagań i liczby — nigdy
wolny tekst z CV (wiersz przeżywa do kasowania kandydata, a CASCADE jest jedynym
mechanizmem RODO tej tabeli). Pilnuje tego ``services/job_proposals``.

``run_id`` celowo BEZ klucza obcego: przeglądy kasuje retencja
(``candidate_search_retention``), a propozycja ma ją przeżyć.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JOB_PROPOSAL_SOURCES = (
    "full_base",
    "new_cv",
    "similar_projects",
    "recommendation",
    "marketplace",
)
JOB_PROPOSAL_STATUSES = ("proposed", "dismissed", "added")


class JobProposal(Base):
    __tablename__ = "job_proposals"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "candidate_id", "source", name="uq_job_proposals_pair_source"
        ),
        CheckConstraint(
            "source IN ('full_base', 'new_cv', 'similar_projects', "
            "'recommendation', 'marketplace')",
            name="ck_job_proposals_source",
        ),
        CheckConstraint(
            "status IN ('proposed', 'dismissed', 'added')",
            name="ck_job_proposals_status",
        ),
        Index("ix_job_proposals_job_status_seen", "job_id", "status", "first_seen_at"),
        Index("ix_job_proposals_candidate_id", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="proposed", server_default="proposed"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dismissed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class JobProposalSeen(Base):
    __tablename__ = "job_proposal_seen"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
