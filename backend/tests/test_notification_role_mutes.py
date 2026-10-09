"""Powiadomienia wyłączone dla roli — tabela „Kto co dostaje” (09.10.2026)."""

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.critical_event import CriticalEvent
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import notification_delivery as delivery
from app.services.notification_access import (
    notification_visibility_predicate,
    user_can_receive_notification,
)
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    CATEGORY_INFO,
    GROUP_BY_TYPE,
    GROUP_INFO,
    group_is_mutable,
    types_in_group,
)
from app.services.notification_role_mutes import (
    MATRIX_ROLES,
    SETTING_KEY,
    normalise,
    role_muted_groups,
    role_muted_types,
)

_BACKEND = Path(__file__).resolve().parents[1]
_AT = "2026-10-09T08:00:00+00:00"


# ── Kontrakty statyczne (bez bazy) ──────────────────────────────────────────


def test_every_notification_type_has_exactly_one_group_in_its_category():
    assert set(GROUP_BY_TYPE) == set(NotificationType)
    for notification_type, group in GROUP_BY_TYPE.items():
        assert GROUP_INFO[group].category == CATEGORY_BY_TYPE[notification_type]
    # Każda kategoria ma co najmniej jedną grupę, a żadna grupa nie jest pusta.
    assert {info.category for info in GROUP_INFO.values()} == set(CATEGORY_INFO)
    assert all(types_in_group(group) for group in GROUP_INFO)


def test_mandatory_categories_cannot_be_switched_off_for_a_role():
    for group, info in GROUP_INFO.items():
        assert group_is_mutable(group) is (not CATEGORY_INFO[info.category].mandatory)
    assert not group_is_mutable("mentions")
    assert not group_is_mutable("nie_ma_takiej")


def test_stored_value_ignores_unknown_roles_groups_and_mandatory():
    value = normalise(
        {
            "revision": 4,
            "roles": {
                "admin": {
                    "contracts_order_ending": _AT,
                    "mentions": _AT,  # obowiązkowa — pomijana
                    "renamed_long_ago": _AT,
                },
                "trainee": {"contracts_order_ending": _AT},  # rola spoza tabeli
                "finance": "nie słownik",
            },
        }
    )
    assert value == {
        "revision": 4,
        "roles": {"admin": {"contracts_order_ending": _AT}},
    }
    assert normalise(None) == {"revision": 0, "roles": {}}
    assert normalise(["x"]) == {"revision": 0, "roles": {}}


def test_multi_role_account_is_muted_only_when_every_role_is():
    value = normalise(
        {
            "roles": {
                "admin": {"contracts_order_ending": _AT, "reminders_stage_6h": _AT},
                "head_of_recruitment": {"reminders_stage_6h": _AT},
            }
        }
    )
    assert role_muted_groups(value, [UserRole.admin]) == {
        "contracts_order_ending",
        "reminders_stage_6h",
    }
    # Admin + Head of Recruitment: wspólna jest tylko „stoi 6 h”.
    both = role_muted_groups(value, [UserRole.admin, UserRole.head_of_recruitment])
    assert both == {"reminders_stage_6h"}
    # Trzecia rola, w której grupa jest włączona, przywraca powiadomienie.
    assert not role_muted_groups(
        value,
        [UserRole.admin, UserRole.head_of_recruitment, UserRole.recruiter],
    )
    assert not role_muted_groups(value, [UserRole.trainee])
    assert not role_muted_groups(value, [])
    assert role_muted_types(value, ["admin"]) >= {
        NotificationType.client_order_ending_14d,
        NotificationType.dl_stage_stale_6h,
    }
    assert NotificationType.contract_ending not in role_muted_types(value, ["admin"])


def test_role_mute_blocks_delivery_and_hides_rows_but_missing_policy_mutes_nothing():
    user = User(
        email="x@example.com",
        name="X",
        role=UserRole.admin,
        roles=["admin"],
        is_active=True,
    )
    # Konto bez policzonej polityki (testy, stare ścieżki) = nic nie wyłączone.
    assert user_can_receive_notification(user, NotificationType.client_order_ending_7d)
    assert "NOT IN" not in str(notification_visibility_predicate(user)).upper()

    user.role_muted_notification_types = types_in_group("contracts_order_ending")
    assert not user_can_receive_notification(
        user, NotificationType.client_order_ending_7d
    )
    assert user_can_receive_notification(user, NotificationType.contract_ending)
    assert "NOT IN" in str(notification_visibility_predicate(user)).upper()


def test_matrix_covers_the_six_working_roles():
    assert {role.value for role in MATRIX_ROLES} == {
        "admin",
        "head_of_recruitment",
        "delivery_lead",
        "recruiter",
        "talent_community_manager",
        "finance",
    }


