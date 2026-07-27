"""Smoke tests for Kontrakty expansion — equipment, terminate, benchmark, notes timeline.

Each test seeds and owns its own contract. The previous `_any_contract` helper
grabbed an arbitrary row off `GET /api/contracts?page_size=1&status=active` —
whatever happened to sort first in the shared table — and then MUTATED it. That
made the file order-dependent in three separate ways:

* the row it picked changed depending on what sibling tests had left behind, so
  `test_terminate_...` asserted `status == "ended"` against a contract whose
  `end_date` sometimes made the termination future-dated (which by design keeps
  the contract active — see P0.7 in `terminate_contract`);
* terminating a borrowed row corrupted it for every later reader;
* `if not contract: return` turned the whole file into a silent no-op on an
  empty database, so it protected nothing precisely when it looked green.

Owning the data fixes all three: assertions are local to rows this test created,
and the dates are known rather than inherited.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import AsyncIterator

import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def owned_contract() -> AsyncIterator[dict]:
    """Seed an active contract (plus its required candidate/client) and drop it.

    Returns the ids and the known dates so tests can assert against values they
    chose instead of whatever a sibling left in the table. Every child row
    (equipment, amendments, ...) is ON DELETE CASCADE, so removing the contract
    is enough.
    """
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType

    token = uuid.uuid4().hex[:8]
    start = date.today() - timedelta(days=30)
    end = date.today() + timedelta(days=60)

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="ContractExp",
            lastname=f"Owned-{token}",
            email=f"cexp-{token}@example.com",
        )
        client = Client(name=f"ContractExp {token}")
        db.add_all([cand, client])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            contract_type=ContractType("b2b"),
            start_date=start,
            end_date=end,
            rate_client=10000,
            rate_candidate=8000,
            margin=2000,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        ids = {
            "id": contract.id,
            "candidate_id": cand.id,
            "client_id": client.id,
            "start_date": start,
            "end_date": end,
        }

    try:
        yield ids
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Contract).where(Contract.id == ids["id"]))
            await db.execute(delete(Candidate).where(Candidate.id == ids["candidate_id"]))
            await db.execute(delete(Client).where(Client.id == ids["client_id"]))
            await db.commit()


# ── Equipment ───────────────────────────────────────────────────────────────


async def test_equipment_crud_roundtrip(
    app_client: AsyncClient, app_auth_headers: dict, owned_contract: dict
):
    cid = owned_contract["id"]

    list_resp = await app_client.get(
        f"/api/contracts/{cid}/equipment", headers=app_auth_headers
    )
    assert list_resp.status_code == 200
    # Our own contract is brand new, so its equipment list starts empty.
    assert list_resp.json() == []

    created = await app_client.post(
        f"/api/contracts/{cid}/equipment",
        json={
            "item_type": "laptop",
            "owner": "ours",
            "brand_model": "ThinkPad X1 Carbon",
            "serial_number": f"PYTEST-X1-{uuid.uuid4().hex[:8]}",
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["item_type"] == "laptop"
    assert body["owner"] == "ours"
    assert body["return_status"] == "pending"
    eq_id = body["id"]

    patched = await app_client.patch(
        f"/api/contracts/{cid}/equipment/{eq_id}",
        json={"returned_date": date.today().isoformat()},
        headers=app_auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["return_status"] == "returned"

    deleted = await app_client.delete(
        f"/api/contracts/{cid}/equipment/{eq_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204

    after = await app_client.get(
        f"/api/contracts/{cid}/equipment", headers=app_auth_headers
    )
    assert after.json() == []


# ── Terminate ───────────────────────────────────────────────────────────────


async def test_terminate_sets_reason_and_amendment(
    app_client: AsyncClient, app_auth_headers: dict, owned_contract: dict
):
    """Terminating effective TODAY ends the contract and records the reason.

    The date is chosen, not inherited, so the outcome is deterministic: a
    same-day termination is what actually flips `status` to `ended`.
    """
    cid = owned_contract["id"]
    effective = date.today()

    terminated = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "termination_lessons": "pytest smoke",
            "terminated_at": effective.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert terminated.status_code == 200, terminated.text
    body = terminated.json()
    assert body["status"] == "ended"
    assert body["termination_reason"] == "project_ended"
    assert body["termination_lessons"] == "pytest smoke"
    # end_date never lags the termination date.
    assert body["end_date"] == effective.isoformat()


async def test_future_dated_termination_keeps_contract_active(
    app_client: AsyncClient, app_auth_headers: dict, owned_contract: dict
):
    """P0.7: a termination dated in the future must NOT end the contract today.

    The old borrowed-row test straddled this branch by accident — whether it saw
    `ended` or `active` depended on the inherited `end_date`. Pinning it makes
    the rule explicit instead of flaky.
    """
    cid = owned_contract["id"]
    effective = date.today() + timedelta(days=5)
    assert effective < owned_contract["end_date"]  # genuinely cuts it short

    terminated = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": effective.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert terminated.status_code == 200, terminated.text
    body = terminated.json()
    assert body["status"] in ("active", "ending"), body
    assert body["end_date"] == effective.isoformat()


# ── Benchmark ───────────────────────────────────────────────────────────────


async def test_benchmark_endpoint_shape(
    app_client: AsyncClient, app_auth_headers: dict, owned_contract: dict
):
    cid = owned_contract["id"]

    bench = await app_client.get(
        f"/api/contracts/{cid}/benchmark", headers=app_auth_headers
    )
    assert bench.status_code == 200, bench.text
    payload = bench.json()
    # The fields exist even if internal_sample_size is 0 or role is None.
    for key in (
        "contract_rate_monthly",
        "internal_avg_monthly",
        "internal_median_monthly",
        "internal_sample_size",
        "market_min",
        "market_median",
        "market_max",
        "market_source",
        "role_used",
        "currency",
    ):
        assert key in payload


# ── Notes+Calls timeline ────────────────────────────────────────────────────


async def test_contract_notes_timeline_shape(
    app_client: AsyncClient, app_auth_headers: dict, owned_contract: dict
):
    cid = owned_contract["id"]
    res = await app_client.get(
        f"/api/contracts/{cid}/notes", headers=app_auth_headers
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    for item in res.json():
        assert item["kind"] in ("note", "call")
        assert "at" in item
