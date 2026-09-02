"""Macierz dostępu do modułu klienta (Moduł 1, PR 1/7 — containment RBAC).

Testuje ``app.services.client_access.ClientAccess`` przez realne endpointy
(in-process ASGI + Postgres z migracjami — jak test_rbac.py):

- macierz profil użytkownika × operacja (kontakty, wiedza, materiały,
  warunki umów, umowy ramowe);
- bezpieczne projekcje: brak pól prawnych/prywatnych/finansowych w JSON
  (pole NIE występuje — nie jest ``null``);
- reguły właściciela relacji (edycja pól relacyjnych, zakaz przepisania
  ownera, claim None → self);
- polityka 404 vs 403;
- audit eventy w ``activities`` (nazwy pól, nigdy wartości prywatne);
- użytkownik multi-role (recruiter + delivery_lead w ``roles``).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def _seed_user(
    role: UserRole, secondary_roles: list[str] | None = None
) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"cam-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!CAM"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"CAM {role.value} {unique}",
            role=role,
            roles=secondary_roles or [role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_client() -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Client(
            name=f"CAM Client {unique}",
            legal_name=f"CAM Client {unique} Sp. z o.o.",
            nip="5252530321",
            regon="147312213",
            notes="Poufne notatki handlowe",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_contact(
    client_id: int,
    *,
    owner_id: int | None = None,
    notes: str | None = "Urodziny 1 maja, dwoje dzieci",
) -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        contact = Contact(
            client_id=client_id,
            name=f"Kontakt {unique}",
            position="CTO",
            is_key_relationship=owner_id is not None,
            relationship_notes=notes,
            key_relationship_owner_id=owner_id,
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        return contact.id


async def _seed_job(client_id: int, recruiter_id: int) -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"CAM Job {unique}",
            client_id=client_id,
            recruiter_id=recruiter_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _assign_client(
    user_id: int,
    client_id: int,
    role: UserRole,
) -> None:
    async with AsyncSessionLocal() as db:
        if role is UserRole.delivery_lead:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user_id,
                    client_id=client_id,
                )
            )
        elif role is UserRole.tac:
            db.add(
                ClientTacAssignment(
                    tac_user_id=user_id,
                    client_id=client_id,
                )
            )
        else:
            raise AssertionError(f"Unsupported client assignment role: {role}")
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def cam_client() -> AsyncClient:
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Macierz profil × operacja ────────────────────────────────────────────────
#
# Profile:
#   admin / hor          — role administracyjne (pełny dostęp)
#   dl / tac             — role zespołu klienta z jawnym przypisaniem
#   tcm                  — globalny, bezpieczny odczyt Delivery
#   recruiter_assigned   — recruiter z Jobem u tego klienta (odczyt operacyjny)
#   recruiter            — recruiter bez przypisania
#   sourcer              — sourcer bez przypisania
#   viewer               — rola `user` (QC / klient) — brak dostępu
#   multi_dl             — primary recruiter + delivery_lead w `roles`
#                          (M1-RBAC-02: liczy się unia ról)
#
# Wartości: True = oczekiwane 2xx, False = oczekiwane 403.

MATRIX: dict[str, dict[str, bool]] = {
    # profile:             contacts  create  knowledge_r  knowledge_w  materials  terms  framework
    "admin": dict(
        client_read=True,
        contacts_read=True,
        contact_write=True,
        knowledge_read=True,
        knowledge_write=True,
        materials_read=True,
        terms_read=True,
        framework_read=True,
        legal_fields=True,
        financials=True,
    ),
    "hor": dict(
        client_read=False,
        contacts_read=True,
        contact_write=False,
        knowledge_read=False,
        knowledge_write=False,
        materials_read=False,
        terms_read=False,
        framework_read=False,
        legal_fields=False,
        financials=False,
    ),
    "dl": dict(
        client_read=True,
        contacts_read=True,
        contact_write=True,
        knowledge_read=True,
        knowledge_write=True,
        materials_read=True,
        terms_read=True,
        framework_read=True,
        legal_fields=True,
        financials=True,
    ),
    "tac": dict(
        client_read=False,
        contacts_read=True,
        contact_write=False,
        knowledge_read=False,
        knowledge_write=False,
        materials_read=False,
        terms_read=False,
        framework_read=False,
        legal_fields=False,
        financials=False,
    ),
    "tcm": dict(
        client_read=True,
        contacts_read=True,
        contact_write=False,
        knowledge_read=True,
        knowledge_write=False,
        materials_read=True,
        terms_read=False,
        framework_read=False,
        legal_fields=False,
        financials=False,
    ),
    "finance": dict(
        client_read=True,
        contacts_read=True,
        contact_write=False,
        knowledge_read=True,
        knowledge_write=False,
        materials_read=True,
        terms_read=True,
        framework_read=True,
        legal_fields=True,
        financials=True,
    ),
    "recruiter_assigned": dict(
        client_read=False,
        contacts_read=True,
        contact_write=False,
        knowledge_read=False,
        knowledge_write=False,
        materials_read=False,
        terms_read=False,
        framework_read=False,
        legal_fields=False,
        financials=False,
    ),
    "recruiter": dict(
        client_read=False,
        contacts_read=False,
        contact_write=False,
        knowledge_read=False,
        knowledge_write=False,
        materials_read=False,
        terms_read=False,
        framework_read=False,
        legal_fields=False,
        financials=False,
    ),
    "sourcer": dict(
        client_read=False,
        contacts_read=False,
        contact_write=False,
        knowledge_read=False,
        knowledge_write=False,
        materials_read=False,
        terms_read=False,
        framework_read=False,
        legal_fields=False,
        financials=False,
    ),
    "viewer": dict(
        client_read=False,
        contacts_read=False,
        contact_write=False,
        knowledge_read=False,
        knowledge_write=False,
        materials_read=False,
        terms_read=False,
        framework_read=False,
        legal_fields=False,
        financials=False,
    ),
    "multi_dl": dict(
        client_read=True,
        contacts_read=True,
        contact_write=True,
        knowledge_read=True,
        knowledge_write=True,
        materials_read=True,
        terms_read=True,
        framework_read=True,
        legal_fields=True,
        financials=True,
    ),
}

_PROFILE_ROLE: dict[str, tuple[UserRole, list[str] | None]] = {
    "admin": (UserRole.admin, None),
    "hor": (UserRole.head_of_recruitment, None),
    "dl": (UserRole.delivery_lead, None),
    "tcm": (UserRole.talent_community_manager, None),
    "finance": (UserRole.finance, None),
    "tac": (UserRole.tac, None),
    "recruiter_assigned": (UserRole.recruiter, None),
    "recruiter": (UserRole.recruiter, None),
    "sourcer": (UserRole.sourcer, None),
    "viewer": (UserRole.user, None),
    "multi_dl": (UserRole.recruiter, ["recruiter", "delivery_lead"]),
}


async def _profile_headers(
    cam_client: AsyncClient, profile: str, client_id: int
) -> dict[str, str]:
    role, secondary = _PROFILE_ROLE[profile]
    user_id, email, password = await _seed_user(role, secondary)
    if profile == "recruiter_assigned":
        await _seed_job(client_id, user_id)
    elif profile in {"dl", "multi_dl"}:
        await _assign_client(user_id, client_id, UserRole.delivery_lead)
    elif profile == "tac":
        await _assign_client(user_id, client_id, UserRole.tac)
    return await _login(cam_client, email, password)


def _expect(resp_status: int, allowed: bool, what: str, profile: str) -> None:
    if allowed:
        assert resp_status < 400, f"[{profile}] {what}: expected 2xx, got {resp_status}"
    else:
        assert resp_status == 403, (
            f"[{profile}] {what}: expected 403, got {resp_status}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", list(MATRIX))
async def test_access_matrix(cam_client: AsyncClient, profile: str) -> None:
    """Tabelaryczna macierz rola × operacja dla powierzchni klienta."""
    expected = MATRIX[profile]
    client_id = await _seed_client()
    await _seed_contact(client_id)
    headers = await _profile_headers(cam_client, profile, client_id)

    # Odczyt kontaktów klienta
    resp = await cam_client.get(f"/api/clients/{client_id}/contacts", headers=headers)
    _expect(resp.status_code, expected["contacts_read"], "contacts read", profile)

    # Zapis kontaktu
    resp = await cam_client.post(
        "/api/contacts",
        headers=headers,
        json={"client_id": client_id, "name": f"Nowy {profile}"},
    )
    _expect(resp.status_code, expected["contact_write"], "contact create", profile)

    # Wiedza — odczyt i zapis
    resp = await cam_client.get(f"/api/clients/{client_id}/knowledge", headers=headers)
    _expect(resp.status_code, expected["knowledge_read"], "knowledge read", profile)

    resp = await cam_client.post(
        f"/api/clients/{client_id}/knowledge",
        headers=headers,
        json={"category": "general", "content": "notatka testowa"},
    )
    _expect(resp.status_code, expected["knowledge_write"], "knowledge write", profile)

    # Materiały (one-pagery)
    resp = await cam_client.get(f"/api/clients/{client_id}/one-pagers", headers=headers)
    _expect(resp.status_code, expected["materials_read"], "materials read", profile)

    # Warunki umów (dane prawne)
    resp = await cam_client.get(
        f"/api/clients/{client_id}/contract-terms", headers=headers
    )
    _expect(resp.status_code, expected["terms_read"], "terms read", profile)

    # Umowy ramowe (dokumenty prawne)
    resp = await cam_client.get(
        f"/api/clients/{client_id}/framework-contracts", headers=headers
    )
    _expect(resp.status_code, expected["framework_read"], "framework read", profile)

    # Projekcja klienta — pola prawne. Detal/lista są OperationalUser
    # (R0 2026-07-16): viewer w ogóle nie przechodzi (403).
    resp = await cam_client.get(f"/api/clients/{client_id}", headers=headers)
    if not expected["client_read"]:
        assert resp.status_code == 403, f"[{profile}] client detail should be 403"
    else:
        assert resp.status_code == 200, f"[{profile}] client detail failed"
        body = resp.json()
        if expected["legal_fields"]:
            assert body.get("nip") == "5252530321", f"[{profile}] nip missing"
            assert "legal_name" in body and "notes" in body
        else:
            # Pola NIE występują (nie są null) — kryterium M1-SEC-02.
            for field in ("nip", "regon", "legal_name", "notes"):
                assert field not in body, f"[{profile}] leaked legal field {field}"

    # Finanse w profilu klienta. Endpoint jest OperationalUser (R0) —
    # viewer 403; redakcja finansów przez `_can_see_client_profile_finance`:
    # capability VIEW_FINANCE (Admin; wydzielona Finance nie korzysta
    # z mieszanej powierzchni klienta) ALBO Delivery Lead w granicach
    # własnego portfela — „Obecni konsultanci" to jego obsada, a stawka
    # kosztowa/przychodowa i marża to kolumny tej tabeli.
    #
    # `hor` i `tac` ZOSTAJĄ na False i to nie jest przeoczenie: HoR przechodzi
    # przez guardy klienta globalnie, bez przypisania (repo trzyma go poza
    # finansami), a TAC widzi konsultantów, ale obsady nie prowadzi.
    resp = await cam_client.get(f"/api/clients/{client_id}/profile", headers=headers)
    if not expected["client_read"]:
        assert resp.status_code == 403
    else:
        assert resp.status_code == 200, f"[{profile}] profile failed"
        summary = resp.json()["summary"]
        if expected["financials"]:
            assert summary["active_mrr"] is not None
            assert summary["ltv"] is not None
        else:
            assert summary["active_mrr"] is None, f"[{profile}] leaked active_mrr"
            assert summary["ltv"] is None, f"[{profile}] leaked ltv"


@pytest.mark.asyncio
async def test_delivery_lead_created_client_joins_own_portfolio(
    cam_client: AsyncClient,
) -> None:
    dl_id, email, password = await _seed_user(UserRole.delivery_lead)
    headers = await _login(cam_client, email, password)
    name = f"CAM DL-created {uuid.uuid4().hex[:8]}"

    created = await cam_client.post(
        "/api/clients",
        headers=headers,
        json={"name": name},
    )

    assert created.status_code == 201, created.text
    client_id = created.json()["id"]
    detail = await cam_client.get(f"/api/clients/{client_id}", headers=headers)
    assert detail.status_code == 200, detail.text

    async with AsyncSessionLocal() as db:
        assignment = await db.scalar(
            select(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id == dl_id,
                DeliveryLeadClientAssignment.client_id == client_id,
            )
        )
    assert assignment is not None
    assert assignment.is_head is True


# ── Prywatne notatki relacyjne ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_private_relationship_notes_projection(cam_client: AsyncClient) -> None:
    """`relationship_notes` widzi tylko Admin/owner/Delivery writer; pole nie jest null-owane
    tylko całkiem znika z odpowiedzi."""
    client_id = await _seed_client()
    owner_id, owner_email, owner_pass = await _seed_user(UserRole.delivery_lead)
    await _assign_client(owner_id, client_id, UserRole.delivery_lead)
    await _seed_contact(client_id, owner_id=owner_id, notes="Sekret: urodziny 1 maja")

    # Admin — widzi notatki
    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    admin_headers = await _login(cam_client, admin_email, admin_pass)
    resp = await cam_client.get(
        f"/api/clients/{client_id}/contacts", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()[0].get("relationship_notes") == "Sekret: urodziny 1 maja"

    # Owner (DL) — widzi notatki swojej relacji
    owner_headers = await _login(cam_client, owner_email, owner_pass)
    resp = await cam_client.get(
        f"/api/clients/{client_id}/contacts", headers=owner_headers
    )
    assert resp.status_code == 200
    assert resp.json()[0].get("relationship_notes") == "Sekret: urodziny 1 maja"

    # Inny TAC — pole nie występuje w ogóle
    tac_id, tac_email, tac_pass = await _seed_user(UserRole.tac)
    await _assign_client(tac_id, client_id, UserRole.tac)
    tac_headers = await _login(cam_client, tac_email, tac_pass)
    resp = await cam_client.get(
        f"/api/clients/{client_id}/contacts", headers=tac_headers
    )
    assert resp.status_code == 200
    body = resp.json()[0]
    assert "relationship_notes" not in body, "leaked private notes to non-owner"
    # Pozostałe pola relacyjne (operacyjne) zostają
    assert body["is_key_relationship"] is True

    # TCM reads contacts organization-wide, but never another person's private
    # relationship notes.
    tcm_id, tcm_email, tcm_pass = await _seed_user(UserRole.talent_community_manager)
    await _seed_contact(
        client_id,
        owner_id=tcm_id,
        notes="TCM nie może odczytać nawet własnej notatki prywatnej",
    )
    tcm_headers = await _login(cam_client, tcm_email, tcm_pass)
    resp = await cam_client.get(
        f"/api/clients/{client_id}/contacts", headers=tcm_headers
    )
    assert resp.status_code == 200
    assert all("relationship_notes" not in item for item in resp.json())

    # Recruiter z Jobem u klienta (odczyt operacyjny, bez prawa edycji) —
    # nie widzi także notatek NIE-zaklaimowanych
    r_id, r_email, r_pass = await _seed_user(UserRole.recruiter)
    await _seed_job(client_id, r_id)
    await _seed_contact(client_id, owner_id=None, notes="Niczyje notatki")
    r_headers = await _login(cam_client, r_email, r_pass)
    resp = await cam_client.get(f"/api/clients/{client_id}/contacts", headers=r_headers)
    assert resp.status_code == 200
    for item in resp.json():
        assert "relationship_notes" not in item

    # ...ale przypisany DL widzi nie-zaklaimowane notatki — inaczej
    # KeyRelationshipDialog pokazywałby pustkę i przy zapisie wymazał treść
    resp = await cam_client.get(
        f"/api/clients/{client_id}/contacts", headers=owner_headers
    )
    assert resp.status_code == 200
    unowned = [c for c in resp.json() if c.get("key_relationship_owner_id") is None]
    assert unowned and any(
        c.get("relationship_notes") == "Niczyje notatki" for c in unowned
    )


# ── Reguły właściciela relacji ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_relationship_owner_without_delivery_write_cannot_mutate(
    cam_client: AsyncClient,
) -> None:
    client_id = await _seed_client()
    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    contact_id = await _seed_contact(client_id, owner_id=owner_id)
    headers = await _login(cam_client, owner_email, owner_pass)

    # Ownership does not reopen Delivery for a recruitment-only role.
    resp = await cam_client.put(
        f"/api/contacts/{contact_id}",
        headers=headers,
        json={"relationship_strength": "strong", "relationship_notes": "nowe"},
    )
    assert resp.status_code == 403

    # Pola tożsamościowe — 403
    resp = await cam_client.put(
        f"/api/contacts/{contact_id}",
        headers=headers,
        json={"name": "Zmienione Nazwisko"},
    )
    assert resp.status_code == 403

    # Przepisanie ownera przez samego ownera — 403
    other_id, _, _ = await _seed_user(UserRole.delivery_lead)
    resp = await cam_client.put(
        f"/api/contacts/{contact_id}",
        headers=headers,
        json={"key_relationship_owner_id": other_id},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_reassignment_rules(cam_client: AsyncClient) -> None:
    client_id = await _seed_client()
    owner_id, _, _ = await _seed_user(UserRole.delivery_lead)
    contact_id = await _seed_contact(client_id, owner_id=owner_id)

    # DL (nie-admin) nie może przepisać ownera na kogoś innego
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    await _assign_client(dl_id, client_id, UserRole.delivery_lead)
    dl_headers = await _login(cam_client, dl_email, dl_pass)
    resp = await cam_client.put(
        f"/api/contacts/{contact_id}",
        headers=dl_headers,
        json={"key_relationship_owner_id": dl_id},
    )
    assert resp.status_code == 403

    # Admin może
    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    admin_headers = await _login(cam_client, admin_email, admin_pass)
    resp = await cam_client.put(
        f"/api/contacts/{contact_id}",
        headers=admin_headers,
        json={"key_relationship_owner_id": dl_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["key_relationship_owner_id"] == dl_id

    # Claim pustego ownera na siebie — dozwolony dla roli z prawem edycji
    unowned_contact = await _seed_contact(client_id, owner_id=None, notes=None)
    resp = await cam_client.put(
        f"/api/contacts/{unowned_contact}",
        headers=dl_headers,
        json={"key_relationship_owner_id": dl_id, "is_key_relationship": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["key_relationship_owner_id"] == dl_id


@pytest.mark.asyncio
async def test_contact_delete_matrix(cam_client: AsyncClient) -> None:
    client_id = await _seed_client()

    # Viewer — 403
    contact_id = await _seed_contact(client_id)
    _, v_email, v_pass = await _seed_user(UserRole.user)
    v_headers = await _login(cam_client, v_email, v_pass)
    resp = await cam_client.delete(f"/api/contacts/{contact_id}", headers=v_headers)
    assert resp.status_code == 403

    # Recruiter — 403 (nawet z jobem u klienta zapis jest zabroniony)
    r_id, r_email, r_pass = await _seed_user(UserRole.recruiter)
    await _seed_job(client_id, r_id)
    r_headers = await _login(cam_client, r_email, r_pass)
    resp = await cam_client.delete(f"/api/contacts/{contact_id}", headers=r_headers)
    assert resp.status_code == 403

    # TAC nie ma już sekcji Delivery — 403 nawet przy przypisaniu klienta.
    tac_id, t_email, t_pass = await _seed_user(UserRole.tac)
    await _assign_client(tac_id, client_id, UserRole.tac)
    t_headers = await _login(cam_client, t_email, t_pass)
    resp = await cam_client.delete(f"/api/contacts/{contact_id}", headers=t_headers)
    assert resp.status_code == 403

    # Delivery Lead przypisany do klienta może usunąć kontakt.
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    await _assign_client(dl_id, client_id, UserRole.delivery_lead)
    dl_headers = await _login(cam_client, dl_email, dl_pass)
    resp = await cam_client.delete(f"/api/contacts/{contact_id}", headers=dl_headers)
    assert resp.status_code == 204


# ── Globalna lista kontaktów ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_global_contacts_list_requires_managing_role(
    cam_client: AsyncClient,
) -> None:
    client_id = await _seed_client()
    await _seed_contact(client_id)

    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    unassigned_dl = await _login(cam_client, dl_email, dl_pass)
    denied = await cam_client.get("/api/contacts", headers=unassigned_dl)
    assert denied.status_code == 403

    await _assign_client(dl_id, client_id, UserRole.delivery_lead)
    allowed_dl = await cam_client.get("/api/contacts", headers=unassigned_dl)
    assert allowed_dl.status_code == 200
    assert {row["client_id"] for row in allowed_dl.json()} == {client_id}

    recruiter_id, r_email, r_pass = await _seed_user(UserRole.recruiter)
    r_headers = await _login(cam_client, r_email, r_pass)
    resp = await cam_client.get("/api/contacts", headers=r_headers)
    assert resp.status_code == 403

    await _seed_job(client_id, recruiter_id)
    assigned_recruiter = await cam_client.get("/api/contacts", headers=r_headers)
    assert assigned_recruiter.status_code == 200
    assert {row["client_id"] for row in assigned_recruiter.json()} == {client_id}
    for row in assigned_recruiter.json():
        assert "relationship_notes" not in row

    _, v_email, v_pass = await _seed_user(UserRole.user)
    v_headers = await _login(cam_client, v_email, v_pass)
    resp = await cam_client.get("/api/contacts", headers=v_headers)
    assert resp.status_code == 403


# ── 404 vs 403 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_404_for_missing_client_403_for_denied(
    cam_client: AsyncClient,
) -> None:
    """Brak encji → 404 (istnienie klienta nie jest tajne); brak prawa → 403."""
    _, v_email, v_pass = await _seed_user(UserRole.user)
    v_headers = await _login(cam_client, v_email, v_pass)

    resp = await cam_client.get("/api/clients/99999999/contacts", headers=v_headers)
    assert resp.status_code == 404

    client_id = await _seed_client()
    resp = await cam_client.get(f"/api/clients/{client_id}/contacts", headers=v_headers)
    assert resp.status_code == 403
    # Stabilny kod błędu w detail (kryterium akceptacji PR1)
    assert resp.json()["detail"].startswith("client_access_denied")


# ── Audit events ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contact_mutations_leave_audit_events(
    cam_client: AsyncClient,
) -> None:
    client_id = await _seed_client()
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    await _assign_client(dl_id, client_id, UserRole.delivery_lead)
    headers = await _login(cam_client, dl_email, dl_pass)

    # create
    resp = await cam_client.post(
        "/api/contacts",
        headers=headers,
        json={"client_id": client_id, "name": "Audytowany Kontakt"},
    )
    assert resp.status_code == 201, resp.text
    contact_id = resp.json()["id"]

    # update (pole prywatne — wartość NIE może trafić do audytu)
    resp = await cam_client.put(
        f"/api/contacts/{contact_id}",
        headers=headers,
        json={"relationship_notes": "SEKRETNA-WARTOSC-XYZ"},
    )
    assert resp.status_code == 200, resp.text

    # delete
    resp = await cam_client.delete(f"/api/contacts/{contact_id}", headers=headers)
    assert resp.status_code == 204

    async with AsyncSessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(Activity).where(
                        Activity.entity_type == "client",
                        Activity.entity_id == client_id,
                    )
                )
            ).scalars()
        )
    actions = {a.action for a in rows}
    assert "contact_created" in actions
    assert "contact_updated" in actions
    assert "contact_deleted" in actions
    for a in rows:
        blob = str(a.details)
        assert "SEKRETNA-WARTOSC-XYZ" not in blob, "private value leaked into audit"
    updated = next(a for a in rows if a.action == "contact_updated")
    assert updated.details.get("fields") == ["relationship_notes"]
    assert updated.user_id is not None


@pytest.mark.asyncio
async def test_knowledge_mutations_leave_audit_events(
    cam_client: AsyncClient,
) -> None:
    client_id = await _seed_client()
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    await _assign_client(dl_id, client_id, UserRole.delivery_lead)
    headers = await _login(cam_client, dl_email, dl_pass)

    resp = await cam_client.post(
        f"/api/clients/{client_id}/knowledge",
        headers=headers,
        json={"category": "general", "content": "TAJNA-TRESC-WPISU"},
    )
    assert resp.status_code == 201, resp.text
    knowledge_id = resp.json()["id"]

    resp = await cam_client.delete(
        f"/api/client-knowledge/{knowledge_id}", headers=headers
    )
    assert resp.status_code == 204

    async with AsyncSessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(Activity).where(
                        Activity.entity_type == "client",
                        Activity.entity_id == client_id,
                    )
                )
            ).scalars()
        )
    actions = {a.action for a in rows}
    assert "knowledge_created" in actions
    assert "knowledge_deleted" in actions
    for a in rows:
        assert "TAJNA-TRESC-WPISU" not in str(a.details), (
            "knowledge content leaked into audit"
        )


# ── Multi-role (M1-RBAC-02) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_role_user_gets_union_of_roles(cam_client: AsyncClient) -> None:
    """Hybryda recruiter+DL: primary role = recruiter, ale unia ról daje
    uprawnienia DL — w portalach osobistych i w module klienta."""
    client_id = await _seed_client()
    user_id, email, password = await _seed_user(
        UserRole.recruiter, ["recruiter", "delivery_lead"]
    )
    await _assign_client(user_id, client_id, UserRole.delivery_lead)
    headers = await _login(cam_client, email, password)

    # Moich klientów — przed fixem M1-RBAC-02 hybryda dostawała 403
    resp = await cam_client.get("/api/my-clients", headers=headers)
    assert resp.status_code == 200, resp.text

    # Zapis kontaktu — przechodzi po roli dodatkowej
    resp = await cam_client.post(
        "/api/contacts",
        headers=headers,
        json={"client_id": client_id, "name": "Od hybrydy"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_client_list_projection_per_role(cam_client: AsyncClient) -> None:
    """Lista klientów: pełne pola prawne tylko dla ról z prawem legal;
    viewer w ogóle nie przechodzi (OperationalUser, R0)."""
    await _seed_client()

    _, v_email, v_pass = await _seed_user(UserRole.user)
    v_headers = await _login(cam_client, v_email, v_pass)
    resp = await cam_client.get("/api/clients?page_size=5", headers=v_headers)
    assert resp.status_code == 403

    _, r_email, r_pass = await _seed_user(UserRole.recruiter)
    r_headers = await _login(cam_client, r_email, r_pass)
    resp = await cam_client.get("/api/clients?page_size=5", headers=r_headers)
    assert resp.status_code == 403

    _, tcm_email, tcm_pass = await _seed_user(UserRole.talent_community_manager)
    tcm_headers = await _login(cam_client, tcm_email, tcm_pass)
    resp = await cam_client.get("/api/clients?page_size=5", headers=tcm_headers)
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        for field in ("nip", "regon", "legal_name", "notes"):
            assert field not in item, f"leaked {field} in list for TCM"

    _, a_email, a_pass = await _seed_user(UserRole.admin)
    a_headers = await _login(cam_client, a_email, a_pass)
    resp = await cam_client.get("/api/clients?page_size=5", headers=a_headers)
    assert resp.status_code == 200
    assert any("nip" in item for item in resp.json()["items"])
