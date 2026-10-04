"""Migracja 0278: `jobs.remote_policy` traci NOT NULL i domyślną 'hybrid'.

Do tej migracji KAŻDA oferta bez ręcznie ustawionego trybu dostawała
'hybrid' (przez `JobCreate.remote_policy = RemotePolicy.hybrid` i importer
Traffita), więc „nieznane" było nieodróżnialne od „chce biura" —
dealbreaker `remote_only_refuses_office` ukrywał kandydatów gotowych
wyłącznie na zdalną pracę na każdej takiej ofercie.

`JobResponse.remote_policy` było też NIE-Optional. Samo poluzowanie kolumny
w bazie/ORM bez poluzowania schematu odpowiedzi wywróciłoby KAŻDY odczyt
oferty bez trybu 500-tką (`ResponseValidationError`) zamiast dać 201/200
z `null` — więc test przechodzi przez CAŁY łańcuch (baza -> ORM -> Pydantic
-> JSON), nie tylko przez `JobResponse.model_validate` w izolacji.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _seed_client_id() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"pytest-remote-policy-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _create_job(app_client: AsyncClient, headers: dict, **overrides) -> dict:
    """Rekrutacja z wierszem w bazie, odczytana przez API (łańcuch baza → ORM
    → Pydantic → JSON).

    Od 04.10.2026 (rekrutacja bez szkiców) ``POST /api/jobs`` nie założy
    rekrutacji bez trybu pracy — bramka przekazania go wymaga. Rekrutację
    z ``remote_policy = NULL`` (stare wiersze, import) zakładamy więc wprost
    w bazie, jako szkic: ochrona rekrutacji w pracy przed nowym brakiem nie
    jest przedmiotem tych testów.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus, RemotePolicy

    client_id = overrides.pop("client_id", None) or await _seed_client_id()
    if overrides.get("remote_policy") is not None:
        overrides["remote_policy"] = RemotePolicy(overrides["remote_policy"])
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"pytest-remote-policy-{uuid.uuid4().hex[:6]}",
            status=JobStatus.draft,
            client_id=client_id,
            **overrides,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    resp = await app_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_job_without_remote_policy_reads_as_null(
    app_client: AsyncClient, app_auth_headers: dict
):
    body = await _create_job(app_client, app_auth_headers)
    assert body["remote_policy"] is None
    assert body.get("onsite_days_per_week") is None


async def test_patch_remote_policy_null_clears(
    app_client: AsyncClient, app_auth_headers: dict
):
    body = await _create_job(app_client, app_auth_headers, remote_policy="hybrid")
    assert body["remote_policy"] == "hybrid"
    job_id = body["id"]

    patched = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"remote_policy": None},
        headers=app_auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["remote_policy"] is None


async def test_patch_rate_budget_hourly_null_clears(
    app_client: AsyncClient, app_auth_headers: dict
):
    body = await _create_job(app_client, app_auth_headers, rate_budget_hourly=180)
    assert body["rate_budget_hourly"] == 180
    job_id = body["id"]

    patched = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"rate_budget_hourly": None},
        headers=app_auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["rate_budget_hourly"] is None


async def test_patch_onsite_days_out_of_range_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    body = await _create_job(app_client, app_auth_headers)
    job_id = body["id"]

    resp = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"onsite_days_per_week": 8},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
