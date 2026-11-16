"""„Dałem znać” po stronie zastępcy (16.11.2026) — Postgres, trasy HTTP.

Zamknięcie rekrutacji z osobami w toku, które przyszło do zastępcy w czasie
nieobecności, ma w okienku „Rekrutacje” stan sprawy (``away_case``). Zastępca
oznacza je jako załatwione, osoba po powrocie widzi to samo w „Gdy Cię nie
było”, a ktoś trzeci dostaje 404 i niczego nie zmienia.

Wspólna baza CI: każdy test zakłada własne konta.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


async def _new_user(db, label: str) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    password = f"T3st_{suffix}!"
    user = User(
        email=f"away-{label}-{suffix}@example.com",
        password_hash=hash_password(password),
        name=f"{label.capitalize()} {suffix}",
        role=UserRole.recruiter,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def ctx(app_client: AsyncClient) -> dict[str, Any]:
    job_id = 900_000 + int(uuid.uuid4().int % 90_000)
    async with AsyncSessionLocal() as db:
        owner, owner_pwd = await _new_user(db, "wraca")
        deputy, deputy_pwd = await _new_user(db, "zastepca")
        third, third_pwd = await _new_user(db, "trzeci")
        # Cichy wiersz: zastępca sam zamknął rekrutację za nieobecną osobę.
        row = Notification(
            user_id=deputy.id,
            on_behalf_of_user_id=owner.id,
            title="Rekrutacja zamknięta — daj znać 1 osobie",
            message="Osoba w toku",
            link=f"/jobs/{job_id}",
            notification_type=NotificationType.job_closed_people_waiting,
            is_read=True,
            quiet=True,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.add(row)
        await db.commit()
        return {
            "owner": await _login(app_client, owner.email, owner_pwd),
            "deputy": await _login(app_client, deputy.email, deputy_pwd),
            "third": await _login(app_client, third.email, third_pwd),
            "deputy_name": deputy.name,
            "owner_name": owner.name,
            "job_id": job_id,
            "row_id": row.id,
        }


def _thread(body: dict[str, Any], job_id: int) -> dict[str, Any]:
    return next(item for item in body["items"] if item["job_id"] == job_id)


async def test_deputy_sees_case_on_quiet_closure(app_client: AsyncClient, ctx):
    resp = await app_client.get("/api/notifications/jobs", headers=ctx["deputy"])
    assert resp.status_code == 200, resp.text
    thread = _thread(resp.json(), ctx["job_id"])
    assert thread["unread_count"] == 0
    assert thread["away_case"] == {
        "id": ctx["row_id"],
        "on_behalf_of_name": ctx["owner_name"],
        "handled_at": None,
        "handled_by_name": None,
    }


async def test_third_person_gets_404_and_changes_nothing(app_client, ctx):
    url = f"/api/notifications/while-away/{ctx['row_id']}/handled"
    resp = await app_client.post(url, headers=ctx["third"])
    assert resp.status_code == 404

    jobs = await app_client.get("/api/notifications/jobs", headers=ctx["deputy"])
    assert _thread(jobs.json(), ctx["job_id"])["away_case"]["handled_at"] is None
    third_jobs = await app_client.get("/api/notifications/jobs", headers=ctx["third"])
    assert all(item["job_id"] != ctx["job_id"] for item in third_jobs.json()["items"])


async def test_deputy_marks_handled_and_owner_sees_it(app_client, ctx):
    url = f"/api/notifications/while-away/{ctx['row_id']}/handled"
    resp = await app_client.post(url, headers=ctx["deputy"])
    assert resp.status_code == 204, resp.text

    jobs = await app_client.get("/api/notifications/jobs", headers=ctx["deputy"])
    case = _thread(jobs.json(), ctx["job_id"])["away_case"]
    assert case["handled_at"] is not None
    assert case["handled_by_name"] == ctx["deputy_name"]

    away = await app_client.get("/api/notifications/while-away", headers=ctx["owner"])
    assert away.status_code == 200, away.text
    (action,) = away.json()["actions"]
    assert action["id"] == ctx["row_id"]
    assert action["handled_by_name"] == ctx["deputy_name"]
