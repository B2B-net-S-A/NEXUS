"""Alarm o masowym przeglądaniu CV (0504, 22.10.2026) — reguły bez bazy.

Progi z ruchu produkcji (30 dni do 22.10.2026): 99. percentyl rekruterów
33 kandydatów w godzinę, na dysk najwyżej 20 plików dziennie. Juniorzy
z 12.10 (konta z tego dnia) pojedynczo mieli do 55 kandydatów dziennie —
złapać ich muszą niższe progi nowych kont i alarm „nowe konta naraz”.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.notification import NotificationType
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
