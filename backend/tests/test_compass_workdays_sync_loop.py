"""`compass_workdays_sync_loop` — configuration gates, the two windows, stamping.

`sync_workdays` (which talks to COMPASS) and `_stamp` (which writes the single
`compass_workdays_sync_state` row read by `/api/health`) are replaced with
recorders: the shared test database must not see a fake sync state, and the
point here is the loop contract — what it asks for, what it records, and that
it survives a COMPASS outage.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.insights_workdays import WorkdaySyncResult
from app.tasks import compass_workdays_sync as loop_mod


# ── pure helpers ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 3, 17), date(2026, 3, 1)),
        (date(2026, 3, 1), date(2026, 3, 1)),
        (date(2024, 2, 29), date(2024, 2, 1)),
    ],
)
def test_first_of_month(value, expected):
    assert loop_mod._first_of_month(value) == expected


@pytest.mark.parametrize(
    ("value", "months", "expected"),
    [
        (date(2026, 3, 1), 0, date(2026, 3, 1)),
        (date(2026, 3, 1), -2, date(2026, 1, 1)),
        (date(2026, 1, 1), -1, date(2025, 12, 1)),
        (date(2026, 1, 31), -13, date(2024, 12, 1)),
        (date(2025, 11, 15), 3, date(2026, 2, 1)),
    ],
)
def test_shift_months_lands_on_first_day(value, months, expected):
    assert loop_mod._shift_months(value, months) == expected


# ── gates ────────────────────────────────────────────────────────────────────


def _configure(monkeypatch, *, enabled=True, url="https://compass.test/x", secret="s"):
    monkeypatch.setattr(loop_mod.settings, "COMPASS_WORKDAYS_ENABLED", enabled)
    monkeypatch.setattr(loop_mod.settings, "COMPASS_WORKDAYS_URL", url)
    monkeypatch.setattr(loop_mod.settings, "COMPASS_WORKDAYS_SECRET", secret)


@pytest.mark.parametrize(
    "overrides",
    [{"enabled": False}, {"url": ""}, {"secret": ""}],
    ids=["disabled", "missing-url", "missing-secret"],
)
async def test_unusable_configuration_returns_immediately(monkeypatch, overrides):
    _configure(monkeypatch, **overrides)

    async def _forbidden(*_a, **_kw):
        raise AssertionError("a loop that cannot run must not wait, sync or stamp")

    monkeypatch.setattr(loop_mod.asyncio, "sleep", _forbidden)
    monkeypatch.setattr(loop_mod, "sync_workdays", _forbidden)
    monkeypatch.setattr(loop_mod, "_stamp", _forbidden)

    assert await loop_mod.compass_workdays_sync_loop() is None


# ── one pass ─────────────────────────────────────────────────────────────────


def _wire(monkeypatch, *, sync, today=date(2026, 3, 17), interval=3600, lookback=3):
    _configure(monkeypatch)
    monkeypatch.setattr(
        loop_mod.settings, "COMPASS_WORKDAYS_SYNC_INTERVAL_SECONDS", interval
    )
    monkeypatch.setattr(loop_mod.settings, "COMPASS_WORKDAYS_LOOKBACK_MONTHS", lookback)
    monkeypatch.setattr(loop_mod, "business_today", lambda: today)
    session = AsyncMock()
    monkeypatch.setattr(loop_mod, "AsyncSessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(loop_mod, "sync_workdays", sync)
    stamps: list[dict] = []

    async def _record(**values):
        stamps.append(values)

    monkeypatch.setattr(loop_mod, "_stamp", _record)
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(loop_mod.asyncio, "sleep", sleep)
    return session, stamps, sleep


async def test_one_pass_syncs_month_and_week_windows(monkeypatch):
    month = WorkdaySyncResult(rows_written=4, matched_users=2)
    week = WorkdaySyncResult(rows_written=9, matched_users=2)
    sync = AsyncMock(side_effect=[month, week])
    today = date(2026, 3, 17)
    session, stamps, sleep = _wire(monkeypatch, sync=sync, today=today, interval=3600)

    with pytest.raises(asyncio.CancelledError):
        await loop_mod.compass_workdays_sync_loop()

    db = session.__aenter__.return_value
    assert sync.await_count == 2
    assert sync.await_args_list[0].args == (db, date(2026, 1, 1), date(2026, 3, 1))
    assert sync.await_args_list[0].kwargs == {"bucket": "month"}
    assert sync.await_args_list[1].args == (
        db,
        today - timedelta(weeks=loop_mod._WEEKS_BACK),
        today,
    )
    assert sync.await_args_list[1].kwargs == {"bucket": "week"}

    assert stamps[0]["last_status"] == "running"
    final = stamps[-1]
    assert final["last_status"] == "ok"
    assert final["last_error"] is None
    assert final["stats"] == {"month": month.as_payload(), "week": week.as_payload()}
    sleep.assert_awaited_once_with(3600)


async def test_soft_error_result_is_recorded_as_errors(monkeypatch):
    sync = AsyncMock(
        side_effect=[
            WorkdaySyncResult(error="fetch_failed: 502"),
            WorkdaySyncResult(rows_written=1),
        ]
    )
    _, stamps, _ = _wire(monkeypatch, sync=sync)

    with pytest.raises(asyncio.CancelledError):
        await loop_mod.compass_workdays_sync_loop()

    assert stamps[-1]["last_status"] == "errors"
    assert stamps[-1]["last_error"] == "month: fetch_failed: 502"


async def test_exception_is_stamped_and_loop_continues(monkeypatch):
    sync = AsyncMock(
        side_effect=[
            RuntimeError("compass unreachable"),
            WorkdaySyncResult(),
            WorkdaySyncResult(),
        ]
    )
    _, stamps, sleep = _wire(monkeypatch, sync=sync, interval=5)
    sleep.side_effect = [None, asyncio.CancelledError]

    with pytest.raises(asyncio.CancelledError):
        await loop_mod.compass_workdays_sync_loop()

    errors = [s for s in stamps if s.get("last_status") == "error"]
    assert len(errors) == 1
    assert errors[0]["last_error"] == "RuntimeError: compass unreachable"
    assert stamps[-1]["last_status"] == "ok", "the next pass runs after a crash"
    assert sync.await_count == 3
    assert [c.args for c in sleep.await_args_list] == [
        (loop_mod._MIN_INTERVAL_SECONDS,),
        (loop_mod._MIN_INTERVAL_SECONDS,),
    ], "interval is clamped to the minimum"


async def test_lookback_below_one_still_syncs_the_current_month(monkeypatch):
    sync = AsyncMock(side_effect=[WorkdaySyncResult(), WorkdaySyncResult()])
    _wire(monkeypatch, sync=sync, today=date(2026, 3, 17), lookback=0)

    with pytest.raises(asyncio.CancelledError):
        await loop_mod.compass_workdays_sync_loop()

    _, date_from, date_to = sync.await_args_list[0].args
    assert date_from == date_to == date(2026, 3, 1)


async def test_stamp_never_raises_when_the_database_is_down(monkeypatch):
    broken = MagicMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(loop_mod, "AsyncSessionLocal", broken)

    assert await loop_mod._stamp(last_status="running") is None
    broken.assert_called_once_with()


async def test_stamp_updates_row_and_sets_updated_at(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(loop_mod, "AsyncSessionLocal", MagicMock(return_value=session))

    await loop_mod._stamp(last_status="ok")

    db = session.__aenter__.return_value
    stmt = db.execute.await_args.args[0]
    params = stmt.compile().params
    assert params["last_status"] == "ok"
    assert params["updated_at"] is not None
    db.commit.assert_awaited_once()
