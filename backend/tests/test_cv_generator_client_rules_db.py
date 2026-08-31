"""Bramka zatwierdzenia reguły CV — test na realnej bazie.

To jest niezmiennik, na którym stoi cała strategia zasiewania: migracja
dopasowuje szablony Championa do klientów PO NAZWIE, co w tym repo jest
normalnie zakazane (`Client.name` nadpisuje sync Traffita, „BNP" to rodzina
rekordów). Wolno tak tylko dlatego, że zasiana reguła **nie obowiązuje**,
dopóki człowiek jej nie zatwierdzi.

Gdyby `resolve_client_rule` przestało filtrować po `confirmed_at`, błędne
dopasowanie weszłoby na produkcję po cichu — a objawem byłby plik CV nazwany
wzorem innego klienta, wykryty dopiero przez odbiorcę.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.client import Client, ClientStatus
from app.models.client_cv_rule import ClientCvRule
from app.services.cv_generator_b2b.client_rules import resolve_client_rule

pytestmark = pytest.mark.asyncio


async def _make_client(db, name: str) -> Client:
    row = Client(name=name, status=ClientStatus.active, hidden=False)
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_unconfirmed_rule_is_invisible_to_the_generator():
    async with AsyncSessionLocal() as db:
        client = await _make_client(db, "Pytest CV Rule Client")
        db.add(
            ClientCvRule(
                client_id=client.id,
                filename_pattern="B2B_{IMIE_NAZWISKO}",
                confirmed_at=None,
            )
        )
        await db.commit()
        client_id = client.id

    try:
        async with AsyncSessionLocal() as db:
            assert await resolve_client_rule(db, client_id) is None, (
                "Propozycja z seeda NIE MOŻE obowiązywać przed zatwierdzeniem"
            )

        # …a po zatwierdzeniu ta sama reguła staje się widoczna.
        async with AsyncSessionLocal() as db:
            rule = (
                await db.execute(
                    select(ClientCvRule).where(ClientCvRule.client_id == client_id)
                )
            ).scalar_one()
            rule.confirmed_at = datetime.now(timezone.utc)
            await db.commit()

        async with AsyncSessionLocal() as db:
            found = await resolve_client_rule(db, client_id)
            assert found is not None
            assert found.filename_pattern == "B2B_{IMIE_NAZWISKO}"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientCvRule).where(ClientCvRule.client_id == client_id)
            )
            await db.execute(delete(Client).where(Client.id == client_id))
            await db.commit()


@pytest.mark.asyncio
async def test_no_client_means_no_rule():
    """Brak wskazanego klienta zostawia dotychczasowe zachowanie generatora."""
    async with AsyncSessionLocal() as db:
        assert await resolve_client_rule(db, None) is None
        assert await resolve_client_rule(db, 0) is None
