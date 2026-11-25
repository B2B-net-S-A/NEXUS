"""Pętla raportów kompetencji w 24 godziny (N4, decyzje Artura 25.11.2026).

Co 5 minut, u lidera (jak każda pętla z ``_start_background_tasks``),
wyłącznik ``COMPETENCE_REPORT_SENDER_ENABLED``. Jeden przebieg:

1. ``waiting_cv`` z odczytanym CV (``cv_parsed_at``) → snapshot, ``ready``.
   Po 20 h bez odczytu → snapshot ``limited`` (termin 24 h zostaje).
2. ``waiting_cv`` bez odczytu po 30 minutach → jeden ponowny odczyt CV
   (``attempts`` = 1), bo odczyt w BackgroundTask ginie przy restarcie.
3. ``ready``, bez „Wstrzymaj” i bez wypisu, ``send_due_at`` minął →
   ``send_report``. Tylko gdy skrzynka kandydatów jest gotowa i admin włączył
   rodzaj ``competence_report`` w Ustawieniach → Powiadomienia.

Wiersze bierzemy po jednym ``FOR UPDATE SKIP LOCKED``; ``send_report``
commituje rezerwację przed wysyłką. Wiersz utworzony „po” ``now`` czeka
na następny przebieg. Logi bez adresów i imion.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.competence_report import CompetenceReport
from app.services import loop_heartbeat
from app.services.competence_report_email import KIND
from app.services.competence_report_engine import build_snapshot, fallback_snapshot
from app.services.competence_report_send import (
    MAX_ATTEMPTS,
    ReportNotSendable,
    send_report,
)

logger = logging.getLogger(__name__)

LOOP_SLEEP_SECONDS = 300
#: Najwyżej tyle wierszy każdego rodzaju w jednym przebiegu.
BATCH = 25
RETRIGGER_AFTER = timedelta(minutes=30)
LIMITED_AFTER = timedelta(hours=20)


def _retrigger_parse(candidate_id: int) -> None:
    """Odczyt CV poza przebiegiem (wołanie modelu trwa minuty)."""
    from app.api import public_share
    from app.core.tasks import spawn

    # Przez moduł: testy podmieniają `_invite_post_apply_task`.
    spawn(
        public_share._invite_post_apply_task(candidate_id),
        "competence_report_cv_reparse",
    )


async def _row_failed(
    db: AsyncSession, report_id: int, error: str, *, from_status: str
) -> None:
    """Wyjątek przy jednym raporcie: próba + 1, po ``MAX_ATTEMPTS`` ``failed``.

    Najpierw rollback (zdejmuje blokadę i zepsutą transakcję), potem zapis
    bez obiektu ORM — po rollbacku jest wygaszony. ``last_error`` bez danych osobowych.
    """
    await db.rollback()
    attempts = CompetenceReport.attempts + 1
    await db.execute(
        update(CompetenceReport)
        .where(
            CompetenceReport.id == report_id,
            CompetenceReport.status == from_status,
        )
        .values(
            attempts=attempts,
            last_error=error[:120],
            status=case(
                (attempts >= MAX_ATTEMPTS, "failed"), else_=CompetenceReport.status
            ),
        )
    )
    await db.commit()


async def _build_ready(db: AsyncSession, now: datetime, stats: dict) -> None:
    seen: set[int] = set()
    for _ in range(BATCH):
        row = await db.scalar(
            select(CompetenceReport)
            .join(Candidate, Candidate.id == CompetenceReport.candidate_id)
            .where(
                CompetenceReport.status == "waiting_cv",
                CompetenceReport.opted_out_at.is_(None),
                CompetenceReport.created_at <= now,
                CompetenceReport.id.not_in(seen) if seen else true(),
                or_(
                    Candidate.cv_parsed_at.is_not(None),
                    CompetenceReport.created_at <= now - LIMITED_AFTER,
                ),
            )
            .order_by(CompetenceReport.send_due_at, CompetenceReport.id)
            .limit(1)
            .with_for_update(of=CompetenceReport, skip_locked=True)
        )
        if row is None:
            return
        report_id = row.id
        seen.add(report_id)
        try:
            variant = await _build_one(db, row, now)
        except Exception as exc:  # noqa: BLE001 — jeden raport nie zatrzymuje pętli
            logger.warning(
                "[competence-report] build aborted report=%s: %s",
                report_id,
                type(exc).__name__,
            )
            # Nawet najkrótszy raport się nie składa (np. warunki spoza schematu):
            # ponowienie nic nie da, raport trafia do kolejki jako ``failed``.
            await db.rollback()
            await db.execute(
                update(CompetenceReport)
                .where(
                    CompetenceReport.id == report_id,
                    CompetenceReport.status == "waiting_cv",
                )
                .values(
                    status="failed",
                    last_error=f"build_error:{type(exc).__name__}"[:120],
                )
            )
            await db.commit()
            stats["failed"] += 1
            continue
        stats["limited" if variant == "limited" else "built"] += 1


async def _build_one(db: AsyncSession, row: CompetenceReport, now: datetime) -> str:
    parsed = await db.scalar(
        select(Candidate.cv_parsed_at).where(Candidate.id == row.candidate_id)
    )
    limited = parsed is None
    try:
        # Punkt zapisu: błąd zapytania w silniku nie zdejmuje blokady wiersza.
        async with db.begin_nested():
            snapshot = await build_snapshot(db, row, limited=limited)
    except Exception as exc:  # noqa: BLE001 — termin 24 h ważniejszy niż pełny raport
        logger.warning(
            "[competence-report] build failed report=%s: %s",
            row.id,
            type(exc).__name__,
        )
        snapshot = fallback_snapshot(row)
        row.last_error = f"build_error:{type(exc).__name__}"[:120]
    row.snapshot = snapshot.model_dump(mode="json")
    row.status, row.ready_at, row.attempts = "ready", now, 0
    await db.commit()
    return snapshot.variant


async def _retrigger(db: AsyncSession, now: datetime, stats: dict) -> None:
    rows = (
        await db.scalars(
            select(CompetenceReport)
            .join(Candidate, Candidate.id == CompetenceReport.candidate_id)
            .where(
                CompetenceReport.status == "waiting_cv",
                CompetenceReport.opted_out_at.is_(None),
                CompetenceReport.attempts == 0,
                CompetenceReport.created_at <= now - RETRIGGER_AFTER,
                Candidate.cv_parsed_at.is_(None),
            )
            .order_by(CompetenceReport.id)
            .limit(BATCH)
            .with_for_update(of=CompetenceReport, skip_locked=True)
        )
    ).all()
    candidate_ids = []
    for row in rows:
        row.attempts = 1
        candidate_ids.append(row.candidate_id)
    await db.commit()
    for candidate_id in dict.fromkeys(candidate_ids):
        _retrigger_parse(candidate_id)
        stats["retriggered"] += 1


async def _send_due(db: AsyncSession, now: datetime, stats: dict) -> None:
    from app.services.candidate_terms_queue import candidate_sender_ready
    from app.services.notification_delivery import load_policy

    if not candidate_sender_ready():
        return
    policy = await load_policy(db)
    if not policy.kind_enabled(KIND):
        return
    seen: set[int] = set()
    for _ in range(BATCH):
        row = await db.scalar(
            select(CompetenceReport)
            .where(
                CompetenceReport.status == "ready",
                CompetenceReport.held_at.is_(None),
                CompetenceReport.opted_out_at.is_(None),
                CompetenceReport.send_due_at <= now,
                CompetenceReport.created_at <= now,
                CompetenceReport.id.not_in(seen) if seen else true(),
            )
            .order_by(CompetenceReport.send_due_at, CompetenceReport.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return
        report_id = row.id
        seen.add(report_id)
        try:
            await send_report(db, row, by_user_id=None, now=now)
        except ReportNotSendable as exc:
            stats["skipped"] += 1
            logger.info(
                "[competence-report] not sent report=%s: %s", report_id, exc.reason
            )
            continue
        except Exception as exc:  # noqa: BLE001 — jeden raport nie zatrzymuje pętli
            logger.warning(
                "[competence-report] send aborted report=%s: %s",
                report_id,
                type(exc).__name__,
            )
            await _row_failed(
                db, report_id, f"send_error:{type(exc).__name__}", from_status="ready"
            )
            stats["retry"] += 1
            continue
        stats[
            "sent"
            if row.status == "sent"
            else "failed"
            if row.status == "failed"
            else "retry"
        ] += 1


async def process_due(db: AsyncSession, *, now: Optional[datetime] = None) -> dict:
    """Jeden przebieg pętli. Zwraca liczniki (bez danych osobowych)."""
    now = now or datetime.now(timezone.utc)
    stats = {
        "built": 0,
        "limited": 0,
        "retriggered": 0,
        "sent": 0,
        "retry": 0,
        "failed": 0,
        "skipped": 0,
    }
    # Każdy etap osobno: awaria składania nie zatrzymuje wysyłki gotowych raportów.
    for phase in (_build_ready, _retrigger, _send_due):
        try:
            await phase(db, now, stats)
        except Exception:  # noqa: BLE001
            logger.exception("competence_report_sender %s failed", phase.__name__)
            await db.rollback()
    return stats


async def run_once() -> dict:
    async with AsyncSessionLocal() as db:
        stats = await process_due(db)
    if any(stats.values()):
        logger.info("competence_report_sender %s", stats)
    return stats


async def competence_report_sender_loop() -> None:
    if not settings.COMPETENCE_REPORT_SENDER_ENABLED:
        logger.info("competence_report_sender disabled")
        return
    beat = loop_heartbeat.register(
        "competence_report_sender", max_silence_seconds=LOOP_SLEEP_SECONDS + 900
    )
    while True:
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("competence_report_sender iteration failed")
        await asyncio.sleep(LOOP_SLEEP_SECONDS)
