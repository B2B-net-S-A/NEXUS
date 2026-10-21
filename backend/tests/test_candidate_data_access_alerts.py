"""Alarm o masowym przeglądaniu CV (0504, 22.10.2026) — reguły bez bazy.

Progi z ruchu produkcji (30 dni do 22.10.2026): 99. percentyl rekruterów
33 kandydatów w godzinę, na dysk najwyżej 20 plików dziennie. Juniorzy
z 12.10 (konta z tego dnia) pojedynczo mieli do 55 kandydatów dziennie —
złapać ich muszą niższe progi nowych kont i alarm „nowe konta naraz”.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity

from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import candidate_data_access_alerts as alerts
from app.services.notification_access import (
    notification_visibility_predicate,
    unmapped_notification_types,
    user_may_receive_type,
)
from app.services.notification_categories import NotificationCategory, category_for
from app.services.notification_delivery import (
    CATALOG,
    IMMEDIATE_KINDS,
    immediate_email_kind,
)
from app.services.notification_email_prefs import APPLIES, _Context
from app.services.section_permissions import ProductSection

BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=400)
NEW = NOW - timedelta(days=3)


def _usage(created: datetime, **counts: int) -> alerts.Usage:
    return alerts.Usage(
        user_id=7, name="Jan Próbny", account_created_at=created, **counts
    )


def _user(role: UserRole, *extra: UserRole) -> User:
    return User(
        id=1,
        email="x@example.com",
        name="X",
        role=role,
        roles=[role.value, *(r.value for r in extra)],
        is_active=True,
    )


def test_busy_recruiter_day_from_production_is_not_an_alarm() -> None:
    # 99. percentyl godziny i maksimum zapisów na dysk z 30 dni produkcji.
    usage = _usage(
        OLD, candidates_last_hour=33, candidates_today=119, disk_files_today=20
    )
    assert alerts.reasons(usage, new_account=False) == []


def test_thresholds_are_exclusive() -> None:
    at_limit = _usage(
        OLD,
        candidates_last_hour=alerts.HOUR_CANDIDATES,
        disk_files_today=alerts.DAY_DISK_FILES,
        export_rows_today=alerts.DAY_EXPORT_ROWS,
    )
    assert alerts.reasons(at_limit, new_account=False) == []
    over = _usage(
        OLD,
        candidates_last_hour=alerts.HOUR_CANDIDATES + 1,
        disk_files_today=alerts.DAY_DISK_FILES + 1,
        export_rows_today=alerts.DAY_EXPORT_ROWS + 1,
    )
    found = alerts.reasons(over, new_account=False)
    assert len(found) == 3
    assert any("w ostatniej godzinie" in r for r in found)
    assert any("na dysk" in r for r in found)
    assert any("eksport" in r for r in found)


def test_new_account_has_half_thresholds() -> None:
    # Junior z 12.10: 25 kandydatów w godzinę i 13 plików na dysk.
    usage = _usage(NEW, candidates_last_hour=25, disk_files_today=13)
    assert alerts.is_new_account(usage, NOW)
    assert len(alerts.reasons(usage, new_account=True)) == 2
    assert alerts.reasons(usage, new_account=False) == []


def test_account_age_decides_new_account() -> None:
    assert not alerts.is_new_account(_usage(OLD), NOW)
    assert not alerts.is_new_account(
        _usage(NOW - timedelta(days=alerts.NEW_ACCOUNT_DAYS)), NOW
    )
    assert alerts.is_new_account(_usage(NOW - timedelta(days=1)), NOW)
    unknown = alerts.Usage(user_id=1, name="X", account_created_at=None)
    assert not alerts.is_new_account(unknown, NOW)


def test_alert_text_says_nothing_was_blocked_and_how_to_react() -> None:
    usage = _usage(
        NEW, candidates_last_hour=25, candidates_today=55, disk_files_today=13
    )
    found = alerts.reasons(usage, new_account=True)
    title, message = alerts.alert_text(usage, found, new_account=True, now=NOW)
    assert title.startswith("Jan Próbny")
    assert "55 kandydatów" in message
    assert "09.10.2026" in message  # data założenia konta w kalendarzu firmy
    assert "niczego nie zablokował" in message
    assert "Osoby i role" in message


def test_burst_text_lists_new_accounts() -> None:
    accounts = [
        alerts.Usage(user_id=i, name=f"Osoba {i}", account_created_at=NEW)
        for i in range(12)
    ]
    title, message = alerts.burst_text(accounts)
    assert title.startswith("12 nowe konta")
    assert "Osoba 0" in message and "i 2 innych" in message


def test_type_is_system_category_and_immediate_mail() -> None:
    ntype = NotificationType.candidate_data_access_alert
    assert category_for(ntype) is NotificationCategory.system
    assert "data_access_alert" in IMMEDIATE_KINDS
    assert {spec["id"] for spec in CATALOG} >= {"data_access_alert"}
    assert (
        immediate_email_kind(ntype, title="x", related_entity_type="user")
        == "data_access_alert"
    )


def test_admin_and_head_of_recruitment_see_the_alarm_recruiter_does_not() -> None:
    ntype = NotificationType.candidate_data_access_alert
    assert user_may_receive_type(_user(UserRole.admin), ntype)
    assert user_may_receive_type(_user(UserRole.head_of_recruitment), ntype)
    # Head of Recruitment jako rola dodatkowa też.
    assert user_may_receive_type(
        _user(UserRole.delivery_lead, UserRole.head_of_recruitment), ntype
    )
    assert not user_may_receive_type(_user(UserRole.recruiter), ntype)
    assert not user_may_receive_type(_user(UserRole.delivery_lead), ntype)


def test_list_predicate_shows_the_alarm_to_head_of_recruitment_only() -> None:
    def sql_for(user: User) -> str:
        user.effective_section_access = {
            section.value: "write" for section in ProductSection
        }
        return str(
            notification_visibility_predicate(user).compile(
                compile_kwargs={"literal_binds": True}
            )
        )

    assert "candidate_data_access_alert" in sql_for(_user(UserRole.head_of_recruitment))
    assert "candidate_data_access_alert" not in sql_for(_user(UserRole.recruiter))
    assert unmapped_notification_types() == frozenset()


def test_mail_applies_to_admin_and_head_of_recruitment_only() -> None:
    applies = APPLIES["data_access_alert"]
    assert applies(_user(UserRole.admin), _Context())
    assert applies(_user(UserRole.head_of_recruitment), _Context())
    assert not applies(_user(UserRole.recruiter), _Context())


def test_new_type_is_mirrored_in_entrypoint() -> None:
    source = (
        BACKEND / "alembic" / "versions" / "0504_candidate_data_access_alert.py"
    ).read_text(encoding="utf-8")
    assert "'candidate_data_access_alert'" in source
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    statement = (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
        "'candidate_data_access_alert'"
    )
    assert re.search(re.escape(f'"{statement}"'), entrypoint)


# ── Z bazą: zapytanie i przebieg skanera (sprawdza CI) ───────────────────────

# Okno w przyszłości: wspólna baza testowa nie ma w nim cudzych zdarzeń.
DB_NOW = datetime(2030, 1, 15, 10, 0, tzinfo=timezone.utc)


async def _account(db, label: str, role: UserRole, created_at: datetime) -> User:
    tag = uuid.uuid4().hex[:8]
    user = User(
        email=f"data-access-{label}-{tag}@example.com",
        password_hash=hash_password(f"T3st_{tag}!Access"),
        name=f"Dostęp {label} {tag}",
        role=role,
        roles=[role.value],
        is_active=True,
        created_at=created_at,
    )
    db.add(user)
    await db.flush()
    return user


def _event(user: User, action: str, entity_id: int, minutes_ago: int, **details):
    return Activity(
        entity_type="candidate",
        entity_id=entity_id,
        action=action,
        user_id=user.id,
        details=details,
        external_source="audit",
        created_at=DB_NOW - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_scan_alerts_admin_once_per_person_and_burst_does_not_collide() -> None:
    old = DB_NOW - timedelta(days=400)
    async with AsyncSessionLocal() as db:
        admin = await _account(db, "admin", UserRole.admin, old)
        heavy = await _account(db, "godzina", UserRole.recruiter, old)
        zipper = await _account(db, "zip", UserRole.recruiter, old)
        exporter = await _account(db, "eksport", UserRole.recruiter, old)
        quiet = await _account(db, "spokojny", UserRole.recruiter, old)
        juniors = [
            await _account(
                db, f"junior{i}", UserRole.recruiter, DB_NOW - timedelta(days=1)
            )
            for i in range(3)
        ]
        events = [
            _event(heavy, "document_downloaded", 900_000 + i, 10, disposition="inline")
            for i in range(alerts.HOUR_CANDIDATES + 1)
        ]
        # Wczoraj (przed północą Warszawy) się nie liczy do „dziś”.
        events += [
            _event(
                quiet,
                "document_downloaded",
                910_000 + i,
                60 * 12,
                disposition="attachment",
            )
            for i in range(alerts.DAY_DISK_FILES + 5)
        ]
        events += [
            _event(quiet, "document_downloaded", 920_000, 5, disposition="attachment")
        ]
        events.append(
            _event(
                zipper,
                "bulk_cv_downloaded",
                0,
                30,
                included_count=alerts.DAY_DISK_FILES + 1,
            )
        )
        events.append(
            _event(
                exporter,
                "export_requested",
                0,
                30,
                row_count=alerts.DAY_EXPORT_ROWS + 1,
            )
        )
        events += [
            _event(j, "cv_downloaded", 930_000 + n, 5) for n, j in enumerate(juniors)
        ]
        db.add_all(events)
        await db.commit()
        everyone = [admin, heavy, zipper, exporter, quiet, *juniors]

    try:
        async with AsyncSessionLocal() as db:
            usages = {u.user_id: u for u in await alerts.collect(db, DB_NOW)}
        assert usages[heavy.id].candidates_last_hour == alerts.HOUR_CANDIDATES + 1
        assert usages[zipper.id].disk_files_today == alerts.DAY_DISK_FILES + 1
        assert usages[exporter.id].export_rows_today == alerts.DAY_EXPORT_ROWS + 1
        assert usages[quiet.id].disk_files_today == 1
        assert usages[quiet.id].candidates_today == 1

        async with AsyncSessionLocal() as db:
            await alerts.scan_once(db, DB_NOW)
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Notification.related_entity_id, Notification.title).where(
                        Notification.user_id == admin.id,
                        Notification.notification_type
                        == NotificationType.candidate_data_access_alert,
                    )
                )
            ).all()
        about = {entity for entity, _ in rows}
        assert {heavy.id, zipper.id, exporter.id, alerts.BURST_ENTITY_ID} <= about
        assert quiet.id not in about
        assert len(rows) == len(about)

        # Drugi przebieg tego samego dnia nie dokłada wpisów.
        async with AsyncSessionLocal() as db:
            assert await alerts.scan_once(db, DB_NOW) == 0
    finally:
        ids = [u.id for u in everyone]
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Notification).where(
                    Notification.notification_type
                    == NotificationType.candidate_data_access_alert
                )
            )
            await db.execute(delete(Activity).where(Activity.user_id.in_(ids)))
            await db.commit()
