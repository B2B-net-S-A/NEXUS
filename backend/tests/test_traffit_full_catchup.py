"""Full reconcile catches up nightly while a budgeted sweep is unfinished.

The budgeted phases (`candidate_files`, `candidates_cv`,
`candidates_enrich_names`) cover a slice per run and park an `after_id` cursor
for the rest. On the weekly cadence the tail was reached one slice per WEEK —
~57k candidates at a 10k budget is over a month of uninterrupted Sundays. It is
not uninterrupted: Coolify restarts the container on every push to main, so in
practice such a sweep could stall indefinitely. That is exactly how the missing
CVs survived for months behind a green health probe.

The extra runs are gated on the CURSORS, not on a calendar or a manual flag, so
the mechanism is self-limiting: it stops the night the sweep completes and
clears its cursor. There is nothing to remember to switch off.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.tasks.traffit_sync import full_sweep_pending, should_run_full

UTC = timezone.utc

# 2026-08-16 is a Sunday; TRAFFIT_SYNC_FULL_WEEKDAY defaults to 6 (Sunday).
_SUNDAY = datetime(2026, 8, 16, 3, 0, tzinfo=UTC)
_WEDNESDAY = datetime(2026, 8, 19, 3, 0, tzinfo=UTC)


def test_weekly_cadence_is_unchanged_when_nothing_is_pending() -> None:
    """The catch-up must not turn into "full scan every night, forever"."""
    last = _SUNDAY - timedelta(days=7)

    assert should_run_full(_SUNDAY, last, 6, 2, sweep_pending=False)
    assert not should_run_full(_WEDNESDAY, last, 6, 2, sweep_pending=False)


def test_pending_sweep_makes_it_due_on_a_weekday() -> None:
    """The whole point: a slice lands the next night, not the next Sunday."""
    last = _WEDNESDAY - timedelta(days=1)

    assert not should_run_full(_WEDNESDAY, last, 6, 2, sweep_pending=False)
    assert should_run_full(_WEDNESDAY, last, 6, 2, sweep_pending=True)


def test_catch_up_still_respects_the_hour_and_one_run_per_night() -> None:
    """Catching up is not "run continuously" — the 30-min loop tick would
    otherwise re-trigger a multi-hour full scan on top of itself."""
    before_hour = _WEDNESDAY.replace(hour=1)
    assert not should_run_full(before_hour, None, 6, 2, sweep_pending=True)

    just_finished = _WEDNESDAY - timedelta(hours=2)
    assert not should_run_full(_WEDNESDAY, just_finished, 6, 2, sweep_pending=True)


def test_first_ever_run_still_waits_for_the_configured_weekday() -> None:
    """`last_finished is None` means the integration was just enabled. A full
    scan must not fire immediately on enable, pending cursors or not — and with
    no prior run there cannot be a sweep of ours to resume anyway."""
    assert not should_run_full(_WEDNESDAY, None, 6, 2, sweep_pending=True)
    assert should_run_full(_SUNDAY, None, 6, 2, sweep_pending=True)


# ── the cursor read that drives it ───────────────────────────────────────────


class _Rows:
    def __init__(self, payloads):
        self._payloads = payloads

    def __iter__(self):
        return iter((p,) for p in self._payloads)


class _FakeDB:
    def __init__(self, payloads):
        self.payloads = payloads
        self.phases_queried = None

    async def execute(self, stmt, params=None):
        assert "cursor_payload IS NOT NULL" in str(stmt)
        self.phases_queried = (params or {}).get("phases")
        return _Rows(self.payloads)


@pytest.mark.asyncio
async def test_pending_is_true_when_a_full_slot_carries_a_cursor() -> None:
    db = _FakeDB([{"full": {"after_id": 10827}}])
    assert await full_sweep_pending(db) is True
    # Exactly the budgeted phases — a cursor on a page-based phase means
    # something else entirely and must not trigger nightly full scans.
    assert set(db.phases_queried) == {
        "candidate_files",
        "candidates_cv",
        "candidates_enrich_names",
    }


@pytest.mark.asyncio
async def test_delta_only_cursor_does_not_count_as_pending() -> None:
    """These phases only ever cursor in full mode, but the slot is shared
    shape-wise with page-based phases. A delta slot alone is not our sweep."""
    db = _FakeDB([{"delta": {"page": 4, "since": "2026-08-10T02:00:00+00:00"}}])
    assert await full_sweep_pending(db) is False


@pytest.mark.asyncio
async def test_legacy_flat_cursor_counts_as_pending() -> None:
    """The per-mode split postdates the flat shape, and these phases never
    cursored in delta mode — so a flat payload is a full-run cursor."""
    db = _FakeDB([{"after_id": 356614}])
    assert await full_sweep_pending(db) is True


@pytest.mark.asyncio
async def test_no_cursors_means_not_pending() -> None:
    assert await full_sweep_pending(_FakeDB([])) is False
    # An empty/None slot is a cleared cursor, not an unfinished sweep.
    assert await full_sweep_pending(_FakeDB([{"full": None}, {}])) is False


def test_budget_covers_the_base_in_a_handful_of_runs() -> None:
    """Guards the reason the budget was raised: at 10k a ~57k base needed ~6
    runs, i.e. a month and a half of Sundays."""
    from app.core.config import settings

    base = 57_000
    runs = -(-base // settings.TRAFFIT_SYNC_FULL_FILES_LIMIT)  # ceil
    assert runs <= 3, f"{settings.TRAFFIT_SYNC_FULL_FILES_LIMIT} needs {runs} runs"


def test_settings_json_roundtrip_is_not_broken_by_the_new_default() -> None:
    """Cheap canary: the value is read via `settings`, so a typo that makes it
    a string would only surface at 2am inside the sweep."""
    from app.core.config import settings

    assert isinstance(settings.TRAFFIT_SYNC_FULL_FILES_LIMIT, int)
    json.dumps({"limit": settings.TRAFFIT_SYNC_FULL_FILES_LIMIT})
