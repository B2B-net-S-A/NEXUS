"""Audyt 22.09 r2 (INTG-01/02): przerwana próba dziennej delty się wznawia.

Coolify restartuje kontener przy każdym pushu na main (25–35 deployów na
dobę), a pełny plan faz trwa dłużej niż odstęp między nimi. Do 22.09 każda
kolejna próba zaczynała od `users` i nie dochodziła do `pipelines` — ruchy
z 21–22.09 nie weszły wcale. Teraz stan próby (`cursor_payload['attempt']`
wiersza znacznika) pozwala pominąć fazy skończone przed przerwaniem, a
`files_since` i watermark liczą się od startu PIERWSZEJ próby (INTG-02).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.tasks import traffit_sync as ts

UTC = timezone.utc
_PRIOR = datetime(2026, 9, 20, 2, 0, tzinfo=UTC)


class _Progress:
    def __init__(self) -> None:
        self.errors = 0
        self.started_at = datetime.now(UTC)
        self.finished_at = datetime.now(UTC)

    def as_dict(self) -> dict:
        return {"processed": 1, "errors": 0, "error_refs": []}


class _Client:
    def __init__(self, *a, **k) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _SessionCM:
    async def __aenter__(self):
        async def _noop(*a, **k):
            return None

        return SimpleNamespace(commit=_noop, rollback=_noop, execute=_noop)

    async def __aexit__(self, *a):
        return False


class _Store:
    """Pamięć stanu próby zamiast tabeli (SQL helperów pilnuje test niżej)."""

    def __init__(self) -> None:
        self.payload: dict | None = None

    async def load(self, db, marker):
        return ts.attempt_from_payload(self.payload)

    async def save(self, db, marker, attempt):
        self.payload = {"attempt": json.loads(json.dumps(attempt))}

    async def clear(self, db, marker):
        self.payload = None


def _install(monkeypatch, store: _Store, plan_factory, seen_files_since):
    upserts = AsyncMock()
    monkeypatch.setattr(ts, "_upsert_state", upserts)
    monkeypatch.setattr(
        ts,
        "_get_state",
        AsyncMock(return_value=SimpleNamespace(last_synced_at=_PRIOR, stats=None)),
    )
    monkeypatch.setattr(ts, "_load_attempt", store.load)
    monkeypatch.setattr(ts, "_save_attempt", store.save)
    monkeypatch.setattr(ts, "_clear_attempt", store.clear)

    def _plan(importer, since, files_since):
        seen_files_since.append(files_since)
        return plan_factory()

    monkeypatch.setattr(ts, "_phase_plan", _plan)
    monkeypatch.setattr(ts, "TraffitImporter", lambda *a, **k: object())
    monkeypatch.setattr(ts, "TraffitClient", _Client)
    monkeypatch.setattr(ts, "AsyncSessionLocal", lambda: _SessionCM())
    monkeypatch.setattr(ts.TraffitConfig, "from_env", staticmethod(lambda: object()))

    async def _no_detection(*a, **k):
        return None

    import app.services.placement_exclusions as pe

    monkeypatch.setattr(pe, "run_detection_safely", _no_detection)
    return upserts


def _ok(name, calls):
    async def _run():
        calls.append(name)
        return _Progress()

    return _run


@pytest.mark.asyncio
async def test_interrupted_attempt_resumes_after_the_finished_phases(monkeypatch):
    store = _Store()
    calls: list[str] = []
    seen_files_since: list = []
    interrupt = {"on": True}

    def _phase(name):
        async def _run():
            calls.append(name)
            if name == "phase3" and interrupt["on"]:
                # Deploy: kontener dostaje SIGTERM, zadanie jest anulowane.
                raise asyncio.CancelledError()
            return _Progress()

        return _run

    def plan():
        return [(n, _phase(n)) for n in ("phase1", "phase2", "phase3", "phase4")]

    upserts = _install(monkeypatch, store, plan, seen_files_since)

    with pytest.raises(asyncio.CancelledError):
        await ts.run_traffit_sync("delta")
    assert calls == ["phase1", "phase2", "phase3"]
    assert store.payload["attempt"]["done"] == ["phase1", "phase2"]
    first_files_since = seen_files_since[0]

    # Druga próba: fazy 1–2 pominięte, `files_since` = start PIERWSZEJ próby.
    interrupt["on"] = False
    calls.clear()
    result = await ts.run_traffit_sync("delta")
    assert calls == ["phase3", "phase4"]
    assert seen_files_since[1] == first_files_since
    assert result["phases"]["phase1"] == {"resumed": "done_in_previous_attempt"}

    # Watermark = start pierwszej próby, a próba jest zamknięta.
    daily = [c for c in upserts.call_args_list if c.args[1] == ts.DAILY_MARKER]
    assert daily[-1].kwargs["last_synced_at"] == first_files_since
    assert store.payload is None


@pytest.mark.asyncio
async def test_stale_attempt_starts_from_scratch(monkeypatch):
    store = _Store()
    old = datetime.now(UTC) - timedelta(hours=30)
    store.payload = {
        "attempt": {
            "since": (_PRIOR - timedelta(hours=48)).isoformat(),
            "run_start": old.isoformat(),
            "touched_at": old.isoformat(),
            "done": ["phase1"],
            "held": [],
        }
    }
    calls: list[str] = []
    seen: list = []
    _install(
        monkeypatch,
        store,
        lambda: [(n, _ok(n, calls)) for n in ("phase1", "phase2")],
        seen,
    )
    await ts.run_traffit_sync("delta")
    assert calls == ["phase1", "phase2"]
    assert seen[0] > old


@pytest.mark.asyncio
async def test_held_phase_from_previous_attempt_still_freezes_the_watermark(
    monkeypatch,
):
    store = _Store()
    now = datetime.now(UTC)
    store.payload = {
        "attempt": {
            "since": (_PRIOR - timedelta(hours=48)).isoformat(),
            "run_start": (now - timedelta(hours=1)).isoformat(),
            "touched_at": now.isoformat(),
            "done": ["phase1"],
            "held": ["phase1"],
        }
    }
    calls: list[str] = []
    upserts = _install(
        monkeypatch,
        store,
        lambda: [(n, _ok(n, calls)) for n in ("phase1", "phase2")],
        [],
    )
    result = await ts.run_traffit_sync("delta")
    assert calls == ["phase2"]
    assert result["status"] == "errors"
    daily = [c for c in upserts.call_args_list if c.args[1] == ts.DAILY_MARKER]
    assert daily[-1].kwargs["last_synced_at"] is None


@pytest.mark.asyncio
async def test_partial_run_neither_resumes_nor_records_an_attempt(monkeypatch):
    store = _Store()
    calls: list[str] = []
    _install(
        monkeypatch,
        store,
        lambda: [(n, _ok(n, calls)) for n in ("users", "pipelines")],
        [],
    )
    monkeypatch.setattr(ts, "validate_phases", lambda phases: frozenset(phases))
    await ts.run_traffit_sync("delta", phases=["pipelines"])
    assert calls == ["pipelines"]
    assert store.payload is None


def test_should_run_daily_resumes_pending_attempt_outside_the_hour():
    now = datetime(2026, 9, 22, 13, 0, tzinfo=UTC)
    last = now - timedelta(hours=2)
    assert ts.should_run_daily(now, last, 22) is False
    assert ts.should_run_daily(now, last, 22, attempt_pending=True) is True


def test_resumable_attempt_requires_the_same_since():
    now = datetime(2026, 9, 22, 13, 0, tzinfo=UTC)
    attempt = {
        "since": "2026-09-18T02:00:00+00:00",
        "run_start": "2026-09-22T12:00:00+00:00",
        "touched_at": "2026-09-22T12:30:00+00:00",
        "done": ["users"],
    }
    assert ts.resumable_attempt(
        attempt, since_iso="2026-09-18T02:00:00+00:00", now_utc=now, resume_hours=24
    ) == (datetime(2026, 9, 22, 12, 0, tzinfo=UTC), {"users"}, set())
    assert (
        ts.resumable_attempt(
            attempt,
            since_iso="2026-09-19T02:00:00+00:00",
            now_utc=now,
            resume_hours=24,
        )
        is None
    )


def test_pipelines_run_before_files_and_cortex():
    """INTG-01: ruchy pipeline'u przed plikami CV i Cortexem."""
    names = list(ts.PHASE_NAMES)
    assert names.index("jobs") < names.index("pipelines")
    assert names.index("pipelines") < names.index("candidates_cv")
    assert names.index("pipelines") < names.index("candidate_files")
    assert names.index("pipelines") < names.index("cortex")


@pytest.mark.asyncio
async def test_attempt_sql_helpers_round_trip_and_keep_other_cursor_keys():
    marker = "__attempt_test__"
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM traffit_sync_state WHERE phase = :p"), {"p": marker}
        )
        await db.execute(
            text(
                "INSERT INTO traffit_sync_state (phase, cursor_payload, created_at, "
                "updated_at) VALUES (:p, CAST(:c AS jsonb), NOW(), NOW())"
            ),
            {"p": marker, "c": json.dumps({"delta": {"page": 3}})},
        )
        await db.commit()
        try:
            await ts._save_attempt(db, marker, {"since": None, "done": ["users"]})
            assert await ts._load_attempt(db, marker) == {
                "since": None,
                "done": ["users"],
            }
            await ts._clear_attempt(db, marker)
            assert await ts._load_attempt(db, marker) is None
            payload = (
                await db.execute(
                    text(
                        "SELECT cursor_payload FROM traffit_sync_state WHERE phase = :p"
                    ),
                    {"p": marker},
                )
            ).scalar_one()
            assert payload == {"delta": {"page": 3}}
        finally:
            await db.execute(
                text("DELETE FROM traffit_sync_state WHERE phase = :p"), {"p": marker}
            )
            await db.commit()
