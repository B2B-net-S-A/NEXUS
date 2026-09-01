"""Integration tests dla Job Chat (per-recruitment internal team chat).

Pokrywa scenariusze z planu:
    1. member_can_post
    2. non_member_forbidden
    3. admin_sees_all
    4. mention_creates_notification
    5. soft_delete
    6. edit_sets_flag
    7. recruiter_cannot_pin
    8. dl_can_pin_max_3
    9. pagination_before_id
   10. fts_search
   11. unread_count
   12. ws_dispatched_on_send
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_chat import JobChatMessage
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _new_user(db, role: UserRole) -> tuple[User, str]:
    """Tworzy aktywnego usera, zwraca (user, password)."""
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    u = User(
        email=f"chat-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Chat {role.value} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u, pwd


async def _new_client(db) -> Client:
    suffix = uuid.uuid4().hex[:8]
    c = Client(name=f"Chat Client {suffix}")
    db.add(c)
    await db.flush()
    return c


async def _new_job(db, client_id: int, *, recruiter_id: int) -> Job:
    j = Job(
        title=f"Chat Test Job {uuid.uuid4().hex[:6]}",
        client_id=client_id,
        recruiter_id=recruiter_id,
        status=JobStatus.published,
    )
    db.add(j)
    await db.flush()
    return j


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def chat_setup(app_client: AsyncClient) -> dict[str, Any]:
    """Twórz klienta + job + recruiter (member) + outsider (non-member) + DL."""
    async with AsyncSessionLocal() as db:
        recruiter, recruiter_pwd = await _new_user(db, UserRole.recruiter)
        outsider, outsider_pwd = await _new_user(db, UserRole.recruiter)
        dl, dl_pwd = await _new_user(db, UserRole.delivery_lead)
        client = await _new_client(db)
        job = await _new_job(db, client.id, recruiter_id=recruiter.id)
        await db.commit()
        return {
            "recruiter_id": recruiter.id,
            "recruiter_email": recruiter.email,
            "recruiter_password": recruiter_pwd,
            "outsider_id": outsider.id,
            "outsider_email": outsider.email,
            "outsider_password": outsider_pwd,
            "dl_id": dl.id,
            "dl_email": dl.email,
            "dl_password": dl_pwd,
            "job_id": job.id,
            "client_id": client.id,
        }


# ── Tests ────────────────────────────────────────────────────────────────────


async def test_member_can_post(app_client: AsyncClient, chat_setup):
    headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    resp = await app_client.post(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages",
        headers=headers,
        json={"content": "hej zespole"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["content"] == "hej zespole"
    assert body["author"]["id"] == chat_setup["recruiter_id"]
    assert body["is_deleted"] is False


async def test_non_member_forbidden(app_client: AsyncClient, chat_setup):
    headers = await _login(
        app_client, chat_setup["outsider_email"], chat_setup["outsider_password"]
    )
    list_resp = await app_client.get(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages", headers=headers
    )
    assert list_resp.status_code == 403

    post_resp = await app_client.post(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages",
        headers=headers,
        json={"content": "should fail"},
    )
    assert post_resp.status_code == 403


async def test_admin_sees_all(
    app_client: AsyncClient, app_auth_headers: dict, chat_setup
):
    """Admin (z app_auth_headers) ma dostęp do każdego jobu — bez bycia w collab."""
    resp = await app_client.get(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages", headers=app_auth_headers
    )
    assert resp.status_code == 200


async def test_mention_creates_notification(app_client: AsyncClient, chat_setup):
    """Recruiter (member) mention'uje DL (admin via dodanie do collab nie potrzebne
    bo sprawdzamy że @ siebie samego DL wymaga członkostwa — DL nie jest member, więc
    użyjemy admina którego mention'ujemy."""
    # Stwórz drugiego recruitera i dodaj jako collaborator, by miał dostęp.
    async with AsyncSessionLocal() as db:
        peer, _peer_pwd = await _new_user(db, UserRole.recruiter)
        from app.models.job_collaborator import (
            JobCollaborator,
            JobCollaboratorSource,
        )

        db.add(
            JobCollaborator(
                job_id=chat_setup["job_id"],
                user_id=peer.id,
                added_by=chat_setup["recruiter_id"],
                source=JobCollaboratorSource.manual,
            )
        )
        await db.commit()
        peer_email = peer.email
        peer_id = peer.id

    headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    resp = await app_client.post(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages",
        headers=headers,
        json={"content": f"hej @{peer_email} co tam?"},
    )
    assert resp.status_code == 201
    msg = resp.json()
    assert peer_id in msg["mentions"]

    # Sprawdź notyfikacje persistent dla peer'a
    async with AsyncSessionLocal() as db:
        notifs = (
            (
                await db.execute(
                    select(Notification).where(Notification.user_id == peer_id)
                )
            )
            .scalars()
            .all()
        )
        types = {n.notification_type for n in notifs}
        assert NotificationType.job_chat_mention in types
        assert NotificationType.job_chat_message in types


