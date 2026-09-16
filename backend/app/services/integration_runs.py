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
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc, func, select
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


async def build_summary(
    db: AsyncSession,
    *,
    days: int,
    stale_after_hours: float,
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

    # Ostatnie błędy per kandydat — to, co operator klika.
    recent_errors = (
        (
            await db.execute(
                select(IntegrationRunEvent)
                .where(IntegrationRunEvent.action == "error")
                .where(IntegrationRunEvent.occurred_at >= since)
                .order_by(desc(IntegrationRunEvent.occurred_at))
                .limit(20)
            )
        )
        .scalars()
        .all()
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
        "recent_errors": [
            {
                "occurred_at": event.occurred_at,
                "source": event.source,
                "run_id": event.run_id,
                "external_id": event.external_id,
                "candidate_id": event.candidate_id,
                "candidate_name": event.candidate_name,
                "offer_title": event.offer_title,
                "error": event.error,
            }
            for event in recent_errors
        ],
        "top_jobs": sorted(top_jobs.values(), key=lambda j: -j["count"])[:10],
    }
