"""Koniec samego zamówienia (bez grupy) też staje w kolejce back office'u.

Na kopii produkcji z 19.11.2026 dawna karta Opieki „Decyzja: koniec zamówienia”
miała 285 kontraktów z końcem w 60 dniach, z czego 272 bez ``contracts.end_date``
(koniec niesie samo zamówienie klienta). Ławka liczy tylko koniec umowy, a
„Przedłużenie” tylko grupy zamówień, więc 218 osób nie miało w Sprawach żadnej
karty: 215 z nich ma zamówienie bez grupy (462 z 556 aktywnych zamówień nie ma
grupy). Zamówienia bez grupy dostają kartę „Przedłużenie” na klienta i datę
końca, a nie kartę ławki na osobę (82 osoby jednego klienta na 31.12 to jedna
rozmowa z klientem, nie 82 karty).

Baza testowa nie jest czyszczona między testami: asercje dotyczą wyłącznie
klientów założonych w danym teście. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus
from app.services.back_office.sources import bench_cards, extend_cards

pytestmark = pytest.mark.asyncio


async def _client() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Przykładowy {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        return client.id


async def _person(
    client_id: int,
    *,
    order_ends: tuple[date, ...],
    contract_end: date | None = None,
    status: ContractStatus = ContractStatus.active,
    group_id: int | None = None,
) -> int:
    """Kontrakt bez końca umowy i jego zamówienia (po jednym na datę końca)."""

    today = business_today()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Ewa",
            lastname=f"Przykładowa-{uuid.uuid4().hex[:6]}",
            email=f"bo-end-{uuid.uuid4().hex[:10]}@example.com",
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            status=status,
            start_date=today - timedelta(days=300),
            end_date=contract_end,
        )
        db.add(contract)
        await db.flush()
        for end in order_ends:
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract.id,
                    order_group_id=group_id,
                    title="Zamówienie przykładowe",
                    status=ClientOrderStatus.active,
                    start_date=today - timedelta(days=300),
                    end_date=end,
                )
            )
        await db.commit()
        return contract.id


def _mine(cards, client_id: int):
    return [card for card in cards if card.client_id == client_id]


async def test_order_end_without_contract_end_gets_an_extension_card() -> None:
    today = business_today()
    end = today + timedelta(days=30)
    client_id = await _client()
    contract_id = await _person(client_id, order_ends=(end,))

    async with AsyncSessionLocal() as db:
        extend = _mine(await extend_cards(db, today), client_id)
        bench = [
            c for c in await bench_cards(db, today) if c.contract_id == contract_id
        ]

    assert [(c.source_key, c.lane, c.due_on) for c in extend] == [
        (f"extend:client:{client_id}:{end.isoformat()}", "extend", end)
    ]
    assert extend[0].client_label == "1 os. na zamówieniu"
    assert extend[0].href == f"/clients/{client_id}?tab=zamowienia"
    # Decyzja o osobie czeka na odpowiedź klienta: bez drugiej karty na osobę.
    assert bench == []


async def test_one_card_per_client_and_end_date() -> None:
    today = business_today()
    end = today + timedelta(days=40)
    other_end = today + timedelta(days=10)
    client_id = await _client()
    for _ in range(3):
        await _person(client_id, order_ends=(end,))
    await _person(client_id, order_ends=(other_end,))

    async with AsyncSessionLocal() as db:
        cards = _mine(await extend_cards(db, today), client_id)

    assert sorted((c.due_on, c.client_label) for c in cards) == [
        (other_end, "1 os. na zamówieniu"),
        (end, "3 os. na zamówieniu"),
    ]


async def test_already_extended_order_and_distant_end_get_no_card() -> None:
    today = business_today()
    client_id = await _client()
    # Klient już przedłużył: ta sama osoba ma zamówienie z dalszym końcem.
    await _person(
        client_id, order_ends=(today + timedelta(days=20), today + timedelta(days=385))
    )
    # Koniec dalej niż 45 dni: karta stanie później.
    await _person(client_id, order_ends=(today + timedelta(days=50),))
    # Kontrakt zakończony: nikt już nie pracuje na tym zamówieniu.
    await _person(
        client_id, order_ends=(today + timedelta(days=20),), status=ContractStatus.ended
    )

    async with AsyncSessionLocal() as db:
        assert _mine(await extend_cards(db, today), client_id) == []


async def test_grouped_order_keeps_only_the_group_card() -> None:
    today = business_today()
    end = today + timedelta(days=30)
    client_id = await _client()
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"ZP-{uuid.uuid4().hex[:6]}",
            start_date=today - timedelta(days=300),
            end_date=end,
            status="active",
        )
        db.add(group)
        await db.commit()
        group_id = group.id
    await _person(client_id, order_ends=(end,), group_id=group_id)

    async with AsyncSessionLocal() as db:
        cards = _mine(await extend_cards(db, today), client_id)

    assert [c.source_key for c in cards] == [f"extend:{group_id}"]


async def test_contract_end_still_gets_a_bench_card() -> None:
    today = business_today()
    end = today + timedelta(days=55)
    client_id = await _client()
    contract_id = await _person(client_id, order_ends=(end,), contract_end=end)

    async with AsyncSessionLocal() as db:
        bench = [
            c for c in await bench_cards(db, today) if c.contract_id == contract_id
        ]

    assert [(c.source_key, c.due_on) for c in bench] == [(f"bench:{contract_id}", end)]