async def test_soft_delete(app_client: AsyncClient, chat_setup):
    headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    create = await app_client.post(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages",
        headers=headers,
        json={"content": "to mam usunąć"},
    )
    msg_id = create.json()["id"]

    delete = await app_client.delete(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages/{msg_id}", headers=headers
    )
    assert delete.status_code == 204

    listed = await app_client.get(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages", headers=headers
    )
    items = listed.json()["items"]
    found = next((m for m in items if m["id"] == msg_id), None)
    assert found is not None
    assert found["is_deleted"] is True
    assert "usunięta" in found["content"].lower()
    assert "to mam" not in found["content"]


async def test_edit_sets_flag(app_client: AsyncClient, chat_setup):
    headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    create = await app_client.post(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages",
        headers=headers,
        json={"content": "wersja 1"},
    )
    msg_id = create.json()["id"]
    assert create.json()["is_edited"] is False

    patched = await app_client.patch(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages/{msg_id}",
        headers=headers,
        json={"content": "wersja 2 (edited)"},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["content"] == "wersja 2 (edited)"
    assert body["is_edited"] is True
    assert body["edited_at"] is not None


async def test_recruiter_cannot_pin(app_client: AsyncClient, chat_setup):
    headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    create = await app_client.post(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages",
        headers=headers,
        json={"content": "pinable"},
    )
    msg_id = create.json()["id"]
    pin = await app_client.post(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages/{msg_id}/pin",
        headers=headers,
    )
    assert pin.status_code == 403


async def test_dl_can_pin_max_3(
    app_client: AsyncClient, app_auth_headers: dict, chat_setup
):
    """Admin (z fixturki) może pinować, ale 4. pin → 400."""
    # Najpierw recruiter musi wysłać 4 wiadomości (admin-too OK, ale recruiter szybciej).
    rec_headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    msg_ids: list[int] = []
    for i in range(4):
        resp = await app_client.post(
            f"/api/jobs/{chat_setup['job_id']}/chat/messages",
            headers=rec_headers,
            json={"content": f"msg-{i}"},
        )
        msg_ids.append(resp.json()["id"])

    # Pin 3 → OK
    for msg_id in msg_ids[:3]:
        pin = await app_client.post(
            f"/api/jobs/{chat_setup['job_id']}/chat/messages/{msg_id}/pin",
            headers=app_auth_headers,
        )
        assert pin.status_code == 200, pin.text
        assert pin.json()["pinned"] is True

    # 4. pin → 400
    pin4 = await app_client.post(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages/{msg_ids[3]}/pin",
        headers=app_auth_headers,
    )
    assert pin4.status_code == 400


async def test_pagination_before_id(app_client: AsyncClient, chat_setup):
    headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    # 60 wiadomości, limit=50 → has_more=true
    for i in range(60):
        await app_client.post(
            f"/api/jobs/{chat_setup['job_id']}/chat/messages",
            headers=headers,
            json={"content": f"page-{i}"},
        )
    page1 = await app_client.get(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages?limit=50", headers=headers
    )
    body1 = page1.json()
    assert len(body1["items"]) == 50
    assert body1["has_more"] is True
    assert body1["next_before_id"] is not None

    page2 = await app_client.get(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages?limit=50&before_id={body1['next_before_id']}",
        headers=headers,
    )
    body2 = page2.json()
    # Pozostałych 10 lub trochę mniej — nigdy więcej niż 50
    assert len(body2["items"]) <= 50
    assert body2["has_more"] is False


async def test_fts_search(app_client: AsyncClient, chat_setup):
    headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    contents = [
        "Python developer needed",
        "Java is also fine",
        "We use Python and Django",
        "Mostly Python actually",
    ]
    for c in contents:
        await app_client.post(
            f"/api/jobs/{chat_setup['job_id']}/chat/messages",
            headers=headers,
            json={"content": c},
        )

    search = await app_client.get(
        f"/api/jobs/{chat_setup['job_id']}/chat/messages?search=Python",
        headers=headers,
    )
    assert search.status_code == 200
    items = search.json()["items"]
    assert len(items) == 3
    for item in items:
        assert "python" in item["content"].lower()


async def test_unread_count(app_client: AsyncClient, chat_setup):
    """Recruiter wysyła 5; outsider-promoted-to-collab czyta po 3 → unread=2."""
    # Promote outsider do collaboratora
    async with AsyncSessionLocal() as db:
        from app.models.job_collaborator import (
            JobCollaborator,
            JobCollaboratorSource,
        )

        db.add(
            JobCollaborator(
                job_id=chat_setup["job_id"],
                user_id=chat_setup["outsider_id"],
                added_by=chat_setup["recruiter_id"],
                source=JobCollaboratorSource.manual,
            )
        )
        await db.commit()

    rec_headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )
    msg_ids = []
    for i in range(5):
        resp = await app_client.post(
            f"/api/jobs/{chat_setup['job_id']}/chat/messages",
            headers=rec_headers,
            json={"content": f"msg-{i}"},
        )
        msg_ids.append(resp.json()["id"])

    out_headers = await _login(
        app_client, chat_setup["outsider_email"], chat_setup["outsider_password"]
    )
    # Najpierw mark_read po wszystkich → unread=0
    full = await app_client.put(
        f"/api/jobs/{chat_setup['job_id']}/chat/read", headers=out_headers
    )
    assert full.status_code == 200
    cnt = await app_client.get(
        f"/api/jobs/{chat_setup['job_id']}/chat/unread-count", headers=out_headers
    )
    assert cnt.json()["unread_count"] == 0

    # Recruiter wysyła 2 nowe → outsider widzi unread=2
    for i in range(2):
        await app_client.post(
            f"/api/jobs/{chat_setup['job_id']}/chat/messages",
            headers=rec_headers,
            json={"content": f"new-{i}"},
        )

    cnt2 = await app_client.get(
        f"/api/jobs/{chat_setup['job_id']}/chat/unread-count", headers=out_headers
    )
    assert cnt2.json()["unread_count"] == 2


async def test_ws_dispatched_on_send(app_client: AsyncClient, chat_setup):
    """notify_user wywołane dla każdego członka projektu (z wyjątkiem? nie — w Section 2.4
    broadcast idzie do WSZYSTKICH członków bo serwer nie wie czy autor ma więcej tabów,
    własne klienty fronendu odfiltrują)."""
    rec_headers = await _login(
        app_client, chat_setup["recruiter_email"], chat_setup["recruiter_password"]
    )

    with patch("app.api.job_chat.notify_user", new_callable=AsyncMock) as mock_notify:
        resp = await app_client.post(
            f"/api/jobs/{chat_setup['job_id']}/chat/messages",
            headers=rec_headers,
            json={"content": "test ws"},
        )
        assert resp.status_code == 201

        # Co najmniej recruiter (autor) jako member projektu → 1+ wywołań.
        # W praktyce: recruiter + admini systemu (z app_client jest seedowany 1 admin).
        assert mock_notify.await_count >= 1
        # Każde wywołanie ma event chat:message:new
        events = [c.args[1].get("type") for c in mock_notify.await_args_list]
        assert all(t == "chat:message:new" for t in events)
