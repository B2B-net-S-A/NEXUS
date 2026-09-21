"""Awaria wysyłki mailem systemowym musi być widoczna w `/api/health`.

Audyt 18.09.2026: 471 kolejnych `ErrorAccessDenied` z kanału app-only przy
`checks.m365 = healthy` — tamta sonda pyta o POŁĄCZENIA skrzynek rekruterów,
a zły nadawca (`M365_MAIL_SENDER_UPN` spoza polityki dostępu aplikacji) nie
dotyka żadnego z nich. Kod niepowodzenia kończył się jednym `logger.warning`
i `return False`, więc nic tej awarii nie podnosiło.

Czysto jednostkowe — bez DB i bez sieci.
"""

from __future__ import annotations

import pytest

import app.services.m365.app_mail as app_mail
from app.core.config import settings


from tests.test_mail_circuit import memory_circuit  # noqa: F401


@pytest.fixture(autouse=True)
def _durable_test_store(memory_circuit):  # noqa: F811
    return memory_circuit


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


@pytest.fixture(autouse=True)
def _clean_state(_durable_test_store):
    app_mail.reset_send_state()
    yield
    app_mail.reset_send_state()


def _configure(monkeypatch, **overrides):
    base = {
        "M365_APP_MAIL_ENABLED": True,
        "M365_MAIL_SENDER_UPN": "nexus@example.com",
        "M365_CLIENT_ID": "cid",
        "M365_CLIENT_SECRET": "secret",
        "M365_MAIL_TENANT_ID": "contoso.onmicrosoft.com",
        "M365_TENANT_ID": "common",
    }
    base.update(overrides)
    for k, v in base.items():
        monkeypatch.setattr(settings, k, v)


def _send(monkeypatch, status: int, text: str = "") -> bool:
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    monkeypatch.setattr(
        app_mail.httpx,
        "post",
        lambda *a, **kw: _FakeResp(status, text),
    )
    return app_mail.send_via_graph_app(
        to="dl@example.com", subject="temat", text_body="treść"
    )


# --- werdykt jako czysta funkcja -------------------------------------------


def test_unconfigured_channel_is_not_degraded():
    # Kanał wyłączony nie jest awarią — to stan, w którym maile po prostu
    # nie wychodzą tą drogą.
    verdict = app_mail.app_mail_send_verdict(
        app_mail.AppMailSendState(), configured=False
    )
    assert verdict == "unconfigured"


def test_configured_but_never_used_is_unknown_not_healthy():
    # Zdolności do wysyłki nie da się sprawdzić inaczej niż wysyłką, a sondowanie
    # jej pustym mailem wysyłałoby maile. `healthy` byłoby tu obietnicą bez pokrycia.
    verdict = app_mail.app_mail_send_verdict(
        app_mail.AppMailSendState(), configured=True
    )
    assert verdict == "unknown"


def test_single_failure_after_a_success_stays_healthy():
    # Graph oddaje 429/503 przy przeciążeniu; następna próba zwykle przechodzi.
    state = app_mail.AppMailSendState(
        attempts=10,
        failures=1,
        consecutive_failures=1,
        last_failure_code="http_503",
        last_success_at=1.0,
    )
    assert app_mail.app_mail_send_verdict(state, configured=True) == "healthy"


def test_streak_degrades_even_after_earlier_successes():
    state = app_mail.AppMailSendState(
        attempts=10,
        failures=3,
        consecutive_failures=app_mail.SEND_FAILURE_STREAK_DEGRADED,
        last_failure_code="http_403",
        last_success_at=1.0,
    )
    assert app_mail.app_mail_send_verdict(state, configured=True) == "degraded"


def test_channel_that_never_delivered_degrades_on_the_first_failure():
    # To jest kształt znalezionej awarii: zły nadawca, zero sukcesów. Czekanie
    # na trzecią próbę znaczyłoby, że zła konfiguracja przez chwilę wygląda
    # zdrowo — a tu nie ma czego ponawiać.
    state = app_mail.AppMailSendState(
        attempts=1, failures=1, consecutive_failures=1, last_failure_code="http_403"
    )
    assert app_mail.app_mail_send_verdict(state, configured=True) == "degraded"


# --- ścieżka wysyłki stempluje stan ----------------------------------------


def test_access_denied_run_turns_the_probe_red(monkeypatch):
    _configure(monkeypatch)
    for _ in range(3):
        assert (
            _send(monkeypatch, 403, '{"error":{"code":"ErrorAccessDenied"}}') is False
        )

    state = app_mail.send_state()
    assert state.attempts == 1
    assert state.failures == 1
    assert state.consecutive_failures == 1
    assert state.last_failure_code == "http_403"
    assert state.last_success_at is None
    assert app_mail.send_health_status() == "degraded"


def test_success_clears_the_streak(monkeypatch, memory_circuit):  # noqa: F811
    _configure(monkeypatch)
    _send(monkeypatch, 403)
    _send(monkeypatch, 403)
    assert app_mail.send_health_status() == "degraded"

    memory_circuit[1][0] += 901
    assert _send(monkeypatch, 202) is True
    state = app_mail.send_state()
    assert state.consecutive_failures == 0
    assert state.last_success_at is not None
    # Historyczne porażki zostają w liczniku — kasujemy streak, nie pamięć.
    assert state.failures == 1
    assert app_mail.send_health_status() == "healthy"


def test_transport_error_counts_as_a_failed_send(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")

    def _boom(*a, **kw):
        raise TimeoutError("read timeout")

    monkeypatch.setattr(app_mail.httpx, "post", _boom)
    assert (
        app_mail.send_via_graph_app(to="dl@example.com", subject="t", text_body="b")
        is False
    )
    state = app_mail.send_state()
    assert state.consecutive_failures == 1
    assert state.last_failure_code == "delivery_uncertain"


def test_token_failure_counts_as_a_failed_send(monkeypatch):
    # Brak tokenu to też „mail nie wyszedł”. Gdyby nie liczyło się jako porażka,
    # kanał z odrzuconym sekretem aplikacji wyglądałby na nieużywany.
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: None)
    assert (
        app_mail.send_via_graph_app(to="dl@example.com", subject="t", text_body="b")
        is False
    )
    assert app_mail.send_state().last_failure_code == "token"
    assert app_mail.send_health_status() == "degraded"


def test_unconfigured_send_does_not_pollute_the_counter(monkeypatch):
    # Pominięcie wysyłki przy wyłączonym kanale nie jest próbą — inaczej każdy
    # caller na środowisku bez M365 zapalałby sondę.
    _configure(monkeypatch, M365_APP_MAIL_ENABLED=False)
    assert (
        app_mail.send_via_graph_app(to="dl@example.com", subject="t", text_body="b")
        is False
    )
    assert app_mail.send_state().attempts == 0
    assert app_mail.send_health_status() == "unconfigured"


def test_state_carries_no_recipient_or_subject(monkeypatch):
    # Stan jedzie do `/api/health`, który czyta uptime-probe i logi Actions.
    _configure(monkeypatch)
    _send(monkeypatch, 403, "kowalski@klient.pl nie ma uprawnień")
    blob = repr(app_mail.send_state())
    assert "dl@example.com" not in blob
    assert "kowalski" not in blob
    assert "temat" not in blob
