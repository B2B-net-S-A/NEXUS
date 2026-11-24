"""Czytnik rozliczeń: tabela klienta „osoba × numer zamówienia” w mailu bez pliku.

Skrzynka to atrapa, dane fikcyjne. Próba IX–X 2026 (Polkomtel IX): koordynatorka
przekazała z adresu firmy zestawienie od klienta — tabelę przestawną z MD osób na
numerach SAP — i mail nie trafiał do nikogo. Teraz trafia jako raport każdej
osoby z tabeli; osobę szukamy tylko wśród kontraktów klienta, do którego należą
numery zamówień, a tabelę musi napisać ktoś z jego domeny.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client_order_group import ClientOrderGroup
from app.models.contact import Contact
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
from tests.test_client_settlements_order_split import _eml, _forward_html, _table
from tests.test_consultant_portal_hours_summary_mail_db import MimeMailbox, _no_file
from tests.test_consultant_portal_zip_mail_db import (  # noqa: F401  (fixture'y)
    DOMAIN,
    FakeMailbox,
    _config,
    _consultant,
    _fresh_state,
    _of_contract,
    _read,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("care_on", "portal_all"),
]

SUBJECT = "FW: [EXT] RE: Raport Timesheet za 09/2026"
CLIENT_DOMAIN = "klient.example"


async def _client_with_orders(numbers: tuple[str, ...]) -> int:
    client_id = await make_client()
    async with AsyncSessionLocal() as db:
        db.add(
            Contact(
                client_id=client_id,
                name="Specjalistka Klienta",
                email=f"specjalistka@{CLIENT_DOMAIN}",
            )
        )
        for number in numbers:
            db.add(
                ClientOrderGroup(
                    client_id=client_id,
                    order_number=number,
                    start_date=business_today() - timedelta(days=120),
                    status="active",
                    order_type="md",
                    is_cost_based=False,
                    is_md_budget_based=False,
                )
            )
        await db.commit()
    return client_id


def _digits(message_id: str, salt: int = 0) -> str:
    """Pięć cyfr numeru zamówienia z identyfikatora maila: numer jest unikalny
    w bazie testów, a powtórzony u dwóch klientów nie wskazuje żadnego."""

    return f"{(int(message_id[-8:], 16) + salt) % 100000:05d}"


def _surname(base: str) -> str:
    """Nazwisko bez cyfr: czytnik tabeli bierze tylko słowa z liter."""

    return base + "".join(chr(ord("a") + int(c, 16)) for c in tag())


def _mail(
    message_id: str,
    jan: str,
    anna: str,
    *,
    author: str = f"specjalistka@{CLIENT_DOMAIN}",
) -> MimeMailbox:
    table = _table(
        [
            "Etykiety wierszy",
            f"SAP 45000{_digits(message_id)}",
            f"45001{_digits(message_id, 7)}",
        ],
        [[jan, "6", "16"], [anna, "", "20"], ["Obcy Ktoś", "1", ""]],
    )
    sender = f"koordynatorka@{DOMAIN}"
    html = _forward_html(table).replace(f"specjalistka@{CLIENT_DOMAIN}", author)
    content = _eml(SUBJECT, sender, "Dw", html).as_bytes()
    return MimeMailbox([_no_file(message_id, sender, SUBJECT)], {message_id: content})


async def test_tabela_od_klienta_trafia_do_osob_z_wierszy():
    message_id = f"tab-{tag()}"
    client_id = await _client_with_orders(
        (f"SAP 45000{_digits(message_id)}", f"45001{_digits(message_id, 7)}")
    )
    jan_last, anna_last = _surname("Testowy"), _surname("Inna")
    jan = await _consultant(client_id, "Jan", jan_last)
    anna = await _consultant(client_id, "Anna", anna_last)
    # Ta sama osoba u innego klienta nie dostaje tabeli.
    elsewhere = await _consultant(await make_client(), "Jan", jan_last)

    result = await _read(_mail(message_id, f"{jan_last} Jan", f"{anna_last} Anna"))

    assert result["created"] == 2
    for contract_id in (jan, anna):
        docs = await _of_contract(contract_id)
        assert [(d.kind, d.period_year, d.period_month, d.mime) for d in docs] == [
            ("report", 2026, 9, "message/rfc822")
        ]
    assert await _of_contract(elsewhere) == []


async def test_tabela_z_obcej_domeny_nie_wskazuje_osob():
    message_id = f"tab-{tag()}"
    client_id = await _client_with_orders(
        (f"SAP 45000{_digits(message_id)}", f"45001{_digits(message_id, 7)}")
    )
    jan_last = _surname("Testowy")
    jan = await _consultant(client_id, "Jan", jan_last)
    reader = _mail(
        message_id, f"{jan_last} Jan", "Nikt Taki", author="ktos@obca-poczta.example"
    )

    await _read(reader)

    assert await _of_contract(jan) == []


async def test_numery_zamowien_spoza_nexusa_nie_wskazuja_klienta():
    message_id = f"tab-{tag()}"
    client_id = await _client_with_orders(("4500077777",))
    jan_last = _surname("Testowy")
    jan = await _consultant(client_id, "Jan", jan_last)

    await _read(_mail(message_id, f"{jan_last} Jan", "Nikt Taki"))

    assert await _of_contract(jan) == []
