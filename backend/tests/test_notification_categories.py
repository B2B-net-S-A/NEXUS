"""Kategorie powiadomień i wyciszenia per użytkownik (0349)."""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.notification_access import (
    notification_visibility_predicate,
    user_can_receive_notification,
)
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    CATEGORY_INFO,
    NotificationCategory,
    muted_categories,
    muted_types_for,
)

_BACKEND = Path(__file__).resolve().parents[1]


# ── Kontrakty statyczne ─────────────────────────────────────────────────────


def test_every_notification_type_has_a_category():
    missing = set(NotificationType) - set(CATEGORY_BY_TYPE)
    assert not missing, (
        "Nowy typ powiadomienia bez kategorii omijałby wyciszenia użytkowników — "
        f"dopisz go do CATEGORY_BY_TYPE: {sorted(t.value for t in missing)}"
    )


def test_every_category_has_info_and_at_least_one_type():
    assert set(CATEGORY_INFO) == set(NotificationCategory)
    used = set(CATEGORY_BY_TYPE.values())
    assert used == set(NotificationCategory)


def test_mandatory_categories_are_the_agreed_ones():
    mandatory = {c for c, info in CATEGORY_INFO.items() if info.mandatory}
    assert mandatory == {
        NotificationCategory.mentions,
        NotificationCategory.interviews,
        NotificationCategory.system,
    }


def test_entrypoint_mirrors_the_migration():
    import importlib.util

    path = _BACKEND / "alembic" / "versions" / "0349_notification_mutes.py"
    spec = importlib.util.spec_from_file_location("m0349", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert migration.ADD_MUTED_NOTIFICATION_CATEGORIES in entrypoint


def test_stored_mutes_ignore_mandatory_and_unknown_keys():
    raw = {
        "reminders": "2026-09-22T10:00:00+00:00",
        "mentions": "2026-09-22T10:00:00+00:00",  # obowiązkowa — ignorowana
        "renamed_long_ago": "x",
    }
    assert muted_categories(raw) == {NotificationCategory.reminders}
    assert NotificationType.stage_stuck_7d in muted_types_for(raw)
    assert NotificationType.note_mention not in muted_types_for(raw)
    assert muted_categories(None) == frozenset()
    assert muted_categories(["reminders"]) == frozenset()


def test_muted_category_blocks_delivery_but_mandatory_stays():
    user = User(
        email="x@example.com",
        name="X",
        role=UserRole.admin,
        is_active=True,
        muted_notification_categories={
            "reminders": "2026-09-22T10:00:00+00:00",
            "interviews": "2026-09-22T10:00:00+00:00",
        },
    )
    assert not user_can_receive_notification(user, NotificationType.stage_stuck_7d)
    assert user_can_receive_notification(user, NotificationType.stage_changed)
    # „Rozmowy" są obowiązkowe — stary zapis nie może ich wyciszyć.
    assert user_can_receive_notification(user, NotificationType.post_interview_t15)
    predicate_sql = str(notification_visibility_predicate(user))
    assert "NOT IN" in predicate_sql.upper()


# ── API ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def admin_id(app_client: AsyncClient):
    """Id administratora z ``app_client``; po teście zdejmuje jego wyciszenia.

    Administratorzy trafiają do KAŻDEJ listy „członkowie rekrutacji + admini"
    we wspólnej bazie testowej. Wyciszenie zostawione po teście ucinałoby
    powiadomienia w cudzych testach (np. podpowiedź „komplet obsady" liczy
    odbiorców).
    """
    uid = await _admin_id(app_client)
    yield uid
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User).where(User.id == uid).values(muted_notification_categories={})
        )
        await db.commit()


async def _admin_id(app_client: AsyncClient) -> int:
    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
    assert uid is not None
    return uid


