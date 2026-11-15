"""Podpowiedź stawki stanowiska z historii klienta (Z4).

Reguły: ``docs/claude/klienci/zespol-dla-klienta.md`` („Z4 i odczyt maila”).
Źródło to stawki do klienta z wierszy etapu (``candidate_stages.client_rate_*``,
ta sama reguła „najnowszy wiersz pary z wpisaną stawką” co
``services/stage_client_rate.py``) z rekrutacji TEGO SAMEGO klienta i tej samej
kategorii kompetencji z ostatnich 365 dni, bez rekrutacji, dla której liczymy.
Tylko stawki godzinowe w złotych; para, której najnowsza stawka jest dzienna
albo w innej walucie, nie wchodzi (starszej stawki nie szukamy). Mniej niż
``MIN_PAIRS`` par = brak podpowiedzi, bez sięgania do innych klientów.

DL widzi ``{p25, median, p75, count}``. Klient dostaje najwyżej ``{min, max}``
(p25–p75) i tylko przy stanowisku bez żadnej stawki godzinowej na liście.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from typing import Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage

MIN_PAIRS = 3
WINDOW_DAYS = 365
HOURLY = "hourly"
# Brak waluty na wierszu etapu = złotówki (formularz „CV wysłane” domyślnie PLN).
_CURRENCIES = frozenset({"PLN"})


def _percentile(values: list[float], q: float) -> float:
    """Interpolacja liniowa między sąsiednimi wartościami (jak ``percentile_cont``)."""
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def summarize(values: Iterable[float]) -> Optional[dict[str, float]]:
    """``{p25, median, p75, count}`` w zł/h albo ``None`` przy mniej niż 3 parach."""
    ordered = sorted(values)
    if len(ordered) < MIN_PAIRS:
        return None
    return {
        "p25": round(_percentile(ordered, 0.25), 2),
        "median": round(_percentile(ordered, 0.5), 2),
        "p75": round(_percentile(ordered, 0.75), 2),
        "count": len(ordered),
    }


def public_estimate(hint: Optional[Mapping[str, float]]) -> Optional[dict[str, float]]:
    """Widełki dla klienta: tylko p25–p75, bez liczby par i mediany."""
    if hint is None:
        return None
    return {"min": hint["p25"], "max": hint["p75"]}


def _window_start() -> datetime:
    day = business_today() - timedelta(days=WINDOW_DAYS)
    return datetime.combine(day, time.min, ZoneInfo(settings.BUSINESS_TZ))


async def _latest_pair_rates(
    db: AsyncSession, client_id: int, category_ids: set[int]
) -> list[tuple[int, int, float]]:
    """``[(kategoria, rekrutacja, zł/h)]`` — najnowsza stawka każdej pary z okna."""
    rows = await db.execute(
        select(
            Job.competence_category_id,
            CandidateStage.job_id,
            CandidateStage.candidate_id,
            CandidateStage.client_rate_value,
            CandidateStage.client_rate_unit,
            CandidateStage.client_rate_currency,
        )
        .join(Job, Job.id == CandidateStage.job_id)
        .where(
            Job.client_id == client_id,
            Job.competence_category_id.in_(sorted(category_ids)),
            CandidateStage.client_rate_value.is_not(None),
            CandidateStage.moved_at >= _window_start(),
        )
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
    )
    out: list[tuple[int, int, float]] = []
    for category, job_id, _cand, value, unit, currency in rows.all():
        if getattr(unit, "value", unit) != HOURLY:
            continue
        if currency is not None and currency.upper() not in _CURRENCIES:
            continue
        out.append((category, job_id, float(value)))
    return out


async def rate_hints(
    db: AsyncSession, jobs: Iterable[Job]
) -> dict[int, Optional[dict[str, float]]]:
    """Rekrutacja → podpowiedź stawki (``None`` bez kategorii albo przy < 3 parach)."""
    jobs = list(jobs)
    out: dict[int, Optional[dict[str, float]]] = {job.id: None for job in jobs}
    by_client: dict[int, list[Job]] = {}
    for job in jobs:
        if job.client_id is not None and job.competence_category_id is not None:
            by_client.setdefault(job.client_id, []).append(job)
    for client_id, client_jobs in by_client.items():
        rates = await _latest_pair_rates(
            db, client_id, {job.competence_category_id for job in client_jobs}
        )
        for job in client_jobs:
            out[job.id] = summarize(
                value
                for category, job_id, value in rates
                if category == job.competence_category_id and job_id != job.id
            )
    return out
