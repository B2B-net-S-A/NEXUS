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
from collections.abc import Sequence
from typing import Any, Optional

from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services.cortex import runs as cortex_runs
from app.services.cortex.extractor_traffit import import_cortex_facts
from app.services.traffit.client import TraffitClient, TraffitConfig
from app.services.traffit.importer import PhaseProgress, TraffitImporter

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
    sweep_pending: bool = False,
) -> bool:
    """Full reconcile is due? Weekly on the configured weekday — unless a
    budgeted sweep is still mid-flight, in which case NIGHTLY until it lands.

    The budgeted phases (`candidate_files`, `candidates_cv`,
    `candidates_enrich_names`) cover a slice per run and park an `after_id`
    cursor for the rest. On a weekly cadence the tail is reached one slice per
    WEEK — ~57k candidates at the old 10k budget is over a month, and that
    assumes nothing interrupts. Coolify restarts the container on every push to
    main, so in practice a sweep needing several uninterrupted Sundays may
    never reach the tail at all. That is not hypothetical: it is how the files
    gap survived for months behind a green health probe.

    `sweep_pending` is derived from the cursors themselves, not from a calendar
    or a manual flag, so this is self-limiting — the extra runs stop the night
    the sweep completes and clears its cursor. Nothing to remember to turn off.
    """
    if now_utc.hour < hour_utc:
        return False
    if last_finished is None:
        # Never fires immediately on enable — it's a heavy full scan. And with
        # no prior run there is no sweep of ours to resume anyway.
        return now_utc.weekday() == weekday
    if sweep_pending:
        # Catching up: any day, but still at most one run per night — the loop
        # ticks every 30 min and would otherwise restack a multi-hour scan.
        return (now_utc - last_finished) >= timedelta(hours=20)
    if now_utc.weekday() != weekday:
        return False
    return (now_utc - last_finished) >= timedelta(days=min_gap_days)


# Phases that cover a budgeted slice per full run and park the rest behind an
# `after_id` cursor. A cursor on any of them means the last full sweep stopped
# short of the tail. Names are the orchestrator's phase-plan names, i.e. the
# rows `traffit_sync_state` actually carries.
_BUDGETED_SWEEP_PHASES = (
    "candidate_files",
    "candidates_cv",
    "candidates_enrich_names",
)


async def full_sweep_pending(db) -> bool:
    """Did the last full run leave a budgeted sweep unfinished?

    Reads the cursors rather than any elapsed-time heuristic: the cursor IS the
    record of "there is more to sweep", and the phase clears it itself on a
    clean pass.
    """
    rows = await db.execute(
        text(
            "SELECT cursor_payload FROM traffit_sync_state "
            "WHERE phase = ANY(:phases) AND cursor_payload IS NOT NULL"
        ),
        {"phases": list(_BUDGETED_SWEEP_PHASES)},
    )
    for (payload,) in rows:
        if not isinstance(payload, dict) or not payload:
            continue
        if payload.keys() & {"delta", "full"}:
            # Per-mode shape. Only the full slot is ours; a delta-only slot is
            # a different phase's business and must not trigger nightly full
            # scans. Testing `"full" in payload` alone got this wrong — a
            # delta-only payload fell through to the legacy branch below.
            #
            # Falsy slot == cleared, and that is an invariant of the writer, not
            # an assumption: `_clear_mode_cursor` POPS the key rather than
            # blanking it, and every `_write_mode_cursor` call passes a
            # populated entry. If a future write path ever parks an empty slot
            # as an intermediate state, it would read as "sweep finished" here
            # and silently drop the catch-up — treat that as a reason to change
            # this check, not to leave both behaviours in place.
            if payload.get("full"):
                return True
            continue
        return True  # legacy flat shape — a full-run cursor by construction
    return False


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


# ── Atrybucja błędów w fazach spoza importera ────────────────────────────────


