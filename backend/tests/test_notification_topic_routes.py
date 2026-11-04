"""Ikony paska zamiast dzwonka (16.10.2026) — Postgres, trasy HTTP.

Okienko „Rekrutacje” grupuje powiadomienia tematu po rekrutacji, gaszenie
tematu nie rusza innych tematów ani cudzych skrzynek, a okienko „Wiadomości”
pokazuje wątki notatek obok czatów.

Wspólna baza CI: każdy test zakłada własne konta, a asercje czytają skrzynkę
konta założonego w teście.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.api import notifications as notifications_api
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.section_permissions import ProductSection
from app.services.workforce_availability import Delegation, WorkforceContext

pytestmark = pytest.mark.asyncio

_T = NotificationType
_NOTE_LINK = "/candidates/3?tab=activity&activity=notes&note=11"


async def _new_user(db) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    password = f"T3st_{suffix}!"
    user = User(
        email=f"topics-{suffix}@example.com",
        password_hash=hash_password(password),
        name=f"Tematy {suffix}",
        role=UserRole.recruiter,
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


def _row(
    user_id: int,
    ntype: NotificationType,
    link: str,
    *,
    days_ago: int = 0,
    is_read: bool = False,
    entity_type: str | None = None,
) -> Notification:
    # Bez `related_entity_id`: dzienny indeks dedupu obejmuje tylko wiersze z encją.
    return Notification(
        user_id=user_id,
        title=f"Test {ntype.value}",
        message="Treść testowa",
        link=link,
        notification_type=ntype,
        related_entity_type=entity_type,
        is_read=is_read,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago, minutes=1),
    )


@pytest_asyncio.fixture
async def ctx(app_client: AsyncClient) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        me, me_pwd = await _new_user(db)
        other, _ = await _new_user(db)
        rows = {
            "move": _row(me.id, _T.stage_rule, "/jobs/5?candidate=9"),
            "deadline": _row(me.id, _T.job_deadline_3d, "/jobs/5"),
            "assigned": _row(
                me.id, _T.request_assignment_changed, "/jobs/6", entity_type="job"
            ),
            "champion_read": _row(
                me.id, _T.champion_profile_updated, "/jobs/7?tab=champion", is_read=True
            ),
            # Auto-match prowadzi na profil kandydata z `?job=`.
            "auto": _row(me.id, _T.auto_match, "/candidates/3?job=8"),
            # Poranne „Twoje requesty na dziś” — kilka rekrutacji, bez jednej.
            "digest": _row(me.id, _T.request_assignment_changed, "/dashboard"),
            "old": _row(me.id, _T.stage_rule, "/jobs/9?candidate=1", days_ago=8),
            "cv": _row(me.id, _T.cv_ready, "/jobs/5?candidate=9&panel=cv"),
            "mention": _row(me.id, _T.note_mention, _NOTE_LINK, entity_type="note"),
            "reply": _row(me.id, _T.note_reply, _NOTE_LINK, entity_type="note"),
            "chat": _row(
                me.id,
                _T.job_chat_message,
                "/jobs/5?tab=chat&msg=1",
                entity_type="job_chat_message",
            ),
            "foreign": _row(other.id, _T.stage_rule, "/jobs/5?candidate=9"),
        }
        db.add_all(rows.values())
        await db.commit()
        return {
            "me": await _login(app_client, me.email, me_pwd),
            "me_id": me.id,
            "ids": {key: row.id for key, row in rows.items()},
        }


async def _unread(ids: dict[str, int]) -> set[str]:
    by_id = {v: k for k, v in ids.items()}
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Notification.id).where(
                Notification.id.in_(list(by_id)), Notification.is_read.is_(False)
            )
        )
        return {by_id[i] for (i,) in rows.all()}


# ── „Rekrutacje” ────────────────────────────────────────────────────────────


async def test_jobs_window_groups_per_recruitment(app_client: AsyncClient, ctx):
    resp = await app_client.get("/api/notifications/jobs", headers=ctx["me"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_key = {(i["job_id"], i["link"]): i for i in body["items"]}

    job5 = by_key[(5, "/jobs/5")]
    assert job5["unread_count"] == 2  # ruch + termin; CV i czat to inne tematy
    assert job5["title"].startswith("Rekrutacja #") or job5["title"]
    assert by_key[(6, "/jobs/6")]["has_task"] is True  # przydział jest imienny
    assert job5["has_task"] is False
    assert (8, "/jobs/8") in by_key  # `?job=` z linku auto-matcha
    digest = by_key[(None, "/dashboard")]
    assert digest["unread_count"] == 1
    assert by_key[(7, "/jobs/7")]["unread_count"] == 0  # przeczytane zostaje w oknie
    assert all(i["job_id"] != 9 for i in body["items"])  # starsze niż 7 dni
    # Nowe najpierw; liczba na ikonie liczy pozycje z nowymi, nie wiersze.
    assert body["items"][-1]["job_id"] == 7
    assert body["unread_jobs"] == 4


async def test_reading_one_recruitment_leaves_other_topics(app_client, ctx):
    resp = await app_client.put(
        "/api/notifications/topics/read",
        json={"topic": "jobs", "job_id": 5},
        headers=ctx["me"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 2
    unread = await _unread(ctx["ids"])
    assert {"move", "deadline"}.isdisjoint(unread)
    # Ta sama rekrutacja, inny temat — ikona „CV” i „Wiadomości” gaszą swoje.
    assert {"cv", "chat", "assigned", "auto", "digest", "foreign"} <= unread


async def test_reading_a_position_without_recruitment_by_link(app_client, ctx):
    resp = await app_client.put(
        "/api/notifications/topics/read",
        json={"topic": "jobs", "link": "/dashboard"},
        headers=ctx["me"],
    )
    assert resp.status_code == 200, resp.text
    unread = await _unread(ctx["ids"])
    assert "digest" not in unread
    assert "assigned" in unread


async def test_reading_whole_topic_touches_only_own_rows_of_it(app_client, ctx):
    resp = await app_client.put(
        "/api/notifications/topics/read", json={"topic": "jobs"}, headers=ctx["me"]
    )
    assert resp.status_code == 200, resp.text
    unread = await _unread(ctx["ids"])
    assert unread == {"cv", "mention", "reply", "chat", "foreign"}


async def test_topic_read_rejects_out_of_range_job_id(app_client, ctx):
    resp = await app_client.put(
        "/api/notifications/topics/read",
        json={"topic": "jobs", "job_id": 10**12},
        headers=ctx["me"],
    )
    assert resp.status_code == 422


async def test_substitute_closes_colleagues_reminder_only_on_purpose() -> None:
    # Klik w pozycję okienka = świadome zamknięcie (jak klik w dzwonku);
    # samo wejście na ekran rekrutacji (`include_covered=false`) gasi tylko
    # własne wiersze — nieobecny zobaczy swoje przypomnienie po powrocie.
    async with AsyncSessionLocal() as db:
        owner, _ = await _new_user(db)
        cover, _ = await _new_user(db)
        reminder = _row(owner.id, _T.stage_stuck_7d, "/jobs/5?candidate=4")
        db.add(reminder)
        await db.commit()
        owner_id, cover_id, reminder_id = owner.id, cover.id, reminder.id

    today = business_today()
    async with AsyncSessionLocal() as db:
        db.info["workforce_context"] = WorkforceContext(
            fresh=True,
            available_ids={cover_id},
            delegations={
                owner_id: Delegation(owner_id, cover_id, today, today, ("ci-leave",))
            },
        )
        acting = await db.get(User, cover_id)
        acting.effective_section_access = {s.value: "write" for s in ProductSection}

        listed = await notifications_api.list_job_threads(acting, db)
        assert [(i.job_id, i.unread_count) for i in listed.items] == [(5, 1)]

        visit = await notifications_api.mark_topic_read(
            notifications_api.TopicReadRequest(
                topic="jobs", job_id=5, include_covered=False
            ),
            acting,
            db,
        )
        assert visit.updated == 0
        clicked = await notifications_api.mark_topic_read(
            notifications_api.TopicReadRequest(topic="jobs", job_id=5), acting, db
        )
        assert clicked.updated == 1

    assert await _unread({"reminder": reminder_id}) == set()


async def test_topic_read_rejects_two_targets(app_client, ctx):
    resp = await app_client.put(
        "/api/notifications/topics/read",
        json={"topic": "jobs", "job_id": 5, "link": "/dashboard"},
        headers=ctx["me"],
    )
    assert resp.status_code == 422


async def test_list_filters_by_topic_and_count_splits_by_topic(app_client, ctx):
    resp = await app_client.get(
        "/api/notifications", params={"topic": "cv"}, headers=ctx["me"]
    )
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()["items"]} == {ctx["ids"]["cv"]}

    resp = await app_client.get("/api/notifications/count", headers=ctx["me"])
    body = resp.json()
    assert body["by_topic"]["cv"] == 1
    assert body["by_topic"]["messages"] == 3
    # 6 = ruch, termin, przydział, auto-match, skrót i stary ruch (licznik nie ma okna).
    assert body["by_topic"]["jobs"] == 6
    assert body["count"] == sum(body["by_topic"].values())


# ── „Umowy” (26.10.2026) ────────────────────────────────────────────────────


async def test_contracts_window_groups_per_contract_and_reads_by_ids(app_client):
    import random

    base = random.randint(10**8, 2 * 10**9)
    async with AsyncSessionLocal() as db:
        me, me_pwd = await _new_user(db)

        def contract_row(ntype, link, entity_type, entity_id, *, is_read=False):
            row = _row(me.id, ntype, link, is_read=is_read, entity_type=entity_type)
            row.related_entity_id = entity_id
            return row

        rows = {
            "waits": contract_row(
                _T.signature_sent,
                "/contracts/b2b-generator?tab=generated",
                "b2b_signing_request",
                base,
            ),
            "signed": contract_row(
                _T.signature_signed,
                "/contracts/b2b-generator?tab=generated",
                "b2b_signing_request",
                base,
            ),
            "expired_read": contract_row(
                _T.signature_failed,
                "/contracts/b2b-generator?tab=generated",
                "b2b_signing_request",
                base + 1,
                is_read=True,
            ),
            "dl_asked": contract_row(
                _T.b2b_signature_requested,
                "/jobs/5?candidate=9",
                "b2b_generated_contract",
                base + 2,
            ),
            "autenti": _row(me.id, _T.signature_rejected, "/candidates?contract=3"),
            "job_move": _row(me.id, _T.stage_rule, "/jobs/5?candidate=9"),
        }
        db.add_all(rows.values())
        await db.commit()
        headers = await _login(app_client, me.email, me_pwd)
        ids = {key: row.id for key, row in rows.items()}

    resp = await app_client.get("/api/notifications/contracts", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Jedna pozycja na umowę: dwa zdarzenia jednego wniosku to jedna pozycja.
    by_count = sorted(i["unread_count"] for i in body["items"])
    assert by_count == [0, 1, 1, 2]
    assert body["unread_contracts"] == 3
    assert body["items"][-1]["unread_count"] == 0  # nowe najpierw
    request_item = next(i for i in body["items"] if i["unread_count"] == 2)
    assert sorted(request_item["unread_ids"]) == sorted([ids["waits"], ids["signed"]])
    assert request_item["link"] == "/contracts/b2b-generator?tab=generated"

    read = await app_client.put(
        "/api/notifications/topics/read",
        json={"topic": "contracts", "ids": request_item["unread_ids"]},
        headers=headers,
    )
    assert read.status_code == 200, read.text
    assert read.json()["updated"] == 2
    unread = await _unread(ids)
    assert unread == {"dl_asked", "autenti", "job_move"}


# ── „Wiadomości”: wątki notatek ─────────────────────────────────────────────


async def test_messages_window_shows_note_thread_only_on_request(app_client, ctx):
    plain = await app_client.get("/api/notifications/chats", headers=ctx["me"])
    assert all(t["kind"] != "note" for t in plain.json()["items"])

    resp = await app_client.get(
        "/api/notifications/chats",
        params={"include_notes": "true"},
        headers=ctx["me"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    notes = [t for t in body["items"] if t["kind"] == "note"]
    # Wzmianka i odpowiedź pod tą samą notatką = jeden wątek.
    assert len(notes) == 1
    assert notes[0]["link"] == _NOTE_LINK
    assert notes[0]["unread_count"] == 2
    assert notes[0]["has_mention"] is True
    assert body["unread_threads"] == plain.json()["unread_threads"] + 1


async def test_reading_a_note_thread_by_link(app_client, ctx):
    resp = await app_client.put(
        "/api/notifications/chats/read",
        json={"kind": "note", "link": _NOTE_LINK},
        headers=ctx["me"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 2
    unread = await _unread(ctx["ids"])
    assert {"mention", "reply"}.isdisjoint(unread)
    assert "chat" in unread


async def test_note_thread_read_needs_a_link(app_client, ctx):
    resp = await app_client.put(
        "/api/notifications/chats/read", json={"kind": "note"}, headers=ctx["me"]
    )
    assert resp.status_code == 422


async def test_mark_all_messages_includes_notes_only_on_request(app_client, ctx):
    await app_client.put("/api/notifications/chats/read", headers=ctx["me"])
    unread = await _unread(ctx["ids"])
    assert "chat" not in unread
    assert {"mention", "reply"} <= unread

    await app_client.put(
        "/api/notifications/chats/read",
        params={"include_notes": "true"},
        headers=ctx["me"],
    )
    assert {"mention", "reply"}.isdisjoint(await _unread(ctx["ids"]))
