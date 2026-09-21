"""Testy app-only Graph mail (`app/services/m365/app_mail.py`) + routing send_email.

Czysto jednostkowe — bez DB i bez sieci (MSAL token i httpx.post mockowane).
"""

from __future__ import annotations

import app.services.email as email_mod
import app.services.m365.app_mail as app_mail
from app.core.config import settings


import pytest
from tests.test_mail_circuit import memory_circuit  # noqa: F401


@pytest.fixture(autouse=True)
def _durable_test_store(memory_circuit):  # noqa: F811
    return memory_circuit


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


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


def test_is_configured_true_with_full_config(monkeypatch):
    _configure(monkeypatch)
    assert app_mail.is_configured() is True


def test_is_configured_false_when_disabled(monkeypatch):
    _configure(monkeypatch, M365_APP_MAIL_ENABLED=False)
    assert app_mail.is_configured() is False


def test_is_configured_false_on_common_tenant(monkeypatch):
    # Pusty override tenanta → fallback na M365_TENANT_ID="common" → odrzucone.
    _configure(monkeypatch, M365_MAIL_TENANT_ID="", M365_TENANT_ID="common")
    assert app_mail.is_configured() is False


def test_is_configured_false_without_sender(monkeypatch):
    _configure(monkeypatch, M365_MAIL_SENDER_UPN="")
    assert app_mail.is_configured() is False


