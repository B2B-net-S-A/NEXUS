"""Notatki i czaty — runda 10 audytu (Postgres, trasy HTTP).

R10-N6-1  usunięta notatka z Traffita nie wraca przy syncu (nagrobek 0391),
R10-N6-2  usunięcie jedynej notatki czyści fakty i stawkę wpisaną z notatek,
R10-N6-3  usunięta/poprawiona treść nie zostaje w powiadomieniach,
R10-N6-5..8  walidacja wejścia /api/notes (422/404 zamiast 500 i pełnej listy),
R10-N6-9  szukanie w czacie pomija usunięte wiadomości,
R10-N6-10 wzmianka dopisana przy edycji wiadomości czatu powiadamia.

Wspólna baza CI: każda asercja filtruje po własnych danych.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.note import Note, NoteType
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.mention_dispatch import (
    CHAT_DELETED_PLACEHOLDER,
    NOTE_DELETED_PLACEHOLDER,
)
from app.services.traffit.importer import TraffitImporter

pytestmark = pytest.mark.asyncio


async def _new_user(db, role: UserRole) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    u = User(
        email=f"r10n-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"R10 {role.value} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u, pwd


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def ctx(app_client: AsyncClient) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        author, author_pwd = await _new_user(db, UserRole.recruiter)
        peer, _ = await _new_user(db, UserRole.recruiter)
        admin, admin_pwd = await _new_user(db, UserRole.admin)
        client = Client(name=f"R10 Client {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"R10 Job {uuid.uuid4().hex[:6]}",
            client_id=client.id,
            recruiter_id=author.id,
            status=JobStatus.published,
        )
        db.add(job)
        await db.flush()
        db.add(
            JobCollaborator(
                job_id=job.id,
                user_id=peer.id,
                added_by=author.id,
                source=JobCollaboratorSource.manual,
            )
        )
        candidate = Candidate(
            name=f"R10{uuid.uuid4().hex[:6]}",
            lastname="Notes",
            email=f"r10-{uuid.uuid4().hex[:8]}@x.com",
        )
        db.add(candidate)
        await db.commit()
        return {
            "author_id": author.id,
            "author_email": author.email,
            "author_password": author_pwd,
            "peer_id": peer.id,
            "peer_email": peer.email,
            "admin_email": admin.email,
            "admin_password": admin_pwd,
            "job_id": job.id,
            "candidate_id": candidate.id,
        }


async def _author(app_client, ctx) -> dict[str, str]:
    return await _login(app_client, ctx["author_email"], ctx["author_password"])


async def _notifications(user_id: int, link: str) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Notification).where(
                Notification.user_id == user_id, Notification.link == link
            )
        )
        return list(rows.scalars().all())


# ── R10-N6-3 / N6-10 / N6-9: czat rekrutacji ────────────────────────────────


async def test_deleted_job_chat_message_leaves_no_snippet(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    job_id = ctx["job_id"]
    created = await app_client.post(
        f"/api/jobs/{job_id}/chat/messages",
        headers=headers,
        json={"content": f"stawka do klienta 199 zł @{ctx['peer_email']}"},
    )
    assert created.status_code == 201, created.text
    msg_id = created.json()["id"]
    link = f"/jobs/{job_id}?tab=chat&msg={msg_id}"
    before = await _notifications(ctx["peer_id"], link)
    assert {n.notification_type for n in before} == {
        NotificationType.job_chat_message,
        NotificationType.job_chat_mention,
    }
    # Jedno powiadomienie już poszło mailem — zostaje jako ślad wysyłki.
    sent_id = next(
        n.id for n in before if n.notification_type == NotificationType.job_chat_message
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Notification)
            .where(Notification.id == sent_id)
            .values(email_sent_at=datetime.now(timezone.utc))
        )
        await db.commit()

    deleted = await app_client.delete(
        f"/api/jobs/{job_id}/chat/messages/{msg_id}", headers=headers
    )
    assert deleted.status_code == 204

    after = await _notifications(ctx["peer_id"], link)
    assert [n.id for n in after] == [sent_id]
    assert after[0].is_read is True
    assert after[0].message == CHAT_DELETED_PLACEHOLDER


async def test_edited_job_chat_message_refreshes_snippet_and_notifies_new_mention(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    job_id = ctx["job_id"]
    created = await app_client.post(
        f"/api/jobs/{job_id}/chat/messages",
        headers=headers,
        json={"content": "wersja pierwsza z literówką"},
    )
    msg_id = created.json()["id"]
    link = f"/jobs/{job_id}?tab=chat&msg={msg_id}"

    patched = await app_client.patch(
        f"/api/jobs/{job_id}/chat/messages/{msg_id}",
        headers=headers,
        json={"content": f"wersja druga @{ctx['peer_email']}"},
    )
    assert patched.status_code == 200, patched.text

    rows = await _notifications(ctx["peer_id"], link)
    by_type = {n.notification_type: n for n in rows}
    assert NotificationType.job_chat_mention in by_type
    for n in rows:
        assert "wersja druga" in n.message
        assert "pierwsza" not in n.message


async def test_job_chat_search_skips_deleted_messages(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    job_id = ctx["job_id"]
    word = f"tajne{uuid.uuid4().hex[:8]}"
    created = await app_client.post(
        f"/api/jobs/{job_id}/chat/messages",
        headers=headers,
        json={"content": f"pesel {word}"},
    )
    msg_id = created.json()["id"]
    await app_client.delete(
        f"/api/jobs/{job_id}/chat/messages/{msg_id}", headers=headers
    )
    found = await app_client.get(
        f"/api/jobs/{job_id}/chat/messages?search={word}", headers=headers
    )
    assert found.status_code == 200
    assert found.json()["items"] == []


# ── R10-N6-3 / N6-9: czat kandydata ─────────────────────────────────────────


async def test_deleted_candidate_chat_message_is_withdrawn(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    cid = ctx["candidate_id"]
    word = f"poufne{uuid.uuid4().hex[:8]}"
    created = await app_client.post(
        f"/api/candidates/{cid}/chat/messages",
        headers=headers,
        json={"content": f"stawka {word}"},
    )
    assert created.status_code == 201, created.text
    msg_id = created.json()["id"]
    link = f"/candidates/{cid}?tab=chat&msg={msg_id}"
    # Odbiorca niezależny od reguły członkostwa czatu kandydata.
    async with AsyncSessionLocal() as db:
        db.add(
            Notification(
                user_id=ctx["peer_id"],
                title="nowa wiadomość o kandydacie",
                message=f"stawka {word}",
                link=link,
                notification_type=NotificationType.job_chat_message,
                related_entity_type="candidate_chat_message",
            )
        )
        await db.commit()

    deleted = await app_client.delete(
        f"/api/candidates/{cid}/chat/messages/{msg_id}", headers=headers
    )
    assert deleted.status_code == 204
    assert await _notifications(ctx["peer_id"], link) == []

    found = await app_client.get(
        f"/api/candidates/{cid}/chat/messages?search={word}", headers=headers
    )
    assert found.status_code == 200
    assert found.json()["items"] == []


# ── R10-N6-5..8: walidacja /api/notes ───────────────────────────────────────


async def test_notes_list_rejects_zero_ids_and_unknown_type(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    for query in ("candidate_id=0", "job_id=0", "note_type=xyz"):
        resp = await app_client.get(f"/api/notes?{query}", headers=headers)
        assert resp.status_code == 422, (query, resp.status_code)


async def test_note_create_with_missing_subject_is_404(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    for body in ({"candidate_id": 2_000_000_000}, {"job_id": 2_000_000_000}):
        resp = await app_client.post(
            "/api/notes", headers=headers, json={"content": "x", **body}
        )
        assert resp.status_code == 404, (body, resp.text)


async def test_note_patch_with_null_is_422(app_client: AsyncClient, ctx) -> None:
    headers = await _author(app_client, ctx)
    created = await app_client.post(
        "/api/notes",
        headers=headers,
        json={"content": "treść", "candidate_id": ctx["candidate_id"]},
    )
    note_id = created.json()["id"]
    for body in ({"content": None}, {"note_type": None}):
        resp = await app_client.patch(
            f"/api/notes/{note_id}", headers=headers, json=body
        )
        assert resp.status_code == 422, (body, resp.text)


# ── R10-N6-3: wzmianka w usuniętej notatce ──────────────────────────────────


async def test_deleted_note_withdraws_mention_snippet(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    created = await app_client.post(
        "/api/notes",
        headers=headers,
        json={
            "content": f"@{ctx['peer_email']} kandydat chce 250 zł/h",
            "candidate_id": ctx["candidate_id"],
        },
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(Notification).where(
                        Notification.notification_type == NotificationType.note_mention,
                        Notification.related_entity_id == note_id,
                        Notification.user_id == ctx["peer_id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1

    resp = await app_client.delete(f"/api/notes/{note_id}", headers=headers)
    assert resp.status_code == 204
    async with AsyncSessionLocal() as db:
        row = await db.get(Notification, rows[0].id)
    assert row.is_read is True
    assert row.message == NOTE_DELETED_PLACEHOLDER


# ── R10-N6-2: fakty z usuniętej notatki ─────────────────────────────────────


async def _seed_notes_facts(candidate_id: int) -> None:
    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, candidate_id)
        cand.expected_rate_hourly = Decimal("180.00")
        cand.expected_rate_currency = "PLN"
        cand.profile_rate_version = 5
        cand.cv_extracted_data = {
            "_notes_insights": {
                "expected_rate": {"value": 180, "currency": "PLN", "period": "h"},
                "_extracted_at": "2026-09-01T02:00:00+00:00",
                "_v2_extracted_at": "2026-09-01T02:00:00+00:00",
                "_rate_written": {"amount": "180.00", "currency": "PLN", "version": 5},
            }
        }
        await db.commit()


async def test_deleting_the_only_note_clears_notes_facts_and_rate(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    cid = ctx["candidate_id"]
    created = await app_client.post(
        "/api/notes",
        headers=headers,
        json={"content": "stawka 180 zł/h", "candidate_id": cid},
    )
    await _seed_notes_facts(cid)

    resp = await app_client.delete(
        f"/api/notes/{created.json()['id']}", headers=headers
    )
    assert resp.status_code == 204
    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, cid)
    assert cand.expected_rate_hourly is None
    assert "_notes_insights" not in (cand.cv_extracted_data or {})

    facts = await app_client.get(f"/api/candidates/{cid}/notes-facts", headers=headers)
    if facts.status_code == 200:
        assert facts.json()["rate"] is None


async def test_deleting_one_of_several_notes_marks_facts_for_refresh(
    app_client: AsyncClient, ctx
) -> None:
    headers = await _author(app_client, ctx)
    cid = ctx["candidate_id"]
    first = await app_client.post(
        "/api/notes",
        headers=headers,
        json={"content": "stawka 180", "candidate_id": cid},
    )
    await app_client.post(
        "/api/notes", headers=headers, json={"content": "druga", "candidate_id": cid}
    )
    await _seed_notes_facts(cid)

    await app_client.delete(f"/api/notes/{first.json()['id']}", headers=headers)
    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, cid)
    insights = cand.cv_extracted_data["_notes_insights"]
    assert insights.get("_notes_changed_at")
    # Stawkę rozstrzygnie nocna ekstrakcja z pozostałych notatek.
    assert cand.expected_rate_hourly == Decimal("180.00")


# ── R10-N6-1: nagrobek notatki z Traffita ───────────────────────────────────


async def _mk_activity(candidate_id: int, *, ext: str, at: datetime) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                INSERT INTO activities (
                    external_id, external_source, action, entity_type,
                    entity_id, details, created_at, updated_at
                ) VALUES (
                    :ext, 'traffit', 'traffit:Notatka', 'candidate', :cid,
                    CAST('{"content": "notatka z Traffita"}' AS jsonb), :at, :at
                )
                """
            ),
            {"ext": ext, "cid": candidate_id, "at": at},
        )
        await db.commit()


