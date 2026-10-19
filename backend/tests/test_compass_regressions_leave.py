"""Błędy urlopów z Compassa, które NIE przechodzą do NEXUSA (krok 1 planu).

Każdy test odtwarza błąd opisany w raporcie rozpoznania Compassa (lista
„Podejrzane”, ``internal-leave.ts`` / ``leave-balance.ts``) i pada, gdyby
moduł urlopów NEXUSA go powtórzył:

1. „Dziś” liczone w UTC — wieczorem pozwalało anulować urlop, który już
   się zaczął w Warszawie.
2. Urlop przez Nowy Rok liczony do roku startu (HF-08).
3. B2B: dni bezpłatne zjadały pulę płatną (HF-09).
4. Pół dnia gubione w kalendarzu i saldzie (``updateLeaveEvent`` zapisywał
   wydarzenie całodniowe).
5. Admin zatwierdzał własny urlop — brak blokady samozatwierdzenia.
6. Dwóch akceptujących naraz — drugi musi dostać konflikt.
7. Przełożony mógł włączyć przekierowanie poczty pracownika bez jego zgody.
8. L4 wpisany za pracownika był odrzucany, a L4 nikogo nie powiadamiał.

Czyste funkcje tam, gdzie się da; reszta przez API i bazę. Dane fikcyjne.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
import time_machine
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_leave import HrM365Operation, LeaveRequest, LeaveRequestDay
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr.calendar import WorkCalendar
from app.services.hr.leave_m365 import LeaveSnapshot, plan_operations
from app.services.hr.leave_policy import (
    Actor,
    PoolYear,
    can_decide,
    own_cancel_refusal,
    plan_days,
    requested_days,
)
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

BASE = "/api/hr/leave"
D = Decimal
_APP = Path(__file__).resolve().parent.parent / "app"


# ── Pomocnicze ────────────────────────────────────────────────────────────────


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, profile: bool = False, **profile_values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"compass-{marker}@example.com",
        name=f"Anna Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **profile_values))
        await db.flush()
    return user


async def _grant(db, user: User, action: str) -> None:
    db.add(UserActionOverride(user_id=user.id, action=action, access="manage"))
    await db.flush()


async def _pool(db, user: User, year: int, days: str) -> None:
    db.add(LeaveEntitlement(user_id=user.id, year=year, entitlement_days=Decimal(days)))
    await db.flush()


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def modules_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _body(leave_type: str, start: date, end: date, **extra) -> dict:
    return {
        "leave_type": leave_type,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        **extra,
    }


async def _balance(app_client, user: User, year: int) -> dict:
    response = await app_client.get(
        BASE + "/balance", params={"year": year}, headers=_headers(user)
    )
    assert response.status_code == 200, response.text
    return response.json()


# ── 1. „Dziś” = kalendarz firmy ───────────────────────────────────────────────


def test_today_is_warsaw_day_in_the_utc_evening() -> None:
    # 23.12.2026 00:30 w Warszawie = 22.12 23:30 UTC. Compass (``toISOString()``)
    # widział jeszcze 22.12 i pozwalał anulować urlop zaczynający się 23.12.
    with time_machine.travel(
        datetime(2026, 12, 22, 23, 30, tzinfo=timezone.utc), tick=False
    ):
        today = business_today()
    assert today == date(2026, 12, 23)
    start = date(2026, 12, 23)
    assert own_cancel_refusal(status="approved", start=start, today=today) is not None
    utc_day = date(2026, 12, 22)
    assert own_cancel_refusal(status="approved", start=start, today=utc_day) is None


def test_leave_code_never_reads_utc_or_container_today() -> None:
    files = [
        _APP / "api" / "hr_leave.py",
        *sorted((_APP / "services" / "hr").glob("leave_*.py")),
        _APP / "services" / "hr" / "absence.py",
        _APP / "services" / "hr" / "calendar.py",
    ]
    forbidden = re.compile(r"date\.today\(\)|utcnow\(\)|\.date\(\)")
    for path in files:
        code = "\n".join(
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        assert not forbidden.search(code), path.name


# ── 2. Urlop przez Nowy Rok dzieli się na dwa lata ───────────────────────────


def test_new_year_leave_splits_days_by_calendar_year() -> None:
    days = requested_days(WorkCalendar(), date(2025, 12, 29), date(2026, 1, 2), None)
    pools = {
        2025: PoolYear(2025, D("26"), booked_paid_days=D("20")),
        2026: PoolYear(2026, D("26")),
    }
    plan = plan_days(
        leave_type="vacation", employment_type="uop", days=days, pools=pools
    )
    by_year = {split.year: split.requested for split in plan.years}
    # 29–31.12 to trzy dni 2025, 1.01 święto, 2.01 jeden dzień 2026.
    assert by_year == {2025: D("3"), 2026: D("1")}
    assert plan.years[0].remaining_after == D("3")
    assert plan.years[1].remaining_after == D("25")


def test_new_year_limit_is_checked_against_each_year() -> None:
    days = requested_days(WorkCalendar(), date(2025, 12, 29), date(2026, 1, 2), None)
    # W 2025 zostały dwa dni — nadwyżki nie wolno „przykryć” pulą 2026.
    pools = {
        2025: PoolYear(2025, D("26"), booked_paid_days=D("24")),
        2026: PoolYear(2026, D("26")),
    }
    with pytest.raises(Exception, match="W 2025 zostało 2"):
        plan_days(leave_type="vacation", employment_type="uop", days=days, pools=pools)


@pytest.mark.asyncio
async def test_new_year_leave_lands_in_two_balances(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "employee", profile=True, employment_type="uop")
        await _pool(db, worker, 2025, "26")
        await _pool(db, worker, 2026, "26")
        await db.commit()

    created = await app_client.post(
        BASE + "/requests",
        json=_body("vacation", date(2025, 12, 29), date(2026, 1, 2)),
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    assert (await _balance(app_client, worker, 2025))["pending_days"] == "3.0"
    assert (await _balance(app_client, worker, 2026))["pending_days"] == "1.0"


# ── 3. B2B: dni bezpłatne nie zjadają puli płatnej (HF-09) ───────────────────


def test_contractor_unpaid_days_do_not_consume_paid_pool() -> None:
    days = requested_days(WorkCalendar(), date(2091, 11, 12), date(2091, 11, 16), None)
    # Pula 5, wcześniej 3 dni płatne i 4 bezpłatne. Compass liczył 7 zużytych
    # (``totalVacationDaysUsed`` po wszystkich dniach) i dawał 0 płatnych.
    pools = {2091: PoolYear(2091, D("5"), booked_paid_days=D("3"))}
    plan = plan_days(
        leave_type="vacation", employment_type="b2b", days=days, pools=pools
    )
    assert plan.paid == D("2")
    assert plan.unpaid == D("3")


@pytest.mark.asyncio
async def test_contractor_balance_counts_only_paid_days(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        contractor = await _user(db, "recruiter", profile=True, employment_type="b2b")
        await _pool(db, contractor, 2091, "5")
        await db.commit()

    first = await app_client.post(
        BASE + "/requests",
        json=_body("vacation", date(2091, 11, 12), date(2091, 11, 15)),
        headers=_headers(contractor),
    )
    assert first.json()["paid_days"] == "4.0"
    second = await app_client.post(
        BASE + "/requests",
        json=_body("vacation", date(2091, 11, 19), date(2091, 11, 21)),
        headers=_headers(contractor),
    )
    assert second.json()["paid_days"] == "1.0"
    assert second.json()["unpaid_days"] == "2.0"

    balance = await _balance(app_client, contractor, 2091)
    assert balance["remaining_days"] == "0.0"  # Compass: 5 − 7 = −2
    assert balance["unpaid_days"] == "2.0"

    cancelled = await app_client.post(
        f"{BASE}/requests/{first.json()['id']}/cancel", headers=_headers(contractor)
    )
    assert cancelled.status_code == 200
    # Wraca tylko to, co było płatne.
    assert (await _balance(app_client, contractor, 2091))["remaining_days"] == "4.0"


# ── 4. Pół dnia zostaje połówką ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_half_day_is_half_in_days_balance_calendar_and_outlook(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "employee", profile=True, employment_type="uop")
        await _pool(db, worker, 2091, "26")
        await db.commit()

    created = await app_client.post(
        BASE + "/requests",
        json=_body(
            "vacation", date(2091, 11, 14), date(2091, 11, 14), half_day="afternoon"
        ),
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    assert created.json()["days_total"] == "0.5"
    async with AsyncSessionLocal() as db:
        fractions = list(
            await db.scalars(
                select(LeaveRequestDay.fraction).where(
                    LeaveRequestDay.leave_request_id == uuid.UUID(created.json()["id"])
                )
            )
        )
    assert fractions == [D("0.5")]
    assert (await _balance(app_client, worker, 2091))["remaining_days"] == "25.5"

    calendar = await app_client.get(
        BASE + "/calendar", params={"month": "2091-11"}, headers=_headers(worker)
    )
    mine = next(p for p in calendar.json()["people"] if p["user_id"] == worker.id)
    assert mine["absences"][0]["half_day"] == "afternoon"

    snapshot = LeaveSnapshot(
        id=created.json()["id"],
        user_id=worker.id,
        start=date(2091, 11, 14),
        end=date(2091, 11, 14),
        half_day="afternoon",
        total_days=D("0.5"),
        substitute_user_id=None,
        forward_mail_consent=False,
        oof_internal_message=None,
        oof_external_message=None,
        return_on=date(2091, 11, 15),
    )
    ops = plan_operations("approved", snapshot, today=date(2091, 1, 1))
    assert [op.payload.get("half_day") for op in ops] == ["afternoon"]


# ── 5. Nikt nie zatwierdza własnego wniosku ──────────────────────────────────


def test_policy_refuses_self_decision_even_for_admin() -> None:
    admin = Actor(user_id=7, is_admin=True, is_people_admin=True)
    assert not can_decide(admin, subject_user_id=7, subject_manager_id=None)


@pytest.mark.asyncio
async def test_admin_cannot_approve_own_request(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin", profile=True, employment_type="uop")
        await db.commit()

    created = await app_client.post(
        BASE + "/requests",
        json=_body("vacation", date(2091, 11, 12), date(2091, 11, 13)),
        headers=_headers(admin),
    )
    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    own = await app_client.post(
        f"{BASE}/approvals/{created.json()['id']}/approve", headers=_headers(admin)
    )
    assert own.status_code == 403
    queue = await app_client.get(BASE + "/approvals/pending", headers=_headers(admin))
    assert created.json()["id"] not in {item["id"] for item in queue.json()["items"]}


@pytest.mark.asyncio
async def test_database_refuses_self_decision() -> None:
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "employee", profile=True)
        await db.commit()
        db.add(
            LeaveRequest(
                user_id=worker.id,
                leave_type="vacation",
                status="approved",
                start_date=date(2091, 11, 12),
                end_date=date(2091, 11, 12),
                decided_by=worker.id,
            )
        )
        with pytest.raises(IntegrityError, match="ck_leave_requests_no_self_decision"):
            await db.flush()
        await db.rollback()


# ── 6. Drugi akceptujący dostaje konflikt ────────────────────────────────────


@pytest.mark.asyncio
async def test_second_approver_gets_conflict(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        # Umowa o pracę — na B2B i zleceniu nie ma decyzji (D5).
        worker = await _user(
            db, "employee", profile=True, employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()

    request_id = (
        await app_client.post(
            BASE + "/requests",
            json=_body("vacation", date(2091, 11, 12), date(2091, 11, 13)),
            headers=_headers(worker),
        )
    ).json()["id"]
    first = await app_client.post(
        f"{BASE}/approvals/{request_id}/approve", headers=_headers(boss)
    )
    assert first.status_code == 200
    second = await app_client.post(
        f"{BASE}/approvals/{request_id}/approve", headers=_headers(hr)
    )
    assert second.status_code == 409
    late_reject = await app_client.post(
        f"{BASE}/approvals/{request_id}/reject",
        json={"note": "Za późno"},
        headers=_headers(hr),
    )
    assert late_reject.status_code == 409
    async with AsyncSessionLocal() as db:
        row = await db.get(LeaveRequest, uuid.UUID(request_id))
        assert row.decided_by == boss.id


# ── 7. Przekierowanie poczty tylko za zgodą osoby ────────────────────────────


@pytest.mark.asyncio
async def test_mail_forwarding_needs_the_persons_own_consent(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        stand_in = await _user(db, "recruiter", profile=True)
        # Umowa o pracę: wpis za osobę na B2B/zleceniu robią tylko Kadry (D5,
        # decyzja Artura 19.10.2026) — kartoteka bez formy to w bazie B2B.
        worker = await _user(
            db, "employee", profile=True, manager_user_id=boss.id, employment_type="uop"
        )
        await db.commit()

    smuggled = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={
            **_body("vacation", date(2091, 11, 12), date(2091, 11, 16)),
            "user_id": worker.id,
            "substitute_user_id": stand_in.id,
            "forward_mail_consent": True,
        },
        headers=_headers(boss),
    )
    assert smuggled.status_code == 422

    entered = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={
            **_body("vacation", date(2091, 11, 12), date(2091, 11, 16)),
            "user_id": worker.id,
            "substitute_user_id": stand_in.id,
        },
        headers=_headers(boss),
    )
    assert entered.status_code == 201, entered.text
    request_id = entered.json()["id"]
    assert entered.json()["forward_mail_consent"] is False

    def forward_ops(kinds: list[str]) -> list[str]:
        return [kind for kind in kinds if kind.startswith("forward_rule")]

    async def kinds() -> list[str]:
        async with AsyncSessionLocal() as db:
            return list(
                await db.scalars(
                    select(HrM365Operation.kind)
                    .where(HrM365Operation.leave_request_id == uuid.UUID(request_id))
                    .order_by(HrM365Operation.id)
                )
            )

    assert forward_ops(await kinds()) == []

    by_boss = await app_client.put(
        f"{BASE}/requests/{request_id}/forward-consent",
        json={"consent": True},
        headers=_headers(boss),
    )
    assert by_boss.status_code in (403, 404)
    assert forward_ops(await kinds()) == []

    by_owner = await app_client.put(
        f"{BASE}/requests/{request_id}/forward-consent",
        json={"consent": True},
        headers=_headers(worker),
    )
    assert by_owner.status_code == 200, by_owner.text
    assert by_owner.json()["forward_mail_consent"] is True
    withdrawn = await app_client.put(
        f"{BASE}/requests/{request_id}/forward-consent",
        json={"consent": False},
        headers=_headers(worker),
    )
    assert withdrawn.status_code == 200
    assert forward_ops(await kinds()) == ["forward_rule_open", "forward_rule_close"]


@pytest.mark.asyncio
async def test_database_refuses_consent_without_substitute() -> None:
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "employee", profile=True)
        await db.commit()
        db.add(
            LeaveRequest(
                user_id=worker.id,
                leave_type="vacation",
                start_date=date(2091, 11, 12),
                end_date=date(2091, 11, 12),
                forward_mail_consent=True,
            )
        )
        with pytest.raises(IntegrityError, match="ck_leave_requests_forward_consent"):
            await db.flush()
        await db.rollback()


# ── 8. L4: przyjęte także za kogoś, z powiadomieniem przełożonego i Kadr ─────


@pytest.mark.asyncio
async def test_sick_leave_entered_on_behalf_is_accepted_and_reported(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        worker = await _user(
            db, "employee", profile=True, employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()

    entered = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={
            **_body("sick_leave", date(2091, 11, 12), date(2091, 11, 14)),
            "user_id": worker.id,
        },
        headers=_headers(boss),
    )
    assert entered.status_code == 201, entered.text
    assert entered.json()["status"] == "approved"

    async def bell(user_id: int) -> list[Notification]:
        async with AsyncSessionLocal() as db:
            return list(
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.hr_absence_reported,
                    )
                )
            )

    reported = await bell(hr.id)
    assert len(reported) == 1
    assert "L4" not in reported[0].title + reported[0].message
    assert await bell(boss.id) == []  # wpisał sam — nie powiadamiamy sprawcy


@pytest.mark.asyncio
async def test_self_reported_sick_leave_is_approved_and_notifies_manager(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        worker = await _user(
            db, "employee", profile=True, employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()

    reported = await app_client.post(
        BASE + "/requests",
        json=_body("sick_leave", date(2091, 11, 19), date(2091, 11, 20)),
        headers=_headers(worker),
    )
    assert reported.status_code == 201
    assert reported.json()["status"] == "approved"
    assert reported.json()["decided_by_name"] is None
    async with AsyncSessionLocal() as db:
        rows = list(
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == boss.id,
                    Notification.notification_type
                    == NotificationType.hr_absence_reported,
                )
            )
        )
        # Rodzaj L4 to dane o zdrowiu: ślad ma poziom ``health`` (odczyt
        # filtruje go po uprawnieniu), a nie ``general`` jak urlop.
        sensitivities = set(
            await db.scalars(
                select(HrAuditEvent.sensitivity).where(
                    HrAuditEvent.subject_user_id == worker.id,
                    HrAuditEvent.entity_type == "leave_request",
                )
            )
        )
    assert len(rows) == 1
    assert sensitivities == {"health"}
