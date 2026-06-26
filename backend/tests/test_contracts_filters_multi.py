"""Multi-value filter tests for /api/contracts.

Verifies that `status` and `contract_type` accept repeated query params and
that single-value calls remain backward-compatible.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient


async def _seed_candidate_minimal() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="ContractFlt",
            lastname=f"X-{uuid.uuid4().hex[:6]}",
            email=f"cflt-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_client_minimal() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cl = Client(name=f"Client-{uuid.uuid4().hex[:6]}")
        db.add(cl)
        await db.commit()
        await db.refresh(cl)
        return cl.id


async def _seed_contract(
    *, status: str, contract_type: str = "b2b"
) -> tuple[int, int, int]:
    """Seed a contract with required FKs. Returns (contract_id, candidate_id, client_id)."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus, ContractType

    cand_id = await _seed_candidate_minimal()
    client_id = await _seed_client_minimal()

    async with AsyncSessionLocal() as db:
        c = Contract(
            candidate_id=cand_id,
            client_id=client_id,
            status=ContractStatus(status),
            contract_type=ContractType(contract_type),
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() + timedelta(days=60),
            rate_client=10000,
            rate_candidate=8000,
            margin=2000,
            currency="PLN",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id, cand_id, client_id


async def _seed_candidate_named(name: str, lastname: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=name,
            lastname=lastname,
            email=f"cflt-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_contract_named(
    name: str, lastname: str, *, status: str = "active"
) -> tuple[int, int, int]:
    """Seed a contract whose consultant has a known name/lastname (for `q` tests)."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus, ContractType

    cand_id = await _seed_candidate_named(name, lastname)
    client_id = await _seed_client_minimal()

    async with AsyncSessionLocal() as db:
        c = Contract(
            candidate_id=cand_id,
            client_id=client_id,
            status=ContractStatus(status),
            contract_type=ContractType("b2b"),
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() + timedelta(days=60),
            rate_client=10000,
            rate_candidate=8000,
            margin=2000,
            currency="PLN",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id, cand_id, client_id


async def _cleanup(rows: list[tuple[int, int, int]]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for contract_id, _, _ in rows:
            await db.execute(delete(Contract).where(Contract.id == contract_id))
        for _, cand_id, client_id in rows:
            await db.execute(delete(Candidate).where(Candidate.id == cand_id))
            await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


@pytest.mark.asyncio
async def test_contracts_status_filter_accepts_multiple(
    app_client: AsyncClient, app_auth_headers: dict
):
    a = await _seed_contract(status="active")
    e = await _seed_contract(status="ending")
    d = await _seed_contract(status="draft")
    try:
        r = await app_client.get(
            "/api/contracts?status=active&status=ending&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert a[0] in ids
        assert e[0] in ids
        assert d[0] not in ids
    finally:
        await _cleanup([a, e, d])


@pytest.mark.asyncio
async def test_contracts_status_single_value_back_compat(
    app_client: AsyncClient, app_auth_headers: dict
):
    a = await _seed_contract(status="active")
    e = await _seed_contract(status="ended")
    try:
        r = await app_client.get(
            "/api/contracts?status=active&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert a[0] in ids
        assert e[0] not in ids
    finally:
        await _cleanup([a, e])


@pytest.mark.asyncio
async def test_contracts_contract_type_filter_accepts_multiple(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Backend ContractType enum is `b2b | uop | uzlecenie`. Filter on b2b+uop."""
    b = await _seed_contract(status="active", contract_type="b2b")
    u = await _seed_contract(status="active", contract_type="uop")
    z = await _seed_contract(status="active", contract_type="uzlecenie")
    try:
        r = await app_client.get(
            "/api/contracts?contract_type=b2b&contract_type=uop&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert b[0] in ids
        assert u[0] in ids
        assert z[0] not in ids
    finally:
        await _cleanup([b, u, z])


@pytest.mark.asyncio
async def test_contracts_q_filters_by_consultant_lastname(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`q` zawęża listę do kontraktów konsultanta pasującego nazwiskiem."""
    marker = uuid.uuid4().hex[:8]
    match = await _seed_contract_named("Jan", f"Kowalski{marker}")
    other = await _seed_contract_named("Anna", f"Nowak{marker}")
    try:
        r = await app_client.get(
            "/api/contracts",
            params={"q": f"Kowalski{marker}", "page_size": 100},
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert match[0] in ids
        assert other[0] not in ids
    finally:
        await _cleanup([match, other])


@pytest.mark.asyncio
async def test_contracts_q_matches_full_name_case_insensitive(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`q` na pełnym „imię nazwisko" (inny case) trafia w gałąź concat()."""
    marker = uuid.uuid4().hex[:8]
    match = await _seed_contract_named("Grzegorz", f"Brzeczyszczykiewicz{marker}")
    other = await _seed_contract_named("Anna", f"Nowak{marker}")
    try:
        r = await app_client.get(
            "/api/contracts",
            params={
                "q": f"grzegorz brzeczyszczykiewicz{marker}",
                "page_size": 100,
            },
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert match[0] in ids
        assert other[0] not in ids
    finally:
        await _cleanup([match, other])
