"""Termin i liczba osób z historii klienta na /jobs/new (decyzja Artura 23.11.2026).

Wariant 1 „Porządki” z makiet szybszego zakładania rekrutacji: pola, w których
klient prawie zawsze odpowiada tak samo, wstawia formularz zamiast pytać
Delivery Leada. Pomiar na kopii z 23.11: Nordea 47 z 47 rekrutacji bez terminu,
80% wszystkich rekrutacji to jedna osoba.

Liczymy tylko rekrutacje założone w NEXUSIE (archiwum Traffita nie ma terminu
ani decyzji „Klient nie podał”). Podpowiedź pada od ``MIN_JOBS`` rekrutacji
i ``MIN_SHARE`` zgodnych; formularz pokazuje ją z podpisem i do zmiany.
To dodatek do odczytu maila: awaria bazy = brak podpowiedzi, nie błąd odczytu.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job

logger = logging.getLogger(__name__)

LOOKBACK_JOBS = 50
MIN_JOBS = 5
MIN_SHARE = 0.8


def defaults_from_history(
    history: Iterable[tuple[bool, Optional[int]]],
) -> dict[str, Any]:
    """``(deadline_not_provided, headcount)`` najnowszych rekrutacji → podpowiedź."""
    rows = list(history)
    jobs = len(rows)
    no_deadline = sum(1 for not_provided, _ in rows if not_provided)
    counts = Counter(headcount for _, headcount in rows if headcount)
    headcount, headcount_jobs = counts.most_common(1)[0] if counts else (None, 0)
    enough = jobs >= MIN_JOBS
    return {
        "jobs": jobs,
        "deadline_not_provided": no_deadline,
        "suggest_deadline_not_provided": enough and no_deadline >= MIN_SHARE * jobs,
        "headcount": headcount,
        "headcount_jobs": headcount_jobs,
        "suggest_headcount": enough and headcount_jobs >= MIN_SHARE * jobs,
    }


async def client_defaults(db: AsyncSession, client_id: int) -> Optional[dict[str, Any]]:
    """Podpowiedź dla klienta albo ``None``, gdy zapytanie się nie udało."""
    try:
        rows = (
            await db.execute(
                select(Job.deadline_not_provided, Job.headcount)
                .where(
                    Job.client_id == client_id,
                    Job.external_source.is_distinct_from("traffit"),
                )
                .order_by(Job.created_at.desc())
                .limit(LOOKBACK_JOBS)
            )
        ).all()
    except Exception as exc:  # noqa: BLE001 — podpowiedź nie jest warunkiem odczytu
        logger.warning(
            "job_intake_client_defaults: query failed: %s", type(exc).__name__
        )
        return None
    return defaults_from_history((bool(r[0]), r[1]) for r in rows)
