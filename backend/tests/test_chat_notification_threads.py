"""Okienko „Czaty” w górnym pasku (09.10.2026) — Postgres, trasy HTTP.

Powiadomienia czatów pogrupowane w rozmowy, wyłączone z dzwonka, gaszone
wejściem do czatu, ze zdarzeniem na żywo dla każdego odbiorcy.

Wspólna baza CI: każdy test zakłada własne konta, rekrutację i kandydata,
a asercje czytają skrzynkę konta założonego w teście.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.services import chat_notifications

pytestmark = pytest.mark.asyncio

_CHAT_TYPES = {"job_chat_message", "job_chat_mention"}


async def _new_user(db, role: UserRole) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    password = f"T3st_{suffix}!"
    user = User(
        email=f"chatwin-{role.value}-{suffix}@example.com",
        password_hash=hash_password(password),
        name=f"Czat {suffix}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, password


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
        peer, peer_pwd = await _new_user(db, UserRole.recruiter)
        outsider, outsider_pwd = await _new_user(db, UserRole.recruiter)
        client = Client(name=f"Czat Klient {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Czat Rekrutacja {uuid.uuid4().hex[:6]}",
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
            name=f"Czat{uuid.uuid4().hex[:6]}",
            lastname="Okienko",
            email=f"chatwin-{uuid.uuid4().hex[:8]}@x.com",
            created_by=peer.id,
        )
        db.add(candidate)
        await db.commit()
        return {
            "author": await _login(app_client, author.email, author_pwd),
            "author_id": author.id,
            "author_name": author.name,
            "peer": await _login(app_client, peer.email, peer_pwd),
            "peer_id": peer.id,
            "peer_email": peer.email,
            "outsider": await _login(app_client, outsider.email, outsider_pwd),
            "outsider_id": outsider.id,
            "outsider_email": outsider.email,
            "job_id": job.id,
            "job_title": job.title,
            "client_name": client.name,
            "candidate_id": candidate.id,
            "candidate_name": f"{candidate.name} {candidate.lastname}",
        }


async def _say(client: AsyncClient, ctx, kind: str, content: str) -> int:
    path = (
        f"/api/jobs/{ctx['job_id']}/chat/messages"
        if kind == "job"
        else f"/api/candidates/{ctx['candidate_id']}/chat/messages"
    )
    resp = await client.post(path, json={"content": content}, headers=ctx["author"])
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _threads(client: AsyncClient, headers) -> dict[str, Any]:
    resp = await client.get("/api/notifications/chats", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _thread(body: dict[str, Any], kind: str, entity_id: int) -> dict[str, Any]:
    matches = [
        item
        for item in body["items"]
        if item["kind"] == kind and item["entity_id"] == entity_id
    ]
    assert len(matches) == 1, body
    return matches[0]


async def test_job_chat_messages_become_one_thread_with_first_unread_link(
    app_client: AsyncClient, ctx
) -> None:
    first = await _say(app_client, ctx, "job", "Pierwsza wiadomość")
    await _say(app_client, ctx, "job", f"Druga, z oznaczeniem @{ctx['peer_email']}")

    body = await _threads(app_client, ctx["peer"])
    thread = _thread(body, "job", ctx["job_id"])

    assert body["unread_threads"] == 1
    assert thread["title"] == ctx["job_title"]
    assert thread["subtitle"] == ctx["client_name"]
    # Wzmianka i wiadomość to dwa wiersze o tej samej wiadomości — liczymy raz.
    assert thread["unread_count"] == 2
    assert thread["has_mention"] is True
    assert thread["last_author_name"] == ctx["author_name"]
    assert thread["last_message"].startswith("Druga")
    assert thread["link"] == f"/jobs/{ctx['job_id']}?tab=chat&msg={first}"


async def test_candidate_chat_is_a_separate_thread_named_after_the_person(
    app_client: AsyncClient, ctx
) -> None:
    await _say(app_client, ctx, "job", "O rekrutacji")
    message_id = await _say(app_client, ctx, "candidate", "O kandydacie")

    body = await _threads(app_client, ctx["peer"])
    thread = _thread(body, "candidate", ctx["candidate_id"])

    assert body["unread_threads"] == 2
    assert thread["title"] == ctx["candidate_name"]
    assert thread["subtitle"] is None
    assert thread["has_mention"] is False
    assert thread["link"] == (
        f"/candidates/{ctx['candidate_id']}?tab=chat&msg={message_id}"
    )


async def test_author_and_strangers_have_no_thread(
    app_client: AsyncClient, ctx
) -> None:
    await _say(app_client, ctx, "job", "Tylko dla zespołu")

    for headers in (ctx["author"], ctx["outsider"]):
        body = await _threads(app_client, headers)
        assert body == {"items": [], "unread_threads": 0}


async def test_bell_can_leave_chats_out_of_list_counter_and_read_all(
    app_client: AsyncClient, ctx
) -> None:
    await _say(app_client, ctx, "job", f"Do dzwonka? @{ctx['peer_email']}")

    everything = (
        await app_client.get("/api/notifications", headers=ctx["peer"])
    ).json()
    bell = (
        await app_client.get(
            "/api/notifications", params={"exclude_chat": True}, headers=ctx["peer"]
        )
    ).json()

    assert {i["notification_type"] for i in everything["items"]} == _CHAT_TYPES
    assert everything["unread_count"] == 2
    assert bell == {"items": [], "unread_count": 0, "own_unread_count": 0}

    resp = await app_client.patch(
        "/api/notifications/read-all",
        params={"exclude_chat": True},
        headers=ctx["peer"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 0
    assert (await _threads(app_client, ctx["peer"]))["unread_threads"] == 1


async def test_marking_one_thread_read_leaves_the_other(
    app_client: AsyncClient, ctx
) -> None:
    await _say(app_client, ctx, "job", "Rekrutacja")
    await _say(app_client, ctx, "candidate", "Kandydat")

    resp = await app_client.put(
        "/api/notifications/chats/read",
        json={"kind": "job", "entity_id": ctx["job_id"]},
        headers=ctx["peer"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1

    body = await _threads(app_client, ctx["peer"])
    assert _thread(body, "job", ctx["job_id"])["unread_count"] == 0
    assert _thread(body, "candidate", ctx["candidate_id"])["unread_count"] == 1
    assert body["unread_threads"] == 1

    resp = await app_client.put("/api/notifications/chats/read", headers=ctx["peer"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    assert (await _threads(app_client, ctx["peer"]))["unread_threads"] == 0


async def test_half_a_thread_reference_is_rejected(
    app_client: AsyncClient, ctx
) -> None:
    resp = await app_client.put(
        "/api/notifications/chats/read", json={"kind": "job"}, headers=ctx["peer"]
    )
    assert resp.status_code == 422, resp.text


async def test_opening_a_chat_clears_its_notifications(
    app_client: AsyncClient, ctx
) -> None:
    await _say(app_client, ctx, "job", f"Wejdź i przeczytaj @{ctx['peer_email']}")
    await _say(app_client, ctx, "candidate", "A tu osobno")

    resp = await app_client.put(
        f"/api/jobs/{ctx['job_id']}/chat/read", headers=ctx["peer"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["notifications_cleared"] == 2

    body = await _threads(app_client, ctx["peer"])
    assert _thread(body, "job", ctx["job_id"])["unread_count"] == 0
    assert _thread(body, "candidate", ctx["candidate_id"])["unread_count"] == 1

    resp = await app_client.put(
        f"/api/candidates/{ctx['candidate_id']}/chat/read", headers=ctx["peer"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["notifications_cleared"] == 1
    assert (await _threads(app_client, ctx["peer"]))["unread_threads"] == 0

    # Drugie wejście nie ma już czego gasić.
    resp = await app_client.put(
        f"/api/jobs/{ctx['job_id']}/chat/read", headers=ctx["peer"]
    )
    assert resp.json()["notifications_cleared"] == 0


async def test_threads_older_than_the_window_are_not_listed(
    app_client: AsyncClient, ctx
) -> None:
    await _say(app_client, ctx, "job", "Stara rozmowa")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Notification)
            .where(Notification.user_id == ctx["peer_id"])
            .values(
                created_at=func.now()
                - timedelta(days=chat_notifications.CHAT_WINDOW_DAYS + 5)
            )
        )
        await db.commit()

    assert await _threads(app_client, ctx["peer"]) == {
        "items": [],
        "unread_threads": 0,
    }


async def test_muted_chat_category_keeps_only_mentions(
    app_client: AsyncClient, ctx
) -> None:
    await _say(app_client, ctx, "job", "Zwykła wiadomość")
    resp = await app_client.put(
        "/api/notifications/preferences/chat",
        json={"muted": True},
        headers=ctx["peer"],
    )
    assert resp.status_code == 200, resp.text
    assert await _threads(app_client, ctx["peer"]) == {
        "items": [],
        "unread_threads": 0,
    }

    await _say(app_client, ctx, "job", f"Ale wzmianka dochodzi @{ctx['peer_email']}")
    thread = _thread(await _threads(app_client, ctx["peer"]), "job", ctx["job_id"])
    assert thread["unread_count"] == 1
    assert thread["has_mention"] is True


async def test_new_message_announces_itself_to_every_recipient(
    app_client: AsyncClient, ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[int, dict]] = []

    async def _capture(user_id: int, event: dict) -> None:
        sent.append((user_id, event))

    monkeypatch.setattr("app.api.job_chat.notify_user", _capture)
    message_id = await _say(
        app_client, ctx, "job", f"Pytanie do @{ctx['outsider_email']}"
    )

    announced = {
        user_id: event["data"]
        for user_id, event in sent
        if event["type"] == chat_notifications.JOB_NOTIFY_EVENT
    }
    assert ctx["author_id"] not in announced
    # Zespół dostaje zapowiedź wiadomości, oznaczona osoba spoza zespołu —
    # wzmianki (rozgłoszenie wiadomości do niej nie dociera).
    assert announced[ctx["peer_id"]]["notification_type"] == "job_chat_message"
    outsider = announced[ctx["outsider_id"]]
    assert outsider["notification_type"] == "job_chat_mention"
    assert outsider["thread_title"] == ctx["job_title"]
    assert outsider["author_name"] == ctx["author_name"]
    assert outsider["link"] == f"/jobs/{ctx['job_id']}?tab=chat&msg={message_id}"
    assert outsider["related_entity_type"] == "job_chat_message"
