"""Regression tests for the notifications unread-count / mark-all-read contract.

Guards against the ``WHERE false`` bug (Module 6, finding P0.4): the endpoints
used ``not Notification.is_read`` which SQLAlchemy evaluates as Python ``False``
*before* building SQL, so the query became ``WHERE false`` — unread count was
always 0 and mark-all-read updated nothing. The correct predicate is
``Notification.is_read.is_(False)``.

These tests seed rows directly in the DB (same in-process loop as ``app_client``)
and exercise the real HTTP endpoints, so they also cover owner isolation and the
mark-all affected-row count.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole


async def _seed_user() -> int:
    """Create an isolated active user and return its id."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        u = User(
            email=f"pytest-notif-{unique}@example.com",
            password_hash=hash_password(f"T3st_{unique}!PassX"),
            name="Pytest Notif Other",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_notifications(user_id: int, *, unread: int, read: int) -> None:
    async with AsyncSessionLocal() as db:
        for i in range(unread):
            db.add(
                Notification(
                    user_id=user_id,
                    title=f"unread-{i}",
                    message="body",
                    notification_type=NotificationType.candidate_added,
                    is_read=False,
                )
            )
        for i in range(read):
            db.add(
                Notification(
                    user_id=user_id,
                    title=f"read-{i}",
                    message="body",
                    notification_type=NotificationType.candidate_added,
                    is_read=True,
                )
            )
        await db.commit()


async def _current_user_id(app_client: AsyncClient, headers: dict[str, str]) -> int:
    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
    assert uid is not None
    return uid


@pytest.mark.asyncio
async def test_unread_count_reflects_actual_unread(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """The two count paths must return the real number of unread rows, not 0."""
    uid = await _current_user_id(app_client, app_auth_headers)
    await _seed_notifications(uid, unread=3, read=2)

    list_resp = await app_client.get("/api/notifications", headers=app_auth_headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["unread_count"] == 3

    count_resp = await app_client.get(
        "/api/notifications/count", headers=app_auth_headers
    )
    assert count_resp.status_code == 200
    assert count_resp.json()["count"] == 3


@pytest.mark.asyncio
async def test_mark_all_read_updates_only_unread_and_reports_count(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """mark-all-read must flip exactly the unread rows and report how many."""
    uid = await _current_user_id(app_client, app_auth_headers)
    await _seed_notifications(uid, unread=4, read=1)

    resp = await app_client.put("/api/notifications/read-all", headers=app_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    # Exactly the 4 unread rows are updated (the already-read row is untouched).
    assert body["updated"] == 4

    # A second call updates nothing — everything is already read.
    resp2 = await app_client.put(
        "/api/notifications/read-all", headers=app_auth_headers
    )
    assert resp2.json()["updated"] == 0

    count_resp = await app_client.get(
        "/api/notifications/count", headers=app_auth_headers
    )
    assert count_resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_mark_all_read_does_not_touch_other_users(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Owner isolation — another user's unread rows survive my mark-all-read."""
    uid = await _current_user_id(app_client, app_auth_headers)
    other_id = await _seed_user()
    await _seed_notifications(uid, unread=2, read=0)
    await _seed_notifications(other_id, unread=5, read=0)

    resp = await app_client.put("/api/notifications/read-all", headers=app_auth_headers)
    assert resp.json()["updated"] == 2  # only mine

    async with AsyncSessionLocal() as db:
        other_unread = await db.scalar(
            select(Notification)
            .where(
                Notification.user_id == other_id,
                Notification.is_read.is_(False),
            )
            .limit(1)
        )
    assert other_unread is not None  # the other user's rows are untouched


@pytest.mark.asyncio
async def test_list_limit_is_bounded(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """The list limit is validated — over-max and non-positive are rejected."""
    over = await app_client.get(
        "/api/notifications", params={"limit": 10_000}, headers=app_auth_headers
    )
    assert over.status_code == 422

    zero = await app_client.get(
        "/api/notifications", params={"limit": 0}, headers=app_auth_headers
    )
    assert zero.status_code == 422