def test_entrypoint_mirrors_the_digest_opt_out_migration():
    path = _BACKEND / "alembic" / "versions" / "0425_daily_digest_opt_out.py"
    spec = importlib.util.spec_from_file_location("m0425", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert migration.ADD_DAILY_DIGEST_EMAIL_ENABLED in entrypoint
    assert "IF NOT EXISTS" in migration.ADD_DAILY_DIGEST_EMAIL_ENABLED
    assert User.__table__.c.daily_digest_email_enabled.nullable is False


def test_email_policy_changes_name_only_what_changed():
    before = delivery.DeliveryPolicy.from_value(
        {
            "enabled": True,
            "send_not_before": _AT,
            "types": {
                "daily_digest": {"email_enabled": True, "send_not_before": _AT},
                "mentions": {"email_enabled": True, "send_not_before": _AT},
            },
        }
    )
    after = delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            before,
            enabled=True,
            toggles={"daily_digest": False},
            now=datetime(2026, 10, 9, 8, 21, tzinfo=timezone.utc),
        )
    )
    changes = delivery.policy_changes(before, after)
    assert changes == {"types": {"daily_digest": {"from": True, "to": False}}}
    assert "Poranny skrót" in delivery._changes_summary(changes)
    assert delivery.policy_changes(before, before) == {}


# ── API i baza ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def clean_role_mutes():
    """Tabela ról jest wspólna dla całej bazy testowej — sprzątamy przed i po.

    Wyłączenie zostawione po teście ucinałoby powiadomienia adminom w cudzych
    testach (ta sama pułapka co przy wyciszeniach osoby).
    """

    async def _clear() -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == SETTING_KEY))
            await db.commit()

    await _clear()
    yield
    await _clear()


async def _admin_id(app_client: AsyncClient) -> int:
    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
    assert uid is not None
    return uid


async def _seed(user_id: int, ntype: NotificationType, *, created_at=None) -> int:
    async with AsyncSessionLocal() as db:
        row = Notification(
            user_id=user_id,
            title=f"t-{uuid.uuid4().hex[:6]}",
            message="body",
            notification_type=ntype,
            is_read=False,
        )
        if created_at is not None:
            row.created_at = created_at
        db.add(row)
        await db.commit()
        return row.id


async def _is_read(notification_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            await db.scalar(
                select(Notification.is_read).where(Notification.id == notification_id)
            )
        )


async def _bell_ids(app_client: AsyncClient, headers: dict[str, str]) -> set[int]:
    resp = await app_client.get("/api/notifications?limit=200", headers=headers)
    assert resp.status_code == 200
    return {item["id"] for item in resp.json()["items"]}


