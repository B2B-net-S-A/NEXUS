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
from typing import Any, Optional

from sqlalchemy import Subquery, and_, or_, select
from sqlalchemy.orm import aliased

from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


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


def current_hired_stage_exists(candidate_id: Any, *, client_id: Any = None):
    """``EXISTS``: kandydat stoi DZIŚ na ``hired`` w jakiejś rekrutacji.

    ``candidate_stages`` to historia dopisywana, więc „stoi dziś" znaczy:
    wiersz ``hired`` bez późniejszego ruchu w tej samej parze (kandydat,
    rekrutacja) — tym samym tiebreakerem ``(moved_at, id)`` co
    :func:`latest_stage_ids`. Korelacja idzie po przekazanym wyrażeniu
    (``Candidate.id`` w filtrze listy kandydatów, ``Contract.candidate_id``
    w definicji żywej umowy), a ``client_id`` zawęża do rekrutacji tego
    klienta. Jedna kopia reguły — wcześniej żyła w ``_at_client_predicate``.
    """
    later = aliased(CandidateStage)
    newer_move_exists = (
        select(1)
        .where(
            and_(
                later.candidate_id == CandidateStage.candidate_id,
                later.job_id == CandidateStage.job_id,
                or_(
                    later.moved_at > CandidateStage.moved_at,
                    and_(
                        later.moved_at == CandidateStage.moved_at,
                        later.id > CandidateStage.id,
                    ),
                ),
            )
        )
        .exists()
    )
    conditions = [
        CandidateStage.candidate_id == candidate_id,
        CandidateStage.stage == PipelineStage.hired,
        ~newer_move_exists,
    ]
    if client_id is not None:
        conditions += [Job.id == CandidateStage.job_id, Job.client_id == client_id]
    return select(1).where(and_(*conditions)).exists()


__all__ = ["current_hired_stage_exists", "latest_stage_ids"]
