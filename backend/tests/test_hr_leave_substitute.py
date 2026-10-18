"""Zastępca nieobecnego przełożonego decyduje o wnioskach jego zespołu.

Plan §4 („Ludzie w NEXUSIE”): akceptacje dla przełożonego, zastępcy i Kadr.
Przełożony na zatwierdzonym urlopie obejmującym dziś (kalendarz firmy) wskazał
zastępcę — zastępca widzi i rozstrzyga wnioski podwładnych tego przełożonego
(tylko rodzaje planowe; L4 i pokrewne przyjmuje do wiadomości), dostaje
powiadomienie o nowym wniosku, a ślad mówi „w zastępstwie za …”. Te same
zasady w timesheetach. Dane fikcyjne (repo jest publiczne); wnioski zespołu
w 2091, urlop przełożonego wokół dzisiejszego dnia.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_leave import LeaveRequest
from app.models.hr_ops import HrAuditEvent
from app.models.hr_time import Timesheet
from app.models.user import User
from app.services.hr import leave_substitute, time_flow
from app.services.hr.leave_policy import (
    HEALTH_TYPES,
    SUBSTITUTE_VISIBLE_TYPES,
    covering_manager,
)
from app.services.hr.time_access import approval_recipients, load_actor
from app.services.hr.time_entries import TimeForbidden
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    grant,
    headers,
    make_user,
    notifications_of,
    time_on,
)

BASE = "/api/hr/leave"
MON = date(2091, 11, 12)
FRI = date(2091, 11, 16)


def _body(leave_type: str = "vacation", **extra) -> dict:
    return {
        "leave_type": leave_type,
        "start_date": MON.isoformat(),
        "end_date": FRI.isoformat(),
        **extra,
    }


async def _on_leave(
    db,
    manager: User,
    substitute: User,
    *,
    start: date,
    end: date,
    half_day: str | None = None,
    status: str = "approved",
) -> None:
    db.add(
        LeaveRequest(
            id=uuid.uuid4(),
            user_id=manager.id,
            leave_type="vacation",
            status=status,
            start_date=start,
            end_date=end,
            half_day=half_day,
            substitute_user_id=substitute.id,
            source="self",
            created_by=manager.id,
        )
    )
    await db.flush()


async def _team(*, leave_from: int = -1, leave_to: int = 3, half_day=None):
    """Przełożony na urlopie (dziś + przesunięcia) z zastępcą i podwładnym."""

    today = business_today()
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead")
        stand_in = await make_user(db, "recruiter")
        worker = await make_user(
            db, "recruiter", employment_type="uop", manager_user_id=boss.id
        )
        start = today + timedelta(days=leave_from)
        end = today + timedelta(days=leave_to)
        if half_day:
            start = end = today
        await _on_leave(db, boss, stand_in, start=start, end=end, half_day=half_day)
        await db.commit()
    return boss, stand_in, worker


async def _submit(app_client, user: User, leave_type: str = "vacation", **extra):
    created = await app_client.post(
        BASE + "/requests", json=_body(leave_type, **extra), headers=headers(user)
    )
    assert created.status_code == 201, created.text
    return created.json()


# ── Reguła (czysta) ───────────────────────────────────────────────────────────


def test_covering_manager_scope() -> None:
    assert (
        covering_manager(
            7, subject_user_id=9, subject_manager_id=3, covered_manager_ids=[3]
        )
        == 3
    )
    # Podwładny innego przełożonego.
    assert (
        covering_manager(
            7, subject_user_id=9, subject_manager_id=4, covered_manager_ids=[3]
        )
        is None
    )
    # Własny wniosek zastępcy (jest w zespole zastępowanego).
    assert (
        covering_manager(
            7, subject_user_id=7, subject_manager_id=3, covered_manager_ids=[3]
        )
        is None
    )
    # Wniosek samego zastępowanego przełożonego (jego przełożony to ktoś inny).
    assert (
        covering_manager(
            7, subject_user_id=3, subject_manager_id=1, covered_manager_ids=[3]
        )
        is None
    )


def test_health_types_are_never_visible_to_substitute() -> None:
    assert not SUBSTITUTE_VISIBLE_TYPES & HEALTH_TYPES
    for hidden in ("sick_leave", "care_leave", "force_majeure", "maternity"):
        assert hidden not in SUBSTITUTE_VISIBLE_TYPES
    for planned in ("vacation", "on_demand", "occasional"):
        assert planned in SUBSTITUTE_VISIBLE_TYPES


# ── Urlopy ────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_substitute_sees_queue_and_approves_with_trace(app_client) -> None:
    boss, stand_in, worker = await _team()
    request = await _submit(app_client, worker, note="Wyjazd rodzinny")

    to_boss = await notifications_of(boss.id, "hr_leave_requested")
    to_stand_in = await notifications_of(stand_in.id, "hr_leave_requested")
    assert len(to_boss) == 1
    assert len(to_stand_in) == 1
    assert f"w zastępstwie za {boss.name}" in to_stand_in[0][1]

    queue = await app_client.get(BASE + "/approvals/pending", headers=headers(stand_in))
    assert queue.status_code == 200, queue.text
    body = queue.json()
    assert [c["manager_user_id"] for c in body["covering"]] == [boss.id]
    assert body["covering"][0]["reports"] == 1
    row = next(item for item in body["items"] if item["id"] == request["id"])
    assert row["as_substitute_for"] == boss.name
    assert row["can_decide"] is True
    assert row["type_visible"] is True
    assert row["leave_type"] == "vacation"
    assert row["note"] is None  # notatka bywa o zdrowiu — tylko krąg D6

    approved = await app_client.post(
        f"{BASE}/approvals/{request['id']}/approve", headers=headers(stand_in)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by_name"] == stand_in.name

    decided = await notifications_of(worker.id, "hr_leave_decided")
    assert decided and f"(w zastępstwie za {boss.name})" in decided[-1][1]
    async with AsyncSessionLocal() as db:
        trace = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_id == request["id"],
                HrAuditEvent.action == "leave_approved",
            )
        )
    assert trace is not None
    assert trace.actor_user_id == stand_in.id
    assert trace.details["as_substitute_for_user_id"] == boss.id
    assert trace.details["as_substitute_for"] == f"w zastępstwie za {boss.name}"


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_substitute_rejects_with_trace(app_client) -> None:
    boss, stand_in, worker = await _team()
    request = await _submit(app_client, worker)
    rejected = await app_client.post(
        f"{BASE}/approvals/{request['id']}/reject",
        json={"note": "Ten tydzień jest zajęty"},
        headers=headers(stand_in),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    async with AsyncSessionLocal() as db:
        trace = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_id == request["id"],
                HrAuditEvent.action == "leave_rejected",
            )
        )
    assert trace.details["as_substitute_for_user_id"] == boss.id


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("leave_from", "leave_to", "half_day"),
    [(2, 5, None), (-6, -1, None), (0, 0, "morning")],
    ids=["urlop-od-jutra", "urlop-minal", "pol-dnia"],
)
async def test_substitute_outside_leave_window_is_403(
    app_client, leave_from, leave_to, half_day
) -> None:
    _, stand_in, worker = await _team(
        leave_from=leave_from, leave_to=leave_to, half_day=half_day
    )
    request = await _submit(app_client, worker)
    queue = await app_client.get(BASE + "/approvals/pending", headers=headers(stand_in))
    assert queue.status_code == 403
    approve = await app_client.post(
        f"{BASE}/approvals/{request['id']}/approve", headers=headers(stand_in)
    )
    assert approve.status_code == 403
    assert not await notifications_of(stand_in.id, "hr_leave_requested")


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_pending_leave_of_manager_does_not_make_a_substitute(
    app_client,
) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead")
        stand_in = await make_user(db, "recruiter")
        await make_user(db, "recruiter", manager_user_id=boss.id)
        await _on_leave(
            db,
            boss,
            stand_in,
            start=today,
            end=today + timedelta(days=2),
            status="pending",
        )
        await db.commit()
    queue = await app_client.get(BASE + "/approvals/pending", headers=headers(stand_in))
    assert queue.status_code == 403


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_substitute_of_a_cannot_decide_for_team_b(app_client) -> None:
    """Zakres to tylko podwładni nieobecnego przełożonego — wniosek spoza niego
    wygląda jak nieistniejący (404, jak u przełożonego cudzego zespołu)."""

    boss, stand_in, _ = await _team()
    async with AsyncSessionLocal() as db:
        other_boss = await make_user(db, "delivery_lead")
        other = await make_user(
            db, "recruiter", employment_type="uop", manager_user_id=other_boss.id
        )
        await db.commit()
    foreign = await _submit(app_client, other)
    approve = await app_client.post(
        f"{BASE}/approvals/{foreign['id']}/approve", headers=headers(stand_in)
    )
    assert approve.status_code == 404
    queue = await app_client.get(BASE + "/approvals/pending", headers=headers(stand_in))
    assert foreign["id"] not in {item["id"] for item in queue.json()["items"]}

    # Wniosek samego zastępowanego przełożonego też nie jest w zakresie.
    boss_request = await _submit(app_client, boss)
    denied = await app_client.post(
        f"{BASE}/approvals/{boss_request['id']}/approve", headers=headers(stand_in)
    )
    assert denied.status_code == 404


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_substitute_cannot_decide_own_request(app_client) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead")
        # Zastępca jest w zespole zastępowanego przełożonego.
        stand_in = await make_user(
            db, "recruiter", employment_type="uop", manager_user_id=boss.id
        )
        colleague = await make_user(
            db, "recruiter", employment_type="uop", manager_user_id=boss.id
        )
        await _on_leave(db, boss, stand_in, start=today, end=today + timedelta(days=4))
        await db.commit()
    own = await _submit(app_client, stand_in)
    # Własny wniosek zastępcy nie idzie do niego.
    assert not await notifications_of(stand_in.id, "hr_leave_requested")
    denied = await app_client.post(
        f"{BASE}/approvals/{own['id']}/approve", headers=headers(stand_in)
    )
    assert denied.status_code == 403
    queue = await app_client.get(BASE + "/approvals/pending", headers=headers(stand_in))
    assert queue.status_code == 200
    ids = {item["id"] for item in queue.json()["items"]}
    assert own["id"] not in ids
    other = await _submit(app_client, colleague)
    queue = await app_client.get(BASE + "/approvals/pending", headers=headers(stand_in))
    assert other["id"] in {item["id"] for item in queue.json()["items"]}


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_substitute_only_acknowledges_health_related_types(app_client) -> None:
    boss, stand_in, worker = await _team()
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        await db.commit()

    care = await _submit(app_client, worker, "care_leave", note="Opieka nad bliskim")
    queue = await app_client.get(BASE + "/approvals/pending", headers=headers(stand_in))
    row = next(item for item in queue.json()["items"] if item["id"] == care["id"])
    assert row["type_visible"] is False
    assert row["leave_type"] is None
    assert row["leave_type_label"] == "Nieobecność"
    assert row["note"] is None
    assert row["can_decide"] is False
    denied = await app_client.post(
        f"{BASE}/approvals/{care['id']}/approve", headers=headers(stand_in)
    )
    assert denied.status_code == 403
    assert "do wiadomości" in denied.json()["detail"]
    # Wniosek nie czeka do powrotu przełożonego: decydują też Kadry.
    assert await notifications_of(hr.id, "hr_leave_requested")
    ack = await notifications_of(stand_in.id, "hr_leave_requested")
    assert ack and ack[-1][0] == "Wniosek o nieobecność do wiadomości"
    assert "opiek" not in ack[-1][1].lower()
    by_hr = await app_client.post(
        f"{BASE}/approvals/{care['id']}/approve", headers=headers(hr)
    )
    assert by_hr.status_code == 200, by_hr.text

    # L4 jest zatwierdzone od razu — zastępca dostaje wiadomość bez rodzaju.
    async with AsyncSessionLocal() as db:
        sick_worker = await make_user(
            db, "recruiter", employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()
    await _submit(app_client, sick_worker, "sick_leave")
    reported = await notifications_of(stand_in.id, "hr_absence_reported")
    assert reported
    assert "L4" not in reported[-1][1] and "lekarsk" not in reported[-1][1]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_substitute_does_not_cancel_or_enter_on_behalf(app_client) -> None:
    boss, stand_in, worker = await _team()
    request = await _submit(app_client, worker)
    cancel = await app_client.post(
        f"{BASE}/approvals/{request['id']}/cancel", headers=headers(stand_in)
    )
    assert cancel.status_code == 404
    on_behalf = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={**_body(), "user_id": worker.id},
        headers=headers(stand_in),
    )
    assert on_behalf.status_code == 403
    history = await app_client.get(
        BASE + "/approvals/history", headers=headers(stand_in)
    )
    assert history.status_code == 200
    assert history.json()["items"] == []


# ── Timesheety ────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_substitute_approves_timesheet_of_covered_report(app_client) -> None:
    boss, stand_in, worker = await _team()
    async with AsyncSessionLocal() as db:
        other_boss = await make_user(db, "delivery_lead")
        other = await make_user(db, "employee", manager_user_id=other_boss.id)
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert sorted(await approval_recipients(db, worker.id)) == sorted(
            [boss.id, stand_in.id]
        )
        assert await approval_recipients(db, other.id) == [other_boss.id]

    sheets = {}
    for person in (worker, other):
        base = "/api/hr/time/me/2031/3"
        added = await app_client.post(
            f"{base}/entries",
            json={"work_date": "2031-03-03", "hours": 8, "description": "Sourcing"},
            headers=headers(person),
        )
        assert added.status_code == 201, added.text
        sent = await app_client.post(f"{base}/submit", headers=headers(person))
        assert sent.status_code == 200, sent.text
        sheets[person.id] = sent.json()["id"]
    assert await notifications_of(stand_in.id, "hr_timesheet_submitted")

    async with AsyncSessionLocal() as db:
        actor = await load_actor(db, stand_in)
        assert actor.is_approver
        subject = await _profile(db, worker.id)
        assert actor.can_approve(subject)
        assert actor.substitute_for(subject).manager_user_id == boss.id
        assert actor.sees_leave_type(subject) is False
        assert actor.cover_details(subject) == {
            "as_substitute_for_user_id": boss.id,
            "as_substitute_for": f"w zastępstwie za {boss.name}",
        }
        approved = await time_flow.approve(
            db, timesheet_id=sheets[worker.id], actor=actor
        )
        assert approved.status == "approved"
        with pytest.raises(TimeForbidden):
            await time_flow.approve(db, timesheet_id=sheets[other.id], actor=actor)
        await db.rollback()


async def _profile(db, user_id: int):
    from app.services.hr import people

    return await people.profile_of(db, user_id)


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_timesheet_substitute_scope_ends_with_leave() -> None:
    _, stand_in, worker = await _team(leave_from=-5, leave_to=-1)
    async with AsyncSessionLocal() as db:
        actor = await load_actor(db, stand_in)
        assert actor.is_approver is False
        assert actor.can_approve(await _profile(db, worker.id)) is False
        assert (
            await leave_substitute.covering_payload(db, stand_in.id, business_today())
            == []
        )
        assert (
            await db.scalar(select(Timesheet.id).where(Timesheet.user_id == worker.id))
            is None
        )
