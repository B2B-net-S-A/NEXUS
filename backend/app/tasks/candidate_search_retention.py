"""Retencja pełnego przeglądu bazy (decyzja produktowa Artura, 10.09.2026).

Każdy przegląd zapisuje w ``candidate_search_results`` wiersz na KAŻDEGO
kandydata w bazie, z dowodami dopasowania w JSONB — jedno kliknięcie
„Szukaj w całej bazie” dopisuje całą populację. Bez retencji tabela rośnie
bez końca.

Reguła: usuwamy wyłącznie przeglądy ZAKOŃCZONE (``complete``/``partial``/
``failed``), starsze niż N dni licząc od zakończenia (``completed_at``,
awaryjnie ``created_at``). Najnowszy przegląd z wynikami (``complete`` albo
``partial`` — oba są czytelne w API) zostaje dłużej: osobno dla każdej pary
(autor, OTWARTA rekrutacja), a dla przeglądów bez rekrutacji (ad hoc z Talent
Radaru) jeden na autora. Dzięki temu powrót do rekrutacji po urlopie nie kończy
się pustym ekranem. Aktywnych przeglądów ta pętla nie dotyka nigdy.

Ochrona ma dwie granice, bo bez nich tabela rosłaby z liczbą par zamiast
z czasem (~100–130 MB na przegląd, wolumen bazy 100 GB): rekrutacja zamknięta
nie chroni swojego przeglądu, a żaden przegląd nie jest chroniony dłużej niż
``CANDIDATE_SEARCH_RETENTION_PROTECT_MAX_DAYS`` (90). Ad hoc nie jest chroniony
per odcisk requestu — każda nowa treść requestu (i każdy bump wersji polityki)
dawałaby nową, wiecznie chronioną partycję.

Wyniki kasujemy partiami z commitem po każdej (``skip_locked`` — nie czekamy na
wiersz, który akurat usuwa kasowanie kandydata), a sam przegląd na końcu:
kaskada z ``candidate_search_runs`` zabrałaby dziesiątki tysięcy wierszy
w jednej instrukcji i jednej długiej transakcji.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.models.job import Job, JobStatus
from app.services.candidate_search_store import (
    FINISHED_STATES,
    RESULT_STATES,
    manual_origin_clause,
)

logger = logging.getLogger(__name__)

RESULT_BATCH_SIZE = 5000
RUNS_PER_CYCLE = 50
_MIN_INTERVAL_SECONDS = 300
_INITIAL_DELAY_SECONDS = 60


def _finished_at():
    return func.coalesce(CandidateSearchRun.completed_at, CandidateSearchRun.created_at)


def _protect_max_age() -> timedelta:
    return timedelta(
        days=max(1, int(settings.CANDIDATE_SEARCH_RETENTION_PROTECT_MAX_DAYS))
    )


def protected_run_ids(*, protect_after: datetime):
    """Najnowszy przegląd z wynikami na (autor, otwarta rekrutacja) / autora (ad hoc).

    ``PARTITION BY (created_by, job_id)`` wrzuca wszystkie przeglądy ad hoc
    jednego autora (``job_id IS NULL``) do jednej partycji — tak ma być.
    """
    ranked = (
        select(
            CandidateSearchRun.id.label("id"),
            CandidateSearchRun.job_id.label("job_id"),
            func.row_number()
            .over(
                partition_by=(CandidateSearchRun.created_by, CandidateSearchRun.job_id),
                order_by=(_finished_at().desc(), CandidateSearchRun.id.desc()),
            )
            .label("rank"),
        )
        .where(
            CandidateSearchRun.state.in_(RESULT_STATES),
            _finished_at() >= protect_after,
            # Przeglądy automatyczne (nocny automat) NIE są chronione: powstają
            # co noc, a ich wynik żyje dalej w skrzynce „Propozycje". Filtr stoi
            # WEWNĄTRZ rankingu — inaczej nocny przegląd (autor = właściciel
            # rekrutacji) zajmowałby miejsce nr 1 i zdejmował ochronę
            # z ręcznego przeglądu tej samej osoby.
            manual_origin_clause(),
        )
        .subquery()
    )
    open_jobs = select(Job.id).where(Job.status != JobStatus.closed)
    return select(ranked.c.id).where(
        ranked.c.rank == 1,
        or_(ranked.c.job_id.is_(None), ranked.c.job_id.in_(open_jobs)),
    )


async def expired_run_ids(
    db, *, cutoff: datetime, limit: int, protect_after: datetime | None = None
) -> list[str]:
    if protect_after is None:
        protect_after = datetime.now(timezone.utc) - _protect_max_age()
    finished_before = or_(
        CandidateSearchRun.completed_at < cutoff,
        and_(
            CandidateSearchRun.completed_at.is_(None),
            CandidateSearchRun.created_at < cutoff,
        ),
    )
    rows = await db.scalars(
        select(CandidateSearchRun.id)
        .where(
            CandidateSearchRun.state.in_(FINISHED_STATES),
            finished_before,
            CandidateSearchRun.id.not_in(
                protected_run_ids(protect_after=protect_after)
            ),
        )
        .order_by(_finished_at(), CandidateSearchRun.id)
        .limit(limit)
    )
    return list(rows.all())


async def purge_run(db, run_id: str, *, batch_size: int = RESULT_BATCH_SIZE) -> int:
    """Skasuj wyniki partiami (commit po każdej), potem sam przegląd."""
    deleted_total = 0
    while True:
        batch = (
            select(CandidateSearchResult.candidate_id)
            .where(CandidateSearchResult.run_id == run_id)
            .order_by(CandidateSearchResult.candidate_id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(
            delete(CandidateSearchResult).where(
                CandidateSearchResult.run_id == run_id,
                CandidateSearchResult.candidate_id.in_(batch),
            )
        )
        await db.commit()
        deleted = result.rowcount or 0
        deleted_total += deleted
        if deleted < batch_size:
            break
    # Stan sprawdzany ponownie: przegląd zakończony nie wraca do pracy, ale
    # ten warunek nie może zależeć od tego, że wybór i kasowanie dzielą sekundy.
    await db.execute(
        delete(CandidateSearchRun).where(
            CandidateSearchRun.id == run_id,
            CandidateSearchRun.state.in_(FINISHED_STATES),
        )
    )
    await db.commit()
    return deleted_total


async def prune_once(*, days: int, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        run_ids = await expired_run_ids(
            db,
            cutoff=cutoff,
            limit=RUNS_PER_CYCLE,
            protect_after=now - _protect_max_age(),
        )
    rows = 0
    for run_id in run_ids:
        async with AsyncSessionLocal() as db:
            rows += await purge_run(db, run_id)
    return {"runs": len(run_ids), "results": rows}


async def candidate_search_retention_loop() -> None:
    """Pętla tła — rejestrowana w lifespanie ``main.py``."""
    if not settings.CANDIDATE_SEARCH_RETENTION_ENABLED:
        logger.info(
            "candidate_search_retention wyłączona "
            "(CANDIDATE_SEARCH_RETENTION_ENABLED=false)"
        )
        return
    days = max(1, int(settings.CANDIDATE_SEARCH_RETENTION_DAYS))
    interval = max(
        _MIN_INTERVAL_SECONDS,
        int(settings.CANDIDATE_SEARCH_RETENTION_CHECK_INTERVAL_SECONDS),
    )
    logger.info(
        "candidate_search_retention aktywna (dni=%s, interwał %ss)", days, interval
    )
    # Start aplikacji nie może czekać na sprzątanie.
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        try:
            stats = await prune_once(days=days)
            if stats["runs"]:
                logger.info(
                    "candidate_search_retention: usunięto %s przeglądów "
                    "(%s wierszy wyników)",
                    stats["runs"],
                    stats["results"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # `exception`, nie `warning`: Sentry ma próg ERROR, a trwale padająca
            # retencja objawia się dopiero zapełnionym dyskiem Postgresa.
            logger.exception("candidate_search_retention: cykl padł")
        await asyncio.sleep(interval)
