"""Agregaty i reguła zastoju dla runów integracji (scrapery pracuj.pl / JJIT).

Logika żyje tutaj, nie w routerze, z dwóch powodów: (1) pętla alertów i
endpoint Insights muszą liczyć „zastój" IDENTYCZNIE — jedna funkcja, jedno
źródło prawdy; (2) testy jednostkowe reguły nie potrzebują FastAPI.

Definicje:
- **udany run** — ``status in ('ok', 'errors')``. „errors" to run, który się
  dokończył, ale część kandydatów padła; to nadal dowód, że scraper żyje.
  ``failed`` (crash, brak logowania) i ``running`` bez końca — nie.
- **zastój** — brak udanego runu od ``stale_after_hours`` (domyślnie 26 h:
  doba harmonogramu + 2 h zapasu na opóźnienia z launchd/caffeinate) ALBO
  źródło nigdy nie raportowało. Run „running" starszy niż ``stale_after_hours``
  traktujemy jak martwy (proces zabity bez ``finish``).
- **niedokończone zgłoszenie** — para ``source`` + ``external_id``, której
  najnowsze zdarzenie w oknie to błąd. Przebiegi próbne (``NON_DELIVERY_MODES``)
  nic nie zapisują, więc nie zamykają błędu i same go nie zgłaszają.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import desc, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_run import (
    INTEGRATION_SOURCE_LABELS,
    INTEGRATION_SOURCES,
    IntegrationRun,
    IntegrationRunEvent,
)

SUCCESS_STATUSES: tuple[str, ...] = ("ok", "errors")
# Klucze liczników wspólne dla obu scraperów — agregujemy tylko te.
STAT_KEYS: tuple[str, ...] = (
    "created",
    "duplicates",
    "cv_refreshed",
    "errors",
    "skipped",
    "nexus_pushed",
    "nexus_created",
    "nexus_existing",
    "nexus_jobs",
    "nexus_errors",
)
NON_DELIVERY_MODES: tuple[str, ...] = ("test", "dry_run")
#: Tyle wierszy listy błędów; resztę mówi ``unfinished_error_count``.
RECENT_ERRORS_LIMIT = 50


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _stat(stats: Any, key: str) -> int:
    if not isinstance(stats, dict):
        return 0
    value = stats.get(key)
    return int(value) if isinstance(value, (int, float)) else 0


def is_stale(
    last_success_at: Optional[datetime],
    *,
    stale_after_hours: float,
    now: Optional[datetime] = None,
) -> bool:
    """Reguła zastoju — jedna dla Insights i dla alertów Slack."""
    if last_success_at is None:
        return True
    now = now or _utcnow()
    return (now - _as_aware(last_success_at)) > timedelta(hours=stale_after_hours)


def run_to_dict(run: IntegrationRun) -> dict:
    return {
        "id": run.id,
        "source": run.source,
        "mode": run.mode,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "host": run.host,
        "version": run.version,
        "stats": run.stats or {},
        "error": run.error,
    }


#: Run „running” dłużej niż tyle godzin = proces zabity bez ``finish``.
STUCK_RUN_HOURS = 6
STUCK_RUN_ERROR = (
    "Przerwany: brak zakończenia przez 6 h (proces scrapera zatrzymany bez "
    "raportu końca)."
)


async def close_stuck_runs(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> list[int]:
    """Runy wiszące w ``running`` > ``STUCK_RUN_HOURS`` → ``failed`` (06.10.2026).

    Scraper zabity w trakcie (restart Maca, launchd) nie wysyła ``finish``.
    Audyt 06.10.2026: takie runy wisiały w Insights jako „trwa” bez końca.
    Zwraca ID zamkniętych runów; zapis idzie w sesji wołającego (bez commita).
    """
    now = now or _utcnow()
    cutoff = now - timedelta(hours=STUCK_RUN_HOURS)

    result = await db.execute(
        update(IntegrationRun)
        .where(IntegrationRun.status == "running", IntegrationRun.started_at < cutoff)
        .values(status="failed", finished_at=now, error=STUCK_RUN_ERROR)
        .returning(IntegrationRun.id)
        .execution_options(synchronize_session=False)
    )
    return [int(i) for i in result.scalars().all()]


async def last_success_per_source(db: AsyncSession) -> dict[str, Optional[datetime]]:
    """Ostatni UDANY run per źródło (``ok``/``errors``); brak wiersza = None."""
    rows = (
        await db.execute(
            select(IntegrationRun.source, func.max(IntegrationRun.finished_at))
            .where(IntegrationRun.status.in_(SUCCESS_STATUSES))
            .group_by(IntegrationRun.source)
        )
    ).all()
    found = {source: finished for source, finished in rows}
    return {source: found.get(source) for source in INTEGRATION_SOURCES}


def collapse_error_events(
    events: Iterable[Any], *, show_candidates: bool
) -> tuple[list[dict], int]:
    """Zdarzenia od najnowszego → (niedokończone zgłoszenia, liczba dokończonych).

    Scraper ponawia zgłoszenie w kolejnych runach (a drugi Mac robi to samo),
    więc surowe wiersze błędu to głównie zgłoszenia, które później się udały
    (03.11.2026: 74 ze 114). Próby liczą się od ostatniego sukcesu.

    Błąd bez ``external_id`` zostaje osobnym wierszem: nie wiadomo, czy to to
    samo zgłoszenie ani czy później się udało.
    """
    rows: dict[Any, dict] = {}
    finished: set[Any] = set()
    resolved = 0
    for event in events:
        key = (event.source, event.external_id) if event.external_id else event.id
        if key in finished:
            continue
        if event.action != "error":
            finished.add(key)
            resolved += key not in rows
        elif key in rows:
            rows[key]["attempts"] += 1
        else:
            rows[key] = {
                "occurred_at": event.occurred_at,
                "source": event.source,
                "run_id": event.run_id,
                "external_id": event.external_id,
                # Sekcja Insights wpuszcza też konta bez odczytu kandydatów
                # (Rada nadzorcza): zdarzenie zostaje, osoba znika.
                "candidate_id": event.candidate_id if show_candidates else None,
                "candidate_name": event.candidate_name if show_candidates else None,
                "offer_title": event.offer_title,
                "error": event.error,
                "attempts": 1,
            }
    return list(rows.values()), resolved


async def _load_error_events(db: AsyncSession, *, since: datetime) -> list[Any]:
    """Błędy z okna i pozostałe zdarzenia zgłoszeń, które mają w oknie błąd.

    Okno wystarcza: wszystko, co zamyka błąd z okna, jest od niego późniejsze.
    Dlatego ``attempts`` to próby w wybranym oknie, nie w całej historii.
    """
    delivered = IntegrationRunEvent.run_id.in_(
        select(IntegrationRun.id).where(IntegrationRun.mode.not_in(NON_DELIVERY_MODES))
    )
    failed_applications = select(
        IntegrationRunEvent.source, IntegrationRunEvent.external_id
    ).where(
        IntegrationRunEvent.action == "error",
        IntegrationRunEvent.occurred_at >= since,
        IntegrationRunEvent.external_id != "",
        delivered,
    )
    result = await db.execute(
        select(
            IntegrationRunEvent.id,
            IntegrationRunEvent.action,
            IntegrationRunEvent.occurred_at,
            IntegrationRunEvent.source,
            IntegrationRunEvent.run_id,
            IntegrationRunEvent.external_id,
            IntegrationRunEvent.candidate_id,
            IntegrationRunEvent.candidate_name,
            IntegrationRunEvent.offer_title,
            IntegrationRunEvent.error,
        )
        .where(
            IntegrationRunEvent.occurred_at >= since,
            delivered,
            or_(
                IntegrationRunEvent.action == "error",
                tuple_(IntegrationRunEvent.source, IntegrationRunEvent.external_id).in_(
                    failed_applications
                ),
            ),
        )
        .order_by(desc(IntegrationRunEvent.occurred_at), desc(IntegrationRunEvent.id))
    )
    return list(result.all())


async def build_summary(
    db: AsyncSession,
    *,
    days: int,
    stale_after_hours: float,
    show_candidates: bool,
    now: Optional[datetime] = None,
) -> dict:
    """Wszystko, czego potrzebuje sekcja „Integracje" w Insights — w jednym obiekcie."""
    now = now or _utcnow()
    since = now - timedelta(days=days)

    last_success = await last_success_per_source(db)

    # Ostatni run per źródło (dowolny status) — do kafelka „ostatni run".
    last_runs: dict[str, IntegrationRun] = {}
    for source in INTEGRATION_SOURCES:
        run = (
            await db.execute(
                select(IntegrationRun)
                .where(IntegrationRun.source == source)
                .order_by(desc(IntegrationRun.started_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if run is not None:
            last_runs[source] = run

    # Sumy liczników i seria dzienna z runów w oknie.
    window_runs = (
        (
            await db.execute(
                select(IntegrationRun)
                .where(IntegrationRun.started_at >= since)
                .where(IntegrationRun.mode != "test")
                .order_by(IntegrationRun.started_at)
            )
        )
        .scalars()
        .all()
    )

    totals: dict[str, dict[str, int]] = {
        source: {key: 0 for key in STAT_KEYS} | {"runs": 0, "runs_failed": 0}
        for source in INTEGRATION_SOURCES
    }
    daily: dict[tuple[str, str], dict[str, int]] = {}
    for run in window_runs:
        if run.source not in totals:
            continue
        bucket = totals[run.source]
        bucket["runs"] += 1
        if run.status == "failed":
            bucket["runs_failed"] += 1
        day = _as_aware(run.started_at).date().isoformat()
        day_bucket = daily.setdefault(
            (run.source, day),
            {"created": 0, "duplicates": 0, "errors": 0, "nexus_jobs": 0},
        )
        for key in STAT_KEYS:
            value = _stat(run.stats, key)
            bucket[key] += value
            if key in day_bucket:
                day_bucket[key] += value

    # Zgłoszenia wciąż niedokończone — to, co operator klika.
    unfinished_errors, resolved_error_count = collapse_error_events(
        await _load_error_events(db, since=since),
        show_candidates=show_candidates,
    )

    # Rekrutacje, do których integracje dodały najwięcej kandydatów.
    top_jobs: dict[int, dict] = {}
    matched_rows = (
        (
            await db.execute(
                select(IntegrationRunEvent.matched_jobs)
                .where(IntegrationRunEvent.occurred_at >= since)
                .where(func.jsonb_array_length(IntegrationRunEvent.matched_jobs) > 0)
            )
        )
        .scalars()
        .all()
    )
    for matched in matched_rows:
        if not isinstance(matched, list):
            continue
        for item in matched:
            if not isinstance(item, dict) or not isinstance(item.get("job_id"), int):
                continue
            entry = top_jobs.setdefault(
                item["job_id"],
                {
                    "job_id": item["job_id"],
                    "title": item.get("title") or "",
                    "count": 0,
                },
            )
            entry["count"] += 1

    sources = []
    for source in INTEGRATION_SOURCES:
        last = last_runs.get(source)
        success_at = last_success.get(source)
        stale = is_stale(success_at, stale_after_hours=stale_after_hours, now=now)
        sources.append(
            {
                "source": source,
                "label": INTEGRATION_SOURCE_LABELS.get(source, source),
                "last_run": run_to_dict(last) if last else None,
                "last_success_at": success_at,
                "stale": stale,
                "stale_after_hours": stale_after_hours,
                "totals": totals[source],
                "daily": [
                    {"date": day, **values}
                    for (src, day), values in sorted(daily.items())
                    if src == source
                ],
            }
        )

    return {
        "days": days,
        "generated_at": now,
        "sources": sources,
        "recent_errors": unfinished_errors[:RECENT_ERRORS_LIMIT],
        "unfinished_error_count": len(unfinished_errors),
        "resolved_error_count": resolved_error_count,
        "top_jobs": sorted(top_jobs.values(), key=lambda j: -j["count"])[:10],
    }
