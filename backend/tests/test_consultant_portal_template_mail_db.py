"""Dokumenty dwóch klientów od jednej osoby: wzór pliku wskazuje kontrakt.

Konsultant z kontraktem w Banku Pocztowym i VeloBanku wysyła z adresu firmy jednym
mailem kartę ewidencji (KCP) banku i Time Sheet VeloBanku. Sam adres nie
rozstrzyga, a cytat w przekazanym wątku wskazuje najwyżej jeden z banków, więc
karta czekała bez osoby albo szła do VeloBanku (maile z VII i VIII 2026).

Osoby, adresy i numery fikcyjne.
"""

from __future__ import annotations

import calendar
import io
import secrets
from datetime import date, datetime, timedelta
from email.message import EmailMessage

import openpyxl
import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.services.client_settlements import kcp
from app.services.order_policies import known_clients
from tests.care_announcements_seed import care_on, tag  # noqa: F401  (fixture)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    make_person,
    portal_restored,
)
from tests.test_consultant_portal_internal import (  # noqa: F401  (fixture'y)
    FakeMailbox,
    _attachment,
    _documents,
    _message,
    _quiet_documents,
    _read,
    _storage,
    company_domain,
    internal,
)
from tests.test_consultant_portal_kind_from_content import pdf_with_text

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("care_on", "internal", "company_domain"),
]

COMPANY_DOMAIN = "firma.example.com"  # fixture ``company_domain``
BANK_DOMAIN = "bank-pocztowy-testowy.example"
VELO_DOMAIN = "velo-testowy.example"
INVOICE = b"%PDF-1.4 fikcyjna faktura"


class _Thread(FakeMailbox):
    """Mail z przekazanym wątkiem: cytat „From:” w treści."""

    def __init__(self, messages, files, quoted_from: str) -> None:
        super().__init__(messages, files)
        mail = EmailMessage()
        mail["From"] = "ktos@firma.example.com"
        mail.set_content(f"From: Ktos <{quoted_from}>\nSubject: akceptacja\n\nOK")
        self.raw = mail.as_bytes()

    async def mime(self, message_id):
        return self.raw


async def _nip(client_id: int) -> str:
    number = str(secrets.randbelow(9 * 10**9) + 10**9)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Client).where(Client.id == client_id).values(nip=number)
        )
        await db.commit()
    return number


async def _contract(contract_id: int, **values) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract).where(Contract.id == contract_id).values(**values)
        )
        await db.commit()


class _Person:
    """Jedna osoba z kontraktem w banku A (karta KCP) i w VeloBanku (Time Sheet)."""

    def __init__(self, first: str, last: str, bank, velo) -> None:
        self.first, self.last = first, last
        self.bank, self.velo = bank, velo
        self.alias = f"{first.lower()}.{last.lower()}@{COMPANY_DOMAIN}"
        self.on_card = f"{last} DSI {first}"
        self.on_sheet = f"{first} {last}"


async def _two_banks(monkeypatch) -> _Person:
    first, last = "Marta", f"Dwubankowa{tag()}"
    bank = await make_person(activated=False)
    velo = await make_person(activated=False, candidate_id=bank.candidate_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == bank.candidate_id)
            .values(name=first, lastname=last)
        )
        await db.commit()
    nips = {
        "bank_pocztowy": (await _nip(bank.client_id),),
        "velobank": (await _nip(velo.client_id),),
    }
    monkeypatch.setattr(known_clients, "KNOWN_REGISTRY_IDS", nips)
    monkeypatch.setattr(
        known_clients,
        "KNOWN_SENDER_DOMAINS",
        {BANK_DOMAIN: "bank_pocztowy", VELO_DOMAIN: "velobank"},
    )
    return _Person(first, last, bank, velo)


def _month_start() -> date:
    return business_today().replace(day=1)


def _card(person: str, month: date, name: str | None = None) -> dict:
    lines = [
        "KARTA EWIDENCJI SWIADCZENIA USLUG",
        f"Imie i Nazwisko: {person}",
        f"Miesiac: {kcp.MONTHS[month.month - 1].capitalize()}",
        f"Rok: {month.year}",
        "1 Zadanie 1: analiza 8",
        "Suma dni przepracowanych 1,0",
        "Liczba godzin czas podstawowy 8",
    ]
    return _attachment(name or f"Karta pracy {month:%m.%Y}.pdf", pdf_with_text(lines))


def _sheet(person: str, month: date) -> dict:
    last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    first_day = datetime(month.year, month.month, 1)
    book = openpyxl.Workbook()
    grid = book.active
    grid.title = "GridTable"
    for row in (
        [None, "Time Sheet"],
        [None, "Project Name", None, "VeloBank"],
        [None, "Consultant(s)", None, person],
        [None, "Date from", None, first_day],
        [None, "Date to", None, datetime(last.year, last.month, last.day)],
        [
            None,
            "Date",
            "Project",
            "Description",
            "Total Hours",
            "Billable",
            "Non-billable",
            "Nr strumienia",
        ],
        [None, first_day, "VeloBank", "Prace programistyczne", 8, 8, 0, 31951],
        [None, "Total Hours", None, None, 8],
    ):
        grid.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return _attachment(f"{person}_TS {month:%m.%Y}.xlsx", buffer.getvalue())


async def _owners() -> dict[str, int | None]:
    return {row.file_name: row.contract_id for row in await _documents()}


