"""Podpowiedzi formularza umowy B2B z rekrutacji (04.10.2026).

Umowę generuje rekruter prowadzący proces — w panelu osoby albo w Generatorze.
Oba wejścia czytają TĘ funkcję, więc pokazują te same liczby z tym samym
źródłem. Nic tu nie zapisuje; formularz wypełnia wyłącznie pola, których
człowiek jeszcze nie ruszył.

Kolejność stawki: karta rekomendacji tej rekrutacji (PLN/h, bez widełek) →
stawka podana w tej rekrutacji (okno „Zweryfikowany”) → „Stawka od” kandydata
(najniższa z 18 miesięcy, a przed przeliczeniem stawka profilu).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_process import RecruitmentProcess
from app.services import candidate_rate_from
from app.services.recommendation_card_rules import split_fields
from app.services.recommendation_cards import (
    attempt_started,
    card_rate_hourly,
    load_card,
)
from app.services.stage_client_rate import latest_client_rates

# Żywa umowa pary wygrywa z anulowaną albo zakończoną — tę pokazujemy jako
# „już istnieje”.
_LIVE_STATUSES = ("in_progress", "active")


def _iso(value: object) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


async def _latest_process(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[RecruitmentProcess]:
    return await db.scalar(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
    )


async def existing_agreement(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[B2BGeneratedContract]:
    """Umowa tej pary z rejestru: żywa przed resztą, potem najnowsza."""
    live_first = case(
        (B2BGeneratedContract.contract_status.in_(_LIVE_STATUSES), 0), else_=1
    )
    return await db.scalar(
        select(B2BGeneratedContract)
        .where(
            B2BGeneratedContract.candidate_id == candidate_id,
            B2BGeneratedContract.job_id == job_id,
            B2BGeneratedContract.source != "excel",
        )
        .order_by(
            live_first,
            B2BGeneratedContract.created_at.desc(),
            B2BGeneratedContract.id.desc(),
        )
        .limit(1)
    )


async def build_prefill(
    db: AsyncSession,
    *,
    candidate: Candidate,
    job: Job,
    show_client_rate: bool,
) -> dict[str, Any]:
    rate: Optional[dict[str, Any]] = None
    availability_text: Optional[str] = None

    card = await load_card(db, candidate_id=candidate.id, job_id=job.id)
    if card is not None:
        process = await _latest_process(db, candidate_id=candidate.id, job_id=job.id)
        current, _ = split_fields(
            card.fields_notes or {},
            card.fields_manual or {},
            attempt_started=attempt_started(process),
        )
        field = current.get("rate")
        value = card_rate_hourly(field)
        if value is not None:
            rate = {"value": value, "source": "card", "at": _iso(field.get("at"))}
        availability = current.get("availability")
        if isinstance(availability, dict):
            availability_text = str(availability.get("raw") or "").strip() or None

    if rate is None:
        this_job = await candidate_rate_from.this_job_rates(db, job.id, [candidate.id])
        hit = this_job.get(candidate.id)
        if hit and hit.get("amount") is not None:
            rate = {
                "value": float(hit["amount"]),
                "source": "this_job",
                "at": _iso(hit.get("at")),
            }

    if rate is None:
        summary = candidate_rate_from.rate_summary(candidate)
        if summary.get("rate_from_hourly") is not None:
            rate = {
                "value": float(summary["rate_from_hourly"]),
                "source": "rate_from",
                "at": _iso(summary.get("rate_from_at")),
            }

    client_rate: Optional[dict[str, Any]] = None
    if show_client_rate:
        found = (await latest_client_rates(db, [(candidate.id, job.id)])).get(
            (candidate.id, job.id)
        )
        if found is not None:
            value, unit, currency = found
            client_rate = {"value": value, "unit": unit, "currency": currency}

    existing = await existing_agreement(db, candidate_id=candidate.id, job_id=job.id)
    return {
        "candidate_id": candidate.id,
        "job_id": job.id,
        "rate": rate,
        "start_date": candidate.availability_date,
        "availability_text": availability_text,
        "client_rate": client_rate,
        "client_rate_redacted": not show_client_rate,
        "existing": (
            {
                "id": existing.id,
                "contract_number": existing.contract_number,
                "contract_status": existing.contract_status,
                "signature_status": existing.signature_status,
            }
            if existing is not None
            else None
        ),
    }
