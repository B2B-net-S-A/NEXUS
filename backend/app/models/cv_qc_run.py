"""Przebiegi QC CV (migracja 0361, Rekrutacja v5).

Automatyczna kontrola jakości CV firmowego zastępuje ręczny przegląd DZ
i jest twardą bramką przed „CV wysłane”/Cpro. Każdy przebieg pary
(kandydat, rekrutacja) zostaje zapisany: tablica pokazuje stan najnowszego
(`cv_qc.pair_statuses`), a obejście przez Delivery Leada/admina to wiersz
z `override_reason` — ślad, kto i dlaczego przepuścił CV mimo braków.

Klucze obce do kandydata i rekrutacji kasują przebiegi razem z nimi
(`result` niesie fragmenty CV). Wiersz etapu i autorzy mogą zniknąć bez
utraty historii (SET NULL).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CvQcRun(Base):
    __tablename__ = "cv_qc_runs"
    __table_args__ = (
        Index(
            "ix_cv_qc_runs_pair_created",
            "candidate_id",
            "job_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_stage_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("candidate_stages.id", ondelete="SET NULL"), nullable=True
    )
    cv_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocking_failed: Mapped[int] = mapped_column(Integer, nullable=False)
    warnings_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    override_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
