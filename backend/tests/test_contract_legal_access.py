"""Macierz autoryzacji dla legal-document surfaces kontraktów (M5 PR-01) +
otwarcie generatora B2B na każdą rolę (decyzja produktowa, 20.08).

P0.11 containment (historia): B2B generator + contract-template render
używały bare ``CurrentUser``, więc read-only viewer (`user`) oraz
recruiter/sourcer mogli generować/mutować/pobierać umowy prawne. Fix z tamtego
audytu wprowadził wspólną ``ContractLegalAccess`` (admin / head_of_recruitment
/ delivery_lead / tac — grono legal-team, spójne z
``client_access.can_view_legal_documents``) dla OBU powierzchni naraz.

20.08: generator B2B dostał WŁASNĄ, szerszą bramkę — ``contract_templates``
(rendering dla dowolnego typu kontraktu, NIE tylko B2B) nadal stoi za
``ContractLegalAccess`` i ten plik go nie testuje. Sidebar nigdy nie miał tu
`roles` ("Generator Umów B2B — dostępny dla wszystkich ról"), więc restrykcja
backendu z P0.11 containment produkowała dokładnie ten sam gap co przy Talent
Radar (19.08): link widoczny, klik = 403. ``require_b2b_generator_access``
teraz przepuszcza każdą rolę; ``_generator_unscoped``
(``b2b_contract_generator.py``) poszerzony w lockstep — inaczej nowo
wpuszczone role dostawałyby pustą listę zamiast 403
(``resolve_client_team_client_ids`` zna tylko DL/TAC).

Delivery Lead JEST WYJĄTKIEM i zostaje nietknięty: zachowuje fail-closed
wymóg jawnego przypisania klienta (operuje na swoim portfelu, nie całej
bazie) — patrz ``test_unassigned_client_team_role_fails_closed``.

Ten test dowodzi: KAŻDA rola przechodzi auth na reprezentatywnych
endpointach każdego typu (GET bez body, GET z listą, POST mutujący, GET
pobierania DOCX), a każda poza nieprzypisanym DL dostaje PEŁNY, nieoskopowany
dostęp — nie tylko przejście bramki. Wszystkie 13 endpointów B2B dzielą tę
samą dependency, więc reprezentatywna próbka pokrywa kontrakt.
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

# KAŻDA rola przechodzi auth na generatorze B2B (20.08). `_headers_for`
# domyślnie przypisuje DL/TAC do klienta, więc DL tu jest reprezentowany w
# swoim zwykłym, przypisanym stanie — nieprzypisany DL ma osobny test niżej.
ALL_ROLES = [
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "tac",
    "finance",
    "recruiter",
    "sourcer",
    "user",
]
# Pełny, nieoskopowany dostęp (nie tylko przejście bramki) — każda rola poza
# Delivery Lead, który zostaje przy wymogu jawnego przypisania klienta.
UNSCOPED_ROLES = [
    "admin",
    "head_of_recruitment",
    "tac",
    "finance",
    "recruiter",
    "sourcer",
    "user",
]


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
    """Generator B2B: KAŻDA rola przechodzi auth (20.08) — nikt nie dostaje 403
    tylko za to, jaką ma rolę (DL wciąż potrzebuje przypisania — domyślne
    ``assign_client=True`` w ``_headers_for`` je zapewnia)."""
    headers = await _headers_for(app_client, role_value)
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
    # hard deny on the generator surfaces. (Every other role intentionally does
    # NOT — see ``test_unscoped_roles_have_full_generator_access``.)
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


@pytest.mark.parametrize("role_value", UNSCOPED_ROLES)
async def test_unscoped_roles_have_full_generator_access(
    app_client: AsyncClient, role_value: str
):
    """Every non-DL role is a full-access generator persona (20.08).

    Originally a TAC-only regression guard: a freshly-added TAC with zero
    ``ClientTacAssignment`` rows saw the "Brak uprawnień" banner because the
    shared legal gate required a non-empty client graph — the generator is a
    full-access tool, so role alone must admit it. Generalized to every role
    opened on 20.08 for the same structural reason: none of them have any
    client-assignment row to be scoped by, so skipping one here would mean it
    passes ``require_b2b_generator_access`` and then hits a permanently empty
    list/403 on every entity — auth without access, not a real decision.
    """

    headers = await _headers_for(app_client, role_value, assign_client=False)

    # Global GET surfaces resolve, they do not 403 into an empty banner.
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url, headers=headers)
        assert r.status_code == 200, (
            f"unassigned {role_value} GET {url} → {r.status_code}: {r.text}"
        )

    # Drafting is reachable: auth passes, business logic 404s on the missing
    # role_id — never a client-scope 403.
    r = await app_client.post(
        GENERATE_URL,
        json={"role_id": 999999, "start_date": "2026-01-01"},
        headers=headers,
    )
    assert r.status_code == 404, (
        f"unassigned {role_value} POST generate → {r.status_code}: {r.text}"
    )

    # DOCX download is the highest-PII generator surface and (unlike
    # delete/update) has no author-only secondary check — so every full-access
    # role reaches it too. Missing id ⇒ 404 (gate + scope passed), never 403.
    # This guards the intentional expanded exposure against a future
    # re-tightening.
    r = await app_client.get(f"{GENERATED_URL}/999999/docx", headers=headers)
    assert r.status_code == 404, (
        f"unassigned {role_value} GET generated/docx → {r.status_code}: {r.text}"
    )


async def test_unauthenticated_is_rejected(app_client: AsyncClient):
    # No Authorization header → FastAPI's HTTPBearer rejects before the role
    # check runs. NEXUS returns 403 there (Bearer auto_error), so accept both
    # "not authenticated" codes — the point is the anon caller gets no data.
    for url in (ROLES_URL, NEXT_NUMBER_URL, GENERATED_URL):
        r = await app_client.get(url)
        assert r.status_code in (401, 403), f"anon GET {url} → {r.status_code}"
