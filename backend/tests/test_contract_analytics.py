"""Tests for Phase 9 B4 — contract analytics endpoints."""

import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType


async def test_margin_by_contractor_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contract-analytics/margin-by-contractor", headers=app_auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for row in data:
        assert {
            "candidate_id",
            "candidate_name",
            "active_contracts",
            "total_monthly_margin",
            "total_monthly_revenue",
            "margin_pct",
        } <= set(row.keys())


async def test_margin_by_client_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/margin-by-client", headers=app_auth_headers
    )
    assert resp.status_code == 200
    for row in resp.json():
        assert "client_id" in row
        assert "total_monthly_margin" in row


async def test_utilization_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/utilization", headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {
        "total_candidates",
        "candidates_active",
        "active_contracts",
        "candidates_on_bench",
        "utilization_pct",
        "avg_bench_days",
    } == set(body.keys())
    assert body["total_candidates"] >= body["candidates_active"]
    assert body["active_contracts"] >= body["candidates_active"]


async def test_revenue_forecast_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/revenue-forecast?horizon_months=6",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["horizon_months"] == 6
    assert len(body["months"]) == 6
    for m in body["months"]:
        assert {"month", "month_label", "revenue", "margin", "active_count"} <= set(
            m.keys()
        )


async def test_role_client_mix_sigma_deduplicates_person_across_clients(
    app_client: AsyncClient, app_auth_headers: dict
):
    marker = uuid.uuid4().hex[:10]
    role = f"Role-{marker}"
    contract_ids: list[int] = []
    candidate_ids: list[int] = []
    client_ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            candidates = [
                Candidate(
                    name="Piotr",
                    lastname="Klimczak",
                    competence_category=role,
                ),
                Candidate(
                    name="PIOTR",
                    lastname="Klim-czak",
                    competence_category=role,
                ),
            ]
            clients = [
                Client(name=f"Client A {marker}"),
                Client(name=f"Client B {marker}"),
            ]
            db.add_all([*candidates, *clients])
            await db.flush()
            contracts = [
                Contract(
                    candidate_id=candidate.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=date.today() - timedelta(days=10),
                    end_date=date.today() + timedelta(days=30),
                )
                for candidate, client in zip(candidates, clients, strict=True)
            ]
            db.add_all(contracts)
            await db.commit()
            contract_ids = [contract.id for contract in contracts]
            candidate_ids = [candidate.id for candidate in candidates]
            client_ids = [client.id for client in clients]

        response = await app_client.get(
            "/api/contract-analytics/role-client-mix",
            headers=app_auth_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        role_rows = [row for row in body["rows"] if row["role"] == role]
        assert len(role_rows) == 2
        assert {row["active_count"] for row in role_rows} == {1}
        assert body["role_totals"][role] == 1
    finally:
        async with AsyncSessionLocal() as db:
            if contract_ids:
                await db.execute(delete(Contract).where(Contract.id.in_(contract_ids)))
            if candidate_ids:
                await db.execute(
                    delete(Candidate).where(Candidate.id.in_(candidate_ids))
                )
            if client_ids:
                await db.execute(delete(Client).where(Client.id.in_(client_ids)))
            await db.commit()
