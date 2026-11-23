"""Czytnik rozliczeń: mail koordynatora z godzinami zaakceptowanymi przez klienta (z bazą).

Skrzynka to atrapa, dane fikcyjne. Decyzja Artura z 23.11.2026: CeZ za X 2026
nie miał podpisanego protokołu umowy, a Finanse wystawiły fakturę z maila
koordynatorki do rozliczenia@ („Zaakceptowane godziny … Październik 2026”,
wiersz „Imię Nazwisko: 176 h” na osobę). Taki mail jest dowodem godzin każdej
osoby z listy; „czekamy” = osoba bez dokumentu.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    care_on,
    make_client,
    make_consultant,
    tag,
)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    portal_all,
    portal_restored,
)
from tests.test_consultant_portal_zip_mail_db import (  # noqa: F401  (fixture'y)
    DOMAIN,
    FakeMailbox,
    _config,
    _consultant,
    _fresh_state,
    _message,
    _of_contract,
    _read,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("care_on", "portal_all"),
]

SUBJECT = "Zaakceptowane godziny przez cez: Umowa nr CeZ 99 2025 - Październik 2026"


class MimeMailbox(FakeMailbox):
    def __init__(self, messages, raw) -> None:
        super().__init__(messages, {})
        self.raw = raw

    async def mime(self, message_id):
        return self.raw.get(message_id)


def _eml(sender: str, subject: str, body: str) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = f"rozliczenia@{DOMAIN}"
    message.set_content(body)
    return message.as_bytes()


def _no_file(message_id: str, sender: str, subject: str) -> dict:
    return {**_message(message_id, sender, subject), "hasAttachments": False}


async def _three(client_id: int):
    names = []
    for first in ("Jan", "Anna", "Piotr"):
        last = f"Testowy{tag()}"
        names.append((await _consultant(client_id, first, last), f"{first} {last}"))
    return names


async def test_godziny_z_maila_koordynatora_trafiaja_do_osob_z_liczba():
    message_id = f"godz-{tag()}"
    (jan, jan_name), (anna, anna_name), (piotr, piotr_name) = await _three(
        await make_client()
    )
    sender = f"koordynator@{DOMAIN}"
    body = (
        f"{jan_name}: 176 h\n{anna_name}:112h\n{piotr_name}: czekamy\n\nPozdrawiam,\n"
    )
    reader = MimeMailbox(
        [_no_file(message_id, sender, SUBJECT)],
        {message_id: _eml(sender, SUBJECT, body)},
    )

    result = await _read(reader)

    assert result["created"] == 2
    for contract_id in (jan, anna):
        docs = await _of_contract(contract_id)
        assert [(d.kind, d.period_year, d.period_month, d.mime) for d in docs] == [
            ("report", 2026, 10, "message/rfc822")
        ]
    assert await _of_contract(piotr) == []
    assert (await _read(reader))["created"] == 0


async def test_mail_od_obcego_adresu_nie_wskazuje_osob():
    message_id = f"godz-{tag()}"
    (jan, jan_name), (anna, anna_name), _ = await _three(await make_client())
    sender = "ktos@obca-poczta.example"
    body = f"{jan_name}: 176 h\n{anna_name}: 112 h\n"
    reader = MimeMailbox(
        [_no_file(message_id, sender, SUBJECT)],
        {message_id: _eml(sender, SUBJECT, body)},
    )

    await _read(reader)

    assert await _of_contract(jan) == []
    assert await _of_contract(anna) == []


async def test_osoby_u_dwoch_klientow_czekaja_na_czlowieka():
    message_id = f"godz-{tag()}"
    jan_last, anna_last = f"Testowy{tag()}", f"Inna{tag()}"
    jan = await _consultant(await make_client(), "Jan", jan_last)
    anna = await _consultant(await make_client(), "Anna", anna_last)
    sender = f"koordynator@{DOMAIN}"
    body = f"Jan {jan_last}: 176 h\nAnna {anna_last}: 112 h\n"
    reader = MimeMailbox(
        [_no_file(message_id, sender, SUBJECT)],
        {message_id: _eml(sender, SUBJECT, body)},
    )

    await _read(reader)

    assert await _of_contract(jan) == []
    assert await _of_contract(anna) == []
