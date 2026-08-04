"""Finance-data-leak containment for activity feeds + contract rate-history.

The rate-change audit trail (``Activity`` rows carrying rate amounts) must not
leak rate values to roles without finance access. The candidate timeline already
hides these (``_HIDDEN_TIMELINE_ACTIONS`` + ``has_financial_access`` redaction);
these sibling feeds did not. This locks the same behaviour on:

- ``GET /api/activities/feed``            (P1) — raw ``Activity.details``.
- ``GET /api/dashboard/recent-activity``  (P1) — raw ``Activity.details``.
- ``GET /api/contracts/{id}/activities``  (P2) — raw ``Activity.details``.
- ``GET /api/contracts/{id}/rate-history``(P1) — raw ``rate`` amounts.

Admin still sees the values; non-finance operational roles (including Delivery
Lead, recruiter and TAC) get the rate-change rows omitted and any
residual finance keys stripped, and rate-history amounts redacted to ``None``.

Pattern mirrors ``test_rbac.py`` / ``test_candidate_module_access.py``: in-process
ASGI client, users seeded per role, domain rows seeded directly via
``AsyncSessionLocal``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.rate_history import ContractType as RateContractType, RateHistory
from app.models.user import User, UserRole
from app.services.candidate_audit import CLIENT_RATE_CHANGED

# Rate amounts seeded into the audit trail — used verbatim in assertions.
OLD_CLIENT_RATE = 100.0
NEW_CLIENT_RATE = 150.0
CONTRACT_RATE_CANDIDATE = 120.5
CONTRACT_RATE_CLIENT = 180.0
RATE_HISTORY_AMOUNT = Decimal("175.500")


# ── Fixtures ─────────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"leak-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Leak"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Leak Test {role.value}",
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def leak_client() -> AsyncIterator[AsyncClient]:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def seeded() -> dict:
    """Seed a candidate rate-change audit row, a contract with a rate-carrying
    ``updated`` audit row, and a rate-history row. Returns the ids for lookup."""
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Leak Client {uuid.uuid4().hex[:6]}")
        candidate = Candidate(name="Leak", lastname=f"Cand-{uuid.uuid4().hex[:6]}")
        db.add_all([client, candidate])
        await db.flush()

        contract = Contract(candidate_id=candidate.id, client_id=client.id)
        db.add(contract)
        await db.flush()

        # Candidate-scoped rate-change audit (findings 1 & 2). Payload mirrors
        # candidates.set_recruitment_client_rate.
        rate_audit = Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action=CLIENT_RATE_CHANGED,
            details={
                "job_id": 0,
                "stage_id": 0,
                "old_client_rate": OLD_CLIENT_RATE,
                "old_client_rate_unit": "monthly",
                "old_client_rate_currency": "PLN",
                "new_client_rate": NEW_CLIENT_RATE,
                "new_client_rate_unit": "monthly",
                "new_client_rate_currency": "PLN",
            },
            external_source="audit",
        )
        # Contract-scoped rate-carrying update (finding 3, also global feeds).
        contract_audit = Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="updated",
            details={
                "rate_candidate": CONTRACT_RATE_CANDIDATE,
                "rate_client": CONTRACT_RATE_CLIENT,
                "margin": 59.5,
                "status": "active",
            },
        )
        rate_row = RateHistory(
            candidate_id=candidate.id,
            client_id=client.id,
            rate=RATE_HISTORY_AMOUNT,
            currency="PLN",
            contract_type=RateContractType.b2b,
            start_date=date(2026, 1, 1),
        )
        db.add_all([rate_audit, contract_audit, rate_row])
        await db.commit()
        return {
            "candidate_id": candidate.id,
            "contract_id": contract.id,
            "rate_activity_id": rate_audit.id,
            "contract_activity_id": contract_audit.id,
            "rate_history_id": rate_row.id,
        }


def _find(items: list[dict], _id: int) -> dict | None:
    return next((i for i in items if i.get("id") == _id), None)


# ── Findings 1 & 2: global activity feeds ────────────────────────────────────


async def test_activities_feed_hides_rate_change_from_non_finance(
    leak_client: AsyncClient, seeded: dict
):
    """recruiter: rows redacted; admin: finance values retained."""
    rec_headers = await _login(leak_client, *await _seed_user(UserRole.recruiter))
    fin_headers = await _login(leak_client, *await _seed_user(UserRole.admin))

    rec = await leak_client.get("/api/activities/feed?limit=100", headers=rec_headers)
    assert rec.status_code == 200, rec.text
    rec_items = rec.json()
    # Rate-change audit row must be absent for the non-finance reader.
    assert _find(rec_items, seeded["rate_activity_id"]) is None
    # Contract "updated" row is kept, but its rate keys are stripped.
    rec_contract = _find(rec_items, seeded["contract_activity_id"])
    assert rec_contract is not None
    assert "rate_candidate" not in rec_contract["details"]
    assert "rate_client" not in rec_contract["details"]
    assert "margin" not in rec_contract["details"]
    assert rec_contract["details"].get("status") == "active"

    fin = await leak_client.get("/api/activities/feed?limit=100", headers=fin_headers)
    assert fin.status_code == 200, fin.text
    fin_items = fin.json()
    fin_rate = _find(fin_items, seeded["rate_activity_id"])
    assert fin_rate is not None
    assert fin_rate["details"]["new_client_rate"] == NEW_CLIENT_RATE
    assert fin_rate["details"]["old_client_rate"] == OLD_CLIENT_RATE
    fin_contract = _find(fin_items, seeded["contract_activity_id"])
    assert fin_contract is not None
    assert fin_contract["details"]["rate_candidate"] == CONTRACT_RATE_CANDIDATE


async def test_recent_activity_hides_rate_change_from_non_finance(
    leak_client: AsyncClient, seeded: dict
):
    rec_headers = await _login(leak_client, *await _seed_user(UserRole.recruiter))
    fin_headers = await _login(leak_client, *await _seed_user(UserRole.admin))

    rec = await leak_client.get(
        "/api/dashboard/recent-activity?limit=100", headers=rec_headers
    )
    assert rec.status_code == 200, rec.text
    rec_items = rec.json()
    assert _find(rec_items, seeded["rate_activity_id"]) is None
    rec_contract = _find(rec_items, seeded["contract_activity_id"])
    assert rec_contract is not None
    assert "rate_candidate" not in rec_contract["details"]
    assert "margin" not in rec_contract["details"]

    fin = await leak_client.get(
        "/api/dashboard/recent-activity?limit=100", headers=fin_headers
    )
    assert fin.status_code == 200, fin.text
    fin_rate = _find(fin.json(), seeded["rate_activity_id"])
    assert fin_rate is not None
    assert fin_rate["details"]["new_client_rate"] == NEW_CLIENT_RATE


# ── Finding 3: contract activities feed ──────────────────────────────────────


async def test_contract_activities_strip_rate_for_non_finance(
    leak_client: AsyncClient, seeded: dict
):
    """TAC has rate keys stripped; admin retains them."""
    tac_headers = await _login(leak_client, *await _seed_user(UserRole.tac))
    fin_headers = await _login(leak_client, *await _seed_user(UserRole.admin))
    cid = seeded["contract_id"]

    tac = await leak_client.get(f"/api/contracts/{cid}/activities", headers=tac_headers)
    assert tac.status_code == 200, tac.text
    tac_entry = _find(tac.json(), seeded["contract_activity_id"])
    assert tac_entry is not None
    assert "rate_candidate" not in tac_entry["details"]
    assert "rate_client" not in tac_entry["details"]
    assert "margin" not in tac_entry["details"]
    assert tac_entry["details"].get("status") == "active"

    fin = await leak_client.get(f"/api/contracts/{cid}/activities", headers=fin_headers)
    assert fin.status_code == 200, fin.text
    fin_entry = _find(fin.json(), seeded["contract_activity_id"])
    assert fin_entry is not None
    assert fin_entry["details"]["rate_candidate"] == CONTRACT_RATE_CANDIDATE


# ── Finding 4: contract rate-history ─────────────────────────────────────────


async def test_contract_rate_history_redacts_amount_for_non_finance(
    leak_client: AsyncClient, seeded: dict
):
    """TAC gets a redacted rate; admin gets the raw amount."""
    tac_headers = await _login(leak_client, *await _seed_user(UserRole.tac))
    fin_headers = await _login(leak_client, *await _seed_user(UserRole.admin))
    cid = seeded["contract_id"]

    tac = await leak_client.get(
        f"/api/contracts/{cid}/rate-history", headers=tac_headers
    )
    assert tac.status_code == 200, tac.text
    tac_entry = _find(tac.json(), seeded["rate_history_id"])
    assert tac_entry is not None
    assert tac_entry["rate"] is None
    assert tac_entry["currency"] is None

    fin = await leak_client.get(
        f"/api/contracts/{cid}/rate-history", headers=fin_headers
    )
    assert fin.status_code == 200, fin.text
    fin_entry = _find(fin.json(), seeded["rate_history_id"])
    assert fin_entry is not None
    assert fin_entry["rate"] == float(RATE_HISTORY_AMOUNT)
