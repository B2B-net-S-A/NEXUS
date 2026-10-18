"""Karta Microsoft 365 w Ustawieniach → Kadry — API ``/api/hr/admin/m365``.

Kadry (``people_admin``) i admin widzą tryb, kolejkę z podglądem żądań
symulacji i ponawiają operacje; pozostali dostają 403. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.hr_leave import HrM365MailboxState, HrM365Operation
from app.models.hr_ops import HrAuditEvent
from app.models.section_permission import UserActionOverride
from app.models.user import User
from app.services.hr.m365 import executor
from tests.hr.m365_helpers import at, make_due, make_leave, make_user, operations, plan

BASE = "/api/hr/admin/m365"


@pytest.fixture(autouse=True)
def _mounted():
    """Router wpina ``app/main.py``; do tego czasu test dokłada go sam."""

    from app.api import hr_m365
    from app.main import app

    if not any(getattr(route, "path", "").startswith(BASE) for route in app.routes):
        app.include_router(hr_m365.router, prefix=BASE, tags=["hr"])
    yield


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _people_admin(db) -> User:
    user = await make_user(db, profile=False)
    db.add(UserActionOverride(user_id=user.id, action="people_admin", access="manage"))
    await db.flush()
    return user


async def _queue(db) -> tuple[User, list[HrM365Operation]]:
    """Osoba z urlopem: autoodpowiedź zasymulowana, wydarzenie nieudane."""

    user = await make_user(db, name="Anna Przykładowa")
    leave = await make_leave(db, user, date(2026, 11, 2), date(2026, 11, 6))
    await plan(db, leave, "approved", today=date(2026, 10, 20))
    await make_due(db, [user.id])
    await db.commit()
    await executor.run_once(
        db, mode="simulate", now=at(date(2026, 10, 20)), user_ids=[user.id]
    )
    ops = await operations(db, user.id)
    ops[1].status = "failed"
    ops[1].attempts = 6
    ops[1].last_error = "forbidden (403)"
    db.add(HrM365MailboxState(user_id=user.id, custom_oof_detected=True, state={}))
    await db.commit()
    return user, ops


@pytest.mark.asyncio
async def test_people_admin_sees_mode_queue_and_simulated_request(app_client) -> None:
    async with AsyncSessionLocal() as db:
        kadry = await _people_admin(db)
        person, ops = await _queue(db)
        await db.commit()

    status = await app_client.get(f"{BASE}/status", headers=_headers(kadry))
    assert status.status_code == 200
    body = status.json()
    assert body["mode"] in ("off", "simulate", "live")
    assert body["credentials_configured"] is False
    assert body["counts"]["failed"] >= 1 and body["counts"]["simulated"] >= 1
    assert {"user_id": person.id, "name": "Anna Przykładowa"}.items() <= next(
        row for row in body["custom_oof_mailboxes"] if row["user_id"] == person.id
    ).items()

    simulated = await app_client.get(
        f"{BASE}/operations",
        params={"status": "simulated", "limit": 200},
        headers=_headers(kadry),
    )
    assert simulated.status_code == 200
    item = next(row for row in simulated.json()["items"] if row["id"] == ops[0].id)
    assert item["user_name"] == "Anna Przykładowa"
    assert item["simulated_request"]["requests"][-1]["method"] in ("PATCH", "POST")
    assert "leave_type" not in item and "sick" not in str(item).lower()

    failed = await app_client.get(
        f"{BASE}/operations",
        params={"status": "failed", "limit": 200},
        headers=_headers(kadry),
    )
    assert ops[1].id in {row["id"] for row in failed.json()["items"]}
    bad = await app_client.get(
        f"{BASE}/operations", params={"status": "zgubione"}, headers=_headers(kadry)
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_retry_puts_failed_operation_back_and_refuses_finished(
    app_client,
) -> None:
    async with AsyncSessionLocal() as db:
        admin = await make_user(db, role="admin", profile=False)
        _, ops = await _queue(db)

    retried = await app_client.post(
        f"{BASE}/operations/{ops[1].id}/retry", headers=_headers(admin)
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "pending"
    assert retried.json()["attempts"] == 0
    assert retried.json()["last_error"] is None

    finished = await app_client.post(
        f"{BASE}/operations/{ops[0].id}/retry", headers=_headers(admin)
    )
    assert finished.status_code == 409
    missing = await app_client.post(
        f"{BASE}/operations/999999999/retry", headers=_headers(admin)
    )
    assert missing.status_code == 404

    async with AsyncSessionLocal() as db:
        trail = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.action == "m365_operation_retried",
                HrAuditEvent.entity_id == str(ops[1].id),
            )
        )
    assert trail is not None and trail.actor_user_id == admin.id


@pytest.mark.asyncio
async def test_other_accounts_are_refused(app_client) -> None:
    async with AsyncSessionLocal() as db:
        recruiter = await make_user(db)
        employee = await make_user(db, role="employee")
        _, ops = await _queue(db)

    for user in (recruiter, employee):
        headers = _headers(user)
        assert (
            await app_client.get(f"{BASE}/status", headers=headers)
        ).status_code == 403
        assert (
            await app_client.get(f"{BASE}/operations", headers=headers)
        ).status_code == 403
        refused = await app_client.post(
            f"{BASE}/operations/{ops[1].id}/retry", headers=headers
        )
        assert refused.status_code == 403
    assert (await app_client.get(f"{BASE}/status")).status_code == 401
