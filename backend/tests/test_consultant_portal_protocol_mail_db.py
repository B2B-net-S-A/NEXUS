"""Czytnik rozliczeń: protokół odbioru zbiorczy w mailu (z bazą).

Skrzynka to atrapa, dane fikcyjne. Próba IX–X 2026: PM albo koordynatorka
przekazuje na rozliczenia@ podpisany protokół klienta z godzinami kilku osób
(CeZ — umowa wykonawcza, PFRON — wszystkie zlecenia). Bez przypisania do osób
protokół stał jako karta, a osoby w „Przebiegu miesiąca” jako „brak raportu”.
"""

from __future__ import annotations

import pytest

from app.services.client_settlements import protocol_collective
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
    _attachment,
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


def _cez(first: str, second: str) -> str:
    return f"""Protokół odbioru
Nr Umowy Wykonawczej CeZ/99/2026
Zestawienie czasu pracy i wykonanych zadań
w okresie od 01.09.2026 do 30.09.2026
(Data i podpis osoby uprawnionej) (Data i podpis osoby uprawnionej)
Zestawienie
Część umowy Rola Imię i nazwisko Nazwa Projektu Typ prac Suma
I Analityk {first} ALFA Rozwój 176
{first} Suma 176
I Analityk {second} ALFA Rozwój 160
{second} Suma 160
Suma końcowa 336
Podsumowanie projektu/ów
"""


def _pfron(first: str, second: str) -> str:
    return f"""Protokół odbioru na usługi outsourcingu specjalistów IT
Specjalisty: {first} Administrator ds. sieci
Liczba Roboczogodzin wykonanych i odebranych przez Zamawiającego Prac w ramach Zlecenia w
danym okresie rozliczeniowym: 176
Specjalisty: {second} Specjalista DevOps
Liczba Roboczogodzin wykonanych i odebranych przez Zamawiającego Prac w ramach Zlecenia w
danym okresie rozliczeniowym: 90,5
"""


@pytest.fixture
def texts(monkeypatch):
    """Tekst PDF-a po jego bajtach: atrapa odczytu pdfplumber."""

    found: dict[bytes, str] = {}
    monkeypatch.setattr(protocol_collective, "pdf_text", found.get)
    return found


async def _two_people(client_id: int) -> tuple[tuple[int, str], tuple[int, str]]:
    jan_last, anna_last = f"Testowy{tag()}", f"Inna{tag()}"
    jan = await _consultant(client_id, "Jan", jan_last)
    anna = await _consultant(client_id, "Anna", anna_last)
    return (jan, f"Jan {jan_last}"), (anna, f"Anna {anna_last}")


async def test_protokol_cez_trafia_do_kazdej_osoby_z_okresem_z_tresci(texts):
    message_id = f"cez-{tag()}"
    (jan, jan_name), (anna, anna_name) = await _two_people(await make_client())
    content = f"%PDF-1.4 cez {message_id}".encode()
    texts[content] = _cez(jan_name, anna_name)
    # Nazwa pliku ma numer umowy, z którego czytnik okresu robi luty.
    name = "CeZ_2_2026 protokół odbioru - wrzesień 2026-sig.pdf"
    reader = FakeMailbox(
        [_message(message_id, f"pm.testowy@{DOMAIN}", "RE: Protokół odbioru")],
        {message_id: [_attachment(name, content)]},
    )

    result = await _read(reader)

    assert result["created"] == 2
    for contract_id in (jan, anna):
        docs = await _of_contract(contract_id)
        assert [(d.kind, d.period_year, d.period_month) for d in docs] == [
            ("report", 2026, 9)
        ]
        assert docs[0].period_guessed is False
    assert (await _read(reader))["created"] == 0


async def test_protokol_pfron_bierze_miesiac_z_nazwy_pliku(texts):
    message_id = f"pfron-{tag()}"
    (jan, jan_name), (anna, anna_name) = await _two_people(await make_client())
    content = f"%PDF-1.4 pfron {message_id}".encode()
    texts[content] = _pfron(jan_name, anna_name)
    reader = FakeMailbox(
        [_message(message_id, f"koordynator@{DOMAIN}", "PFRON protokół")],
        {message_id: [_attachment("Protokół odbioru wrzesień 2026-sig.pdf", content)]},
    )

    await _read(reader)

    for contract_id in (jan, anna):
        docs = await _of_contract(contract_id)
        assert [(d.period_year, d.period_month) for d in docs] == [(2026, 9)]


