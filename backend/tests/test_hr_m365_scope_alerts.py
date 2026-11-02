"""Alarm o skrzynkach poza zakresem aplikacji „NEXUS Kadry” (0630). Dane fikcyjne.

02.11.2026 wszystkie konta założone 18–29.10 dostały 403 przy odczycie skrzynki
i nikt nie dostał sygnału: osoba poza grupą wychodzi na urlop bez autoodpowiedzi,
wydarzenia i kopii poczty do zastępcy.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.hr_leave import HrM365MailboxState
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.services import notification_access as na
from app.services.hr.m365 import executor, scope_alerts
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    NotificationCategory,
)
from app.services.notification_delivery import notification_kind
from tests.hr.m365_helpers import make_user

BACKEND = Path(__file__).resolve().parents[1]
NTYPE = NotificationType.hr_m365_scope_missing
FORBIDDEN = "forbidden (403)"


async def _admin(db):
    return await make_user(db, role="admin", profile=False)


async def _with_error(db, user, error: str = FORBIDDEN) -> None:
    await executor.save_mailbox_state(db, user.id, last_error=error)


async def _state(db, user_id: int) -> HrM365MailboxState:
    return await db.get(HrM365MailboxState, user_id)


async def _alarms(db, admin_id: int) -> list[Notification]:
    rows = await db.scalars(
        select(Notification).where(
            Notification.user_id == admin_id,
            Notification.notification_type == NTYPE,
        )
    )
    return list(rows.all())


async def _scan_and_read(db, admin_id: int, user_ids: list[int]) -> list[Notification]:
    await scope_alerts.scan_once(db, mode="live", user_ids=user_ids)
    return await _alarms(db, admin_id)


async def test_person_with_403_gives_alarm_with_the_fix() -> None:
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        person = await make_user(db, name="Anna Przykładowa")
        await _with_error(db, person)
        await db.commit()
        alarms = await _scan_and_read(db, admin.id, [person.id])

    (alarm,) = alarms
    assert alarm.title == "NEXUS nie widzi skrzynki 1 osoby"
    assert f"Anna Przykładowa ({person.email})" in alarm.message
    assert (
        f"Add-DistributionGroupMember -Identity {scope_alerts.SCOPE_GROUP}"
        in alarm.message
    )
    assert "Test-ServicePrincipalAuthorization" in alarm.message
    assert alarm.link == "/settings/hr?zakladka=urlopy"
    # Reguła z 02.11: uprawnienie w Entra działałoby na całą firmę.
    assert "Entra" in alarm.message
    assert "Zostaw poza grupą" in alarm.message


async def test_alarm_lists_every_person_and_counts_them() -> None:
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        first = await make_user(db, name="Anna Przykładowa")
        second = await make_user(db, name="Jan Przykładowy")
        await _with_error(db, first)
        await _with_error(db, second)
        await db.commit()
        alarms = await _scan_and_read(db, admin.id, [first.id, second.id])

    (alarm,) = alarms
    assert alarm.title == "NEXUS nie widzi skrzynek 2 osób"
    assert first.email in alarm.message and second.email in alarm.message


@pytest.mark.parametrize(
    "error", [None, "throttled (429)", "no_mailbox (404)", "server_error (500)"]
)
async def test_no_403_gives_no_alarm(error) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        person = await make_user(db)
        await _with_error(db, person, error)
        await db.commit()
        alarms = await _scan_and_read(db, admin.id, [person.id])

    assert alarms == []


async def test_second_alarm_the_same_day_does_not_go_out() -> None:
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        person = await make_user(db)
        await _with_error(db, person)
        await db.commit()
        await scope_alerts.scan_once(db, mode="live", user_ids=[person.id])
        second = await scope_alerts.scan_once(db, mode="live", user_ids=[person.id])
        alarms = await _alarms(db, admin.id)

    assert second == 0
    assert len(alarms) == 1


async def test_switch_turns_the_alarm_off(monkeypatch) -> None:
    monkeypatch.setenv("HR_M365_SCOPE_ALERTS_ENABLED", "false")
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        person = await make_user(db)
        await _with_error(db, person)
        await db.commit()
        alarms = await _scan_and_read(db, admin.id, [person.id])

    assert alarms == []


@pytest.mark.parametrize("mode", ["off", "simulate"])
async def test_only_live_mode_alerts(mode) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        person = await make_user(db)
        await _with_error(db, person)
        await db.commit()
        await scope_alerts.scan_once(db, mode=mode, user_ids=[person.id])
        alarms = await _alarms(db, admin.id)

    assert alarms == []


@pytest.mark.parametrize(
    ("active", "status"), [(False, "active"), (True, "exited"), (False, "exited")]
)
async def test_person_after_leaving_is_not_listed(active, status) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        person = await make_user(db)
        person.is_active = active
        await db.execute(
            update(EmployeeProfile)
            .where(EmployeeProfile.user_id == person.id)
            .values(employment_status=status)
        )
        await _with_error(db, person)
        await db.commit()
        alarms = await _scan_and_read(db, admin.id, [person.id])

    assert alarms == []


async def test_account_without_profile_is_not_listed() -> None:
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        person = await make_user(db, profile=False)
        await _with_error(db, person)
        await db.commit()
        alarms = await _scan_and_read(db, admin.id, [person.id])

    assert alarms == []


async def test_person_left_outside_on_purpose_is_not_listed() -> None:
    # Decyzja Artura 02.11.2026: osoba z Zarządu zostaje poza grupą.
    async with AsyncSessionLocal() as db:
        admin = await _admin(db)
        exempt = await make_user(db, name="Osoba Wyłączona")
        other = await make_user(db, name="Osoba Dopisywana")
        await _with_error(db, exempt)
        await _with_error(db, other)
        scope_alerts.set_exempt(await _state(db, exempt.id), exempt=True)
        await db.commit()
        alarms = await _scan_and_read(db, admin.id, [exempt.id, other.id])

    (alarm,) = alarms
    assert "Osoba Dopisywana" in alarm.message
    assert "Osoba Wyłączona" not in alarm.message


async def test_flag_survives_saving_the_mailbox_state() -> None:
    async with AsyncSessionLocal() as db:
        person = await make_user(db)
        await _with_error(db, person)
        scope_alerts.set_exempt(await _state(db, person.id), exempt=True)
        await db.commit()
        await executor.save_mailbox_state(
            db, person.id, events={"leave": "event"}, last_error=FORBIDDEN
        )
        await db.commit()
        state = await _state(db, person.id)

    assert scope_alerts.is_exempt(state.state)
    assert state.state["events"] == {"leave": "event"}


class _FakeDb:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1


def _pass_result(monkeypatch, result: dict) -> list[object]:
    from app.services.hr.m365 import reconcile

    calls: list[object] = []

    async def run_once(_db):
        return result

    async def scan_once(db):
        calls.append(db)
        return 1

    monkeypatch.setattr(reconcile, "run_once", run_once)
    monkeypatch.setattr(scope_alerts, "scan_once", scan_once)
    return calls


async def test_finished_pass_runs_the_scan(monkeypatch) -> None:
    from app.tasks.hr_loops import hr_m365_reconcile_job

    calls = _pass_result(monkeypatch, {"mode": "live", "mailboxes": 3})
    result = await hr_m365_reconcile_job(_FakeDb())
    assert len(calls) == 1
    assert result["scope_alerts"] == 1


@pytest.mark.parametrize(
    "outcome",
    [
        {"mode": "live", "skipped": "already_ran"},
        {"status": "disabled"},
        {"mode": "live", "failed": "RuntimeError"},
    ],
)
async def test_pass_without_fresh_reads_does_not_run_the_scan(
    monkeypatch, outcome
) -> None:
    from app.tasks.hr_loops import hr_m365_reconcile_job

    calls = _pass_result(monkeypatch, outcome)
    await hr_m365_reconcile_job(_FakeDb())
    assert calls == []


async def test_failed_scan_does_not_break_the_pass(monkeypatch) -> None:
    from app.tasks.hr_loops import hr_m365_reconcile_job

    _pass_result(monkeypatch, {"mode": "live", "mailboxes": 3})

    async def broken(_db):
        raise RuntimeError("awaria")

    monkeypatch.setattr(scope_alerts, "scan_once", broken)
    db = _FakeDb()
    result = await hr_m365_reconcile_job(db)
    assert result == {"mode": "live", "mailboxes": 3}
    assert db.rollbacks == 1


def test_text_names_the_address_once_and_keeps_the_placeholder() -> None:
    person = SimpleNamespace(name="Anna", address="anna@example.test")
    title, message = scope_alerts.alert_text([person])
    assert title == "NEXUS nie widzi skrzynki 1 osoby"
    assert message.count("anna@example.test") == 1
    assert "<adres>" in message


def test_type_is_admin_only_system_and_mailed_at_once() -> None:
    assert NTYPE in na.ADMIN_ONLY_NOTIFICATION_TYPES
    assert CATEGORY_BY_TYPE[NTYPE] == NotificationCategory.system
    assert notification_kind(NTYPE) == "system_failure"


def test_new_type_is_mirrored_in_entrypoint_and_migration() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    enum_block = entrypoint.split("_ENUM_STATEMENTS = [", 1)[1].split("\n]", 1)[0]
    assert "ADD VALUE IF NOT EXISTS 'hr_m365_scope_missing'" in enum_block
    migration = next(
        (BACKEND / "alembic" / "versions").glob("*_hr_m365_scope_alert.py")
    )
    assert re.search(
        r"ADD VALUE IF NOT EXISTS 'hr_m365_scope_missing'", migration.read_text()
    )
