"""Authorization matrix for legal-document and B2B generator surfaces.

P0.11 containment (historia): B2B generator + contract-template render
używały bare ``CurrentUser``, więc read-only viewer (`user`) oraz
recruiter/sourcer mogli generować/mutować/pobierać umowy prawne. Fix z tamtego
audytu wprowadził wspólną ``ContractLegalAccess`` (admin / head_of_recruitment
/ delivery_lead / tac — grono legal-team, spójne z
``client_access.can_view_legal_documents``) dla OBU powierzchni naraz.

Generator B2B ma własną, konfigurowalną bramkę akcji wewnątrz Sourcingu.
Domyślny poziom zachowuje dotychczasowe operacje wszystkich ról poza TCM i
legacy viewerem, którzy zaczynają od bezpiecznego podglądu rejestru.

Delivery Lead zachowuje istniejący, granularny zakres klientów również w tym
narzędziu. Poziom ``view`` nie może generować, renderować, pobierać ani
modyfikować dokumentów zawierających stawkę.
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

# Każda rola ma domyślnie co najmniej podgląd. Administrator może to jednak
# odebrać lub podnieść niezależnie od dostępu do całej sekcji Sourcing.
ALL_ROLES = [
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "talent_community_manager",
    "tac",
    "finance",
    "recruiter",
    "sourcer",
    "user",
]
UNSCOPED_ROLES = [role for role in ALL_ROLES if role != "delivery_lead"]


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


@pytest.mark.parametrize("role_value", ALL_ROLES)
async def test_every_role_passes_generator_auth(
    app_client: AsyncClient, role_value: str
):
    """Every role can browse in its valid scope; TCM stops at generation."""
    headers = await _headers_for(app_client, role_value)
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url, headers=headers)
        assert r.status_code == 200, (
            f"{role_value} GET {url} → {r.status_code}: {r.text}"
        )

    # Missing role reaches business validation for document operators. Plain
    # TCM is deliberately stopped before any rate-bearing operation.
    r = await app_client.post(
        GENERATE_URL,
        json={"role_id": 999999, "start_date": "2026-01-01"},
        headers=headers,
    )
    if role_value == "talent_community_manager":
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == {
            "code": "action_access_denied",
            "action": "b2b_contract_generator",
            "required": "generate",
            "granted": "view",
        }
    elif role_value == "user":
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == {
            "code": "section_access_denied",
            "section": "sourcing",
            "required": "write",
            "granted": "read",
        }
    else:
        assert r.status_code == 404, (
            f"{role_value} POST generate → {r.status_code}: {r.text}"
        )


async def test_unassigned_delivery_lead_fails_closed(app_client: AsyncClient):
    headers = await _headers_for(
        app_client,
        "delivery_lead",
        assign_client=False,
    )
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        response = await app_client.get(url, headers=headers)
        assert response.status_code == 403, (
            f"unassigned delivery_lead GET {url} → "
            f"{response.status_code}: {response.text}"
        )


@pytest.mark.parametrize("role_value", UNSCOPED_ROLES)
async def test_unscoped_roles_can_browse_generator(
    app_client: AsyncClient, role_value: str
):
    """Non-DL roles admitted to Sourcing do not need client assignments.

    Originally a TAC-only regression guard: a freshly-added TAC with zero
    ``ClientTacAssignment`` rows saw the "Brak uprawnień" banner because the
    shared legal gate required a non-empty client graph — the generator is a
    organization-wide Sourcing tool, so role alone must admit its catalog.
    Generalized to every role
    opened on 20.08 for the same structural reason: none of them have any
    client-assignment row to be scoped by, so the global catalog and register
    remain available even with no assignment.
    """

    headers = await _headers_for(app_client, role_value, assign_client=False)

    # Global GET surfaces resolve, they do not 403 into an empty banner.
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url, headers=headers)
        assert r.status_code == 200, (
            f"unassigned {role_value} GET {url} → {r.status_code}: {r.text}"
        )

    # Drafting is reachable for document operators. TCM is a deliberate 403 at
    # the finance boundary; the plain viewer is read-only in Sourcing.
    r = await app_client.post(
        GENERATE_URL,
        json={"role_id": 999999, "start_date": "2026-01-01"},
        headers=headers,
    )
    post_expected = 403 if role_value in {"talent_community_manager", "user"} else 404
    assert r.status_code == post_expected, (
        f"unassigned {role_value} POST generate → {r.status_code}: {r.text}"
    )
    if role_value == "user":
        assert r.json()["detail"] == {
            "code": "section_access_denied",
            "section": "sourcing",
            "required": "write",
            "granted": "read",
        }
    elif role_value == "talent_community_manager":
        assert r.json()["detail"]["code"] == "action_access_denied"

    # Opaque DOCX can contain rates. Missing id therefore produces the same
    # split: view-only roles are rejected before lookup, document operators
    # reach the 404.
    r = await app_client.get(f"{GENERATED_URL}/999999/docx", headers=headers)
    docx_expected = (
        403 if role_value in {"talent_community_manager", "user"} else 404
    )
    assert r.status_code == docx_expected, (
        f"unassigned {role_value} GET generated/docx → {r.status_code}: {r.text}"
    )

    # Generated-contract mutations are read-only for TCM.
    if role_value == "talent_community_manager":
        patch = await app_client.patch(
            f"{GENERATED_URL}/999999",
            headers=headers,
            json={"client_name": "Blocked"},
        )
        delete = await app_client.delete(
            f"{GENERATED_URL}/999999",
            headers=headers,
        )
        assert patch.status_code == 403, patch.text
        assert delete.status_code == 403, delete.text
        assert patch.json()["detail"]["required"] == "manage"
        assert delete.json()["detail"]["required"] == "manage"


async def test_unauthenticated_is_rejected(app_client: AsyncClient):
    # No Authorization header → FastAPI's HTTPBearer rejects before the role
    # check runs. NEXUS returns 403 there (Bearer auto_error), so accept both
    # "not authenticated" codes — the point is the anon caller gets no data.
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url)
        assert r.status_code in (401, 403), f"anon GET {url} → {r.status_code}"
