"""Tests for per-provider AI health tracking and call_claude wiring."""

from __future__ import annotations

import pytest

from app.services import claude_client
from app.services.ai_health import (
    provider_health_label,
    provider_observed,
    provider_status,
    record_provider_call,
    reset_providers_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_providers():
    reset_providers_for_tests()
    yield
    reset_providers_for_tests()


def test_unknown_provider_is_ok():
    assert provider_status("never-seen") == "ok"


def test_three_consecutive_failures_trip_down():
    for _ in range(3):
        record_provider_call("p", 10, failed=True)
    assert provider_status("p") == "down"


def test_success_after_failures_recovers():
    for _ in range(3):
        record_provider_call("p", 10, failed=True)
    record_provider_call("p", 10, failed=False)
    assert provider_status("p") == "ok"


def test_providers_are_isolated():
    for _ in range(3):
        record_provider_call("a", 10, failed=True)
    assert provider_status("a") == "down"
    assert provider_status("b") == "ok"


# ── "never called" must not read as "healthy" ────────────────────────────────


def test_never_called_provider_is_not_observed():
    """`provider_status` says "ok" for a provider nobody ever called.

    That is the shape of every false-green outage — the probe reports success
    because it has nothing to report. `provider_observed` is what lets the
    healthcheck tell the two apart.
    """
    assert provider_status("never-seen") == "ok"
    assert provider_observed("never-seen") is False
    assert provider_health_label("never-seen") == "unknown"


def test_health_label_reports_unknown_until_first_call():
    assert provider_health_label("voyage") == "unknown"
    record_provider_call("voyage", 10, failed=False)
    assert provider_health_label("voyage") == "healthy"


def test_health_label_reports_unhealthy_after_failure_streak():
    for _ in range(3):
        record_provider_call("voyage", 10, failed=True)
    assert provider_observed("voyage") is True
    assert provider_health_label("voyage") == "unhealthy"


def test_health_label_reports_degraded_on_slow_streak():
    for _ in range(3):
        record_provider_call("qdrant", 6000, failed=False)
    assert provider_health_label("qdrant") == "degraded"


def test_observation_survives_recovery():
    """Recovering to healthy must not reset "has been observed" — otherwise a
    provider would flip back to `unknown` the moment it started working."""
    record_provider_call("reranker", 10, failed=True)
    record_provider_call("reranker", 10, failed=False)
    assert provider_observed("reranker") is True
    assert provider_health_label("reranker") == "healthy"


# ── call_claude wiring ───────────────────────────────────────────────────────


class _FakeErr(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(str(status_code))
        self.status_code = status_code


class _FakeMessage:
    content = [type("Block", (), {"text": "ok"})()]


def _install_client(monkeypatch, side_effects):
    calls = {"n": 0}

    class _Msgs:
        def create(self, **_kwargs):
            i = calls["n"]
            calls["n"] += 1
            effect = side_effects[i]
            if isinstance(effect, Exception):
                raise effect
            return effect

    class _Client:
        def __init__(self, **_kwargs) -> None:
            self.messages = _Msgs()

    monkeypatch.setattr(claude_client.anthropic, "Anthropic", _Client)
    monkeypatch.setattr(claude_client.time, "sleep", lambda *_a, **_k: None)
    return calls


def test_call_claude_success_records_healthy(monkeypatch):
    _install_client(monkeypatch, [_FakeMessage()])
    claude_client.call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="m",
        max_tokens=10,
        api_key="k",
    )
    assert provider_status("claude") == "ok"


def test_call_claude_repeated_failures_trip_claude_down(monkeypatch):
    _install_client(monkeypatch, [_FakeErr(529), _FakeErr(529), _FakeErr(529)])
    for _ in range(3):
        with pytest.raises(_FakeErr):
            claude_client.call_claude(
                messages=[{"role": "user", "content": "x"}],
                model="m",
                max_tokens=10,
                api_key="k",
                max_retries=0,
            )
    assert provider_status("claude") == "down"


# ── /api/health `ai_features` probe ──────────────────────────────────────────
#
# Both cases below were live defects on prod (2026-08-10), and both were
# invisible: the probe answered `unknown` and `healthy` respectively, and
# neither value looks like a bug to an operator.


def _uncapped_from(limits: dict[str, int]) -> list[str]:
    """Mirror of the probe's classification in `app/main.py`.

    Kept as a pure function so the rule can be tested without standing up the
    app; `test_probe_source_matches_this_rule` pins it to the real source.
    """
    from app.models.ai_feature import AIFeatureKey

    return sorted(k.value for k in AIFeatureKey if limits.get(k.value, 0) <= 0)


def test_zero_monthly_limit_counts_as_uncapped():
    """`monthly_limit = 0` means unlimited — a row is not a ceiling.

    Prod had all 19 features configured at 0 while the probe reported
    `healthy`: a green light on a system with no spending ceiling anywhere.
    """
    from app.models.ai_feature import AIFeatureKey

    all_zero = {k.value: 0 for k in AIFeatureKey}
    assert _uncapped_from(all_zero) == sorted(k.value for k in AIFeatureKey)

    all_capped = {k.value: 100 for k in AIFeatureKey}
    assert _uncapped_from(all_capped) == []


def test_missing_row_still_counts_as_uncapped():
    """Fail-open: no row means no ceiling, so it must stay reported."""
    from app.models.ai_feature import AIFeatureKey

    keys = [k.value for k in AIFeatureKey]
    limits = {k: 100 for k in keys[1:]}  # first key has no row at all
    assert _uncapped_from(limits) == [keys[0]]


def test_unknown_db_key_does_not_break_the_rule():
    """Prod holds 11 rows whose key the enum no longer has (`embeddings`, …).

    Reading the column as the enum type raised on those rows and turned the
    whole probe into `unknown`. A drift detector must survive the drift.
    """
    from app.models.ai_feature import AIFeatureKey

    limits = {k.value: 100 for k in AIFeatureKey}
    limits.update({"embeddings": 0, "reranking": 0, "matching": 0})
    assert _uncapped_from(limits) == []


def test_probe_source_matches_this_rule():
    """Guard the guard: the probe must read text + limit, not the enum type."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "main.py"
    text = src.read_text(encoding="utf-8")
    assert "cast(AIFeatureConfig.feature, Text)" in text, (
        "probe stopped reading the feature column as text — an orphan row will "
        "again turn the whole check into `unknown`"
    )
    assert "limits.get(k.value, 0) <= 0" in text, (
        "probe stopped treating monthly_limit=0 as uncapped — it will report "
        "healthy on a system with no ceiling"
    )