@pytest.mark.asyncio
async def test_view_lists_roles_groups_and_counts(
    app_client: AsyncClient, app_auth_headers: dict[str, str], clean_role_mutes
):
    uid = await _admin_id(app_client)
    await _seed(uid, NotificationType.client_order_ending_14d)

    resp = await app_client.get(
        "/api/settings/notification-roles", headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["revision"] == 0
    assert [role["key"] for role in body["roles"]] == [r.value for r in MATRIX_ROLES]
    admin_role = next(role for role in body["roles"] if role["key"] == "admin")
    assert admin_role["accounts"] >= 1
    categories = {category["key"]: category for category in body["categories"]}
    assert set(categories) == {category.value for category in CATEGORY_INFO}
    assert categories["mentions"]["mandatory"] is True
    contracts = {group["key"]: group for group in categories["contracts"]["groups"]}
    assert contracts["contracts_order_ending"]["muted"]["admin"] is False
    assert contracts["contracts_order_ending"]["received_30d"]["admin"] >= 1


@pytest.mark.asyncio
async def test_muting_a_group_for_admins_hides_it_and_reenabling_marks_window_read(
    app_client: AsyncClient, app_auth_headers: dict[str, str], clean_role_mutes
):
    uid = await _admin_id(app_client)
    older = await _seed(
        uid,
        NotificationType.client_order_ending_14d,
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    other = await _seed(uid, NotificationType.contract_ending)
    assert {older, other} <= await _bell_ids(app_client, app_auth_headers)

    muted = await app_client.put(
        "/api/settings/notification-roles",
        headers=app_auth_headers,
        json={
            "revision": 0,
            "changes": [
                {"role": "admin", "group": "contracts_order_ending", "muted": True}
            ],
        },
    )
    assert muted.status_code == 200, muted.text
    assert muted.json()["revision"] == 1

    # Producent omijający `emit` (skaner zamówień) zapisuje wiersz mimo wyłączenia.
    during = await _seed(uid, NotificationType.client_order_ending_7d)
    visible = await _bell_ids(app_client, app_auth_headers)
    assert older not in visible and during not in visible
    assert other in visible

    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(CriticalEvent)
            .where(CriticalEvent.event_type == "notifications.role_mutes")
            .order_by(CriticalEvent.id.desc())
            .limit(1)
        )
    assert event is not None and event.entity_label == "Admin"
    assert event.details["changes"] == {
        "contracts_order_ending": {"from": False, "to": True}
    }

    unmuted = await app_client.put(
        "/api/settings/notification-roles",
        headers=app_auth_headers,
        json={
            "revision": 1,
            "changes": [
                {"role": "admin", "group": "contracts_order_ending", "muted": False}
            ],
        },
    )
    assert unmuted.status_code == 200, unmuted.text
    assert {older, during} <= await _bell_ids(app_client, app_auth_headers)
    # Zaległość z czasu wyłączenia nie wraca jako nieprzeczytana; starsza zostaje.
    assert await _is_read(during) is True
    assert await _is_read(older) is False


@pytest.mark.asyncio
async def test_stale_revision_mandatory_group_and_noop_are_refused_or_ignored(
    app_client: AsyncClient, app_auth_headers: dict[str, str], clean_role_mutes
):
    change = {"role": "finance", "group": "candidates", "muted": True}
    first = await app_client.put(
        "/api/settings/notification-roles",
        headers=app_auth_headers,
        json={"revision": 0, "changes": [change]},
    )
    assert first.status_code == 200
    stale = await app_client.put(
        "/api/settings/notification-roles",
        headers=app_auth_headers,
        json={"revision": 0, "changes": [{**change, "muted": False}]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_notification_roles"

    # Ten sam stan wysłany ponownie niczego nie zapisuje i nie podbija wersji.
    noop = await app_client.put(
        "/api/settings/notification-roles",
        headers=app_auth_headers,
        json={"revision": 1, "changes": [change]},
    )
    assert noop.status_code == 200 and noop.json()["revision"] == 1

    for bad in (
        {"role": "admin", "group": "mentions", "muted": True},
        {"role": "trainee", "group": "candidates", "muted": True},
        {"role": "admin", "group": "nie_ma_takiej", "muted": True},
    ):
        refused = await app_client.put(
            "/api/settings/notification-roles",
            headers=app_auth_headers,
            json={"revision": 1, "changes": [bad]},
        )
        assert refused.status_code == 422, bad


@pytest.mark.asyncio
async def test_preferences_say_when_the_role_switched_a_category_off(
    app_client: AsyncClient, app_auth_headers: dict[str, str], clean_role_mutes
):
    resp = await app_client.put(
        "/api/settings/notification-roles",
        headers=app_auth_headers,
        json={
            "revision": 0,
            "changes": [
                {"role": "admin", "group": "deadlines", "muted": True},
                # Jedna z sześciu grup kategorii — kategoria nie jest wyłączona cała.
                {"role": "admin", "group": "contracts_order_ending", "muted": True},
            ],
        },
    )
    assert resp.status_code == 200
    prefs = await app_client.get(
        "/api/notifications/preferences", headers=app_auth_headers
    )
    by_key = {category["key"]: category for category in prefs.json()["categories"]}
    assert by_key["deadlines"]["role_muted"] is True
    assert by_key["contracts"]["role_muted"] is False
    assert by_key["pipeline"]["role_muted"] is False


@pytest.mark.asyncio
async def test_digest_opt_out_removes_the_account_from_recipients(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.tasks import daily_digest_email

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        staying = User(
            email=f"digest-on-{suffix}@example.com",
            password_hash=hash_password("x"),
            name="Digest On",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        opted_out = User(
            email=f"digest-off-{suffix}@example.com",
            password_hash=hash_password("x"),
            name="Digest Off",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            daily_digest_email_enabled=False,
        )
        db.add_all([staying, opted_out])
        await db.commit()
        ids = (staying.id, opted_out.id)
    try:
        async with AsyncSessionLocal() as db:
            recipients = {user.id for user in await daily_digest_email._recipients(db)}
        assert ids[0] in recipients
        assert ids[1] not in recipients
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.id.in_(ids)))
            await db.commit()

    # Własny wyłącznik zapisuje się przez preferencje konta; admin bez roli
    # ze skrótu dostaje informację, że skrót do niego nie trafia.
    uid = await _admin_id(app_client)
    try:
        saved = await app_client.patch(
            "/api/users/me/preferences",
            headers=app_auth_headers,
            json={"daily_digest_email_enabled": False},
        )
        assert saved.status_code == 200
        assert saved.json()["daily_digest_email_enabled"] is False
        assert saved.json()["daily_digest_email_available"] is False
    finally:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, uid)
            user.daily_digest_email_enabled = True
            await db.commit()
