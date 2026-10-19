"""Zgłoszenie zamiast wniosku na B2B i zleceniu (etap 2, D5, 17.10.2026).

Na B2B i zleceniu termin wchodzi od razu (``approved`` bez decydującego),
koordynator dostaje informację i może zgłosić kolizję — nie akceptuje, nie
odrzuca i nie anuluje. Umowa o pracę bez zmian (wniosek czeka na akceptację).
Dane fikcyjne (repo jest publiczne); daty w 2091, żeby nie zderzać się z „dziś”.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_leave import HrM365Operation, LeaveRequest
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import leave_service
from app.services.hr_foundation_schema import (
    HR_DIVISIONS_SETTING,
    HR_MODULE_KEYS,
    HR_MODULES_SETTING,
)

BASE = "/api/hr/leave"
MON = date(2091, 11, 12)
FRI = date(2091, 11, 16)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, profile: bool = False, **profile_values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"report-{marker}@example.com",
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


async def _set(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def modules_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
        heads = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_DIVISIONS_SETTING)
        )
    await _set(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    yield
    await _set(HR_DIVISIONS_SETTING, heads)
    await _set(HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS})


def _body(start: date = MON, end: date = FRI, **extra) -> dict:
    return {
        "leave_type": "vacation",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        **extra,
    }


async def _bells(user_id: int, ntype: NotificationType) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.notification_type == ntype,
                )
                .order_by(Notification.id)
            )
        )


async def _report(app_client, person: User, **extra) -> dict:
    created = await app_client.post(
        BASE + "/requests", json=_body(**extra), headers=_headers(person)
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _pending_payload(app_client, viewer: User) -> dict:
    response = await app_client.get(
        BASE + "/approvals/pending", headers=_headers(viewer)
    )
    assert response.status_code == 200, response.text
    return response.json()


# ── Zgłoszenie wchodzi od razu ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("form", "title"),
    [
        ("b2b", "Zgłoszona przerwa w świadczeniu usług"),
        ("zlecenie", "Zgłoszona nieobecność"),
    ],
)
@pytest.mark.asyncio
async def test_contractor_report_is_approved_without_decision_and_queue(
    app_client, modules_on, form, title
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, employment_type="uop")
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        person = await _user(
            db,
            "employee",
            profile=True,
            employment_type=form,
            manager_user_id=boss.id,
        )
        await db.commit()

    preview = await app_client.post(
        BASE + "/preview", json=_body(), headers=_headers(person)
    )
    assert preview.status_code == 200
    assert preview.json()["flow"] == "report"
    assert preview.json()["auto_approved"] is True
    assert preview.json()["approver"] == boss.name

    row = await _report(app_client, person)
    assert row["status"] == "approved"
    assert row["decided_by_name"] is None
    assert row["is_report"] is True
    async with AsyncSessionLocal() as db:
        stored = await db.get(LeaveRequest, uuid.UUID(row["id"]))
        assert stored.decided_by is None and stored.decided_at is not None
        # Microsoft 365 od razu (autoodpowiedź i wydarzenie w kalendarzu).
        ops = list(
            await db.scalars(
                select(HrM365Operation.kind).where(
                    HrM365Operation.leave_request_id == stored.id
                )
            )
        )
    assert ops

    for viewer in (boss, hr):
        payload = await _pending_payload(app_client, viewer)
        assert row["id"] not in {item["id"] for item in payload["items"]}
        assert row["id"] in {item["id"] for item in payload["reported"]}
    counts = await app_client.get("/api/hr/counts", headers=_headers(boss))
    assert counts.status_code == 200
    assert counts.json()["approvals"] == 0

    reported = await _bells(boss.id, NotificationType.hr_absence_reported)
    assert [bell.title for bell in reported] == [title]
    assert "Urlop" not in reported[0].message  # bez rodzaju (D6)
    assert not await _bells(boss.id, NotificationType.hr_leave_requested)
    # Kadry nie dostają kopii zgłoszenia — to nie L4.
    assert not await _bells(hr.id, NotificationType.hr_absence_reported)


@pytest.mark.asyncio
async def test_uop_request_still_waits_for_the_supervisor(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, employment_type="uop")
        worker = await _user(
            db, "employee", profile=True, employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()

    preview = await app_client.post(
        BASE + "/preview", json=_body(), headers=_headers(worker)
    )
    assert preview.json()["flow"] == "request"
    assert preview.json()["auto_approved"] is False
    row = await _report(app_client, worker)
    assert row["status"] == "pending" and row["is_report"] is False
    payload = await _pending_payload(app_client, boss)
    assert row["id"] in {item["id"] for item in payload["items"]}
    assert row["id"] not in {item["id"] for item in payload["reported"]}
    assert await _bells(boss.id, NotificationType.hr_leave_requested)
    approved = await app_client.post(
        f"{BASE}/approvals/{row['id']}/approve", headers=_headers(boss)
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"


# ── Bez akceptacji, odrzucenia i anulowania przez koordynatora ────────────────


@pytest.mark.asyncio
async def test_coordinator_cannot_approve_reject_or_cancel_a_report(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, employment_type="uop")
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        person = await _user(
            db, "employee", profile=True, employment_type="b2b", manager_user_id=boss.id
        )
        await db.commit()
    row = await _report(app_client, person)

    for decision, body in (("approve", None), ("reject", {"note": "Nie teraz"})):
        for actor in (boss, hr):
            refused = await app_client.post(
                f"{BASE}/approvals/{row['id']}/{decision}",
                json=body,
                headers=_headers(actor),
            )
            assert refused.status_code == 409, (decision, refused.text)
            assert "zgłoszeniem" in refused.json()["detail"]
    cancel = await app_client.post(
        f"{BASE}/approvals/{row['id']}/cancel", headers=_headers(boss)
    )
    assert cancel.status_code == 403
    assert "Kadry" in cancel.json()["detail"]
    async with AsyncSessionLocal() as db:
        stored = await db.get(LeaveRequest, uuid.UUID(row["id"]))
        assert stored.status == "approved" and stored.decided_by is None

    # Kadry poprawiają zgłoszenie administracyjnie; osoba anuluje własne.
    by_hr = await app_client.post(
        f"{BASE}/approvals/{row['id']}/cancel", headers=_headers(hr)
    )
    assert by_hr.status_code == 200 and by_hr.json()["status"] == "cancelled"
    again = await _report(app_client, person)
    own = await app_client.post(
        f"{BASE}/requests/{again['id']}/cancel", headers=_headers(person)
    )
    assert own.status_code == 200 and own.json()["status"] == "cancelled"
    cancelled = await _bells(boss.id, NotificationType.hr_leave_cancelled)
    assert cancelled[-1].title == "Przerwa w świadczeniu usług anulowana"


@pytest.mark.asyncio
async def test_started_report_is_cancelled_by_hr_not_by_owner(
    app_client, modules_on
) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        person = await _user(db, "employee", profile=True, employment_type="zlecenie")
        await db.commit()
    row = await _report(
        app_client,
        person,
        start=today - timedelta(days=1),
        end=today + timedelta(days=6),
    )
    assert row["can_cancel"] is False
    refused = await app_client.post(
        f"{BASE}/requests/{row['id']}/cancel", headers=_headers(person)
    )
    assert refused.status_code == 422
    assert "Kadry" in refused.json()["detail"]
    assert "przełożony" not in refused.json()["detail"]


# ── Kolizja ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conflict_notifies_the_person_and_leaves_an_audit_trail(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, employment_type="uop")
        person = await _user(
            db, "employee", profile=True, employment_type="b2b", manager_user_id=boss.id
        )
        await db.commit()
    row = await _report(app_client, person)

    short = await app_client.post(
        f"{BASE}/{row['id']}/conflict", json={"note": " a "}, headers=_headers(boss)
    )
    assert short.status_code == 422
    too_long = await app_client.post(
        f"{BASE}/{row['id']}/conflict",
        json={"note": "x" * 1001},
        headers=_headers(boss),
    )
    assert too_long.status_code == 422

    note = "14.11 wdrożenie u klienta — czy możesz przesunąć o tydzień?"
    done = await app_client.post(
        f"{BASE}/{row['id']}/conflict", json={"note": note}, headers=_headers(boss)
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "approved"  # kolizja to nie odrzucenie
    assert done.json()["conflict"]["note"] == note
    assert done.json()["conflict"]["by_name"] == boss.name

    bells = await _bells(person.id, NotificationType.hr_leave_conflict)
    assert [bell.title for bell in bells] == [
        "Kolizja z Twoją przerwą w świadczeniu usług"
    ]
    assert note in bells[0].message and bells[0].link == "/my-time?tab=leave"
    async with AsyncSessionLocal() as db:
        trail = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_id == row["id"],
                    HrAuditEvent.action == leave_service.CONFLICT_ACTION,
                )
            )
        )
    assert len(trail) == 1
    assert trail[0].actor_user_id == boss.id and trail[0].details["note"] == note

    mine = await app_client.get(BASE + "/my-requests", headers=_headers(person))
    item = next(i for i in mine.json()["items"] if i["id"] == row["id"])
    assert item["conflict"]["note"] == note


@pytest.mark.asyncio
async def test_conflict_is_refused_outside_the_circle_and_for_uop(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, employment_type="uop")
        other_boss = await _user(db, "delivery_lead", profile=True)
        colleague = await _user(db, "employee", profile=True, employment_type="b2b")
        await _user(db, "employee", profile=True, manager_user_id=other_boss.id)
        person = await _user(
            db, "employee", profile=True, employment_type="b2b", manager_user_id=boss.id
        )
        worker = await _user(
            db, "employee", profile=True, employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()
    row = await _report(app_client, person)
    body = {"note": "Kolizja z wdrożeniem"}

    # Bez zespołu: bramka akceptujących (403); inny przełożony: jak nieistniejący.
    plain = await app_client.post(
        f"{BASE}/{row['id']}/conflict", json=body, headers=_headers(colleague)
    )
    assert plain.status_code == 403
    stranger = await app_client.post(
        f"{BASE}/{row['id']}/conflict", json=body, headers=_headers(other_boss)
    )
    assert stranger.status_code == 404
    own = await app_client.post(
        f"{BASE}/{row['id']}/conflict", json=body, headers=_headers(person)
    )
    assert own.status_code == 403

    uop = await _report(app_client, worker)
    refused = await app_client.post(
        f"{BASE}/{uop['id']}/conflict", json=body, headers=_headers(boss)
    )
    assert refused.status_code == 409
    assert not await _bells(person.id, NotificationType.hr_leave_conflict)


# ── Koordynator bez przełożonego: head pionu, potem Kadry ─────────────────────


@pytest.mark.asyncio
async def test_division_head_coordinates_people_without_a_manager(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        head = await _user(
            db, "head_of_recruitment", profile=True, employment_type="uop"
        )
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        person = await _user(
            db,
            "employee",
            profile=True,
            employment_type="zlecenie",
            division="front_office",
        )
        loner = await _user(
            db, "employee", profile=True, employment_type="b2b", division="back_office"
        )
        await db.commit()
    await _set(HR_DIVISIONS_SETTING, {"front_office": head.id, "back_office": None})

    preview = await app_client.post(
        BASE + "/preview", json=_body(), headers=_headers(person)
    )
    assert preview.json()["approver"] == head.name
    row = await _report(app_client, person)
    assert [
        b.title for b in await _bells(head.id, NotificationType.hr_absence_reported)
    ] == ["Zgłoszona nieobecność"]
    payload = await _pending_payload(app_client, head)
    assert row["id"] in {item["id"] for item in payload["reported"]}
    conflict = await app_client.post(
        f"{BASE}/{row['id']}/conflict",
        json={"note": "Spotkanie z klientem"},
        headers=_headers(head),
    )
    assert conflict.status_code == 200, conflict.text

    # Pion bez heada — informacja trafia do Kadr.
    other = await _report(
        app_client, loner, start=MON + timedelta(days=7), end=FRI + timedelta(days=7)
    )
    assert other["status"] == "approved"
    hr_bells = await _bells(hr.id, NotificationType.hr_absence_reported)
    assert hr_bells and hr_bells[-1].title == "Zgłoszona przerwa w świadczeniu usług"


# ── Decyzje Artura 19.10.2026 (audyt) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_only_hr_enters_absence_for_a_contractor(app_client, modules_on) -> None:
    # D5: zgłoszenie składa sama osoba; wpis za nią — Kadry i admin, jak
    # zmiana i anulowanie. Koordynator dostaje 403, a lista osób to mówi.
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, employment_type="uop")
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        person = await _user(
            db, "employee", profile=True, employment_type="b2b", manager_user_id=boss.id
        )
        colleague = await _user(
            db, "employee", profile=True, employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()
    body = {**_body(MON, MON), "user_id": person.id}
    refused = await app_client.post(
        BASE + "/approvals/on-behalf", json=body, headers=_headers(boss)
    )
    assert refused.status_code == 403
    assert "Kadry" in refused.json()["detail"]
    people = await app_client.get(BASE + "/approvals/people", headers=_headers(boss))
    flags = {row["user_id"]: row["can_enter"] for row in people.json()["items"]}
    assert flags[person.id] is False and flags[colleague.id] is True
    by_hr = await app_client.post(
        BASE + "/approvals/on-behalf", json=body, headers=_headers(hr)
    )
    assert by_hr.status_code == 201, by_hr.text


@pytest.mark.asyncio
async def test_hr_change_in_a_sent_report_tells_the_coordinator(
    app_client, modules_on
) -> None:
    # Kadry mogą zmienić nieobecność na dni z wysłanego raportu godzin, ale
    # koordynator dostaje dzwonek (bez rodzaju nieobecności, D6).
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, employment_type="uop")
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        person = await _user(
            db, "employee", profile=True, employment_type="b2b", manager_user_id=boss.id
        )
        await db.commit()
    month = f"/api/hr/time/me/{MON.year}/{MON.month}"
    filled = await app_client.post(f"{month}/fill", json={}, headers=_headers(person))
    assert filled.status_code == 200, filled.text
    sent = await app_client.post(f"{month}/submit", headers=_headers(person))
    assert sent.status_code == 200, sent.text

    entered = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={**_body(MON, MON), "user_id": person.id},
        headers=_headers(hr),
    )
    assert entered.status_code == 201, entered.text
    bells = await _bells(boss.id, NotificationType.hr_timesheet_decided)
    assert len(bells) == 1
    assert bells[0].title == "Raport godzin: godziny zmienione po wysłaniu"
    assert "listopad 2091" in bells[0].message
    for word in ("L4", "chorob", "urlop"):
        assert word not in bells[0].message
    assert await _bells(hr.id, NotificationType.hr_timesheet_decided) == []


@pytest.mark.asyncio
async def test_own_preview_shows_only_approved_absences_of_colleagues(
    app_client, modules_on
) -> None:
    # Oczekujące cudze wnioski widzi tylko krąg D6 (jak w kalendarzu zespołu).
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "delivery_lead", profile=True, employment_type="uop")
        me = await _user(
            db,
            "employee",
            profile=True,
            employment_type="uop",
            manager_user_id=boss.id,
            department="Audyt 19.10",
        )
        waiting = await _user(
            db,
            "employee",
            profile=True,
            employment_type="uop",
            manager_user_id=boss.id,
            department="Audyt 19.10",
        )
        await db.commit()
    pending = await _report(app_client, waiting, start=MON, end=MON)
    assert pending["status"] == "pending"
    preview = await app_client.post(
        BASE + "/preview",
        json={**_body(MON, FRI), "substitute_user_id": waiting.id},
        headers=_headers(me),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["department_absent"] == []
    assert preview.json()["substitute_absent"] is False
