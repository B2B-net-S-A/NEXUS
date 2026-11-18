"""A callback is not equivalent to a business write (Grok audit 17.11.2026)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.api.sales_bots import _run_out
from app.models.sales import SalesSignalRun
from app.services.sales.bot_health import received_outcome


@pytest.mark.parametrize(
    ("kind", "source", "report", "expected"),
    [
        ("lists", None, {"firms": 5, "added": 0, "skipped": {}}, "no_changes"),
        ("lists", None, {"firms": 5, "added": 3}, "saved"),
        ("enrich", None, {"applied_fields": 0, "kept_fields": 4}, "no_changes"),
        ("enrich", None, {"applied_fields": 2, "kept_fields": 4}, "saved"),
        ("enrich", None, {"applied_fields": 2, "invalid_fields": 1}, "partial"),
        ("people", "public", {"added": 0, "waiting": 1}, "partial"),
        ("people", "public", {"added": 2, "waiting": 0}, "saved"),
        ("people", "public", {"added": 0, "dropped": {"known": 3}}, "no_changes"),
        (
            "people",
            "cognism",
            {"processed": 0, "people": 0, "not_processed": 5},
            "partial",
        ),
        (
            "people",
            "cognism",
            {"processed": 5, "people": 0, "no_people": 5},
            "no_changes",
        ),
        ("people", "cognism", {"processed": 5, "people": 8}, "saved"),
        ("briefing", None, {"leads": 0, "briefings": 0, "hooks": 1}, "saved"),
        ("signals", None, {"leads": 1, "sent_firms": 5, "checked_firms": 2}, "partial"),
        (
            "signals",
            None,
            {"leads": 0, "dropped": {"nexus_clients": [{"company": "Client"}]}},
            "no_changes",
        ),
        ("question", None, {"answer_lines": 2, "results_new": 1}, "saved"),
        ("discovery", None, {"results_new": 0, "results": 3}, "no_changes"),
        ("enrich", None, {}, "received"),
    ],
)
def test_outcome_requires_recorded_writes_and_exposes_incomplete_work(
    kind, source, report, expected
):
    outcome, detail = received_outcome(kind, source, report)
    assert outcome == expected
    assert detail


def test_started_attempt_past_token_expiry_is_not_shown_as_still_waiting():
    now = datetime(2026, 11, 17, 20, tzinfo=timezone.utc)
    run = SalesSignalRun(
        id=30,
        kind="signals",
        status="started",
        started_at=now - timedelta(hours=3),
        token_expires_at=now - timedelta(hours=1),
        request={},
        report={},
    )
    assert _run_out(run, now=now).outcome == "expired"
    run.token_expires_at = now + timedelta(hours=1)
    assert _run_out(run, now=now).outcome == "waiting"


def test_checked_counter_does_not_hide_missing_company_results():
    outcome, _ = received_outcome(
        "enrich",
        None,
        {
            "applied_fields": 2,
            "sent_firms": 5,
            "checked_firms": 5,
            "researched_company_ids": [1, 2],
        },
    )
    assert outcome == "partial"
    # Hooks are stored separately and absent from researched_company_ids.
    outcome, _ = received_outcome(
        "briefing",
        None,
        {
            "leads": 0,
            "hooks": 2,
            "sent_firms": 2,
            "checked_firms": 2,
            "researched_company_ids": [],
        },
    )
    assert outcome == "saved"


def test_on_demand_success_remains_a_dated_attempt_not_a_guessed_health_deadline():
    now = datetime(2026, 11, 17, 20, tzinfo=timezone.utc)
    started = now - timedelta(days=30)
    run = SalesSignalRun(
        id=10,
        kind="question",
        status="received",
        started_at=started,
        received_at=started + timedelta(minutes=2),
        request={},
        report={"results_new": 1},
    )
    result = _run_out(run, now=now)
    assert result.outcome == "saved"
    assert result.started_at == started
