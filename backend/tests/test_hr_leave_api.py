"""Urlopy i zastępstwa — API (``/api/hr/leave``, „Ludzie w NEXUSIE”, E1).

Szczęśliwe ścieżki (wniosek → akceptacja → anulowanie, wpis za pracownika,
kalendarz, „Nieobecni dziś”) i odmowy 403/404/409/422, w tym D6: zespół nie
widzi rodzaju nieobecności. Dane fikcyjne (repo jest publiczne); daty w 2091,
żeby nie zderzać się z „dziś” ani z innymi testami.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

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
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

BASE = "/api/hr/leave"
MON = date(2091, 11, 12)  # poniedziałek, cały tydzień roboczy
FRI = date(2091, 11, 16)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, profile: bool = False, **profile_values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"leave-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
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


async def _pool(db, user: User, year: int, days: str, carried: str = "0") -> None:
    db.add(
        LeaveEntitlement(
            user_id=user.id,
            year=year,
            entitlement_days=Decimal(days),
            carried_over_days=Decimal(carried),
        )
    )
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


@pytest_asyncio.fixture
async def leave_off():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({**{key: True for key in HR_MODULE_KEYS}, "leave": False})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


async def _bell(user_id: int, ntype: NotificationType) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.notification_type == ntype,
                )
            )
        )


async def _ops(request_id: str) -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(HrM365Operation.kind)
            .where(HrM365Operation.leave_request_id == uuid.UUID(request_id))
            .order_by(HrM365Operation.id)
        )
        return list(rows)


def _body(leave_type: str = "vacation", start: date = MON, end: date = FRI, **extra):
    return {
        "leave_type": leave_type,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        **extra,
    }


@pytest.mark.asyncio
async def test_switched_off_module_hides_leave_except_for_admin(
    app_client, leave_off
) -> None:
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "employee", profile=True)
        admin = await _user(db, "admin")
        await db.commit()

    for path in ("/balance", "/my-requests", "/absent-today", "/calendar"):
        denied = await app_client.get(BASE + path, headers=_headers(worker))
        assert denied.status_code == 404, path
    allowed = await app_client.get(BASE + "/absent-today", headers=_headers(admin))
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_request_approve_and_cancel_flow(app_client, modules_on) -> None:
    department = f"Rekrutacja {uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter", profile=True, department=department)
        stand_in = await _user(db, "recruiter", profile=True, department=department)
        worker = await _user(
            db,
            "recruiter",
            profile=True,
            employment_type="uop",
            manager_user_id=boss.id,
            department=department,
        )
        await _pool(db, worker, MON.year, "26")
        await db.commit()

    preview = await app_client.post(
        BASE + "/preview",
        json=_body(substitute_user_id=stand_in.id),
        headers=_headers(worker),
    )
    assert preview.status_code == 200, preview.text
    shown = preview.json()
    assert shown["days_total"] == "5.0"
    assert shown["paid_days"] == "5.0"
    assert shown["approver"] == boss.name
    assert shown["blocking_reason"] is None
    assert shown["return_on"] == "2091-11-19"
    assert shown["years"][0]["remaining_after"] == "21.0"

    created = await app_client.post(
        BASE + "/requests",
        json=_body(substitute_user_id=stand_in.id, note="Wyjazd rodzinny"),
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    request = created.json()
    assert request["status"] == "pending"
    assert request["days_total"] == "5.0"
    assert request["can_cancel"] is True
    request_id = request["id"]
    assert len(await _bell(boss.id, NotificationType.hr_leave_requested)) == 1

    balance = (
        await app_client.get(
            BASE + "/balance", params={"year": MON.year}, headers=_headers(worker)
        )
    ).json()
    assert balance["pending_days"] == "5.0"
    assert balance["remaining_days"] == "21.0"

    queue = await app_client.get(BASE + "/approvals/pending", headers=_headers(boss))
    assert queue.status_code == 200
    mine = [item for item in queue.json()["items"] if item["id"] == request_id]
    assert mine and mine[0]["leave_type"] == "vacation"
    assert mine[0]["note"] == "Wyjazd rodzinny"

    approved = await app_client.post(
        f"{BASE}/approvals/{request_id}/approve", headers=_headers(boss)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by_name"] == boss.name
    assert len(await _bell(worker.id, NotificationType.hr_leave_decided)) == 1
    substitute_bell = await _bell(stand_in.id, NotificationType.hr_leave_substitute)
    assert len(substitute_bell) == 1
    assert "Urlop" not in substitute_bell[0].message
    assert await _ops(request_id) == ["set_oof", "calendar_event_upsert"]

    cancelled = await app_client.post(
        f"{BASE}/requests/{request_id}/cancel", headers=_headers(worker)
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert len(await _bell(boss.id, NotificationType.hr_leave_cancelled)) == 1
    assert len(await _bell(stand_in.id, NotificationType.hr_leave_cancelled)) == 1
    assert await _ops(request_id) == [
        "set_oof",
        "calendar_event_upsert",
        "clear_oof",
        "calendar_event_delete",
    ]
    after = (
        await app_client.get(
            BASE + "/balance", params={"year": MON.year}, headers=_headers(worker)
        )
    ).json()
    assert after["remaining_days"] == "26.0"

    again = await app_client.post(
        f"{BASE}/requests/{request_id}/cancel", headers=_headers(worker)
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_approvals_are_refused_outside_scope(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter", profile=True)
        other_boss = await _user(db, "recruiter", profile=True)
        await _user(db, "employee", profile=True, manager_user_id=other_boss.id)
        worker = await _user(db, "employee", profile=True, manager_user_id=boss.id)
        colleague = await _user(db, "recruiter", profile=True)
        await db.commit()

    created = await app_client.post(
        BASE + "/requests", json=_body(), headers=_headers(worker)
    )
    request_id = created.json()["id"]

    no_reports = await app_client.get(
        BASE + "/approvals/pending", headers=_headers(colleague)
    )
    assert no_reports.status_code == 403
    assert no_reports.json()["detail"] == "Akceptacje widzą przełożeni i Kadry."

    wrong_team = await app_client.post(
        f"{BASE}/approvals/{request_id}/approve", headers=_headers(other_boss)
    )
    assert wrong_team.status_code == 404
    queue = await app_client.get(
        BASE + "/approvals/pending", headers=_headers(other_boss)
    )
    assert request_id not in {item["id"] for item in queue.json()["items"]}

    missing = await app_client.post(
        f"{BASE}/approvals/{uuid.uuid4()}/approve", headers=_headers(boss)
    )
    assert missing.status_code == 404

    foreign_cancel = await app_client.post(
        f"{BASE}/requests/{request_id}/cancel", headers=_headers(colleague)
    )
    assert foreign_cancel.status_code == 404


@pytest.mark.asyncio
async def test_reject_requires_reason_and_frees_the_days(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        worker = await _user(db, "employee", profile=True, employment_type="uop")
        await _pool(db, worker, MON.year, "20")
        await db.commit()

    request_id = (
        await app_client.post(
            BASE + "/requests", json=_body(), headers=_headers(worker)
        )
    ).json()["id"]
    # Osoba bez przełożonego → decydują Kadry (i one dostają dzwonek).
    assert len(await _bell(hr.id, NotificationType.hr_leave_requested)) == 1

    empty = await app_client.post(
        f"{BASE}/approvals/{request_id}/reject",
        json={"note": "  "},
        headers=_headers(hr),
    )
    assert empty.status_code == 422
    rejected = await app_client.post(
        f"{BASE}/approvals/{request_id}/reject",
        json={"note": "Termin koliduje z wdrożeniem u klienta"},
        headers=_headers(hr),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    bell = await _bell(worker.id, NotificationType.hr_leave_decided)
    assert len(bell) == 1 and "wdrożeniem" not in bell[0].message

    async with AsyncSessionLocal() as db:
        active = await db.scalars(
            select(LeaveRequestDay.active).where(
                LeaveRequestDay.leave_request_id == uuid.UUID(request_id)
            )
        )
        assert set(active) == {False}
    # Te same dni można złożyć ponownie — odrzucony wniosek nie blokuje.
    retry = await app_client.post(
        BASE + "/requests", json=_body(), headers=_headers(worker)
    )
    assert retry.status_code == 201


@pytest.mark.asyncio
async def test_overlapping_request_is_a_conflict(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "employee", profile=True)
        await db.commit()

    first = await app_client.post(
        BASE + "/requests", json=_body(), headers=_headers(worker)
    )
    assert first.status_code == 201
    overlap = await app_client.post(
        BASE + "/requests",
        json=_body(start=FRI, end=FRI + timedelta(days=3)),
        headers=_headers(worker),
    )
    assert overlap.status_code == 409
    assert "nakładać" in overlap.json()["detail"]
    preview = await app_client.post(
        BASE + "/preview", json=_body(start=FRI, end=FRI), headers=_headers(worker)
    )
    assert "nakładać" in preview.json()["blocking_reason"]


@pytest.mark.asyncio
async def test_policy_refusals_are_422(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        contractor = await _user(db, "recruiter", profile=True, employment_type="b2b")
        employee = await _user(db, "employee", profile=True, employment_type="uop")
        await _pool(db, employee, MON.year, "3")
        outsider = await _user(db, "recruiter")
        await db.commit()

    b2b = await app_client.post(
        BASE + "/requests", json=_body("on_demand"), headers=_headers(contractor)
    )
    assert b2b.status_code == 422
    assert "wyłącznie o urlop wypoczynkowy" in b2b.json()["detail"]
    over = await app_client.post(
        BASE + "/requests", json=_body(), headers=_headers(employee)
    )
    assert over.status_code == 422
    assert "urlop bezpłatny" in over.json()["detail"]
    weekend = await app_client.post(
        BASE + "/requests",
        json=_body(start=date(2091, 11, 10), end=date(2091, 11, 11)),
        headers=_headers(employee),
    )
    assert weekend.status_code == 422
    self_sub = await app_client.post(
        BASE + "/requests",
        json=_body("unpaid_leave", substitute_user_id=employee.id),
        headers=_headers(employee),
    )
    assert self_sub.status_code == 422
    no_profile = await app_client.get(BASE + "/balance", headers=_headers(outsider))
    assert no_profile.status_code == 403


@pytest.mark.asyncio
async def test_team_calendar_hides_type_outside_d6(app_client, modules_on) -> None:
    department = f"Delivery {uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, department=department)
        sick = await _user(
            db,
            "recruiter",
            profile=True,
            employment_type="uop",
            manager_user_id=boss.id,
            department=department,
        )
        colleague = await _user(db, "recruiter", profile=True, department=department)
        hr = await _user(db, "finance")
        await _grant(db, hr, "people_admin")
        await db.commit()

    reported = await app_client.post(
        BASE + "/requests",
        json=_body("sick_leave", note="Grypa"),
        headers=_headers(sick),
    )
    assert reported.status_code == 201
    assert reported.json()["status"] == "approved"
    pending = await app_client.post(
        BASE + "/requests",
        json=_body(start=date(2091, 11, 19), end=date(2091, 11, 20)),
        headers=_headers(sick),
    )
    assert pending.status_code == 201

    def entry(body: dict, user_id: int) -> dict:
        return next(p for p in body["people"] if p["user_id"] == user_id)

    params = {"month": "2091-11", "department": department}
    as_colleague = await app_client.get(
        BASE + "/calendar", params=params, headers=_headers(colleague)
    )
    assert as_colleague.status_code == 200, as_colleague.text
    seen = entry(as_colleague.json(), sick.id)
    assert seen["type_visible"] is False
    assert [a["label"] for a in seen["absences"]] == ["Nieobecność"]
    assert seen["absences"][0]["leave_type"] is None
    assert seen["absences"][0]["id"] is None
    assert "Grypa" not in as_colleague.text and "L4" not in as_colleague.text

    as_boss = entry(
        (
            await app_client.get(
                BASE + "/calendar", params=params, headers=_headers(boss)
            )
        ).json(),
        sick.id,
    )
    assert as_boss["type_visible"] is True
    assert {a["status"] for a in as_boss["absences"]} == {"approved", "pending"}
    assert "Zwolnienie lekarskie (L4)" in {a["label"] for a in as_boss["absences"]}

    as_hr = await app_client.get(
        BASE + "/calendar", params=params, headers=_headers(hr)
    )
    assert as_hr.status_code == 200
    assert entry(as_hr.json(), sick.id)["type_visible"] is True

    days = as_colleague.json()["days"]
    assert len(days) == 30
    assert next(d for d in days if d["date"] == "2091-11-01")["kind"] == "holiday"

    bad = await app_client.get(
        BASE + "/calendar", params={"month": "2091-13"}, headers=_headers(boss)
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_absent_today_and_badge_show_no_type(app_client, modules_on) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        absent = await _user(db, "employee", profile=True, employment_type="uop")
        stand_in = await _user(db, "recruiter", profile=True)
        recruiter_without_profile = await _user(db, "recruiter")
        robot = await _user(db, "automation")
        await db.commit()

    entered = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={
            **_body("sick_leave", start=today, end=today + timedelta(days=9)),
            "user_id": absent.id,
            "substitute_user_id": stand_in.id,
        },
        headers=_headers(hr),
    )
    assert entered.status_code == 201, entered.text

    listing = await app_client.get(
        BASE + "/absent-today", headers=_headers(recruiter_without_profile)
    )
    assert listing.status_code == 200, listing.text
    row = next(item for item in listing.json()["items"] if item["user_id"] == absent.id)
    assert row["until"] == entered.json()["end_date"]
    assert row["substitute_name"] == stand_in.name
    assert "leave_type" not in row and "L4" not in listing.text

    as_substitute = await app_client.get(
        BASE + "/absent-today", headers=_headers(stand_in)
    )
    mine = next(i for i in as_substitute.json()["items"] if i["user_id"] == absent.id)
    assert mine["i_substitute"] is True

    badge = await app_client.get(
        BASE + "/absence",
        params={"user_ids": f"{absent.id},{stand_in.id}"},
        headers=_headers(recruiter_without_profile),
    )
    assert badge.status_code == 200
    assert [item["user_id"] for item in badge.json()["items"]] == [absent.id]
    assert "leave_type" not in badge.json()["items"][0]

    garbage = await app_client.get(
        BASE + "/absence", params={"user_ids": "1,abc"}, headers=_headers(hr)
    )
    assert garbage.status_code == 422
    refused = await app_client.get(BASE + "/absent-today", headers=_headers(robot))
    assert refused.status_code == 403


@pytest.mark.asyncio
async def test_entry_on_behalf_respects_team_scope(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        report = await _user(
            db, "employee", profile=True, employment_type="uop", manager_user_id=boss.id
        )
        stranger = await _user(db, "employee", profile=True)
        await db.commit()

    people = await app_client.get(BASE + "/approvals/people", headers=_headers(boss))
    assert [p["user_id"] for p in people.json()["items"]] == [report.id]

    ok = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={**_body("occasional"), "user_id": report.id},
        headers=_headers(boss),
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["status"] == "approved"
    assert ok.json()["source"] == "on_behalf"
    assert ok.json()["decided_by_name"] == boss.name
    assert len(await _bell(report.id, NotificationType.hr_leave_decided)) == 1

    foreign = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={**_body(), "user_id": stranger.id},
        headers=_headers(boss),
    )
    assert foreign.status_code == 403
    own = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={**_body(), "user_id": boss.id},
        headers=_headers(boss),
    )
    assert own.status_code == 403


@pytest.mark.asyncio
async def test_started_leave_is_cancelled_by_manager_not_by_owner(
    app_client, modules_on
) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        # Umowa o pracę: przełożony anuluje trwający urlop (B2B i zlecenie —
        # tylko Kadry, D5: test_hr_leave_reports.py).
        worker = await _user(
            db,
            "employee",
            profile=True,
            manager_user_id=boss.id,
            employment_type="uop",
        )
        await db.commit()

    request_id = (
        await app_client.post(
            BASE + "/approvals/on-behalf",
            json={
                **_body(
                    "vacation",
                    start=today - timedelta(days=1),
                    end=today + timedelta(days=6),
                ),
                "user_id": worker.id,
            },
            headers=_headers(boss),
        )
    ).json()["id"]
    mine = (
        await app_client.get(BASE + "/my-requests", headers=_headers(worker))
    ).json()
    assert (
        next(i for i in mine["items"] if i["id"] == request_id)["can_cancel"] is False
    )

    refused = await app_client.post(
        f"{BASE}/requests/{request_id}/cancel", headers=_headers(worker)
    )
    assert refused.status_code == 422
    assert "przełożony albo Kadry" in refused.json()["detail"]
    # Termin się zaczął: bez powodu przełożony też nie cofnie (28.10.2026).
    for body in (None, {}, {"reason": "  "}, {"reason": "ab"}):
        missing = await app_client.post(
            f"{BASE}/approvals/{request_id}/cancel",
            json=body,
            headers=_headers(boss),
        )
        assert missing.status_code == 422, (body, missing.text)
        assert "powód" in missing.json()["detail"].lower()
    reason = "Była w pracy u klienta, wpis pomyłkowy"
    done = await app_client.post(
        f"{BASE}/approvals/{request_id}/cancel",
        json={"reason": f"  {reason} "},
        headers=_headers(boss),
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "cancelled"

    # Powód: w śladzie i w dymku osoby; przełożony (autor) nie dostaje dymka.
    async with AsyncSessionLocal() as db:
        trail = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_id == request_id,
                    HrAuditEvent.action == "leave_cancelled",
                )
            )
        )
    assert len(trail) == 1
    assert trail[0].details["reason"] == reason
    assert trail[0].sensitivity == "health"
    bells = await _bell(worker.id, NotificationType.hr_leave_cancelled)
    assert len(bells) == 1 and bells[0].message.endswith(f"Powód: {reason}")
    assert "urlop" not in bells[0].message.lower()


@pytest.mark.asyncio
async def test_approver_cancels_a_future_leave_without_a_reason(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        worker = await _user(
            db, "employee", profile=True, manager_user_id=boss.id, employment_type="uop"
        )
        await db.commit()
    request_id = (
        await app_client.post(
            BASE + "/approvals/on-behalf",
            json={**_body("vacation"), "user_id": worker.id},
            headers=_headers(boss),
        )
    ).json()["id"]
    done = await app_client.post(
        f"{BASE}/approvals/{request_id}/cancel", headers=_headers(boss)
    )
    assert done.status_code == 200, done.text
    async with AsyncSessionLocal() as db:
        trail = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_id == request_id,
                HrAuditEvent.action == "leave_cancelled",
            )
        )
    assert trail is not None and "reason" not in trail.details
    bells = await _bell(worker.id, NotificationType.hr_leave_cancelled)
    assert len(bells) == 1 and "Powód" not in bells[0].message


@pytest.mark.asyncio
async def test_started_pending_request_is_not_cancelled_by_owner(
    app_client, modules_on
) -> None:
    """Oczekujący wniosek po pierwszym dniu: osoba była nieobecna — anuluje albo
    odrzuca go przełożony albo Kadry (decyzja Artura 28.10.2026)."""

    today = business_today()
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        worker = await _user(
            db, "employee", profile=True, manager_user_id=boss.id, employment_type="uop"
        )
        started = LeaveRequest(
            user_id=worker.id,
            leave_type="vacation",
            status="pending",
            start_date=today - timedelta(days=3),
            end_date=today - timedelta(days=1),
        )
        future = LeaveRequest(
            user_id=worker.id,
            leave_type="vacation",
            status="pending",
            start_date=today + timedelta(days=30),
            end_date=today + timedelta(days=31),
        )
        db.add_all([started, future])
        await db.commit()
        started_id, future_id = str(started.id), str(future.id)

    mine = (
        await app_client.get(BASE + "/my-requests", headers=_headers(worker))
    ).json()["items"]
    by_id = {item["id"]: item for item in mine}
    assert by_id[started_id]["can_cancel"] is False
    assert by_id[future_id]["can_cancel"] is True

    refused = await app_client.post(
        f"{BASE}/requests/{started_id}/cancel", headers=_headers(worker)
    )
    assert refused.status_code == 422
    assert "przełożony albo Kadry" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(LeaveRequest, uuid.UUID(started_id))).status == "pending"

    own = await app_client.post(
        f"{BASE}/requests/{future_id}/cancel", headers=_headers(worker)
    )
    assert own.status_code == 200 and own.json()["status"] == "cancelled"
    by_boss = await app_client.post(
        f"{BASE}/approvals/{started_id}/cancel",
        json={"reason": "Nieobecność wpisana pomyłkowo"},
        headers=_headers(boss),
    )
    assert by_boss.status_code == 200, by_boss.text


@pytest.mark.asyncio
async def test_substitute_suggestions_prefer_department_and_skip_absent(
    app_client, modules_on
) -> None:
    department = f"Sourcing {uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "recruiter", profile=True, department=department)
        same = await _user(db, "recruiter", profile=True, department=department)
        away = await _user(db, "recruiter", profile=True, department=department)
        await _user(db, "recruiter", profile=True, department=f"{department} inny")
        await db.commit()

    await app_client.post(BASE + "/requests", json=_body(), headers=_headers(away))
    found = await app_client.get(
        BASE + "/substitutes",
        params={"start_date": MON.isoformat(), "end_date": FRI.isoformat()},
        headers=_headers(worker),
    )
    assert found.status_code == 200
    items = found.json()["items"]
    ids = [item["user_id"] for item in items]
    assert ids[0] == same.id and items[0]["suggested"] is True
    assert away.id not in ids and worker.id not in ids

    reversed_range = await app_client.get(
        BASE + "/substitutes",
        params={"start_date": FRI.isoformat(), "end_date": MON.isoformat()},
        headers=_headers(worker),
    )
    assert reversed_range.status_code == 422


@pytest.mark.asyncio
async def test_history_filters_and_scope(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True)
        worker = await _user(db, "employee", profile=True, manager_user_id=boss.id)
        await db.commit()

    request_id = (
        await app_client.post(
            BASE + "/requests", json=_body(), headers=_headers(worker)
        )
    ).json()["id"]
    await app_client.post(
        f"{BASE}/approvals/{request_id}/approve", headers=_headers(boss)
    )
    history = await app_client.get(
        BASE + "/approvals/history",
        params={"status": "approved", "user_id": worker.id},
        headers=_headers(boss),
    )
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["items"]] == [request_id]
    wrong = await app_client.get(
        BASE + "/approvals/history", params={"status": "maybe"}, headers=_headers(boss)
    )
    assert wrong.status_code == 422


@pytest.mark.asyncio
async def test_on_behalf_preview_hides_event_titles(app_client, modules_on) -> None:
    """Podgląd „za pracownika” nie oddaje tytułów wydarzeń z kalendarza osoby.

    Tytuły rozmów i prepów niosą nazwiska kandydatów („Rozmowa u klienta: …”),
    a Kadry (także rola „Pracownik” z nadaniem) nie mają dostępu do rekrutacji.
    Sama osoba widzi swoje tytuły w swoim oknie.
    """
    from datetime import datetime, timezone

    from app.models.calendar_event import CalendarEvent, EventStatus, EventType

    async with AsyncSessionLocal() as db:
        hr = await _user(db, "employee", profile=True)
        await _grant(db, hr, "people_admin")
        worker = await _user(db, "recruiter", profile=True, employment_type="uop")
        await _pool(db, worker, MON.year, "20")
        db.add(
            CalendarEvent(
                title="Rozmowa u klienta: Kandydatka Przykładowa — Rekrutacja testowa",
                event_type=EventType.client_interview,
                start_time=datetime(
                    MON.year, MON.month, MON.day, 10, tzinfo=timezone.utc
                ),
                status=EventStatus.scheduled,
                created_by=worker.id,
                operational_owner_id=worker.id,
            )
        )
        await db.commit()

    on_behalf = await app_client.post(
        BASE + "/approvals/preview",
        json={**_body(), "user_id": worker.id},
        headers=_headers(hr),
    )
    assert on_behalf.status_code == 200, on_behalf.text
    work = on_behalf.json()["work"]
    assert work["total"] == 1
    assert "Kandydatka" not in str(on_behalf.json())
    assert all(item.get("title") is None for item in work["items"])

    own = await app_client.post(
        BASE + "/preview", json=_body(), headers=_headers(worker)
    )
    assert own.status_code == 200, own.text
    assert own.json()["work"]["items"][0]["title"].startswith("Rozmowa u klienta")
