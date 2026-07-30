"""Integration contract for the scope-shaped Clients directory."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.client_directory import (
    ClientAlias,
    ClientPortfolioScope,
    PortfolioCategory,
)
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.contract import Contract, ContractStatus

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _seed_directory() -> dict[str, object]:
    suffix = uuid.uuid4().hex[:10]
    today = date.today()
    async with AsyncSessionLocal() as db:
        alpha = Client(
            name=f"Source Alpha {suffix}",
            display_name=f"Alpha {suffix}",
            legal_name=f"Alpha Legal {suffix} S.A.",
            industry="Banking",
            status=ClientStatus.active,
        )
        zulu = Client(
            name=f"Source Zulu {suffix}",
            display_name=f"Zulu {suffix}",
            legal_name=f"Zulu Legal {suffix} S.A.",
            industry="Engineering",
            status=ClientStatus.prospect,
        )
        hidden = Client(
            name=f"Hidden {suffix}",
            hidden=True,
            status=ClientStatus.active,
        )
        db.add_all((alpha, zulu, hidden))
        await db.flush()

        msa = ClientFrameworkContract(
            client_id=zulu.id,
            name=f"MSA {suffix}",
            status=FrameworkContractStatus.active,
            effective_date=today - timedelta(days=30),
            expiry_date=None,
        )
        db.add(msa)
        await db.flush()

        scopes = [
            ClientPortfolioScope(
                client_id=alpha.id,
                category=PortfolioCategory.active,
                label=None,
                source_system="test",
                source_key=f"{suffix}:alpha",
            ),
            ClientPortfolioScope(
                client_id=zulu.id,
                framework_contract_id=msa.id,
                category=PortfolioCategory.active,
                label="B scope",
                source_system="test",
                source_key=f"{suffix}:zulu-b",
            ),
            ClientPortfolioScope(
                client_id=zulu.id,
                category=PortfolioCategory.active,
                label="A scope",
                source_system="test",
                source_key=f"{suffix}:zulu-a",
            ),
            ClientPortfolioScope(
                client_id=zulu.id,
                category=PortfolioCategory.relationship,
                label="Pentesty",
                source_system="test",
                source_key=f"{suffix}:zulu-rel",
            ),
            ClientPortfolioScope(
                client_id=hidden.id,
                category=PortfolioCategory.active,
                source_system="test",
                source_key=f"{suffix}:hidden",
            ),
        ]
        db.add_all(scopes)
        db.add(
            ClientAlias(
                client_id=zulu.id,
                alias=f"Legacy Alias {suffix}",
                normalized_alias=f"legacy alias {suffix}",
                source_system="test",
                source_key=f"{suffix}:alias",
            )
        )

        candidate_one = Candidate(name="Anna", lastname=f"One-{suffix}")
        candidate_two = Candidate(name="Jan", lastname=f"Two-{suffix}")
        candidate_future = Candidate(name="Future", lastname=f"Three-{suffix}")
        candidate_ended = Candidate(name="Ended", lastname=f"Four-{suffix}")
        db.add_all(
            (candidate_one, candidate_two, candidate_future, candidate_ended)
        )
        await db.flush()
        contracts = [
            Contract(
                candidate_id=candidate_one.id,
                client_id=zulu.id,
                status=ContractStatus.active,
                start_date=today - timedelta(days=10),
                end_date=None,
            ),
            # Same candidate twice must still count once.
            Contract(
                candidate_id=candidate_one.id,
                client_id=zulu.id,
                status=ContractStatus.ending,
                start_date=today - timedelta(days=5),
                end_date=today + timedelta(days=5),
            ),
            Contract(
                candidate_id=candidate_two.id,
                client_id=zulu.id,
                status=ContractStatus.ending,
                start_date=today,
                end_date=today,
            ),
            Contract(
                candidate_id=candidate_future.id,
                client_id=zulu.id,
                status=ContractStatus.active,
                start_date=today + timedelta(days=1),
                end_date=None,
            ),
            Contract(
                candidate_id=candidate_ended.id,
                client_id=zulu.id,
                status=ContractStatus.active,
                start_date=today - timedelta(days=20),
                end_date=today - timedelta(days=1),
            ),
        ]
        db.add_all(contracts)
        await db.commit()
        return {
            "suffix": suffix,
            "client_ids": [alpha.id, zulu.id, hidden.id],
            "candidate_ids": [
                candidate_one.id,
                candidate_two.id,
                candidate_future.id,
                candidate_ended.id,
            ],
            "msa_id": msa.id,
        }


async def _cleanup_directory(seed: dict[str, object]) -> None:
    client_ids = seed["client_ids"]
    candidate_ids = seed["candidate_ids"]
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Contract).where(Contract.client_id.in_(client_ids)))
        await db.execute(
            delete(ClientAlias).where(ClientAlias.client_id.in_(client_ids))
        )
        await db.execute(
            delete(ClientPortfolioScope).where(
                ClientPortfolioScope.client_id.in_(client_ids)
            )
        )
        await db.execute(
            delete(ClientFrameworkContract).where(
                ClientFrameworkContract.client_id.in_(client_ids)
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.commit()


async def test_directory_requires_auth(app_client: AsyncClient) -> None:
    response = await app_client.get("/api/clients/directory")
    assert response.status_code == 401


async def test_directory_counts_scopes_sorts_and_counts_consultants(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    seed = await _seed_directory()
    try:
        response = await app_client.get(
            "/api/clients/directory",
            params={
                "category": "active",
                "q": seed["suffix"],
                "page": 1,
                "page_size": 50,
            },
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total_rows"] == 3
        assert body["total_clients"] == 2
        assert body["page_size"] == 50
        assert body["category_counts"]["active"] >= 2
        assert body["category_counts"]["relationship"] >= 1

        items = body["items"]
        assert [item["display_name"].split()[0] for item in items] == [
            "Alpha",
            "Zulu",
            "Zulu",
        ]
        assert [item["scope_label"] for item in items[1:]] == [
            "A scope",
            "B scope",
        ]
        assert {item["active_consultants_count"] for item in items[1:]} == {2}
        assert items[1]["client_status"] == "prospect"
        assert items[2]["effective_date"] is not None
        assert items[2]["expiry_date"] is None
        assert items[2]["msa_id"] == seed["msa_id"]
    finally:
        await _cleanup_directory(seed)


@pytest.mark.parametrize("needle_kind", ["alias", "legal", "industry", "scope"])
async def test_directory_search_is_scoped_to_selected_category(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    needle_kind: str,
) -> None:
    seed = await _seed_directory()
    suffix = seed["suffix"]
    needles = {
        "alias": f"Legacy Alias {suffix}",
        "legal": f"Zulu Legal {suffix}",
        "industry": "Engineering",
        "scope": "A scope",
    }
    try:
        active = await app_client.get(
            "/api/clients/directory",
            params={"category": "active", "q": needles[needle_kind]},
            headers=app_auth_headers,
        )
        assert active.status_code == 200, active.text
        assert active.json()["total_clients"] == 1
        assert all(
            item["display_name"].startswith("Zulu")
            for item in active.json()["items"]
        )

        relationship = await app_client.get(
            "/api/clients/directory",
            params={"category": "relationship", "q": needles[needle_kind]},
            headers=app_auth_headers,
        )
        assert relationship.status_code == 200, relationship.text
        if needle_kind in {"alias", "legal", "industry"}:
            assert relationship.json()["total_rows"] == 1
            assert relationship.json()["items"][0]["scope_label"] == "Pentesty"
        else:
            assert relationship.json()["total_rows"] == 0
    finally:
        await _cleanup_directory(seed)


async def test_scope_crud_archives_instead_of_deleting(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    seed = await _seed_directory()
    client_id = seed["client_ids"][0]
    try:
        created = await app_client.post(
            f"/api/clients/{client_id}/portfolio-scopes",
            json={"category": "inactive", "label": "Manual"},
            headers=app_auth_headers,
        )
        assert created.status_code == 201, created.text
        scope_id = created.json()["id"]

        updated = await app_client.patch(
            f"/api/clients/{client_id}/portfolio-scopes/{scope_id}",
            json={"category": "relationship", "label": "Relacja"},
            headers=app_auth_headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["category"] == "relationship"

        archived = await app_client.delete(
            f"/api/clients/{client_id}/portfolio-scopes/{scope_id}",
            headers=app_auth_headers,
        )
        assert archived.status_code == 204, archived.text
        async with AsyncSessionLocal() as db:
            scope = await db.get(ClientPortfolioScope, scope_id)
            assert scope is not None
            assert scope.archived_at is not None
    finally:
        await _cleanup_directory(seed)


async def test_scope_crud_rejects_null_category_foreign_and_occupied_msa(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    seed = await _seed_directory()
    alpha_id, zulu_id, _hidden_id = seed["client_ids"]
    msa_id = seed["msa_id"]
    try:
        foreign_msa = await app_client.post(
            f"/api/clients/{alpha_id}/portfolio-scopes",
            json={
                "category": "active",
                "framework_contract_id": msa_id,
            },
            headers=app_auth_headers,
        )
        assert foreign_msa.status_code == 422, foreign_msa.text

        occupied_msa = await app_client.post(
            f"/api/clients/{zulu_id}/portfolio-scopes",
            json={
                "category": "active",
                "framework_contract_id": msa_id,
            },
            headers=app_auth_headers,
        )
        assert occupied_msa.status_code == 409, occupied_msa.text

        created = await app_client.post(
            f"/api/clients/{alpha_id}/portfolio-scopes",
            json={"category": "inactive", "label": "Validate null"},
            headers=app_auth_headers,
        )
        assert created.status_code == 201, created.text
        scope_id = created.json()["id"]

        null_category = await app_client.patch(
            f"/api/clients/{alpha_id}/portfolio-scopes/{scope_id}",
            json={"category": None},
            headers=app_auth_headers,
        )
        assert null_category.status_code == 422, null_category.text
    finally:
        await _cleanup_directory(seed)