def _attributed_progress(
    stats: dict[str, Any], *, phase: str, verb: str, entity: str, detail: str
) -> PhaseProgress:
    """``PhaseProgress`` użyty WYŁĄCZNIE jako akumulator atrybucji błędów.

    Fazy `cortex` i `candidates_cv_fields` nie idą przez importera Traffita,
    więc ich statystyki to zwykłe słowniki, a nie ``PhaseProgress``. Do
    2026-08-20 ich adaptery nie wystawiały ``error_refs``/``attributed_errors``,
    przez co `_blocking_errors` traktował KAŻDY błąd tych faz jako
    nieprzypisany: watermark stał bezterminowo, a kwarantanna nie miała czego
    zaparkować. Jeden trwale wywracający się wiersz mroził przez to GLOBALNY
    znacznik ``__daily__`` — dokładnie ta awaria, którą kwarantanna miała
    domykać.

    Atrybucja NIE jest tu przepisana, tylko delegowana do
    ``PhaseProgress.add_error``: ta metoda trzyma cztery sprzężone
    niezmienniki (regex referencji, cap 500 z polityką „nadmiar jest
    nieprzypisany", cap sampli na 20 oraz ``attributed_errors`` liczone osobno
    od zbioru referencji). Przepisanie ich w dwóch adapterach to dokładnie ten
    dryf, przed którym ostrzega komentarz „only one place parses it back"
    w ``importer.py``.

    Komunikat ma kształt ``"<czasownik> <encja> id=<ID>: <treść>"`` — ten sam
    co 41 wywołań w importerze i co precedens ``enrich candidate_name id=…``.
    ``entity`` CELOWO nie jest gołym „candidate": faza ``candidates`` kluczuje
    referencje po ZEWNĘTRZNYM id Traffita, a tutaj są id Nexusa — wspólne słowo
    scaliłoby dwie różne przestrzenie identyfikatorów w jeden wpis kwarantanny,
    i to po cichu. ``detail`` idzie na KOŃCU i nie może nieść własnego
    ``<słowo> id=``: ``re.search`` bierze PIERWSZE dopasowanie, więc repr
    wyjątku ukradłby klucz wiersza (pełny wyjątek jest już w logu źródła).
    """
    progress = PhaseProgress(phase=phase)
    error_ids = stats.get("error_ids") or []
    for row_id in error_ids:
        progress.add_error(f"{verb} {entity} id={row_id}: {detail}")
    # Źródło o starym kształcie statystyk (bez ``error_ids``) degraduje się do
    # stanu sprzed poprawki — błędy nieprzypisane, watermark stoi — zamiast
    # wymuszać zmianę kontraktu wszystkich źródeł naraz.
    leftover = int(stats.get("errors") or 0) - len(error_ids)
    if leftover > 0:  # defensywnie: licznik ma zostać uczciwy
        progress.errors += leftover
    return progress


# ── Cortex extraction phase ──────────────────────────────────────────────────


class _CortexPhaseResult:
    """Adapter stats ekstraktora Cortexa na kontrakt fazy (as_dict/errors/*_at).

    Projekcja domenowa zostaje (``inserted`` ← ``facts_upserted`` itd.), a
    atrybucja błędów jest delegowana do ``_attributed_progress``. Świadomie NIE
    zwracamy tu całego ``PhaseProgress.as_dict()``: ten emituje STAŁY zestaw
    kluczy, więc `_summarize` zaczęłoby wypisywać na tym wierszu komplet zer
    (``notes_promoted``, ``gone_upstream``, ``tombstoned``…), a zero, którego
    nikt nie mierzył, czyta się w ``/sync/status`` jak zmierzone zero.
    """

    def __init__(
        self, stats: dict[str, Any], started_at: datetime, finished_at: datetime
    ):
        self._stats = stats
        self.started_at = started_at
        self.finished_at = finished_at
        self._progress = _attributed_progress(
            stats,
            phase="cortex",
            verb="extract",
            entity="candidate_facts",
            detail="cortex extraction failed",
        )
        self.errors = self._progress.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "processed": self._stats.get("processed", 0),
            "inserted": self._stats.get("facts_upserted", 0),
            "skipped": self._stats.get("unmatched_tokens", 0),
            "errors": self.errors,
            "total_source": self._stats.get("total", 0),
            "error_samples": self._progress.error_samples[:20],
            "error_refs": sorted(self._progress.error_refs),
            "attributed_errors": self._progress.attributed_errors,
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


