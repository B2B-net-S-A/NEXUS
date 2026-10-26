"""„Kończą u klientów” (25.10.2026) — ``GET /api/contracts/ending-consultants``.

Delivery Lead widzi w „Moich ludziach” konsultantów u swoich klientów, którym
w ``days`` dni kończy się umowa, bez potwierdzonych przedłużeń i bez kwot.
Baza testowa jest wspólna dla przebiegu — każdy test zakłada własne dane
(osoby zmyślone) i je sprząta.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    ProlongationStatus,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _seed_contract(
    *,
    days_to_end: int,
    status: ContractStatus = ContractStatus.active,
    prolongation: ProlongationStatus = ProlongationStatus.unknown,
    client_id: int | None = None,
) -> tuple[int, int, int]:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Jan", lastname=f"Kończący-{_hex()}", email=f"end-{_hex()}@example.com"
        )
        db.add(cand)
        if client_id is None:
            client = Client(name=f"Klient Testowy {_hex()}")
            db.add(client)
            await db.flush()
            client_id = client.id
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client_id,
            status=status,
            contract_type=ContractType.b2b,
            start_date=business_today() - timedelta(days=200),
            end_date=business_today() + timedelta(days=days_to_end),
            prolongation_status=prolongation,
            rate_client=10000,
            rate_candidate=8000,
            margin=2000,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return contract.id, cand.id, client_id


async def _cleanup(rows: list[tuple[int, int, int]]) -> None:
    async with AsyncSessionLocal() as db:
        for contract_id, _, _ in rows:
            await db.execute(delete(Contract).where(Contract.id == contract_id))
        for _, cand_id, _ in rows:
            await db.execute(delete(Candidate).where(Candidate.id == cand_id))
        await db.commit()


async def _headers_for(
    app_client: AsyncClient, role: UserRole, *, client_ids: tuple[int, ...] = ()
) -> dict[str, str]:
    email = f"ending-{role.value}-{_hex()}@example.com"
    password = f"T3st_{_hex()}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Kończą {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        for client_id in client_ids:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id, client_id=client_id
                )
            )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_lists_live_contracts_in_window_without_confirmed_renewal(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    soon = await _seed_contract(days_to_end=10)
    ending = await _seed_contract(days_to_end=40, status=ContractStatus.ending)
    renewed = await _seed_contract(days_to_end=10, prolongation=ProlongationStatus.yes)
    far = await _seed_contract(days_to_end=120)
    ended = await _seed_contract(days_to_end=5, status=ContractStatus.ended)
    try:
        resp = await app_client.get(
            "/api/contracts/ending-consultants", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        rows = {r["contract_id"]: r for r in resp.json()}
        assert soon[0] in rows and ending[0] in rows
        assert renewed[0] not in rows
        assert far[0] not in rows
        assert ended[0] not in rows
        row = rows[soon[0]]
        assert row["candidate_id"] == soon[1]
        assert row["candidate_name"].startswith("Jan Kończący-")
        assert row["client_name"].startswith("Klient Testowy")
        assert row["prolongation_status"] == "unknown"
        # Bez kwot — trasa nie niesie stawek ani marży.
        assert "rate_client" not in row and "margin" not in row

        narrow = await app_client.get(
            "/api/contracts/ending-consultants",
            headers=app_auth_headers,
            params={"days": 20},
        )
        assert {r["contract_id"] for r in narrow.json()} >= {soon[0]}
        assert ending[0] not in {r["contract_id"] for r in narrow.json()}
    finally:
        await _cleanup([soon, ending, renewed, far, ended])


async def test_delivery_lead_sees_only_own_clients(app_client: AsyncClient) -> None:
    mine = await _seed_contract(days_to_end=15)
    other = await _seed_contract(days_to_end=15)
    try:
        dl = await _headers_for(
            app_client, UserRole.delivery_lead, client_ids=(mine[2],)
        )
        resp = await app_client.get("/api/contracts/ending-consultants", headers=dl)
        assert resp.status_code == 200, resp.text
        ids = {r["contract_id"] for r in resp.json()}
        assert mine[0] in ids
        assert other[0] not in ids
    finally:
        await _cleanup([mine, other])


async def test_recruiter_without_delivery_view_is_refused(
    app_client: AsyncClient,
) -> None:
    recruiter = await _headers_for(app_client, UserRole.recruiter)
    resp = await app_client.get("/api/contracts/ending-consultants", headers=recruiter)
    assert resp.status_code == 403