async def _send(sender: str, *files: dict) -> dict[str, int | None]:
    reader = FakeMailbox([_message("m1", sender)], {"m1": list(files)})
    await _read(reader)
    return await _owners()


async def test_dokumenty_obu_bankow_ida_do_swoich_kontraktow(monkeypatch) -> None:
    person = await _two_banks(monkeypatch)
    month = _month_start()
    card = _card(person.on_card, month)
    sheet = _sheet(person.on_sheet, month)
    invoice = _attachment(f"Faktura {month:%m.%Y}.pdf", INVOICE)

    owners = await _send(person.alias, invoice, card, sheet)

    assert owners[card["name"]] == person.bank.contract_id
    assert owners[sheet["name"]] == person.velo.contract_id
    # Faktura nie ma wzoru klienta: czeka na człowieka jak dotąd.
    assert owners[invoice["name"]] is None


async def test_karta_pod_nazwa_bez_slow_kluczy_tez_idzie_do_banku(monkeypatch) -> None:
    person = await _two_banks(monkeypatch)
    month = _month_start()
    card = _card(person.on_card, month, name=f"timelog {month:%m.%Y}.pdf")

    owners = await _send(person.alias, card)

    assert owners == {card["name"]: person.bank.contract_id}


async def test_wzor_wygrywa_z_kontraktem_z_przekazanego_watku(monkeypatch) -> None:
    """Przekazana akceptacja ze skrzynki w VeloBanku wskazywała kontrakt Velo
    dla wszystkich plików maila, także dla karty drugiego banku."""

    person = await _two_banks(monkeypatch)
    month = _month_start()
    card = _card(person.on_card, month)
    sheet = _sheet(person.on_sheet, month)
    velo_box = f"{person.first.lower()}.{person.last.lower()}@{VELO_DOMAIN}"
    reader = _Thread([_message("m1", person.alias)], {"m1": [card, sheet]}, velo_box)

    await _read(reader)
    owners = await _owners()

    assert owners[card["name"]] == person.bank.contract_id
    assert owners[sheet["name"]] == person.velo.contract_id


async def test_wzor_wygrywa_z_kontraktem_skrzynki_u_drugiego_klienta(
    monkeypatch,
) -> None:
    """Time Sheet VeloBanku wysłany ze skrzynki w pierwszym banku."""

    person = await _two_banks(monkeypatch)
    bank_box = f"{person.first.lower()}.{person.last.lower()}@{BANK_DOMAIN}"
    sheet = _sheet(person.on_sheet, _month_start())

    owners = await _send(bank_box, sheet)

    assert owners == {sheet["name"]: person.velo.contract_id}


async def test_karta_z_innym_nazwiskiem_czeka_na_czlowieka(monkeypatch) -> None:
    person = await _two_banks(monkeypatch)
    card = _card("Obcy DSI Jan", _month_start())

    owners = await _send(person.alias, card)

    assert owners == {card["name"]: None}


async def test_karta_za_miesiac_spoza_kontraktu_w_banku_nie_idzie_do_velo(
    monkeypatch,
) -> None:
    """Kontrakt w banku skończył się przed miesiącem karty: bez tej reguły karta
    szła do jedynego działającego kontraktu, czyli do drugiego klienta."""

    person = await _two_banks(monkeypatch)
    month = _month_start()
    await _contract(
        person.bank.contract_id,
        status=ContractStatus.ended,
        end_date=month - timedelta(days=1),
    )
    card = _card(person.on_card, month)

    owners = await _send(person.alias, card)

    assert owners == {card["name"]: None}


async def test_dwa_kontrakty_w_banku_wzoru_czekaja_na_czlowieka(monkeypatch) -> None:
    person = await _two_banks(monkeypatch)
    second = await make_person(activated=False, candidate_id=person.bank.candidate_id)
    await _contract(second.contract_id, client_id=person.bank.client_id)
    card = _card(person.on_card, _month_start())

    owners = await _send(person.alias, card)

    assert owners == {card["name"]: None}


async def test_wzor_klienta_bez_kontraktu_osoby_niczego_nie_zmienia(
    monkeypatch,
) -> None:
    """Osoba bez kontraktu w VeloBanku: Time Sheet czeka jak dotąd."""

    person = await _two_banks(monkeypatch)
    known = dict(known_clients.KNOWN_REGISTRY_IDS)
    known["velobank"] = ("0000000000",)
    monkeypatch.setattr(known_clients, "KNOWN_REGISTRY_IDS", known)
    sheet = _sheet(person.on_sheet, _month_start())

    owners = await _send(person.alias, sheet)

    assert owners == {sheet["name"]: None}


async def test_karta_od_koordynatora_czeka_jak_dotad(monkeypatch) -> None:
    """Adres firmy, który nie jest tej osoby: nadawca nikogo nie wskazuje."""

    person = await _two_banks(monkeypatch)
    card = _card(person.on_card, _month_start())

    owners = await _send(f"koordynator@{COMPANY_DOMAIN}", card)

    assert owners == {card["name"]: None}


async def test_dwie_osoby_pod_jednym_adresem_czekaja(monkeypatch) -> None:
    person = await _two_banks(monkeypatch)
    other = await make_person(activated=False)
    shared = f"wspolna-{tag()}@example.com"
    for contract_id in (person.bank.contract_id, other.contract_id):
        await _contract(contract_id, candidate_email=shared)
    card = _card(person.on_card, _month_start())

    owners = await _send(shared, card)

    assert owners == {card["name"]: None}
