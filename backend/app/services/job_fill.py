"""Ilu kandydatów obsadzono na rekrutacji — jedna definicja.

Repo liczyło to na trzy sposoby, dające różne liczby:

* `insights_delivery_leads` — z widoku `analytics_first_milestones`
  (pierwsze `hired` per para; kanonicznie);
* `reports.py` — `count(candidate_stages.id)` po WSZYSTKICH wierszach `hired`,
  więc kandydat z powtórzonym etapem liczył się dwa razy;
* `reports.py` (fill rate) — suma `headcount` zamkniętych rekrutacji.

Kanoniczna jest pierwsza: placement to PIERWSZE wejście pary (kandydat,
rekrutacja) na „Zatrudniony" (`FIRST_HIRED_PER_CANDIDATE_JOB`). Ta sama
definicja stoi za `/insights` i banerem kampanii.

Moduł NIE zmienia stanu rekrutacji ani kandydata. Zamknięcie oferty zostaje
świadomą decyzją człowieka (`POST /api/jobs/{job_id}/close`) — 99,6% ruchu
w pipelinie pochodzi z importu, więc automat działałby retroaktywnie na
tysiącach rekordów, o które nikt nie prosił.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PLACEMENTS_SQL = text(
    """
    SELECT fm.job_id, count(*) AS cnt
    FROM analytics_first_milestones fm
    WHERE fm.stage = 'hired'
      AND fm.job_id = ANY(:job_ids)
    GROUP BY fm.job_id
    """
)


async def placements_by_job(db: AsyncSession, job_ids: Sequence[int]) -> dict[int, int]:
    """Liczba placementów per rekrutacja wg definicji kanonicznej."""

    if not job_ids:
        return {}
    rows = await db.execute(_PLACEMENTS_SQL, {"job_ids": list(job_ids)})
    return {int(job_id): int(cnt) for job_id, cnt in rows.all()}


def open_vacancies(headcount: int | None, placements: int) -> int:
    """Ile wakatów zostało. Nigdy ujemnie — nadmiar obsady to nie „minus etat"."""

    return max(int(headcount or 1) - placements, 0)


def is_fully_staffed(headcount: int | None, placements: int) -> bool:
    return open_vacancies(headcount, placements) == 0


__all__ = ["is_fully_staffed", "open_vacancies", "placements_by_job"]
