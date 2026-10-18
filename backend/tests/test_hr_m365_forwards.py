"""Przekierowania poczty w karcie Microsoft 365 i „Uzgodnij teraz”.

* lista przekierowań zapisanych w NEXUSIE (trwające, nadchodzące, reguła
  mogła zostać po urlopie),
* „Sprawdź skrzynki” na ``FakeMailboxOps``: reguła trwającego urlopu,
  reguła po urlopie, reguła bez wniosku w NEXUSIE, urlop bez reguły; nic nie
  jest zapisywane w skrzynkach; przy trybie „Wyłączone” zdanie zamiast błędu,
* „Zamknij regułę” — operacja w kolejce; regułę trwającego urlopu ze zgodą
  zamyka się wyłączeniem przekierowania we wniosku (409),
* „Uzgodnij teraz” — przebieg mimo dziennej rezerwacji, odmowa przy
  równoległym przebiegu i przy wyłączonym Microsoft 365,
* każde działanie w śladzie; tylko Kadry i admin.

Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select, text, update

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.hr_leave import HrM365Operation
from app.models.hr_ops import HrAuditEvent, HrJobRun
from app.models.section_permission import UserActionOverride
from app.models.user import User
from app.services.hr import job_runs
from app.services.hr.m365 import forward_admin, reconcile
from tests.hr.fakes import FakeMailboxOps
from tests.hr.m365_helpers import at, make_leave, make_user, operations, plan

BASE = "/api/hr/admin/m365"
D = date
TODAY = D(2026, 10, 20)


@pytest.fixture(autouse=True)
def _mounted():
    from app.api import hr_m365
    from app.main import app

    if not any(getattr(route, "path", "").startswith(BASE) for route in app.routes):
        app.include_router(hr_m365.router, prefix=BASE, tags=["hr"])
    yield


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _kadry(db) -> User:
    user = await make_user(db, profile=False)
    db.add(UserActionOverride(user_id=user.id, action="people_admin", access="manage"))
    await db.flush()
    return user


async def _scene(db):
    """Osoba z trwającym urlopem ze zgodą i druga z urlopem po terminie."""

    substitute = await make_user(db, name="Ola Zastępczyni")
    running_owner = await make_user(db, name="Jan Trwający")
    running = await make_leave(
        db,
        running_owner,
        D(2026, 10, 19),
        D(2026, 10, 23),
        substitute=substitute,
        consent=True,
    )
    ended_owner = await make_user(db, name="Ewa Po Urlopie")
    ended = await make_leave(
        db,
        ended_owner,
        D(2026, 10, 12),
        D(2026, 10, 16),
        substitute=substitute,
        consent=True,
    )
    # Reguła urlopu po terminie weszła do skrzynki, zamknięcie się nie odbyło.
    await plan(db, ended, "approved", today=D(2026, 10, 1))
    await db.execute(
        update(HrM365Operation)
        .where(HrM365Operation.leave_request_id == ended.id)
        .values(status="done")
    )
    await db.flush()
    return substitute, running_owner, running, ended_owner, ended


async def test_saved_forwards_lists_running_and_possibly_left_rules() -> None:
    async with AsyncSessionLocal() as db:
        _, running_owner, running, ended_owner, ended = await _scene(db)
        await db.commit()
        result = await forward_admin.saved_forwards(db, today=TODAY)

    rows = {row["leave_request_id"]: row for row in result["items"]}
    assert rows[str(running.id)]["health"] == "ok"
    assert rows[str(running.id)]["substitute_name"] == "Ola Zastępczyni"
    assert rows[str(ended.id)]["health"] == "orphan"
    assert "skończyła się 16.10.2026" in rows[str(ended.id)]["reason"]
    assert "leave_type" not in rows[str(running.id)]


async def test_check_mailboxes_reads_rules_live_without_writing() -> None:
    fake = FakeMailboxOps()
    stray = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        _, running_owner, running, ended_owner, ended = await _scene(db)
        missing_owner = await make_user(db, name="Piotr Bez Reguły")
        missing = await make_leave(
            db,
            missing_owner,
            D(2026, 10, 19),
            D(2026, 10, 21),
            substitute=running_owner,
            consent=True,
        )
        await db.commit()
        fake.add_rule(running_owner.email, f"NEXUS · zastępstwo · {running.id}")
        fake.add_rule(ended_owner.email, f"COMPASS · zastępstwo · {ended.id}")
        fake.add_rule(ended_owner.email, f"NEXUS · zastępstwo · {stray}")
        fake.add_rule(ended_owner.email, "Faktury do folderu")
        result = await forward_admin.check_mailboxes(
            db,
            today=TODAY,
            ops=fake,
            mode="live",
            user_ids=[running_owner.id, ended_owner.id, missing_owner.id],
        )

    assert result["available"] is True
    assert result["scanned"] == 3
    by_leave = {item["leave_request_id"]: item for item in result["items"]}
    assert by_leave[str(running.id)]["health"] == "ok"
    assert by_leave[str(ended.id)]["health"] == "orphan"
    assert by_leave[str(ended.id)]["owner"] == "compass"
    assert by_leave[stray]["health"] == "unknown"
    assert by_leave[stray]["known"] is False
    assert by_leave[str(missing.id)]["health"] == "missing"
    assert by_leave[str(missing.id)]["rule_id"] is None
    assert len(result["items"]) == 4  # reguła spoza zastępstw nie jest pokazywana
    assert fake.writes == []


async def test_check_mailboxes_in_off_mode_says_so() -> None:
    async with AsyncSessionLocal() as db:
        result = await forward_admin.check_mailboxes(db, today=TODAY, mode="off")
    assert result["available"] is False
    assert "nie czyta skrzynek" in result["message"]


async def test_close_rule_queues_operation_and_refuses_needed_rule(app_client) -> None:
    stray = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        kadry = await _kadry(db)
        _, running_owner, running, ended_owner, ended = await _scene(db)
        await db.commit()

    stray_close = await app_client.post(
        f"{BASE}/forwards/close",
        json={"user_id": ended_owner.id, "leave_request_id": stray},
        headers=_headers(kadry),
    )
    assert stray_close.status_code == 200, stray_close.text
    assert stray_close.json()["known"] is False

    async with AsyncSessionLocal() as db:
        ops = [
            op
            for op in await operations(db, ended_owner.id)
            if op.kind == "forward_rule_close"
        ]
        trail = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.action == "m365_forward_close_requested",
                HrAuditEvent.entity_id == stray,
            )
        )
    (close,) = ops
    assert close.payload["leave_id"] == stray
    assert close.leave_request_id is None
    assert trail is not None and trail.actor_user_id == kadry.id


async def test_needed_rule_refusal_in_service() -> None:
    """Reguła trwającego urlopu ze zgodą — tylko przez wyłączenie przekierowania."""

    async with AsyncSessionLocal() as db:
        _, running_owner, running, _, _ = await _scene(db)
        await db.commit()
        with pytest.raises(forward_admin.ForwardAdminError):
            await forward_admin.close_rule(
                db,
                user_id=running_owner.id,
                leave_request_id=str(running.id),
                today=TODAY,
                actor_id=running_owner.id,
                now=at(TODAY),
            )


async def test_manual_reconcile_runs_after_daily_and_respects_running_pass() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM hr_job_runs WHERE kind LIKE 'hr_m365_reconcile%'")
        )
        await db.commit()
        user = await make_user(db)
        leave = await make_leave(
            db, user, D(2026, 10, 19), D(2026, 10, 23), source="compass_import"
        )
        await db.commit()
        daily = await reconcile.run_once(
            db, ops=fake, mode="live", now=at(TODAY, 7, 5), user_ids=[user.id]
        )
        assert daily["oof_enqueued"] == 1
        # Dzienny przebieg już był — „Uzgodnij teraz” i tak przechodzi (przed 7:00 też).
        manual = await reconcile.run_manual(
            db, ops=fake, mode="live", now=at(D(2026, 10, 21), 6, 0), user_ids=[user.id]
        )
        assert manual["status"] == "done"
        assert manual["counts"]["mailboxes"] == 1

        # Trwa inny przebieg — ręczny dostaje odmowę, dzienny czeka.
        lock = await job_runs.claim(
            db,
            reconcile.LOCK_KIND,
            reconcile.LOCK_KEY,
            at(D(2026, 10, 22), 7, 0),
            retake_done=True,
        )
        assert lock is not None
        # ``claimed_at`` to zegar bazy — test udaje 22.10, więc blokada musi mieć
        # tę samą chwilę, inaczej wyglądałaby na porzuconą (STALE_CLAIM).
        await db.execute(
            update(HrJobRun)
            .where(HrJobRun.id == lock)
            .values(claimed_at=at(D(2026, 10, 22), 7, 0))
        )
        await db.commit()
        refused = await reconcile.run_manual(
            db, ops=fake, mode="live", now=at(D(2026, 10, 22), 7, 1), user_ids=[user.id]
        )
        waiting = await reconcile.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 22), 7, 2), user_ids=[user.id]
        )
        day_row = await db.scalar(
            select(HrJobRun).where(
                HrJobRun.kind == reconcile.JOB_KIND, HrJobRun.period_key == "2026-10-22"
            )
        )
        await job_runs.finish(db, lock, status="done", counts={})
        ops = await operations(db, user.id)

    assert refused["status"] == reconcile.ALREADY_RUNNING
    assert waiting["skipped"] == reconcile.ALREADY_RUNNING
    assert day_row.status == "failed"  # kolejny obrót pętli przejmie dzień
    # Autoodpowiedź z porannego przebiegu czeka w kolejce — ręczny jej nie dubluje.
    assert [op.kind for op in ops] == ["set_oof"]
    assert {op.leave_request_id for op in ops} == {leave.id}


async def test_reconcile_endpoint_explains_off_mode_and_is_audited(app_client) -> None:
    async with AsyncSessionLocal() as db:
        kadry = await _kadry(db)
        recruiter = await make_user(db)
        await db.commit()

    response = await app_client.post(f"{BASE}/reconcile", headers=_headers(kadry))
    # W testach HR_M365_MODE = off.
    assert response.status_code == 409
    assert "wyłączony" in response.json()["detail"]
    check = await app_client.post(f"{BASE}/forwards/check", headers=_headers(kadry))
    assert check.status_code == 200
    assert check.json()["available"] is False
    listed = await app_client.get(f"{BASE}/forwards", headers=_headers(kadry))
    assert listed.status_code == 200

    for path, method in (
        ("/forwards", "get"),
        ("/forwards/check", "post"),
        ("/reconcile", "post"),
    ):
        refused = await getattr(app_client, method)(
            f"{BASE}{path}", headers=_headers(recruiter)
        )
        assert refused.status_code == 403, path

    async with AsyncSessionLocal() as db:
        actions = set(
            await db.scalars(
                select(HrAuditEvent.action).where(
                    HrAuditEvent.actor_user_id == kadry.id
                )
            )
        )
    assert {"m365_reconcile_requested", "m365_forwards_checked"} <= actions
