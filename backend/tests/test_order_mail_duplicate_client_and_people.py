"""Zdublowany rekord klienta i osoba, której nie ma w rosterze (zgłoszenie PKO BP).

Dwie warstwy, obie z bazy:

1. ``build_registry_from_db`` — NIP prowadzi do klienta KANONICZNEGO. Scalenie
   duplikatu nie przepisuje danych, więc numer zostaje na scalonym wierszu;
   bez pójścia za ``merged_into_client_id`` scalenie klienta w ogóle nie
   naprawiałoby poczty zamówień. Ten sam numer na dwóch RÓŻNYCH klientach
   kanonicznych wypada z rejestru — dokument idzie do kolejki zamiast do
   rekordu wybranego kolejnością wierszy.
2. ``load_people_outside_roster`` — osoba spoza rostera klienta, ale obecna
   w bazie. To sygnał „nie zakładaj nowego kontraktora bez pytania".

Lata 2031+, dane syntetyczne, baza testowa jest współdzielona i nie jest
czyszczona — stąd unikalny sufiks per przebieg.
"""

import random
import uuid
from datetime import date

import pytest
import pytest_asyncio

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.order_mail_ingest import _follow_client_merge, build_registry_from_db
from app.services.order_mail_resolver import load_people_outside_roster

RUN = uuid.uuid4().hex[:8]


def _synthetic_nip() -> str:
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    while True:
        body = [random.randint(0, 9) for _ in range(9)]
        control = sum(d * w for d, w in zip(body, weights)) % 11
        if control != 10:
            return "".join(map(str, body)) + str(control)


@pytest_asyncio.fixture
async def db_session():
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


async def _client(db, name: str, **kw) -> Client:
    client = Client(name=f"{name} {RUN}", **kw)
    db.add(client)
    await db.flush()
    return client


async def _candidate(db, name: str, lastname: str) -> Candidate:
    candidate = Candidate(name=name, lastname=lastname)
    db.add(candidate)
    await db.flush()
    return candidate


async def _contract(db, candidate, client, status=ContractStatus.active) -> Contract:
    contract = Contract(
        client_id=client.id,
        candidate_id=candidate.id,
        status=status,
        start_date=date(2031, 7, 1),
        rate_unit=RateUnit.hourly,
        currency="PLN",
    )
    db.add(contract)
    await db.flush()
    return contract


# ── Rejestr: numer prowadzi do klienta kanonicznego ─────────────────────────


@pytest.mark.asyncio
async def test_registry_follows_a_merged_duplicate_to_the_surviving_client(db_session):
    """Scalenie duplikatu naprawia pocztę zamówień — bo NIP zostaje na duplikacie."""
    nip = _synthetic_nip()
    surviving = await _client(db_session, "Klient Kanoniczny")
    duplicate = await _client(db_session, "Klient Duplikat", nip=nip)
    duplicate.merged_into_client_id = surviving.id
    await db_session.flush()

    registry = await build_registry_from_db(db_session)

    assert registry.by_registry_id[nip] == str(surviving.id)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_registry_drops_a_number_shared_by_two_separate_clients(db_session):
    """Niejednoznaczny numer = brak rozpoznania, nie losowanie rekordu."""
    nip = _synthetic_nip()
    await _client(db_session, "Klient Pierwszy", nip=nip)
    await _client(db_session, "Klient Drugi", nip=nip)
    await db_session.flush()

    registry = await build_registry_from_db(db_session)

    assert nip not in registry.by_registry_id
    await db_session.rollback()


@pytest.mark.asyncio
async def test_registry_keeps_a_plain_client_untouched(db_session):
    nip = _synthetic_nip()
    client = await _client(db_session, "Klient Zwykły", nip=nip)
    await db_session.flush()

    registry = await build_registry_from_db(db_session)

    assert registry.by_registry_id[nip] == str(client.id)
    await db_session.rollback()


# ── Osoba spoza rostera klienta ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_person_with_a_live_contract_at_another_client_is_reported(db_session):
    """Dokładnie zgłoszenie: dokument trafił na pusty duplikat rekordu klienta."""
    with_contracts = await _client(db_session, "Bank Rekord Właściwy")
    empty_duplicate = await _client(db_session, "Bank Rekord Pusty")
    candidate = await _candidate(db_session, "Piotr", "Michałowski")
    contract = await _contract(db_session, candidate, with_contracts)
    await db_session.flush()

    found = await load_people_outside_roster(
        db_session, client_id=empty_duplicate.id, names=["Piotr Michałowski"]
    )

    hits = found["Piotr Michałowski"]
    assert [h.candidate_id for h in hits] == [candidate.id]
    assert hits[0].contract_id == contract.id
    assert hits[0].client_id == with_contracts.id
    assert hits[0].is_open
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_document_without_diacritics_still_finds_the_person(db_session):
    """Prod nie ma ``unaccent`` — prefiltr musi zwijać polskie znaki po obu stronach."""
    other = await _client(db_session, "Bank Inny")
    this_client = await _client(db_session, "Bank Ten")
    candidate = await _candidate(db_session, "Piotr", "Michałowski")
    await _contract(db_session, candidate, other)
    await db_session.flush()

    found = await load_people_outside_roster(
        db_session, client_id=this_client.id, names=["Michalowski Piotr"]
    )

    assert [h.candidate_id for h in found["Michalowski Piotr"]] == [candidate.id]
    await db_session.rollback()