class _CvFieldsPhaseResult:
    """Adapter stats `backfill_cv_fields` na kontrakt fazy (as_dict/errors/*_at).

    Atrybucja błędów jak w `_CortexPhaseResult` — patrz `_attributed_progress`.
    """

    def __init__(
        self, stats: dict[str, Any], started_at: datetime, finished_at: datetime
    ):
        self._stats = stats
        self.started_at = started_at
        self.finished_at = finished_at
        self._progress = _attributed_progress(
            stats,
            phase="candidates_cv_fields",
            verb="parse",
            entity="candidate_cv_fields",
            detail="cv field parse failed",
        )
        self.errors = self._progress.errors

    def as_dict(self) -> dict[str, Any]:
        out = {
            "processed": self._stats.get("processed", 0),
            "updated": self._stats.get("updated", 0),
            "skipped": self._stats.get("skipped_no_result", 0),
            "errors": self.errors,
            "fields_filled": self._stats.get("fields_filled", {}),
            "llm_calls": (self._stats.get("usage") or {}).get("calls", 0),
            "error_samples": self._progress.error_samples[:20],
            "error_refs": sorted(self._progress.error_refs),
            "attributed_errors": self._progress.attributed_errors,
        }
        if self._stats.get("stopped_reason"):
            out["stopped_reason"] = self._stats["stopped_reason"]
        if "note" in self._stats:
            out["note"] = self._stats["note"]
        return out


async def _cv_fields_phase(files_since: Optional[datetime]) -> _CvFieldsPhaseResult:
    """Parse pól z CV (skills/city/years) dla kandydatów dotkniętych w tym biegu.

    Domyka lukę świeżości po Fali 3: backfill był jednorazowy, a nowe/zmienione
    CV z nocnego syncu nie dostawały pól strukturalnych, dopóki ktoś nie
    odpalił biegu ręcznie. Delta-only ŚWIADOMIE: pełny reconcile nie ma tu
    czego naprawiać — pozostałość scope'u po Fali 3 to wiersze, których parser
    już nie uzupełni (sufit pokrycia), i nocne re-przemiatanie ich co tydzień
    płaciłoby LLM za te same odmowy. FILL_EMPTY + scope filter w
    `backfill_cv_fields` czynią fazę idempotentną; kwota `cv_backfill` + sufit
    `TRAFFIT_SYNC_CV_FIELDS_LIMIT` ograniczają koszt pojedynczej nocy.
    """
    started = datetime.now(timezone.utc)
    from app.services.cv_field_backfill import _scope_filter, backfill_cv_fields

    if files_since is None:
        stats: dict[str, Any] = {
            "processed": 0,
            "note": "full-scan pominięty celowo (delta-only faza)",
        }
        return _CvFieldsPhaseResult(stats, started, datetime.now(timezone.utc))

    async with AsyncSessionLocal() as db:
        ids = (
            (
                await db.execute(
                    select(Candidate.id)
                    .where(Candidate.updated_at >= files_since, *_scope_filter())
                    .order_by(Candidate.id)
                )
            )
            .scalars()
            .all()
        )
        stats = await backfill_cv_fields(
            db,
            candidate_ids=list(ids),
            limit=max(1, int(settings.TRAFFIT_SYNC_CV_FIELDS_LIMIT)),
        )
    return _CvFieldsPhaseResult(stats, started, datetime.now(timezone.utc))


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
        ("candidates_cv_fields", lambda: _cv_fields_phase(files_since)),
        ("pipelines", lambda: importer.import_pipelines(since=since)),
        (
            "candidate_activities",
            lambda: importer.import_candidate_activities(since=since),
        ),
        ("candidate_sources", lambda: importer.import_candidate_sources(since=since)),
        # Ostatnia i wyłącznie raportowa — nic nie zapisuje, nic nie blokuje.
        ("reconcile", lambda: _reconcile_phase(importer)),
    ]


