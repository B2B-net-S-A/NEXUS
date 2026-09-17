"""Zapis zdarzeń do kolejki auto-dopasowania (`candidate_match_outbox`).

Wpis idzie w transakcji wołającego: zdarzenie istnieje dokładnie wtedy, gdy
utrwalił się profil z CV albo publikacja rekrutacji. Podwójne zgłoszenie tej
samej wersji profilu zwija częściowy UNIQUE na otwartych wpisach
(`ON CONFLICT DO NOTHING`), więc wołający nie musi niczego sprawdzać.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


def auto_match_enabled() -> bool:
    return bool(getattr(settings, "AUTO_MATCH_ENABLED", False))


def candidate_revision(candidate) -> str:
    """Wersja profilu do dedupu: hash pliku CV albo chwila odczytu.

    Ta sama funkcja dla zdarzeń od strony kandydata i rekrutacji — dwie różne
    wersje tego samego profilu pozwalałyby dodać ponownie kogoś, kogo rekruter
    usunął z procesu.
    """
    extracted = candidate.cv_extracted_data
    highlights = extracted.get("cv_highlights") if isinstance(extracted, dict) else None
    source_hash = (
        highlights.get("source_hash") if isinstance(highlights, dict) else None
    )
    if source_hash:
        return str(source_hash)[:64]
    parsed_at = candidate.cv_parsed_at
    return f"parsed:{parsed_at.isoformat()}"[:64] if parsed_at else "unparsed"


async def enqueue_candidate(
    db: AsyncSession,
    *,
    candidate_id: int,
    trigger: str,
    profile_revision: str,
) -> None:
    """Zgłoś kandydata do dopasowania z otwartymi rekrutacjami."""
    if not auto_match_enabled():
        return
    # SAVEPOINT: konflikt na częściowym UNIQUE nie może zatruć sesji, w której
    # właśnie zapisał się profil z CV.
    async with db.begin_nested():
        await db.execute(
            text(
                "INSERT INTO candidate_match_outbox "
                "(candidate_id, trigger, profile_revision, status) "
                "VALUES (:candidate_id, :trigger, :revision, 'pending') "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "candidate_id": candidate_id,
                "trigger": trigger[:16],
                "revision": profile_revision[:64],
            },
        )


async def enqueue_job(db: AsyncSession, *, job_id: int, trigger: str) -> None:
    """Zgłoś rekrutację do dopasowania ze świeżymi profilami z CV."""
    if not auto_match_enabled():
        return
    async with db.begin_nested():
        await db.execute(
            text(
                "INSERT INTO candidate_match_outbox (job_id, trigger, status) "
                "VALUES (:job_id, :trigger, 'pending') "
                "ON CONFLICT DO NOTHING"
            ),
            {"job_id": job_id, "trigger": trigger[:16]},
        )


async def enqueue_job_safe(job_id: int, trigger: str = "job_publish") -> None:
    """Wariant dla `BackgroundTasks`: własna sesja, commit, nigdy nie rzuca."""
    if not auto_match_enabled():
        return
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await enqueue_job(db, job_id=job_id, trigger=trigger)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[auto_match] enqueue job=%s failed: %s", job_id, exc)
