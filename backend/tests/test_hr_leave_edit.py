"""Zmiana cudzego wniosku i wyłączenie przekierowania przez Kadry — API.

``PATCH /api/hr/leave/approvals/{id}`` (rodzaj, daty, pół dnia, zastępca):
przeliczenie dni i puli, kolizje, operacje Microsoft 365 z nowym oknem,
zachowana zgoda na przekierowanie i własny tekst autoodpowiedzi,
powiadomienie osoby; odmowy dla obcego zespołu, własnego wniosku,
koordynatora zgłoszenia B2B i zamkniętego wniosku.
``POST …/forward-off`` — tylko Kadry, z powodem w śladzie.
Liczniki statusów i źródło w „Wszystkich wnioskach”. Dane fikcyjne, daty w 2092.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
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
MON = date(2092, 10, 13)  # poniedziałek
FRI = date(2092, 10, 17)
NEXT_MON = date(2092, 10, 20)
NEXT_WED = date(2092, 10, 22)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, *, profile: bool = True, **values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"edit-{marker}@example.com",
        name=f"Osoba Edycja {marker}",
        role=UserRole.recruiter,
        roles=["recruiter"],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **values))
        await db.flush()
    return user


async def _kadry(db) -> User:
    user = await _user(db, profile=False)
    db.add(UserActionOverride(user_id=user.id, action="people_admin", access="manage"))
    await db.flush()
    return user


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


async def _team(*, form: str = "uop", pool: str | None = "26"):
    async with AsyncSessionLocal() as db:
        boss = await _user(db)
        old_sub = await _user(db)
        new_sub = await _user(db)
        worker = await _user(db, employment_type=form, manager_user_id=boss.id)
        if pool is not None:
            db.add(
                LeaveEntitlement(
                    user_id=worker.id, year=MON.year, entitlement_days=Decimal(pool)
                )
            )
        await db.commit()
    return boss, worker, old_sub, new_sub


def _body(start: date = MON, end: date = FRI, **extra) -> dict:
    return {
        "leave_type": "vacation",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        **extra,
    }


async def _ops(request_id: str) -> list[HrM365Operation]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(HrM365Operation)
            .where(HrM365Operation.leave_request_id == uuid.UUID(request_id))
            .order_by(HrM365Operation.id)
        )
        return list(rows.all())


async def _approved(app_client, boss, worker, **extra) -> str:
    created = await app_client.post(
        BASE + "/requests", json=_body(**extra), headers=_headers(worker)
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    approved = await app_client.post(
        f"{BASE}/approvals/{request_id}/approve", headers=_headers(boss)
    )
    assert approved.status_code == 200, approved.text
    return request_id


async def test_manager_moves_approved_leave_and_m365_follows(
    app_client, modules_on
) -> None:
    boss, worker, old_sub, new_sub = await _team()
    request_id = await _approved(
        app_client,
        boss,
        worker,
        substitute_user_id=old_sub.id,
        forward_mail_consent=True,
        oof_internal_message="Wracam w poniedziałek",
    )
    before = {op.dedupe_key for op in await _ops(request_id)}

    edited = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={
            "start_date": NEXT_MON.isoformat(),
            "end_date": NEXT_WED.isoformat(),
            "substitute_user_id": new_sub.id,
        },
        headers=_headers(boss),
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["status"] == "approved"
    assert (body["start_date"], body["end_date"]) == (
        NEXT_MON.isoformat(),
        NEXT_WED.isoformat(),
    )
    assert body["days_total"] == "3.0"
    assert body["substitute_user_id"] == new_sub.id
    # Zgodę osoba dała na poprzedniego zastępcę — nowy jej nie dziedziczy.
    assert body["forward_mail_consent"] is False

    added = [op for op in await _ops(request_id) if op.dedupe_key not in before]
    kinds = [op.kind for op in added]
    assert kinds == [
        "clear_oof",
        "set_oof",
        "calendar_event_upsert",
        "forward_rule_close",
    ]
    set_oof = added[1]
    assert set_oof.payload["start"] == NEXT_MON.isoformat()
    # Własny tekst autoodpowiedzi osoby zostaje po zmianie.
    assert set_oof.payload["internal_message"] == "Wracam w poniedziałek"
    assert set_oof.payload["substitute_user_id"] == new_sub.id

    async with AsyncSessionLocal() as db:
        bells = list(
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == worker.id,
                    Notification.notification_type == NotificationType.hr_leave_decided,
                )
            )
        )
        trail = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_id == request_id,
                    HrAuditEvent.action == "leave_edited",
                )
            )
        )
    edited_bell = next(bell for bell in bells if bell.title == "Zmieniono Twój wniosek")
    assert "Przekierowanie poczty do zastępcy wyłączone" in edited_bell.message
    (event,) = trail
    assert event.details["changed"] == ["end_date", "start_date", "substitute_user_id"]
    assert event.details["before"]["start_date"] == MON.isoformat()
    assert event.details["forward_consent_dropped"] is True


async def test_edit_keeps_consent_with_the_same_substitute(
    app_client, modules_on
) -> None:
    boss, worker, substitute, _ = await _team()
    request_id = await _approved(
        app_client,
        boss,
        worker,
        substitute_user_id=substitute.id,
        forward_mail_consent=True,
    )
    before = {op.dedupe_key for op in await _ops(request_id)}
    edited = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"end_date": date(2092, 10, 15).isoformat()},
        headers=_headers(boss),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["forward_mail_consent"] is True
    kinds = [op.kind for op in await _ops(request_id) if op.dedupe_key not in before]
    assert kinds[-2:] == ["forward_rule_close", "forward_rule_open"]


async def test_edit_after_parallel_cancel_is_a_conflict(app_client, modules_on) -> None:
    """Edycja z nieaktualnym stanem wniosku (anulowany w innej sesji) = 409."""

    from app.services.hr import leave_edit, leave_service

    boss, worker, _, _ = await _team()
    request_id = await _approved(app_client, boss, worker)
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, boss.id)
        seen = await db.get(LeaveRequest, uuid.UUID(request_id))
        assert seen.status == "approved"
        async with AsyncSessionLocal() as other:
            other_actor = await other.get(User, boss.id)
            await leave_service.cancel_as_approver(
                other,
                actor=other_actor,
                request_id=uuid.UUID(request_id),
                today=MON,
                # Pierwszy dzień urlopu — od 28.10.2026 cofnięcie wymaga powodu.
                reason="Wpis pomyłkowy",
            )
            await other.commit()
        try:
            await leave_edit.edit_request(
                db,
                actor=actor,
                request_id=uuid.UUID(request_id),
                changes=leave_edit.LeaveChanges(end_date=date(2092, 10, 15)),
                today=MON,
            )
        except leave_service.LeaveConflict:
            await db.rollback()
        else:
            raise AssertionError("edycja anulowanego wniosku przeszła")
        active = await db.scalars(
            select(LeaveRequestDay.active).where(
                LeaveRequestDay.leave_request_id == uuid.UUID(request_id)
            )
        )
        assert not any(active.all())


async def test_parallel_edits_keep_both_changes(app_client, modules_on) -> None:
    """Audyt 19.10.2026: druga edycja liczyła wartości przed blokadą i
    zapisywała stare daty — zmiana pierwszej edycji znikała bez śladu."""

    from app.services.hr import leave_edit

    boss, worker, old_sub, _ = await _team()
    request_id = await _approved(app_client, boss, worker)
    thursday = date(2092, 10, 16)
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, boss.id)
        seen = await db.get(LeaveRequest, uuid.UUID(request_id))
        assert seen.end_date == FRI
        async with AsyncSessionLocal() as other:
            other_actor = await other.get(User, boss.id)
            await leave_edit.edit_request(
                other,
                actor=other_actor,
                request_id=uuid.UUID(request_id),
                changes=leave_edit.LeaveChanges(end_date=thursday),
                today=MON,
            )
            await other.commit()
        await leave_edit.edit_request(
            db,
            actor=actor,
            request_id=uuid.UUID(request_id),
            changes=leave_edit.LeaveChanges(substitute_user_id=old_sub.id),
            today=MON,
        )
        await db.commit()
    async with AsyncSessionLocal() as check:
        row = await check.get(LeaveRequest, uuid.UUID(request_id))
        days = await check.scalars(
            select(LeaveRequestDay.day).where(
                LeaveRequestDay.leave_request_id == row.id,
                LeaveRequestDay.active.is_(True),
            )
        )
        active_days = sorted(days.all())
    assert (row.end_date, row.substitute_user_id) == (thursday, old_sub.id)
    assert active_days[-1] == thursday


async def test_edit_recounts_pool_and_refuses_overlap_and_over_limit(
    app_client, modules_on
) -> None:
    boss, worker, _, _ = await _team(pool="7")
    request_id = await _approved(app_client, boss, worker)
    other = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={**_body(NEXT_WED, NEXT_WED), "user_id": worker.id},
        headers=_headers(boss),
    )
    assert other.status_code == 201, other.text

    overlap = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"end_date": NEXT_WED.isoformat()},
        headers=_headers(boss),
    )
    assert overlap.status_code == 409
    # Pula 7, 1 dzień wpisany za pracownika — 7 dni roboczych to ponad pulę.
    over = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"end_date": date(2092, 10, 21).isoformat()},
        headers=_headers(boss),
    )
    assert over.status_code == 422
    assert "zostało" in over.json()["detail"]

    shorter = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={
            "start_date": MON.isoformat(),
            "end_date": MON.isoformat(),
            "half_day": "morning",
        },
        headers=_headers(boss),
    )
    assert shorter.status_code == 200, shorter.text
    assert shorter.json()["days_total"] == "0.5"
    balance = (
        await app_client.get(
            BASE + "/balance", params={"year": MON.year}, headers=_headers(worker)
        )
    ).json()
    assert balance["remaining_days"] == "5.5"


async def test_edit_refusals(app_client, modules_on) -> None:
    boss, worker, _, _ = await _team()
    request_id = await _approved(app_client, boss, worker)
    async with AsyncSessionLocal() as db:
        stranger = await _user(db)
        await _user(db, manager_user_id=stranger.id)  # stranger ma swój zespół
        await db.commit()

    foreign = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"end_date": MON.isoformat()},
        headers=_headers(stranger),
    )
    assert foreign.status_code == 404
    unknown = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"forward_mail_consent": False},
        headers=_headers(boss),
    )
    assert unknown.status_code == 422  # zgoda nie należy do edycji
    bad_type = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"leave_type": "nie_ma_takiego"},
        headers=_headers(boss),
    )
    assert bad_type.status_code == 422

    cancelled = await app_client.post(
        f"{BASE}/approvals/{request_id}/cancel", headers=_headers(boss)
    )
    assert cancelled.status_code == 200
    closed = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"end_date": MON.isoformat()},
        headers=_headers(boss),
    )
    assert closed.status_code == 409


async def test_b2b_report_is_edited_by_hr_not_by_coordinator(
    app_client, modules_on
) -> None:
    coordinator, worker, _, _ = await _team(form="b2b", pool=None)
    async with AsyncSessionLocal() as db:
        kadry = await _kadry(db)
        await db.commit()
    reported = await app_client.post(
        BASE + "/requests", json=_body(), headers=_headers(worker)
    )
    assert reported.status_code == 201, reported.text
    request_id = reported.json()["id"]

    by_coordinator = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"end_date": date(2092, 10, 15).isoformat()},
        headers=_headers(coordinator),
    )
    assert by_coordinator.status_code == 403
    by_hr = await app_client.patch(
        f"{BASE}/approvals/{request_id}",
        json={"end_date": date(2092, 10, 15).isoformat()},
        headers=_headers(kadry),
    )
    assert by_hr.status_code == 200, by_hr.text
    assert by_hr.json()["days_total"] == "3.0"
    async with AsyncSessionLocal() as db:
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == worker.id,
                Notification.notification_type == NotificationType.hr_leave_decided,
            )
        )
    assert bell is not None and bell.title == "Zmieniono Twoje zgłoszenie"


async def test_hr_switches_off_forwarding_with_reason(app_client, modules_on) -> None:
    boss, worker, substitute, _ = await _team()
    request_id = await _approved(
        app_client,
        boss,
        worker,
        substitute_user_id=substitute.id,
        forward_mail_consent=True,
    )
    async with AsyncSessionLocal() as db:
        kadry = await _kadry(db)
        await db.commit()

    by_manager = await app_client.post(
        f"{BASE}/approvals/{request_id}/forward-off",
        json={"reason": "Zastępca prosi o wyłączenie"},
        headers=_headers(boss),
    )
    assert by_manager.status_code == 403
    no_reason = await app_client.post(
        f"{BASE}/approvals/{request_id}/forward-off",
        json={"reason": " "},
        headers=_headers(kadry),
    )
    assert no_reason.status_code == 422
    off = await app_client.post(
        f"{BASE}/approvals/{request_id}/forward-off",
        json={"reason": "Zastępca prosi o wyłączenie"},
        headers=_headers(kadry),
    )
    assert off.status_code == 200, off.text
    assert off.json()["forward_mail_consent"] is False
    again = await app_client.post(
        f"{BASE}/approvals/{request_id}/forward-off",
        json={"reason": "Drugi raz"},
        headers=_headers(kadry),
    )
    assert again.status_code == 409

    ops = await _ops(request_id)
    assert ops[-1].kind == "forward_rule_close"
    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_id == request_id,
                HrAuditEvent.action == "forward_consent_off",
            )
        )
        stored = await db.get(LeaveRequest, uuid.UUID(request_id))
    assert event.actor_user_id == kadry.id
    assert event.details["reason"] == "Zastępca prosi o wyłączenie"
    assert stored.forward_mail_consent is False


async def test_history_counts_per_status_and_source(app_client, modules_on) -> None:
    boss, worker, _, _ = await _team()
    await _approved(app_client, boss, worker)
    pending = await app_client.post(
        BASE + "/requests",
        json=_body(NEXT_MON, NEXT_WED),
        headers=_headers(worker),
    )
    assert pending.status_code == 201
    entered = await app_client.post(
        BASE + "/approvals/on-behalf",
        json={**_body(date(2092, 12, 1), date(2092, 12, 1)), "user_id": worker.id},
        headers=_headers(boss),
    )
    assert entered.status_code == 201

    history = await app_client.get(
        BASE + "/approvals/history",
        params={"user_id": worker.id, "status": "pending"},
        headers=_headers(boss),
    )
    assert history.status_code == 200, history.text
    payload = history.json()
    assert [item["status"] for item in payload["items"]] == ["pending"]
    assert payload["counts"] == {
        "all": 3,
        "pending": 1,
        "approved": 2,
        "rejected": 0,
        "cancelled": 0,
    }
    everything = (
        await app_client.get(
            BASE + "/approvals/history",
            params={"user_id": worker.id},
            headers=_headers(boss),
        )
    ).json()
    assert sorted(item["source"] for item in everything["items"]) == [
        "on_behalf",
        "self",
        "self",
    ]