@pytest.mark.asyncio
async def test_contracts_at_the_asking_client_are_not_reported_as_elsewhere(db_session):
    """Roster to inna warstwa — tu interesuje nas wyłącznie „gdzie indziej"."""
    client = await _client(db_session, "Bank Jedyny")
    candidate = await _candidate(db_session, "Piotr", "Michałowski")
    await _contract(db_session, candidate, client)
    await db_session.flush()

    found = await load_people_outside_roster(
        db_session, client_id=client.id, names=["Piotr Michałowski"]
    )

    # Osoba jest w bazie, ale bez ŻADNEGO zaangażowania poza tym klientem.
    hits = found["Piotr Michałowski"]
    assert [h.candidate_id for h in hits] == [candidate.id]
    assert hits[0].contract_id is None and not hits[0].is_open
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_similar_but_different_name_is_not_a_hit(db_session):
    """Sygnał wyłącza automat, więc nie może reagować na literówkę ani odmianę."""
    other = await _client(db_session, "Bank Obcy")
    this_client = await _client(db_session, "Bank Nasz")
    candidate = await _candidate(db_session, "Piotr", "Michalak")
    await _contract(db_session, candidate, other)
    await db_session.flush()

    found = await load_people_outside_roster(
        db_session, client_id=this_client.id, names=["Piotr Michałowski"]
    )

    assert found == {} or all(
        h.candidate_id != candidate.id for h in found.get("Piotr Michałowski", ())
    )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_two_namesakes_are_both_reported(db_session):
    """Dwie RÓŻNE osoby o tym nazwisku — automat ma zamilknąć, nie wybrać."""
    other = await _client(db_session, "Bank Trzeci")
    this_client = await _client(db_session, "Bank Czwarty")
    first = await _candidate(db_session, "Piotr", "Michałowski")
    second = await _candidate(db_session, "Piotr", "Michałowski")
    await _contract(db_session, first, other)
    await _contract(db_session, second, other)
    await db_session.flush()

    found = await load_people_outside_roster(
        db_session, client_id=this_client.id, names=["Piotr Michałowski"]
    )

    assert {h.candidate_id for h in found["Piotr Michałowski"]} >= {
        first.id,
        second.id,
    }
    await db_session.rollback()


# ── Dokument już w kolejce po scaleniu duplikatu ────────────────────────────


@pytest.mark.asyncio
async def test_a_queued_document_moves_off_a_merged_duplicate(db_session):
    """Scalenie musi dosięgnąć kolejki, nie tylko nowych wiadomości."""
    from app.models.order_mail import OrderMailDocument

    surviving = await _client(db_session, "Klient Kanoniczny Kolejka")
    duplicate = await _client(db_session, "Klient Duplikat Kolejka")
    duplicate.merged_into_client_id = surviving.id
    await db_session.flush()
    row = OrderMailDocument(
        internet_message_id=f"<merge-{RUN}@example>",
        client_id=duplicate.id,
        identification_reason="Numer rejestrowy z dokumentu pasuje do jednego klienta.",
    )
    db_session.add(row)
    await db_session.flush()

    await _follow_client_merge(db_session, row)

    assert row.client_id == surviving.id
    assert f"#{duplicate.id}" in row.identification_reason
    assert "Numer rejestrowy" in row.identification_reason
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_document_on_a_plain_client_is_left_alone(db_session):
    from app.models.order_mail import OrderMailDocument

    client = await _client(db_session, "Klient Bez Scalenia")
    await db_session.flush()
    row = OrderMailDocument(
        internet_message_id=f"<plain-{RUN}@example>",
        client_id=client.id,
        identification_reason="Numer rejestrowy z dokumentu pasuje do jednego klienta.",
    )
    db_session.add(row)
    await db_session.flush()

    await _follow_client_merge(db_session, row)

    assert row.client_id == client.id
    assert "scalony" not in row.identification_reason
    await db_session.rollback()
