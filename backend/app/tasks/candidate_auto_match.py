"""Worker autonomicznego dopasowania CV ↔ rekrutacje (17.09.2026).

Drenuje `candidate_match_outbox`. Stan żyje w bazie, więc restart kontenera przy
deployu niczego nie gubi: wiersz „processing” bez sygnału życia dłużej niż
`_RECLAIM_AFTER` wraca do kolejki. Zdarzenia starsze niż
`AUTO_MATCH_STALE_HOURS` są pomijane — CV sprzed dwóch dni nie powinno nagle
wylądować w pipeline'ie po długiej awarii.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_auto_match import CandidateMatchOutbox
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)

_BATCH = 10
_RECLAIM_AFTER = timedelta(minutes=15)


def _retry_after(attempts: int) -> timedelta:
    """Odstęp przed ponowieniem: 1, 2, 4… min — krótka awaria Qdranta albo
    Voyage nie zużywa wszystkich prób w kilka sekund."""
    return timedelta(minutes=2 ** max(0, attempts - 1))


async def _claim(db) -> list[int]:
    """Przejmij paczkę zdarzeń.

    Częściowy UNIQUE kolejki obejmuje `pending`, `processing` i `failed`, więc
    dla jednej rekrutacji (albo wersji CV) istnieje najwyżej jedno otwarte
    zdarzenie i przejęcie paczki nie może trafić w konflikt unikalności.
    Zdarzenie przejęte po raz ostatni i ubite restartem (deploy) zostałoby
    na zawsze w `processing` i blokowałoby kolejne zgłoszenia — domykamy je
    jako `dead`.
    """
    now = datetime.now(timezone.utc)
    max_attempts = max(1, settings.AUTO_MATCH_MAX_ATTEMPTS)
    await db.execute(
        update(CandidateMatchOutbox)
        .where(
            CandidateMatchOutbox.attempts >= max_attempts,
            or_(
                CandidateMatchOutbox.status == "failed",
                (CandidateMatchOutbox.status == "processing")
                & (CandidateMatchOutbox.heartbeat_at < now - _RECLAIM_AFTER),
            ),
        )
        .values(status="dead", processed_at=now)
    )
    candidates = (
        await db.execute(
            select(
                CandidateMatchOutbox.id,
                CandidateMatchOutbox.status,
                CandidateMatchOutbox.attempts,
                CandidateMatchOutbox.heartbeat_at,
            )
            .where(
                or_(
                    CandidateMatchOutbox.status.in_(("pending", "failed")),
                    (CandidateMatchOutbox.status == "processing")
                    & (CandidateMatchOutbox.heartbeat_at < now - _RECLAIM_AFTER),
                ),
                CandidateMatchOutbox.attempts < max_attempts,
            )
            .order_by(CandidateMatchOutbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(_BATCH * 3)
        )
    ).all()
    rows = [
        row.id
        for row in candidates
        if row.status != "failed"
        or row.heartbeat_at is None
        or row.heartbeat_at < now - _retry_after(row.attempts)
    ][:_BATCH]
    if rows:
        await db.execute(
            update(CandidateMatchOutbox)
            .where(CandidateMatchOutbox.id.in_(rows))
            .values(
                status="processing",
                heartbeat_at=now,
                attempts=CandidateMatchOutbox.attempts + 1,
            )
        )
    await db.commit()
    return rows


async def _run_my_people(db, event: CandidateMatchOutbox) -> dict:
    """Dzwonek „Moi ludzie" dla tej samej publikacji rekrutacji.

    Brak Qdranta (``AutoMatchUnavailable``) przechodzi dalej: zdarzenie się
    powtórzy, a obie strony są idempotentne (dziennik auto-matcha, UNIQUE
    dopasowań). Każdy inny błąd zostaje w savepoincie — nie może cofnąć
    auto-matcha, który właśnie się udał.
    """
    from app.models.job import Job
    from app.services.auto_match_service import AutoMatchUnavailable
    from app.services.my_people_matching import run_for_job

    job = await db.get(Job, event.job_id)
    if job is None:
        return {"skipped": "job_missing"}
    try:
        async with db.begin_nested():
            return await run_for_job(db, job)
    except AutoMatchUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("[my_people] job=%s failed: %s", event.job_id, exc)
        return {"error": type(exc).__name__}


async def _process(event_id: int) -> str:
    from app.services.auto_match_service import (
        AutoMatchUnavailable,
        run_candidate_event,
        run_job_event,
    )

    async with AsyncSessionLocal() as db:
        event = await db.get(CandidateMatchOutbox, event_id)
        if event is None:
            return "missing"
        stale = datetime.now(timezone.utc) - timedelta(
            hours=max(1, settings.AUTO_MATCH_STALE_HOURS)
        )
        if event.created_at < stale:
            event.status, event.processed_at = "skipped", datetime.now(timezone.utc)
            event.result = {"skipped": "stale"}
            await db.commit()
            return "skipped"
        trigger, attempts = event.trigger, event.attempts
        try:
            if event.candidate_id is not None:
                result = await run_candidate_event(db, event)
            else:
                result = await run_job_event(db, event)
                result = {**result, "my_people": await _run_my_people(db, event)}
        except Exception as exc:  # noqa: BLE001 — jedno zdarzenie nie zabija pętli
            await db.rollback()
            final = attempts >= max(1, settings.AUTO_MATCH_MAX_ATTEMPTS)
            await db.execute(
                update(CandidateMatchOutbox)
                .where(CandidateMatchOutbox.id == event_id)
                .values(
                    status="dead" if final else "failed",
                    last_error=f"{type(exc).__name__}: {exc}"[:500],
                    heartbeat_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            level = (
                logging.INFO
                if isinstance(exc, AutoMatchUnavailable)
                else logging.WARNING
            )
            logger.log(
                level,
                "[auto_match] event=%s trigger=%s failed (attempt %s): %s",
                event_id,
                trigger,
                attempts,
                exc,
            )
            return "failed"
        await db.execute(
            update(CandidateMatchOutbox)
            .where(CandidateMatchOutbox.id == event_id)
            .values(
                status="done",
                result=result,
                last_error=None,
                processed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        logger.info("[auto_match] event=%s trigger=%s %s", event_id, trigger, result)
        return "done"


async def drain_once() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        ids = await _claim(db)
    counts: dict[str, int] = {}
    for event_id in ids:
        outcome = await _process(event_id)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def candidate_auto_match_loop() -> None:
    if not settings.AUTO_MATCH_ENABLED:
        logger.info("[auto_match] disabled (AUTO_MATCH_ENABLED=false)")
        return
    interval = max(5, int(settings.AUTO_MATCH_INTERVAL_SECONDS))
    beat = loop_heartbeat.register(
        "candidate_auto_match", max_silence_seconds=interval + 1800
    )
    logger.info("[auto_match] worker started (interval=%ss)", interval)
    await asyncio.sleep(30)
    while True:
        beat.tick()
        delay = interval
        try:
            counts = await drain_once()
            if counts:
                logger.info("[auto_match] drained: %s", counts)
                delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla nie może umrzeć
            logger.warning("[auto_match] tick failed: %s", exc)
        await asyncio.sleep(delay)
