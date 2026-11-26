"""Nadawca z adresu firmowego (imie.nazwisko@<domena adresu rozliczeń>).

Konsultanci piszą na rozliczenia@ ze skrzynek firmowych, a kontrakt i kartoteka
mają ich adres prywatny. Próba na archiwum IX–XI 2026: bez tego dopasowania
NEXUS rozpoznał 14% dokumentów. Pasuje tylko jedna osoba z jednym działającym
kontraktem; konto NEXUSA (pracownik przesyła cudze pliki) nie pasuje nigdy.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.contract import ContractStatus
from app.services.consultant_portal import identity
from app.services.consultant_portal.portal_settings import PortalSettings
from tests.care_announcements_seed import make_user, tag
from tests.consultant_portal_seed import make_person
from app.models.user import UserRole

DOMAIN = "firma-testowa.example"
INTERNAL = PortalSettings(state="internal")


@pytest.fixture(autouse=True)
def _settlements_address(monkeypatch):
    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", f"rozliczenia@{DOMAIN}"
    )


async def _named(first: str, last: str, **kw):
    person = await make_person(**kw)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == person.candidate_id)
            .values(name=first, lastname=last)
        )
        await db.commit()
    return person


async def _resolve(address: str, today: date | None = None):
    async with AsyncSessionLocal() as db:
        return await identity.resolve_sender(
            db, address, settings=INTERNAL, today=today or business_today()
        )


async def test_company_address_finds_the_person() -> None:
    last = f"Żółtańska{tag()}"
    person = await _named("Łucja", last)
    folded = "zoltanska" + last.removeprefix("Żółtańska").lower()
    for local in (f"lucja.{folded}", f"l.{folded}", f"lucja_{folded}"):
        found = await _resolve(f"{local}@{DOMAIN}")
        assert found is not None and found.id == person.contract_id, local


async def test_other_domain_and_unknown_name_do_not_match() -> None:
    last = f"Nowacka{tag()}"
    await _named("Ewa", last)
    assert await _resolve(f"ewa.{last.lower()}@inna-firma.example") is None
    assert await _resolve(f"ewa.kowalska{tag()}@{DOMAIN}") is None


async def test_two_people_with_the_same_name_need_a_human() -> None:
    last = f"Wiśniewska{tag()}"
    await _named("Ewa", last)
    await _named("Ewa", last)
    folded = "wisniewska" + last.removeprefix("Wiśniewska").lower()
    assert await _resolve(f"ewa.{folded}@{DOMAIN}") is None


async def test_staff_account_never_matches_a_consultant() -> None:
    last = f"Kowal{tag()}"
    await _named("Ola", last)
    address = f"ola.{last.lower()}@{DOMAIN}"
    staff = await make_user(UserRole.finance)
    async with AsyncSessionLocal() as db:
        from app.models.user import User

        await db.execute(update(User).where(User.id == staff.id).values(email=address))
        await db.commit()
    assert await _resolve(address) is None


async def test_ended_contract_outside_grace_does_not_match() -> None:
    last = f"Zielna{tag()}"
    person = await _named("Iga", last, status=ContractStatus.ended)
    async with AsyncSessionLocal() as db:
        from app.models.contract import Contract

        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(end_date=date(2020, 1, 31))
        )
        await db.commit()
    assert await _resolve(f"iga.{last.lower()}@{DOMAIN}") is None


async def test_client_mailbox_domain_finds_the_person(monkeypatch) -> None:
    """BNP zakłada konsultantom skrzynki imie.nazwisko@external.bnpparibas.pl
    (klauzula umowy B2B). Próba IX–X 2026: 32 dokumenty z tej domeny bez
    kontraktu, każdy wskazywał dokładnie jedną osobę."""

    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_PERSONAL_DOMAINS", "klient-osobowy.example"
    )
    last = f"Malinowska{tag()}"
    person = await _named("Ada", last)
    found = await _resolve(f"ada.{last.lower()}@klient-osobowy.example")
    assert found is not None and found.id == person.contract_id
    # Domena spoza listy dalej nikogo nie wskazuje.
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_PERSONAL_DOMAINS", "")
    assert await _resolve(f"ada.{last.lower()}@klient-osobowy.example") is None


async def test_client_mailbox_domain_two_people_need_a_human(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_PERSONAL_DOMAINS", "klient-osobowy.example"
    )
    last = f"Jasna{tag()}"
    await _named("Ola", last)
    await _named("Ola", last)
    assert await _resolve(f"ola.{last.lower()}@klient-osobowy.example") is None


# ── Adres konsultanta dla komunikatów (decyzja Artura z 26.11.2026) ──────────


async def _mail_document(contract_id: int, sender: str, name: str) -> None:
    from app.core.scheduling import local_now
    from app.services.consultant_portal import documents

    today = business_today()
    async with AsyncSessionLocal() as db:
        await documents.store(
            db,
            contract_id=contract_id,
            kind="report",
            year=today.year,
            month=today.month,
            content=b"%PDF-1.4 " + name.encode(),
            file_name=name,
            channel="mailbox",
            now=local_now(),
            sender_email=sender,
        )
        await db.commit()


async def test_adres_konsultanta_to_jego_skrzynka_z_poczty_nie_kierownik(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service
    from app.services.client_settlements import reminders

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    last = f"Nowacka{tag()}"
    person = await _named("Ewa", last)
    alias = f"ewa.{last.lower()}@{DOMAIN}"
    await _mail_document(person.contract_id, alias, "ts.pdf")
    # Później plik przysłał kierownik u klienta: to nie jest adres konsultanta.
    await _mail_document(person.contract_id, "kierownik@klient.example", "akc.pdf")

    async with AsyncSessionLocal() as db:
        found = await reminders.consultant_addresses(
            db, {person.contract_id}, today=business_today()
        )

    assert found == {person.contract_id: alias}


async def test_bez_dokumentu_konsultanta_brak_adresu_z_poczty(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service
    from app.services.client_settlements import reminders

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    person = await _named("Ewa", f"Nowacka{tag()}")
    await _mail_document(person.contract_id, "kierownik@klient.example", "akc.pdf")

    async with AsyncSessionLocal() as db:
        assert (
            await reminders.consultant_addresses(
                db, {person.contract_id}, today=business_today()
            )
            == {}
        )
