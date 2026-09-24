"""Propozycje kandydatów do rekrutacji (skrzynka „Propozycje", migracja 0333).

``job_proposals`` — kandydat zaproponowany do rekrutacji przez JEDNO źródło
(pełny przegląd bazy, nowe CV, podobne projekty, rekomendacje, targ).
UNIQUE ``(job_id, candidate_id, source)``: ta sama osoba z dwóch źródeł to dwa
wiersze, a odczyt składa je w jedną pozycję z listą źródeł.

``status``: ``added`` nigdy się nie cofa. ``dismissed`` („Pomiń") obowiązuje
CAŁY zespół i wszystkie źródła, dopóki osoba nie dostanie NOWEJ wersji CV
(``cv_revision`` inne niż ``dismissed_cv_revision``) — wtedy wraca jako
``proposed`` z flagą ``previously_dismissed`` w ``evidence``.

Licznik na liście rekrutacji jest zespołowy (propozycja liczy się, dopóki ktoś
jej nie obsłuży: „Dodaj" albo „Pomiń") — nie ma znacznika „widziane" per osoba.

``evidence`` niesie WYŁĄCZNIE nazwy/identyfikatory wymagań i liczby — nigdy
wolny tekst z CV. ``run_id`` celowo BEZ klucza obcego: przeglądy kasuje
retencja, a propozycja ma ją przeżyć.
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
    # 0341: przepięcie — osoba wysłana do klienta w podobnej rekrutacji.
    "reassign",
    # 0371: przekazane przez praktykanta po rozmowie telefonicznej.
    "trainee",
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
            "'recommendation', 'marketplace', 'reassign', 'trainee')",
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
    # `none_as_null`: brak dowodów to SQL NULL, nie JSON-owe `null` (to drugie
    # psułoby `evidence || {…}` przy powrocie pominiętej osoby).
    evidence: Mapped[Optional[dict]] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
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
    # Wersja CV/profilu, dla której policzono propozycję — ta sama wartość co
    # `candidate_auto_match_log.profile_revision` (`candidate_revision`).
    cv_revision: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Wersja CV w chwili pominięcia: INNA wersja proponuje osobę ponownie.
    dismissed_cv_revision: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