async def test_protokol_pfron_bez_miesiaca_w_nazwie_i_temacie_czeka(texts):
    message_id = f"pfron-{tag()}"
    (jan, jan_name), (anna, anna_name) = await _two_people(await make_client())
    content = f"%PDF-1.4 pfron {message_id}".encode()
    texts[content] = _pfron(jan_name, anna_name)
    reader = FakeMailbox(
        [_message(message_id, f"koordynator@{DOMAIN}", "PFRON")],
        {message_id: [_attachment("protokol-sig.pdf", content)]},
    )

    await _read(reader)

    assert await _of_contract(jan) == []
    assert await _of_contract(anna) == []


async def test_protokol_z_osobami_u_dwoch_klientow_czeka_na_czlowieka(texts):
    message_id = f"cez-{tag()}"
    jan_last, anna_last = f"Testowy{tag()}", f"Inna{tag()}"
    jan = await _consultant(await make_client(), "Jan", jan_last)
    anna = await _consultant(await make_client(), "Anna", anna_last)
    content = f"%PDF-1.4 cez {message_id}".encode()
    texts[content] = _cez(f"Jan {jan_last}", f"Anna {anna_last}")
    reader = FakeMailbox(
        [_message(message_id, f"pm.testowy@{DOMAIN}", "Protokół odbioru")],
        {message_id: [_attachment("protokol.pdf", content)]},
    )

    await _read(reader)

    assert await _of_contract(jan) == []
    assert await _of_contract(anna) == []


async def test_protokol_od_obcego_adresu_nie_wskazuje_osob(texts):
    message_id = f"cez-{tag()}"
    (jan, jan_name), (anna, anna_name) = await _two_people(await make_client())
    content = f"%PDF-1.4 cez {message_id}".encode()
    texts[content] = _cez(jan_name, anna_name)
    reader = FakeMailbox(
        [_message(message_id, "ktos@obca-poczta.example", "Protokół odbioru")],
        {message_id: [_attachment("protokol.pdf", content)]},
    )

    await _read(reader)

    assert await _of_contract(jan) == []
    assert await _of_contract(anna) == []


async def _client_with_contact(email: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.contact import Contact

    client_id = await make_client()
    async with AsyncSessionLocal() as db:
        db.add(Contact(client_id=client_id, name="Koordynator Klienta", email=email))
        await db.commit()
    return client_id


async def test_protokol_odeslany_klientowi_z_dw_ma_nadawce_klienta(texts):
    """PM podpisuje protokół od klienta i odsyła go klientowi z DW rozliczenia@."""

    message_id = f"cez-{tag()}"
    client_domain = f"klient-{tag()}.example"
    client_id = await _client_with_contact(f"koordynator@{client_domain}")
    (jan, jan_name), (anna, anna_name) = await _two_people(client_id)
    content = f"%PDF-1.4 cez {message_id}".encode()
    texts[content] = _cez(jan_name, anna_name)
    message = {
        **_message(message_id, f"pm.testowy@{DOMAIN}", "RE: Protokół odbioru"),
        "toRecipients": [{"emailAddress": {"address": f"Ktos@{client_domain}"}}],
        "ccRecipients": [{"emailAddress": {"address": f"rozliczenia@{DOMAIN}"}}],
    }
    reader = FakeMailbox(
        [message], {message_id: [_attachment("protokol-sig.pdf", content)]}
    )

    await _read(reader)

    for contract_id in (jan, anna):
        (doc,) = await _of_contract(contract_id)
        assert doc.sender_email == f"ktos@{client_domain}"


async def test_protokol_z_adresu_firmy_bez_klienta_w_watku_zostaje_od_firmy(texts):
    message_id = f"cez-{tag()}"
    client_id = await _client_with_contact(f"koordynator@klient-{tag()}.example")
    (jan, jan_name), (anna, anna_name) = await _two_people(client_id)
    content = f"%PDF-1.4 cez {message_id}".encode()
    texts[content] = _cez(jan_name, anna_name)
    message = {
        **_message(message_id, f"pm.testowy@{DOMAIN}", "Protokół odbioru"),
        "toRecipients": [{"emailAddress": {"address": f"rozliczenia@{DOMAIN}"}}],
    }
    reader = FakeMailbox(
        [message], {message_id: [_attachment("protokol-sig.pdf", content)]}
    )

    await _read(reader)

    (doc,) = await _of_contract(jan)
    assert doc.sender_email == f"pm.testowy@{DOMAIN}"
