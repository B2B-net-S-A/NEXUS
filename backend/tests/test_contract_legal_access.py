"""Macierz autoryzacji dla legal-document surfaces kontraktów (M5 PR-01).

P0.11 containment: B2B generator + contract-template render używały bare
``CurrentUser``, więc read-only viewer (`user`) oraz recruiter/sourcer mogli
generować/mutować/pobierać umowy prawne. Po zmianie chroni je ``ContractLegalAccess``
(admin / head_of_recruitment / delivery_lead / tac — grono legal-team, spójne z
``client_access.can_view_legal_documents``).

Ten test dowodzi: denied roles → 403, legal-team → NIE 403 (auth przechodzi),
na reprezentatywnych endpointach każdego typu (GET bez body, GET z listą,
POST mutujący). Wszystkie 13 B2B + 3 template endpointy dzielą tę samą
dependency, więc reprezentatywna próbka pokrywa kontrakt.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

ROLES_URL = "/api/b2b-generator/roles"
NEXT_NUMBER_URL = "/api/b2b-generator/next-number"
GENERATED_URL = "/api/b2b-generator/generated"
GENERATE_URL = "/api/b2b-generator/generate"

# Legal-team — auth must pass (may still 404/422 from business logic, never 403).
ALLOWED_ROLES = ["admin", "head_of_recruitment", "delivery_lead", "tac"]
# Delivery + viewer — must be 403 on every legal-document surface.
DENIED_ROLES = ["recruiter", "sourcer", "user"]


async def _headers_for(app_client: AsyncClient, role_value: str) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"legal-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Legal {role_value}",
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
async def test_denied_roles_get_403_on_legal_surfaces(
    app_client: AsyncClient, role_value: str
):
    headers = await _headers_for(app_client, role_value)
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url, headers=headers)
        assert r.status_code == 403, f"{role_value} GET {url} → {r.status_code}"

    # P0.11 core: mutujący generate z poprawnym schematycznie payloadem.
    r = await app_client.post(
        GENERATE_URL,
        json={"role_id": 999999, "start_date": "2026-01-01"},
        headers=headers,
    )
    assert r.status_code == 403, f"{role_value} POST generate → {r.status_code}"


@pytest.mark.parametrize("role_value", ALLOWED_ROLES)
async def test_legal_team_roles_pass_auth(app_client: AsyncClient, role_value: str):
    headers = await _headers_for(app_client, role_value)
    # Pure-auth GETs: legal team gets 200.
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url, headers=headers)
        assert r.status_code == 200, (
            f"{role_value} GET {url} → {r.status_code}: {r.text}"
        )

    # generate: auth passes → business logic 404 (role_id nie istnieje), never 403.
    r = await app_client.post(
        GENERATE_URL,
        json={"role_id": 999999, "start_date": "2026-01-01"},
        headers=headers,
    )
    assert r.status_code != 403, f"{role_value} POST generate wrongly 403"
    assert r.status_code == 404, (
        f"{role_value} POST generate → {r.status_code}: {r.text}"
    )


async def test_unauthenticated_is_401(app_client: AsyncClient):
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url)
        assert r.status_code == 401, f"anon GET {url} → {r.status_code}"