# Nazwy faz w kolejności planu. Trzymane osobno, bo walidacja `phases=` musi
# działać BEZ budowania importera i klienta HTTP — a 422 za literówkę ma paść
# zanim cokolwiek ruszy. `test_traffit_sync_phases` pilnuje, żeby ta krotka nie
# rozjechała się z `_phase_plan`; rozjazd znaczyłby albo odrzucanie poprawnej
# nazwy, albo przepuszczenie nazwy, której plan nie zna (a wtedy filtr cicho
# nie uruchamia NICZEGO i bieg wygląda na udany).
PHASE_NAMES: tuple[str, ...] = (
    "users",
    "clients",
    "contacts",
    "workflows",
    "candidates",
    "cortex",
    "jobs",
    "talents",
    "candidates_cv",
    "candidate_files",
    "candidates_enrich_names",
    "candidates_cv_fields",
    "pipelines",
    "candidate_activities",
    "candidate_sources",
    "reconcile",
)


def active_phase_names() -> tuple[str, ...]:
    """Fazy, które plan wyprodukuje PRZY OBECNYCH USTAWIENIACH.

    `PHASE_NAMES` to słownik pisowni; ta funkcja mówi, co realnie pobiegnie.
    Różnią się o fazy warunkowe — dziś `cortex`, gasnący przy
    `CORTEX_SYNC_ENABLED=false`.

    Rozdzielenie jest konieczne, bo bez niego `?phases=cortex` z wyłączonym
    cortexem przechodzi walidację pisowni, bieg startuje, filtr nie dopasowuje
    NICZEGO i operator dostaje „started" po biegu, który nie zrobił nic. To ta
    sama cicha porażka, przed którą broni odrzucanie literówek — tylko wchodząca
    tylnymi drzwiami przez nazwę poprawną, ale nieaktywną.
    """
    if settings.CORTEX_SYNC_ENABLED:
        return PHASE_NAMES
    return tuple(p for p in PHASE_NAMES if p != "cortex")


def validate_phases(phases: Sequence[str]) -> frozenset[str]:
    """Sprawdź nazwy faz i zwróć je jako zbiór. Wspólne dla API i orkiestratora.

    Wydzielone, bo obie strony muszą odrzucać dokładnie to samo. Gdyby endpoint
    miał własną kopię listy, rozjazd oznaczałby 422 za poprawną nazwę albo — co
    gorsza — przepuszczenie nazwy, której plan nie zna: filtr nie uruchomiłby
    wtedy ŻADNEJ fazy, a bieg zakończyłby się statusem "ok".
    """
    requested = tuple(phases)
    if not requested:
        raise ValueError("phases must not be empty")
    unknown = [p for p in requested if p not in PHASE_NAMES]
    if unknown:
        raise ValueError(
            f"unknown phase(s): {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(PHASE_NAMES)}"
        )
    # Nazwa poprawna, ale wyłączona ustawieniem, kończy się tak samo jak
    # literówka: filtr nie dopasowuje niczego, bieg nie robi nic i raportuje
    # sukces. Odrzucamy dopiero, gdy CAŁY wybór jest nieaktywny — mieszanka
    # `candidate_files,cortex` przy wyłączonym cortexie ma sens i ma pobiec.
    active = frozenset(active_phase_names())
    if not (frozenset(requested) & active):
        inactive = sorted(set(requested) - active)
        raise ValueError(
            f"phase(s) not active in this configuration: {', '.join(inactive)}. "
            f"Active now: {', '.join(active_phase_names())}"
        )
    return frozenset(requested)


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
        "gone_upstream",
        "unresolved_client",
        "tombstoned",
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


def _parked_refs(quarantine: dict[str, Any], limit: int) -> list[str]:
    """Które wiersze przekroczyły limit prób — odporne na śmieci w JSONB.

    ``quarantine`` wraca z kolumny ``jsonb``, więc wartością bywa cokolwiek, co
    kiedykolwiek tam zapisano. Nieczytelny wpis jest POMIJANY, a nie wysadza
    całości: ta funkcja jest wołana m.in. z bloku ``except`` obsługującego
    awarię fazy, gdzie wyjątek oznaczałby brak zapisu ``last_status="error"``,
    a przy okazji utratę licznika prób dla WSZYSTKICH pozostałych wierszy.
    """
    parked: list[str] = []
    for ref, attempts in quarantine.items():
        try:
            n = int(attempts)
        except (TypeError, ValueError):
            continue
        if n >= limit:
            parked.append(ref)
    return sorted(parked)


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


