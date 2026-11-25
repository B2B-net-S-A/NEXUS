"""Numer nabywcy z dowodu (osoby z pozycji, nazwa prawna) — reguły bez bazy.

Decyzja Artura z 25.11.2026, ``services/client_invoicing/buyer_proof.py``. Osoby,
nazwy firm, numery i faktury fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import critical_events
from app.services.client_invoicing import buyer_proof, clients, matching
from app.services.client_invoicing.buyer_proof import (
    SOURCE_LEGAL_NAME,
    SOURCE_PERSONS,
    People,
    Person,
    Proof,
    Stint,
    decide,
    position_client,
)

CLIENT = 7
OTHER = 8
NOVEMBER = (2026, 11)
NUMBER = "1234567890"
SECOND_NUMBER = "2345678901"

JAN = Person("Jan Przykładowy", (Stint(CLIENT, date(2026, 1, 1)),))
EWA = Person("Ewa Testowa", (Stint(CLIENT, date(2026, 3, 1), date(2026, 12, 31)),))
ADAM = Person("Adam Wzorcowy", (Stint(OTHER, date(2025, 6, 1)),))
#: Kontrakty u dwóch klientów w listopadzie 2026.
OLA = Person(
    "Ola Próbna",
    (Stint(CLIENT, date(2026, 1, 1)), Stint(OTHER, date(2026, 10, 1))),
)
PEOPLE = (JAN, EWA, ADAM, OLA)


def _item(name: str) -> str:
    return f"Usługi programistyczne — {name} — 11/2026"


def _votes(*names: str, people=PEOPLE, period=NOVEMBER) -> list:
    index = People(people)
    votes = []
    for name in names:
        named = index.named_in(_item(name))
        if named:
            votes.append(position_client(named, period))
    return votes


# ── Osoby z pozycji ──────────────────────────────────────────────────────────


def test_two_positions_naming_people_of_one_client_prove_the_buyer():
    proof = decide(_votes("Jan Przykładowy", "Ewa Testowa"), None)

    assert proof == Proof(CLIENT, SOURCE_PERSONS, 2)


def test_the_same_person_on_two_invoices_counts_twice():
    proof = decide(_votes("Jan Przykładowy", "Jan Przykładowy"), None)

    assert (proof.client_id, proof.named) == (CLIENT, 2)


def test_one_position_pointing_at_another_client_gives_nothing():
    proof = decide(_votes("Jan Przykładowy", "Ewa Testowa", "Adam Wzorcowy"), None)

    assert proof.client_id is None
    assert proof.reason == "persons_disagree"


def test_one_named_position_is_not_enough():
    proof = decide(_votes("Jan Przykładowy", "Licencja roczna"), None)

    assert proof.client_id is None
    assert (proof.named, proof.reason) == (1, "no_proof")


def test_person_with_contracts_at_two_clients_that_month_does_not_vote():
    assert _votes("Ola Próbna") == [None]
    # Sama nie dowodzi niczego, a obok dwóch pozycji klienta niczego nie blokuje.
    assert decide(_votes("Jan Przykładowy", "Ola Próbna"), None).client_id is None
    proof = decide(_votes("Jan Przykładowy", "Ewa Testowa", "Ola Próbna"), None)
    assert (proof.client_id, proof.named) == (CLIENT, 2)


def test_contract_in_the_service_month_wins_over_other_contracts():
    moved = Person(
        "Piotr Zmienny",
        (
            Stint(OTHER, date(2024, 1, 1), date(2025, 12, 31)),
            Stint(CLIENT, date(2026, 2, 1)),
        ),
    )

    assert _votes("Piotr Zmienny", people=[moved]) == [CLIENT]
    assert _votes("Piotr Zmienny", people=[moved], period=(2025, 6)) == [OTHER]
    # Miesiąc bez żadnego kontraktu: wszystkie kontrakty, a są u dwóch klientów.
    assert _votes("Piotr Zmienny", people=[moved], period=(2023, 6)) == [None]
    assert _votes("Adam Wzorcowy", period=(2024, 1)) == [OTHER]
    assert _votes("Adam Wzorcowy", period=None) == [OTHER]


def test_position_naming_people_of_two_clients_does_not_vote():
    assert _votes("Jan Przykładowy i Adam Wzorcowy") == [None]


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Lukasz Zoltowski — konsultacje", True),
        ("ŻÓŁTOWSKI ŁUKASZ", True),
        ("Łukasz Żółtowskiego", False),
        ("Łukasz", False),
    ],
)
def test_people_are_named_by_full_name_in_whole_words(text, found):
    person = Person("Łukasz Żółtowski", (Stint(CLIENT),))

    assert (People([person]).named_in(text) == [person]) is found


def test_person_without_a_full_name_is_never_named():
    assert People([Person("Jan", (Stint(CLIENT),))]).named_in("Jan Jan") == []


# ── Nazwa prawna ─────────────────────────────────────────────────────────────


def test_legal_name_alone_proves_the_buyer():
    assert decide([], CLIENT) == Proof(CLIENT, SOURCE_LEGAL_NAME, 0)
    assert decide([CLIENT], CLIENT) == Proof(CLIENT, SOURCE_LEGAL_NAME, 1)


def test_people_come_first_when_both_point_at_the_client():
    assert decide([CLIENT, CLIENT], CLIENT).source == SOURCE_PERSONS


@pytest.mark.parametrize(
    ("votes", "legal_client", "reason"),
    [
        ([CLIENT, CLIENT], OTHER, "sources_differ"),
        ([OTHER], CLIENT, "sources_differ"),
        ([OTHER, None], CLIENT, "sources_differ"),
        ([CLIENT, OTHER, OTHER], CLIENT, "persons_disagree"),
    ],
)
def test_people_and_legal_name_pointing_at_different_clients_give_nothing(
    votes, legal_client, reason
):
    proof = decide(votes, legal_client)

    assert proof.client_id is None
    assert proof.reason == reason


def test_people_need_the_buyer_name_not_to_contradict_the_clients_legal_name():
    """Spółka z grupy z własnym numerem, fakturowana za osoby klienta siostry."""

    legal_names = {CLIENT: "przykład ubezpieczenia majątkowe s.a."}

    other_company = decide(
        [CLIENT, CLIENT],
        None,
        buyer_name="przykład ubezpieczenia na życie s.a.",
        legal_names=legal_names,
    )
    same_company = decide(
        [CLIENT, CLIENT],
        None,
        buyer_name="przykład ubezpieczenia majątkowe s.a.",
        legal_names=legal_names,
    )
    without_legal_name = decide(
        [OTHER, OTHER], None, buyer_name="dowolna s.a.", legal_names=legal_names
    )

    assert (other_company.client_id, other_company.reason) == (
        None,
        "legal_name_differs",
    )
    assert same_company == Proof(CLIENT, SOURCE_PERSONS, 2)
    assert without_legal_name == Proof(OTHER, SOURCE_PERSONS, 2)


@pytest.mark.asyncio
async def test_legal_name_counts_only_when_no_other_client_has_that_name():
    rows_legal = [
        (1, "Alfa S.A."),
        (3, "Gamma Sp. z o.o."),
        (5, "Epsilon S.A."),
    ]
    rows_visible = [
        (1, "Alfa S.A.", None, "Alfa"),
        (2, None, "ALFA  s.a.", "Alfa duplikat"),
        (3, "Gamma Sp. z o.o.", None, "Gamma"),
        (4, None, "Delta S.A.", "Delta"),
    ]
    db = SimpleNamespace(execute=AsyncMock(side_effect=[rows_legal, rows_visible]))

    by_name, of_client = await buyer_proof._legal_names(db)

    # Alfa: ta sama nazwa u drugiego klienta; Delta: to nie nazwa prawna;
    # Epsilon: klient spoza podpowiedzi (np. nieaktywny).
    assert by_name == {"gamma sp. z o.o.": 3}
    assert of_client == {1: "alfa s.a.", 3: "gamma sp. z o.o.", 5: "epsilon s.a."}


# ── Odczyt czekających faktur i klientów ─────────────────────────────────────


@pytest.mark.asyncio
async def test_waiting_invoices_group_by_number_and_skip_items_before_correction():
    rows = [
        (
            NUMBER,
            None,
            "Nabywca Testowy S.A.",
            2026,
            11,
            [
                {"name": "Jan Przykładowy", "before_correction": True},
                {"name": "Ewa Testowa"},
                "nie pozycja",
            ],
        ),
        (None, "FI12345678", "Nabywca Zagraniczny Oy", None, None, None),
        # Numer ucięty przed pełnym zapisem VAT UE nie należy do jednej firmy.
        (None, "FR1", "Nabywca Ucięty", 2026, 11, [{"name": "Ewa Testowa"}]),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=rows))

    groups = await buyer_proof._waiting(db)

    assert set(groups) == {NUMBER, "FI12345678"}
    assert groups[NUMBER][0].items == ("Ewa Testowa",)
    assert groups[NUMBER][0].period == NOVEMBER
    assert groups["FI12345678"][0].period is None


@pytest.mark.asyncio
async def test_canonical_clients_follow_merges_and_skip_deleted():
    deleted = datetime(2026, 11, 1, tzinfo=timezone.utc)
    rows = [
        (1, None, None),
        (2, 1, None),
        (3, None, deleted),
        (4, 3, None),
        (5, 99, None),
    ]
    db = SimpleNamespace(
        execute=AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    )

    assert await clients.canonical_clients(db) == {1: 1, 2: 1}


# ── Stan numeru i zapis ──────────────────────────────────────────────────────


class _Savepoint:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.log.append("rollback" if exc_type else "release")
        return False


def _waiting(*names: str, buyer_name: str = "Nabywca Testowy S.A."):
    return [
        buyer_proof._Waiting(
            buyer_name=buyer_name, period=NOVEMBER, items=(_item(name),)
        )
        for name in names
    ]


class _World:
    """Czekające faktury, osoby i stany numerów zamiast bazy."""

    def __init__(self, monkeypatch, groups, *, states=None, failing=()) -> None:
        self.log: list[str] = []
        self.saved: list[tuple[str, int]] = []
        self.db = SimpleNamespace(begin_nested=lambda: _Savepoint(self.log))
        self.record = AsyncMock()
        states = states or {}

        async def waiting(_db):
            return groups

        async def people(_db):
            return People(PEOPLE)

        async def legal_names(_db):
            return {}, {}

        async def check(_db, client_id, number):
            return clients.BuyerNumber(
                states.get(number, "add"), number=number, client_id=client_id
            )

        async def invoices_waiting(_db, number):
            return [
                SimpleNamespace(id=100, invoice_number="FS 1/11/2026", buyer=number)
            ]

        async def save(_db, invoice, *, client_id=None):
            if invoice.buyer in failing:
                raise RuntimeError("awaria zapisu")
            self.saved.append((invoice.buyer, client_id))
            return {
                "state": "add",
                "number": invoice.buyer,
                "client_id": client_id,
                "saved": True,
                "retried": 3,
                "matched": 1,
            }

        monkeypatch.setattr(buyer_proof, "_waiting", waiting)
        monkeypatch.setattr(buyer_proof, "_people", people)
        monkeypatch.setattr(buyer_proof, "_legal_names", legal_names)
        monkeypatch.setattr(clients, "check_buyer_number", check)
        monkeypatch.setattr(matching, "invoices_waiting_for_number", invoices_waiting)
        monkeypatch.setattr(matching, "save_buyer_number", save)
        monkeypatch.setattr(critical_events, "record_executed", self.record)

    async def attach(self) -> dict[str, int]:
        return await buyer_proof.attach(self.db)


@pytest.mark.asyncio
async def test_unanimous_people_attach_the_number_like_finance_with_the_source(
    monkeypatch,
):
    world = _World(monkeypatch, {NUMBER: _waiting("Jan Przykładowy", "Ewa Testowa")})

    result = await world.attach()

    assert result == {"proven": 1, "added": 1, "matched": 1}
    assert world.saved == [(NUMBER, CLIENT)]
    assert world.log == ["release"]
    event = world.record.await_args.kwargs
    assert event["actor"] is None
    assert event["event_type"] == "client.registry_number_added"
    assert event["client_id"] == CLIENT
    assert event["details"] == {
        "invoice_id": 100,
        "retried": 3,
        "matched": 1,
        "source": "auto_persons",
        "named_positions": 2,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["differs", "taken", "same"])
async def test_number_stays_with_finance_unless_the_client_can_take_it(
    monkeypatch, state
):
    """Klient z innym numerem, numer innego klienta: decydują Finanse."""

    world = _World(
        monkeypatch,
        {NUMBER: _waiting("Jan Przykładowy", "Ewa Testowa")},
        states={NUMBER: state},
    )

    proposals = await buyer_proof.plan(world.db)
    result = await world.attach()

    assert [(p.proof.client_id, p.state) for p in proposals] == [(CLIENT, state)]
    assert result["added"] == 0
    assert world.saved == []
    world.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_numbers_proving_one_client_stay_with_finance(monkeypatch):
    world = _World(
        monkeypatch,
        {
            NUMBER: _waiting("Jan Przykładowy", "Ewa Testowa"),
            SECOND_NUMBER: _waiting("Jan Przykładowy", "Ewa Testowa"),
        },
    )

    proposals = await buyer_proof.plan(world.db)
    result = await world.attach()

    assert {p.state for p in proposals} == {"several_numbers"}
    assert result["added"] == 0
    assert world.saved == []


@pytest.mark.asyncio
async def test_failed_buyer_rolls_back_its_savepoint_and_the_rest_goes_on(
    monkeypatch,
):
    groups = {
        NUMBER: _waiting("Jan Przykładowy", "Ewa Testowa"),
        SECOND_NUMBER: _waiting("Adam Wzorcowy", "Adam Wzorcowy"),
    }
    world = _World(monkeypatch, groups, failing={NUMBER})

    result = await world.attach()

    assert world.log == ["rollback", "release"]
    assert world.saved == [(SECOND_NUMBER, OTHER)]
    assert result == {"proven": 2, "added": 1, "matched": 1}


@pytest.mark.asyncio
async def test_buyer_without_waiting_invoices_any_more_is_skipped(monkeypatch):
    """Finanse przypisały faktury między odczytem a zapisem."""

    world = _World(monkeypatch, {NUMBER: _waiting("Jan Przykładowy", "Ewa Testowa")})
    monkeypatch.setattr(
        matching, "invoices_waiting_for_number", AsyncMock(return_value=[])
    )

    result = await world.attach()

    assert result["added"] == 0
    assert world.saved == []
    world.record.assert_not_awaited()
