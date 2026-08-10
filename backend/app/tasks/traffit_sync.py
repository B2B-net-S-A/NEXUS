"""Scheduled Traffit → Nexus sync.

Keeps Nexus complete and current against Traffit:

- **Daily delta** (~02:00 UTC): pulls only records changed since the last
  watermark (candidates, jobs, files/CV, stages, activities → notes, sources)
  and upserts idempotently. Light.
- **Weekly full reconcile** (Sun ~02:00 UTC): a full-scan safety net so nothing
  is ever permanently missed.

The importer (``app/services/traffit/importer.py``) is the same one used for the
one-time migration — every write is ON CONFLICT idempotent, so re-runs and the
delta/full overlap are safe.

Restart-safe: the loop decides whether a run is due from the **persisted**
``traffit_sync_state`` watermark, not an in-memory timer. Coolify rebuilds the
container on every push to ``main``; without the persisted gate we'd re-trigger
a multi-hour import on each deploy.

Kill-switch: ``settings.TRAFFIT_SYNC_ENABLED`` (default False). The loop exits
immediately when off; secrets missing → loop idles and re-checks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.cortex import runs as cortex_runs
from app.services.cortex.extractor_traffit import import_cortex_facts
from app.services.traffit.client import TraffitClient, TraffitConfig
from app.services.traffit.importer import TraffitImporter

logger = logging.getLogger(__name__)

# Serialize runs across the scheduled loop and on-demand admin triggers so two
# imports never overlap (both would hit the same Traffit API + DB rows).
_sync_lock = asyncio.Lock()

DAILY_MARKER = "__daily__"
FULL_MARKER = "__full__"


def sync_is_running() -> bool:
    """True while a delta/full sync is in progress (admin endpoint guard)."""
    return _sync_lock.locked()


# ── Scheduling decisions (pure, unit-testable) ───────────────────────────────


def should_run_daily(
    now_utc: datetime,
    last_finished: Optional[datetime],
    hour_utc: int,
    *,
    min_gap_hours: int = 20,
) -> bool:
    """Daily delta is due?

    First run (no watermark) fires immediately after enabling, regardless of
    hour. Afterwards it runs only at/after ``hour_utc`` and only once the gap
    since the last finish is large enough (prevents same-day re-runs and
    Coolify-redeploy re-triggers).
    """
    if last_finished is None:
        return True
    if now_utc.hour < hour_utc:
        return False
    return (now_utc - last_finished) >= timedelta(hours=min_gap_hours)


def should_run_full(
    now_utc: datetime,
    last_finished: Optional[datetime],
    weekday: int,
    hour_utc: int,
    *,
    min_gap_days: int = 6,
) -> bool:
    """Weekly full reconcile is due? Only on the configured weekday at/after the
    hour — never fires immediately on enable (it's a heavy full scan)."""
    if now_utc.weekday() != weekday:
        return False
    if now_utc.hour < hour_utc:
        return False
    if last_finished is None:
        return True
    return (now_utc - last_finished) >= timedelta(days=min_gap_days)


# ── Watermark state helpers ──────────────────────────────────────────────────


async def _get_state(db, phase: str):
    row = await db.execute(
        text(
            "SELECT phase, last_synced_at, last_run_started_at, "
            "last_run_finished_at, last_status, stats "
            "FROM traffit_sync_state WHERE phase = :phase"
        ),
        {"phase": phase},
    )
    return row.fetchone()


_UPSERT_STATE = text(
    """
    INSERT INTO traffit_sync_state (
        phase, last_synced_at, last_run_started_at, last_run_finished_at,
        last_status, stats, created_at, updated_at
    ) VALUES (
        :phase, :last_synced_at, :last_run_started_at, :last_run_finished_at,
        :last_status, CAST(:stats AS jsonb), NOW(), NOW()
    )
    ON CONFLICT (phase) DO UPDATE SET
        last_synced_at       = COALESCE(
            EXCLUDED.last_synced_at, traffit_sync_state.last_synced_at
        ),
        last_run_started_at  = COALESCE(
            EXCLUDED.last_run_started_at, traffit_sync_state.last_run_started_at
        ),
        last_run_finished_at = COALESCE(
            EXCLUDED.last_run_finished_at, traffit_sync_state.last_run_finished_at
        ),
        last_status          = EXCLUDED.last_status,
        stats                = COALESCE(EXCLUDED.stats, traffit_sync_state.stats),
        updated_at           = NOW()
    """
)


async def _upsert_state(
    db,
    phase: str,
    *,
    last_synced_at: Optional[datetime] = None,
    last_run_started_at: Optional[datetime] = None,
    last_run_finished_at: Optional[datetime] = None,
    last_status: Optional[str] = None,
    stats: Optional[dict[str, Any]] = None,
) -> None:
    await db.execute(
        _UPSERT_STATE,
        {
            "phase": phase,
            "last_synced_at": last_synced_at,
            "last_run_started_at": last_run_started_at,
            "last_run_finished_at": last_run_finished_at,
            "last_status": last_status,
            "stats": json.dumps(stats) if stats is not None else None,
        },
    )
    await db.commit()


# ── Cortex extraction phase ──────────────────────────────────────────────────


class _CortexPhaseResult:
    """Adapter stats ekstraktora Cortexa na kontrakt fazy (as_dict/errors/*_at)."""

    def __init__(
        self, stats: dict[str, Any], started_at: datetime, finished_at: datetime
    ):
        self._stats = stats
        self.started_at = started_at
        self.finished_at = finished_at
        self.errors = int(stats.get("errors") or 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "processed": self._stats.get("processed", 0),
            "inserted": self._stats.get("facts_upserted", 0),
            "skipped": self._stats.get("unmatched_tokens", 0),
            "errors": self.errors,
            "total_source": self._stats.get("total", 0),
            **({"note": self._stats["skipped"]} if "skipped" in self._stats else {}),
        }


async def _cortex_phase(since: Optional[datetime]) -> _CortexPhaseResult:
    """Faza Cortexa w daily sync — własna sesja (izoluje częste commity ekstraktora).

    Delta (``since=files_since``=run_start) re-ekstrahuje tylko kandydatów, których
    faza ``candidates`` dotknęła w tym runie; full (``since=None``) skanuje bazę i
    reconciluje. Najpierw sprząta osierocone runy (zwalnia slot single-flight)."""
    started = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as cortex_db:
        await cortex_runs.reap_orphans(cortex_db)
        stats = await import_cortex_facts(cortex_db, since=since)
    return _CortexPhaseResult(stats, started, datetime.now(timezone.utc))


class _ReconcilePhaseResult:
    """Adapter raportu `reconcile()` na kontrakt fazy.

    CELOWO `errors = 0`: to sonda obserwacyjna, nie import. Rozjazd liczników
    jest informacją dla operatora, a nie powodem, żeby zamrozić watermark —
    zamrożenie wstrzymałoby wszystkie pozostałe fazy z powodu czegoś, czego ta
    faza i tak nie potrafi naprawić.
    """

    def __init__(
        self, report: dict[str, Any], started_at: datetime, finished_at: datetime
    ):
        self._report = report
        self.started_at = started_at
        self.finished_at = finished_at
        self.errors = 0

    def as_dict(self) -> dict[str, Any]:
        drift = {
            entity: row
            for entity, row in self._report.items()
            if isinstance(row, dict)
            and (row.get("error") or row.get("traffit") != row.get("nexus"))
        }
        return {
            "processed": len(self._report),
            # NOT `skipped`: that field means "records skipped" in every other
            # phase, and this counts entity TYPES out of sync (0-6).
            "drifted_entities": len(drift),
            "errors": 0,
            "note": "counters only — Nexus>Traffit means rows deleted in Traffit",
            **({"drift": drift} if drift else {}),
        }


async def _reconcile_phase(importer: TraffitImporter) -> _ReconcilePhaseResult:
    """Porównanie liczników Traffit vs Nexus jako faza raportowa.

    `TraffitImporter.reconcile()` istniał od migracji, ale NIE był wpięty w
    `_phase_plan`, więc w zaplanowanym syncu nie biegł nigdy. Skutek: dryf w
    drugą stronę — rekordy obecne w Nexusie, a usunięte w Traffit — był
    całkowicie niewidoczny (brak obsługi tombstone'ów to osobna, większa
    sprawa). Sześć wywołań `total_count` + sześć lokalnych `count(*)`, więc
    wpięcie jest tanie i czyni rozjazd widocznym w `/sync/status`.
    """
    started = datetime.now(timezone.utc)
    try:
        report = await importer.reconcile()
    except Exception as exc:  # noqa: BLE001
        # Six Traffit API calls live here. `errors = 0` on the adapter protects
        # the watermark from DRIFT, but not from a RAISE: the orchestrator's
        # generic handler would stamp this phase `error`, flip `any_error`, and
        # a nightly run in which every real import phase succeeded would refuse
        # to advance its watermark — because the last, purely observational
        # phase hiccuped. Swallow it here instead.
        logger.warning("Traffit reconcile phase failed (informational): %r", exc)
        # Shaped per-entity on purpose: `as_dict()`'s drift filter expects
        # ``{entity: {...}}`` and drops non-dict values, so a bare
        # ``{"error": "..."}`` would vanish instead of surfacing.
        report = {"reconcile": {"error": repr(exc)[:200]}}
    return _ReconcilePhaseResult(report, started, datetime.now(timezone.utc))


# ── Phase plan ───────────────────────────────────────────────────────────────


def _phase_plan(
    importer: TraffitImporter,
    since: Optional[datetime],
    files_since: Optional[datetime],
):
    """(name, coroutine-factory) in FK dependency order.

    Small master-data phases full-scan every run (cheap: ~700 rows total).
    Data phases honour ``since`` (None = full scan).

    The CV/files phases use a separate ``files_since`` cutoff. In delta mode this
    is the run start, not the data ``since``: the candidates phase has just
    upserted exactly the Traffit-changed candidates (bumping their Nexus
    ``updated_at`` to NOW() >= run start), so scoping files to ``run_start``
    re-fetches files only for candidates Traffit actually changed — instead of
    every candidate edited in Nexus within the 45-day window (which is all of
    them). One /files API call per genuinely-changed candidate, not per row.
    """
    return [
        ("users", importer.import_users),
        ("clients", importer.import_clients),
        ("contacts", importer.import_contacts),
        ("workflows", importer.import_workflows),
        ("candidates", lambda: importer.import_candidates(since=since)),
        # Cortex re-ekstrahuje fakty skilli tuż po upsercie kandydatów. W delcie
        # używa ``files_since`` (=run_start) — tylko kandydaci dotknięci w tym
        # runie (updated_at >= run_start), tak jak faza plików. Reconcile +
        # single-flight czynią to bezpiecznym.
        *(
            [("cortex", lambda: _cortex_phase(files_since))]
            if settings.CORTEX_SYNC_ENABLED
            else []
        ),
        ("jobs", lambda: importer.import_jobs(since=since)),
        ("talents", importer.import_talents),
        ("candidates_cv", lambda: importer.import_candidates_cv(since=files_since)),
        ("candidate_files", lambda: importer.import_candidate_files(since=files_since)),
        (
            "candidates_enrich_names",
            lambda: importer.enrich_missing_names(since=files_since),
        ),
        ("pipelines", lambda: importer.import_pipelines(since=since)),
        (
            "candidate_activities",
            lambda: importer.import_candidate_activities(since=since),
        ),
        ("candidate_sources", lambda: importer.import_candidate_sources(since=since)),
        # Ostatnia i wyłącznie raportowa — nic nie zapisuje, nic nie blokuje.
        ("reconcile", lambda: _reconcile_phase(importer)),
    ]


def _summarize(progress_dict: dict[str, Any]) -> dict[str, Any]:
    """Compact per-phase summary for the watermark stats JSONB.

    Zachowuje też przycięte ``error_samples`` — bez nich watermark mówi tylko
    "errors: 311" i diagnoza z admin statusu jest niemożliwa (prod nie ma
    dostępnych logów kontenera po restarcie). Sample zawierają identyfikatory
    i repr wyjątku, nie wartości pól kandydata.
    """
    keys = (
        "processed",
        "inserted",
        "updated",
        "skipped",
        "errors",
        "notes_promoted",
        "skipped_pages",
        "resynced_pointers",
        "drifted_entities",
        "drift",
        "total_source",
    )
    out = {k: progress_dict.get(k) for k in keys if k in progress_dict}
    samples = progress_dict.get("error_samples") or []
    if samples:
        out["error_samples"] = [str(s)[:200] for s in samples[:10]]
    return out


def _next_quarantine(
    previous: Optional[dict[str, Any]], error_refs: list[str]
) -> dict[str, int]:
    """Consecutive-failure counter per source row.

    Rows that failed again keep counting up; rows absent from this run's errors
    are dropped, because "it imported this time" is exactly the recovery signal
    — a row must not accumulate credit towards quarantine across unrelated runs.
    """
    prev = previous or {}
    return {ref: int(prev.get(ref, 0)) + 1 for ref in error_refs}


def _blocking_errors(
    total_errors: int,
    error_refs: list[str],
    quarantine: dict[str, int],
    limit: int,
    attributed_errors: Optional[int] = None,
) -> int:
    """How many of this phase's errors may still hold back the watermark.

    Quarantined rows (``attempts >= limit``) stop blocking. Everything else
    does — including errors we could NOT attribute to a row (e.g.
    "total_count failed"), because an unattributable error might be a brand-new
    fault and we refuse to let it ride in on a known-bad row's exemption.

    ``attributed_errors`` is how many errors carried a row key, which is NOT
    ``len(error_refs)``: one row can fail twice in a single run and then the set
    holds one entry for two errors. Deriving the count from the set size
    invented a phantom unattributable error that blocked the watermark forever,
    so the quarantine could never release — the mechanism silently did nothing.
    The parameter is optional so older callers keep the previous (set-size)
    behaviour instead of crashing; every live caller passes it.
    """
    attributed = len(error_refs) if attributed_errors is None else attributed_errors
    unattributable = max(0, total_errors - attributed)
    still_retrying = sum(1 for ref in error_refs if quarantine.get(ref, 0) < limit)
    return unattributable + still_retrying


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def run_traffit_sync(mode: str = "delta") -> dict[str, Any]:
    """Run all phases once. ``mode`` = "delta" (incremental) | "full" (reconcile).

    Returns a summary dict. Safe to call from the loop or the admin endpoint —
    the module lock serializes overlapping calls (the second one is skipped).
    """
    if mode not in ("delta", "full"):
        raise ValueError(f"mode must be 'delta' or 'full', got {mode!r}")

    if _sync_lock.locked():
        logger.info("Traffit sync already running — skipping %s request", mode)
        return {"skipped": True, "reason": "already_running", "mode": mode}

    async with _sync_lock:
        run_start = datetime.now(timezone.utc)
        try:
            config = TraffitConfig.from_env()
        except RuntimeError as exc:
            logger.warning("Traffit sync skipped: %s", exc)
            return {"skipped": True, "reason": "secrets_missing", "mode": mode}

        results: dict[str, Any] = {}
        logger.info("Traffit %s sync starting", mode)

        async with TraffitClient(config) as traffit:
            async with AsyncSessionLocal() as db:
                # Compute the delta cutoff from the persisted watermark.
                since: Optional[datetime] = None
                if mode == "delta":
                    daily = await _get_state(db, DAILY_MARKER)
                    if daily is not None and daily.last_synced_at is not None:
                        since = daily.last_synced_at - timedelta(
                            hours=settings.TRAFFIT_SYNC_DELTA_LOOKBACK_HOURS
                        )
                    else:
                        # First delta ever — backfill since the migration.
                        since = run_start - timedelta(
                            days=settings.TRAFFIT_SYNC_INITIAL_BACKFILL_DAYS
                        )
                    logger.info("Traffit delta cutoff (since): %s", since)

                # CV/files re-fetch only candidates this run actually touched
                # (Traffit-changed → upserted with updated_at >= run_start).
                # Full reconcile uses None (its own "missing files" gate).
                files_since = run_start if mode == "delta" else None

                importer = TraffitImporter(traffit, db, dry_run=False, batch_size=100)

                for name, factory in _phase_plan(importer, since, files_since):
                    try:
                        progress = await factory()
                        pd = progress.as_dict()
                        summary = _summarize(pd)

                        # Advance the per-phase watermark only when nothing is
                        # still failing. Row-level errors mean records did not
                        # import, so we keep the prior watermark
                        # (last_synced_at=None → UPSERT COALESCE preserves it)
                        # and the next delta re-covers them (M2-IMP-01).
                        #
                        # …with a bound. Without one, a row that can NEVER
                        # import freezes the watermark forever: measured on prod
                        # 2026-07-27, ONE candidate with a colliding e-mail had
                        # held `__daily__` at 2026-07-20 for 7 days. The delta
                        # window grows every night, `traffit=degraded` becomes
                        # permanent, and — worst of all — a genuinely new error
                        # is invisible because the status is already "errors".
                        # After TRAFFIT_MAX_ROW_ATTEMPTS consecutive failures a
                        # row is parked: recorded, surfaced to the operator, and
                        # no longer holding back the other 179 287 records. That
                        # is not silent loss (which M2-IMP-01 rightly forbids) —
                        # it is explicit, countable, and owned.
                        prev = await _get_state(db, name)
                        prev_stats = (prev.stats if prev is not None else None) or {}
                        quarantine = _next_quarantine(
                            prev_stats.get("quarantine"), pd.get("error_refs") or []
                        )
                        blocking = _blocking_errors(
                            progress.errors,
                            pd.get("error_refs") or [],
                            quarantine,
                            settings.TRAFFIT_MAX_ROW_ATTEMPTS,
                            attributed_errors=pd.get("attributed_errors"),
                        )
                        parked = {
                            ref: n
                            for ref, n in quarantine.items()
                            if n >= settings.TRAFFIT_MAX_ROW_ATTEMPTS
                        }
                        if blocking:
                            # Read by the global gate below. Absent when zero so
                            # the stats stay quiet on a clean phase.
                            summary["blocking_errors"] = blocking
                        if quarantine:
                            summary["quarantine"] = quarantine
                        if parked:
                            summary["quarantined"] = sorted(parked)
                            logger.warning(
                                "Traffit phase %s: %d row(s) quarantined after "
                                "%d consecutive failures and no longer blocking "
                                "the watermark: %s",
                                name,
                                len(parked),
                                settings.TRAFFIT_MAX_ROW_ATTEMPTS,
                                sorted(parked),
                            )

                        results[name] = summary
                        await _upsert_state(
                            db,
                            name,
                            last_synced_at=None if blocking else run_start,
                            last_run_started_at=progress.started_at,
                            last_run_finished_at=progress.finished_at,
                            last_status="errors" if blocking else "ok",
                            stats=summary,
                        )
                        logger.info("Traffit phase %s: %s", name, results[name])
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Traffit phase %s failed", name)
                        results[name] = {"error": repr(exc)}
                        try:
                            await db.rollback()
                        except Exception:  # noqa: BLE001
                            pass
                        await _upsert_state(
                            db,
                            name,
                            last_status="error",
                            stats={"error": repr(exc)[:500]},
                        )

                finished = datetime.now(timezone.utc)
                # Same definition as the per-phase gate above: a quarantined row
                # is NOT a blocker. Reading `v.get("errors")` here instead would
                # re-freeze the daily watermark on the very rows the phase just
                # decided to park, and the whole mechanism would be a no-op.
                any_error = any(
                    isinstance(v, dict) and ("error" in v or v.get("blocking_errors"))
                    for v in results.values()
                )
                status = "errors" if any_error else "ok"

                # Advance the delta watermark (``last_synced_at``) ONLY on a
                # clean run. If any phase raised or reported row-level errors we
                # keep the previous watermark so the NEXT delta re-covers the
                # failed range — otherwise a record that failed to import ages
                # out of the ~48h overlap window and is silently lost forever,
                # drifting Nexus away from Traffit (M2-IMP-01). Passing
                # ``last_synced_at=None`` lets the UPSERT's COALESCE preserve the
                # prior value; idempotent upserts + the lookback overlap make the
                # re-cover safe.
                #
                # ``last_run_finished_at`` / ``last_status`` advance regardless,
                # so the daily gate resets to the normal schedule (no hot-retry
                # loop) and /api/health surfaces the failure as ``degraded``.
                watermark = run_start if not any_error else None

                # A full run also advances the daily watermark (it covers
                # everything) so the next delta computes its cutoff from here and
                # the daily gate resets.
                await _upsert_state(
                    db,
                    FULL_MARKER if mode == "full" else DAILY_MARKER,
                    last_synced_at=watermark,
                    last_run_started_at=run_start,
                    last_run_finished_at=finished,
                    last_status=status,
                    stats=results,
                )
                if mode == "full":
                    await _upsert_state(
                        db,
                        DAILY_MARKER,
                        last_synced_at=watermark,
                        last_run_finished_at=finished,
                        last_status=status,
                        stats={"via": "full_reconcile"},
                    )

        notes = sum(
            v.get("notes_promoted") or 0
            for v in results.values()
            if isinstance(v, dict)
        )
        logger.info(
            "Traffit %s sync done: status=%s notes_promoted=%d", mode, status, notes
        )
        return {
            "mode": mode,
            "status": status,
            "since": since.isoformat() if since else None,
            "notes_promoted": notes,
            "phases": results,
        }


# ── Background loop ───────────────────────────────────────────────────────────


async def traffit_daily_sync_loop() -> None:
    """Periodic Traffit sync scheduler. Cancellation-aware."""
    if not settings.TRAFFIT_SYNC_ENABLED:
        logger.info("traffit_daily_sync_loop disabled (TRAFFIT_SYNC_ENABLED=false)")
        return

    check_interval = max(300, int(settings.TRAFFIT_SYNC_CHECK_INTERVAL_SECONDS))
    logger.info("traffit_daily_sync_loop started (check every %ds)", check_interval)
    await asyncio.sleep(60)  # bootstrap grace

    while True:
        try:
            if not settings.TRAFFIT_SYNC_ENABLED:
                await asyncio.sleep(check_interval)
                continue

            now = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as db:
                daily = await _get_state(db, DAILY_MARKER)
                full = await _get_state(db, FULL_MARKER)
            daily_done = daily.last_run_finished_at if daily else None
            full_done = full.last_run_finished_at if full else None

            if should_run_full(
                now,
                full_done,
                settings.TRAFFIT_SYNC_FULL_WEEKDAY,
                settings.TRAFFIT_SYNC_HOUR_UTC,
            ):
                logger.info("Traffit: weekly full reconcile is due")
                await run_traffit_sync("full")
            elif should_run_daily(now, daily_done, settings.TRAFFIT_SYNC_HOUR_UTC):
                logger.info("Traffit: daily delta is due")
                await run_traffit_sync("delta")
        except asyncio.CancelledError:
            logger.info("traffit_daily_sync_loop cancelled — shutting down")
            return
        except Exception:  # noqa: BLE001
            logger.exception("traffit_daily_sync_loop iteration failed")

        await asyncio.sleep(check_interval)
