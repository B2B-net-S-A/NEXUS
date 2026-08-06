"""Macierz autoryzacji dla legal-document surfaces kontraktów (M5 PR-01).

P0.11 containment: B2B generator + contract-template render używały bare
``CurrentUser``, więc read-only viewer (`user`) oraz recruiter/sourcer mogli
generować/mutować/pobierać umowy prawne. Po zmianie chroni je ``ContractLegalAccess``
(admin / head_of_recruitment / delivery_lead / tac — grono legal-team, spójne z
``client_access.can_view_legal_documents``).

Generator umów B2B jest jednak pełnoprawnym narzędziem TAC-a: TAC (obok
Admin/HoR) otwiera i obsługuje generator **rolą, bez wymogu przypisania do
klienta** (``B2BGeneratorAccess`` + odscopowane wrappery w
``b2b_contract_generator``). Delivery Lead nadal wymaga co najmniej jednego
jawnego przypisania klienta dla narzędzi globalnych i dokładnego przypisania
dla tras encji.

Ten test dowodzi: denied roles → 403, legal-team → NIE 403 (auth przechodzi),
na reprezentatywnych endpointach każdego typu (GET bez body, GET z listą,
POST mutujący). Wszystkie 13 B2B + 3 template endpointy dzielą tę samą
dependency, więc reprezentatywna próbka pokrywa kontrakt.
"""

from __future__ import annotations

import ast
import inspect
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
DENIED_ROLES = ["recruiter", "sourcer", "finance", "user"]


@pytest.mark.parametrize("handler_name", ["generate", "get_detail", "download_docx"])
def test_b2b_contract_loader_always_receives_current_actor(handler_name: str) -> None:
    """Every shared contract load must retain its relationship-aware RBAC check."""

    from app.api import b2b_contract_generator

    handler = getattr(b2b_contract_generator, handler_name)
    tree = ast.parse(inspect.getsource(handler))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_load_contract_with_relations"
    ]
    assert calls, f"{handler_name} must load its contract through the scoped helper"
    for call in calls:
        assert len(call.args) >= 3
        actor = call.args[2]
        assert isinstance(actor, ast.Name) and actor.id == "current_user"


async def _headers_for(
    app_client: AsyncClient,
    role_value: str,
    *,
    assign_client: bool = True,
) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.client import Client
    from app.models.team_structure import (
        ClientTacAssignment,
        DeliveryLeadClientAssignment,
    )
    from app.models.user import User, UserRole

    email = f"legal-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        role = UserRole(role_value)
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Legal {role_value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if assign_client and role in (UserRole.delivery_lead, UserRole.tac):
            client = Client(name=f"Legal scope {uuid.uuid4().hex[:8]}")
            db.add(client)
            await db.flush()
            if role is UserRole.delivery_lead:
                db.add(
                    DeliveryLeadClientAssignment(
                        delivery_lead_user_id=user.id,
                        client_id=client.id,
                    )
                )
            else:
                db.add(
                    ClientTacAssignment(
                        tac_user_id=user.id,
                        client_id=client.id,
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


@pytest.mark.parametrize("role_value", ["delivery_lead"])
async def test_unassigned_client_team_role_fails_closed(
    app_client: AsyncClient,
    role_value: str,
):
    # Delivery Lead keeps the fail-closed contract: an empty client graph is a
    # hard deny on the generator surfaces. (TAC intentionally does NOT — see
    # ``test_unassigned_tac_has_full_generator_access``.)
    headers = await _headers_for(
        app_client,
        role_value,
        assign_client=False,
    )
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        response = await app_client.get(url, headers=headers)
        assert response.status_code == 403, (
            f"unassigned {role_value} GET {url} → {response.status_code}"
        )


async def test_unassigned_tac_has_full_generator_access(app_client: AsyncClient):
    """A TAC with zero ClientTacAssignment rows still gets the full generator.

    Regression guard for the reported bug: a freshly-added TAC saw the "Brak
    uprawnień" banner because the shared legal gate required a non-empty client
    graph. The generator is a full-access TAC tool, so role alone must admit it.
    """

    headers = await _headers_for(app_client, "tac", assign_client=False)

    # Global GET surfaces resolve, they do not 403 into an empty banner.
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url, headers=headers)
        assert r.status_code == 200, (
            f"unassigned tac GET {url} → {r.status_code}: {r.text}"
        )

    # Drafting is reachable: auth passes, business logic 404s on the missing
    # role_id — never a client-scope 403.
    r = await app_client.post(
        GENERATE_URL,
        json={"role_id": 999999, "start_date": "2026-01-01"},
        headers=headers,
    )
    assert r.status_code == 404, (
        f"unassigned tac POST generate → {r.status_code}: {r.text}"
    )

    # DOCX download is the highest-PII generator surface and (unlike
    # delete/update) has no author-only secondary check — so full-access TAC
    # reaches it too. Missing id ⇒ 404 (gate + scope passed), never 403. This
    # guards the intentional expanded exposure against a future re-tightening.
    r = await app_client.get(f"{GENERATED_URL}/999999/docx", headers=headers)
    assert r.status_code == 404, (
        f"unassigned tac GET generated/docx → {r.status_code}: {r.text}"
    )


async def test_unauthenticated_is_rejected(app_client: AsyncClient):
    # No Authorization header → FastAPI's HTTPBearer rejects before the role
    # check runs. NEXUS returns 403 there (Bearer auto_error), so accept both
    # "not authenticated" codes — the point is the anon caller gets no data.
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url)
        assert r.status_code in (401, 403), f"anon GET {url} → {r.status_code}"
