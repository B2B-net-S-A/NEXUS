"""P0.12 — faktury tylko dla VIEW_FINANCE (admin + delivery_lead) (M5 PR-01c).

Faktury to w całości dane finansowe (kwoty, DSO). Dotąd wszystkie endpointy
``/api/invoices`` używały ``TacPlus`` (admin/DL/tac), więc TAC — który wg
kanonicznej polityki NEXUS (``AnalyticsCapability.VIEW_FINANCE``) finansów nie
ma — widział i mutował kwoty faktur. Po zmianie chroni je
``require_capability(VIEW_FINANCE)`` (admin + delivery_lead).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

INVOICES_URL = "/api/invoices"

# VIEW_FINANCE = admin + delivery_lead (app/analytics/capabilities.py).
ALLOWED_ROLES = ["admin", "delivery_lead"]
# tac/HoR mają role operacyjne ale NIE VIEW_FINANCE; recruiter/sourcer/user tym
# bardziej. Wszyscy → 403 na fakturach.
DENIED_ROLES = ["tac", "head_of_recruitment", "recruiter", "sourcer", "user"]


async def _headers_for(app_client: AsyncClient, role_value: str) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"inv-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Inv {role_value}",
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


@pytest.mark.parametrize("role_value", DENIED_ROLES)
async def test_non_finance_roles_get_403(app_client: AsyncClient, role_value: str):
    headers = await _headers_for(app_client, role_value)
    r = await app_client.get(INVOICES_URL, headers=headers)
    assert r.status_code == 403, f"{role_value} → {r.status_code}: {r.text}"


@pytest.mark.parametrize("role_value", ALLOWED_ROLES)
async def test_finance_roles_pass(app_client: AsyncClient, role_value: str):
    headers = await _headers_for(app_client, role_value)
    r = await app_client.get(INVOICES_URL, headers=headers)
    assert r.status_code == 200, f"{role_value} → {r.status_code}: {r.text}"


async def test_non_finance_cannot_create_or_mutate(app_client: AsyncClient):
    """TAC nie może już tworzyć faktur (mutacja kwot poza polityką)."""
    headers = await _headers_for(app_client, "tac")
    r = await app_client.post(
        INVOICES_URL,
        json={
            "contract_id": 1,
            "direction": "to_client",
            "invoice_number": "T-1",
            "issue_date": "2026-01-01",
            "amount": 1000,
        },
        headers=headers,
    )
    assert r.status_code == 403


async def test_unauthenticated_rejected(app_client: AsyncClient):
    r = await app_client.get(INVOICES_URL)
    assert r.status_code in (401, 403)
