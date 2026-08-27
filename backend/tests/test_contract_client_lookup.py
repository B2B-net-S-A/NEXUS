"""Client picker for a new contract follows the Client module tabs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory


pytestmark = pytest.mark.asyncio


async def test_contract_lookup_uses_effective_active_and_relationship_tabs(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    unique = uuid.uuid4().hex[:10]
    clients: list[Client] = []
    async with AsyncSessionLocal() as db:
        for label in (
            "active",
            "relationship",
            "inactive",
            "override",
            "archived-scope",
            "hidden-client",
            "archived-client",
            "merged-client",
        ):
            client = Client(name=f"Contract lookup {label} {unique}")
            db.add(client)
            clients.append(client)
        await db.flush()

        db.add_all(
            [
                ClientPortfolioScope(
                    client_id=clients[0].id,
                    category=PortfolioCategory.active,
                    source_system="test",
                    source_key=f"contract-lookup-active-{unique}",
                ),
                ClientPortfolioScope(
                    client_id=clients[1].id,
                    category=PortfolioCategory.relationship,
                    source_system="test",
                    source_key=f"contract-lookup-relationship-{unique}",
                ),
                ClientPortfolioScope(
                    client_id=clients[2].id,
                    category=PortfolioCategory.inactive,
                    source_system="test",
                    source_key=f"contract-lookup-inactive-{unique}",
                ),
                # Effective category is the manual override, not the manifest.
                ClientPortfolioScope(
                    client_id=clients[3].id,
                    category=PortfolioCategory.inactive,
                    category_override=PortfolioCategory.active,
                    source_system="test",
                    source_key=f"contract-lookup-override-{unique}",
                ),
                # Archived scopes never make a client selectable.
                ClientPortfolioScope(
                    client_id=clients[4].id,
                    category=PortfolioCategory.active,
                    archived_at=datetime.now(timezone.utc),
                    source_system="test",
                    source_key=f"contract-lookup-archived-{unique}",
                ),
                ClientPortfolioScope(
                    client_id=clients[5].id,
                    category=PortfolioCategory.active,
                    source_system="test",
                    source_key=f"contract-lookup-hidden-client-{unique}",
                ),
                ClientPortfolioScope(
                    client_id=clients[6].id,
                    category=PortfolioCategory.relationship,
                    source_system="test",
                    source_key=f"contract-lookup-archived-client-{unique}",
                ),
                ClientPortfolioScope(
                    client_id=clients[7].id,
                    category=PortfolioCategory.active,
                    source_system="test",
                    source_key=f"contract-lookup-merged-client-{unique}",
                ),
            ]
        )
        clients[5].hidden = True
        clients[6].archived_at = datetime.now(timezone.utc)
        clients[7].merged_into_client_id = clients[0].id
        await db.commit()
        client_ids = [client.id for client in clients]

    response = await app_client.get(
        "/api/clients-lookup?contract_eligible=true",
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    returned_ids = {row["id"] for row in response.json()}
    assert set(client_ids[:2]) <= returned_ids
    assert client_ids[3] in returned_ids
    assert client_ids[2] not in returned_ids
    assert client_ids[4] not in returned_ids
    assert client_ids[5] not in returned_ids
    assert client_ids[6] not in returned_ids
    assert client_ids[7] not in returned_ids


async def test_default_lookup_remains_backward_compatible(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    unique = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Contract lookup legacy {unique}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        client_id = client.id

    response = await app_client.get("/api/clients-lookup", headers=app_auth_headers)

    assert response.status_code == 200, response.text
    assert client_id in {row["id"] for row in response.json()}
