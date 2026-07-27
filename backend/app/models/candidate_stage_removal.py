"""Archiwum historii rekrutacji usuniętej korekcyjnie.

``DELETE /api/candidates/{id}/recruitments/{job_id}`` jest operacją korekcyjną
("dodano nie tego kandydata / nie na tę ofertę") i fizycznie kasuje WSZYSTKIE
``CandidateStage`` pary, a kaskadą snapshoty CV, share-tokeny i zaplanowane
maile odrzucenia. Po takiej korekcie nie dało się już odtworzyć, przez jakie
etapy kandydat przeszedł ani kto go przesuwał — zostawało zbiorcze
``Activity`` bez treści decyzji.

Ta tabela to zapis pełnych wierszy PRZED skasowaniem. Korekta nadal usuwa
kandydata z pipeline'u (to jest jej cel i UX się nie zmienia), ale dowód
przebiegu procesu zostaje.

Dlaczego archiwum, a nie flaga ``voided`` na ``candidate_stages``: flagę
trzeba by filtrować w 132 zapytaniach w 64 plikach, a pierwsze pominięte
pokazywałoby skasowaną rekrutację jako żywą. Archiwum dotyka jednego miejsca
zapisu i zera ścieżek odczytu.

Append-only z założenia: brak API, które by tu kasowało lub aktualizowało.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class CandidateStageRemoval(Base):
    __tablename__ = "candidate_stage_removals"
    __table_args__ = (
        Index("ix_candidate_stage_removals_pair", "candidate_id", "job_id"),
        Index("ix_candidate_stage_removals_removed_at", "removed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Bez FK do candidates/jobs: archiwum ma przeżyć skasowanie kandydata albo
    # oferty. Kaskada z FK zabrałaby dokładnie ten dowód, dla którego ta tabela
    # istnieje.
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False)

    removed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Ostatni etap przed usunięciem — pozwala odpowiedzieć "jak daleko doszedł"
    # bez rozpakowywania JSON-a.
    last_stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    stage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Pełne wiersze ``candidate_stages`` w chwili usunięcia (lista obiektów).
    stages_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return (
            f"<CandidateStageRemoval candidate={self.candidate_id} "
            f"job={self.job_id} stages={self.stage_count}>"
        )
