"""„Ludzie → Struktura” (etap 2, D4 i D7, 17.10.2026) — ``/api/hr/structure``.

Drzewo przełożonych z kartotek, piony (Front office / Back office z headem),
zmiana przełożonego wielu osób naraz OD RAZU (bez daty „od kiedy”) z regułami
kartoteki dla całego zbioru i śladem per osoba, rozjazd z Microsoft 365 jako
podpowiedź. Otwarte wnioski i timesheety po zmianie decyduje nowy przełożony,
bo akceptującego liczy się w chwili decyzji. Tylko Kadry i admin. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import lifecycle_service, people
from app.services.hr_foundation_schema import (
    HR_DIVISIONS_SETTING,
    HR_MODULE_KEYS,
    HR_MODULES_SETTING,
)

BASE = "/api/hr/structure"
MON = date(2091, 11, 12)
FRI = date(2091, 11, 16)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(
    db, role: str = "employee", *, profile: bool = True, active: bool = True, **values
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"structure-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=active,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **values))
        await db.flush()
    return user


async def _kadry(db) -> User:
    user = await _user(db, "recruiter", profile=False)
    db.add(UserActionOverride(user_id=user.id, action="people_admin", access="manage"))
    await db.flush()
    return user


async def _set_setting(key: str, value) -> None:
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
    await _set_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    yield
    await _set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )
    await _set_setting(HR_DIVISIONS_SETTING, heads)


async def _manager_of(user_id: int):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(EmployeeProfile.manager_user_id).where(
                EmployeeProfile.user_id == user_id
            )
        )


def _by_id(body: dict) -> dict[int, dict]:
    return {row["user_id"]: row for row in body["people"]}


# ── Odczyt ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_structure_is_only_for_kadry_and_admin(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter")
        await _user(db, manager_user_id=boss.id)
        worker = await _user(db)
        admin = await _user(db, "admin", profile=False)
        await db.commit()

    for outsider in (boss, worker):
        denied = await app_client.get(BASE, headers=_headers(outsider))
        assert denied.status_code == 403
        moved = await app_client.post(
            f"{BASE}/reassign",
            json={"user_ids": [worker.id], "manager_user_id": None},
            headers=_headers(outsider),
        )
        assert moved.status_code == 403
    assert (await app_client.get(BASE, headers=_headers(admin))).status_code == 200


@pytest.mark.asyncio
async def test_tree_counts_reports_marks_leavers_divisions_and_m365_hints(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _kadry(db)
        head = await _user(db, "head_of_recruitment", division="front_office")
        lead = await _user(
            db, "recruiter", manager_user_id=head.id, division="front_office"
        )
        first = await _user(
            db,
            manager_user_id=lead.id,
            division="front_office",
            m365_manager_upn=head.email.upper(),
        )
        second = await _user(db, manager_user_id=lead.id, m365_manager_upn=lead.email)
        orphan = await _user(
            db, division="front_office", m365_manager_upn="spoza-nexusa@example.com"
        )
        gone_boss = await _user(db, "recruiter", profile=False, active=False)
        stranded = await _user(db, manager_user_id=gone_boss.id)
        await db.commit()
        case = await lifecycle_service.create_offboarding(
            db,
            actor=hr,
            user_id=lead.id,
            last_working_day=date(2091, 11, 30),
            exit_initiator="employee",
            exit_reason="career_growth",
            exit_note=None,
            manager_user_id=None,
            manager_given=False,
            template_id=None,
        )
        await db.commit()

    saved = await app_client.put(
        f"{BASE}/divisions",
        json={"front_office": head.id},
        headers=_headers(hr),
    )
    assert saved.status_code == 200, saved.text
    response = await app_client.get(BASE, headers=_headers(hr))
    assert response.status_code == 200, response.text
    body = response.json()
    rows = _by_id(body)

    assert rows[head.id]["reports"] == 1
    assert rows[lead.id]["reports"] == 2
    assert rows[lead.id]["manager_state"] == "ok"
    assert rows[lead.id]["leaving"]["case_id"] == case.id
    assert rows[lead.id]["leaving"]["last_working_day"] == "2091-11-30"
    # Domyślnie podwładnych przejmuje przełożony odchodzącej (D5).
    assert rows[lead.id]["leaving"]["reports_receiver_user_id"] == head.id
    assert rows[lead.id]["leaving"]["reports_receiver_name"] == head.name
    assert rows[stranded.id]["manager_state"] == "inactive"
    assert rows[orphan.id]["manager_state"] == "none"

    front = next(item for item in body["divisions"] if item["key"] == "front_office")
    assert front["head_user_id"] == head.id and front["label"] == "Front office"
    assert rows[first.id]["division"] == "front_office"
    # Bez przełożonego w pionie z headem → podpowiedź, bez zapisu.
    assert rows[orphan.id]["suggested_manager"] == {
        "user_id": head.id,
        "name": head.name,
    }
    assert rows[head.id]["suggested_manager"] is None, "head nie podlega sam sobie"
    assert rows[first.id]["suggested_manager"] is None, "ma przełożonego"
    assert await _manager_of(orphan.id) is None

    # Rozjazd z M365: tylko podpowiedź (wielkość liter bez znaczenia).
    assert rows[first.id]["m365_hint"] == {
        "upn": head.email.lower(),
        "user_id": head.id,
        "name": head.name,
        "can_accept": True,
    }
    assert rows[second.id]["m365_hint"] is None, "katalog zgodny z kartoteką"
    assert rows[orphan.id]["m365_hint"]["user_id"] is None
    assert rows[orphan.id]["m365_hint"]["can_accept"] is False
    assert await _manager_of(first.id) == lead.id


# ── Zmiana przełożonego ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reassign_moves_many_at_once_with_trail_per_person(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _kadry(db)
        old = await _user(db, "recruiter")
        new = await _user(db, "recruiter")
        first = await _user(db, manager_user_id=old.id)
        second = await _user(db, manager_user_id=old.id)
        already = await _user(db, manager_user_id=new.id)
        await db.commit()

    moved = await app_client.post(
        f"{BASE}/reassign",
        json={"user_ids": [first.id, second.id, already.id], "manager_user_id": new.id},
        headers=_headers(hr),
    )
    assert moved.status_code == 200, moved.text
    assert sorted(moved.json()["changed"]) == sorted([first.id, second.id])
    assert moved.json()["unchanged"] == [already.id]
    assert await _manager_of(first.id) == new.id
    assert await _manager_of(second.id) == new.id
    async with AsyncSessionLocal() as db:
        trail = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.subject_user_id.in_([first.id, second.id, already.id]),
                    HrAuditEvent.action == "profile_updated",
                )
            )
        )
    assert len(trail) == 2
    assert {event.actor_user_id for event in trail} == {hr.id}
    assert {event.details["previous_manager_user_id"] for event in trail} == {old.id}
    assert {event.details["source"] for event in trail} == {"structure"}

    cleared = await app_client.post(
        f"{BASE}/reassign",
        json={"user_ids": [first.id], "manager_user_id": None},
        headers=_headers(hr),
    )
    assert cleared.status_code == 200
    assert await _manager_of(first.id) is None

    # Brak klucza to nie „bez przełożonego” — trzeba to powiedzieć wprost.
    missing_key = await app_client.post(
        f"{BASE}/reassign", json={"user_ids": [second.id]}, headers=_headers(hr)
    )
    assert missing_key.status_code == 422
    assert await _manager_of(second.id) == new.id


@pytest.mark.asyncio
async def test_reassign_refuses_like_the_profile_does_for_the_whole_set(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _kadry(db)
        top = await _user(db, "recruiter")
        middle = await _user(db, "recruiter", manager_user_id=top.id)
        other = await _user(db)
        inactive = await _user(db, "recruiter", active=False)
        exited = await _user(db, employment_status="exited")
        no_profile = await _user(db, profile=False)
        await db.commit()

    async def reassign(user_ids: list[int], manager_id):
        return await app_client.post(
            f"{BASE}/reassign",
            json={"user_ids": user_ids, "manager_user_id": manager_id},
            headers=_headers(hr),
        )

    itself = await reassign([other.id, top.id], top.id)
    assert itself.status_code == 422
    assert "własnym przełożonym" in itself.json()["detail"]
    # `middle` podlega `top` — przepięcie `top` (razem z kimś) pod `middle` = pętla.
    loop = await reassign([other.id, top.id], middle.id)
    assert loop.status_code == 422
    assert "pętlę" in loop.json()["detail"]
    dead = await reassign([other.id], inactive.id)
    assert dead.status_code == 422
    assert "aktywnego konta" in dead.json()["detail"]
    left = await reassign([exited.id], top.id)
    assert left.status_code == 422
    unknown = await reassign([no_profile.id], top.id)
    assert unknown.status_code == 404
    # Odmowa nie zmienia nikogo ze zbioru.
    assert await _manager_of(other.id) is None
    assert await _manager_of(top.id) is None


@pytest.mark.asyncio
async def test_open_requests_and_timesheets_follow_the_new_manager(
    app_client, modules_on
) -> None:
    """Zmiana od razu: wniosek i timesheet złożone przed zmianą decyduje nowy
    przełożony (akceptujący liczy się w chwili decyzji, nie złożenia)."""

    async with AsyncSessionLocal() as db:
        hr = await _kadry(db)
        old = await _user(db, "recruiter")
        new = await _user(db, "recruiter")
        # Umowa o pracę: wniosek czeka na decyzję (na B2B i zleceniu nie ma
        # decyzji — D5).
        worker = await _user(db, manager_user_id=old.id, employment_type="uop")
        await _user(db, manager_user_id=old.id)  # stary zostaje przełożonym
        timesheet = Timesheet(
            user_id=worker.id, year=2091, month=11, status="submitted"
        )
        db.add(timesheet)
        await db.commit()
        timesheet_id = timesheet.id

    created = await app_client.post(
        "/api/hr/leave/requests",
        json={
            "leave_type": "vacation",
            "start_date": MON.isoformat(),
            "end_date": FRI.isoformat(),
        },
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]

    moved = await app_client.post(
        f"{BASE}/reassign",
        json={"user_ids": [worker.id], "manager_user_id": new.id},
        headers=_headers(hr),
    )
    assert moved.status_code == 200

    old_queue = await app_client.get(
        "/api/hr/leave/approvals/pending", headers=_headers(old)
    )
    assert request_id not in {item["id"] for item in old_queue.json()["items"]}
    new_queue = await app_client.get(
        "/api/hr/leave/approvals/pending", headers=_headers(new)
    )
    assert request_id in {item["id"] for item in new_queue.json()["items"]}

    by_old = await app_client.post(
        f"/api/hr/leave/approvals/{request_id}/approve", headers=_headers(old)
    )
    assert by_old.status_code == 404
    by_new = await app_client.post(
        f"/api/hr/leave/approvals/{request_id}/approve", headers=_headers(new)
    )
    assert by_new.status_code == 200, by_new.text

    ts_old = await app_client.post(
        f"/api/hr/time/timesheets/{timesheet_id}/approve", headers=_headers(old)
    )
    assert ts_old.status_code in (403, 404)
    ts_new = await app_client.post(
        f"/api/hr/time/timesheets/{timesheet_id}/approve", headers=_headers(new)
    )
    assert ts_new.status_code == 200, ts_new.text
    assert ts_new.json()["status"] == "approved"


# ── Piony ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_division_heads_and_bulk_division(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _kadry(db)
        front = await _user(db, "head_of_recruitment")
        back = await _user(db, "talent_community_manager")
        gone = await _user(db, "recruiter", active=False)
        first = await _user(db)
        second = await _user(db)
        await db.commit()
    await _set_setting(HR_DIVISIONS_SETTING, None)

    refused = await app_client.put(
        f"{BASE}/divisions", json={"front_office": gone.id}, headers=_headers(hr)
    )
    assert refused.status_code == 422
    both = await app_client.put(
        f"{BASE}/divisions",
        json={"front_office": front.id, "back_office": back.id},
        headers=_headers(hr),
    )
    assert both.json()["heads"] == {"front_office": front.id, "back_office": back.id}
    # Pion pominięty zostaje, `null` czyści.
    partial = await app_client.put(
        f"{BASE}/divisions", json={"back_office": None}, headers=_headers(hr)
    )
    assert partial.json()["heads"] == {"front_office": front.id, "back_office": None}
    denied = await app_client.put(
        f"{BASE}/divisions", json={"back_office": back.id}, headers=_headers(first)
    )
    assert denied.status_code == 403

    bulk = await app_client.post(
        f"{BASE}/division",
        json={"user_ids": [first.id, second.id], "division": "back_office"},
        headers=_headers(hr),
    )
    assert bulk.status_code == 200 and len(bulk.json()["changed"]) == 2
    wrong = await app_client.post(
        f"{BASE}/division",
        json={"user_ids": [first.id], "division": "middle_office"},
        headers=_headers(hr),
    )
    assert wrong.status_code == 422
    async with AsyncSessionLocal() as db:
        divisions = set(
            await db.scalars(
                select(EmployeeProfile.division).where(
                    EmployeeProfile.user_id.in_([first.id, second.id])
                )
            )
        )
    assert divisions == {"back_office"}


@pytest.mark.asyncio
async def test_profile_form_saves_division_and_rejects_unknown(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _kadry(db)
        worker = await _user(db)
        await db.commit()

    saved = await app_client.patch(
        f"/api/hr/admin/profiles/{worker.id}",
        json={"division": "front_office"},
        headers=_headers(hr),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["division"] == "front_office"
    wrong = await app_client.patch(
        f"/api/hr/admin/profiles/{worker.id}",
        json={"division": "middle_office"},
        headers=_headers(hr),
    )
    assert wrong.status_code == 422
    async with AsyncSessionLocal() as db:
        with pytest.raises(people.HrPeopleError):
            await people.update_profile(
                db, user_id=worker.id, values={"division": "middle_office"}, actor=hr
            )
        await db.rollback()
