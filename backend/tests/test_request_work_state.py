"""Stan requestu (0371): widoczny stan i podpowiedź dla DL — czyste reguły."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.request_work_state import (
    WorkSignals,
    suggest,
    visible_state,
)

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
CASES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "frontend/src/lib/__fixtures__/request-work-state-cases.json"
    ).read_text()
)["cases"]


def _signals(*, age=None, work=None, cv=None) -> WorkSignals:
    ago = lambda days: None if days is None else NOW - timedelta(days=days)  # noqa: E731
    return WorkSignals(
        job_id=1,
        opened_at=ago(age),
        last_work_at=ago(work),
        last_cv_at=ago(cv),
        applications_14d=0,
        sent_total=0 if cv is None else 1,
    )


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES)
def test_visible_state_matches_shared_cases(case) -> None:
    champion = NOW if case["champion"] else None
    assert visible_state(case["work_state"], champion) == case["visible"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "signals,expected",
    [
        (_signals(age=200, work=3, cv=5), "searching"),
        (_signals(age=5), "searching"),
        (_signals(age=200, work=10), "searching"),
        (_signals(age=200, work=45, cv=45), "client_silent"),
        (_signals(age=400, work=120, cv=150), "finished"),
        (_signals(age=400), "finished"),
        (_signals(age=400, work=60), "client_silent"),
        (_signals(age=60, work=20, cv=20), None),
    ],
    ids=[
        "fresh-cv",
        "new-request",
        "recruiter-worked-recently",
        "cv-then-silence",
        "cv-long-ago-dead",
        "never-worked",
        "no-cv-quiet",
        "ambiguous",
    ],
)
def test_suggestion(signals, expected) -> None:
    assert suggest(signals, NOW).state == expected


@pytest.mark.unit
def test_suggestion_always_explains_itself() -> None:
    assert suggest(_signals(age=200, work=45, cv=45), NOW).reason.startswith(
        "CV wysłane 45 dni temu"
    )
