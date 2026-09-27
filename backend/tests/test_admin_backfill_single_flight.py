"""Runda 10 (R10-N8-2/4/5): backfille admina — jeden bieg naraz, trwały kursor.

* Dwa szybkie POST-y nie mogą odpalić dwóch płatnych biegów: flaga `running`
  stoi, zanim handler odda odpowiedź (dotąd ustawiało ją dopiero zadanie
  w tle, w kolejnej iteracji pętli).
* Kursor biegu przeżywa restart kontenera: zapis w `app_settings`, odczyt
  w statusie i jako domyślne `after_id`.
* `/backfill-names` przyjmuje `after_id`.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api import admin_candidates as ac
from app.api import admin_notes_insights as ani
from app.api import admin_recruitment_processes as arp


@pytest.fixture(autouse=True)
def _no_db_progress(monkeypatch):
    saved: dict[str, dict] = {}

    async def fake_save(name, job, keys):
        saved[name] = {k: job.get(k) for k in keys if k in job}

    async def fake_load(name):
        return saved.get(name)

    monkeypatch.setattr(ac, "_save_progress", fake_save)
    monkeypatch.setattr(ac, "_load_progress", fake_load)
    for job in (ac._JOB, ac._CC_JOB, ac._CV_FIELDS_JOB, ac._EXP_DATES_JOB):
        job["running"] = False
    arp._JOB["running"] = False
    ani._manual_reserved = False
    return saved


@pytest.mark.asyncio
async def test_two_quick_cc_posts_start_one_run(monkeypatch):
    release = asyncio.Event()
    calls = 0

    async def fake_backfill(db, **kwargs):
        nonlocal calls
        calls += 1
        await release.wait()
        return {}

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(ac, "backfill_candidate_ccs", fake_backfill)
    monkeypatch.setattr(ac, "AsyncSessionLocal", _Session)

    async def post():
        return await ac.trigger_backfill_cc(
            None, limit=None, only_missing=True, start_after_id=0, only_slug=[]
        )

    results = await asyncio.gather(post(), post(), return_exceptions=True)
    conflicts = [r for r in results if isinstance(r, HTTPException)]
    assert len(conflicts) == 1 and conflicts[0].status_code == 409
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release.set()
    for _ in range(20):
        await asyncio.sleep(0)
    assert calls == 1


@pytest.mark.asyncio
async def test_two_quick_process_backfill_posts_start_one_run(monkeypatch):
    release = asyncio.Event()

    async def fake_run(limit_pairs, resync_stale):
        arp._JOB["running"] = True
        await release.wait()
        arp._JOB["running"] = False

    monkeypatch.setattr(arp, "_run_backfill", fake_run)

    async def post():
        return await arp.trigger_process_backfill(
            None, limit_pairs=None, resync_stale=False
        )

    results = await asyncio.gather(post(), post(), return_exceptions=True)
    assert sum(isinstance(r, HTTPException) for r in results) == 1
    release.set()
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_notes_insights_second_post_is_409_not_queued(monkeypatch):
    runs = 0
    release = asyncio.Event()

    async def fake_run():
        nonlocal runs
        runs += 1
        await release.wait()
        return {}

    monkeypatch.setattr(ani, "run_and_persist", fake_run)
    monkeypatch.setattr(ani.settings, "NOTES_INSIGHTS_SYNC_ENABLED", True)

    async def post():
        return await ani.trigger_notes_insights_sync.__wrapped__(None, None)

    results = await asyncio.gather(post(), post(), return_exceptions=True)
    assert sum(isinstance(r, HTTPException) for r in results) == 1
    release.set()
    for _ in range(5):
        await asyncio.sleep(0)
    assert runs == 1
    assert ani._manual_reserved is False


@pytest.mark.asyncio
async def test_cc_cursor_survives_restart_and_is_the_default(monkeypatch, _no_db_progress):
    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    async def interrupted(db, *, progress, start_after_id, **kwargs):
        progress["processed"] = 3
        progress["last_id"] = 4242
        raise RuntimeError("container restart")

    monkeypatch.setattr(ac, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(ac, "backfill_candidate_ccs", interrupted)
    await ac._run_cc_backfill(None, True, 0, None)

    # „Restart”: stan w pamięci wraca do zera, zapis zostaje.
    ac._CC_JOB.update(running=False, last_id=0)
    status = await ac.backfill_cc_status(None)
    assert status["resume_after_id"] == 4242

    seen: list[int] = []

    async def resumed(db, *, start_after_id, **kwargs):
        seen.append(start_after_id)
        return {}

    monkeypatch.setattr(ac, "backfill_candidate_ccs", resumed)
    response = await ac.trigger_backfill_cc(
        None, limit=None, only_missing=True, start_after_id=None, only_slug=[]
    )
    assert response["start_after_id"] == 4242
    for _ in range(10):
        await asyncio.sleep(0)
    assert seen == [4242]

    # Inne parametry = inny bieg, od początku.
    ac._CC_JOB["running"] = False
    other = await ac.trigger_backfill_cc(
        None, limit=None, only_missing=False, start_after_id=None, only_slug=[]
    )
    assert other["start_after_id"] == 0
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_finished_run_resets_the_default_cursor(monkeypatch):
    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    async def done(db, *, progress, **kwargs):
        progress["last_id"] = 999
        progress["stopped_reason"] = "done"
        return progress

    import app.services.cv_field_backfill as runner

    monkeypatch.setattr(ac, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(runner, "backfill_cv_fields", done)
    await ac._run_cv_fields_backfill(None, 0, None)

    status = await ac.backfill_cv_fields_status(None)
    assert status["saved_progress"]["last_id"] == 999
    assert status["resume_after_id"] == 0


@pytest.mark.asyncio
async def test_backfill_names_accepts_after_id(monkeypatch):
    seen: list = []

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    async def fake_names(db, *, limit, after_id, prefer_llm, progress):
        seen.append(after_id)
        progress["cursor_id"] = 77
        progress["total"] = limit
        return {}

    monkeypatch.setattr(ac, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(ac, "backfill_missing_names", fake_names)

    response = await ac.trigger_backfill_names(
        None, limit=2, prefer_llm=True, after_id=10
    )
    assert response["after_id"] == 10
    for _ in range(10):
        await asyncio.sleep(0)
    assert seen == [10]

    # Pełna paczka (total == limit) = ogon nieosiągnięty → następny bieg od 77.
    status = await ac.backfill_names_status(None)
    assert status["resume_after_id"] == 77
