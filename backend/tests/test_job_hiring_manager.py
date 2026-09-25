"""Hiring manager rekrutacji: wybór z listy albo nowa osoba (25.09.2026).

Decyzja Artura: osobę wpisuje każdy, kto redaguje rekrutację (także rekruter),
a serwis zakłada ją jako kontakt KLIENTA tej rekrutacji — po dopasowaniu do
istniejących kontaktów, bo weto HM dopasowuje rekrutacje po id kontaktu.

In-process `app_client`; baza testowa wspólna i nieczyszczona — asercje tylko
na własnych wierszach (uuid).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services.job_hiring_manager import name_key, pick_matching_contact


# ── Reguła dopasowania (bez bazy) ─────────────────────────────────────────────


def test_name_key_ignores_order_case_and_polish_letters() -> None:
    assert name_key("Łukasz Żółć") == name_key("zolc  lukasz")
    assert name_key("Anna Nowak-Kowalska") == name_key("nowak-kowalska anna")
    assert name_key("Anna Nowak") != name_key("Anna Nowak-Kowalska")


def test_pick_matching_contact_prefers_name_then_email_and_lowest_id() -> None:
    contacts = [
        SimpleNamespace(id=9, name="Jan Kowalski", email=None),
        SimpleNamespace(id=4, name="KOWALSKI Jan", email="x@firma.pl"),
        SimpleNamespace(id=7, name="Ewa Mazur", email="ewa@firma.pl"),
    ]
    assert pick_matching_contact(contacts, name="jan kowalski", email=None).id == 4
    assert pick_matching_contact(contacts, name="E. M.", email="EWA@firma.pl").id == 7
    assert pick_matching_contact(contacts, name="Adam Nowy", email=None) is None
    # Samo imię nie wystarcza — „Jan” to nie „Jan Kowalski”.
    assert pick_matching_contact(contacts, name="Jan", email=None) is None


def test_request_body_needs_exactly_one_choice() -> None:
    from pydantic import ValidationError

    from app.schemas.job import JobHiringManagerRequest

    JobHiringManagerRequest(contact_id=1)
    JobHiringManagerRequest(new_person={"name": "Jan Kowalski", "email": ""})
    JobHiringManagerRequest(clear=True)
    for body in ({}, {"contact_id": 1, "clear": True}):
        with pytest.raises(ValidationError):
            JobHiringManagerRequest(**body)


def test_intake_keeps_hiring_manager_only_as_quotes() -> None:
    from app.services.job_request_intake import normalize_model_output

    text = (
        "Szukamy Java Developera.\n\nPozdrawiam\nAnna Nowak\n"
        "Kierownik Zespołu Rozwoju\nanna.nowak@bank.pl"
    )
    quoted = normalize_model_output(
        {
            "hiring_manager_name": "Anna Nowak",
            "hiring_manager_position": "Kierownik Zespołu Rozwoju",
            "hiring_manager_email": "anna.nowak@bank.pl",
        },
        text,
    )
    assert quoted.hiring_manager_name == "Anna Nowak"
    assert quoted.hiring_manager_position == "Kierownik Zespołu Rozwoju"
    assert quoted.hiring_manager_email == "anna.nowak@bank.pl"
    assert quoted.provenance["hiring_manager"] == "request"

    invented = normalize_model_output(
        {
            "hiring_manager_name": "Piotr Zmyślony",
            "hiring_manager_position": "Kierownik Zespołu Rozwoju",
        },
        text,
    )
    assert invented.hiring_manager_name is None
    # Stanowisko bez osoby nie ma kogo opisać.
    assert invented.hiring_manager_position is None
    assert "hiring_manager" not in invented.provenance


# ── API ──────────────────────────────────────────────────────────────────────


async def _seed_user(app_client: AsyncClient, *roles: str) -> dict:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"job-hm-{roles[0]}-{unique}@example.com"
    password = f"T3st_{unique}!Hm"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"HM {roles[0]}",
                role=UserRole(roles[0]),
                roles=list(roles),
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_world() -> dict:
    from app.models.client import Client
    from app.models.contact import Contact
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"HmClient-{tag}")
        other = Client(name=f"HmOther-{tag}")
        db.add_all([client, other])
        await db.flush()
        known = Contact(client_id=client.id, name=f"Jan Kowalski{tag}")
        foreign = Contact(client_id=other.id, name=f"Obcy Kontakt{tag}")
        db.add_all([known, foreign])
        await db.flush()
        job = Job(
            title=f"HmJob-{tag}",
            description="Opis",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        return {
            "tag": tag,
            "client_id": client.id,
            "other_client_id": other.id,
            "known_id": known.id,
            "foreign_id": foreign.id,
            "job_id": job.id,
        }


async def _client_contacts(client_id: int) -> list:
    from app.models.contact import Contact

    async with AsyncSessionLocal() as db:
        return list(
            (await db.execute(select(Contact).where(Contact.client_id == client_id)))
            .scalars()
            .all()
        )


async def _activities(entity_type: str, entity_id: int, action: str) -> list:
    from app.models.activity import Activity

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(Activity).where(
                        Activity.entity_type == entity_type,
                        Activity.entity_id == entity_id,
                        Activity.action == action,
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_recruiter_adds_a_new_person_without_duplicates(app_client):
    world = await _seed_world()
    recruiter = await _seed_user(app_client, "recruiter")
    url = f"/api/jobs/{world['job_id']}/hiring-manager"
    name = f"Anna Nowak{world['tag']}"

    resp = await app_client.put(
        url,
        headers=recruiter,
        json={"new_person": {"name": name, "position": "Kierownik"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hiring_manager_name"] == name
    created_id = body["hiring_manager_contact_id"]

    contacts = await _client_contacts(world["client_id"])
    assert [c.id for c in contacts if c.id == created_id]
    created = next(c for c in contacts if c.id == created_id)
    assert created.position == "Kierownik"
    audits = await _activities("client", world["client_id"], "contact_created")
    assert any(
        (a.details or {}).get("contact_id") == created_id
        and (a.details or {}).get("source") == "job_hiring_manager"
        for a in audits
    )
    changes = await _activities("job", world["job_id"], "hiring_manager_changed")
    assert changes and changes[-1].details["contact_created"] is True

    # Ta sama osoba wpisana inaczej → ten sam kontakt, e-mail uzupełniony.
    again = await app_client.put(
        url,
        headers=recruiter,
        json={
            "new_person": {
                "name": f"  {name.split()[1].upper()}   anna ",
                "position": "Inne stanowisko",
                "email": f"anna{world['tag']}@bank.pl",
            }
        },
    )
    assert again.status_code == 200, again.text
    assert again.json()["hiring_manager_contact_id"] == created_id
    after = {c.id: c for c in await _client_contacts(world["client_id"])}
    assert len(after) == len(contacts)
    # Fill-only: stanowisko zostaje, pusty e-mail dostaje wartość.
    assert after[created_id].position == "Kierownik"
    assert after[created_id].email == f"anna{world['tag']}@bank.pl"


@pytest.mark.asyncio
async def test_existing_contact_other_client_and_clear(app_client):
    world = await _seed_world()
    recruiter = await _seed_user(app_client, "recruiter")
    url = f"/api/jobs/{world['job_id']}/hiring-manager"

    ok = await app_client.put(
        url, headers=recruiter, json={"contact_id": world["known_id"]}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["hiring_manager_contact_id"] == world["known_id"]

    foreign = await app_client.put(
        url, headers=recruiter, json={"contact_id": world["foreign_id"]}
    )
    assert foreign.status_code == 422, foreign.text

    cleared = await app_client.put(url, headers=recruiter, json={"clear": True})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["hiring_manager_contact_id"] is None


@pytest.mark.asyncio
async def test_viewer_is_denied_and_one_word_is_not_a_person(app_client):
    world = await _seed_world()
    recruiter = await _seed_user(app_client, "recruiter")
    viewer = await _seed_user(app_client, "user")
    url = f"/api/jobs/{world['job_id']}/hiring-manager"

    denied = await app_client.put(
        url, headers=viewer, json={"new_person": {"name": "Jan Kowalski"}}
    )
    assert denied.status_code == 403, denied.text

    one_word = await app_client.put(
        url, headers=recruiter, json={"new_person": {"name": "Jan"}}
    )
    assert one_word.status_code == 422, one_word.text


@pytest.mark.asyncio
async def test_patch_and_create_reject_a_contact_of_another_client(
    app_client, app_auth_headers
):
    world = await _seed_world()
    patch = await app_client.patch(
        f"/api/jobs/{world['job_id']}",
        headers=app_auth_headers,
        json={"hiring_manager_contact_id": world["foreign_id"]},
    )
    assert patch.status_code == 422, patch.text

    create = await app_client.post(
        "/api/jobs",
        headers=app_auth_headers,
        json={
            "title": f"HmCreate-{world['tag']}",
            "description": "Opis",
            "client_id": world["client_id"],
            "hiring_manager_contact_id": world["foreign_id"],
        },
    )
    assert create.status_code == 422, create.text


@pytest.mark.asyncio
async def test_changing_the_client_drops_the_old_hiring_manager(
    app_client, app_auth_headers
):
    world = await _seed_world()
    set_hm = await app_client.put(
        f"/api/jobs/{world['job_id']}/hiring-manager",
        headers=app_auth_headers,
        json={"contact_id": world["known_id"]},
    )
    assert set_hm.status_code == 200, set_hm.text

    moved = await app_client.patch(
        f"/api/jobs/{world['job_id']}",
        headers=app_auth_headers,
        json={"client_id": world["other_client_id"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["hiring_manager_contact_id"] is None


@pytest.mark.asyncio
async def test_options_are_a_narrow_projection(app_client):
    world = await _seed_world()
    recruiter = await _seed_user(app_client, "recruiter")
    resp = await app_client.get(
        "/api/jobs/hiring-manager-options",
        headers=recruiter,
        params={"client_id": world["client_id"]},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["id"] for r in rows] == [world["known_id"]]
    assert set(rows[0]) == {"id", "name", "position"}


@pytest.mark.asyncio
async def test_intake_points_at_the_existing_contact():
    from app.services.job_request_intake import (
        match_hiring_manager,
        normalize_model_output,
    )

    world = await _seed_world()
    name = f"kowalski{world['tag']} jan"
    intake = normalize_model_output(
        {"hiring_manager_name": name}, f"Pozdrawiam, {name}"
    )
    async with AsyncSessionLocal() as db:
        matched = await match_hiring_manager(
            db, client_id=world["client_id"], intake=intake
        )
        other = await match_hiring_manager(
            db, client_id=world["other_client_id"], intake=intake
        )
    assert matched.hiring_manager_contact_id == world["known_id"]
    assert other.hiring_manager_contact_id is None
