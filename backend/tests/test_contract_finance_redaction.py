"""P0.12 — stawki/marże kontraktu tylko dla VIEW_FINANCE (M5 PR-01d).

Lista kontraktów, detal, lista kontraktorów i eksport ujawniały
``rate_candidate``/``rate_client``/``margin`` (+ harmonogramy) każdej roli z
``TacPlus`` — więc TAC (bez VIEW_FINANCE) widział finanse niezgodnie z
kanoniczną polityką NEXUS. Po zmianie kwoty widzą tylko admin + delivery_lead;
pozostali zachowują widok operacyjny (rekordy są, kwoty = None), a eksport
(kolumny kwotowe) jest tylko dla finansów.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

_TODAY = date.today()


async def _headers_for(app_client: AsyncClient, role_value: str) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"fin-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Fin {role_value}",
                role=UserRole(role_value),
                is_active=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


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


async def test_finance_sees_rates_in_detail(
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
