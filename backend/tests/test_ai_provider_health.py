"""Tests for per-provider AI health tracking and call_claude wiring."""

from __future__ import annotations

import pytest

from app.services import claude_client
from app.services.ai_health import (
    CLAUDE_SLOW_THRESHOLD_MS,
    CONSECUTIVE_FAILURE_THRESHOLD,
    SLOW_THRESHOLD_MS,
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


# ── "slow" is a property of the provider, not of the module ─────────────────


def test_claude_is_not_degraded_by_ordinary_multi_second_calls():
    """Measured defect, not a hypothetical: prod said `"anthropic": "degraded"`.

    One module constant (5 s, sized for Voyage/Qdrant) judged every tracker, so
    three ORDINARY SUCCESSFUL Claude calls — the provider legitimately runs
    10-31+ s, which is why the HTTP timeouts were raised to 120 s — pinned the
    provider on yellow permanently. A probe that is always yellow teaches the
    operator to skip that line, which is how the next real outage goes unread.
    """
    for _ in range(5):
        record_provider_call("claude", 31_000, failed=False)
    assert provider_health_label("claude") == "healthy"


def test_retrieval_keeps_the_five_second_bar_while_claude_does_not():
    """Paired on purpose: the SAME latency, two verdicts.

    Six seconds is a broken retrieval call and an unremarkable LLM call. A
    single threshold cannot say both, so the pair is what proves the bar is
    per provider rather than merely raised for everyone.
    """
    for _ in range(3):
        record_provider_call("voyage", SLOW_THRESHOLD_MS + 1000, failed=False)
        record_provider_call("claude", SLOW_THRESHOLD_MS + 1000, failed=False)
    assert provider_health_label("voyage") == "degraded"
    assert provider_health_label("claude") == "healthy"


def test_claude_still_reports_degraded_when_calls_crawl_toward_the_timeout():
    """The wider bar is still a bar — otherwise the criterion is decoration.

    A call that SUCCEEDS a minute in is a provider about to start failing; the
    yellow light is worth having before the red one.
    """
    for _ in range(3):
        record_provider_call("claude", CLAUDE_SLOW_THRESHOLD_MS + 1000, failed=False)
    assert provider_health_label("claude") == "degraded"


def test_claude_failure_streak_still_reports_unhealthy():
    """Widening the slow bar must not blunt the error criterion.

    That criterion is what keeps a genuine outage distinguishable — the whole
    reason the slow one could be relaxed without losing anything.
    """
    for _ in range(CONSECUTIVE_FAILURE_THRESHOLD):
        record_provider_call("claude", 12_000, failed=True)
    assert provider_health_label("claude") == "unhealthy"


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


@pytest.fixture
def _declared_provider_call():
    """Deklaracja wywołania AI dla testów podmieniających KLIENTA SDK.

    Takie testy realnie wchodzą w `_assert_declared`, a CI biegnie od 0270
    z `AI_QUOTA_STRICT=true` — bez deklaracji padałyby na bramce kwot zamiast
    sprawdzać circuit breaker dostawcy. Nie autouse: w tym pliku są też testy
    czytające `main.py` jako tekst, którym kontekst jest niepotrzebny.
    """
    from datetime import date

    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import QuotaState, declared_call

    with declared_call(
        AIFeatureKey.scoring,
        user_id=None,
        state=QuotaState(used=1, limit=0, period_start=date(2026, 9, 1)),
    ):
        yield


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


def test_call_claude_success_records_healthy(monkeypatch, _declared_provider_call):
    _install_client(monkeypatch, [_FakeMessage()])
    claude_client.call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="m",
        max_tokens=10,
        api_key="k",
    )
    assert provider_status("claude") == "ok"


def test_call_claude_repeated_failures_trip_claude_down(
    monkeypatch, _declared_provider_call
):
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


