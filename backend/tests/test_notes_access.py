"""Regression tests for Module 6 finding P0.6 (notes global PII exposure).

`GET /api/notes` used to accept no filter and return every note in the company
(unbounded), and the enriched response leaked the author's email. Containment:

- a narrowing filter is required — ``candidate_id``, ``job_id`` or ``note_type``
  (else 400); "dump the whole notes table" is gone,
- the result is bounded (``limit`` capped),
- ``author_email`` is no longer returned (safe identity = ``author_name``),
- the endpoint stays gated by ``CandidatePIIAccess`` (viewer excluded).
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.user import User, UserRole


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"m6notes-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!M6"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"M6 notes {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Candidate(name=f"Cand{unique}", lastname="Notes", email=f"{unique}@x.com")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_list_requires_a_narrowing_filter(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    resp = await app_client.get("/api/notes", headers=app_auth_headers)
    assert resp.status_code == 400

    cand_id = await _seed_candidate()
    ok = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=app_auth_headers
    )
    assert ok.status_code == 200

    # note_type filter alone is accepted (Champion "unlinked meetings" path).
    ok_type = await app_client.get(
        "/api/notes", params={"note_type": "meeting"}, headers=app_auth_headers
    )
    assert ok_type.status_code == 200


@pytest.mark.asyncio
async def test_author_email_is_redacted(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    cand_id = await _seed_candidate()
    created = await app_client.post(
        "/api/notes",
        headers=app_auth_headers,
        json={"content": "prywatna notatka", "candidate_id": cand_id},
    )
    assert created.status_code == 201, created.text

    listed = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=app_auth_headers
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) >= 1
    for item in items:
        assert item["author_email"] is None  # redacted
    # the safe identity is still present
    assert any(item.get("author_name") for item in items)


@pytest.mark.asyncio
async def test_viewer_cannot_list_notes(app_client: AsyncClient):
    cand_id = await _seed_candidate()
    v_email, v_pass = await _seed_user(UserRole.user)
    v_headers = await _login(app_client, v_email, v_pass)
    resp = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=v_headers
    )
    assert resp.status_code == 403


# ── Źródła AI Championa: „Meetingi bez powiązania” (UAT M03-B13 / M04-B04) ──
#
# Lista brała każdą notatkę „meeting” — także rozmowy z kandydatami innych
# klientów z importu Traffita — z przyciskiem „Powiąż + AI” na dowolnej
# rekrutacji. Podpięcie przenosiło notatkę i karmiło jej treścią Championa roli
# innego klienta.


async def _seed_job_for_notes() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"NotesClient-{unique}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Rola {unique}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_meeting_note(
    *, candidate_id: int | None = None, job_id: int | None = None
) -> int:
    from app.models.note import Note, NoteType

    async with AsyncSessionLocal() as db:
        note = Note(
            content=f"# Spotkanie {uuid.uuid4().hex[:6]}",
            note_type=NoteType.meeting,
            candidate_id=candidate_id,
            job_id=job_id,
        )
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return note.id


@pytest.mark.asyncio
async def test_unattached_meetings_exclude_candidate_and_job_notes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    cand_id = await _seed_candidate()
    job_id = await _seed_job_for_notes()
    free_id = await _seed_meeting_note()
    cand_note_id = await _seed_meeting_note(candidate_id=cand_id)
    job_note_id = await _seed_meeting_note(job_id=job_id)

    resp = await app_client.get(
        "/api/notes",
        params={"note_type": "meeting", "unattached": "true", "limit": 2000},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert free_id in ids
    assert cand_note_id not in ids
    assert job_note_id not in ids
    assert all(
        item["candidate_id"] is None and item["job_id"] is None
        for item in resp.json()["items"]
    )


@pytest.mark.asyncio
async def test_link_job_refuses_candidate_note_outside_the_pipeline(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.models.note import Note

    cand_id = await _seed_candidate()
    job_id = await _seed_job_for_notes()
    note_id = await _seed_meeting_note(candidate_id=cand_id)

    resp = await app_client.post(
        f"/api/notes/{note_id}/link-job",
        json={"job_id": job_id},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "nie jest w pipeline" in resp.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Note, note_id)).job_id is None


@pytest.mark.asyncio
async def test_link_job_refuses_note_attached_to_another_recruitment(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.models.note import Note

    other_job_id = await _seed_job_for_notes()
    job_id = await _seed_job_for_notes()
    note_id = await _seed_meeting_note(job_id=other_job_id)

    resp = await app_client.post(
        f"/api/notes/{note_id}/link-job",
        json={"job_id": job_id},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Note, note_id)).job_id == other_job_id
