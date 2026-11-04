"""Wybór powodu zamknięcia rekrutacji — reguły wspólne dla zamknięcia i zmiany.

Decyzja Artura 21.10.2026: powód z grupy „Nie liczy się” wycina rekrutację
z hit ratio (Liga DL, cel DL), więc wymaga uzasadnienia, a
rekrutacja z zatrudnieniem od nas nie może do tej grupy trafić. „Inny” nie
jest już do wyboru — stare zamknięcia z nim czekają na przegląd.
Grupy: `metric_definitions.HIT_RATIO_*_CLOSE_REASONS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobCloseReason
from app.services.hit_ratio_scope import close_reason_group
from app.services.job_fill import placements_by_job


@dataclass(frozen=True)
class CloseChoice:
    reason: JobCloseReason
    notes: Optional[str]
    duplicate_of_job_id: Optional[int]


def _reject(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message})


async def validate_close_choice(
    db: AsyncSession,
    job: Job,
    *,
    reason: JobCloseReason,
    notes: Optional[str],
    duplicate_of_job_id: Optional[int],
) -> CloseChoice:
    """Sprawdza wybór i zwraca go oczyszczonego; 422 z `code` przy błędzie."""
    clean_notes = (notes or "").strip() or None
    if reason is JobCloseReason.other:
        raise _reject(
            "close_reason_other_retired",
            "Wybierz powód z listy — „Inny” nie jest już dostępny.",
        )
    if reason is JobCloseReason.no_activity:
        # Nadaje go tylko automat (`services/job_idle.py`) — człowiek wybiera
        # powód, który mówi, co się stało.
        raise _reject(
            "close_reason_system_only",
            "Ten powód nadaje tylko NEXUS — wybierz, jak skończyła się rekrutacja.",
        )
    if duplicate_of_job_id is not None and reason is not JobCloseReason.duplicate:
        raise _reject(
            "duplicate_of_requires_duplicate",
            "Rekrutację, która zostaje, wskazuje się tylko przy duplikacie.",
        )
    if close_reason_group(reason) == "neutral":
        if clean_notes is None:
            raise _reject(
                "close_notes_required",
                "Napisz uzasadnienie — ta rekrutacja nie wejdzie do hit ratio.",
            )
        if (await placements_by_job(db, [job.id])).get(job.id):
            raise _reject(
                "close_reason_has_hire",
                "W tej rekrutacji jest zatrudnienie od nas — zamknij ją jako "
                "„Obsadzone przez nas”.",
            )
    if duplicate_of_job_id is not None:
        if duplicate_of_job_id == job.id:
            raise _reject(
                "duplicate_of_self",
                "Wskaż inną rekrutację niż zamykana.",
            )
        exists = (
            await db.execute(select(Job.id).where(Job.id == duplicate_of_job_id))
        ).scalar_one_or_none()
        if exists is None:
            raise _reject(
                "duplicate_of_not_found",
                "Nie ma rekrutacji, która miałaby zostać.",
            )
    return CloseChoice(
        reason=reason, notes=clean_notes, duplicate_of_job_id=duplicate_of_job_id
    )
