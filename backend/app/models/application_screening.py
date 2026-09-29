"""Ocena zgłoszenia z linku rekrutacji przez AI (migracja 0404, 29.09.2026).

Zgłoszenie z ``/r/<slug>`` (link ``kind='job'``) nie otwiera procesu
w requeście — zapisuje się wiersz ``pending``, a pętla
``application_screening`` po odczycie CV decyduje: osoba wchodzi do „Nowi”
(``added``) albo zostaje w bazie i na liście „Odrzuceni przez AI”
(``screened_out``). Reguła w ``services/application_screening.py``.

Kandydat i rekrutacja kasują wiersz (CASCADE) — ``cv_text`` i cytaty
w ``reasons`` to treść CV. ``cv_text`` jest czyszczone przy decyzji.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApplicationScreening(Base):
    __tablename__ = "application_screenings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # NULL dla nowego e-maila — ta gałąź nie zapisuje `application_submissions`.
    submission_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("application_submissions.id", ondelete="CASCADE"),
        nullable=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    verdict: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    must_found: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    must_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # [{"text": zdanie PL, "quote": cytat z CV}] — cytat sprawdzony kodem.
    reasons: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # Klasa wyjątku albo kod powodu — nigdy treść odpowiedzi modelu.
    error: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Dzierżawa pętli: wiersz wzięty do oceny nie wraca do innego przebiegu
    # przed tym terminem (restart w trakcie oceny = ponowienie po terminie).
    claimed_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Tekst przesłanego CV (odczyt przy zgłoszeniu) — czyszczony przy decyzji.
    cv_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # {link_owner_id, origin_assignment_id, priority_compliant_at_create, via,
    #  first_name, last_name, utm_source} — bez sekretu linku.
    context: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    digested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    overridden_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    overridden_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
