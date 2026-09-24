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
from app.services.traffit.client import TraffitClient, TraffitConfig
from app.services.traffit.importer import PhaseProgress, TraffitImporter
from app.services import loop_heartbeat

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
    attempt_pending: bool = False,
) -> bool:
    """Daily delta is due?

    First run (no watermark) fires immediately after enabling, regardless of
    hour. Afterwards it runs only at/after ``hour_utc`` and only once the gap
    since the last finish is large enough (prevents same-day re-runs and
    Coolify-redeploy re-triggers).

    ``attempt_pending`` (audyt 22.09 r2, INTG-01): poprzednia próba została
    przerwana (deploy zabił kontener w trakcie) i jej ślad jest świeży — bieg
    jest należny od razu, niezależnie od godziny, i WZNOWI się od faz, których
    przerwana próba nie skończyła.
    """
    if attempt_pending:
        return True
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
            "last_run_finished_at, last_status, stats, cursor_payload "
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


# ── Stan PRÓBY biegu (audyt 22.09 r2, INTG-01/02) ────────────────────────────
#
# Coolify restartuje kontener przy każdym pushu na main (25–35 deployów
# dziennie), a pełny plan faz trwa dłużej niż odstęp między nimi. Do 22.09
# każda nowa próba zaczynała od `users` i nie docierała do `pipelines`:
# `__daily__` stał 39 h, a ruchy pipeline'u z 21–22.09 nie weszły wcale (KPI
# i Insights puste). Stan próby żyje w `cursor_payload['attempt']` wiersza
# znacznika (`__daily__`/`__full__`): kolejna próba z tą samą `since` pomija
# fazy, które poprzednia już skończyła, a `files_since` i watermark liczy od
# startu PIERWSZEJ próby — inaczej kandydaci dotknięci przed przerwaniem
# wypadali z zakresu plików/CV (INTG-02).
#
# Czyszczony na końcu KAŻDEGO biegu, który dobiegł końca (także z błędami),
# i przy wyjątku; NIE przy anulowaniu — to właśnie deploy.

_ATTEMPT_KEY = "attempt"


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def attempt_from_payload(payload: Any) -> Optional[dict[str, Any]]:
    """Wyciąga stan próby z `cursor_payload` (odporne na śmieci w JSONB)."""
    if not isinstance(payload, dict):
        return None
    attempt = payload.get(_ATTEMPT_KEY)
    return attempt if isinstance(attempt, dict) else None


def attempt_is_fresh(
    attempt: Optional[dict[str, Any]], now_utc: datetime, resume_hours: int
) -> bool:
    """Czy ślad przerwanej próby jest na tyle świeży, żeby ją wznowić."""
    if not attempt:
        return False
    touched = _parse_iso(attempt.get("touched_at"))
    if touched is None:
        return False
    return (now_utc - touched) < timedelta(hours=max(0, int(resume_hours)))


def resumable_attempt(
    attempt: Optional[dict[str, Any]],
    *,
    since_iso: Optional[str],
    now_utc: datetime,
    resume_hours: int,
) -> Optional[tuple[datetime, set[str], set[str]]]:
    """(start pierwszej próby, fazy skończone, fazy z blokującymi błędami)
    albo None, gdy próby nie da się wznowić (inna `since`, stary ślad)."""
    if not attempt_is_fresh(attempt, now_utc, resume_hours):
        return None
    assert attempt is not None
    if attempt.get("since") != since_iso:
        return None
    first_start = _parse_iso(attempt.get("run_start"))
    if first_start is None:
        return None
    done = {str(p) for p in (attempt.get("done") or []) if isinstance(p, str)}
    held = {str(p) for p in (attempt.get("held") or []) if isinstance(p, str)}
    return first_start, done, held


async def _load_attempt(db, marker: str) -> Optional[dict[str, Any]]:
    row = await _get_state(db, marker)
    if row is None:
        return None
    return attempt_from_payload(getattr(row, "cursor_payload", None))


