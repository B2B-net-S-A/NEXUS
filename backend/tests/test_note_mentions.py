"""Integration tests dla @mention w notatkach (Note).

Pokrywa scenariusze:
    1. parse_mentions_global_finds_user
    2. parse_mentions_global_skips_inactive
    3. post_note_creates_mention_and_notification
    4. post_note_sends_email_when_smtp_enabled
    5. post_note_does_not_email_self
    6. patch_note_only_emails_new_mentions
    7. post_note_with_job_filters_to_members
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.note_mention import NoteMention
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.mention_parser import parse_mentions_global


pytestmark = pytest.mark.asyncio


async def _new_user(db, role: UserRole, *, is_active: bool = True) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    u = User(
        email=f"note-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Note {role.value} {suffix}",
        role=role,
        is_active=is_active,
    )
    db.add(u)
    await db.flush()
    return u, pwd


async def _new_candidate(db) -> Candidate:
    suffix = uuid.uuid4().hex[:8]
    c = Candidate(
        name=f"Cand{suffix}",
        lastname="Test",
        email=f"cand-{suffix}@x.com",
    )
    db.add(c)
    await db.flush()
    return c


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def setup_users(app_client: AsyncClient) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        author, author_pwd = await _new_user(db, UserRole.recruiter)
        target, _ = await _new_user(db, UserRole.delivery_lead)
        inactive, _ = await _new_user(db, UserRole.recruiter, is_active=False)
        candidate = await _new_candidate(db)
        await db.commit()
        return {
            "author_id": author.id,
            "author_email": author.email,
            "author_password": author_pwd,
            "target_id": target.id,
            "target_email": target.email,
            "inactive_email": inactive.email,
            "candidate_id": candidate.id,
        }


# ── Unit: parse_mentions_global ─────────────────────────────────────────────


async def test_parse_mentions_global_finds_user(setup_users):
    target_email = setup_users["target_email"]
    target_id = setup_users["target_id"]
    async with AsyncSessionLocal() as db:
        ids = await parse_mentions_global(
            db, f"sprawdź ten case @{target_email} dzięki"
        )
    assert ids == [target_id]


async def test_parse_mentions_global_skips_inactive(setup_users):
    """Inactive user nie pojawia się w wynikach mention."""
    inactive_email = setup_users["inactive_email"]
    async with AsyncSessionLocal() as db:
        ids = await parse_mentions_global(db, f"hej @{inactive_email}")
    assert ids == []


# ── Integration: POST /api/notes ────────────────────────────────────────────


async def test_post_note_creates_mention_and_notification(
    app_client: AsyncClient, setup_users
):
    headers = await _login(
        app_client, setup_users["author_email"], setup_users["author_password"]
    )
    target_email = setup_users["target_email"]
    target_id = setup_users["target_id"]
    candidate_id = setup_users["candidate_id"]

    resp = await app_client.post(
        "/api/notes",
        headers=headers,
        json={
            "content": f"Hey @{target_email} sprawdź proszę tego kandydata",
            "note_type": "general",
            "candidate_id": candidate_id,
        },
    )
    assert resp.status_code == 201, resp.text
    note_id = resp.json()["id"]

    async with AsyncSessionLocal() as db:
        mentions = (
            (
                await db.execute(
                    select(NoteMention).where(NoteMention.note_id == note_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(mentions) == 1
        assert mentions[0].user_id == target_id

        notifs = (
            (
                await db.execute(
                    select(Notification)
                    .where(Notification.user_id == target_id)
                    .where(
                        Notification.notification_type == NotificationType.note_mention
                    )
                    .where(Notification.related_entity_id == note_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(notifs) == 1
        assert notifs[0].related_entity_type == "note"


async def test_post_note_does_not_email_self(app_client: AsyncClient, setup_users):
    """Author oznacza siebie → 0 NoteMention rows."""
    headers = await _login(
        app_client, setup_users["author_email"], setup_users["author_password"]
    )
    author_email = setup_users["author_email"]
    candidate_id = setup_users["candidate_id"]

    with patch("smtplib.SMTP") as smtp_mock:
        resp = await app_client.post(
            "/api/notes",
            headers=headers,
            json={
                "content": f"My own note with @{author_email} self-mention",
                "note_type": "general",
                "candidate_id": candidate_id,
            },
        )
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    async with AsyncSessionLocal() as db:
        mentions = (
            (
                await db.execute(
                    select(NoteMention).where(NoteMention.note_id == note_id)
                )
            )
            .scalars()
            .all()
        )
    assert mentions == []
    smtp_mock.assert_not_called()


async def test_post_note_sends_email_when_smtp_enabled(
    app_client: AsyncClient, setup_users, monkeypatch
):
    """Z włączonym SMTP — smtplib.SMTP zostaje wywołane raz."""
    from app.services import email as email_module

    monkeypatch.setattr(email_module.settings, "SMTP_ENABLED", True)
    monkeypatch.setattr(email_module.settings, "SMTP_HOST", "smtp.test.local")

    headers = await _login(
        app_client, setup_users["author_email"], setup_users["author_password"]
    )

    with patch("app.services.email.smtplib.SMTP") as smtp_cls:
        instance = smtp_cls.return_value.__enter__.return_value
        resp = await app_client.post(
            "/api/notes",
            headers=headers,
            json={
                "content": f"Pilne @{setup_users['target_email']} zerknij",
                "note_type": "general",
                "candidate_id": setup_users["candidate_id"],
            },
        )
    assert resp.status_code == 201
    assert smtp_cls.called, "smtplib.SMTP powinien być wywołany"
    instance.send_message.assert_called_once()


async def test_patch_note_only_emails_new_mentions(
    app_client: AsyncClient, setup_users, monkeypatch
):
    """PATCH dodający nowy mention emaila tylko dla *nowego* usera."""
    from app.services import email as email_module

    monkeypatch.setattr(email_module.settings, "SMTP_ENABLED", True)
    monkeypatch.setattr(email_module.settings, "SMTP_HOST", "smtp.test.local")

    # Setup: drugi target user
    async with AsyncSessionLocal() as db:
        target2, _ = await _new_user(db, UserRole.delivery_lead)
        await db.commit()
        target2_email = target2.email
        target2_id = target2.id

    headers = await _login(
        app_client, setup_users["author_email"], setup_users["author_password"]
    )
    candidate_id = setup_users["candidate_id"]

    # POST z target1
    with patch("app.services.email.smtplib.SMTP") as smtp_cls:
        instance = smtp_cls.return_value.__enter__.return_value
        resp = await app_client.post(
            "/api/notes",
            headers=headers,
            json={
                "content": f"@{setup_users['target_email']} 1st",
                "candidate_id": candidate_id,
            },
        )
        assert resp.status_code == 201
        first_call_count = instance.send_message.call_count
    note_id = resp.json()["id"]

    # PATCH dodaje target2
    with patch("app.services.email.smtplib.SMTP") as smtp_cls2:
        instance2 = smtp_cls2.return_value.__enter__.return_value
        resp = await app_client.patch(
            f"/api/notes/{note_id}",
            headers=headers,
            json={
                "content": (
                    f"@{setup_users['target_email']} 1st + @{target2_email} added"
                )
            },
        )
        assert resp.status_code == 200
        # Tylko target2 dostaje email — call_count == 1
        assert instance2.send_message.call_count == 1, (
            f"oczekiwane 1 wysłanie (tylko target2), było "
            f"{instance2.send_message.call_count}"
        )

    async with AsyncSessionLocal() as db:
        mentions = (
            (
                await db.execute(
                    select(NoteMention).where(NoteMention.note_id == note_id)
                )
            )
            .scalars()
            .all()
        )
    user_ids = {m.user_id for m in mentions}
    assert setup_users["target_id"] in user_ids
    assert target2_id in user_ids
    assert first_call_count == 1


async def test_post_note_with_job_filters_to_members(
    app_client: AsyncClient, setup_users
):
    """Note z job_id → user spoza projektu w content NIE dostaje notyfikacji."""
    async with AsyncSessionLocal() as db:
        author = await db.get(User, setup_users["author_id"])
        # Nowy user — non-member projektu
        non_member, _ = await _new_user(db, UserRole.recruiter)
        client = Client(name=f"NM Client {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        # Job w którym tylko author jest recruiterem (member)
        job = Job(
            title="MentionFilter Job",
            client_id=client.id,
            recruiter_id=author.id,
            status=JobStatus.published,
        )
        db.add(job)
        await db.commit()
        non_member_email = non_member.email
        non_member_id = non_member.id
        job_id = job.id

    headers = await _login(
        app_client, setup_users["author_email"], setup_users["author_password"]
    )
    resp = await app_client.post(
        "/api/notes",
        headers=headers,
        json={
            "content": f"Notatka @{non_member_email} (nie w projekcie)",
            "job_id": job_id,
        },
    )
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    async with AsyncSessionLocal() as db:
        mentions = (
            (
                await db.execute(
                    select(NoteMention).where(NoteMention.note_id == note_id)
                )
            )
            .scalars()
            .all()
        )
        notifs = (
            (
                await db.execute(
                    select(Notification).where(
                        Notification.user_id == non_member_id,
                        Notification.related_entity_id == note_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert mentions == [], "non-member nie powinien dostać NoteMention"
    assert notifs == [], "non-member nie powinien dostać Notification"
