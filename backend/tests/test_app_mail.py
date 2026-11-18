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
        "M365_APP_MAIL_CLIENT_ID": "",
        "M365_APP_MAIL_CLIENT_SECRET": "",
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


def test_sender_credentials_are_separate_from_order_mail(monkeypatch):
    _configure(
        monkeypatch,
        M365_APP_MAIL_CLIENT_ID="sender-id",
        M365_APP_MAIL_CLIENT_SECRET="sender-secret",
    )
    assert app_mail._mail_credentials() == ("sender-id", "sender-secret")
    assert app_mail.is_configured() is True
    assert settings.M365_CLIENT_ID == "cid"


def test_partial_sender_credentials_fail_closed(monkeypatch):
    _configure(monkeypatch, M365_APP_MAIL_CLIENT_ID="sender-id")
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
        app_mail, "acquire_mail_token", lambda **kw: refreshes.append(kw) or "new"
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


@pytest.mark.parametrize("status", [502, 504])
def test_gateway_error_is_uncertain_not_a_refusal(monkeypatch, status):
    """Runda 7 (R7-N5-8): 502/504 z bramy — Graph mógł mail przyjąć, więc
    to nie jest pewna odmowa (ponowienie dałoby duplikat)."""
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    monkeypatch.setattr(app_mail.httpx, "post", lambda *a, **k: _FakeResp(status))
    assert not app_mail.send_via_graph_app(
        to="x@example.com", subject="s", text_body="b"
    )
    assert app_mail.last_delivery_uncertain()
    assert not app_mail.last_delivery_deferred()


@pytest.mark.parametrize("status,deferred", [(429, True), (503, True), (400, False)])
def test_explicit_refusal_marks_deferred_only_when_transient(
    monkeypatch, status, deferred
):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    monkeypatch.setattr(app_mail.httpx, "post", lambda *a, **k: _FakeResp(status))
    assert not app_mail.send_via_graph_app(
        to="x@example.com", subject="s", text_body="b"
    )
    assert not app_mail.last_delivery_uncertain()
    assert app_mail.last_delivery_deferred() is deferred


def test_open_circuit_marks_mail_as_deferred(monkeypatch):
    """Runda 7 (R7-N5-2): bezpiecznik zamknięty = mail na pewno nie wyszedł."""
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail.mail_circuit, "acquire", lambda: None)
    monkeypatch.setattr(
        app_mail.httpx, "post", lambda *a, **kw: pytest.fail("must not send")
    )
    assert not app_mail.send_via_graph_app(
        to="x@example.com", subject="s", text_body="b"
    )
    assert app_mail.last_delivery_deferred()
    assert not app_mail.last_delivery_uncertain()


def _mime_from(captured):
    import base64
    from email import message_from_bytes, policy

    return message_from_bytes(base64.b64decode(captured["content"]), policy=policy.default)


def test_list_unsubscribe_sends_mime_with_text_part_and_one_click(monkeypatch):
    """Maile do kandydatów (17.11.2026): Graph JSON nie przyjmuje nagłówka
    List-Unsubscribe (tylko ``x-*``), więc idzie MIME z częścią tekstową."""
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None, content=None):
        captured.update(url=url, json=json, headers=headers, content=content)
        return _FakeResp(202)

    monkeypatch.setattr(app_mail.httpx, "post", _fake_post)
    ok = app_mail.send_via_graph_app(
        to="kandydat@example.com",
        subject="Dziękujemy za zgłoszenie",
        text_body="Zwykły tekst ąę",
        html_body="<p>Bogaty ąę</p>",
        sender_upn="kariera@example.com",
        list_unsubscribe="https://api.example.com/api/public/candidate-terms/abc/opt-out",
    )
    assert ok is True
    assert captured["url"].endswith("/users/kariera@example.com/sendMail")
    assert captured["json"] is None
    assert captured["headers"]["Content-Type"] == "text/plain"
    msg = _mime_from(captured)
    assert msg["From"] == "kariera@example.com"
    assert msg["To"] == "kandydat@example.com"
    assert msg["Subject"] == "Dziękujemy za zgłoszenie"
    assert msg["Reply-To"] is None
    assert msg["List-Unsubscribe"] == (
        "<https://api.example.com/api/public/candidate-terms/abc/opt-out>"
    )
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg.get_content_type() == "multipart/alternative"
    assert msg.get_body(("plain",)).get_content().strip() == "Zwykły tekst ąę"
    assert msg.get_body(("html",)).get_content().strip() == "<p>Bogaty ąę</p>"


def test_long_list_unsubscribe_stays_plain_ascii_in_raw_mime(monkeypatch):
    """T3 18.11.2026: adres wypisu z prawdziwym tokenem ma ponad 78 znaków,
    a ``policy.SMTP`` kodował go wtedy jako ``=?utf-8?q?...?=``. Gmail nie
    rozpoznaje takiego nagłówka jako wypisu, więc w surowym MIME musi stać
    dosłowny ``<https://...>``."""
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None, content=None):
        captured.update(content=content)
        return _FakeResp(202)

    monkeypatch.setattr(app_mail.httpx, "post", _fake_post)
    url = (
        "https://api.nexus.example.com/api/public/candidate-terms/"
        + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
        + "/opt-out"
    )
    assert app_mail.send_via_graph_app(
        to="k@example.com", subject="Dziękujemy za zgłoszenie", text_body="t",
        html_body="<p>h</p>", sender_upn="kariera@example.com", list_unsubscribe=url,
    )
    import base64

    raw = base64.b64decode(captured["content"])
    assert f"\r\nList-Unsubscribe: <{url}>\r\n".encode() in raw
    assert b"\r\nList-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n" in raw


def test_mime_retry_after_401_resends_the_same_body(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "old")
    monkeypatch.setattr(app_mail, "acquire_mail_token", lambda force_refresh=False: "new")
    bodies = []

    def _fake_post(url, json=None, headers=None, timeout=None, content=None):
        bodies.append(content)
        return _FakeResp(401 if len(bodies) == 1 else 202)

    monkeypatch.setattr(app_mail.httpx, "post", _fake_post)
    assert app_mail.send_via_graph_app(
        to="k@example.com", subject="s", text_body="t", html_body="<p>h</p>",
        list_unsubscribe="https://api.example.com/u",
    )
    assert len(bodies) == 2 and bodies[0] == bodies[1] and bodies[0]


def test_smtp_message_carries_list_unsubscribe(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "nexus@example.com")
    msg = email_mod._build_message(
        "k@example.com", "s", "t", "<p>h</p>", None,
        list_unsubscribe="https://api.example.com/u",
    )
    assert msg["List-Unsubscribe"] == "<https://api.example.com/u>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    plain = email_mod._build_message("k@example.com", "s", "t")
    assert plain["List-Unsubscribe"] is None