async def _save_attempt(db, marker: str, attempt: dict[str, Any]) -> None:
    """UPSERT samego klucza `attempt` w `cursor_payload` wiersza znacznika."""
    await db.execute(
        text(
            """
            INSERT INTO traffit_sync_state
                (phase, cursor_payload, created_at, updated_at)
            VALUES (:p, jsonb_build_object('attempt', CAST(:a AS JSONB)), NOW(), NOW())
            ON CONFLICT (phase) DO UPDATE SET
                cursor_payload = COALESCE(traffit_sync_state.cursor_payload,
                                          '{}'::jsonb)
                                 || jsonb_build_object('attempt', CAST(:a AS JSONB)),
                updated_at = NOW()
            """
        ),
        {"p": marker, "a": json.dumps(attempt)},
    )
    await db.commit()


async def _clear_attempt(db, marker: str) -> None:
    await db.execute(
        text(
            """
            UPDATE traffit_sync_state
               SET cursor_payload = NULLIF(cursor_payload - 'attempt', '{}'::jsonb),
                   updated_at = NOW()
             WHERE phase = :p AND cursor_payload -> 'attempt' IS NOT NULL
            """
        ),
        {"p": marker},
    )
    await db.commit()


# ── Atrybucja błędów w fazach spoza importera ────────────────────────────────


