"""Runda 9 audytu, obszar CLIENTS (R9-N4-1…9).

Testy bez bazy (schematy, reguła notatek kontaktów, zakres dat) i z bazą
(scalenie, ponowne otwarcie rekrutacji, przypisania). Baza testowa jest
wspólna i nieczyszczona — każdy test zakłada własnych klientów i sprawdza
tylko swoje wiersze. Osoby i firmy są zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

# ── Bez bazy ─────────────────────────────────────────────────────────────────


def test_client_and_contact_schemas_mirror_column_lengths() -> None:
    """R9-N4-5: za długa wartość = 422 (walidacja), nie 500 z bazy."""
    from app.api.client_knowledge import ClientKnowledgeCreate
    from app.api.contacts import ContactCreate, ContactUpdate
    from app.schemas.client import ClientCreate, ClientUpdate

    with pytest.raises(ValidationError):
        ClientCreate(name="x" * 256)
    with pytest.raises(ValidationError):
        ClientCreate(name="Firma", industry="i" * 101)
    with pytest.raises(ValidationError):
        ClientUpdate(nip="1" * 33)
    with pytest.raises(ValidationError):
        ClientUpdate(website="w" * 501)
    with pytest.raises(ValidationError):
        ContactCreate(client_id=1, name="Jan Test", phone="1" * 51)
    with pytest.raises(ValidationError):
        ContactUpdate(email="e" * 256)
    with pytest.raises(ValidationError):
        ClientKnowledgeCreate(category="general", content="x", source="s" * 256)
    # Wartości na granicy przechodzą.
    ClientCreate(name="x" * 255, nip="1" * 32)
    ContactCreate(client_id=1, name="Jan Test", phone="1" * 50)


def test_event_history_rejects_dates_outside_1900_2100() -> None:
    """R9-N4-6: 9999-12-31 przepełniało `date + 1 dzień` → OverflowError 500."""
    from app.api.event_history import _assert_filter_date

    for bad in (date(9999, 12, 31), date(1, 1, 1), date(1899, 12, 31)):
        with pytest.raises(HTTPException) as exc:
            _assert_filter_date(bad, "Data do")
        assert exc.value.status_code == 422
    _assert_filter_date(date(2100, 12, 31), "Data do")
    _assert_filter_date(None, "Data do")


@pytest.mark.asyncio
async def test_global_contact_notes_use_the_per_client_rule(monkeypatch) -> None:
    """R9-N4-2: hybryda HoR+DL nie widzi notatek kontaktów cudzego DL-a.

    ``GET /api/contacts`` liczył „admin-like” bez wyjątku persony DL, więc
    hybryda widziała notatki relacyjne kontaktu klienta spoza portfela, których
    ``GET /clients/{id}/contacts`` (``resolve_client_access``) jej nie dawał.
    Checker listy MUSI dawać tę samą decyzję co reguła per klient.
    """
    from app.models.user import UserRole
    from app.services import client_access as ca

    async def team_ids(db, user, *, purpose="delivery"):
        return frozenset({1})

    async def assigned(user, db):
        return frozenset({1})

    monkeypatch.setattr(ca, "resolve_client_team_client_ids", team_ids)
    monkeypatch.setattr(ca, "resolve_delivery_lead_assigned_client_ids", assigned)
    monkeypatch.setattr(
        ca, "section_access_for_user", lambda user, section: ca.SectionAccess.write
    )
    roles = {UserRole.head_of_recruitment, UserRole.delivery_lead}
    hybrid = SimpleNamespace(
        id=7,
        has_role=lambda role: role in roles,
        has_any_role=lambda *rs: any(r in roles for r in rs),
        get_all_roles=lambda: set(roles),
    )
    monkeypatch.setattr(ca, "has_financial_access", lambda user: False)

    own = SimpleNamespace(client_id=1, key_relationship_owner_id=99)
    foreign = SimpleNamespace(client_id=2, key_relationship_owner_id=99)
    foreign_unowned = SimpleNamespace(client_id=2, key_relationship_owner_id=None)
    mine_elsewhere = SimpleNamespace(client_id=2, key_relationship_owner_id=7)

    check = await ca.contact_private_notes_checker(None, hybrid)
    for contact in (own, foreign, foreign_unowned, mine_elsewhere):
        per_client = await ca.resolve_client_access(None, hybrid, contact.client_id)
        assert check(contact) == per_client.can_view_contact_private_notes(contact)
    assert check(foreign) is False
    assert check(foreign_unowned) is False
    assert check(mine_elsewhere) is True
    assert check(own) is False  # nie jego relacja, a hybryda nie jest admin-like


def test_merge_blockers_know_duplicate_singletons() -> None:
    """R9-N4-3: blokada `duplicate_singletons` jest w ocenie scalenia."""
    import inspect

    from app.services import client_deletion

    source = inspect.getsource(client_deletion.assess_client_merge_blockers)
    assert "_merge_singleton_conflicts" in source
    assert (
        "target_id"
        in inspect.signature(client_deletion.assess_client_merge_blockers).parameters
    )


# ── Z bazą ───────────────────────────────────────────────────────────────────


async def _admin_headers(app_client: AsyncClient) -> dict[str, str]:
    email = app_client.headers.get("X-Test-Admin-Email")
    password = app_client.headers.get("X-Test-Admin-Password")
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user(
    app_client: AsyncClient, *roles: str, active: bool = True
) -> tuple[int, dict[str, str] | None]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"r9-clients-{roles[0]}-{unique}@example.com"
    password = f"P4ss_{unique}!R9"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"R9 {roles[0]} {unique}",
            role=UserRole(roles[0]),
            roles=list(roles),
            is_active=active,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    if not active:
        return user_id, None
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _new_client(tag: str) -> int:
    from tests.test_client_deletion import _client

    return await _client(f"r9-{tag}")


async def _mark(client_id: int, **values) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        row = await db.get(Client, client_id)
        for key, value in values.items():
            setattr(row, key, value)
        await db.commit()


async def _job(client_id: int, status) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"R9 rekrutacja {uuid.uuid4().hex[:6]}",
            client_id=client_id,
            status=status,
        )
        db.add(job)
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_reopening_a_recruitment_of_a_deleted_or_merged_client_is_422(
    app_client: AsyncClient,
):
    """R9-N4-1: ponowne otwarcie (`POST /publish`) sprawdza klienta."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    headers = await _admin_headers(app_client)
    deleted_id = await _new_client("reopen-usuniety")
    job_a = await _job(deleted_id, JobStatus.closed)
    await _mark(deleted_id, deleted_at=datetime.now(timezone.utc))

    # Rekrutacja bez szkiców (04.10.2026): PATCH nie otwiera rekrutacji —
    # „Otwórz ponownie” idzie przez `/publish` z przekazaniem do searchu.
    resp = await app_client.patch(
        f"/api/jobs/{job_a}", json={"status": "published"}, headers=headers
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "reopen_required"

    from tests._job_factory import new_recruiter

    reopen = {"assignment_mode": "manual", "recruiter_id": await new_recruiter()}
    resp = await app_client.post(
        f"/api/jobs/{job_a}/publish", json=reopen, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "client_deleted"

    target_id = await _new_client("reopen-cel")
    merged_id = await _new_client("reopen-scalony")
    job_b = await _job(merged_id, JobStatus.closed)
    await _mark(
        merged_id,
        merged_into_client_id=target_id,
        archived_at=datetime.now(timezone.utc),
    )
    resp = await app_client.post(f"/api/jobs/{job_b}/publish", headers=headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "handoff_required"
    resp = await app_client.post(
        f"/api/jobs/{job_b}/publish", json=reopen, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "client_merged"

    async with AsyncSessionLocal() as db:
        for job_id in (job_a, job_b):
            assert (await db.get(Job, job_id)).status == JobStatus.closed


@pytest.mark.asyncio
async def test_merge_moves_client_knowledge_and_repoints_earlier_duplicates(
    app_client: AsyncClient,
):
    """R9-N4-3/4: kontakty, wiedza, one-pagery, warunki i karta idą na cel;
    duplikat scalony wcześniej w źródło wskazuje od teraz wprost na cel."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_contract_terms import ClientContractTerms
    from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
    from app.models.client_one_pager import ClientOnePager
    from app.models.client_playbook import ClientPlaybook
    from app.models.contact import Contact

    headers = await _admin_headers(app_client)
    earlier = await _new_client("scalenie-wczesniejszy")
    source = await _new_client("scalenie-zrodlo")
    target = await _new_client("scalenie-cel")
    resp = await app_client.post(
        f"/api/clients/{earlier}/merge-into/{source}", headers=headers
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        contact = Contact(client_id=source, name="Anna Zmyślona")
        knowledge = ClientKnowledge(
            client_id=source, category=KnowledgeCategory.general, content="Wiedza"
        )
        pager = ClientOnePager(
            client_id=source, title="One-pager", filename="a.pdf", file_path="x/a.pdf"
        )
        terms = ClientContractTerms(client_id=source, payment_net_days=30)
        playbook = ClientPlaybook(client_id=source, version=1, rate_policy="Zasady")
        db.add_all([contact, knowledge, pager, terms, playbook])
        await db.commit()
        ids = (contact.id, knowledge.id, pager.id, terms.id, playbook.id)

    resp = await app_client.post(
        f"/api/clients/{source}/merge-into/{target}", headers=headers
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        for model, row_id in zip(
            (
                Contact,
                ClientKnowledge,
                ClientOnePager,
                ClientContractTerms,
                ClientPlaybook,
            ),
            ids,
        ):
            assert (await db.get(model, row_id)).client_id == target, model
        assert (await db.get(Client, earlier)).merged_into_client_id == target
        assert (await db.get(Client, source)).merged_into_client_id == target


@pytest.mark.asyncio
async def test_merge_is_blocked_when_both_sides_have_contract_terms(
    app_client: AsyncClient,
):
    """R9-N4-3: jeden wiersz warunków na klienta — o treści decyduje człowiek."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_contract_terms import ClientContractTerms

    headers = await _admin_headers(app_client)
    source = await _new_client("scalenie-warunki-zrodlo")
    target = await _new_client("scalenie-warunki-cel")
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                ClientContractTerms(client_id=source, payment_net_days=30),
                ClientContractTerms(client_id=target, payment_net_days=45),
            ]
        )
        await db.commit()

    resp = await app_client.post(
        f"/api/clients/{source}/merge-into/{target}", headers=headers
    )
    assert resp.status_code == 409, resp.text
    codes = [b["code"] for b in resp.json()["detail"]["blockers"]]
    assert codes == ["duplicate_singletons"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Client, source)).merged_into_client_id is None
        rows = (
            await db.scalars(
                select(ClientContractTerms.client_id).where(
                    ClientContractTerms.client_id.in_((source, target))
                )
            )
        ).all()
        assert sorted(rows) == sorted([source, target])


@pytest.mark.asyncio
async def test_global_contacts_hide_foreign_notes_from_hor_dl_hybrid(
    app_client: AsyncClient,
):
    """R9-N4-2: `/api/contacts` = ta sama projekcja co `/clients/{id}/contacts`.

    Hybryda HoR+DL z klientem w portfelu nie widzi notatek relacji, której
    właścicielem jest INNY Delivery Lead — do rundy 9 globalna lista liczyła
    ją jako „admin-like” (HoR) i oddawała notatki.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.contact import Contact
    from app.models.team_structure import DeliveryLeadClientAssignment

    client_id = await _new_client("kontakty-hybryda")
    owner_id, _ = await _user(app_client, "delivery_lead")
    hybrid_id, hybrid = await _user(app_client, "head_of_recruitment", "delivery_lead")
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=hybrid_id, client_id=client_id
            )
        )
        contact = Contact(
            client_id=client_id,
            name="Zmyślony Kontakt",
            is_key_relationship=True,
            key_relationship_owner_id=owner_id,
            relationship_notes="Prywatna notatka R9",
        )
        db.add(contact)
        await db.commit()
        contact_id = contact.id

    per_client = await app_client.get(
        f"/api/clients/{client_id}/contacts", headers=hybrid
    )
    assert per_client.status_code == 200, per_client.text
    listed = await app_client.get("/api/contacts", headers=hybrid)
    assert listed.status_code == 200, listed.text
    rows = [r for r in listed.json() if r["id"] == contact_id]
    assert rows, "kontakt klienta z portfela musi być na liście"
    per_client_row = next(r for r in per_client.json() if r["id"] == contact_id)
    assert "relationship_notes" not in per_client_row
    assert "relationship_notes" not in rows[0]


@pytest.mark.asyncio
async def test_contact_with_unknown_relationship_owner_is_422(app_client: AsyncClient):
    """R9-N4-5: nieistniejący właściciel relacji szedł do FK → 500."""
    headers = await _admin_headers(app_client)
    client_id = await _new_client("kontakt-wlasciciel")
    resp = await app_client.post(
        "/api/contacts",
        json={
            "client_id": client_id,
            "name": "Zmyślony Kontakt",
            "key_relationship_owner_id": 2_000_000_000,
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    too_long = await app_client.post(
        "/api/contacts",
        json={"client_id": client_id, "name": "Zmyślony", "phone": "1" * 51},
        headers=headers,
    )
    assert too_long.status_code == 422, too_long.text


@pytest.mark.asyncio
async def test_event_history_far_date_is_422(app_client: AsyncClient):
    """R9-N4-6."""
    headers = await _admin_headers(app_client)
    resp = await app_client.get(
        "/api/settings/event-history?date_to=9999-12-31", headers=headers
    )
    assert resp.status_code == 422, resp.text
    ok = await app_client.get(
        "/api/settings/event-history?date_from=2026-01-01", headers=headers
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_hiring_manager_new_person_rejected_for_deleted_client(
    app_client: AsyncClient,
):
    """R9-N4-7: nowa osoba nie zakłada kontaktu usuniętego klienta."""
    from app.core.database import AsyncSessionLocal
    from app.models.contact import Contact
    from app.models.job import JobStatus

    headers = await _admin_headers(app_client)
    client_id = await _new_client("hm-usuniety")
    job_id = await _job(client_id, JobStatus.published)
    await _mark(client_id, deleted_at=datetime.now(timezone.utc))

    resp = await app_client.put(
        f"/api/jobs/{job_id}/hiring-manager",
        json={"new_person": {"name": "Anna Zmyślona"}},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    async with AsyncSessionLocal() as db:
        contacts = (
            await db.scalars(select(Contact).where(Contact.client_id == client_id))
        ).all()
        assert contacts == []


@pytest.mark.asyncio
async def test_cv_rule_save_rejected_for_deleted_client(app_client: AsyncClient):
    """R9-N4-7: reguła CV nie zapisuje się usuniętemu klientowi."""
    headers = await _admin_headers(app_client)
    client_id = await _new_client("regula-usuniety")
    await _mark(client_id, deleted_at=datetime.now(timezone.utc))
    from tests.test_client_cv_rules_recipe_api import _full_payload

    resp = await app_client.put(
        f"/api/clients/{client_id}/cv-rule",
        json={**_full_payload(), "expected_revision": 0},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "client_deleted"


@pytest.mark.asyncio
async def test_dl_client_assignment_guards(app_client: AsyncClient):
    """R9-N4-7: nieistniejący klient 404 (nie FK 500), nieaktywny DL 422,
    usunięty klient 422; ponowne przypisanie jest idempotentne."""
    headers = await _admin_headers(app_client)
    dl_id, _ = await _user(app_client, "delivery_lead")
    inactive_dl, _ = await _user(app_client, "delivery_lead", active=False)
    client_id = await _new_client("dl-przypisanie")
    url = "/api/team-structure/dl-clients"

    missing = await app_client.post(
        url,
        json={"delivery_lead_user_id": dl_id, "client_id": 2_000_000_000},
        headers=headers,
    )
    assert missing.status_code == 404, missing.text
    inactive = await app_client.post(
        url,
        json={"delivery_lead_user_id": inactive_dl, "client_id": client_id},
        headers=headers,
    )
    assert inactive.status_code == 422, inactive.text
    for _ in range(2):
        ok = await app_client.post(
            url,
            json={"delivery_lead_user_id": dl_id, "client_id": client_id},
            headers=headers,
        )
        assert ok.status_code == 201, ok.text

    deleted_id = await _new_client("dl-usuniety")
    await _mark(deleted_id, deleted_at=datetime.now(timezone.utc))
    deleted = await app_client.post(
        url,
        json={"delivery_lead_user_id": dl_id, "client_id": deleted_id},
        headers=headers,
    )
    assert deleted.status_code == 422, deleted.text
