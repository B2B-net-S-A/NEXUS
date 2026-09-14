"""Cortex → Następcy: okno kończących się umów (UAT M10-B02).

„Kończy się" to data końca UMOWY w oknie ``[dziś, dziś + N]``. Koniec okresu
zamówienia nie kończy współpracy, więc nie wciąga umowy bezterminowej na
listę i nie jest pokazywany jako „koniec"; umowy z datą w przeszłości odpadają.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.services.cortex.client_stack import contract_successors

pytestmark = pytest.mark.asyncio

NOW = date(2031, 3, 1)


async def _seed(db, client: Client, *, end: date | None, order_end: date | None) -> int:
    candidate = Candidate(
        name="Następca",
        lastname=f"Okno-{uuid.uuid4().hex[:6]}",
        email=f"succ-{uuid.uuid4().hex[:8]}@example.com",
    )
    db.add(candidate)
    await db.flush()
    contract = Contract(
        candidate_id=candidate.id,
        client_id=client.id,
        contract_type=ContractType.b2b,
        status=ContractStatus.active,
        start_date=NOW - timedelta(days=400),
        end_date=end,
        client_order_end_date=order_end,
        rate_candidate=Decimal("100.000"),
        rate_unit=RateUnit.hourly,
        currency="PLN",
        rate_candidate_currency="PLN",
    )
    db.add(contract)
    await db.flush()
    return contract.id


async def test_window_uses_the_contract_end_and_ignores_past_and_order_only_ends():
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Następcy {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        ending = await _seed(
            db, client, end=NOW + timedelta(days=10), order_end=NOW + timedelta(days=90)
        )
        indefinite_old_order = await _seed(
            db, client, end=None, order_end=NOW - timedelta(days=900)
        )
        indefinite_order_in_window = await _seed(
            db, client, end=None, order_end=NOW + timedelta(days=5)
        )
        already_past = await _seed(
            db, client, end=NOW - timedelta(days=3), order_end=None
        )
        beyond_window = await _seed(
            db, client, end=NOW + timedelta(days=45), order_end=None
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        result = await contract_successors(db, now=NOW, days=30)

    rows = {row["contract_id"]: row for row in result["ending_contracts"]}
    assert ending in rows
    assert rows[ending]["end_date"] == (NOW + timedelta(days=10)).isoformat()
    assert (
        rows[ending]["client_order_end_date"] == (NOW + timedelta(days=90)).isoformat()
    )
    for excluded in (
        indefinite_old_order,
        indefinite_order_in_window,
        already_past,
        beyond_window,
    ):
        assert excluded not in rows