def test_send_via_graph_app_success_builds_payload(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResp(202)

    monkeypatch.setattr(app_mail.httpx, "post", _fake_post)

    ok = app_mail.send_via_graph_app(
        to="rec@example.com",
        subject="Deadline",
        text_body="plain",
        html_body="<p>rich</p>",
    )
    assert ok is True
    assert captured["url"].endswith("/users/nexus@example.com/sendMail")
    assert captured["headers"]["Authorization"] == "Bearer tok"
    msg = captured["json"]["message"]
    assert msg["subject"] == "Deadline"
    assert msg["body"] == {"contentType": "HTML", "content": "<p>rich</p>"}
    assert msg["toRecipients"] == [{"emailAddress": {"address": "rec@example.com"}}]
    assert captured["json"]["saveToSentItems"] is False


def test_send_via_graph_app_text_when_no_html(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _FakeResp(202)

    monkeypatch.setattr(app_mail.httpx, "post", _fake_post)
    ok = app_mail.send_via_graph_app(
        to="x@example.com", subject="s", text_body="only text"
    )
    assert ok is True
    assert captured["json"]["message"]["body"] == {
        "contentType": "Text",
        "content": "only text",
    }


def test_send_via_graph_app_returns_false_on_non_202(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    monkeypatch.setattr(
        app_mail.httpx, "post", lambda *a, **k: _FakeResp(403, "Forbidden")
    )
    assert (
        app_mail.send_via_graph_app(to="x@example.com", subject="s", text_body="t")
        is False
    )


def test_send_via_graph_app_returns_false_when_no_token(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: None)

    def _boom(*a, **k):  # brak tokenu → nie powinno dojść do POST
        raise AssertionError("httpx.post nie powinno być wołane bez tokenu")

    monkeypatch.setattr(app_mail.httpx, "post", _boom)
    assert (
        app_mail.send_via_graph_app(to="x@example.com", subject="s", text_body="t")
        is False
    )


def test_send_via_graph_app_returns_false_on_network_error(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")

    def _raise(*a, **k):
        raise app_mail.httpx.ConnectError("timeout")

    monkeypatch.setattr(app_mail.httpx, "post", _raise)
    assert (
        app_mail.send_via_graph_app(to="x@example.com", subject="s", text_body="t")
        is False
    )


def test_send_via_graph_app_noop_when_not_configured(monkeypatch):
    _configure(monkeypatch, M365_APP_MAIL_ENABLED=False)

    def _boom(*a, **k):  # nie powinno być wołane
        raise AssertionError("httpx.post nie powinno być wołane gdy nieskonfigurowane")

    monkeypatch.setattr(app_mail.httpx, "post", _boom)
    assert (
        app_mail.send_via_graph_app(to="x@example.com", subject="s", text_body="t")
        is False
    )


def test_send_email_routes_to_graph_and_skips_smtp(monkeypatch):
    _configure(monkeypatch)
    # SMTP celowo "włączony" — routing i tak ma wybrać Graph, nie smtplib.
    monkeypatch.setattr(settings, "SMTP_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")

    calls = []
    monkeypatch.setattr(
        app_mail,
        "send_via_graph_app",
        lambda **kw: calls.append(kw) or True,
    )

    def _no_smtp(*a, **k):
        raise AssertionError("smtplib nie powinno być użyte gdy Graph app-mail ON")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _no_smtp)

    ok = email_mod.send_email("to@example.com", "Subj", "body", "<p>body</p>")
    assert ok is True
    assert calls and calls[0]["to"] == "to@example.com"


def test_email_channel_enabled_true_for_graph(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "SMTP_ENABLED", False)
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert email_mod.email_channel_enabled() is True


def test_email_channel_enabled_false_when_nothing_configured(monkeypatch):
    _configure(monkeypatch, M365_APP_MAIL_ENABLED=False)
    monkeypatch.setattr(settings, "SMTP_ENABLED", False)
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert email_mod.email_channel_enabled() is False


def test_401_refreshes_once_then_recovers(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "old")
    refreshes, requests = [], []
    monkeypatch.setattr(
        app_mail, "acquire_app_token", lambda **kw: refreshes.append(kw) or "new"
    )

    def post(*args, **kwargs):
        requests.append(kwargs)
        return _FakeResp(401 if len(requests) == 1 else 202)

    monkeypatch.setattr(app_mail.httpx, "post", post)
    assert app_mail.send_via_graph_app(
        to="synthetic@example.com", subject="s", text_body="b"
    )
    assert refreshes == [{"force_refresh": True}]
    assert len(requests) == 2
    assert requests[1]["headers"]["Authorization"] == "Bearer new"


def test_read_timeout_is_uncertain_but_connect_error_is_not(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")

    def timeout(*a, **kw):
        raise app_mail.httpx.ReadTimeout("synthetic private body")

    monkeypatch.setattr(app_mail.httpx, "post", timeout)
    assert not app_mail.send_via_graph_app(
        to="x@example.com", subject="s", text_body="b"
    )
    assert app_mail.last_delivery_uncertain()
    # A blocked call is explicitly not an attempted/ambiguous POST.
    assert not app_mail.send_via_graph_app(
        to="x@example.com", subject="s", text_body="b"
    )
    assert not app_mail.last_delivery_uncertain()


def test_repeated_denial_emits_one_sentry_event_and_no_private_logs(
    monkeypatch, caplog
):
    import sentry_sdk

    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    posts, events = [], []
    monkeypatch.setattr(
        sentry_sdk, "capture_message", lambda *a, **kw: events.append(a)
    )

    def post(*a, **kw):
        posts.append(1)
        return _FakeResp(403, "private@example.com token=synthetic_secret")

    monkeypatch.setattr(app_mail.httpx, "post", post)
    for _ in range(50):
        assert not app_mail.send_via_graph_app(
            to="private@example.com",
            subject="private subject",
            text_body="private body",
        )
    assert len(posts) == len(events) == 1
    assert "private" not in caplog.text and "synthetic_secret" not in caplog.text


def test_gate_unavailable_does_not_send_or_report_success(monkeypatch):
    _configure(monkeypatch)

    def failed():
        raise RuntimeError("private database connection")

    monkeypatch.setattr(app_mail.mail_circuit, "acquire", failed)
    monkeypatch.setattr(
        app_mail.httpx, "post", lambda **kw: pytest.fail("must not send")
    )
    assert not app_mail.send_via_graph_app(
        to="x@example.com", subject="s", text_body="b"
    )
