"""Sonda `checks.compass_lifecycle` — stempel biegu i werdykt świeżości (MON-04/INT-10).

Do 09.2026 jedynym śladem pętli `compass_lifecycle_sync` w `/api/health` było
`running` z `classify_background_tasks`, a pętla łyka każdy wyjątek i wraca
z `fetch_failed`/`empty_roster` normalnie — niedostępny COMPASS wyglądał jak
zdrowa instalacja, a osoba `exited` zachowywała dostęp.

Trzy grupy, bo trzy rzeczy mogą się zepsuć niezależnie:

* **drabina** (`unconfigured` / `misconfigured`) — przez HTTP, przed I/O;
* **werdykt** (`healthy` / `degraded`) — na czystej funkcji;
* **stempel** — na bazie: co `sync_user_lifecycle` zostawia po sukcesie
  i po porażce, i czy porażka nie kasuje stanu epizodów odejścia.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.app_setting import AppSetting
from app.services import compass_lifecycle
from app.services.compass_lifecycle import (
    lifecycle_sync_verdict,
    public_error_kind,
    record_sync_outcome,
)

_INTERVAL = 21_600  # 6 h — wartość domyślna z config.py
_NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
_STATE_KEY = "compass_lifecycle_state"


@pytest.fixture
def env_with_metadata(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("BUILT_AT", "2099-12-31T12:00:00Z")


def _configure(monkeypatch, people=None, *, fetch=None):
    async def fake_fetch():
        if fetch is not None:
            return await fetch()
        return {"people": people or []}

    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_URL", "http://x")
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_SECRET", "s")
    monkeypatch.setattr(compass_lifecycle, "fetch_roster", fake_fetch)


async def _clear_state() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key == _STATE_KEY))
        await db.commit()


async def _state() -> dict | None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, _STATE_KEY)
        return dict(row.value) if row is not None else None


async def _health() -> dict:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        return (await ac.get("/api/health")).json()


# ── drabina konfiguracji (przez HTTP) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_unconfigured_when_kill_switch_off(env_with_metadata, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_ENABLED", False)
    body = await _health()
    assert body["checks"].get("compass_lifecycle") == "unconfigured"


@pytest.mark.asyncio
async def test_misconfigured_when_enabled_without_url_or_secret(
    env_with_metadata, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_URL", "")
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_SECRET", "s3cret")
    body = await _health()
    assert body["checks"].get("compass_lifecycle") == "misconfigured"


@pytest.mark.asyncio
async def test_compass_outage_never_turns_nexus_red(env_with_metadata, monkeypatch):
    """`status` liczy się WYŁĄCZNIE z `database` — sonda jest informacyjna."""
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_URL", "")
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_SECRET", "")
    body = await _health()
    assert body["checks"]["compass_lifecycle"] == "misconfigured"
    assert body["status"] == (
        "healthy" if body["checks"]["database"] == "healthy" else "unhealthy"
    )


# ── werdykt świeżości (czysta funkcja) ──────────────────────────────────────


def test_no_state_row_is_degraded():
    assert (
        lifecycle_sync_verdict(None, interval_seconds=_INTERVAL, now=_NOW) == "degraded"
    )


def test_state_without_stamp_is_degraded():
    """Stan sprzed stempla (wersja 2: tylko `last_seen`/`exit_since`)."""
    state = {"version": 2, "last_seen": {}, "exit_since": {}}
    assert (
        lifecycle_sync_verdict(state, interval_seconds=_INTERVAL, now=_NOW)
        == "degraded"
    )


def test_fresh_ok_is_healthy():
    state = {
        "last_status": "ok",
        "last_success_at": (_NOW - timedelta(hours=2)).isoformat(),
    }
    assert (
        lifecycle_sync_verdict(state, interval_seconds=_INTERVAL, now=_NOW) == "healthy"
    )


def test_one_late_run_does_not_degrade():
    """Próg to DWA odstępy — jeden bieg zjedzony przez deploy nie alarmuje."""
    state = {
        "last_status": "ok",
        "last_success_at": (_NOW - timedelta(hours=11)).isoformat(),
    }
    assert (
        lifecycle_sync_verdict(state, interval_seconds=_INTERVAL, now=_NOW) == "healthy"
    )


def test_no_success_for_more_than_two_intervals_degrades():
    state = {
        "last_status": "ok",
        "last_success_at": (_NOW - timedelta(hours=13)).isoformat(),
    }
    assert (
        lifecycle_sync_verdict(state, interval_seconds=_INTERVAL, now=_NOW)
        == "degraded"
    )


def test_failed_last_run_degrades_even_with_a_fresh_success():
    """NAJWAŻNIEJSZY test: padnięty bieg = COMPASS właśnie przestał odpowiadać."""
    state = {
        "last_status": "error",
        "last_error": "fetch_failed (ConnectError)",
        "last_success_at": (_NOW - timedelta(hours=1)).isoformat(),
    }
    assert (
        lifecycle_sync_verdict(state, interval_seconds=_INTERVAL, now=_NOW)
        == "degraded"
    )


def test_threshold_never_drops_below_the_loop_clamp():
    """Literówka w env (60 s) nie może dać progu 2 min — pętla i tak biega co 15 min."""
    state = {
        "last_status": "ok",
        "last_success_at": (_NOW - timedelta(minutes=20)).isoformat(),
    }
    assert lifecycle_sync_verdict(state, interval_seconds=60, now=_NOW) == "healthy"


def test_public_error_kind_drops_exception_text():
    exc = RuntimeError("http://compass.example/api/internal/roster -> 401 body…")
    kind = public_error_kind("fetch_failed: " + str(exc), exc)
    assert kind == "fetch_failed (RuntimeError)"
    assert "compass.example" not in kind
    assert public_error_kind("empty_roster") == "empty_roster"


# ── stempel na bazie ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_run_stamps_last_success(monkeypatch):
    await _clear_state()
    _configure(
        monkeypatch, [{"email": "nobody@example.com", "employment_status": "active"}]
    )

    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)
    assert result.error is None

    state = await _state()
    assert state is not None
    assert state["last_status"] == "ok"
    assert state["last_error"] is None
    assert state["last_success_at"] is not None
    assert (
        lifecycle_sync_verdict(
            state, interval_seconds=_INTERVAL, now=datetime.now(timezone.utc)
        )
        == "healthy"
    )


@pytest.mark.asyncio
async def test_fetch_failure_stamps_error_without_erasing_episode_state(monkeypatch):
    """Porażka dopisuje stempel SCALENIEM — `last_seen` z poprzedniego biegu zostaje."""
    await _clear_state()
    marker = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        db.add(
            AppSetting(
                key=_STATE_KEY,
                value={"version": 2, "last_seen": {marker: "active"}, "exit_since": {}},
            )
        )
        await db.commit()

    async def failing_fetch():
        raise ConnectionError("http://compass.example/roster refused")

    _configure(monkeypatch, fetch=failing_fetch)
    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)
    assert result.error and result.error.startswith("fetch_failed")

    state = await _state()
    assert state["last_status"] == "error"
    assert state["last_error"] == "fetch_failed (ConnectionError)"
    assert "compass.example" not in state["last_error"]
    assert state["last_seen"] == {marker: "active"}
    assert "last_success_at" not in state


@pytest.mark.asyncio
async def test_empty_roster_is_stamped_as_a_failure(monkeypatch):
    await _clear_state()
    _configure(monkeypatch, [])
    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)
    assert result.error == "empty_roster"
    state = await _state()
    assert state["last_status"] == "error"
    assert state["last_error"] == "empty_roster"


@pytest.mark.asyncio
async def test_health_reads_the_stamp_end_to_end(env_with_metadata, monkeypatch):
    """Konfiguracja pełna → sonda czyta stempel z bazy, nie flagi."""
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_URL", "http://x")
    monkeypatch.setattr("app.core.config.settings.COMPASS_LIFECYCLE_SECRET", "s")

    await _clear_state()
    assert (await _health())["checks"]["compass_lifecycle"] == "degraded"

    async with AsyncSessionLocal() as db:
        await record_sync_outcome(db, ok=True)
    assert (await _health())["checks"]["compass_lifecycle"] == "healthy"

    async with AsyncSessionLocal() as db:
        await record_sync_outcome(db, ok=False, error="fetch_failed (ReadTimeout)")
    assert (await _health())["checks"]["compass_lifecycle"] == "degraded"
