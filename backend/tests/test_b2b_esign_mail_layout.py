"""Wygląd maili podpisu umowy B2B (uwaga Klaudii 27.10.2026).

Mail „Umowa B2B do podpisu” miał dwa pożegnania („Pozdrawiamy, B2B Network”
nad stopką Outlooka nadawcy), pełne imię i nazwisko w powitaniu, link w
środku akapitu i treść domyślną czcionką, bo wysyłka wycinała style.
Teraz wszystkie cztery maile obiegu mają jeden wzór: bez pożegnania
(zamyka je stopka), z przyciskiem i stylami, które przechodzą przez wysyłkę.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.b2b_esign import mail as esign_mail
from app.services.m365.html_sanitize import sanitize_signature_html

URL = "https://nexus.example.test/sign/b2b/tok123"
SENT = datetime(2026, 10, 27, 9, 14, tzinfo=timezone.utc)
# 01.11 23:30 UTC = 02.11 00:30 w Warszawie (poniedziałek).
EXPIRES = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)


def _all_messages() -> list[tuple[str, str]]:
    return [
        esign_mail.contractor_sign_message(
            number="1555/2026", url=URL, expires_at=EXPIRES
        ),
        esign_mail.contractor_reminder_message(
            number="1555/2026", sent_at=SENT, expires_at=EXPIRES
        ),
        esign_mail.company_signer_message(
            number="1555/2026",
            contractor_name="Jan Testowy",
            since=SENT,
            reminder=False,
        ),
        esign_mail.company_signer_message(
            number="1555/2026", contractor_name="Jan Testowy", since=SENT, reminder=True
        ),
        esign_mail.contractor_copy_message(number="1555/2026"),
    ]


@pytest.mark.parametrize("message", _all_messages())
def test_no_second_sign_off_above_the_outlook_signature(message):
    _subject, body = message
    assert "Pozdrawiamy" not in body
    assert "B2B Network</p>" not in body


def test_contractor_mail_greets_without_full_name_and_shows_button_and_deadline():
    subject, body = esign_mail.contractor_sign_message(
        number="1555/2026", url=URL, expires_at=EXPIRES
    )
    assert subject == "Umowa B2B nr 1555/2026 do podpisu"
    assert ">Dzień dobry,</p>" in body
    assert "przesyłam do podpisu umowę o współpracy B2B nr" in body
    assert f'href="{URL}"' in body
    assert "Otwórz umowę do podpisu" in body
    assert "poniedziałku 02.11.2026" in body
    assert "<ol" in body


def test_styles_survive_the_sending_sanitizer():
    _subject, body = esign_mail.contractor_sign_message(
        number="1555/2026", url=URL, expires_at=EXPIRES
    )
    cleaned = sanitize_signature_html(body)
    assert "background-color: #c8102e" in cleaned
    assert "font-family" in cleaned
    assert f'href="{URL}"' in cleaned


def test_reminder_points_to_the_first_mail_and_the_deadline():
    subject, body = esign_mail.contractor_reminder_message(
        number="1555/2026", sent_at=SENT, expires_at=EXPIRES
    )
    assert subject == "Przypomnienie: umowa B2B nr 1555/2026 czeka na podpis"
    assert "27.10.2026" in body
    assert "poniedziałku 02.11.2026" in body


def test_company_signer_mail_is_internal_with_button_and_escaped_name():
    _subject, body = esign_mail.company_signer_message(
        number="1555/2026",
        contractor_name="<script>x</script>",
        since=SENT,
        reminder=False,
    )
    assert ">Cześć,</p>" in body
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "podpisał(a)" not in body
    assert esign_mail.REGISTER_PATH.split("?")[0] in body
    assert "background-color" in body


def test_copy_mail_mentions_the_30_day_link():
    _subject, body = esign_mail.contractor_copy_message(number="1555/2026")
    assert ">Dzień dobry,</p>" in body
    assert "30 dni" in body


@pytest.mark.asyncio
async def test_send_from_keeps_template_styles(monkeypatch):
    captured: dict[str, Any] = {}

    async def _send_new(db, connection, **kwargs):  # noqa: ANN001
        captured.update(kwargs)

    class _Db:
        async def scalar(self, _stmt):  # noqa: ANN001
            return SimpleNamespace(is_active=True)

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(esign_mail.m365_sender, "send_new", _send_new)
    sent, problem = await esign_mail.send_from(
        _Db(),
        user_id=1,
        to="kontraktor@example.com",
        subject="Temat",
        body_html="<p>x</p>",
        candidate_id=None,
        request_key="k",
    )
    assert (sent, problem) == (True, None)
    assert captured["styled_body"] is True
