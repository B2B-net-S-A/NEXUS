"""Wejście i odejście — API (krok E4): kto co widzi, kreator wejścia, odejście,
„Cofnij odejście”, zadania w dniach roboczych.

Uprawnienia: Kadry (``people_admin``) i admin prowadzą; przełożony widzi
i odhacza zadania swojego człowieka; wykonawca odhacza swoje; inni 403;
wyłączony moduł 404 (admin przechodzi). Dane fikcyjne (repo jest publiczne).
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
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr.calendar import load_calendar
from app.services.hr.lifecycle_dates import calendar_window, shift_working_days
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

BASE = "/api/hr/lifecycle"


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(
    db, role: str, *, roles: list[str] | None = None, profile: bool = False, **values
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"lc-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=roles or [role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **values))
        await db.flush()
    return user


async def _grant(db, user: User, action: str) -> None:
    db.add(UserActionOverride(user_id=user.id, action=action, access="manage"))
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
async def modules_off():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: False for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _future_weekday(days: int) -> date:
    day = business_today() + timedelta(days=days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


async def _team() -> dict[str, User]:
    """Kadry, przełożony, jego człowiek, recepcja i osoba z boku."""

    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter", profile=True)
        await _grant(db, hr, "people_admin")
        reception = await _user(db, "recruiter", profile=True)
        await _grant(db, reception, "equipment")
        boss = await _user(
            db, "delivery_lead", roles=["delivery_lead", "recruiter"], profile=True
        )
        worker = await _user(
            db,
            "recruiter",
            profile=True,
            manager_user_id=None,
            employment_type="uop",
            employment_status="active",
        )
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == worker.id)
        )
        profile.manager_user_id = boss.id
        outsider = await _user(db, "recruiter", profile=True)
        admin = await _user(db, "admin")
        await db.commit()
    return {
        "hr": hr,
        "reception": reception,
        "boss": boss,
        "worker": worker,
        "outsider": outsider,
        "admin": admin,
    }


@pytest.mark.asyncio
async def test_switched_off_module_is_404_for_hr_but_open_for_admin(
    app_client, modules_off
) -> None:
    team = await _team()
    denied = await app_client.get(f"{BASE}/templates", headers=_headers(team["hr"]))
    assert denied.status_code == 404
    assert denied.json()["detail"] == "Ten moduł nie jest jeszcze włączony."
    allowed = await app_client.get(f"{BASE}/templates", headers=_headers(team["admin"]))
    assert allowed.status_code == 200
    kinds = {row["kind"] for row in allowed.json()["items"]}
    assert {"onboarding", "offboarding"} <= kinds


@pytest.mark.asyncio
async def test_offboarding_scopes_hr_manager_assignee_and_outsider(
    app_client, modules_on
) -> None:
    team = await _team()
    last_day = _future_weekday(10)
    body = {
        "user_id": team["worker"].id,
        "last_working_day": last_day.isoformat(),
        "exit_initiator": "employee",
        "exit_reason": "new_opportunity",
        "exit_note": "Przechodzi do innej firmy.",
        "start": True,
    }

    forbidden = await app_client.post(
        f"{BASE}/cases/offboarding", json=body, headers=_headers(team["boss"])
    )
    assert forbidden.status_code == 403

    created = await app_client.post(
        f"{BASE}/cases/offboarding", json=body, headers=_headers(team["hr"])
    )
    assert created.status_code == 201, created.text
    case = created.json()
    assert case["status"] == "active"
    assert case["deactivate_on"] == (last_day + timedelta(days=1)).isoformat()
    assert case["manager_user_id"] == team["boss"].id
    assert case["exit_reason"] == "new_opportunity"
    kinds = [row["kind"] for row in case["work"]]
    assert len(kinds) == 8 and kinds[0] == "recruitments"
    # Domyślny przejmujący = przełożony (ma role rekrutera i DL-a).
    by_kind = {row["kind"]: row for row in case["work"]}
    assert by_kind["recruitments"]["receiver_user_id"] == team["boss"].id
    assert by_kind["pipeline_cards"]["transferable"] is False

    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == team["worker"].id)
        )
        assert profile.employment_status == "offboarding"
        assert profile.last_working_day == last_day

    # Przełożony widzi sprawę razem z powodem i odhacza każde zadanie.
    as_boss = await app_client.get(
        f"{BASE}/cases/{case['id']}", headers=_headers(team["boss"])
    )
    assert as_boss.status_code == 200
    assert as_boss.json()["scope"] == "manager"
    assert as_boss.json()["exit_reason"] == "new_opportunity"
    reception_task = next(
        t for t in as_boss.json()["tasks"] if t["assignee_kind"] == "reception"
    )
    manager_task = next(
        t for t in as_boss.json()["tasks"] if t["assignee_kind"] == "manager"
    )
    ticked = await app_client.patch(
        f"{BASE}/tasks/{manager_task['id']}",
        json={"status": "done"},
        headers=_headers(team["boss"]),
    )
    assert ticked.status_code == 200

    # Recepcja (uprawnienie Sprzęt) widzi sprawę bez powodu odejścia,
    # odhacza swoje zadanie, cudzego nie.
    as_reception = await app_client.get(
        f"{BASE}/cases/{case['id']}", headers=_headers(team["reception"])
    )
    assert as_reception.status_code == 200
    assert as_reception.json()["scope"] == "assignee"
    assert "exit_reason" not in as_reception.json()
    assert "exit_note" not in as_reception.json()
    own = await app_client.patch(
        f"{BASE}/tasks/{reception_task['id']}",
        json={"status": "done", "note": "Odebrane w biurze."},
        headers=_headers(team["reception"]),
    )
    assert own.status_code == 200
    foreign = await app_client.patch(
        f"{BASE}/tasks/{manager_task['id']}",
        json={"status": "open"},
        headers=_headers(team["reception"]),
    )
    assert foreign.status_code == 403

    # Osoba z boku: ani sprawa, ani zadanie, ani lista spraw.
    for path in (f"{BASE}/cases/{case['id']}", f"{BASE}/cases"):
        response = await app_client.get(path, headers=_headers(team["outsider"]))
        assert response.status_code == 403, path
    response = await app_client.patch(
        f"{BASE}/tasks/{manager_task['id']}",
        json={"status": "done"},
        headers=_headers(team["outsider"]),
    )
    assert response.status_code == 403

    # Lista przełożonego zawiera sprawę jego człowieka.
    listing = await app_client.get(f"{BASE}/cases", headers=_headers(team["boss"]))
    assert listing.status_code == 200
    assert case["id"] in {row["id"] for row in listing.json()["items"]}

    # Druga żywa sprawa odejścia tej samej osoby — 409.
    duplicate = await app_client.post(
        f"{BASE}/cases/offboarding", json=body, headers=_headers(team["hr"])
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_offboarding_refuses_a_last_day_in_the_past(
    app_client, modules_on
) -> None:
    team = await _team()
    response = await app_client.post(
        f"{BASE}/cases/offboarding",
        json={
            "user_id": team["worker"].id,
            "last_working_day": (business_today() - timedelta(days=1)).isoformat(),
        },
        headers=_headers(team["hr"]),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_exit_reason_outside_the_dictionary_is_rejected(
    app_client, modules_on
) -> None:
    team = await _team()
    response = await app_client.post(
        f"{BASE}/cases/offboarding",
        json={
            "user_id": team["worker"].id,
            "last_working_day": _future_weekday(10).isoformat(),
            "exit_reason": "health",
        },
        headers=_headers(team["hr"]),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cancel_offboarding_restores_the_profile_before_execution(
    app_client, modules_on
) -> None:
    team = await _team()
    created = await app_client.post(
        f"{BASE}/cases/offboarding",
        json={
            "user_id": team["worker"].id,
            "last_working_day": _future_weekday(12).isoformat(),
            "start": True,
        },
        headers=_headers(team["hr"]),
    )
    case_id = created.json()["id"]
    assert created.json()["can_cancel"] is True

    as_boss = await app_client.post(
        f"{BASE}/cases/{case_id}/cancel", headers=_headers(team["boss"])
    )
    assert as_boss.status_code == 403

    cancelled = await app_client.post(
        f"{BASE}/cases/{case_id}/cancel", headers=_headers(team["hr"])
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == team["worker"].id)
        )
        assert profile.employment_status == "active"
        assert profile.last_working_day is None

    again = await app_client.post(
        f"{BASE}/cases/{case_id}/cancel", headers=_headers(team["hr"])
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_cancel_after_handover_started_is_refused(app_client, modules_on) -> None:
    team = await _team()
    created = await app_client.post(
        f"{BASE}/cases/offboarding",
        json={
            "user_id": team["worker"].id,
            "last_working_day": _future_weekday(12).isoformat(),
            "start": True,
        },
        headers=_headers(team["hr"]),
    )
    case_id = created.json()["id"]
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, case_id)
        case.handover_executed_at = case.created_at
        await db.commit()
    refused = await app_client.post(
        f"{BASE}/cases/{case_id}/cancel", headers=_headers(team["hr"])
    )
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_onboarding_by_email_waits_for_the_account_and_dates_tasks_in_working_days(
    app_client, modules_on
) -> None:
    team = await _team()
    start = _future_weekday(20)
    while start.weekday() != 0:
        start += timedelta(days=1)
    email = f"nowa-{uuid.uuid4().hex[:8]}@example.com"
    draft = await app_client.post(
        f"{BASE}/cases/onboarding",
        json={
            "email": email,
            "name": "Kacper Przykładowy",
            "start_date": start.isoformat(),
            "manager_user_id": team["boss"].id,
            "profile": {"job_title": "Rekruter", "employment_type": "uop"},
        },
        headers=_headers(team["hr"]),
    )
    assert draft.status_code == 201, draft.text
    case = draft.json()
    assert case["status"] == "draft"
    assert case["user_id"] is None
    assert case["person_name"] == "Kacper Przykładowy"
    assert case["tasks"], "szablon startowy daje zadania"

    async with AsyncSessionLocal() as db:
        lo, hi = calendar_window(start)
        calendar = await load_calendar(db, lo, hi)
        rows = list(
            await db.scalars(
                select(LifecycleTask).where(LifecycleTask.case_id == case["id"])
            )
        )
        from app.models.hr_lifecycle import LifecycleTemplateItem

        for task in rows:
            item = await db.get(LifecycleTemplateItem, task.template_item_id)
            assert task.due_date == shift_working_days(
                calendar, start, item.due_offset_days
            )
            if item.due_offset_days != 0:
                assert calendar.is_working_day(task.due_date)
        manager_tasks = [t for t in rows if t.assignee_kind == "manager"]
        assert manager_tasks and all(
            t.assignee_user_id == team["boss"].id for t in manager_tasks
        )

    # Konta jeszcze nie ma — start czeka.
    early = await app_client.post(
        f"{BASE}/cases/{case['id']}/start", headers=_headers(team["hr"])
    )
    assert early.status_code == 409

    async with AsyncSessionLocal() as db:
        newcomer = User(
            email=email,
            name="Kacper Przykładowy",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(newcomer)
        await db.commit()
        newcomer_id = newcomer.id

    started = await app_client.post(
        f"{BASE}/cases/{case['id']}/start", headers=_headers(team["hr"])
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "active"
    assert started.json()["user_id"] == newcomer_id
    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == newcomer_id)
        )
        assert profile.employment_status == "onboarding"
        assert profile.work_start_date == start
        assert profile.manager_user_id == team["boss"].id
        assert profile.job_title == "Rekruter"
        person_tasks = list(
            await db.scalars(
                select(LifecycleTask).where(
                    LifecycleTask.case_id == case["id"],
                    LifecycleTask.assignee_kind == "person",
                )
            )
        )
        assert all(t.assignee_user_id == newcomer_id for t in person_tasks)

    # Wejście osobie, która już pracuje — 409.
    again = await app_client.post(
        f"{BASE}/cases/onboarding",
        json={"user_id": team["worker"].id, "start_date": start.isoformat()},
        headers=_headers(team["hr"]),
    )
    assert again.status_code == 409

    summary = await app_client.get(
        f"{BASE}/people/{newcomer_id}/summary", headers=_headers(newcomer)
    )
    assert summary.status_code == 200
    assert summary.json()["case"]["kind"] == "onboarding"
    outsider = await app_client.get(
        f"{BASE}/people/{newcomer_id}/summary", headers=_headers(team["outsider"])
    )
    assert outsider.status_code == 403

    completed = await app_client.post(
        f"{BASE}/cases/{case['id']}/complete", headers=_headers(team["hr"])
    )
    assert completed.status_code == 200
    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == newcomer_id)
        )
        assert profile.employment_status == "active"


@pytest.mark.asyncio
async def test_preview_and_template_edit_by_hr_only(app_client, modules_on) -> None:
    team = await _team()
    created = await app_client.post(
        f"{BASE}/templates",
        json={
            "kind": "onboarding",
            "name": "Wejście — dział testowy",
            "department": f"Dział {uuid.uuid4().hex[:6]}",
            "items": [
                {
                    "title": "Laptop",
                    "category": "equipment",
                    "assignee_kind": "reception",
                    "due_offset_days": -2,
                },
                {
                    "title": "Rozmowa",
                    "category": "meeting",
                    "assignee_kind": "manager",
                    "due_offset_days": 0,
                },
            ],
        },
        headers=_headers(team["hr"]),
    )
    assert created.status_code == 201, created.text
    template = created.json()
    preview = await app_client.post(
        f"{BASE}/preview",
        json={
            "kind": "onboarding",
            "anchor": "2026-11-02",
            "template_id": template["id"],
        },
        headers=_headers(team["hr"]),
    )
    assert preview.status_code == 200
    assert [t["due_date"] for t in preview.json()["tasks"]] == [
        "2026-10-29",
        "2026-11-02",
    ]

    bad = await app_client.put(
        f"{BASE}/templates/{template['id']}",
        json={
            **{k: template[k] for k in ("kind", "name")},
            "items": [{"title": "X", "due_offset_days": 500}],
        },
        headers=_headers(team["hr"]),
    )
    assert bad.status_code == 422
    denied = await app_client.post(
        f"{BASE}/templates",
        json={"kind": "onboarding", "name": "Nie wolno", "items": []},
        headers=_headers(team["boss"]),
    )
    assert denied.status_code == 403
