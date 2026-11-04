"""Propozycje kandydatów do rekrutacji (skrzynka „Propozycje", migracja 0333).

``job_proposals`` — kandydat zaproponowany do rekrutacji przez JEDNO źródło
(pełny przegląd bazy, nowe CV, podobne projekty, rekomendacje, targ).
UNIQUE ``(job_id, candidate_id, source)``: ta sama osoba z dwóch źródeł to dwa
wiersze, a odczyt składa je w jedną pozycję z listą źródeł.

``status``: ``added`` nigdy się nie cofa. ``dismissed`` („Pomiń") obowiązuje
CAŁY zespół i wszystkie źródła, dopóki osoba nie dostanie NOWEJ wersji CV
(``cv_revision`` inne niż ``dismissed_cv_revision``) — wtedy wraca jako
``proposed`` z flagą ``previously_dismissed`` w ``evidence``.

``expired`` (0422): propozycja nocnego przeglądu bazy (``full_base``), której
nowszy, kompletny przegląd tej rekrutacji już nie zaproponował. Wiersz zostaje,
status pary go pomija, a powrót osoby w kolejnym przeglądzie = ``proposed``.

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
    # 0374: przekazane przez praktykanta po rozmowie telefonicznej.
    "trainee",
    # 0405: dopasowanie z integracji (JJIT/RocketJobs) — nigdy karta na tablicy.
    "job_board",
)
# 0422: ``expired`` = nowszy, kompletny nocny przegląd już tej osoby nie
# zaproponował albo rekrutację zamknięto (audyt 06.10.2026, R6). Status pary go
# pomija; powrót w kolejnym przeglądzie = ``proposed``.
JOB_PROPOSAL_STATUSES = ("proposed", "dismissed", "added", "expired")


class JobProposal(Base):
    __tablename__ = "job_proposals"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "candidate_id", "source", name="uq_job_proposals_pair_source"
        ),
        CheckConstraint(
            "source IN ('full_base', 'new_cv', 'similar_projects', "
            "'recommendation', 'marketplace', 'reassign', 'trainee', 'job_board')",
            name="ck_job_proposals_source",
        ),
        CheckConstraint(
            "dismiss_reason IS NULL OR dismiss_reason IN ('missing_critical', "
            "'too_expensive', 'location_office', 'too_junior', 'outdated_cv', 'other')",
            name="ck_job_proposals_dismiss_reason",
        ),
        CheckConstraint(
            "status IN ('proposed', 'dismissed', 'added', 'expired')",
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
    # 0405: powód „Pomiń” (wymagany od 30.09.2026) i opis przy „inny”.
    dismiss_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    dismiss_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
