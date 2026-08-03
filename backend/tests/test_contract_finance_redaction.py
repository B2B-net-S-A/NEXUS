"""P0.12 — stawki/marże kontraktu tylko dla VIEW_FINANCE (M5 PR-01d).

Lista kontraktów, detal, lista kontraktorów i eksport ujawniały
``rate_candidate``/``rate_client``/``margin`` (+ harmonogramy) każdej roli z
``TacPlus`` — więc role bez VIEW_FINANCE widziały finanse niezgodnie z
kanoniczną polityką NEXUS. Na candidate-bearing kontraktach kwoty widzi Admin;
Finance używa bezosobowych endpointów. Pozostali, w tym Delivery Lead,
zachowują widok operacyjny (rekordy są, kwoty = None), a eksport zawierający
tożsamość kandydata jest Admin-only.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

_TODAY = date.today()


async def _headers_for(
    app_client: AsyncClient,
    role_value: str,
    *,
    assigned_contract_id: int | None = None,
) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.contract import Contract
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    email = f"fin-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Fin {role_value}",
            role=UserRole(role_value),
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if role_value == "delivery_lead" and assigned_contract_id is not None:
            client_id = await db.scalar(
                select(Contract.client_id).where(Contract.id == assigned_contract_id)
            )
            assert client_id is not None
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=client_id,
                )
            )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_candidate_client() -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Fin",
            lastname=f"C-{uuid.uuid4().hex[:6]}",
            email=f"finc-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"FinClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)
        return cand.id, client.id


async def _seed_contract() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Fin",
            lastname=f"C-{uuid.uuid4().hex[:6]}",
            email=f"finc-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"FinClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=10),
            end_date=_TODAY + timedelta(days=90),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            margin=Decimal("50.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def test_admin_sees_rates_in_detail(
    app_client: AsyncClient, app_auth_headers: dict
):
    # app_auth_headers = admin (ma VIEW_FINANCE)
    cid = await _seed_contract()
    r = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rate_candidate"] is not None
    assert body["rate_client"] is not None
    assert body["margin"] is not None


async def test_tac_gets_redacted_detail(app_client: AsyncClient):
    cid = await _seed_contract()
    headers = await _headers_for(app_client, "tac")
    r = await app_client.get(f"/api/contracts/{cid}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Rekord widoczny operacyjnie…
    assert body["status"] == "active"
    # …ale kwoty wyzerowane.
    assert body["rate_candidate"] is None
    assert body["rate_client"] is None
    assert body["margin"] is None
    assert body["candidate_rate_schedule"] == []
    assert body["currency"] is None
    assert body["rate_unit"] is None
    assert body["billing_hours_per_month"] is None


async def test_delivery_lead_gets_redacted_detail(app_client: AsyncClient):
    cid = await _seed_contract()
    headers = await _headers_for(
        app_client,
        "delivery_lead",
        assigned_contract_id=cid,
    )
    response = await app_client.get(f"/api/contracts/{cid}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rate_candidate"] is None
    assert body["rate_client"] is None
    assert body["margin"] is None
    assert body["currency"] is None
    assert body["rate_unit"] is None
    assert body["billing_hours_per_month"] is None


async def test_delivery_lead_cannot_read_unassigned_client_contract(
    app_client: AsyncClient,
):
    cid = await _seed_contract()
    headers = await _headers_for(app_client, "delivery_lead")

    response = await app_client.get(f"/api/contracts/{cid}", headers=headers)

    assert response.status_code == 403, response.text


async def test_export_requires_finance(app_client: AsyncClient, app_auth_headers: dict):
    tac = await _headers_for(app_client, "tac")
    r_tac = await app_client.get("/api/contracts/export?format=csv", headers=tac)
    assert r_tac.status_code == 403, r_tac.text
    r_admin = await app_client.get(
        "/api/contracts/export?format=csv", headers=app_auth_headers
    )
    assert r_admin.status_code == 200, r_admin.text


async def test_tac_gets_redacted_contractor_list(app_client: AsyncClient):
    cid = await _seed_contract()
    headers = await _headers_for(app_client, "tac")
    r = await app_client.get("/api/contractors?page_size=100", headers=headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    row = next((i for i in items if i["contract_id"] == cid), None)
    assert row is not None, "seeded contractor not in list"
    assert row["rate_candidate"] is None
    assert row["margin"] is None
    assert row["currency"] is None
    assert row["rate_unit"] is None


async def test_tac_cannot_create_contract_with_finance_fields(
    app_client: AsyncClient,
):
    """Redaction is not authorization: hidden rates must never be persisted."""
    cand_id, client_id = await _seed_candidate_client()
    tac = await _headers_for(app_client, "tac")
    body = {
        "candidate_id": cand_id,
        "client_id": client_id,
        "start_date": (_TODAY - timedelta(days=1)).isoformat(),
        "end_date": (_TODAY + timedelta(days=120)).isoformat(),
        "rate_candidate": 111.0,
        "rate_client": 222.0,
        "status": "active",
    }
    r = await app_client.post("/api/contracts", json=body, headers=tac)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "finance_fields_forbidden"


async def test_tac_expiring_list_redacted(app_client: AsyncClient):
    cid = await _seed_contract()  # end_date = today + 90, status active
    tac = await _headers_for(app_client, "tac")
    r = await app_client.get("/api/contracts/expiring?days=90", headers=tac)
    assert r.status_code == 200, r.text
    row = next((i for i in r.json() if i["id"] == cid), None)
    assert row is not None, "seeded contract missing from expiring list"
    assert row["rate_candidate"] is None
    assert row["rate_client"] is None
    assert row["margin"] is None


async def test_admin_expiring_list_shows_rates(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_contract()
    r = await app_client.get(
        "/api/contracts/expiring?days=90", headers=app_auth_headers
    )
    assert r.status_code == 200, r.text
    row = next((i for i in r.json() if i["id"] == cid), None)
    assert row is not None
    assert row["rate_client"] is not None


async def test_tac_cannot_patch_finance_fields(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    cid = await _seed_contract()
    tac = await _headers_for(app_client, "tac")
    r = await app_client.patch(
        f"/api/contracts/{cid}", json={"rate_client": 321.0}, headers=tac
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "finance_fields_forbidden"

    unchanged = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["rate_client"] == 150.0


async def test_delivery_lead_cannot_patch_finance_fields(
    app_client: AsyncClient,
):
    cid = await _seed_contract()
    delivery_lead = await _headers_for(
        app_client,
        "delivery_lead",
        assigned_contract_id=cid,
    )
    response = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"rate_candidate": 1, "candidate_rate_schedule": []},
        headers=delivery_lead,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "finance_fields_forbidden"
