"""Wykluczone placementy — pary (kandydat, rekrutacja), których „Zatrudniony"
nie liczy się jako placement w ŻADNEJ statystyce (0343, decyzja 22.09.2026).

Powód istnienia: 24–25.09.2025 jedno konto ustawiło 45 parom etap
„Zatrudniony" w dwa dni (wiersze z importu Traffita, 35 z nich nigdy nie miało
„CV wysłane"). To dawało fałszywy szczyt placementów we wrześniu 2025
w Insights, na Radzie, w KPI i w wyścigach.

Wiersz NIE kasuje historii etapów — ``candidate_stages`` zostaje nietknięte.
Wykluczenie działa w dwóch miejscach czytania:

* widok ``analytics_first_milestones`` pomija wiersze ``hired`` wykluczonych
  par (rodzina atrybucji B — Insights, Rada, Hall of Fame, kampanie);
* ``VERIFIER_ANCHORED_CTE`` robi to samo w gałęzi czytającej
  ``candidate_stages`` wprost (rodzina A — KPI, wyścigi płacące nagrody).

Reguła wykrywania i jedyne źródło SQL-a: ``app/services/placement_exclusions.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlacementExclusion(Base):
    __tablename__ = "placement_exclusions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "job_id", name="uq_placement_exclusions_candidate_job"
        ),
        CheckConstraint(
            "reason IN ('admin_bulk_no_cv', 'admin_bulk_2025_09_series')",
            name="ck_placement_exclusions_reason",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # CASCADE po kandydacie: twarde usunięcie osoby (art. 17 RODO) zabiera też
    # ślad wykluczenia — bez osoby nie ma czego wykluczać.
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Wiersz etapu, który regułę uruchomił (pierwszy „Zatrudniony" pary).
    # Informacyjnie — wykluczenie działa po PARZE, nie po wierszu.
    candidate_stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
