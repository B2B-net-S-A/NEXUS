"""Delivery Lead widzi w modułach Delivery tylko przypisanych klientów.

Decyzja Artura 25.09.2026: w Klientach, Kontaktach, Kontraktach,
Kontraktorach, Zamówieniach i portalu „Moi klienci” DL widzi wyłącznie
klientów, do których ma JAKIEKOLWIEK przypisanie w
``delivery_lead_client_assignments`` (główny albo nie). Do tego dnia (#1365)
widział wszystkich. Zespół klienta, podpowiedzi klientów i generator umów B2B
zostają dla DL org-wide (``purpose="org"``). ``DL_CLIENT_SCOPE=all`` przywraca
stan sprzed zmiany; konto DL z rolą Talent Community Manager czyta Delivery
całej organizacji jak dotąd.

Baza testowa jest wspólna i nie jest czyszczona — każdy test zakłada własnych
klientów, kontrakty i użytkowników. Osoby i firmy są zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


async def _client(tag: str) -> int:
    from app.services.inactive_client_cleanup_signals import code_configured_client_ids

    # ID zaszyte w kodzie (e-Zdrowie, Polkomtel…) zmieniają zachowanie tras
    # zamówień — omijamy je jak w ``test_client_deletion``.
    reserved = set(code_configured_client_ids())
    async with AsyncSessionLocal() as db:
        while True:
            client = Client(
                name=f"DL Zakres {tag} {uuid.uuid4().hex[:8]}",
                status=ClientStatus.active,
            )
            db.add(client)
            await db.flush()
            if client.id not in reserved:
                break
            await db.delete(client)
            await db.flush()
        db.add(
            ClientPortfolioScope(client_id=client.id, category=PortfolioCategory.active)
        )
        await db.commit()
        return client.id


async def _contract(client_id: int) -> int:
    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan",
            lastname=f"Zakresowy-{suffix}",
            email=f"dl-scope-{suffix}@example.com",
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("140.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def _delivery_lead(
    app_client: AsyncClient,
    *,
    assigned_client_ids: tuple[int, ...] = (),
    extra_roles: tuple[UserRole, ...] = (),
) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"dl-scope-{unique}@example.com"
    password = f"P4ss_{unique}!X"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"DL Zakres {unique}",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value, *(r.value for r in extra_roles)],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        for client_id in assigned_client_ids:
            # Zwykłe (nie główne) przypisanie wystarcza.
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=client_id,
                    is_head=False,
                )
            )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_pair() -> tuple[int, int, int, int]:
    """Klient A (przypisany) i B (obcy), każdy z aktywnym kontraktem."""
    client_a = await _client("A")
    client_b = await _client("B")
    return client_a, await _contract(client_a), client_b, await _contract(client_b)


# ── Moduły Delivery: tylko przypisani klienci ───────────────────────────────


async def test_client_profile_and_directory_follow_assignment(
    app_client: AsyncClient,
) -> None:
    tag = uuid.uuid4().hex[:8]
    client_a = await _client(f"Katalog {tag}")
    client_b = await _client(f"Katalog {tag}")
    headers = await _delivery_lead(app_client, assigned_client_ids=(client_a,))

    own = await app_client.get(f"/api/clients/{client_a}", headers=headers)
    assert own.status_code == 200, own.text
    foreign = await app_client.get(f"/api/clients/{client_b}", headers=headers)
    assert foreign.status_code == 403, foreign.text
    foreign_profile = await app_client.get(
        f"/api/clients/{client_b}/profile", headers=headers
    )
    assert foreign_profile.status_code == 403, foreign_profile.text

    directory = await app_client.get(
        "/api/clients/directory",
        params={"category": "active", "q": tag},
        headers=headers,
    )
    assert directory.status_code == 200, directory.text
    listed = {item["client_id"] for item in directory.json()["items"]}
    assert client_a in listed
    assert client_b not in listed


async def test_contract_register_and_detail_follow_assignment(
    app_client: AsyncClient,
) -> None:
    client_a, contract_a, client_b, contract_b = await _seed_pair()
    headers = await _delivery_lead(app_client, assigned_client_ids=(client_a,))

    own = await app_client.get(
        "/api/contracts",
        params={"client_id": client_a, "group_by_candidate": "false"},
        headers=headers,
    )
    assert own.status_code == 200, own.text
    assert [item["id"] for item in own.json()["items"]] == [contract_a]

    foreign = await app_client.get(
        "/api/contracts",
        params={"client_id": client_b, "group_by_candidate": "false"},
        headers=headers,
    )
    assert foreign.status_code == 200, foreign.text
    assert foreign.json()["items"] == []
    assert foreign.json()["total"] == 0

    detail = await app_client.get(f"/api/contracts/{contract_b}", headers=headers)
    assert detail.status_code == 403, detail.text


async def test_contractors_roster_excludes_unassigned_clients(
    app_client: AsyncClient,
) -> None:
    client_a, contract_a, _client_b, contract_b = await _seed_pair()
    headers = await _delivery_lead(app_client, assigned_client_ids=(client_a,))

    roster = await app_client.get(
        "/api/contractors", params={"page_size": 200}, headers=headers
    )
    assert roster.status_code == 200, roster.text
    contract_ids = {item["contract_id"] for item in roster.json()["items"]}
    # Świeży DL ma jednego przypisanego klienta — lista to dokładnie jego umowa.
    assert contract_ids == {contract_a}
    assert contract_b not in contract_ids


async def test_orders_contacts_and_dashboard_of_foreign_client_are_denied(
    app_client: AsyncClient,
) -> None:
    client_a, _contract_a, client_b, _contract_b = await _seed_pair()
    headers = await _delivery_lead(app_client, assigned_client_ids=(client_a,))

    for path in (
        f"/api/clients/{client_b}/orders",
        f"/api/clients/{client_b}/contacts",
        f"/api/my-clients/{client_b}/dashboard",
    ):
        denied = await app_client.get(path, headers=headers)
        assert denied.status_code == 403, (path, denied.text)

    for path in (
        f"/api/clients/{client_a}/orders",
        f"/api/clients/{client_a}/contacts",
        f"/api/my-clients/{client_a}/dashboard",
    ):
        allowed = await app_client.get(path, headers=headers)
        assert allowed.status_code == 200, (path, allowed.text)


async def test_order_writes_at_foreign_client_are_denied(
    app_client: AsyncClient,
) -> None:
    """Zapis zamówienia u klienta spoza portfela = 403 (bramka routera).

    Trasa „nowe zamówienie” autoryzowała sam `DeliveryLeadOrAdmin`, więc bez
    `require_delivery_client_path_scope` DL zakładałby zamówienia u klienta,
    którego nie widzi.
    """
    client_a, _contract_a, client_b, contract_b = await _seed_pair()
    headers = await _delivery_lead(app_client, assigned_client_ids=(client_a,))

    created = await app_client.post(
        f"/api/clients/{client_b}/orders",
        data={
            "contract_id": str(contract_b),
            "title": "Zamówienie u obcego klienta",
            "order_status": "draft",
        },
        headers=headers,
    )
    assert created.status_code == 403, created.text
    groups = await app_client.get(
        f"/api/clients/{client_b}/order-groups", headers=headers
    )
    assert groups.status_code == 403, groups.text


# ── Powierzchnie org-wide: bez zmian ────────────────────────────────────────


async def test_client_team_and_lookup_stay_org_wide(app_client: AsyncClient) -> None:
    client_a = await _client("Zespół A")
    client_b = await _client("Zespół B")
    headers = await _delivery_lead(app_client, assigned_client_ids=(client_a,))

    team = await app_client.get(f"/api/clients/{client_b}/team", headers=headers)
    assert team.status_code == 200, team.text
    assert set(team.json()) == {"tacs", "delivery_leads"}

    lookup = await app_client.get("/api/clients-lookup", headers=headers)
    assert lookup.status_code == 200, lookup.text
    assert client_b in {row["id"] for row in lookup.json()}


async def test_b2b_generator_register_stays_org_wide(app_client: AsyncClient) -> None:
    client_a = await _client("Generator A")
    client_b = await _client("Generator B")
    seq = 100000 + (uuid.uuid4().int % 800000)
    contract_number = f"{seq}/2026"
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=contract_number,
            partner_name="Partner Testowy",
            client_id=client_b,
            client_name="Klient B",
            language="pl",
            render_payload={"language": "pl", "client_name": "Klient B"},
        )
        db.add(row)
        await db.commit()
        row_id = row.id
    headers = await _delivery_lead(app_client, assigned_client_ids=(client_a,))

    listed = await app_client.get(
        "/api/b2b-generator/generated",
        params={"q": contract_number},
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert row_id in {item["id"] for item in listed.json()}


# ── Wyłączniki ──────────────────────────────────────────────────────────────


async def test_scope_all_restores_every_client(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_a = await _client("Wyłącznik A")
    client_b = await _client("Wyłącznik B")
    headers = await _delivery_lead(app_client, assigned_client_ids=(client_a,))

    assert (
        await app_client.get(f"/api/clients/{client_b}", headers=headers)
    ).status_code == 403

    monkeypatch.setattr(settings, "DL_CLIENT_SCOPE", "all")
    restored = await app_client.get(f"/api/clients/{client_b}", headers=headers)
    assert restored.status_code == 200, restored.text


async def test_delivery_lead_with_tcm_role_reads_every_client(
    app_client: AsyncClient,
) -> None:
    client_a = await _client("TCM A")
    client_b = await _client("TCM B")
    headers = await _delivery_lead(
        app_client,
        assigned_client_ids=(client_a,),
        extra_roles=(UserRole.talent_community_manager,),
    )

    detail = await app_client.get(f"/api/clients/{client_b}", headers=headers)
    assert detail.status_code == 200, detail.text
    contacts = await app_client.get(
        f"/api/clients/{client_b}/contacts", headers=headers
    )
    assert contacts.status_code == 200, contacts.text


async def test_me_reports_the_delivery_client_scope(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_a = await _client("Me A")
    plain = await _delivery_lead(app_client, assigned_client_ids=(client_a,))
    hybrid = await _delivery_lead(
        app_client,
        assigned_client_ids=(client_a,),
        extra_roles=(UserRole.talent_community_manager,),
    )

    me = await app_client.get("/api/auth/me", headers=plain)
    assert me.status_code == 200, me.text
    assert me.json()["delivery_client_scope"] == "assigned"
    me_hybrid = await app_client.get("/api/auth/me", headers=hybrid)
    assert me_hybrid.json()["delivery_client_scope"] == "all"

    monkeypatch.setattr(settings, "DL_CLIENT_SCOPE", "all")
    me_all = await app_client.get("/api/auth/me", headers=plain)
    assert me_all.json()["delivery_client_scope"] == "all"