async def _seed(
    user_id: int,
    ntype: NotificationType,
    *,
    created_at: datetime | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        n = Notification(
            user_id=user_id,
            title=f"t-{uuid.uuid4().hex[:6]}",
            message="body",
            notification_type=ntype,
            is_read=False,
        )
        if created_at is not None:
            n.created_at = created_at
        db.add(n)
        await db.commit()
        return n.id


async def _is_read(notification_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            await db.scalar(
                select(Notification.is_read).where(Notification.id == notification_id)
            )
        )


@pytest.mark.asyncio
async def test_preferences_list_categories_with_counts(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    admin_id: int,
):
    uid = admin_id
    await _seed(uid, NotificationType.stage_stuck_7d)
    await _seed(uid, NotificationType.dl_stage_stale_6h)

    resp = await app_client.get(
        "/api/notifications/preferences", headers=app_auth_headers
    )
    assert resp.status_code == 200
    by_key = {c["key"]: c for c in resp.json()["categories"]}
    # Administrator może dostać każdy typ, więc widzi wszystkie kategorie.
    assert set(by_key) == {c.value for c in NotificationCategory}
    assert by_key["reminders"]["received_30d"] >= 2
    assert by_key["reminders"]["muted"] is False
    assert by_key["mentions"]["mandatory"] is True


@pytest.mark.asyncio
async def test_muting_hides_category_from_bell_and_count(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    admin_id: int,
):
    uid = admin_id
    stuck = await _seed(uid, NotificationType.stage_stuck_7d)
    moved = await _seed(uid, NotificationType.stage_changed)

    before = await app_client.get("/api/notifications", headers=app_auth_headers)
    ids_before = {n["id"] for n in before.json()["items"]}
    assert {stuck, moved} <= ids_before
    item = next(n for n in before.json()["items"] if n["id"] == stuck)
    assert item["category"] == "reminders"
    assert item["category_label"] == "Zaległości i przypomnienia"
    assert item["category_mutable"] is True

    resp = await app_client.put(
        "/api/notifications/preferences/reminders",
        json={"muted": True},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    by_key = {c["key"]: c for c in resp.json()["categories"]}
    assert by_key["reminders"]["muted"] is True

    after = await app_client.get("/api/notifications", headers=app_auth_headers)
    ids_after = {n["id"] for n in after.json()["items"]}
    assert stuck not in ids_after
    assert moved in ids_after
    assert after.json()["unread_count"] == before.json()["unread_count"] - 1

    count = await app_client.get("/api/notifications/count", headers=app_auth_headers)
    assert count.json()["count"] == after.json()["unread_count"]


@pytest.mark.asyncio
async def test_unmute_marks_only_items_from_the_muted_period_as_read(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    admin_id: int,
):
    uid = admin_id
    older = await _seed(
        uid,
        NotificationType.job_deadline_3d,
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    mute = await app_client.put(
        "/api/notifications/preferences/deadlines",
        json={"muted": True},
        headers=app_auth_headers,
    )
    assert mute.status_code == 200
    during = await _seed(uid, NotificationType.job_deadline_1d)

    unmute = await app_client.put(
        "/api/notifications/preferences/deadlines",
        json={"muted": False},
        headers=app_auth_headers,
    )
    assert unmute.status_code == 200
    assert await _is_read(during) is True
    assert await _is_read(older) is False

    listing = await app_client.get("/api/notifications", headers=app_auth_headers)
    assert older in {n["id"] for n in listing.json()["items"]}


@pytest.mark.asyncio
async def test_mandatory_and_unknown_categories_are_rejected(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    admin_id: int,
):
    mandatory = await app_client.put(
        "/api/notifications/preferences/mentions",
        json={"muted": True},
        headers=app_auth_headers,
    )
    assert mandatory.status_code == 422
    assert "nie można wyłączyć" in mandatory.json()["detail"]

    unknown = await app_client.put(
        "/api/notifications/preferences/nope",
        json={"muted": True},
        headers=app_auth_headers,
    )
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_muting_is_idempotent_and_keeps_original_timestamp(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    admin_id: int,
):
    uid = admin_id
    for _ in range(2):
        resp = await app_client.put(
            "/api/notifications/preferences/kpi",
            json={"muted": True},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200
    async with AsyncSessionLocal() as db:
        stored = await db.scalar(
            select(User.muted_notification_categories).where(User.id == uid)
        )
    assert set(stored) == {"kpi"}
