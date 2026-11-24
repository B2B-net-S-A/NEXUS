"""Ręczne przebiegi z tras przy dwóch procesach web (24.11.2026).

Flaga ``running`` i postęp żyły w pamięci procesu, który bieg uruchomił: status
z drugiego procesu web mówił „nie biegnie” (import talent-radar: 404), a drugi
start szedł równolegle z pierwszym. Teraz bieg startuje przez
``manual_runs.start_exclusive`` i trzyma blokadę doradczą do końca, a status
czyta blokadę (``pg_locks``) i zapis w ``app_settings``.

Dwa procesy w jednym teście: blokady to zbiór ``held`` (podstawione
``cross_process_lock`` i ``lock_held``), ``app_settings`` to słownik, a drugi
proces to ``other_process``: pusta rezerwacja i świeża pamięć modułu na czas
bloku. Prawdziwe ``pg_locks`` sprawdza test z bazą na końcu pliku (CI).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.api import admin_candidates as ac
from app.api import admin_import as adm
from app.api import admin_job_board_cards as ajb
from app.api import admin_notes_insights as ani
from app.api import admin_order_mail as aom
from app.api import admin_recruitment_processes as arp
from app.api import admin_screening_note_backfill as asb
from app.api import admin_talent_pools as atp
from app.api import order_mail_queue as queue_api
from app.core import manual_runs, process_lock
from app.services import job_board_cards_to_proposals as conversion
from app.services import order_mail_ingest as svc
from app.services import screening_note_backfill as backfill
from app.services import talent_pool_backfill as tpb
from app.tasks import notes_insights_sync as nis

_DSN = "postgresql://example.invalid/talent_radar"
_ADMIN = SimpleNamespace(id=1)


class _NoSession:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def procs(monkeypatch):
    """Blokady i ``app_settings`` wspólne dla „obu procesów” testu."""
    held: set[str] = set()
    store: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_lock(name: str, item: int = 0):  # noqa: ARG001
        if name in held:
            yield False
            return
        held.add(name)
        try:
            yield True
        finally:
            held.discard(name)

    async def fake_lock_held(name: str, *, db: Any = None) -> bool:  # noqa: ARG001
        return name in held

    async def fake_save(key: str, value: dict[str, Any]) -> None:
        store[key] = json.loads(json.dumps(value, default=str))

    async def fake_load(key: str) -> dict[str, Any] | None:
        value = store.get(key)
        return dict(value) if isinstance(value, dict) else None

    monkeypatch.setattr(manual_runs.settings, "NEXUS_PROCESS_ROLE", "web")
    monkeypatch.setattr(manual_runs, "cross_process_lock", fake_lock)
    monkeypatch.setattr(manual_runs, "lock_held", fake_lock_held)
    monkeypatch.setattr(manual_runs, "save_snapshot", fake_save)
    monkeypatch.setattr(manual_runs, "load_snapshot", fake_load)
    monkeypatch.setattr(manual_runs, "SNAPSHOT_EVERY_SECONDS", 0.01)
    monkeypatch.setattr(ac, "_PROGRESS_POLL_SECONDS", 0.01)
    monkeypatch.setattr(ac, "AsyncSessionLocal", _NoSession)
    monkeypatch.setattr(arp, "AsyncSessionLocal", _NoSession)
    monkeypatch.setattr(ani.settings, "NOTES_INSIGHTS_SYNC_ENABLED", True)
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_INGEST_ENABLED", True)
    for job in (ac._JOB, ac._CC_JOB, ac._CV_FIELDS_JOB, ac._EXP_DATES_JOB, arp._JOB):
        job["running"] = False
    adm._TASKS.clear()
    manual_runs._reserved.clear()
    yield SimpleNamespace(held=held, store=store)
    manual_runs._reserved.clear()
    adm._TASKS.clear()


@contextmanager
def other_process(*states: tuple[dict, dict]) -> Iterator[None]:
    """Drugi proces web na czas bloku: pusta rezerwacja i świeża pamięć modułu."""
    reserved = set(manual_runs._reserved)
    manual_runs._reserved.clear()
    backups = [(state, dict(state)) for state, _fresh in states]
    for state, fresh in states:
        state.clear()
        state.update(fresh)
    try:
        yield
    finally:
        for state, backup in backups:
            state.clear()
            state.update(backup)
        manual_runs._reserved.update(reserved)


async def _until(check: Callable[[], Any], timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not check():
        assert loop.time() < deadline, "warunek nie spełnił się na czas"
        await asyncio.sleep(0.005)


# ── start_exclusive i blokada ────────────────────────────────────────────────


async def test_start_is_refused_while_another_process_holds_the_lock(procs):
    calls: list[int] = []

    async def run() -> None:
        calls.append(1)

    procs.held.add("x")
    assert await manual_runs.start_exclusive("x", run, label="test") is False
    await asyncio.sleep(0)
    assert calls == [] and not manual_runs.running_here("x")

    procs.held.discard("x")
    assert await manual_runs.start_exclusive("x", run, label="test") is True
    await _until(lambda: calls and not procs.held)
    assert calls == [1] and not manual_runs.running_here("x")


async def test_lock_is_held_for_the_whole_run_and_status_sees_it(procs):
    release = asyncio.Event()

    async def run() -> None:
        await release.wait()

    assert await manual_runs.start_exclusive("x", run, label="test")
    assert procs.held == {"x"}
    with other_process():
        assert await manual_runs.is_running("x")
        assert not await manual_runs.start_exclusive("x", run, label="test")
    release.set()
    await _until(lambda: not procs.held)
    assert not await manual_runs.is_running("x")


async def test_failed_lock_check_reaches_the_route_and_frees_the_name(
    procs, monkeypatch
):
    @asynccontextmanager
    async def broken(name: str, item: int = 0):  # noqa: ARG001
        raise OSError("baza niedostępna")
        yield True  # pragma: no cover

    async def run() -> None:
        raise AssertionError("bez blokady nic nie startuje")

    monkeypatch.setattr(manual_runs, "cross_process_lock", broken)
    with pytest.raises(OSError):
        await manual_runs.start_exclusive("x", run, label="test")
    assert not manual_runs.running_here("x")


async def test_single_process_role_needs_no_database(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("rola all nie pyta pg_locks")

    monkeypatch.setattr(manual_runs.settings, "NEXUS_PROCESS_ROLE", "all")
    monkeypatch.setattr(manual_runs, "lock_held", boom)
    manual_runs._reserved.clear()
    assert await manual_runs.is_running("x") is False


async def test_lock_is_reentrant_only_in_the_task_that_holds_it(monkeypatch):
    granted: set[tuple[int, int]] = set()
    connects = 0

    class _Conn:
        key: tuple[int, int] | None = None

        async def fetchval(self, _sql: str, ns: int, item: int) -> bool:
            if (ns, item) in granted:
                return False
            granted.add((ns, item))
            self.key = (ns, item)
            return True

        async def close(self) -> None:
            granted.discard(self.key)

    async def connect(*_a, **_k) -> _Conn:
        nonlocal connects
        connects += 1
        return _Conn()

    monkeypatch.setattr(process_lock.settings, "NEXUS_PROCESS_ROLE", "web")
    monkeypatch.setattr(process_lock.asyncpg, "connect", connect)

    async def other_task() -> bool:
        async with process_lock.cross_process_lock("x") as owned:
            return owned

    async with process_lock.cross_process_lock("x") as outer:
        async with process_lock.cross_process_lock("x") as inner:
            assert outer is True and inner is True
        assert connects == 1, "wejście drugi raz nie otwiera połączenia"
        assert await asyncio.create_task(other_task()) is False
    assert process_lock._holders == {}
    assert await asyncio.create_task(other_task()) is True


# ── drugi start przy trzymanej blokadzie = 409, nic nie startuje ─────────────


def _starts(monkeypatch, calls: list[str]) -> dict[str, tuple[str, Callable]]:
    """Trasa → (blokada, wywołanie); biegi podstawione, żeby liczyć starty."""

    def fake(label: str) -> Callable[..., Awaitable[None]]:
        async def run(*_a, **_k) -> None:
            calls.append(label)

        return run

    monkeypatch.setattr(adm, "_run_import", fake("import"))
    monkeypatch.setattr(atp, "run_membership_backfill", fake("talent_pools"))
    monkeypatch.setattr(ac, "_run_backfill", fake("names"))
    monkeypatch.setattr(ac, "_run_cc_backfill", fake("cc"))
    monkeypatch.setattr(ac, "_run_cv_fields_backfill", fake("cv_fields"))
    monkeypatch.setattr(ac, "_run_experience_dates_backfill", fake("exp_dates"))
    monkeypatch.setattr(arp, "_run_backfill", fake("processes"))
    monkeypatch.setattr(conversion, "run_apply", fake("job_board"))
    monkeypatch.setattr(backfill, "run_apply", fake("screening"))
    monkeypatch.setattr(ani, "_run_manual", fake("notes_insights"))
    monkeypatch.setattr(svc, "run_order_mail_ingest", fake("order_mail"))

    # Zapisy kart i arkuszy wymagają świeżej próby i ``expected`` — tu gotowe.
    async def fresh_dry_run(*_a, **_k) -> Any:
        return {"include_other_notes": False, "to_change": 5}

    async def five(*_a, **_k) -> int:
        return 5

    monkeypatch.setattr(conversion, "fresh_dry_run_exists", fresh_dry_run)
    monkeypatch.setattr(conversion, "count_targets", five)
    monkeypatch.setattr(backfill, "fresh_dry_run", fresh_dry_run)
    monkeypatch.setattr(asb.screening_note_sync, "other_notes_enabled", lambda: False)
    request = adm.ImportTalentRadarRequest(source_dsn=_DSN)
    return {
        "import": (
            adm._RUN,
            lambda: adm.start_import_talent_radar(None, req=request),
        ),
        "talent_pools": (
            tpb.RUN_NAME,
            lambda: atp.trigger_talent_pool_backfill(None, since=None, limit=None),
        ),
        "names": (
            ac._run_name(ac._NAMES_PROGRESS),
            lambda: ac.trigger_backfill_names(
                None, limit=None, prefer_llm=True, after_id=0
            ),
        ),
        "cc": (
            ac._run_name(ac._CC_PROGRESS),
            lambda: ac.trigger_backfill_cc(
                None, limit=None, only_missing=True, start_after_id=0, only_slug=[]
            ),
        ),
        "cv_fields": (
            ac._run_name(ac._CV_FIELDS_PROGRESS),
            lambda: ac.trigger_backfill_cv_fields(
                None, limit=None, after_id=0, dry_run=False, calibration_log=None
            ),
        ),
        "exp_dates": (
            ac._run_name(ac._EXP_DATES_PROGRESS),
            lambda: ac.trigger_backfill_experience_dates(
                None, limit=None, after_id=0, dry_run=False
            ),
        ),
        "processes": (
            arp._RUN,
            lambda: arp.trigger_process_backfill(
                None, limit_pairs=None, resync_stale=False
            ),
        ),
        "job_board": (
            conversion.run_name("convert"),
            lambda: ajb.convert_integration_cards(
                _ADMIN, dry_run=False, mode="convert", expected=5, job_ids=None, db=None
            ),
        ),
        "screening": (
            backfill.RUN_NAME,
            lambda: asb.screening_note_backfill(
                _ADMIN, dry_run=False, expected=5, include_other_notes=False, db=None
            ),
        ),
        "notes_insights": (
            nis.RUN_LOCK,
            lambda: ani.trigger_notes_insights_sync.__wrapped__(None, None),
        ),
        "order_mail_admin": (
            svc.INGEST_LOCK,
            lambda: aom.trigger_order_mail_sync(None, since_days=None),
        ),
        "order_mail_queue": (svc.INGEST_LOCK, lambda: queue_api.trigger_sync(None)),
    }


_ROUTES = [
    "import",
    "talent_pools",
    "names",
    "cc",
    "cv_fields",
    "exp_dates",
    "processes",
    "job_board",
    "screening",
    "notes_insights",
    "order_mail_admin",
    "order_mail_queue",
]


@pytest.mark.parametrize("route", _ROUTES)
async def test_second_start_while_other_process_runs_is_409(procs, monkeypatch, route):
    calls: list[str] = []
    lock, start = _starts(monkeypatch, calls)[route]
    procs.held.add(lock)  # bieg trwa w pierwszym procesie

    with pytest.raises(HTTPException) as exc:
        await start()
    assert exc.value.status_code == 409
    for _ in range(5):
        await asyncio.sleep(0)
    assert calls == [], "odmowa nie może uruchomić drugiego biegu"
    assert not manual_runs.running_here(lock)
    assert adm._TASKS == {}, "odrzucony import nie zostawia zadania"


@pytest.mark.parametrize("route", _ROUTES)
async def test_free_lock_starts_exactly_one_run(procs, monkeypatch, route):
    calls: list[str] = []
    lock, start = _starts(monkeypatch, calls)[route]

    response = await start()
    if isinstance(response, adm.TaskStatus):
        assert response.status in {"queued", "running"}
    else:
        assert response["status"] == "started"
    await _until(lambda: calls and not procs.held)
    assert len(calls) == 1 and not manual_runs.running_here(lock)


# ── status z drugiego procesu (czysta pamięć) pokazuje bieg z pierwszego ─────


async def test_cc_status_in_other_process_shows_the_running_backfill(
    procs, monkeypatch
):
    release = asyncio.Event()

    async def backfill_ccs(db, *, progress, **_kw):
        progress.update(processed=60, assigned=55, last_id=4242)
        await release.wait()
        return progress

    monkeypatch.setattr(ac, "backfill_candidate_ccs", backfill_ccs)
    await ac.trigger_backfill_cc(
        None, limit=None, only_missing=True, start_after_id=0, only_slug=[]
    )
    await _until(
        lambda: (
            (procs.store.get("admin_backfill_progress:cc") or {}).get("processed") == 60
        )
    )

    with other_process((ac._CC_JOB, {"running": False})):
        status = await ac.backfill_cc_status(None)
        assert status["running"] is True
        assert (status["processed"], status["assigned"], status["last_id"]) == (
            60,
            55,
            4242,
        )

    release.set()
    await _until(lambda: not procs.held)
    with other_process((ac._CC_JOB, {"running": False})):
        status = await ac.backfill_cc_status(None)
    assert status["running"] is False
    assert status["saved_progress"]["processed"] == 60


async def test_import_status_answers_from_other_process(procs, monkeypatch):
    release = asyncio.Event()

    async def phases(tid: str, _req: Any) -> None:
        adm._set(tid, progress={"candidates": {"processed": 7}})
        await release.wait()
        adm._set(tid, status="done", finished_at="2026-11-24T12:00:00+00:00")

    monkeypatch.setattr(adm, "_import_phases", phases)
    task = await adm.start_import_talent_radar(
        None, req=adm.ImportTalentRadarRequest(source_dsn=_DSN)
    )
    key = adm._LAST_TASK_KEY
    await _until(lambda: (procs.store.get(key) or {}).get("progress"))

    with other_process((adm._TASKS, {})):
        status = await adm.get_import_talent_radar_status(task.task_id, None)
        assert status.status == "running"
        assert status.progress == {"candidates": {"processed": 7}}
        listed = await adm.list_import_tasks(None)
        assert [t.task_id for t in listed] == [task.task_id]
        with pytest.raises(HTTPException) as exc:
            await adm.start_import_talent_radar(
                None, req=adm.ImportTalentRadarRequest(source_dsn=_DSN)
            )
        assert exc.value.status_code == 409
        assert adm._TASKS == {}

    release.set()
    await _until(lambda: not procs.held)
    with other_process((adm._TASKS, {})):
        status = await adm.get_import_talent_radar_status(task.task_id, None)
    assert status.status == "done"


async def test_saved_running_import_without_live_lock_is_interrupted(procs):
    procs.store[adm._LAST_TASK_KEY] = {
        "task_id": "abc123",
        "kind": "import_talent_radar",
        "status": "running",
        "started_at": "2026-11-24T10:00:00+00:00",
        "finished_at": None,
        "progress": {},
        "error": None,
    }
    status = await adm.get_import_talent_radar_status("abc123", None)
    assert status.status == "error" and "przerwany" in status.error
    with pytest.raises(HTTPException) as exc:
        await adm.get_import_talent_radar_status("other", None)
    assert exc.value.status_code == 404


def _saved_import(task_id: str, status: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "kind": "import_talent_radar",
        "status": status,
        "started_at": "2026-11-24T10:00:00+00:00",
        "finished_at": None,
        "progress": {},
        "error": None,
    }


async def test_run_finishing_during_the_read_is_not_called_interrupted(
    procs, monkeypatch
):
    """Pierwszy proces kończy bieg między odczytem zapisu a sprawdzeniem blokady.

    Bieg zapisuje stan końcowy, zanim zwolni blokadę, więc kolejność „najpierw
    blokada, potem zapis” nigdy nie da „przerwany” dla biegu, który się udał
    (odwrotna dawała końcowy status błędu i ekran importu przestawał odpytywać).
    """
    key = adm._LAST_TASK_KEY
    procs.held.add(adm._RUN)
    procs.store[key] = _saved_import("abc123", "running")
    load = manual_runs.load_snapshot

    async def load_then_finish(k: str) -> dict[str, Any] | None:
        value = await load(k)
        procs.store[k] = _saved_import("abc123", "done")
        procs.held.discard(adm._RUN)
        return value

    monkeypatch.setattr(manual_runs, "load_snapshot", load_then_finish)
    assert (await adm.get_import_talent_radar_status("abc123", None)).status == (
        "running"
    )
    assert (await adm.get_import_talent_radar_status("abc123", None)).status == ("done")


async def test_run_starting_during_the_read_is_not_called_interrupted(
    procs, monkeypatch
):
    load = manual_runs.load_snapshot

    async def start_then_load(k: str) -> dict[str, Any] | None:
        # Drugi proces startuje między sprawdzeniem blokady a odczytem zapisu.
        procs.held.add(adm._RUN)
        procs.store[k] = _saved_import("new123", "running")
        return await load(k)

    monkeypatch.setattr(manual_runs, "load_snapshot", start_then_load)
    status = await adm.get_import_talent_radar_status("new123", None)
    assert status.status == "running"


async def test_process_backfill_status_from_other_process(procs, monkeypatch):
    release = asyncio.Event()

    async def run(db, *, progress, **_kw):
        progress.update(total_pairs=100, pairs_seen=12, created=10)
        await release.wait()

    monkeypatch.setattr(arp, "backfill_recruitment_processes", run)
    await arp.trigger_process_backfill(None, limit_pairs=None, resync_stale=False)
    key = arp._PROGRESS_KEY
    await _until(lambda: (procs.store.get(key) or {}).get("pairs_seen") == 12)

    with other_process((arp._JOB, {"running": False})):
        status = await arp.process_backfill_status(None)
        assert status["running"] is True
        assert (status["total_pairs"], status["pairs_seen"]) == (100, 12)

    release.set()
    await _until(lambda: not procs.held)
    with other_process((arp._JOB, {"running": False})):
        status = await arp.process_backfill_status(None)
    assert status["running"] is False and status["finished_at"]


async def test_process_status_never_shows_a_stop_without_finish(procs, monkeypatch):
    key = arp._PROGRESS_KEY
    procs.held.add(arp._RUN)
    procs.store[key] = {"running": True, "pairs_seen": 12, "finished_at": None}
    load = manual_runs.load_snapshot

    async def load_then_finish(k: str) -> dict[str, Any] | None:
        value = await load(k)
        procs.store[k] = {
            "running": False,
            "pairs_seen": 20,
            "finished_at": "2026-11-24T12:00:00+00:00",
        }
        procs.held.discard(arp._RUN)
        return value

    monkeypatch.setattr(manual_runs, "load_snapshot", load_then_finish)
    with other_process((arp._JOB, {"running": False})):
        status = await arp.process_backfill_status(None)
    assert status["running"] is True and status["pairs_seen"] == 12


async def test_talent_pool_status_from_other_process(procs, monkeypatch):
    release = asyncio.Event()

    async def run(**_kw) -> dict:
        await release.wait()
        return {}

    monkeypatch.setattr(atp, "run_membership_backfill", run)
    monkeypatch.setattr(tpb, "_last_run", {})
    await atp.trigger_talent_pool_backfill(None, since=None, limit=None)
    procs.store[tpb.LAST_RUN_KEY] = {"added": 3, "committed": True}

    with other_process():
        status = await atp.talent_pool_backfill_status(None)
    assert status == {"running": True, "last_run": {"added": 3, "committed": True}}
    release.set()
    await _until(lambda: not procs.held)
    assert (await atp.talent_pool_backfill_status(None))["running"] is False


async def test_statuses_see_a_run_held_by_another_process(procs, monkeypatch):
    async def no_setting(_db: Any, _key: str) -> None:
        return None

    monkeypatch.setattr(conversion, "_read_setting", no_setting)
    monkeypatch.setattr(backfill, "_read_setting", no_setting)
    procs.held.update(
        {conversion.run_name("delete"), backfill.RUN_NAME, svc.INGEST_LOCK}
    )

    cards = await conversion.read_status(None)
    assert cards["running"] is False and cards["delete"]["running"] is True
    assert (await backfill.read_status(None))["running"] is True
    # Bieg planowy w workerze: status z web to „trwa”, nie „przerwany”.
    snapshot = svc.sync_snapshot(
        {"last_status": "running"}, running=await svc.ingest_is_running()
    )
    assert snapshot["running"] is True and snapshot["interrupted"] is False


# ── prawdziwe pg_locks (CI z Postgresem) ─────────────────────────────────────


async def test_pg_locks_shows_a_lock_held_by_another_connection(monkeypatch):
    monkeypatch.setattr(process_lock.settings, "NEXUS_PROCESS_ROLE", "web")
    manual_runs._reserved.clear()
    name = f"test_manual_runs_{uuid.uuid4().hex[:8]}"

    async def run() -> None:
        raise AssertionError("blokada zajęta — bieg nie może ruszyć")

    assert await manual_runs.lock_held(name) is False
    async with process_lock.cross_process_lock(name) as owned:
        assert owned is True
        assert await manual_runs.lock_held(name) is True
        assert await manual_runs.is_running(name) is True
        # „Drugi proces”: osobne połączenie nie dostaje blokady.
        assert await manual_runs.start_exclusive(name, run, label="test") is False
    assert await manual_runs.lock_held(name) is False
