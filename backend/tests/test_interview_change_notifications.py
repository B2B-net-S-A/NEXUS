"""Rozmowa u klienta przełożona albo odwołana — powiadomienie pary (0500, 21.10.2026).

Do 21.10.2026 edycja wydarzenia powiadamiała parę tylko przy prepie;
Delivery Lead nie wiedział, że rekruter przełożył albo odwołał rozmowę
u klienta. Każdy test zakłada własne dane (shard ma wspólną bazę).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.calendar_event import CalendarEvent, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

BACKEND = Path(__file__).resolve().parents[1]


async def _user(db, role: UserRole) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    user = User(
        email=f"iv-change-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Iv {role.value} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, pwd


async def _pair(
    *, start: datetime, event_type: EventType = EventType.client_interview
) -> dict:
    """Rekruter (właściciel wydarzenia), DL rekrutacji i rozmowa u klienta."""
    async with AsyncSessionLocal() as db:
        recruiter, pwd = await _user(db, UserRole.recruiter)
        dl, _ = await _user(db, UserRole.delivery_lead)
        client = Client(name=f"IvChange {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Senior Java Developer",
            client_id=client.id,
            recruiter_id=recruiter.id,
            delivery_lead_id=dl.id,
            status=JobStatus.published,
        )
        candidate = Candidate(
            name="Jan", lastname="Kowalski", email=f"jk-{uuid.uuid4().hex[:8]}@x.com"
        )
        db.add_all([job, candidate])
        await db.flush()
        event = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=event_type,
            start_time=start,
            end_time=start + timedelta(hours=1),
            candidate_id=candidate.id,
            job_id=job.id,
            created_by=recruiter.id,
        )
        db.add(event)
        await db.commit()
        return {
            "recruiter_id": recruiter.id,
            "recruiter_email": recruiter.email,
            "recruiter_password": pwd,
            "dl_id": dl.id,
            "event_id": event.id,
            "start": start,
        }


async def _headers(client: AsyncClient, pair: dict) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login",
        json={"email": pair["recruiter_email"], "password": pair["recruiter_password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _changes(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.interview_changed,
                    )
                )
            ).all()
        )


def _future() -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        minute=0, second=0, microsecond=0
    )


async def test_moving_a_client_interview_tells_the_delivery_lead(
    app_client: AsyncClient,
) -> None:
    pair = await _pair(start=_future())
    new_start = pair["start"] + timedelta(hours=3)

    resp = await app_client.patch(
        f"/api/calendar/events/{pair['event_id']}",
        headers=await _headers(app_client, pair),
        json={
            "start_time": new_start.isoformat(),
            "end_time": (new_start + timedelta(hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text

    [notif] = await _changes(pair["dl_id"])
    assert notif.title.startswith("Rozmowa u klienta przełożona na ")
    assert "Jan Kowalski" in notif.message and "było" in notif.message
    assert notif.link.startswith("/calendar?cycle=")
    assert notif.is_read is False
    # Autor zmiany nic nie dostaje.
    assert await _changes(pair["recruiter_id"]) == []


async def test_cancelling_a_client_interview_tells_the_delivery_lead(
    app_client: AsyncClient,
) -> None:
    pair = await _pair(start=_future())

    resp = await app_client.post(
        f"/api/calendar/events/{pair['event_id']}/cancel",
        headers=await _headers(app_client, pair),
    )
    assert resp.status_code == 200, resp.text

    [notif] = await _changes(pair["dl_id"])
    assert notif.title == "Rozmowa u klienta odwołana"
    assert "odwołana przez" in notif.message


async def test_two_moves_on_one_day_both_reach_the_delivery_lead(
    app_client: AsyncClient,
) -> None:
    """Bez ID encji — dzienny dedup nie zjada drugiego przełożenia."""
    pair = await _pair(start=_future())
    headers = await _headers(app_client, pair)
    for hours in (2, 4):
        new_start = pair["start"] + timedelta(hours=hours)
        resp = await app_client.patch(
            f"/api/calendar/events/{pair['event_id']}",
            headers=headers,
            json={
                "start_time": new_start.isoformat(),
                "end_time": (new_start + timedelta(hours=1)).isoformat(),
            },
        )
        assert resp.status_code == 200, resp.text

    assert len(await _changes(pair["dl_id"])) == 2


async def test_past_interview_or_title_only_edit_or_other_event_sends_nothing(
    app_client: AsyncClient,
) -> None:
    past = await _pair(start=datetime.now(timezone.utc) - timedelta(days=2))
    moved = past["start"] + timedelta(hours=1)
    resp = await app_client.patch(
        f"/api/calendar/events/{past['event_id']}",
        headers=await _headers(app_client, past),
        json={
            "start_time": moved.isoformat(),
            "end_time": (moved + timedelta(hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    assert await _changes(past["dl_id"]) == []

    renamed = await _pair(start=_future())
    resp = await app_client.patch(
        f"/api/calendar/events/{renamed['event_id']}",
        headers=await _headers(app_client, renamed),
        json={"title": "Rozmowa u klienta — runda 2"},
    )
    assert resp.status_code == 200, resp.text
    assert await _changes(renamed["dl_id"]) == []

    meeting = await _pair(start=_future(), event_type=EventType.meeting)
    resp = await app_client.post(
        f"/api/calendar/events/{meeting['event_id']}/cancel",
        headers=await _headers(app_client, meeting),
    )
    assert resp.status_code == 200, resp.text
    assert await _changes(meeting["dl_id"]) == []


async def test_deleting_an_upcoming_client_interview_counts_as_cancelled(
    app_client: AsyncClient,
) -> None:
    pair = await _pair(start=_future())

    resp = await app_client.delete(
        f"/api/calendar/events/{pair['event_id']}",
        headers=await _headers(app_client, pair),
    )
    assert resp.status_code == 204, resp.text

    [notif] = await _changes(pair["dl_id"])
    assert notif.title == "Rozmowa u klienta odwołana"
    async with AsyncSessionLocal() as db:
        assert await db.get(CalendarEvent, pair["event_id"]) is None


def test_new_type_is_mirrored_in_entrypoint() -> None:
    migration = (
        BACKEND / "alembic/versions/0500_interview_changed_notification.py"
    ).read_text(encoding="utf-8")
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    statement = (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'interview_changed'"
    )
    assert statement in migration
    assert re.search(re.escape(f'"{statement}"'), entrypoint)
