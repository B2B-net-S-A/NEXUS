"""Dwa adresy administracji: widoczny dla ludzi i skrzynka M365 NEXUSA.

Od 18.10.2026 administracja@ zostaje na home.pl, a NEXUS czyta kopię poczty
w osobnej skrzynce M365 (wariant B). Autoodpowiedź i Reply-To mają pokazywać
adres, który ludzie czytają; czytnik spraw i wysyłka idą przez skrzynkę M365.
Pusta jedna zmienna = obie role ma druga (skrzynka przeniesiona do M365).
Graph jest podmieniony ``httpx.MockTransport``; nic nie wychodzi.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.services.admin_cases import mail_ingest
from app.services.admin_cases import mailbox as admin_mailbox
from app.services.care import announcement_mail
from app.services.hr.m365 import auth as m365_auth

PUBLIC = "administracja@example.com"
COPY = "nexus-administracja@example.com"
_REAL_CLIENT = httpx.AsyncClient


def _set(monkeypatch, *, public: str, m365: str) -> None:
    monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", public)
    monkeypatch.setattr(settings, "ADMIN_CASES_M365_MAILBOX", m365)


@pytest.mark.parametrize(
    ("public", "m365", "expected_public", "expected_m365"),
    [
        (PUBLIC, COPY, PUBLIC, COPY),
        (PUBLIC, "", PUBLIC, PUBLIC),
        ("", COPY, COPY, COPY),
        ("  ", " ", None, None),
    ],
)
def test_each_role_falls_back_to_the_other_address(
    monkeypatch, public, m365, expected_public, expected_m365
) -> None:
    _set(monkeypatch, public=public, m365=m365)
    assert admin_mailbox.public_address() == expected_public
    assert admin_mailbox.m365_mailbox() == expected_m365


def test_reader_reads_the_m365_mailbox_not_the_public_address(monkeypatch) -> None:
    monkeypatch.setenv(mail_ingest.MAILBOX_ENV, PUBLIC)
    monkeypatch.setenv(mail_ingest.M365_MAILBOX_ENV, COPY)
    monkeypatch.setenv(mail_ingest.ENABLED_ENV, "true")
    assert mail_ingest.mailbox_upn() == COPY
    assert mail_ingest.ingest_enabled() is True


def test_reader_without_m365_mailbox_reads_the_single_address(monkeypatch) -> None:
    monkeypatch.setenv(mail_ingest.MAILBOX_ENV, PUBLIC)
    monkeypatch.setenv(mail_ingest.M365_MAILBOX_ENV, "")
    assert mail_ingest.mailbox_upn() == PUBLIC


def test_reader_stays_off_without_any_mailbox(monkeypatch) -> None:
    monkeypatch.delenv(mail_ingest.MAILBOX_ENV, raising=False)
    monkeypatch.delenv(mail_ingest.M365_MAILBOX_ENV, raising=False)
    monkeypatch.setenv(mail_ingest.ENABLED_ENV, "true")
    assert mail_ingest.mailbox_upn() is None
    assert mail_ingest.ingest_enabled() is False


def _graph(monkeypatch) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def factory(*args, **kwargs):
        def route(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(202)

        return _REAL_CLIENT(*args, transport=httpx.MockTransport(route), **kwargs)

    monkeypatch.setattr(announcement_mail.httpx, "AsyncClient", factory)
    monkeypatch.setattr(m365_auth, "acquire_hr_token", lambda **_: "token")
    return calls


@pytest.mark.asyncio
async def test_mail_goes_from_m365_mailbox_with_reply_to_public_address(
    monkeypatch,
) -> None:
    calls = _graph(monkeypatch)
    outcome = await announcement_mail.GraphMailer(COPY, reply_to=PUBLIC).send(
        to="anna.przykladowa@example.com", subject="Temat", text="Treść"
    )
    assert outcome.status == "accepted"
    (request,) = calls
    assert request.url.path.endswith(f"/users/{COPY}/sendMail")
    message = json.loads(request.content)["message"]
    assert message["replyTo"] == [{"emailAddress": {"address": PUBLIC}}]


@pytest.mark.asyncio
async def test_single_mailbox_sends_without_reply_to(monkeypatch) -> None:
    calls = _graph(monkeypatch)
    await announcement_mail.GraphMailer(PUBLIC, reply_to=PUBLIC.upper()).send(
        to="anna.przykladowa@example.com", subject="Temat", text="Treść"
    )
    (request,) = calls
    assert "replyTo" not in json.loads(request.content)["message"]


def test_live_mailer_uses_m365_mailbox_and_shows_public_address(monkeypatch) -> None:
    _set(monkeypatch, public=PUBLIC, m365=COPY)
    monkeypatch.setattr(announcement_mail, "transport_mode", lambda: "live")
    monkeypatch.setattr(m365_auth, "credentials_configured", lambda: True)
    mailer = announcement_mail.default_mailer()
    assert isinstance(mailer, announcement_mail.GraphMailer)
    assert mailer._mailbox == COPY
    assert mailer._reply_to == PUBLIC
    assert announcement_mail.sender_address() == PUBLIC
