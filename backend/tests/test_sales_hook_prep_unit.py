"""Haczyk przed telefonem i teczka przed spotkaniem bez bazy: dni robocze, wybór
firm, polecenie dla bota i przyjęcie haczyków. Dane są fikcyjne."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.services.sales import bot_tasks, hook_prep_targets, signals
from app.services.sales.bot_tasks import call_hook, signals_briefing
from app.tasks import sales_signals as loop

WARSAW = ZoneInfo("Europe/Warsaw")
TODAY = date(2026, 11, 12)


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WARSAW)


# ── dni robocze ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("today", "due"),
    [
        (date(2026, 11, 12), date(2026, 11, 13)),  # czwartek → piątek
        (date(2026, 11, 13), date(2026, 11, 16)),  # piątek → poniedziałek
        (date(2026, 11, 10), date(2026, 11, 12)),  # 11.11 to święto
        (date(2026, 12, 23), date(2026, 12, 28)),  # Wigilia, święta, weekend
    ],
)
def test_due_day_is_the_next_business_day(today: date, due: date) -> None:
    assert hook_prep_targets.due_day(today) == due


def test_prep_window_on_friday_covers_the_weekend_and_monday() -> None:
    start, end = hook_prep_targets.prep_window(date(2026, 11, 13))
    assert start == _local(date(2026, 11, 14), 0).astimezone(timezone.utc)
    assert end.astimezone(WARSAW).date() == date(2026, 11, 16)
    assert end + timedelta(microseconds=1) == _local(date(2026, 11, 17), 0)


def test_prep_window_before_a_holiday_reaches_the_day_after_it() -> None:
    start, end = hook_prep_targets.prep_window(date(2026, 11, 10))
    assert start.astimezone(WARSAW).date() == date(2026, 11, 11)
    assert end.astimezone(WARSAW).date() == date(2026, 11, 12)


def test_opened_today_counts_failed_runs_only_for_an_hour() -> None:
    now = _local(TODAY, 18).astimezone(timezone.utc)
    hook = {"1": "call_hook"}
    assert hook_prep_targets.opened_today(
        [("started", now - timedelta(hours=2), hook)], "call_hook", now=now
    )
    assert hook_prep_targets.opened_today(
        [("failed", now - timedelta(minutes=30), hook)], "call_hook", now=now
    )
    assert not hook_prep_targets.opened_today(
        [("failed", now - timedelta(hours=2), hook)], "call_hook", now=now
    )
    # Bieg punktów albo teczki nie zastępuje haczyka.
    assert not hook_prep_targets.opened_today(
        [("received", now, {"1": "meeting_prep"}), ("received", now, {"2": "ongoing"})],
        "call_hook",
        now=now,
    )


@pytest.mark.asyncio
async def test_hook_targets_ask_the_queue_for_monday_on_friday(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fresh(_db, **_k):
        return {7}

    async def due(_db, day, today, *, exclude, limit):
        calls.append((day, today, set(exclude), limit))
        return [1, 2]

    monkeypatch.setattr(call_hook, "fresh_company_ids", fresh)
    monkeypatch.setattr(hook_prep_targets.calling, "companies_due_by", due)
    now = _local(date(2026, 11, 13), 16).astimezone(timezone.utc)
    ids = await hook_prep_targets.hook_company_ids(
        None, now=now, today=date(2026, 11, 13)
    )
    assert ids == [1, 2]
    assert calls == [(date(2026, 11, 16), date(2026, 11, 13), {7}, 40)]


class _Rows:
    def __init__(self, values: list[int]) -> None:
        self.values = values

    def scalars(self) -> list[int]:
        return self.values


class _FreshDb:
    def __init__(self, fresh: list[int]) -> None:
        self.fresh = fresh

    async def execute(self, _statement) -> _Rows:
        return _Rows(self.fresh)


@pytest.mark.asyncio
async def test_prep_targets_skip_firms_with_points_younger_than_three_days(
    monkeypatch,
) -> None:
    windows: list[tuple[datetime, datetime]] = []

    async def meetings(_db, start, end):
        windows.append((start, end))
        return [5, 6, 7]

    monkeypatch.setattr(hook_prep_targets.my_day, "meeting_company_ids", meetings)
    now = _local(TODAY, 16).astimezone(timezone.utc)
    ids = await hook_prep_targets.prep_company_ids(_FreshDb([6]), now=now, today=TODAY)
    assert ids == [5, 7]
    assert windows == [hook_prep_targets.prep_window(TODAY)]


# ── pętla ─────────────────────────────────────────────────────────────────


def _patch_loop(monkeypatch, started: list, runs: list | None = None) -> None:
    async def runs_since(_db, since):
        return list(runs or [])

    async def hooks(_db, **_k):
        return [1, 2]

    async def preps(_db, **_k):
        return [3, 4]

    async def modes(_db, company_ids, **_k):
        return {3: "first_call", 4: "ongoing"}

    class _Run:
        status = "started"

    async def start(_db, kind, company_ids, **kwargs):
        started.append(
            (kind, list(company_ids), kwargs.get("modes"), kwargs.get("request"))
        )
        return _Run()

    monkeypatch.setattr(loop.hook_prep, "runs_since", runs_since)
    monkeypatch.setattr(loop.hook_prep, "hook_company_ids", hooks)
    monkeypatch.setattr(loop.hook_prep, "prep_company_ids", preps)
    monkeypatch.setattr(loop.targets, "modes_for", modes)
    monkeypatch.setattr(loop.signals, "start_run", start)


async def _run_at(local: datetime) -> dict[str, int]:
    return await loop.hooks_and_prep(
        None, now=local.astimezone(timezone.utc), local=local
    )


@pytest.mark.asyncio
async def test_friday_at_four_starts_hooks_and_prep_once(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    started: list = []
    _patch_loop(monkeypatch, started)
    done = await _run_at(_local(date(2026, 11, 13), 16, 5))
    assert done == {"call_hook": 2, "meeting_prep": 2}
    assert started == [
        ("briefing", [1, 2], {1: "call_hook", 2: "call_hook"}, None),
        (
            "briefing",
            [3, 4],
            {3: "meeting_prep", 4: "meeting_prep"},
            {"first_meeting": [3]},
        ),
    ]

    started.clear()
    now = _local(date(2026, 11, 13), 16, 20).astimezone(timezone.utc)
    _patch_loop(
        monkeypatch,
        started,
        runs=[
            ("started", now, {"1": "call_hook"}),
            ("received", now, {"3": "meeting_prep"}),
        ],
    )
    assert await _run_at(_local(date(2026, 11, 13), 16, 20)) == {
        "call_hook": 0,
        "meeting_prep": 0,
    }
    assert started == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "local",
    [
        _local(date(2026, 11, 13), 15, 55),  # przed 16:00
        _local(date(2026, 11, 14), 16, 30),  # sobota
        _local(date(2026, 11, 11), 17, 0),  # święto
    ],
)
async def test_no_hooks_or_prep_before_four_or_off_business_days(
    monkeypatch, local: datetime
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    started: list = []
    _patch_loop(monkeypatch, started)
    await _run_at(local)
    assert started == []


@pytest.mark.asyncio
async def test_no_hooks_or_prep_without_the_flag(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    started: list = []
    _patch_loop(monkeypatch, started)
    await _run_at(_local(TODAY, 17))
    assert started == []


# ── raport i polecenie ────────────────────────────────────────────────────


def _hook(ref: int, **over: Any) -> dict[str, Any]:
    base = {
        "company_ref": ref,
        "sentence": "Widziałem, że uruchomiliście asystenta w obsłudze klienta.",
        "facts": [
            {
                "text": "Firma wdrożyła asystenta AI",
                "url": "example.com/ai",
                "published": (TODAY - timedelta(days=30)).isoformat(),
            }
        ],
    }
    return {**base, **over}


def _report(**over: Any) -> signals_briefing.BriefingReport:
    return signals_briefing.BriefingReport.model_validate({"checked_firms": 2, **over})


def test_hook_report_takes_no_people_and_at_most_two_sourced_facts() -> None:
    report = _report(hooks=[_hook(1)])
    assert report.hooks[0].facts[0].url == "https://example.com/ai"
    with pytest.raises(ValidationError):
        _report(hooks=[_hook(1, email="jan@example.com")])
    with pytest.raises(ValidationError):
        _report(hooks=[_hook(1, facts=[_hook(1)["facts"][0]] * 3)])
    with pytest.raises(ValidationError):
        _report(hooks=[_hook(1, facts=[])])
    bad_url = {**_hook(1)["facts"][0], "url": "javascript:alert(1)"}
    with pytest.raises(ValidationError):
        _report(hooks=[_hook(1, facts=[bad_url])])
    # Raport v1 bez ``hooks`` dalej przechodzi.
    assert _report().hooks == []


def _run(modes: dict[int, str], ids=(1, 2, 3)):
    return signals.new_run(
        "briefing", list(ids), now=datetime.now(timezone.utc), modes=modes
    )[0]


def test_plan_keeps_hooks_only_for_call_hook_firms_once_and_with_fresh_facts() -> None:
    run = _run({1: "call_hook", 2: "ongoing", 3: "call_hook"})
    run.id = 77
    old = {**_hook(3)["facts"][0], "published": "2024-01-01"}
    hooks = _report(
        hooks=[_hook(1), _hook(1), _hook(2), _hook(3, facts=[old]), _hook(9)]
    ).hooks
    rows, dropped = call_hook.plan_hooks(run, hooks, today=TODAY)
    assert [row["company_id"] for row in rows] == [1]
    assert dropped == 4
    assert rows[0]["payload"]["facts"][0] == {
        "text": "Firma wdrożyła asystenta AI",
        "url": "https://example.com/ai",
        "published": (TODAY - timedelta(days=30)).isoformat(),
    }
    assert rows[0]["fingerprint"].startswith("call_hook|")


@pytest.mark.asyncio
async def test_briefing_ingest_keeps_points_of_hook_firms_out_of_briefings(
    monkeypatch,
) -> None:
    seen: dict[str, Any] = {}

    async def ingest(_db, run, report, *, now):
        seen["refs"] = [b.company_ref for b in report.briefings]
        return {"briefings": len(report.briefings), "dropped": {}}

    async def save(_db, run, rows, now, *, kind=None):
        seen["saved"] = (kind, [row["company_id"] for row in rows])
        return len(rows)

    monkeypatch.setattr(signals_briefing.signals, "ingest", ingest)
    monkeypatch.setattr(call_hook, "save_results", save)
    run = _run({1: "call_hook", 2: "meeting_prep"}, ids=(1, 2))
    report = _report(
        briefings=[
            {"company_ref": 1, "points": [{"text": "Nie powinno nadpisać"}]},
            {"company_ref": 2, "points": [{"text": "Przed spotkaniem"}]},
        ],
        hooks=[_hook(1)],
    )
    summary = await signals_briefing.BRIEFING.ingest(
        None, run, report, datetime.now(timezone.utc)
    )
    assert seen == {"refs": [2], "saved": ("call_hook", [1])}
    assert (summary["hooks"], summary["hooks_dropped"]) == (1, 0)


def _text(firms: list[dict[str, Any]], request: dict[str, Any] | None = None) -> str:
    task = bot_tasks.REGISTRY["briefing"]
    return task.task_text(
        _run({}), bot_tasks.TaskContext(firms=tuple(firms), request=request or {})
    )


def test_task_text_says_which_meeting_is_the_first_and_asks_for_hooks() -> None:
    text = _text(
        [
            {"ref": 3, "name": "A", "mode": "meeting_prep"},
            {"ref": 4, "name": "B", "mode": "meeting_prep"},
            {"ref": 5, "name": "C", "mode": "call_hook"},
        ],
        {"first_meeting": [3]},
    )
    assert "Pierwsze spotkanie z firmą (ref 3)" in text
    assert "rozmowy już trwają (ref 4)" in text
    assert 'mode = "call_hook" (ref 5)' in text
    legacy = _text([{"ref": 1, "name": "A", "mode": "first_call"}])
    assert "meeting_prep" not in legacy and "hooks zostaw puste" in legacy


def test_briefing_request_takes_only_first_meeting_refs() -> None:
    task = bot_tasks.REGISTRY["briefing"]
    assert task.validate_request(None) == {}
    assert task.validate_request({"first_meeting": [3]}) == {"first_meeting": [3]}
    with pytest.raises(ValueError):
        task.validate_request({"first_meeting": [3], "contact": "Jan"})


def test_webhook_body_for_hooks_has_names_domains_and_hook_format() -> None:
    from app.models.sales import SalesCompany

    run = _run({1: "call_hook"}, ids=(1,))
    run.id = 5
    body = signals.webhook_body(
        run,
        "token",
        [SalesCompany(id=1, name="Firma A", domain="a.example")],
        {"rejected": [], "seen_urls": []},
    )
    assert body["firms"] == [
        {"ref": 1, "name": "Firma A", "domain": "a.example", "mode": "call_hook"}
    ]
    assert body["report_format"]["hooks"][0]["facts"][0]["url"] == "https://..."
    assert 'mode = "call_hook" (ref 1)' in body["task"]
