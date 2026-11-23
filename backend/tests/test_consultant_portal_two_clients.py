"""Osoba z dwoma działającymi kontraktami u dwóch klientów (próba IX–X 2026).

To nie błąd danych: konsultant pracuje naraz u dwóch klientów i fakturujemy obu
(Nordea i Bosch, Bank Pocztowy i VeloBank). Dwa kontrakty dalej znaczą „karta do
ręcznego przypisania”, chyba że mail sam wskazuje klienta:

- skrzynka u klienta (``p.nazwisko@<domena klienta>``) → kontrakt u tego klienta,
  a domena wspólna dla grupy (``plus.pl``: Polkomtel i Cyfrowy Polsat) nic nie
  rozstrzyga;
- drugi kontrakt u klienta rozliczanego z raportu T4T → raport godzin z poczty idzie
  do pozostałego kontraktu. Faktura nie, bo bywa jedna na obu klientów (IX 2026:
  252 h = Nordea + MS Enter-Prise na jednej fakturze).

Dane fikcyjne.
"""

from __future__ import annotations

import secrets
from datetime import date

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.services.client_settlements import time_reports
from app.services.consultant_portal import identity
from app.services.consultant_portal.portal_settings import PortalSettings
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
    internal,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("care_on")]

CLIENT_DOMAIN = "bank-testowy.example"
GROUP_DOMAIN = "grupa-testowa.example"
INTERNAL = PortalSettings(state="internal")
PDF = b"%PDF-1.4 fikcyjny dokument"


async def _person_at_two_clients(first: str, last: str):
    """Jedna osoba, dwa działające kontrakty u dwóch różnych klientów."""

    one = await make_person(activated=False)
    two = await make_person(activated=False, candidate_id=one.candidate_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == one.candidate_id)
            .values(name=first, lastname=last)
        )
        await db.commit()
    return one, two


async def _nip(client_id: int, nip: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(Client).where(Client.id == client_id).values(nip=nip))
        await db.commit()


def _registry(monkeypatch, domains: dict, nips: dict, shared: dict | None = None):
    monkeypatch.setattr(known_clients, "KNOWN_SENDER_DOMAINS", domains)
    monkeypatch.setattr(known_clients, "KNOWN_REGISTRY_IDS", nips)
    monkeypatch.setattr(
        known_clients, "SHARED_SENDER_DOMAINS", shared or {}, raising=False
    )


def _t4t(monkeypatch, *client_ids: int) -> None:
    async def enabled(db, month):
        return sorted(client_ids)

    monkeypatch.setattr(time_reports, "enabled_clients", enabled)


async def _resolve(address: str, today: date | None = None):
    async with AsyncSessionLocal() as db:
        return await identity.resolve_sender(
            db, address, settings=INTERNAL, today=today or business_today()
        )


def _nip_for_test() -> str:
    return str(secrets.randbelow(9 * 10**9) + 10**9)


# ── Skrzynka u klienta ───────────────────────────────────────────────────────


async def test_client_mailbox_picks_the_contract_at_that_client(monkeypatch) -> None:
    """BP 425 / VeloBank 469: KCP przychodzi z ``P.Nazwisko@pocztowy.pl``, TS
    z ``Imie.Nazwisko@velobank.pl``. Domena nadawcy wskazuje klienta."""

    last = f"Klimek{tag()}"
    bank, other = await _person_at_two_clients("Piotr", last)
    nip = _nip_for_test()
    await _nip(bank.client_id, nip)
    _registry(monkeypatch, {CLIENT_DOMAIN: "bank_testowy"}, {"bank_testowy": (nip,)})

    for local in (f"p.{last.lower()}", f"piotr.{last.lower()}"):
        found = await _resolve(f"{local}@{CLIENT_DOMAIN}")
        assert found is not None and found.id == bank.contract_id, local
    assert other.contract_id != bank.contract_id


async def test_client_mailbox_without_contract_at_that_client(monkeypatch) -> None:
    """Imię i nazwisko konsultanta w skrzynce klienta, u którego nie pracuje:
    to raczej pracownik klienta o tym samym nazwisku, więc nikt."""

    last = f"Obcy{tag()}"
    await _person_at_two_clients("Jan", last)
    nip = _nip_for_test()
    elsewhere = await make_person(activated=False)
    await _nip(elsewhere.client_id, nip)
    _registry(monkeypatch, {CLIENT_DOMAIN: "bank_testowy"}, {"bank_testowy": (nip,)})

    assert await _resolve(f"jan.{last.lower()}@{CLIENT_DOMAIN}") is None


