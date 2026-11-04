"""Okienko „Rozmowy” w górnym pasku (13.10.2026) — Postgres, trasy HTTP.

Powiadomienia kategorii „Rozmowy” mają własną listę i własne gaszenie,
a dzwonek może je pominąć na liście, w obu licznikach i w „Oznacz wszystko”.

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
from app.services.notification_categories import NotificationCategory, types_in
from app.services.section_permissions import ProductSection
from app.services.workforce_availability import Delegation, WorkforceContext

pytestmark = pytest.mark.asyncio

_T = NotificationType
_INTERVIEW_TYPES = {t.value for t in types_in(NotificationCategory.interviews)}


async def _new_user(db, role: UserRole = UserRole.recruiter) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    password = f"T3st_{suffix}!"
    user = User(
        email=f"ivwin-{role.value}-{suffix}@example.com",
        password_hash=hash_password(password),
        name=f"Rozmowy {suffix}",
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


def _row(
    user_id: int,
    ntype: NotificationType,
    *,
    link: str = "/calendar?cycle=1-2",
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
            "slots": _row(me.id, _T.interview_slots_requested),
            "prep": _row(me.id, _T.prep_attention),
            # Starsze niż okno 7 dni i przeczytane nie wchodzą do okienka.
            "old": _row(
                me.id, _T.interview_scheduled, link="/calendar?event=7", days_ago=8
            ),
            "read": _row(me.id, _T.interview_debrief_saved, is_read=True),
            "stage": _row(me.id, _T.stage_changed, link="/jobs/1"),
            "chat": _row(
                me.id,
                _T.job_chat_message,
                link="/jobs/1?tab=chat&msg=1",
                entity_type="job_chat_message",
            ),
            "foreign": _row(other.id, _T.interview_slot_confirmed),
        }
        db.add_all(rows.values())
        await db.commit()
        return {
            "me": await _login(app_client, me.email, me_pwd),
            "me_id": me.id,
            "other_id": other.id,
            "ids": {key: row.id for key, row in rows.items()},
        }


async def _window(client: AsyncClient, headers) -> list[dict]:
    resp = await client.get("/api/notifications/interviews", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _unread_ids(user_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Notification.id).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)
            )
        )
        return set(rows.all())


async def test_window_lists_own_unread_interview_rows_from_last_week(
    app_client: AsyncClient, ctx
) -> None:
    items = await _window(app_client, ctx["me"])

    assert {i["id"] for i in items} == {ctx["ids"]["slots"], ctx["ids"]["prep"]}
    assert {i["category"] for i in items} == {"interviews"}
    assert all(i["on_behalf_of_name"] is None for i in items)


async def test_bell_can_leave_interviews_out_of_list_counters_and_read_all(
    app_client: AsyncClient, ctx
) -> None:
    everything = (await app_client.get("/api/notifications", headers=ctx["me"])).json()
    bell = (
        await app_client.get(
            "/api/notifications",
            params={"exclude_chat": True, "exclude_interviews": True},
            headers=ctx["me"],
        )
    ).json()

    assert _INTERVIEW_TYPES & {i["notification_type"] for i in everything["items"]}
    assert everything["unread_count"] == 5
    assert [i["id"] for i in bell["items"]] == [ctx["ids"]["stage"]]
    assert bell["unread_count"] == 1
    assert bell["own_unread_count"] == 1

    resp = await app_client.patch(
        "/api/notifications/read-all",
        params={"exclude_chat": True, "exclude_interviews": True},
        headers=ctx["me"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    assert await _unread_ids(ctx["me_id"]) == {
        ctx["ids"]["slots"],
        ctx["ids"]["prep"],
        ctx["ids"]["old"],
        ctx["ids"]["chat"],
    }


async def test_read_all_without_the_flag_still_closes_interviews(
    app_client: AsyncClient, ctx
) -> None:
    resp = await app_client.patch("/api/notifications/read-all", headers=ctx["me"])

    assert resp.status_code == 200, resp.text
    assert await _unread_ids(ctx["me_id"]) == set()


async def test_marking_selected_rows_read_touches_only_own_interview_rows(
    app_client: AsyncClient, ctx
) -> None:
    resp = await app_client.put(
        "/api/notifications/interviews/read",
        json={"ids": [ctx["ids"]["slots"], ctx["ids"]["stage"], ctx["ids"]["foreign"]]},
        headers=ctx["me"],
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    assert [i["id"] for i in await _window(app_client, ctx["me"])] == [
        ctx["ids"]["prep"]
    ]
    assert ctx["ids"]["stage"] in await _unread_ids(ctx["me_id"])
    assert await _unread_ids(ctx["other_id"]) == {ctx["ids"]["foreign"]}


async def test_marking_all_read_closes_every_own_interview_row_and_nothing_else(
    app_client: AsyncClient, ctx
) -> None:
    resp = await app_client.put("/api/notifications/interviews/read", headers=ctx["me"])

    assert resp.status_code == 200, resp.text
    # Także wiersz starszy niż okno listy — „wszystkie” znaczy wszystkie własne.
    assert resp.json()["updated"] == 3
    assert await _window(app_client, ctx["me"]) == []
    assert await _unread_ids(ctx["me_id"]) == {ctx["ids"]["stage"], ctx["ids"]["chat"]}
    assert await _unread_ids(ctx["other_id"]) == {ctx["ids"]["foreign"]}


@pytest.mark.parametrize("ids", [[], list(range(1, 102))])
async def test_empty_or_oversized_id_list_is_rejected(
    app_client: AsyncClient, ctx, ids
) -> None:
    resp = await app_client.put(
        "/api/notifications/interviews/read", json={"ids": ids}, headers=ctx["me"]
    )

    assert resp.status_code == 422, resp.text
    assert len(await _unread_ids(ctx["me_id"])) == 5


async def test_substitute_sees_and_closes_only_the_reminder_clicked() -> None:
    async with AsyncSessionLocal() as db:
        owner, _ = await _new_user(db)
        cover, _ = await _new_user(db)
        reminder = _row(owner.id, _T.interview_scheduled, link="/calendar?event=7")
        second = _row(owner.id, _T.post_interview_t15)
        # Potwierdzenie terminu nie jest przypomnieniem operacyjnym — zastępca
        # go nie dziedziczy.
        personal = _row(owner.id, _T.interview_slot_confirmed)
        db.add_all([reminder, second, personal])
        await db.commit()
        owner_id, cover_id, owner_name = owner.id, cover.id, owner.name
        reminder_id, second_id, personal_id = reminder.id, second.id, personal.id

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

        listed = await notifications_api.list_interview_notifications(acting, db)
        assert {i.id for i in listed.items} == {reminder_id, second_id}
        assert {i.on_behalf_of_name for i in listed.items} == {owner_name}

        clicked = await notifications_api.mark_interview_notifications_read(
            acting,
            db,
            notifications_api.InterviewNotificationsReadRequest(ids=[reminder_id]),
        )
        assert clicked.updated == 1

        # „Oznacz nowe” zastępcy nie zamyka spraw nieobecnego.
        everything = await notifications_api.mark_interview_notifications_read(
            acting, db, None
        )
        assert everything.updated == 0

    assert await _unread_ids(owner_id) == {second_id, personal_id}
