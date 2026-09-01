"""Smoke tests for the new contract analytics endpoints."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient


async def test_role_client_mix_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/role-client-mix", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "total_active" in body
    assert "rows" in body
    assert "roles" in body
    assert "clients" in body
    for row in body["rows"]:
        for key in ("role", "client_id", "client_name", "active_count", "pct_of_total"):
            assert key in row


async def test_location_distribution_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contract-analytics/location-distribution", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("total", "total_with_hub", "hubs", "regions"):
        assert key in body


async def test_termination_analysis_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contract-analytics/termination-analysis?window_months=24",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("window_months", "total_terminated", "by_reason", "client_retention"):
        assert key in body
    for r in body["by_reason"]:
        for key in ("reason", "count", "avg_contract_days"):
            assert key in r
    for r in body["client_retention"]:
        for key in (
            "client_id",
            "client_name",
            "total_ended",
            "kept_to_end",
            "ended_early",
            "retention_pct",
        ):
            assert key in r


async def test_contract_analytics_use_canonical_client_display_name(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.job import Job

    marker = uuid.uuid4().hex[:8]
    canonical_name = f"Canonical Analytics Client {marker}"
    today = date.today()
    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"Raw Analytics Client {marker}",
            display_name=f"  {canonical_name}  ",
        )
        candidate = Candidate(name="Analytics", lastname=f"Candidate-{marker}")
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"Analytics Role {marker}",
            client_id=client.id,
        )
        db.add(job)
        await db.flush()
        db.add_all(
            [
                Contract(
                    candidate_id=candidate.id,
                    client_id=client.id,
                    job_id=job.id,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=30),
                    rate_candidate=Decimal("1"),
                    rate_client=Decimal("99999999"),
                    rate_unit=RateUnit.monthly,
                ),
                Contract(
                    candidate_id=candidate.id,
                    client_id=client.id,
                    job_id=job.id,
                    status=ContractStatus.ended,
                    start_date=today - timedelta(days=120),
                    end_date=today - timedelta(days=1),
                ),
            ]
        )
        await db.commit()
        client_id = client.id

    margin = await app_client.get(
        "/api/contract-analytics/margin-by-client?limit=100",
        headers=app_auth_headers,
    )
    assert margin.status_code == 200, margin.text
    assert (
        next(r for r in margin.json() if r["client_id"] == client_id)["client_name"]
        == canonical_name
    )

    role_mix = await app_client.get(
        "/api/contract-analytics/role-client-mix",
        headers=app_auth_headers,
    )
    assert role_mix.status_code == 200, role_mix.text
    assert (
        next(r for r in role_mix.json()["rows"] if r["client_id"] == client_id)[
            "client_name"
        ]
        == canonical_name
    )

    termination = await app_client.get(
        "/api/contract-analytics/termination-analysis?window_months=24",
        headers=app_auth_headers,
    )
    assert termination.status_code == 200, termination.text
    assert (
        next(
            r
            for r in termination.json()["client_retention"]
            if r["client_id"] == client_id
        )["client_name"]
        == canonical_name
    )
