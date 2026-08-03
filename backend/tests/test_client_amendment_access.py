"""Macierz autoryzacji dla aneksów umów ramowych klienta (M5 PR-01b).

P0.6a containment: ``GET .../amendments`` (list) i ``.../amendments/{id}/file``
(download) używały bare ``CurrentUser`` + tylko check istnienia client/framework,
więc read-only viewer (``user``) oraz recruiter/sourcer mogli iterować i pobierać
dokumenty prawne (aneksy) dowolnego klienta. Po zmianie chroni je scope
``resolve_client_access.can_view_legal_documents``. Admin/HoR mają nadzór
organizacyjny, a DL/TAC dostęp wyłącznie przez jawną relację z klientem.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

# Legal-team — can_view_legal_documents=True (oversight or explicit client team).
ALLOWED_ROLES = ["admin", "head_of_recruitment", "delivery_lead", "tac"]
# Delivery + viewer — no legal-doc access.
DENIED_ROLES = ["recruiter", "sourcer", "user"]


async def _headers_for(
    app_client: AsyncClient,
    role_value: str,
    *,
    client_id: int | None = None,
) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import (
        ClientTacAssignment,
        DeliveryLeadClientAssignment,
    )
    from app.models.user import User, UserRole

    email = f"amd-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Amd {role_value}",
            role=UserRole(role_value),
            is_active=True,
        )
        db.add(user)
        await db.flush()
        if client_id is not None and role_value == UserRole.delivery_lead.value:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=client_id,
                )
            )
        if client_id is not None and role_value == UserRole.tac.value:
            db.add(
                ClientTacAssignment(
                    tac_user_id=user.id,
                    client_id=client_id,
                    is_primary=False,
                    is_first_priority_for_tac=True,
                )
            )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_client_and_framework() -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_framework_contract import ClientFrameworkContract

    async with AsyncSessionLocal() as db:
        client = Client(name=f"AmdClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        fc = ClientFrameworkContract(
            client_id=client.id, name=f"MSA-{uuid.uuid4().hex[:6]}"
        )
        db.add(fc)
        await db.commit()
        await db.refresh(fc)
        return client.id, fc.id


def _list_url(client_id: int, fc_id: int) -> str:
    return f"/api/clients/{client_id}/framework-contracts/{fc_id}/amendments"


@pytest.mark.parametrize("role_value", DENIED_ROLES)
async def test_denied_roles_cannot_list_amendments(
    app_client: AsyncClient, role_value: str
):
    client_id, fc_id = await _seed_client_and_framework()
    headers = await _headers_for(app_client, role_value)
    r = await app_client.get(_list_url(client_id, fc_id), headers=headers)
    assert r.status_code == 403, f"{role_value} → {r.status_code}: {r.text}"
    # Stabilny kod błędu (client_access_denied) — nie tylko polski tekst.
    assert "client_access_denied" in r.text


@pytest.mark.parametrize("role_value", ALLOWED_ROLES)
async def test_legal_team_can_list_amendments(app_client: AsyncClient, role_value: str):
    client_id, fc_id = await _seed_client_and_framework()
    headers = await _headers_for(app_client, role_value, client_id=client_id)
    r = await app_client.get(_list_url(client_id, fc_id), headers=headers)
    assert r.status_code == 200, f"{role_value} → {r.status_code}: {r.text}"
    assert r.json() == []  # brak aneksów, ale dostęp jest


async def test_scope_runs_before_leaking_existence(app_client: AsyncClient):
    """Viewer na istniejącym kliencie dostaje 403 (scope), nie 200/404 — czyli
    guard faktycznie blokuje, nie tylko odsyła pustkę."""
    client_id, fc_id = await _seed_client_and_framework()
    headers = await _headers_for(app_client, "user")
    r = await app_client.get(_list_url(client_id, fc_id), headers=headers)
    assert r.status_code == 403


async def test_unauthenticated_rejected(app_client: AsyncClient):
    client_id, fc_id = await _seed_client_and_framework()
    r = await app_client.get(_list_url(client_id, fc_id))
    assert r.status_code in (401, 403)