# ── /api/health `ai_features` probe (C12) ────────────────────────────────────
#
# Do C12 ten check raportował `uncapped: <funkcje z monthly_limit=0>`. Brak
# sufitów jest jednak stanem ZAMIERZONYM od 24.08 (bez sufitów, zamiast tego
# alarm o skoku), więc ostrzeżenie było stałe i bezużyteczne — a jednocześnie
# NIE pokazywało, że sam alarm nie wystartował (03.09: `ai_spend_alerts` w
# `exited_cleanly`, brak SLACK_WEBHOOK_URL, health `healthy`). Teraz check
# raportuje STAN mechanizmu zastępczego: webhook + czy pętla biegnie.

_RUNNING = {"tasks": ["ai_spend_alerts", "calendar_reminder"]}
_STOPPED = {"tasks": ["calendar_reminder"], "exited_cleanly": ["ai_spend_alerts"]}
_FORBIDDEN_PREFIXES = ("unhealthy", "misconfigured", "critical", "crashed")


def test_ai_features_healthy_only_when_webhook_set_and_loop_runs():
    from app.services.background_task_health import spend_alarm_status

    assert spend_alarm_status(_RUNNING, webhook_set=True) == "healthy"


def test_ai_features_never_trips_uptime_probe_prefixes():
    """uptime-probe.yml:258 tworzy issue dla ^(unhealthy|misconfigured|critical
    |crashed). `ai_features` liczy się na KAŻDYM pollu, więc żaden jego stan nie
    może zaczynać się od tych prefiksów — inaczej brak webhooka (stan O-1)
    spamowałby issue co godzinę."""
    from app.services.background_task_health import spend_alarm_status

    for cls, webhook in [
        (_RUNNING, True),
        (_STOPPED, True),
        (_STOPPED, False),
        ({}, False),
    ]:
        val = spend_alarm_status(cls, webhook_set=webhook)
        assert not val.startswith(_FORBIDDEN_PREFIXES), val


def test_ai_features_names_the_missing_webhook():
    """Brak SLACK_WEBHOOK_URL = budżet AI bez alarmu — musi być WIDOCZNE, ale
    nie jako awaria (to stan-do-skonfigurowania, O-1)."""
    from app.services.background_task_health import spend_alarm_status

    val = spend_alarm_status(_STOPPED, webhook_set=False)
    assert "SLACK_WEBHOOK_URL" in val and "off" in val


def test_ai_features_flags_loop_down_despite_webhook():
    """Webhook ustawiony, a pętla nie biegnie — informacyjnie tu (alarm leci
    przez background_tasks), ale stan musi być czytelny, nie `healthy`."""
    from app.services.background_task_health import spend_alarm_status

    val = spend_alarm_status(_STOPPED, webhook_set=True)
    assert val != "healthy"
    assert not val.startswith(_FORBIDDEN_PREFIXES), val


def test_background_tasks_flags_stopped_alarm_only_when_webhook_set():
    """Config-bramka: cichy alarm alarmuje (issue) TYLKO gdy webhook jest — inaczej
    to stan O-1 i flagowanie go co godzinę byłoby fałszywym alarmem."""
    from app.services.background_task_health import stopped_webhook_alarms

    assert stopped_webhook_alarms(_STOPPED, webhook_set=True) == ["ai_spend_alerts"]
    assert stopped_webhook_alarms(_STOPPED, webhook_set=False) == []
    assert stopped_webhook_alarms(_RUNNING, webhook_set=True) == []


def test_probe_source_uses_the_shared_classifier():
    """Guard the guard: sonda `ai_features` i `background_tasks` w main.py MUSZĄ
    czytać wspólny klasyfikator, a nie wrócić do własnej, inline'owej logiki
    (dwie kopie rozjeżdżają się po cichu — to była przyczyna C12)."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "spend_alarm_status" in src, (
        "ai_features przestał raportować stan alarmu — wróci wieczny uncapped"
    )
    assert "stopped_webhook_alarms" in src, (
        "background_tasks przestał wykrywać cichy, krytyczny alarm"
    )
    assert "limits.get(k.value, 0) <= 0" not in src, (
        "wrócił martwy check `uncapped` (brak sufitów jest zamierzony od 24.08)"
    )
