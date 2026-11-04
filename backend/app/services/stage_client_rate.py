"""Najnowsza stawka do klienta pary (kandydat, rekrutacja).

Stawkę wpisuje Delivery Lead przy wysyłce CV („CV wysłane”), na wierszu etapu.
Stawka do klienta jest punktem odniesienia dla zamówienia klienta (przychód);
do umowy idzie stawka kandydata. Czytają ją kolejka przeglądu DL, podpowiedzi
formularza umowy (tylko do wglądu) i porównanie ze stawką w zamówieniu
(``recruitment_rates``, D7 08.10.2026) — jedna reguła: najnowszy wiersz etapu
z wpisaną stawką.
"""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment_pipeline import CandidateStage

ClientRate = tuple[float, Optional[str], Optional[str]]


async def latest_client_rates(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], ClientRate]:
    """``{(kandydat, rekrutacja): (kwota, jednostka, waluta)}`` — jedno zapytanie."""

    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.client_rate_value,
            CandidateStage.client_rate_unit,
            CandidateStage.client_rate_currency,
        )
        .where(
            tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(wanted),
            CandidateStage.client_rate_value.is_not(None),
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )
    out: dict[tuple[int, int], ClientRate] = {}
    for cand, job, value, unit, currency in rows.all():
        unit_value = getattr(unit, "value", unit)
        out.setdefault((cand, job), (float(value), unit_value, currency))
    return out
