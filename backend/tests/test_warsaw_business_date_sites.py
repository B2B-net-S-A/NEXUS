"""Miejsca, które liczyły „dziś" jako dzień UTC, liczą teraz dzień w Warszawie.

Każdy test przypina zegar na chwilę po północy warszawskiej, kiedy w UTC jest
jeszcze poprzedni dzień: 24.09.2026 22:30 UTC = 25.09 00:30 w Warszawie,
a 30.09.2026 22:30 UTC = 1.10 00:30 (nowy miesiąc tylko w Warszawie). Na starym
kodzie każda asercja dostawała dzień (albo miesiąc) wcześniej.

Daty liczone wewnątrz testów — nic przy imporcie (`test_no_import_time_dates`).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import time_machine

#: 25.09.2026 00:30 w Warszawie; w UTC jeszcze 24.09.
AFTER_WARSAW_MIDNIGHT = datetime(2026, 9, 24, 22, 30, tzinfo=timezone.utc)
#: 1.10.2026 00:30 w Warszawie; w UTC jeszcze wrzesień.
AFTER_WARSAW_MONTH_START = datetime(2026, 9, 30, 22, 30, tzinfo=timezone.utc)


def test_ai_quota_month_follows_warsaw_calendar():
    from app.services.ai_quota import _current_period_start

    with time_machine.travel(AFTER_WARSAW_MONTH_START, tick=False):
        assert _current_period_start() == date(2026, 10, 1)


def test_ai_spend_alert_month_matches_quota_month():
    """Alert pyta o wiersze pod tym samym `period_start`, pod którym zapisuje limit."""
    from app.services.ai_quota import _current_period_start
    from app.tasks.ai_spend_alerts import _period_start

    with time_machine.travel(AFTER_WARSAW_MONTH_START, tick=False):
        assert _period_start() == date(2026, 10, 1)
        assert _period_start() == _current_period_start()


def test_merged_submission_message_dated_with_warsaw_day():
    from app.api.application_submissions import _append_submission_message

    with time_machine.travel(AFTER_WARSAW_MIDNIGHT, tick=False):
        assert _append_submission_message(None, " Cześć ") == "[2026-09-25] Cześć"
        assert (
            _append_submission_message("O mnie ", "Cześć")
            == "O mnie\n\n[2026-09-25] Cześć"
        )


def test_branded_cv_filename_dated_with_warsaw_day():
    from app.services.candidate_stage_cv_service import branded_cv_filename

    with time_machine.travel(AFTER_WARSAW_MIDNIGHT, tick=False):
        assert (
            branded_cv_filename("Jan_Kowalski", 3)
            == "cv_brandowane_Jan_Kowalski_v3_2026-09-25.html"
        )


def test_portfolio_msa_starting_today_is_active_after_warsaw_midnight():
    from app.models.client_framework_contract import FrameworkContractStatus
    from app.services.client_portfolio_import import _application_date, _msa_status

    with time_machine.travel(AFTER_WARSAW_MIDNIGHT, tick=False):
        today = _application_date()
        assert today == date(2026, 9, 25)
        assert (
            _msa_status(date(2026, 9, 25), None, today)
            == FrameworkContractStatus.active
        )


async def test_client_trend_ends_with_warsaw_month(monkeypatch):
    from app.api import reports

    calls = []

    async def fake_hit_ratio(db, *, period_start, period_end, only_client_id):
        calls.append((period_start, period_end))
        return [], None

    monkeypatch.setattr(reports, "_compute_client_hit_ratio", fake_hit_ratio)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: 7)

    with time_machine.travel(AFTER_WARSAW_MONTH_START, tick=False):
        result = await reports.report_client_trend(
            client_id=7, current_user=None, db=db, months=2
        )

    assert [row["month"] for row in result["trend"]] == ["2026-09", "2026-10"]
    # Granice miesięcy to północ warszawska (CEST = UTC+2).
    assert calls[-1] == (
        datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc),
    )


async def test_order_mail_proposal_uses_warsaw_day(monkeypatch):
    from app.services import order_mail_ingest, order_types

    captured = {}

    def fake_plan_document(**kwargs):
        captured.update(kwargs)
        return "plan"

    monkeypatch.setattr(order_mail_ingest, "load_roster", AsyncMock(return_value=[]))
    monkeypatch.setattr(order_mail_ingest, "resolve_rows", lambda rows, roster: [])
    monkeypatch.setattr(order_mail_ingest, "plan_document", fake_plan_document)
    monkeypatch.setattr(
        order_types,
        "suggested_order_type",
        AsyncMock(return_value=SimpleNamespace(value="periodic")),
    )

    with time_machine.travel(AFTER_WARSAW_MIDNIGHT, tick=False):
        proposal, _, _ = await order_mail_ingest.current_proposal(
            AsyncMock(), SimpleNamespace(consultant_rows=[]), 123456
        )

    assert proposal == "plan"
    assert captured["today"] == date(2026, 9, 25)


async def test_engagement_inventory_today_is_warsaw_day():
    from app.api import admin_engagement_inventory as inventory

    assert not any("CURRENT_DATE" in sql for *_, sql in inventory._CHECKS)

    seen = {}

    async def fake_execute(statement, params):
        seen.update(params)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))

    db = SimpleNamespace(execute=fake_execute)
    key, severity, description, sql = next(
        check for check in inventory._CHECKS if check[0] == "active_before_start_date"
    )
    with time_machine.travel(AFTER_WARSAW_MIDNIGHT, tick=False):
        result = await inventory._run_check(db, key, severity, description, sql)

    assert result["count"] == 0 and "error" not in result
    assert ":today" in sql
    assert seen["today"] == date(2026, 9, 25)
