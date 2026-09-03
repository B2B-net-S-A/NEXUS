"""Jedna definicja „bieżącego etapu pary" dla całego repo.

Kanoniczny tiebreaker to ``(moved_at DESC, id DESC)`` — pokrywa go indeks
``ix_analytics_cs_cand_job_moved`` i używa go widok ``analytics_current_pipeline``.

Dwa moduły liczyły to inaczej: ``MAX(id) GROUP BY (candidate_id, job_id)``,
z komentarzem „id rośnie wraz z moved_at — wstawiany sekwencyjnie". **Dla
importu z Traffita to nieprawda**: `moved_at` przychodzi z zewnątrz i bywa
cofnięty, więc wiersz o najwyższym `id` nie musi być najnowszym zdarzeniem.
Skala rozjazdu na produkcji (2026-09-02, `/api/admin/pipeline-inventory`):
2 712 par, dla których „latest wg czasu" ≠ „latest wg id", plus 4 699 par
z remisem `moved_at` rozstrzyganym dowolnie.

Skutek był cichy: rozbicie etapów per rekrutacja i licznik „aktywnych
kandydatów" per TAC pokazywały inny etap niż tablica i niż KPI.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from sqlalchemy import Subquery, select

from app.models.recruitment_pipeline import CandidateStage


def latest_stage_ids(*, job_ids: Optional[Sequence[int]] = None) -> Subquery:
    """Podzapytanie z kolumną ``latest_id`` — po jednym wierszu na parę.

    Używaj jako ``CandidateStage.id.in_(select(sq.c.latest_id))``. `DISTINCT ON`
    wymaga, by `ORDER BY` zaczynał się od wyrażeń rozróżniających — stąd
    kolejność kolumn poniżej.
    """

    stmt = (
        select(CandidateStage.id.label("latest_id"))
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
    )
    if job_ids is not None:
        stmt = stmt.where(CandidateStage.job_id.in_(job_ids))
    return stmt.subquery()


__all__ = ["latest_stage_ids"]