async def run_traffit_sync(
    mode: str = "delta", phases: Optional[Sequence[str]] = None
) -> dict[str, Any]:
    """Run the phase plan once. ``mode`` = "delta" (incremental) | "full" (reconcile).

    ``phases`` zawęża bieg do wskazanych faz. Powstało, bo `candidate_files`
    jest DZIEWIĄTĄ z piętnastu faz, a `candidates` przed nią trwa godzinami:
    Coolify restartuje kontener przy każdym pushu na main, więc bieg ginie,
    zanim dojdzie do zamiatania plików. Na prodzie 11.08 kursor plików nie
    drgnął przez 2,5 h mimo trzech uruchomionych biegów, a `__full__` stał na
    19 lipca. Bez tego parametru domknięcie zaległości wymaga okna dłuższego
    niż odstęp między deployami — czyli w praktyce nie następuje.

    Bieg CZĘŚCIOWY nie stempluje znaczników `__daily__`/`__full__`. To nie jest
    ostrożność, tylko warunek poprawności: `__daily__` wyznacza `since` kolejnej
    delty, więc przesunięcie go po biegu, który pominął fazy, przeskoczyłoby
    dane, których nikt nie zaimportował — cicha strata, dokładnie ta, której
    zakazuje M2-IMP-01. `__full__` z kolei znaczy „pełny reconcile się
    zakończył" i karmi sondę świeżości w `/api/health`. Znaczniki per faza
    aktualizują się normalnie, bo one mówią prawdę o swojej fazie.

    Returns a summary dict. Safe to call from the loop or the admin endpoint —
    the module lock serializes overlapping calls (the second one is skipped).
    """
    if mode not in ("delta", "full"):
        raise ValueError(f"mode must be 'delta' or 'full', got {mode!r}")

    # Literówka MUSI wybuchnąć — patrz `validate_phases`.
    selected = validate_phases(phases) if phases is not None else None

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

                executed = 0
                for name, factory in _phase_plan(importer, since, files_since):
                    if selected is not None and name not in selected:
                        continue
                    executed += 1
                    # Znacznik startu poza `try`: gałąź awaryjna też ma czym
                    # ostemplować wiersz fazy. Bez tego `/sync/status` po
                    # wywrotce pokazuje znaczniki z POPRZEDNIEGO, udanego biegu
                    # (COALESCE zachowuje starą wartość), czyli twierdzi, że
                    # faza ostatnio skończyła się wtedy, gdy naprawdę się udała.
                    phase_started = datetime.now(timezone.utc)
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
                        crash_stats: dict[str, Any] = {"error": repr(exc)[:500]}
                        # Przenieś licznik kwarantanny przez awarię fazy.
                        # `stats` jest podmieniane W CAŁOŚCI (COALESCE w
                        # `_UPSERT_STATE` chroni wyłącznie przed NULL-em, a to
                        # jest niepusty dict), więc do 2026-08-20 każda awaria
                        # fazy ZEROWAŁA licznik prób. Skutek: w fazie, która
                        # bywa wywracana, wiersz nie do zaimportowania NIGDY nie
                        # dobijał do TRAFFIT_MAX_ROW_ATTEMPTS — kwarantanna była
                        # martwa dokładnie tam, gdzie jest potrzebna, mimo że
                        # cały mechanizm wyglądał na sprawny.
                        #
                        # Odczyt MUSI być PO rollbacku: przed nim sesja stoi
                        # w zepsutej transakcji i SELECT rzuca
                        # PendingRollbackError — wyjątek z obsługi wyjątku,
                        # czyli faza nie zapisałaby nawet `last_status="error"`.
                        #
                        # Licznik przenosimy DOSŁOWNIE — bez inkrementu i bez
                        # kasowania. Skasowanie = reset (naprawiany błąd).
                        # Inkrement = karanie wierszy za awarię, która nie jest
                        # ich: po N wywrotkach zdrowy wiersz zostałby
                        # zaparkowany i cicho przestał blokować watermark.
                        # Licznik znaczy „tyle KOLEJNYCH PRÓB IMPORTU tego
                        # wiersza padło", a faza, która się wywróciła, nie
                        # podjęła żadnej próby. Reguła „nieobecny ⇒ zapomnij"
                        # z `_next_quarantine` kluczuje na DOWODZIE SUKCESU
                        # (wiersz się zaimportował); wywrotka nie jest dowodem
                        # niczego, więc ta reguła jej nie dotyczy.
                        carried: Optional[dict[str, Any]] = None
                        parked_now: list[str] = []
                        try:
                            prev_row = await _get_state(db, name)
                            prev_crash_stats = (
                                prev_row.stats if prev_row is not None else None
                            ) or {}
                            maybe = prev_crash_stats.get("quarantine")
                            if isinstance(maybe, dict) and maybe:
                                carried = maybe
                                parked_now = _parked_refs(
                                    maybe, settings.TRAFFIT_MAX_ROW_ATTEMPTS
                                )
                        except Exception:  # noqa: BLE001 — odczyt best-effort
                            # Degradacja do stanu sprzed poprawki (tracimy
                            # licznik), nie do braku zapisu statusu fazy.
                            carried, parked_now = None, []
                        if carried:
                            crash_stats["quarantine"] = carried
                            # `quarantined` WYLICZANE z `carried`, nie przenoszone
                            # osobno — dwa lepkie klucze to druga okazja do
                            # rozjazdu między listą a licznikiem, z którego ona
                            # wynika.
                            if parked_now:
                                crash_stats["quarantined"] = parked_now
                        await _upsert_state(
                            db,
                            name,
                            last_run_started_at=phase_started,
                            last_run_finished_at=datetime.now(timezone.utc),
                            last_status="error",
                            stats=crash_stats,
                        )

                # Bieg, który nie wykonał ŻADNEJ fazy, nie może zgłaszać sukcesu.
                # `validate_phases` odrzuca to na wejściu API, ale ta funkcja ma
                # też wywołujących spoza endpointu (pętla, testy, przyszły CLI),
                # a fazy warunkowe mogą przybyć — kolejna równie cicha ścieżka do
                # „started" po biegu, który nic nie zrobił.
                if selected is not None and executed == 0:
                    logger.warning(
                        "Traffit run matched NO phases (requested: %s; active: %s)",
                        ", ".join(sorted(selected)),
                        ", ".join(active_phase_names()),
                    )
                    return {
                        "skipped": True,
                        "reason": "no_phases_matched",
                        "mode": mode,
                        "requested_phases": sorted(selected),
                        "active_phases": list(active_phase_names()),
                    }

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
                #
                # …ale TYLKO gdy bieg objął cały plan. Bieg zawężony przez
                # `phases=` przesunąłby `__daily__` ponad danymi, których nie
                # dotknął — kolejna delta liczyłaby `since` od tego momentu
                # i pominięte rekordy wypadłyby z okna na zawsze. `__full__`
                # kłamałby o zakończonym reconcile i uciszał sondę świeżości.
                if selected is None:
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
                else:
                    logger.info(
                        "Traffit partial run (%s) — markers NOT advanced; phases: %s",
                        mode,
                        ", ".join(sorted(selected)),
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
                sweep_pending = await full_sweep_pending(db)
            daily_done = daily.last_run_finished_at if daily else None
            full_done = full.last_run_finished_at if full else None

            if should_run_full(
                now,
                full_done,
                settings.TRAFFIT_SYNC_FULL_WEEKDAY,
                settings.TRAFFIT_SYNC_HOUR_UTC,
                sweep_pending=sweep_pending,
            ):
                logger.info(
                    "Traffit: full reconcile is due (%s)",
                    "catching up — sweep cursor still set"
                    if sweep_pending
                    else "weekly schedule",
                )
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
