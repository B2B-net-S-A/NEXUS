"""Stawki w Generatorze Umów B2B (decyzja Artura 22.09.2026).

Wszystkie stawki widzą admin i Finanse, Delivery Lead — klientów ze swojego
portfela, a każda inna rola wyłącznie umowy, które sama wygenerowała, albo
z rekrutacji, które prowadzi. Wejście do rejestru zostaje otwarte (20.08).
Cudzy DOCX (niesie stawkę w treści) nie jest wydawany wcale: 403 i
``can_download = False`` w rejestrze.

In-process `app_client`; baza testowa wspólna i nieczyszczona — asercje tylko
na własnych wierszach.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed_user(app_client: AsyncClient, role: str) -> tuple[dict, int]:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"b2b-rates-{role}-{unique}@example.com"
    password = f"T3st_{unique}!Rate"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"B2B rates {role}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        uid = user.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, uid


async def _seed_documents(*, author_id: int, job_recruiter_id: int) -> dict:
    """Kontrakt B2B ze stawką i wpis rejestru — oba z rekrutacji rekrutera."""

    from app.models.activity import Activity
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"B2BRates-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="B2B rates job",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=job_recruiter_id,
        )
        db.add(job)
        await db.flush()
        contract = Contract(
            client_id=client.id,
            job_id=job.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.draft,
            rate_candidate=Decimal("150"),
            start_date=date(2026, 10, 1),
        )
        db.add(contract)
        await db.flush()
        # Autorstwo kontraktu niesie dziennik `b2b_generated` (POST /generate).
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract.id,
                action="b2b_generated",
                user_id=author_id,
            )
        )
        seq = int(uuid.uuid4().int % 900_000) + 100_000
        row = B2BGeneratedContract(
            year=2099,
            seq=seq,
            contract_number=f"{seq}/2099",
            client_id=client.id,
            job_id=job.id,
            created_by=author_id,
            render_payload=None,
        )
        db.add(row)
        await db.commit()
        return {"contract_id": contract.id, "generated_id": row.id, "job_id": job.id}


@pytest.fixture
async def world(app_client: AsyncClient):
    admin_h = {
        "Authorization": (
            "Bearer "
            + (
                await app_client.post(
                    "/api/auth/login",
                    json={
                        "email": app_client.headers["X-Test-Admin-Email"],
                        "password": app_client.headers["X-Test-Admin-Password"],
                    },
                )
            ).json()["access_token"]
        )
    }
    author_h, author_id = await _seed_user(app_client, "sourcer")
    runner_h, runner_id = await _seed_user(app_client, "recruiter")
    outsider_h, _ = await _seed_user(app_client, "recruiter")
    finance_h, _ = await _seed_user(app_client, "finance")
    hor_h, _ = await _seed_user(app_client, "head_of_recruitment")
    docs = await _seed_documents(author_id=author_id, job_recruiter_id=runner_id)
    return {
        **docs,
        "admin": admin_h,
        "author": author_h,
        "runner": runner_h,
        "outsider": outsider_h,
        "finance": finance_h,
        "hor": hor_h,
    }


VISIBLE = ("admin", "finance", "author", "runner")
HIDDEN = ("outsider", "hor")


@pytest.mark.asyncio
async def test_contract_detail_redacts_rates_of_someone_elses_contract(
    app_client, world
):
    url = f"/api/b2b-generator/contracts/{world['contract_id']}/detail"
    for who in VISIBLE + HIDDEN:
        resp = await app_client.get(url, headers=world[who])
        assert resp.status_code == 200, (who, resp.text)
        rate = resp.json()["rate_candidate"]
        if who in VISIBLE:
            assert rate is not None and float(rate) == 150.0, who
        else:
            assert rate is None, who


@pytest.mark.asyncio
async def test_docx_of_someone_elses_contract_is_not_issued(app_client, world):
    contract_docx = f"/api/b2b-generator/contracts/{world['contract_id']}/docx"
    generated_docx = f"/api/b2b-generator/generated/{world['generated_id']}/docx"
    for who in HIDDEN:
        for url in (contract_docx, generated_docx):
            resp = await app_client.get(url, headers=world[who])
            assert resp.status_code == 403, (who, url, resp.text)
    # Autor przechodzi bramkę stawek — wpis bez payloadu kończy się dopiero 422.
    resp = await app_client.get(generated_docx, headers=world["author"])
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_register_hides_download_for_rows_with_hidden_rates(app_client, world):
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, world["generated_id"])
        row.render_payload = {"language": "pl"}
        await db.commit()

    for who, expected in (("author", True), ("runner", True), ("outsider", False)):
        resp = await app_client.get(
            "/api/b2b-generator/generated",
            headers=world[who],
            params={"job_id": world["job_id"]},
        )
        assert resp.status_code == 200, (who, resp.text)
        [item] = [i for i in resp.json() if i["id"] == world["generated_id"]]
        assert item["can_download"] is expected, who