def _attributed_progress(
    stats: dict[str, Any], *, phase: str, verb: str, entity: str, detail: str
) -> PhaseProgress:
    """``PhaseProgress`` użyty WYŁĄCZNIE jako akumulator atrybucji błędów.

    Faza `candidates_cv_fields` nie idzie przez importera Traffita,
    więc jej statystyki to zwykłe słowniki, a nie ``PhaseProgress``. Do
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
    # Nazwa klasy wyjątku (nie treść — ta bywa cytatem z CV) na końcu próbki.
    error_types = stats.get("error_types") or {}
    for row_id in error_ids:
        kind = error_types.get(row_id)
        suffix = f" ({kind})" if kind else ""
        progress.add_error(f"{verb} {entity} id={row_id}: {detail}{suffix}")
    # Źródło o starym kształcie statystyk (bez ``error_ids``) degraduje się do
    # stanu sprzed poprawki — błędy nieprzypisane, watermark stoi — zamiast
    # wymuszać zmianę kontraktu wszystkich źródeł naraz.
    leftover = int(stats.get("errors") or 0) - len(error_ids)
    if leftover > 0:  # defensywnie: licznik ma zostać uczciwy
        progress.errors += leftover
    return progress


class _CvFieldsPhaseResult:
    """Adapter stats `backfill_cv_fields` na kontrakt fazy (as_dict/errors/*_at).

    Atrybucja błędów delegowana do `_attributed_progress`. Świadomie NIE
    zwracamy całego ``PhaseProgress.as_dict()``: ten emituje STAŁY zestaw
    kluczy, a zero, którego nikt nie mierzył, czyta się w ``/sync/status`` jak
    zmierzone zero.
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


class _CvTextPhaseResult:
    """Adapter ``cv_text_backfill.run_backfill`` na kontrakt fazy.

    CELOWO ``errors = 0``: nieudany plik dostaje znacznik w
    ``cv_extracted_data._cv_text_extraction`` i wraca w następnym biegu
    (``download_failed``/``error``) albo zostaje opisany jako beznadziejny
    (``junk``/``legacy_doc``) — nic tu nie wymaga wstrzymywania watermarku, a
    wstrzymany watermark i tak niczego by w tej fazie nie ponowił.
    """

    def __init__(
        self, stats: dict[str, Any], started_at: datetime, finished_at: datetime
    ):
        self._stats = stats
        self.started_at = started_at
        self.finished_at = finished_at
        self.errors = 0

    def as_dict(self) -> dict[str, Any]:
        return dict(self._stats)


async def _cv_text_phase() -> _CvTextPhaseResult:
    """Tekst z CV, które import już zapisał, a których nikt jeszcze nie przeczytał.

    Fazy ``candidates_cv``/``candidate_files`` pobierają pliki, ale TEKSTU
    z nich nie wyciąga żadna faza: robił to jednorazowy skrypt
    ``backfill_cv_text`` (10.08.2026), więc każde CV pobrane później zostawało
    niewidoczne dla wyszukiwania słów kluczowych. Zmierzone 22.09.2026: 3 731
    kandydatów z Traffita z plikiem PDF i bez tekstu, do tego 3 320 z PDF-em
    zapisanym pod nazwą ``.docx`` (oznaczonych ``empty`` przed rozpoznawaniem
    formatu po bajtach). Obie grupy Traffit przeszukuje, NEXUS nie.

    Bez ``since``: backfill bierze wiersze bez tekstu w kolejności id, a wiersz
    z odczytanym tekstem albo znacznikiem terminalnym sam wypada z zakresu, więc
    kolejne noce kończą zaległość. Budżet ``TRAFFIT_SYNC_CV_TEXT_LIMIT`` na bieg
    (ekstrakcja lokalna, bez AI; OCR tylko dla skanów).

    Drugi przebieg z tym samym budżetem czyta ponownie CV SKLEJONE (słowa bez
    przerw, 1 581 na produkcji 23.09.2026) — ``run_backfill(glued=True)``.
    """
    from app.services.cv_text_backfill import run_backfill

    started = datetime.now(timezone.utc)
    limit = max(1, int(settings.TRAFFIT_SYNC_CV_TEXT_LIMIT))
    stats = await run_backfill(commit=True, limit=limit)
    glued = await run_backfill(commit=True, limit=limit, glued=True)
    summary = stats.as_dict()
    summary["glued"] = glued.as_dict()
    return _CvTextPhaseResult(summary, started, datetime.now(timezone.utc))


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
    is the start of the FIRST attempt of this run (INTG-02 — an interrupted
    attempt resumes with the same cutoff), not the data ``since``: the candidates phase has just
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
        # Audyt 22.09 r2 (INTG-01): `jobs` i `pipelines` ZARAZ po kandydatach.
        # Ruchy pipeline'u zasilają KPI, Insights, konkursy i przepięcia —
        # 21–22.09 dzienna delta w ogóle do nich nie dochodziła (deploy zabijał
        # próbę w fazach plików i 35-minutowym Cortexie, usuniętym 23.09.2026).
        # `pipelines` wymaga
        # `jobs` (FK), a obie są szybkie przy delcie ogonowej (INTG-03).
        ("jobs", lambda: importer.import_jobs(since=since)),
        ("pipelines", lambda: importer.import_pipelines(since=since)),
        # Pliki CV zaraz za ruchami: CV nowych kandydatów nie czeka na fazy
        # wzbogacania, które i tak czytają zapisane CV.
        ("candidates_cv", lambda: importer.import_candidates_cv(since=files_since)),
        ("candidate_files", lambda: importer.import_candidate_files(since=files_since)),
        # Tekst z pobranych CV — zanim pola z CV zaczną go czytać.
        ("candidates_cv_text", _cv_text_phase),
        (
            "candidate_activities",
            lambda: importer.import_candidate_activities(since=since),
        ),
        ("candidate_sources", lambda: importer.import_candidate_sources(since=since)),
        ("talents", importer.import_talents),
        (
            "candidates_enrich_names",
            lambda: importer.enrich_missing_names(since=files_since),
        ),
        ("candidates_cv_fields", lambda: _cv_fields_phase(files_since)),
        # Ostatnia i wyłącznie raportowa — nic nie zapisuje, nic nie blokuje.
        ("reconcile", lambda: _reconcile_phase(importer)),
    ]


# Fazy WZBOGACANIA: wyprowadzają dane z tego, co Nexus JUŻ ma (zapisane CV),
# a nie z okna zmian Traffita wyznaczanego przez `__daily__` — imię z CV,
# pola strukturalne CV. DORADCZE są wyłącznie ich błędy
# WIERSZY. Wstrzymany watermark ponawia te fazy — kolejna delta importuje
# szersze okno, faza `candidates` stempluje `updated_at` tych kandydatów na
# nowo, więc trafiają ponownie w zakres `files_since` — ale wiersz trwale
# zepsuty pada przy każdym ponowieniu. Kwarantanna go nie ratuje — pełny bieg
# przemiata budżetowany wycinek, więc wiersz jest oglądany raz na przebieg,
# a `_next_quarantine` zapomina go następnej nocy (nieobecny = „zaimportował
# się") i licznik nigdy nie dobija do limitu. Tak jeden nieparsowalny CV
# (kandydat 287387) zamroził `__daily__` od 2026-09-08. Błędy wierszy ZOSTAJĄ
# widoczne — status fazy `errors`, próbki z klasą wyjątku, referencje
# i kwarantanna w `/sync/status` — tylko nie blokują watermarku.
#
# WYWROTKA fazy (wyjątek poza pętlą wierszy, np. nieudany commit) blokuje
# watermark jak w każdej innej fazie: nie wiadomo, które wiersze przeszły,
# a dla `candidates_cv_fields` wstrzymany watermark jest JEDYNYM ponowieniem
# — pełny bieg ją pomija, delta widzi tylko `updated_at >= run_start`.
ADVISORY_PHASES = frozenset({"candidates_enrich_names", "candidates_cv_fields"})


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
    "jobs",
    "pipelines",
    "candidates_cv",
    "candidate_files",
    "candidates_cv_text",
    "candidate_activities",
    "candidate_sources",
    "talents",
    "candidates_enrich_names",
    "candidates_cv_fields",
    "reconcile",
)


# ── Świeżość PER FAZA (INT-09) ───────────────────────────────────────────────
#
# `checks.traffit` w `/api/health` czyta WYŁĄCZNIE `__daily__` i to jest sonda
# świeżości BIEGU, nie kompletności: `healthy` znaczy „nocna delta się kończy",
# a nie „każda faza widziała ogon". Faza budżetowana, która od tygodni nie
# przesuwa kursora, albo faza doradcza padająca na tym samym wierszu, wygląda
# w health identycznie jak zdrowa — dokładnie tak luka w plikach przeżyła
# miesiące. Werdykt per faza w `/sync/status` domyka to bez zmiany sondy.
#
# Progi zależą od typu fazy, bo każdy typ ma INNE „normalne" opóźnienie:
# - zwykła faza biegnie w każdej nocnej delcie → 36 h (lustro `checks.traffit`);
# - faza kursorowana/budżetowana też biegnie co noc, ale przemiata wycinek
#   i bywa ucięta deployem w połowie → luźniej, 72 h;
# - kadencja pełna (`__full__`) to tydzień → tydzień + doba zapasu
#   (Coolify restartuje kontener przy pushu, a pełny bieg trwa godziny);
# - tygodniowy pomiar jakości wyszukiwania (`weekly_eval`) zapisuje swój stan
#   w tej samej tabeli, więc trafia do tej samej odpowiedzi — też tydzień.
#   Z progiem 36 h lądował w `phases_stale` pięć dni w tygodniu (odczyt
#   produkcji 15.09), czyli lista uczyła ignorować siebie samą;
# - fazy DORADCZE (`ADVISORY_PHASES`) nie blokują watermarku, więc ich
#   opóźnienie nie zatrzymuje importu — werdykt `advisory`, nie `stale`,
#   i nie liczą się do `phases_stale`.

_DAILY_PHASE_STALE_HOURS = 36
_CURSORED_PHASE_STALE_HOURS = 72
_FULL_CADENCE_STALE_HOURS = 8 * 24

# Fazy z kursorem wznawiania (patrz CLAUDE.md „Wznawialność"): budżetowane po
# `after_id` oraz stronicowane po numerze strony.
_CURSORED_PHASES = frozenset(
    _BUDGETED_SWEEP_PHASES + ("candidates", "candidate_activities", "pipelines")
)
# Nazwa stanu wprost, nie import z `app.tasks.weekly_eval`: ten moduł jest
# importowany przy starcie, a test pilnuje, że stała się nie rozjechała.
WEEKLY_EVAL_STATE_PHASE = "weekly_eval"
_FULL_CADENCE_PHASES = frozenset({FULL_MARKER, WEEKLY_EVAL_STATE_PHASE})

FRESHNESS_FRESH = "fresh"
FRESHNESS_STALE = "stale"
FRESHNESS_NEVER = "never"
FRESHNESS_ADVISORY = "advisory"


def phase_stale_after(phase: str) -> timedelta:
    """Próg świeżości dla fazy (albo znacznika) — po typie, nie po nazwie."""
    if phase in _FULL_CADENCE_PHASES:
        return timedelta(hours=_FULL_CADENCE_STALE_HOURS)
    if phase in _CURSORED_PHASES:
        return timedelta(hours=_CURSORED_PHASE_STALE_HOURS)
    return timedelta(hours=_DAILY_PHASE_STALE_HOURS)


def phase_freshness(
    phase: str, *, finished_at: Optional[datetime], now: datetime
) -> str:
    """``fresh`` | ``stale`` | ``never`` | ``advisory`` dla jednego wiersza stanu.

    Czysta funkcja — o świeżości, nie o wyniku: `last_status` jedzie obok
    w tej samej odpowiedzi i mówi o błędach, ten werdykt mówi o CZASIE.
    `never` = wiersz bez końca biegu (faza nigdy nie doszła do końca).
    """
    if finished_at is None:
        return FRESHNESS_NEVER
    overdue = (now - finished_at) > phase_stale_after(phase)
    if phase in ADVISORY_PHASES:
        return FRESHNESS_ADVISORY if overdue else FRESHNESS_FRESH
    return FRESHNESS_STALE if overdue else FRESHNESS_FRESH


def annotate_freshness(states: list[dict[str, Any]], now: datetime) -> list[str]:
    """Dopisz `freshness` i `stale_after_hours` do wierszy `/sync/status`;
    zwróć posortowane nazwy faz z werdyktem `stale` (zbiorcze `phases_stale`).

    Wiersze bez końca biegu (`never`) NIE trafiają do `phases_stale`: faza,
    która nigdy nie pobiegła, to stan świeżo włączonej instalacji, nie regres —
    a lista ma być tym, na co operator reaguje.
    """
    stale: list[str] = []
    for state in states:
        phase = str(state.get("phase") or "")
        raw = state.get("last_run_finished_at")
        finished_at = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
        if finished_at is not None and finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)
        verdict = phase_freshness(phase, finished_at=finished_at, now=now)
        state["freshness"] = verdict
        state["stale_after_hours"] = int(
            phase_stale_after(phase).total_seconds() // 3600
        )
        if verdict == FRESHNESS_STALE:
            stale.append(phase)
    return sorted(stale)


def active_phase_names() -> tuple[str, ...]:
    """Fazy, które plan wyprodukuje PRZY OBECNYCH USTAWIENIACH.

    `PHASE_NAMES` to słownik pisowni; ta funkcja mówi, co realnie pobiegnie.
    Dziś plan nie ma faz warunkowych (jedyna — `cortex` — zniknęła 23.09.2026),
    więc obie listy są równe. Rozdzielenie zostaje: faza warunkowa wyłączona
    ustawieniem przechodziłaby walidację pisowni, a filtr nie uruchomiłby
    NICZEGO i bieg raportowałby sukces.
    """
    return PHASE_NAMES


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
    # aktywnej i wyłączonej fazy ma sens i ma pobiec.
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
        # 0325: ruchy ofert „prowadzonych w NEXUSIE" pominięte przez fazę pipelines.
        "skipped_managed",
        # 18.09.2026: intencje przeindeksowania zapisane przez fazę `jobs`.
        "index_intents",
        # Audyt 22.09 r2 (INTG-03): rekrutacje bez zmian i wpisy historii
        # sprzed `since` pominięte przez deltę ogonową.
        "unchanged",
        "skipped_before_since",
        # Audyt 22.09 r2 (DATA-01): zdarzenia rekrutacji dla automatów.
        "job_events",
        # Audyt 22.09 r2 (REC-01): przepięcia z etapów wstawionych przez import.
        "reassigned",
        # 23.09.2026: rekruterzy dopełnieni z detalu `/recruitments/{id}`.
        "recruiter_resolved",
        "recruiter_detail_failed",
        # 24.09.2026: archiwum z Traffita i kategorie nowych rekrutacji.
        "archived",
        "categorised",
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
    była DZIEWIĄTĄ z piętnastu faz (do 22.09.2026 — dziś idzie zaraz po `candidates`), a `candidates` przed nią trwa godzinami:
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

                # Wznowienie przerwanej próby (INTG-01/02). Tylko pełny plan —
                # bieg częściowy (`phases=`) nie jest próbą znacznika i nie
                # może ani wznawiać, ani zostawiać jej śladu.
                attempt_marker = DAILY_MARKER if mode == "delta" else FULL_MARKER
                since_iso = since.isoformat() if since else None
                first_start = run_start
                done_before: set[str] = set()
                held_before: set[str] = set()
                attempt: Optional[dict[str, Any]] = None
                if selected is None:
                    resumed = resumable_attempt(
                        await _load_attempt(db, attempt_marker),
                        since_iso=since_iso,
                        now_utc=run_start,
                        resume_hours=settings.TRAFFIT_SYNC_ATTEMPT_RESUME_HOURS,
                    )
                    if resumed is not None:
                        first_start, done_before, held_before = resumed
                        logger.info(
                            "Traffit %s: resuming interrupted attempt started %s; "
                            "skipping finished phases: %s",
                            mode,
                            first_start.isoformat(),
                            ", ".join(sorted(done_before)) or "-",
                        )
                    attempt = {
                        "since": since_iso,
                        "run_start": first_start.isoformat(),
                        "touched_at": run_start.isoformat(),
                        "done": sorted(done_before),
                        "held": sorted(held_before),
                    }
                    await _save_attempt(db, attempt_marker, attempt)

                # CV/files re-fetch only candidates this run actually touched
                # (Traffit-changed → upserted with updated_at >= first_start).
                # Full reconcile uses None (its own "missing files" gate).
                files_since = first_start if mode == "delta" else None

                importer = TraffitImporter(traffit, db, dry_run=False, batch_size=100)

                executed = 0
                for name, factory in _phase_plan(importer, since, files_since):
                    if selected is not None and name not in selected:
                        continue
                    if name in done_before:
                        results[name] = {"resumed": "done_in_previous_attempt"}
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
                        if blocking and name in ADVISORY_PHASES:
                            # Row errors of an enrichment phase: counted and
                            # shown, but under a key the global gate below does
                            # not read — see `ADVISORY_PHASES`.
                            summary["advisory_errors"] = blocking
                        elif blocking:
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
                        if attempt is not None:
                            # Faza doszła do końca — kolejna próba jej nie
                            # powtórzy. Blokujące błędy wierszy pamiętamy
                            # osobno, żeby watermark nadal stał.
                            attempt["done"] = sorted(set(attempt["done"]) | {name})
                            if blocking and name not in ADVISORY_PHASES:
                                attempt["held"] = sorted(set(attempt["held"]) | {name})
                            attempt["touched_at"] = datetime.now(
                                timezone.utc
                            ).isoformat()
                            await _save_attempt(db, attempt_marker, attempt)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Traffit phase %s failed", name)
                        # A crash holds the watermark in EVERY phase, the
                        # enrichment ones included — see `ADVISORY_PHASES`.
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
                # Row errors of enrichment phases are filed under
                # `advisory_errors`, so they never gate it; a crash (`error`)
                # does, in every phase — `ADVISORY_PHASES`.
                any_error = bool(held_before) or any(
                    isinstance(v, dict) and ("error" in v or v.get("blocking_errors"))
                    for v in results.values()
                )
                advisory_failures = sorted(
                    phase_name
                    for phase_name, v in results.items()
                    if isinstance(v, dict) and v.get("advisory_errors")
                )
                if advisory_failures:
                    logger.warning(
                        "Traffit %s: enrichment phase(s) with row errors, not "
                        "holding the watermark: %s",
                        mode,
                        ", ".join(advisory_failures),
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
                # Od startu PIERWSZEJ próby (INTG-02): wznowiona próba nie
                # może przesunąć watermarku ponad okres, w którym poprzednia
                # próba importowała już fazy przed przerwaniem.
                watermark = first_start if not any_error else None

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
                        last_run_started_at=first_start,
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
                if attempt is not None:
                    # Bieg dobiegł końca — próba zamknięta, następny bieg
                    # zaczyna od zera (niezależnie od błędów faz).
                    await _clear_attempt(db, attempt_marker)

        from app.core.operation_telemetry import record_job_outcome

        if selected is None:
            record_job_outcome("traffit_sync", status == "ok", interval_seconds=86400)
            # 0343: import mógł dowieźć serię „Zatrudniony" jednego konta (≥ 10
            # par w dniu, bez CV wysłane) — taka seria nie jest placementem.
            # Własna sesja, nigdy nie rzuca: statystyka nie wywraca importu.
            from app.services.placement_exclusions import run_detection_safely

            await run_detection_safely(f"traffit_{mode}")
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
            **({"advisory_failures": advisory_failures} if advisory_failures else {}),
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

    # MON-04: tick na początku iteracji; cisza dłuższa niż próg = „stalled”.
    beat = loop_heartbeat.register(
        "traffit_sync", max_silence_seconds=check_interval + 24 * 3600
    )
    while True:
        beat.tick()
        try:
            if not settings.TRAFFIT_SYNC_ENABLED:
                await asyncio.sleep(check_interval)
                continue

            now = datetime.now(timezone.utc)
            resume_hours = settings.TRAFFIT_SYNC_ATTEMPT_RESUME_HOURS
            async with AsyncSessionLocal() as db:
                daily = await _get_state(db, DAILY_MARKER)
                full = await _get_state(db, FULL_MARKER)
                sweep_pending = await full_sweep_pending(db)
            daily_done = daily.last_run_finished_at if daily else None
            full_done = full.last_run_finished_at if full else None
            # INTG-01: przerwana próba (deploy) wznawia się przy najbliższym
            # ticku zamiast czekać do jutra albo zaczynać od `users`.
            full_attempt = attempt_is_fresh(
                attempt_from_payload(getattr(full, "cursor_payload", None)),
                now,
                resume_hours,
            )
            daily_attempt = attempt_is_fresh(
                attempt_from_payload(getattr(daily, "cursor_payload", None)),
                now,
                resume_hours,
            )

            if full_attempt:
                logger.info("Traffit: resuming an interrupted full reconcile")
                await run_traffit_sync("full")
            elif should_run_full(
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
            elif should_run_daily(
                now,
                daily_done,
                settings.TRAFFIT_SYNC_HOUR_UTC,
                attempt_pending=daily_attempt,
            ):
                logger.info("Traffit: daily delta is due")
                await run_traffit_sync("delta")
        except asyncio.CancelledError:
            logger.info("traffit_daily_sync_loop cancelled — shutting down")
            return
        except Exception:  # noqa: BLE001
            logger.exception("traffit_daily_sync_loop iteration failed")

        await asyncio.sleep(check_interval)
