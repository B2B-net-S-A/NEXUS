"""Formy nadawcy i okresu, przez które raport z poczty nie trafiał do kontraktu.

Próba rozliczeń IX–X 2026 (23.11.2026): część przypadków „bez dokumentu” miała raport
w poczcie, ale NEXUS nie łączył go z osobą albo z miesiącem:
* Gmail bez kropek (``jannowak@``), gdy kontrakt ma ``jan.nowak@`` (BIK);
* skrzynka konsultanta u klienta w domenie ``erste.pl`` (ERSTE, dawny Santander);
* karta pracy „KCP Nazwisko Imię 09 2026.pdf” z okresem rozdzielonym spacją (Bank
  Pocztowy), z maila z połowy miesiąca szła na poprzedni miesiąc;
* „Wszystko się zgadza” jako akceptacja klienta (Bosch).
Osoby, adresy i klienci fikcyjni.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.services.client_settlements import client_acceptance
from app.services.consultant_portal import identity
from app.services.consultant_portal.mailbox import period_for
from app.services.consultant_portal.portal_settings import PortalSettings
from app.services.order_policies import known_clients
from tests.care_announcements_seed import tag
from tests.consultant_portal_seed import make_person

INTERNAL = PortalSettings(state="internal")


@pytest.mark.parametrize(
    ("subject", "name", "received", "expected"),
    [
        ("Prośba", "KCP Nowak Jan 09 2026.pdf", date(2026, 9, 15), (2026, 9, False)),
        ("KCP 1 za 04 2026", "KCP Nowak Jan 04 2026.pdf", date(2026, 4, 20), (2026, 4, False)),
        ("Rozliczenie październik 2026", "TimeSheet 2610 - Nowak Jan.xlsm", date(2026, 11, 5), (2026, 10, False)),
        # Numer bez miesiąca i roku dalej nie jest okresem.
        ("Raport", "Umowa 1516 2026.pdf", date(2026, 10, 30), (2026, 10, True)),
    ],
)  # fmt: skip
def test_period_with_space_between_month_and_year(subject, name, received, expected):
    assert period_for(subject, name, received) == expected


@pytest.mark.parametrize(
    ("text", "accepted"),
    [
        ("Wszystko się zgadza, proszę o wystawienie faktury.", True),
        ("Dzień dobry, zgadza się.", True),
        ("Coś się nie zgadza, brakuje dnia urlopu.", False),
        ("Nie zgadza się liczba godzin.", False),
        ("Potwierdzam zestawienie.", True),
    ],
)
def test_matching_hours_is_an_acceptance(text, accepted):
    assert client_acceptance.accepts(text) is accepted


async def _resolve(address: str):
    async with AsyncSessionLocal() as db:
        return await identity.resolve_sender(
            db, address, settings=INTERNAL, today=business_today()
        )


@pytest.mark.asyncio
async def test_gmail_address_without_dots_finds_the_contract() -> None:
    local = f"jan.nowak.{tag()}"
    person = await make_person(email=f"{local}@gmail.com", activated=False)
    found = await _resolve(f"{local.replace('.', '')}@gmail.com")
    assert found is not None and found.id == person.contract_id
    # Inna domena z tą samą nazwą skrzynki to inny adres.
    assert await _resolve(f"{local.replace('.', '')}@example.com") is None


@pytest.mark.asyncio
async def test_gmail_alias_of_two_people_needs_a_human() -> None:
    local = f"ewa.nowak.{tag()}"
    await make_person(email=f"{local}@gmail.com", activated=False)
    await make_person(email=f"{local.replace('.', '')}@gmail.com", activated=False)
    # Trzecia forma tego samego adresu pasuje do obu osób: karta do przypisania.
    assert await _resolve(f"e.{local[1:]}@gmail.com") is None


def test_erste_domain_is_a_known_client_domain() -> None:
    assert known_clients.KNOWN_SENDER_DOMAINS["erste.pl"] == "erste"
    assert known_clients.KNOWN_REGISTRY_IDS["erste"]


@pytest.mark.asyncio
async def test_consultant_mailbox_at_erste_finds_the_contract() -> None:
    last = f"Matyszczak{tag()}"
    person = await make_person(activated=False)
    nip = known_clients.KNOWN_REGISTRY_IDS["erste"][0]
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, person.client_id)
        clash = await db.scalar(
            select(Client.id).where(Client.nip == nip, Client.id != client.id)
        )
        if clash is not None:
            pytest.skip("klient z numerem ERSTE istnieje już w bazie testowej")
        client.nip = nip
        await db.execute(
            update(Candidate)
            .where(Candidate.id == person.candidate_id)
            .values(name="Marian", lastname=last)
        )
        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(candidate_email=None)
        )
        await db.commit()
    try:
        found = await _resolve(f"marian.{last.lower()}@erste.pl")
        assert found is not None and found.id == person.contract_id
    finally:
        async with AsyncSessionLocal() as db:
            client = await db.get(Client, person.client_id)
            client.nip = None
            await db.commit()