async def _promote() -> None:
    async with AsyncSessionLocal() as db:
        await TraffitImporter(object(), db, dry_run=False).promote_notes()


async def _candidate_notes(candidate_id: int) -> list[Note]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(Note).where(Note.candidate_id == candidate_id))
        return list(rows.scalars().all())


async def test_deleted_traffit_note_is_not_promoted_again(
    app_client: AsyncClient, ctx
) -> None:
    admin = await _login(app_client, ctx["admin_email"], ctx["admin_password"])
    cid = ctx["candidate_id"]
    await _mk_activity(
        cid, ext=f"r10-{uuid.uuid4().hex[:10]}", at=datetime.now(timezone.utc)
    )
    await _promote()
    notes = await _candidate_notes(cid)
    assert len(notes) == 1 and notes[0].source_ref.startswith("traffit:activity:")

    resp = await app_client.delete(f"/api/notes/{notes[0].id}", headers=admin)
    assert resp.status_code == 204
    await _promote()
    assert await _candidate_notes(cid) == []


async def test_deleted_0077_note_without_source_ref_is_not_promoted_again(
    app_client: AsyncClient, ctx
) -> None:
    admin = await _login(app_client, ctx["admin_email"], ctx["admin_password"])
    cid = ctx["candidate_id"]
    at = datetime.now(timezone.utc).replace(microsecond=0)
    await _mk_activity(cid, ext=f"r10-{uuid.uuid4().hex[:10]}", at=at)
    # Notatka z migracji 0077: bez `source_ref`, dopasowana po znaczniku czasu.
    async with AsyncSessionLocal() as db:
        note = Note(
            candidate_id=cid,
            content="notatka z Traffita",
            note_type=NoteType.general,
            created_at=at,
            updated_at=at,
        )
        db.add(note)
        await db.commit()
        note_id = note.id
    await _promote()
    assert [n.id for n in await _candidate_notes(cid)] == [note_id]

    resp = await app_client.delete(f"/api/notes/{note_id}", headers=admin)
    assert resp.status_code == 204
    await _promote()
    assert await _candidate_notes(cid) == []
