"""Migawka `credited` całej firmy — jedno `VERIFIER_ANCHORED_CTE` na minutę.

27.10.2026 (lag NEXUSA): jedno wyliczenie `VERIFIER_ANCHORED_CTE` to na
produkcji 2,2 s bez JIT, a w 5 minutach było 16 wywołań i 53% czasu bazy —
panel „Moje KPI”, cele, panel zespołu, Liga i wyścigi, „Aktywność
rekrutacyjna” i kafel „Wyniki zespołu” liczyły je każdy osobno. Każdy
z nich i tak filtrował osobę, etap i okno dopiero na wyniku CTE, a sam
wynik (`credited`) jest mały: na kopii produkcji z 22.10.2026 14,4 tys.
wierszy, z czego 13,5 tys. to dni z DynaReportera.

Dlatego liczymy `credited` RAZ na minutę dla całej firmy (jeden wykonawca,
`cache_single_flight`), a konsument zamiast `VERIFIER_ANCHORED_CTE` dokleja
`CREDITED_FROM_SNAPSHOT_CTE` — CTE `credited` o tych samych kolumnach,
czytane z tablic parametrów (`unnest`). Reszta SQL-a konsumenta zostaje
słowo w słowo, więc liczby są te same co do jednej: te same wiersze, te same
filtry. Treść `VERIFIER_ANCHORED_CTE` (atrybucja, która płaci nagrody) jest
nietknięta.

Świeżość: migawka ma do 60 s, a konsumenci z własnym cache'em 60 s dokładają
swoje — ruch na Tablicy widać w liczniku najpóźniej po ok. 2 min (wcześniej
po 60 s). Nagród to nie rusza: wypłaca je zamrożenie okresu, które liczy
migawkę od nowa (`invalidate_credited_snapshot`).
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_invalidate, cache_set, cache_single_flight

# (stage, reached_at, candidate_id, job_id, credit_user) — kolumny `credited`.
# `candidate_id`/`job_id` = None: dzień z DynaReportera (bez pary).
CreditedRow = tuple[str, datetime, Optional[int], Optional[int], Optional[int]]

_SNAPSHOT_TTL_SECONDS = 60
_SNAPSHOT_KEY = "kpi:credited:v1"

# CTE `credited` z migawki — podmiana 1:1 za `VERIFIER_ANCHORED_CTE`.
# Konsument dokleja własny `SELECT … FROM credited` albo `, inne AS (…)`.
CREDITED_FROM_SNAPSHOT_CTE = """
    WITH credited AS (
        SELECT snapshot.stage,
               snapshot.reached_at,
               snapshot.candidate_id,
               snapshot.job_id,
               snapshot.credit_user
        FROM unnest(
            CAST(:credited_stage AS text[]),
            CAST(:credited_reached_at AS timestamptz[]),
            CAST(:credited_candidate_id AS integer[]),
            CAST(:credited_job_id AS integer[]),
            CAST(:credited_credit_user AS integer[])
        ) AS snapshot(stage, reached_at, candidate_id, job_id, credit_user)
    )
"""


@lru_cache(maxsize=1)
def _snapshot_sql():
    # Import lokalny: kpi_panel czyta migawkę, a CTE mieszka w kpi_panel.
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    return text(
        VERIFIER_ANCHORED_CTE
        + """
    SELECT stage, reached_at, candidate_id, job_id, credit_user
    FROM credited
    """
    )


async def credited_rows(db: AsyncSession) -> tuple[CreditedRow, ...]:
    """Wszystkie wiersze `credited` całej firmy, najwyżej sprzed minuty."""
    cached = await cache_get(_SNAPSHOT_KEY)
    if cached is not None:
        return cached
    async with cache_single_flight(_SNAPSHOT_KEY, db=db):
        cached = await cache_get(_SNAPSHOT_KEY)
        if cached is not None:
            return cached
        result = await db.execute(_snapshot_sql())
        rows: tuple[CreditedRow, ...] = tuple(
            (
                str(r[0]),
                r[1],
                None if r[2] is None else int(r[2]),
                None if r[3] is None else int(r[3]),
                None if r[4] is None else int(r[4]),
            )
            for r in result.all()
        )
        if _SNAPSHOT_TTL_SECONDS > 0:
            await cache_set(
                _SNAPSHOT_KEY,
                rows,
                ttl_seconds=_SNAPSHOT_TTL_SECONDS,
                jitter_seconds=10,
            )
        return rows


async def invalidate_credited_snapshot() -> None:
    """Następny odczyt liczy `credited` od nowa (zamrożenie okresu z nagrodami
    nie może stać na migawce sprzed poprawki zrobionej chwilę wcześniej)."""
    await cache_invalidate(_SNAPSHOT_KEY)


def credited_params(rows: Iterable[CreditedRow]) -> dict[str, list]:
    """Parametry `CREDITED_FROM_SNAPSHOT_CTE` dla podanych wierszy."""
    stages: list[str] = []
    reached: list[datetime] = []
    candidates: list[Optional[int]] = []
    jobs: list[Optional[int]] = []
    credit: list[Optional[int]] = []
    for stage, reached_at, candidate_id, job_id, credit_user in rows:
        stages.append(stage)
        reached.append(reached_at)
        candidates.append(candidate_id)
        jobs.append(job_id)
        credit.append(credit_user)
    return {
        "credited_stage": stages,
        "credited_reached_at": reached,
        "credited_candidate_id": candidates,
        "credited_job_id": jobs,
        "credited_credit_user": credit,
    }


async def credited_bind(
    db: AsyncSession,
    *,
    credit_user: Optional[int] = None,
    stage: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> dict[str, list]:
    """Parametry migawki, zawężone tak, jak SQL konsumenta i tak by zawęził.

    Zawężenie jest tylko optymalizacją (mniej wierszy w tablicach): konsument
    podaje wyłącznie filtry, które jego SQL stosuje do KAŻDEGO odczytu
    `credited`. `since`/`until` to półotwarte `[since, until)`.
    """
    rows: Iterable[CreditedRow] = await credited_rows(db)
    if credit_user is not None:
        rows = [row for row in rows if row[4] == credit_user]
    if stage is not None:
        rows = [row for row in rows if row[0] == stage]
    # Naiwną datę Postgres porównuje inaczej niż Python (i Python nie umie jej
    # porównać ze strefową) — wtedy zawężenie zostaje w samym SQL-u.
    if since is not None and since.tzinfo is not None:
        rows = [row for row in rows if row[1] is not None and row[1] >= since]
    if until is not None and until.tzinfo is not None:
        rows = [row for row in rows if row[1] is not None and row[1] < until]
    return credited_params(rows)


__all__ = [
    "CREDITED_FROM_SNAPSHOT_CTE",
    "CreditedRow",
    "credited_bind",
    "credited_params",
    "credited_rows",
    "invalidate_credited_snapshot",
]
