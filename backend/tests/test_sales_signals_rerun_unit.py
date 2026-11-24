"""Plan ponownego zlecenia biegów bez wyniku (``scripts/sales_signals_rerun.py``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.sales import SalesSignalRun
from scripts import sales_signals_rerun as rerun

T0 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)


def _run(run_id: int, ids, *, status="expired", modes=None, at=T0, **over):
    return SalesSignalRun(
        id=run_id,
        kind=over.pop("kind", "briefing"),
        status=status,
        company_ids=list(ids),
        modes={str(k): v for k, v in (modes or {}).items()},
        request=over.pop("request", {}),
        report=over.pop("report", {}),
        started_at=at,
    )


def test_expired_research_runs_are_merged_and_split_like_the_loop() -> None:
    hooks = _run(261, range(1, 13), modes={cid: "call_hook" for cid in range(1, 13)})
    points = _run(639, [50, 51], modes={50: "first_call", 51: "ongoing"})
    again = _run(
        648,
        [50, 51],
        modes={50: "first_call", 51: "ongoing"},
        at=T0 + timedelta(hours=2),
    )
    later = _run(
        700,
        [51, 3],
        status="received",
        modes={51: "ongoing", 3: "first_call"},
        at=T0 + timedelta(hours=5),
    )
    result = rerun.plan(
        [rerun.source_of(run) for run in (hooks, points, again)],
        rerun.covering([hooks, points, again, later]),
        fresh_hooks={2},
    )
    groups = [(group, ids) for group, ids in result.batches]
    assert groups == [
        (("briefing", False, "call_hook"), [1, 3, 4, 5, 6]),
        (("briefing", False, "call_hook"), [7, 8, 9, 10, 11]),
        (("briefing", False, "call_hook"), [12]),
        (("briefing", False, "first_call"), [50]),
    ]
    # Firma 51 dostała później wynik w tym samym trybie; 3 tylko w innym trybie.
    assert (result.covered, result.fresh_hook) == (2, 1)


def test_cognism_resends_only_unprocessed_firms_not_processed_later() -> None:
    source = _run(
        598,
        [10, 11, 12],
        status="received",
        kind="people",
        request={"source": "cognism"},
        report={"unprocessed_company_ids": [11, 12]},
    )
    later = _run(
        618,
        [12],
        status="received",
        kind="people",
        request={"source": "cognism"},
        report={"unprocessed_company_ids": []},
        at=T0 + timedelta(hours=9),
    )
    result = rerun.plan(
        [rerun.source_of(source)], rerun.covering([source, later]), fresh_hooks=set()
    )
    assert result.batches == [(("people", True, ""), [11])]
    assert result.covered == 1


def test_received_and_running_research_runs_are_left_alone() -> None:
    done = _run(560, [1], status="received", modes={1: "ongoing"})
    running = _run(765, [2], status="started", modes={2: "call_hook"})
    result = rerun.plan(
        [rerun.source_of(done), rerun.source_of(running)], {}, fresh_hooks=set()
    )
    assert result.batches == []
    assert result.skipped_runs == {560: "bieg ma raport", 765: "bieg jeszcze trwa"}
