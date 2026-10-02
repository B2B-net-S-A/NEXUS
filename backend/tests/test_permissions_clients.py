"""Uprawnienia z ekranu Osoby i role na powierzchniach klienta (0410).

Do 0410 o zapisie klienta, kontaktów, umów ramowych i wykonawczych decydowała
ROLA (admin / Delivery Lead), a „Moi klienci”, roster kontraktorów i kluczowe
relacje czytały listy ról. Teraz decyduje uprawnienie nadane roli albo osobie:

- **co** konto może — uprawnienie (odmowa nazywa brakującą pozycję, także
  wtedy, gdy zatrzymuje bramka sekcji),
- **u kogo** — zakres: konto z rolą Delivery Leada działa w swoim portfelu,
  każdy inny posiadacz u wszystkich klientów.

Pierwsza część idzie przez realne endpointy (in-process ASGI + Postgres
z migracjami, jak ``test_client_access_matrix.py``); druga sprawdza same
reguły bez bazy.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient, Response
from sqlalchemy import select

from app.api import client_directory, clients, my_clients, my_relationships
from app.api.client_framework_contracts import require_client_legal_docs_write
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.schemas.client import ClientResponse, ClientSafeResponse
from app.services.access_scope import DL_CLIENT_OUT_OF_SCOPE_DETAIL
from tests._authz_matrix import Persona, build_user
from tests._permission_grants import grant_permissions, role_permission

EZDROWIE_GATE = "app.services.ezdrowie.EZDROWIE_CLIENT_ID"


# ── Dane testowe ─────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole, *extra_roles: UserRole) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"perm-a-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!PermA"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Perm A {role.value} {unique}",
            role=role,
            roles=[role.value, *(extra.value for extra in extra_roles)],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _headers(client: AsyncClient, role: UserRole, *extra_roles: UserRole):
    user_id, email, password = await _seed_user(role, *extra_roles)
    return user_id, await _login(client, email, password)


async def _seed_client() -> tuple[int, str]:
    unique = uuid.uuid4().hex[:8]
    name = f"Perm A Client {unique}"
    async with AsyncSessionLocal() as db:
        client = Client(
            name=name,
            legal_name=f"{name} Sp. z o.o.",
            nip="5252530321",
            regon="147312213",
            notes="Poufne notatki handlowe",
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id, name


async def _assign_dl(user_id: int, client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=user_id,
                client_id=client_id,
            )
        )
        await db.commit()


async def _seed_framework(client_id: int, *, project_part: str | None = None) -> int:
    async with AsyncSessionLocal() as db:
        framework = ClientFrameworkContract(
            client_id=client_id,
            name=f"MSA {uuid.uuid4().hex[:6]}",
            status=FrameworkContractStatus.active,
            project_part=project_part,
        )
        db.add(framework)
        await db.commit()
        await db.refresh(framework)
        return framework.id


async def _seed_contact(
    client_id: int, *, owner_id: int | None, notes: str | None = None
) -> int:
    async with AsyncSessionLocal() as db:
        contact = Contact(
            client_id=client_id,
            name=f"Kontakt {uuid.uuid4().hex[:6]}",
            is_key_relationship=owner_id is not None,
            key_relationship_owner_id=owner_id,
            relationship_notes=notes,
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        return contact.id


def _denied_permission(response: Response) -> str:
    """Klucz uprawnienia z odmowy 403 w kształcie ``permission_denied``."""

    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), response.text
    assert detail["code"] == "permission_denied", response.text
    assert detail["message"].startswith("Brakuje Ci uprawnienia"), response.text
    return detail["permission"]


# ── 1. „Klienci: dodawanie i edycja” ─────────────────────────────────────────


async def test_recruiter_with_granted_clients_edit_creates_and_edits_a_client(
    app_client: AsyncClient,
) -> None:
    user_id, headers = await _headers(app_client, UserRole.recruiter)
    name = f"Perm A created {uuid.uuid4().hex[:8]}"

    # Bez uprawnienia odmowa nazywa je — także gdy zatrzymuje bramka sekcji.
    denied = await app_client.post("/api/clients", headers=headers, json={"name": name})
    assert _denied_permission(denied) == "clients_edit"

    await grant_permissions(user_id, "clients_edit")

    created = await app_client.post(
        "/api/clients",
        headers=headers,
        json={"name": name, "nip": "5252530321", "notes": "Notatka handlowa"},
    )
    assert created.status_code == 201, created.text
    client_id = created.json()["id"]

    # Formularz „Edytuj firmę” odsyła komplet pól; konto bez podglądu danych
    # prawnych przysyła je puste — zapis branży nie może ich skasować.
    edited = await app_client.patch(
        f"/api/clients/{client_id}",
        headers=headers,
        json={"industry": "Bankowość", "notes": None, "nip": ""},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["industry"] == "Bankowość"
    # Edycja klienta nie daje podglądu danych prawnych — to „Stawki i kwoty:
    # podgląd”. Pole nie występuje w odpowiedzi (nie jest ``null``).
    assert "nip" not in edited.json()

    detail = await app_client.get(f"/api/clients/{client_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    for field in ("nip", "regon", "legal_name", "notes"):
        assert field not in detail.json(), f"leaked legal field {field}"

    # Wpisana wartość to próba zmiany pola, którego konto nie widzi.
    blind = await app_client.patch(
        f"/api/clients/{client_id}", headers=headers, json={"nip": "1111111111"}
    )
    assert _denied_permission(blind) == "amounts_view"
    async with AsyncSessionLocal() as db:
        stored = await db.get(Client, client_id)
        assert stored.nip == "5252530321"
        assert stored.notes == "Notatka handlowa"

    # Posiadacz bez roli Delivery Leada działa u każdego klienta…
    contact = await app_client.post(
        "/api/contacts",
        headers=headers,
        json={"client_id": client_id, "name": "Kontakt od rekrutera"},
    )
    assert contact.status_code == 201, contact.text

    # …a auto-przypisanie twórcy jako głównego DL zostaje przy ROLI.
    async with AsyncSessionLocal() as db:
        assignment = await db.scalar(
            select(DeliveryLeadClientAssignment.id).where(
                DeliveryLeadClientAssignment.client_id == client_id
            )
        )
    assert assignment is None

    # Z podglądem danych prawnych to samo konto zmienia je i czyści jak dotąd.
    await grant_permissions(user_id, "amounts_view")
    legal = await app_client.patch(
        f"/api/clients/{client_id}",
        headers=headers,
        json={"nip": "1111111111", "notes": None},
    )
    assert legal.status_code == 200, legal.text
    assert legal.json()["nip"] == "1111111111"
    assert legal.json()["notes"] is None


async def test_delivery_lead_without_clients_edit_reads_but_cannot_edit(
    app_client: AsyncClient,
) -> None:
    client_id, _ = await _seed_client()
    dl_id, headers = await _headers(app_client, UserRole.delivery_lead)
    await _assign_dl(dl_id, client_id)

    # Domyślnie Delivery Lead edytuje klienta ze swojego portfela.
    before = await app_client.patch(
        f"/api/clients/{client_id}", headers=headers, json={"industry": "IT"}
    )
    assert before.status_code == 200, before.text

    async with role_permission("delivery_lead", "clients_edit", granted=False):
        edit = await app_client.patch(
            f"/api/clients/{client_id}", headers=headers, json={"industry": "Bank"}
        )
        assert _denied_permission(edit) == "clients_edit"

        contact = await app_client.post(
            "/api/contacts",
            headers=headers,
            json={"client_id": client_id, "name": "Bez uprawnienia"},
        )
        assert _denied_permission(contact) == "clients_edit"

        knowledge = await app_client.post(
            f"/api/clients/{client_id}/knowledge",
            headers=headers,
            json={"category": "general", "content": "notatka"},
        )
        assert _denied_permission(knowledge) == "clients_edit"

        # Podgląd zostaje: wyłączona edycja nie odbiera klienta z portfela.
        detail = await app_client.get(f"/api/clients/{client_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["industry"] == "IT"
        contacts = await app_client.get(
            f"/api/clients/{client_id}/contacts", headers=headers
        )
        assert contacts.status_code == 200, contacts.text

    # Po przywróceniu przełącznika roli edycja wraca tym samym tokenem.
    after = await app_client.patch(
        f"/api/clients/{client_id}", headers=headers, json={"industry": "Bank"}
    )
    assert after.status_code == 200, after.text


async def test_contact_edit_denial_names_the_permission_and_owner_rule_stays(
    app_client: AsyncClient,
) -> None:
    client_id, _ = await _seed_client()
    tcm_id, headers = await _headers(app_client, UserRole.talent_community_manager)
    own_contact = await _seed_contact(client_id, owner_id=tcm_id)
    other_contact = await _seed_contact(client_id, owner_id=None)

    # Talent Community Manager ma zapis w Delivery (zmienia status kontraktu),
    # ale klientów nie edytuje — odmowa mówi, którego uprawnienia brakuje.
    created = await app_client.post(
        "/api/contacts",
        headers=headers,
        json={"client_id": client_id, "name": "Nowy kontakt"},
    )
    assert _denied_permission(created) == "clients_edit"
    deleted = await app_client.delete(f"/api/contacts/{other_contact}", headers=headers)
    assert _denied_permission(deleted) == "clients_edit"
    edited = await app_client.put(
        f"/api/contacts/{other_contact}", headers=headers, json={"name": "Zmiana"}
    )
    assert _denied_permission(edited) == "clients_edit"

    # Właściciel relacji nadal prowadzi pola relacyjne SWOJEGO kontaktu — to
    # reguła o relacji, nie uprawnienie…
    own = await app_client.put(
        f"/api/contacts/{own_contact}",
        headers=headers,
        json={"relationship_strength": "strong"},
    )
    assert own.status_code == 200, own.text
    assert own.json()["relationship_strength"] == "strong"
    # …ale pól tożsamościowych już nie.
    identity = await app_client.put(
        f"/api/contacts/{own_contact}", headers=headers, json={"name": "Inne nazwisko"}
    )
    assert identity.status_code == 403, identity.text
    assert str(identity.json()["detail"]).startswith("client_access_denied")


# ── 2. Sam podgląd Delivery ──────────────────────────────────────────────────


async def test_delivery_view_only_reads_clients_without_legal_data(
    app_client: AsyncClient,
) -> None:
    client_id, client_name = await _seed_client()
    framework_id = await _seed_framework(client_id)
    owner_id, _, _ = await _seed_user(UserRole.delivery_lead)
    await _assign_dl(owner_id, client_id)
    key_contact = await _seed_contact(
        client_id, owner_id=owner_id, notes="Prywatna notatka relacyjna"
    )
    user_id, headers = await _headers(app_client, UserRole.recruiter)

    # Rekruter bez uprawnień nie wchodzi do klientów; odmowa nazywa podgląd.
    blocked = await app_client.get(f"/api/clients/{client_id}", headers=headers)
    assert _denied_permission(blocked) == "delivery_view"

    await grant_permissions(user_id, "delivery_view")

    listing = await app_client.get(
        "/api/clients", headers=headers, params={"q": client_name}
    )
    assert listing.status_code == 200, listing.text
    rows = [row for row in listing.json()["items"] if row["id"] == client_id]
    assert rows, "klient musi być na liście posiadacza podglądu"
    detail = await app_client.get(f"/api/clients/{client_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    for body in (rows[0], detail.json()):
        for field in ("nip", "regon", "legal_name", "notes"):
            assert field not in body, f"leaked legal field {field}"

    # Dokumenty prawne mogą nieść stawki — wymagają „Stawki i kwoty: podgląd”.
    base = f"/api/clients/{client_id}"
    for path in (
        f"{base}/contract-terms",
        f"{base}/framework-contracts",
        f"{base}/framework-contracts/{framework_id}",
        f"{base}/framework-contracts/{framework_id}/file",
        f"{base}/framework-contracts/{framework_id}/amendments",
    ):
        legal = await app_client.get(path, headers=headers)
        assert _denied_permission(legal) == "amounts_view", path

    # Podgląd to nie zapis.
    write = await app_client.post(
        "/api/contacts",
        headers=headers,
        json={"client_id": client_id, "name": "Bez edycji"},
    )
    assert _denied_permission(write) == "clients_edit"

    # „Moi klienci”, roster i kluczowe relacje: posiadacz podglądu bez roli DL
    # czyta całą organizację — bez kwot i bez prywatnych notatek relacyjnych.
    mine = await app_client.get("/api/my-clients", headers=headers)
    assert mine.status_code == 200, mine.text
    row = next(r for r in mine.json() if r["client_id"] == client_id)
    assert "total_revenue_all_time" not in row
    assert "active_revenue" not in row

    dashboard = await app_client.get(
        f"/api/my-clients/{client_id}/dashboard", headers=headers
    )
    assert dashboard.status_code == 200, dashboard.text
    assert "total_revenue_all_time" not in dashboard.json()

    roster = await app_client.get(
        "/api/contractors", headers=headers, params={"page_size": 1}
    )
    assert roster.status_code == 200, roster.text
    stats = await app_client.get("/api/contractors/stats", headers=headers)
    assert stats.status_code == 200, stats.text

    relationships = await app_client.get("/api/my-relationships", headers=headers)
    assert relationships.status_code == 200, relationships.text
    relation = next(r for r in relationships.json() if r["contact_id"] == key_contact)
    assert relation["relationship_notes"] is None


async def test_my_clients_amounts_follow_the_amounts_view_permission(
    app_client: AsyncClient,
) -> None:
    client_id, _ = await _seed_client()
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name=f"Perm A {suffix}", lastname=f"Testowy{suffix}")
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            start_date=business_today(),
            rate_client=15000,
            rate_candidate=12000,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client_id,
                contract_id=contract.id,
                title="Perm A kwoty",
                status=ClientOrderStatus.active,
                start_date=business_today(),
                total_value=Decimal("25000.00"),
                currency="PLN",
            )
        )
        await db.commit()
        candidate_id = candidate.id

    dl_id, dl_headers = await _headers(app_client, UserRole.delivery_lead)
    await _assign_dl(dl_id, client_id)
    reader_id, reader_headers = await _headers(app_client, UserRole.recruiter)
    await grant_permissions(reader_id, "delivery_view")

    async def my_client_row(headers: dict[str, str]) -> dict:
        resp = await app_client.get("/api/my-clients", headers=headers)
        assert resp.status_code == 200, resp.text
        return next(r for r in resp.json() if r["client_id"] == client_id)

    try:
        # Delivery Lead domyślnie widzi kwoty klienta ze swojego portfela.
        row = await my_client_row(dl_headers)
        assert Decimal(str(row["active_revenue"])) == Decimal("25000.00")

        # Sam podgląd Delivery: wiersz jest, kwot nie ma.
        row = await my_client_row(reader_headers)
        assert "active_revenue" not in row
        assert "total_revenue_all_time" not in row

        # Nadany podgląd kwot działa u każdego klienta (konto bez roli DL).
        await grant_permissions(reader_id, "amounts_view")
        row = await my_client_row(reader_headers)
        assert Decimal(str(row["active_revenue"])) == Decimal("25000.00")
        assert Decimal(str(row["total_revenue_all_time"])) == Decimal("25000.00")

        # Wyłączony przełącznik roli odbiera kwoty także u własnego klienta —
        # na liście i na dashboardzie tak samo.
        async with role_permission("delivery_lead", "amounts_view", granted=False):
            row = await my_client_row(dl_headers)
            assert "active_revenue" not in row
            assert "total_revenue_all_time" not in row
            dashboard = await app_client.get(
                f"/api/my-clients/{client_id}/dashboard", headers=dl_headers
            )
            assert dashboard.status_code == 200, dashboard.text
            assert "active_revenue" not in dashboard.json()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
            )
            await db.execute(
                Contract.__table__.delete().where(Contract.client_id == client_id)
            )
            await db.execute(
                Candidate.__table__.delete().where(Candidate.id == candidate_id)
            )
            await db.commit()


# ── 3. Dokumenty prawne: umowy ramowe, aneksy, umowy wykonawcze ──────────────


async def test_finance_writes_framework_and_executive_contracts(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decyzja 02.10.2026: Finanse prowadzą kontrakty i zamówienia.

    Mają „Kontrakty i zamówienia: tworzenie i edycja” razem z podglądem kwot,
    więc zapisują umowy ramowe, aneksy, warunki umów i umowy wykonawcze —
    u każdego klienta. Klientów nadal nie edytują.
    """

    client_id, _ = await _seed_client()
    part_framework = await _seed_framework(client_id, project_part="cz4")
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    _, headers = await _headers(app_client, UserRole.finance)
    base = f"/api/clients/{client_id}"

    created = await app_client.post(
        f"{base}/framework-contracts", headers=headers, data={"name": "MSA Finanse"}
    )
    assert created.status_code == 201, created.text
    framework_id = created.json()["id"]

    patched = await app_client.patch(
        f"{base}/framework-contracts/{framework_id}",
        headers=headers,
        json={"notes": "uzupełnione przez Finanse"},
    )
    assert patched.status_code == 200, patched.text

    amendment = await app_client.post(
        f"{base}/framework-contracts/{framework_id}/amendments",
        headers=headers,
        data={"name": "Aneks nr 1", "effective_date": business_today().isoformat()},
    )
    assert amendment.status_code == 201, amendment.text
    removed = await app_client.delete(
        f"{base}/framework-contracts/{framework_id}/amendments/"
        f"{amendment.json()['id']}",
        headers=headers,
    )
    assert removed.status_code == 204, removed.text

    terms = await app_client.put(
        f"{base}/contract-terms", headers=headers, json={"payment_net_days": 30}
    )
    assert terms.status_code == 200, terms.text

    executive = await app_client.post(
        f"{base}/executive-contracts",
        headers=headers,
        json={
            "framework_contract_id": part_framework,
            "number": f"TEST/EC/FIN/{uuid.uuid4().hex[:6]}",
        },
    )
    assert executive.status_code == 201, executive.text
    renamed = await app_client.patch(
        f"{base}/executive-contracts/{executive.json()['id']}",
        headers=headers,
        json={"notes": "notatka Finansów"},
    )
    assert renamed.status_code == 200, renamed.text

    # Szkic umowy ramowej Finanse też usuwają.
    deleted = await app_client.delete(
        f"{base}/framework-contracts/{framework_id}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text

    # Kontrakty i zamówienia to nie klienci.
    client_edit = await app_client.patch(base, headers=headers, json={"industry": "X"})
    assert _denied_permission(client_edit) == "clients_edit"
    contact = await app_client.post(
        "/api/contacts", headers=headers, json={"client_id": client_id, "name": "Nie"}
    )
    assert _denied_permission(contact) == "clients_edit"


async def test_granted_contracts_edit_writes_executive_but_not_framework_contracts(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id, _ = await _seed_client()
    part_framework = await _seed_framework(client_id, project_part="cz2")
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    user_id, headers = await _headers(app_client, UserRole.talent_community_manager)
    base = f"/api/clients/{client_id}"
    payload = {
        "framework_contract_id": part_framework,
        "number": f"TEST/EC/TCM/{uuid.uuid4().hex[:6]}",
    }

    # Talent Community Manager domyślnie nie prowadzi kontraktów.
    denied = await app_client.post(
        f"{base}/executive-contracts", headers=headers, json=payload
    )
    assert _denied_permission(denied) == "contracts_orders_edit"

    await grant_permissions(user_id, "contracts_orders_edit")

    # Umowa wykonawcza nie niesie stawek — wystarcza prowadzenie kontraktów.
    executive = await app_client.post(
        f"{base}/executive-contracts", headers=headers, json=payload
    )
    assert executive.status_code == 201, executive.text

    # Umowa ramowa i aneks mogą nieść stawki: bez podglądu kwot odmowa.
    framework = await app_client.post(
        f"{base}/framework-contracts", headers=headers, data={"name": "MSA bez kwot"}
    )
    assert _denied_permission(framework) == "amounts_view"
    amendment = await app_client.post(
        f"{base}/framework-contracts/{part_framework}/amendments",
        headers=headers,
        data={"name": "Aneks", "effective_date": business_today().isoformat()},
    )
    assert _denied_permission(amendment) == "amounts_view"
    terms = await app_client.put(
        f"{base}/contract-terms", headers=headers, json={"payment_net_days": 14}
    )
    assert _denied_permission(terms) == "amounts_view"


async def test_delivery_lead_outside_assignment_is_refused_by_portfolio(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uprawnienie jest, klienta nie ma w portfelu — odmowa mówi o portfelu."""

    own_id, _ = await _seed_client()
    foreign_id, _ = await _seed_client()
    foreign_part = await _seed_framework(foreign_id, project_part="cz1")
    monkeypatch.setattr(EZDROWIE_GATE, foreign_id)
    dl_id, dl_headers = await _headers(app_client, UserRole.delivery_lead)
    await _assign_dl(dl_id, own_id)
    executive_payload = {"framework_contract_id": foreign_part, "number": "TEST/EC/X"}

    framework = await app_client.post(
        f"/api/clients/{foreign_id}/framework-contracts",
        headers=dl_headers,
        data={"name": "Cudzy klient"},
    )
    assert framework.status_code == 403, framework.text
    assert framework.json()["detail"] == DL_CLIENT_OUT_OF_SCOPE_DETAIL
    executive = await app_client.post(
        f"/api/clients/{foreign_id}/executive-contracts",
        headers=dl_headers,
        json=executive_payload,
    )
    assert executive.status_code == 403, executive.text
    assert executive.json()["detail"] == DL_CLIENT_OUT_OF_SCOPE_DETAIL

    # U klienta z portfela ten sam Delivery Lead zapisuje bez przeszkód.
    own = await app_client.post(
        f"/api/clients/{own_id}/framework-contracts",
        headers=dl_headers,
        data={"name": "Własny klient"},
    )
    assert own.status_code == 201, own.text

    # Hybryda DL + TCM WIDZI każdego klienta, ale konsekwentny zapis prawny
    # nadal wymaga jawnego przypisania — granica przypisania, nie widoczności.
    hybrid_id, hybrid_headers = await _headers(
        app_client, UserRole.delivery_lead, UserRole.talent_community_manager
    )
    await _assign_dl(hybrid_id, own_id)
    seen = await app_client.get(f"/api/clients/{foreign_id}", headers=hybrid_headers)
    assert seen.status_code == 200, seen.text
    framework = await app_client.post(
        f"/api/clients/{foreign_id}/framework-contracts",
        headers=hybrid_headers,
        data={"name": "Bez przypisania"},
    )
    assert framework.status_code == 403, framework.text
    assert str(framework.json()["detail"]).startswith("client_access_denied")
    executive = await app_client.post(
        f"/api/clients/{foreign_id}/executive-contracts",
        headers=hybrid_headers,
        json=executive_payload,
    )
    assert executive.status_code == 403, executive.text
    assert executive.json()["detail"] == DL_CLIENT_OUT_OF_SCOPE_DETAIL


# ── Reguły bez bazy ──────────────────────────────────────────────────────────


class _Rows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


_ACCOUNT_IDS = iter(range(930_000, 931_000))


def _account(
    role: UserRole, *extra_roles: UserRole, grants: tuple[str, ...] = ()
) -> User:
    """Konto z polityką dołączoną tak, jak robi to uwierzytelnienie."""

    return build_user(
        Persona(role.value, role, tuple(extra_roles), grants),
        user_id=next(_ACCOUNT_IDS),
    )


def _without(user: User, permission: str) -> User:
    """To samo konto po wyłączeniu przełącznika roli przez administratora."""

    user.effective_action_access = {
        **user.effective_action_access,
        permission: "none",
    }
    return user


def test_client_legal_fields_follow_the_amounts_view_permission() -> None:
    for holder in (
        _account(UserRole.admin),
        _account(UserRole.finance),
        _account(UserRole.delivery_lead),
        _account(UserRole.recruiter, grants=("amounts_view",)),
    ):
        assert clients._client_schema_for(holder) is ClientResponse
        assert client_directory._can_view_directory_legal(holder)

    for reader in (
        _account(UserRole.talent_community_manager),
        _account(UserRole.recruiter, grants=("delivery_view",)),
        _account(UserRole.recruiter, grants=("clients_edit",)),
        _without(_account(UserRole.delivery_lead), "amounts_view"),
    ):
        assert clients._client_schema_for(reader) is ClientSafeResponse
        assert not client_directory._can_view_directory_legal(reader)


def test_client_legal_fields_cannot_be_changed_without_seeing_them() -> None:
    """Edycja klienta bez podglądu danych prawnych nie kasuje ich ani nie zmienia."""

    for editor in (
        _account(UserRole.recruiter, grants=("clients_edit",)),
        _without(_account(UserRole.delivery_lead), "amounts_view"),
    ):
        # Formularz odsyła komplet pól: puste dane prawne są pomijane.
        blank = {"industry": "IT", "notes": None, "nip": "", "legal_name": None}
        clients._keep_unreadable_legal_fields(editor, blank)
        assert blank == {"industry": "IT"}

        # Wpisana wartość = próba zmiany pola, którego konto nie widzi.
        for field in ("legal_name", "nip", "regon", "notes"):
            with pytest.raises(HTTPException) as denied:
                clients._keep_unreadable_legal_fields(
                    editor, {"industry": "IT", field: "nowa wartość"}
                )
            assert denied.value.status_code == 403
            assert denied.value.detail["permission"] == "amounts_view"

    # Konto z podglądem zmienia i czyści dane prawne jak dotąd.
    for holder in (
        _account(UserRole.admin),
        _account(UserRole.delivery_lead),
        _account(UserRole.recruiter, grants=("clients_edit", "amounts_view")),
    ):
        full = {"industry": "IT", "notes": None, "nip": "1111111111"}
        clients._keep_unreadable_legal_fields(holder, full)
        assert full == {"industry": "IT", "notes": None, "nip": "1111111111"}


async def test_legal_docs_writer_needs_both_permissions_and_the_dl_assignment() -> None:
    no_db = SimpleNamespace(scalars=AsyncMock(), execute=AsyncMock())

    # Finanse: komplet uprawnień, brak portfela — każdy klient, bez pytania bazy.
    finance = _account(UserRole.finance)
    assert (
        await require_client_legal_docs_write(
            client_id=77, current_user=finance, _amounts_viewer=finance, db=no_db
        )
        is finance
    )
    no_db.scalars.assert_not_awaited()
    no_db.execute.assert_not_awaited()

    # Nadane prowadzenie kontraktów bez podglądu kwot: odmowa nazywa kwoty.
    holder = _account(
        UserRole.talent_community_manager, grants=("contracts_orders_edit",)
    )
    with pytest.raises(HTTPException) as missing_amounts:
        await require_client_legal_docs_write(
            client_id=77, current_user=holder, _amounts_viewer=holder, db=no_db
        )
    assert missing_amounts.value.status_code == 403
    assert missing_amounts.value.detail["permission"] == "amounts_view"

    # Podgląd kwot bez prowadzenia kontraktów: brakuje pierwszego z dwóch.
    viewer = _account(UserRole.recruiter, grants=("amounts_view",))
    with pytest.raises(HTTPException) as missing_edit:
        await require_client_legal_docs_write(
            client_id=77,
            current_user=viewer,
            _amounts_viewer=viewer,
            db=SimpleNamespace(execute=AsyncMock(return_value=_Scalar(False))),
        )
    assert missing_edit.value.detail["permission"] == "contracts_orders_edit"

    # Delivery Lead: u klienta z przypisania tak, poza nim komunikat o przypisaniu.
    lead = _account(UserRole.delivery_lead)
    assigned_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([77])))
    assert (
        await require_client_legal_docs_write(
            client_id=77, current_user=lead, _amounts_viewer=lead, db=assigned_db
        )
        is lead
    )
    foreign_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10])))
    with pytest.raises(HTTPException) as unassigned:
        await require_client_legal_docs_write(
            client_id=77, current_user=lead, _amounts_viewer=lead, db=foreign_db
        )
    assert unassigned.value.status_code == 403
    assert str(unassigned.value.detail).startswith("client_access_denied")


async def test_client_dashboard_gate_is_org_wide_unless_delivery_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        my_clients,
        "resolve_visible_client",
        AsyncMock(return_value=SimpleNamespace(id=77)),
    )
    gate = my_clients.require_client_dashboard_access_after_merge
    no_db = SimpleNamespace(scalars=AsyncMock())

    # Posiadacz podglądu bez roli DL czyta dashboard każdego klienta.
    for reader in (
        _account(UserRole.finance),
        _account(UserRole.talent_community_manager),
        _account(UserRole.recruiter, grants=("delivery_view",)),
    ):
        assert await gate(client_id=77, current_user=reader, db=no_db) is reader
    no_db.scalars.assert_not_awaited()

    # Konto z rolą Delivery Leada (także hybryda z HoR) zostaje przy portfelu.
    for lead in (
        _account(UserRole.delivery_lead),
        _account(UserRole.head_of_recruitment, UserRole.delivery_lead),
    ):
        own_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([77])))
        assert await gate(client_id=77, current_user=lead, db=own_db) is lead
        foreign_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10])))
        with pytest.raises(HTTPException) as denied:
            await gate(client_id=77, current_user=lead, db=foreign_db)
        assert denied.value.status_code == 403
        assert denied.value.detail == DL_CLIENT_OUT_OF_SCOPE_DETAIL


async def test_key_relationships_scope_follows_the_view_permission() -> None:
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    row = SimpleNamespace(
        id=5,
        name="Kontakt kluczowy",
        position=None,
        email=None,
        phone=None,
        client_id=77,
        client_name="Klient fikcyjny",
        is_decision_maker=False,
        relationship_strength=None,
        relationship_notes="Prywatna notatka",
        last_personal_touchpoint_at=None,
        last_contacted_at=None,
    )

    def _db(statements: list[str], *, portfolio: list[int] | None = None):
        async def execute(statement):
            statements.append(
                str(statement.compile(compile_kwargs={"literal_binds": True}))
            )
            return _Result([row])

        return SimpleNamespace(
            execute=execute,
            scalars=AsyncMock(return_value=_Rows(portfolio or [])),
        )

    # Nadany podgląd Delivery: wszystkie kluczowe relacje, bez filtra
    # właściciela — ale prywatne notatki zostają przy roli (admin, Finanse).
    statements: list[str] = []
    granted = _account(UserRole.recruiter, grants=("delivery_view",))
    items = await my_relationships.list_my_key_relationships(granted, _db(statements))
    assert "key_relationship_owner_id" not in statements[0]
    assert items[0].relationship_notes is None

    statements = []
    finance = _account(UserRole.finance)
    items = await my_relationships.list_my_key_relationships(finance, _db(statements))
    assert "key_relationship_owner_id" not in statements[0]
    assert items[0].relationship_notes == "Prywatna notatka"

    # Konto z rolą Delivery Leada: tylko własne relacje u klientów z portfela.
    statements = []
    lead = _account(UserRole.delivery_lead)
    items = await my_relationships.list_my_key_relationships(
        lead, _db(statements, portfolio=[77])
    )
    assert f"key_relationship_owner_id = {lead.id}" in statements[0]
    assert "contacts.client_id IN (77)" in statements[0]
    assert items[0].relationship_notes == "Prywatna notatka"