async def test_shared_group_domain_decides_nothing(monkeypatch) -> None:
    """Polkomtel 471 / Cyfrowy Polsat 633: obie spółki piszą z ``plus.pl``, a wpis
    w rejestrze domen wskazuje tylko Polkomtel. Dla CP 634 X wybrałby źle."""

    last = f"Wysocka{tag()}"
    one, two = await _person_at_two_clients("Ewa", last)
    nip_one, nip_two = _nip_for_test(), _nip_for_test()
    await _nip(one.client_id, nip_one)
    await _nip(two.client_id, nip_two)
    _registry(
        monkeypatch,
        {GROUP_DOMAIN: "spolka_a"},
        {"spolka_a": (nip_one,), "spolka_b": (nip_two,)},
        shared={GROUP_DOMAIN: ("spolka_a", "spolka_b")},
    )

    assert await _resolve(f"ewa.{last.lower()}@{GROUP_DOMAIN}") is None


async def test_client_mailbox_of_staff_never_matches(monkeypatch) -> None:
    from app.models.user import User, UserRole
    from tests.care_announcements_seed import make_user

    last = f"Kadra{tag()}"
    bank, _ = await _person_at_two_clients("Ola", last)
    nip = _nip_for_test()
    await _nip(bank.client_id, nip)
    _registry(monkeypatch, {CLIENT_DOMAIN: "bank_testowy"}, {"bank_testowy": (nip,)})
    address = f"ola.{last.lower()}@{CLIENT_DOMAIN}"
    staff = await make_user(UserRole.finance)
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.id == staff.id).values(email=address))
        await db.commit()

    assert await _resolve(address) is None


# ── Drugi kontrakt u klienta z raportem T4T ──────────────────────────────────


async def _company_mail(monkeypatch, files: list[dict]):
    """Oba kontrakty pod jednym adresem (z kontraktu): nadawca wskazuje osobę."""

    t4t_side, other = await _person_at_two_clients("Dorota", f"Hanecka{tag()}")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == other.contract_id)
            .values(candidate_email=t4t_side.email)
        )
        await db.commit()
    _t4t(monkeypatch, t4t_side.client_id)
    reader = FakeMailbox([_message("m1", t4t_side.email)], {"m1": files})
    return t4t_side, other, reader


@pytest.mark.usefixtures("internal")
async def test_report_goes_to_the_contract_outside_t4t(monkeypatch) -> None:
    """Nordea 292 / Bosch 623: Nordea liczy godziny z T4T, więc timesheet z poczty
    jest Boscha („W załączniku Timesheet (Bosch)”, 30.09 i 31.10.2026)."""

    _, bosch, reader = await _company_mail(
        monkeypatch, [_attachment("TS_September2026.pdf", PDF + b" raport")]
    )

    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [bosch.contract_id]


@pytest.mark.usefixtures("internal")
async def test_invoice_of_two_clients_still_waits(monkeypatch) -> None:
    """Faktura bywa jedna na obu klientów (252 h = Nordea + MS Enter-Prise), więc
    z poczty nie trafia do kontraktu spoza T4T. Raport z tego samego maila tak."""

    _, other, reader = await _company_mail(
        monkeypatch,
        [
            _attachment("Faktura_09_2026.pdf", PDF),
            _attachment("Time Sheet 09.2026.pdf", PDF + b" raport"),
        ],
    )

    assert (await _read(reader))["created"] == 2
    by_kind = {row.kind: row.contract_id for row in await _documents()}
    assert by_kind == {"invoice": None, "report": other.contract_id}


@pytest.mark.usefixtures("internal")
async def test_without_t4t_two_clients_still_wait(monkeypatch) -> None:
    _, _, reader = await _company_mail(
        monkeypatch, [_attachment("TS_September2026.pdf", PDF + b" raport")]
    )
    _t4t(monkeypatch)

    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]


@pytest.mark.usefixtures("internal")
async def test_two_contracts_outside_t4t_still_wait(monkeypatch) -> None:
    """Trzeci kontrakt poza T4T: dwa kandydaty na raport, więc karta."""

    t4t_side, other, reader = await _company_mail(
        monkeypatch, [_attachment("TS_September2026.pdf", PDF + b" raport")]
    )
    third = await make_person(activated=False, candidate_id=t4t_side.candidate_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == third.contract_id)
            .values(candidate_email=t4t_side.email)
        )
        await db.commit()
    assert third.client_id not in (t4t_side.client_id, other.client_id)

    assert (await _read(reader))["created"] == 1
    assert [row.contract_id for row in await _documents()] == [None]
