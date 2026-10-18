"""Kartoteka z katalogu Microsoft 365 (``profile_sync``) na atrapie katalogu.

Pola z katalogu trafiają do kartoteki, ślad tylko przy zmianie, ręczna zmiana
Kadr wygrywa z katalogiem (Compass nadpisywał ją co tydzień), wyczyszczone
pole wraca z katalogu; 404 pomija osobę, 403 przerywa przebieg i zapala
sondę; symulacja nie zmienia kartoteki. Dane fikcyjne.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from typing import Any, Optional

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_ops import HrAuditEvent, HrJobRun
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.services.hr import health, people
from app.services.hr.m365 import profile_sync
from app.services.hr.m365.directory import (
    USER_SELECT,
    SimulatedDirectoryOps,
    profile_values,
)
from app.services.hr.m365.ops import MailboxError
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.hr.m365_helpers import at, make_user

D = date
BASE = "/api/hr/admin/m365"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeDirectory:
    """Katalog w pamięci: brak konta = 404, ``fail`` wstrzykuje błąd dla UPN.

    ``managers`` — UPN przełożonego z katalogu (brak wpisu = bez przełożonego).
    """

    def __init__(self, accounts: Optional[dict[str, dict[str, Any]]] = None) -> None:
        self.accounts = accounts or {}
        self.failures: dict[str, MailboxError] = {}
        self.calls: list[str] = []
        self.managers: dict[str, str] = {}

    def fail(self, upn: str, status: int) -> None:
        self.failures[upn] = MailboxError(status)

    async def get_user(self, upn: str) -> dict[str, Any]:
        self.calls.append(upn)
        if upn in self.failures:
            raise self.failures[upn]
        if upn not in self.accounts:
            raise MailboxError(404, "Request_ResourceNotFound")
        return copy.deepcopy(self.accounts[upn])

    async def get_manager(self, upn: str) -> Optional[str]:
        return self.managers.get(upn)

    async def aclose(self) -> None:
        return None


def account(
    title: Optional[str] = "Rekruterka",
    department: Optional[str] = "Rekrutacja",
    mobile: Optional[str] = "+48 500 000 001",
    business: Optional[list[str]] = None,
    enabled: bool = True,
) -> dict[str, Any]:
    return {
        "jobTitle": title,
        "department": department,
        "mobilePhone": mobile,
        "businessPhones": business or [],
        "accountEnabled": enabled,
    }


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def people_module():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: key == "people" for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest_asyncio.fixture(autouse=True)
async def _reset_runs():
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM hr_job_runs WHERE kind = :kind"),
            {"kind": profile_sync.JOB_KIND},
        )
        await db.commit()
    yield


async def _profile(db, user_id: int) -> EmployeeProfile:
    profile = await db.scalar(
        select(EmployeeProfile)
        .where(EmployeeProfile.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    assert profile is not None
    return profile


async def _sync_trail(db, user_id: int) -> list[list[str]]:
    rows = await db.scalars(
        select(HrAuditEvent)
        .where(
            HrAuditEvent.subject_user_id == user_id,
            HrAuditEvent.action == profile_sync.SYNC_ACTION,
        )
        .order_by(HrAuditEvent.id)
    )
    return [row.details["fields"] for row in rows]


# ── Czyste reguły ────────────────────────────────────────────────────────────


def test_profile_values_from_graph() -> None:
    assert profile_values(account(business=["+48 22 000 00 00"])) == {
        "job_title": "Rekruterka",
        "department": "Rekrutacja",
        "phone": "+48 500 000 001",
    }
    # Bez komórki — pierwszy niepusty numer biurowy; puste pola = None.
    assert profile_values(
        account(title="  ", department=None, mobile="", business=["", "+48 22 1"])
    ) == {"job_title": None, "department": None, "phone": "+48 22 1"}
    long_title = profile_values({"jobTitle": "x\x00" * 300})["job_title"]
    assert long_title == "x" * 200
    assert profile_values({"jobTitle": 7, "businessPhones": "nie lista"}) == {
        "job_title": None,
        "department": None,
        "phone": None,
    }


def test_manual_fields_pin_until_next_sync_write() -> None:
    later = T0.replace(day=2)
    latest = T0.replace(day=3)
    events = [
        ("profile_created", {"fields": ["job_title", "phone", "manager_user_id"]}, T0),
        (profile_sync.SYNC_ACTION, {"fields": ["phone"]}, later),
        ("profile_updated", {"fields": ["department"]}, latest),
        ("profile_updated", {"fields": "zepsute"}, latest),
        ("profile_updated", None, latest),
    ]
    assert profile_sync.manual_fields(events) == {"job_title", "department"}
    assert profile_sync.manual_fields([]) == set()


def test_plan_changes_respects_pins_and_never_clears() -> None:
    current = {"job_title": "Lider zespołu", "department": None, "phone": "+48 1"}
    remote = {"job_title": "Rekruter", "department": "Rekrutacja", "phone": None}
    changes, kept = profile_sync.plan_changes(current, remote, {"job_title"})
    assert changes == {"department": "Rekrutacja"}
    assert kept == ["job_title"]
    # Pole wyczyszczone przez Kadry (przypięte, ale puste) wypełnia katalog.
    changes, kept = profile_sync.plan_changes(
        {"job_title": None}, {"job_title": "Rekruter"}, {"job_title"}
    )
    assert changes == {"job_title": "Rekruter"} and kept == []
    # Ta sama wartość — nic do zrobienia, także przy przypięciu.
    assert profile_sync.plan_changes(
        {"job_title": "Rekruter"}, {"job_title": "Rekruter"}, {"job_title"}
    ) == ({}, [])


# ── Przebieg na bazie ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_live_sync_writes_fields_once_a_day_with_trail_only_on_change(
    people_module, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "HR_M365_MAILBOX_ALLOWLIST", "")
    async with AsyncSessionLocal() as db:
        person = await make_user(db, name="Anna Przykładowa")
        await db.commit()
        directory = FakeDirectory({person.email: account()})

        early = await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 20), 5, 50),
            user_ids=[person.id],
        )
        first = await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 20), 6, 10),
            user_ids=[person.id],
        )
        again = await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 20), 9),
            user_ids=[person.id],
        )
        next_day = await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 21), 6, 10),
            user_ids=[person.id],
        )
        profile = await _profile(db, person.id)
        trail = await _sync_trail(db, person.id)
        run = await db.scalar(
            select(HrJobRun).where(
                HrJobRun.kind == profile_sync.JOB_KIND,
                HrJobRun.period_key == "2026-10-20",
            )
        )

    assert early == {"mode": "live", "skipped": "before_06"}
    assert first["updated"] == 1 and first["read"] == 1
    assert again == {"mode": "live", "skipped": "already_ran"}
    assert next_day["unchanged"] == 1 and "updated" not in next_day
    assert (profile.job_title, profile.department, profile.phone) == (
        "Rekruterka",
        "Rekrutacja",
        "+48 500 000 001",
    )
    assert profile.m365_synced_at == at(D(2026, 10, 21), 6, 10)
    # Ślad tylko przy zmianie i bez wartości (same nazwy pól).
    assert trail == [["department", "job_title", "phone"]]
    assert run.status == "done" and run.counts["updated"] == 1
    assert directory.calls == [person.email, person.email]


@pytest.mark.asyncio
async def test_manual_change_by_kadry_wins_until_cleared(people_module) -> None:
    async with AsyncSessionLocal() as db:
        kadry = await make_user(db, profile=False)
        person = await make_user(db)
        await db.commit()
        directory = FakeDirectory({person.email: account(title="Rekruter")})
        await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 20), 7),
            user_ids=[person.id],
        )

        # Kadry poprawiają stanowisko ręcznie; katalog dalej mówi swoje
        # i jeszcze zmienia dział.
        await people.update_profile(
            db,
            user_id=person.id,
            values={"job_title": "Starsza rekruterka"},
            actor=kadry,
        )
        await db.commit()
        directory.accounts[person.email] = account(
            title="Rekruter", department="Delivery"
        )
        pinned = await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 21), 7),
            user_ids=[person.id],
        )
        after_pin = await _profile(db, person.id)
        kept_title = after_pin.job_title
        kept_department = after_pin.department

        # Kadry czyszczą pole — wraca z katalogu, a potem znów płynie z katalogu.
        await people.update_profile(
            db, user_id=person.id, values={"job_title": None}, actor=kadry
        )
        await db.commit()
        await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 22), 7),
            user_ids=[person.id],
        )
        refilled = (await _profile(db, person.id)).job_title
        directory.accounts[person.email] = account(
            title="Lider rekrutacji", department="Delivery"
        )
        await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 23), 7),
            user_ids=[person.id],
        )
        followed = (await _profile(db, person.id)).job_title

    assert pinned["kept_manual"] == 1 and pinned["updated"] == 1
    assert kept_title == "Starsza rekruterka"
    assert kept_department == "Delivery"
    assert refilled == "Rekruter"
    assert followed == "Lider rekrutacji"


@pytest.mark.asyncio
async def test_imported_value_is_refreshed_and_empty_directory_clears_nothing(
    people_module,
) -> None:
    async with AsyncSessionLocal() as db:
        person = await make_user(db)
        profile = await _profile(db, person.id)
        # Wartości z importu Compassa (bez śladu ręcznej zmiany w NEXUSIE).
        profile.job_title = "Stare stanowisko"
        profile.phone = "+48 600 000 000"
        await db.commit()
        directory = FakeDirectory(
            {
                person.email: account(
                    title="Nowe stanowisko", department=None, mobile=None
                )
            }
        )
        result = await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 20), 7),
            user_ids=[person.id],
        )
        profile = await _profile(db, person.id)

    assert result["updated"] == 1
    assert profile.job_title == "Nowe stanowisko"
    assert profile.phone == "+48 600 000 000"
    assert profile.department is None


@pytest.mark.asyncio
async def test_missing_account_is_skipped_and_others_continue(people_module) -> None:
    async with AsyncSessionLocal() as db:
        outside = await make_user(db)
        inside = await make_user(db)
        exited = await make_user(db)
        (await _profile(db, exited.id)).employment_status = "exited"
        inactive = await make_user(db)
        inactive.is_active = False
        await db.commit()
        directory = FakeDirectory(
            {
                inside.email: account(enabled=False),
                exited.email: account(),
                inactive.email: account(),
            }
        )
        result = await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 20), 7),
            user_ids=[outside.id, inside.id, exited.id, inactive.id],
        )
        outside_profile = await _profile(db, outside.id)
        inside_profile = await _profile(db, inside.id)

    assert result["profiles"] == 2
    assert result["not_found"] == 1 and result["updated"] == 1
    # Konto wyłączone w Entra ID — liczymy, kartoteka i tak się odświeża.
    assert result["account_disabled"] == 1
    assert outside_profile.m365_synced_at is None
    assert inside_profile.m365_synced_at is not None
    assert set(directory.calls) == {outside.email, inside.email}


@pytest.mark.asyncio
async def test_forbidden_stops_the_run_and_lights_the_probe(
    people_module, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "HR_M365_MODE", "live")
    monkeypatch.setattr(settings, "HR_M365_CLIENT_SECRET_EXPIRES_ON", None)
    async with AsyncSessionLocal() as db:
        first = await make_user(db)
        second = await make_user(db)
        await db.commit()
        directory = FakeDirectory({first.email: account(), second.email: account()})
        directory.fail(first.email, 403)
        now = at(D(2026, 10, 20), 7)
        result = await profile_sync.run_once(
            db, ops=directory, mode="live", now=now, user_ids=[first.id, second.id]
        )
        calls = list(directory.calls)
        stamps = [
            (await _profile(db, user.id)).m365_synced_at for user in (first, second)
        ]
        # Rezerwacja ma czas bazy, więc sonda czyta „teraz”, nie dzień z testu.
        probe = await health.m365_state(db)

        # Uprawnienie nadane — kolejny obrót pętli tego samego dnia przejmuje
        # nieudaną rezerwację.
        directory.failures.clear()
        retried = await profile_sync.run_once(
            db,
            ops=directory,
            mode="live",
            now=at(D(2026, 10, 20), 8),
            user_ids=[first.id, second.id],
        )

    assert result["failed"] == "forbidden"
    assert calls == [first.email]
    assert stamps == [None, None]
    assert "profile_sync_forbidden" in probe and probe.startswith("degraded")
    assert retried["updated"] == 2


@pytest.mark.asyncio
async def test_simulate_reads_nothing_and_changes_nothing(people_module) -> None:
    async with AsyncSessionLocal() as db:
        person = await make_user(db)
        (await _profile(db, person.id)).job_title = "Rekruterka"
        await db.commit()
        recorder = SimulatedDirectoryOps()
        result = await profile_sync.run_once(
            db,
            ops=recorder,
            mode="simulate",
            now=at(D(2026, 10, 20), 7),
            user_ids=[person.id],
        )
        profile = await _profile(db, person.id)
        trail = await _sync_trail(db, person.id)

    assert result["mode"] == "simulate" and result["read"] == 1
    assert result["request"] == f"GET /users/{{upn}}?$select={USER_SELECT}"
    assert person.email not in str(result)
    assert result["manager_request"] == (
        "GET /users/{upn}/manager?$select=userPrincipalName"
    )
    assert recorder.requests == [
        {
            "method": "GET",
            "path": f"/users/{person.email}",
            "params": {"$select": USER_SELECT},
        },
        {
            "method": "GET",
            "path": f"/users/{person.email}/manager",
            "params": {"$select": "userPrincipalName"},
        },
    ]
    assert profile.job_title == "Rekruterka" and profile.m365_synced_at is None
    assert trail == []


@pytest.mark.asyncio
async def test_off_module_off_and_allowlist(people_module, monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        person = await make_user(db)
        other = await make_user(db)
        await db.commit()
        directory = FakeDirectory({person.email: account(), other.email: account()})
        now = at(D(2026, 10, 20), 7)

        off = await profile_sync.run_once(db, ops=directory, mode="off", now=now)
        await _set_modules({key: False for key in HR_MODULE_KEYS})
        module_off = await profile_sync.run_once(
            db, ops=directory, mode="live", now=now, user_ids=[person.id]
        )
        await _set_modules({key: key == "people" for key in HR_MODULE_KEYS})
        monkeypatch.setattr(settings, "HR_M365_MAILBOX_ALLOWLIST", person.email)
        result = await profile_sync.run_once(
            db, ops=directory, mode="live", now=now, user_ids=[person.id, other.id]
        )

    assert off == module_off == {"status": "disabled"}
    assert result["updated"] == 1 and result["not_allowlisted"] == 1
    assert directory.calls == [person.email]


# ── Karta M365 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_shows_last_profile_sync_and_secret(
    app_client, people_module, monkeypatch
) -> None:
    from app.core.scheduling import business_today

    expires = date.fromordinal(business_today().toordinal() + 12)
    monkeypatch.setattr(settings, "HR_M365_CLIENT_SECRET_EXPIRES_ON", expires)
    async with AsyncSessionLocal() as db:
        kadry = await make_user(db, profile=False)
        db.add(
            UserActionOverride(user_id=kadry.id, action="people_admin", access="manage")
        )
        person = await make_user(db)
        await db.commit()
        await profile_sync.run_once(
            db,
            ops=SimulatedDirectoryOps(),
            mode="simulate",
            now=at(D(2091, 3, 7), 7),
            user_ids=[person.id],
        )

    token = create_access_token(subject=kadry.id, role=kadry.role.value)
    response = await app_client.get(
        f"{BASE}/status", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["last_profile_sync"]["day"] == "2091-03-07"
    assert body["last_profile_sync"]["status"] == "done"
    assert body["last_profile_sync"]["counts"]["read"] == 1
    assert body["secret"] == {
        "expires_on": expires.isoformat(),
        "days_left": 12,
        "state": "expiring",
    }
