"""Phase 5.4 — calendar conflict detection tests.

Covers:
* `GET /api/calendar/conflicts` — overlap query for the booking modal.
* `GET /api/calendar/conflicts-summary` — bulk overlap map for the grid view.

Uses the in-process `app_client` + `app_auth_headers` fixtures (admin user).
Events are created either via `POST /api/calendar/events` (auto-assigns
`created_by`) or directly through the ORM when we need a different owner.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _me_id(client: AsyncClient, headers: dict) -> int:
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def _create_event(
    client: AsyncClient,
    headers: dict,
    *,
    title: str,
    start: datetime,
    end: datetime | None,
    event_type: str = "interview",
) -> int:
    payload: dict = {
        "title": title,
        "event_type": event_type,
        "start_time": _iso(start),
    }
    if end is not None:
        payload["end_time"] = _iso(end)
    r = await client.post("/api/calendar/events", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


async def _set_status(event_id: int, status: EventStatus) -> None:
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, event_id)
        assert ev is not None
        ev.status = status
        await db.commit()


async def _seed_recruiter() -> tuple[int, str, str]:
    """Create a fresh recruiter user; return (id, email, plaintext_password)."""
    suffix = uuid.uuid4().hex[:8]
    email = f"calendar-recruiter-{suffix}@example.com"
    password = f"R3cTest_{suffix}!Pw"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Recruiter {suffix}",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# Fixed window so test events can't accidentally collide with other suites.
_BASE = datetime(2027, 6, 14, 9, 0, tzinfo=timezone.utc)


# ── /api/calendar/conflicts ──────────────────────────────────────────────────


async def test_no_overlap_returns_empty(
    app_client: AsyncClient, app_auth_headers: dict
):
    await _create_event(
        app_client,
        app_auth_headers,
        title="Existing morning slot",
        start=_BASE,
        end=_BASE + timedelta(hours=1),
    )
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE + timedelta(hours=4)),
            "end": _iso(_BASE + timedelta(hours=5)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conflicts"] == []


async def test_partial_overlap(app_client: AsyncClient, app_auth_headers: dict):
    ev_id = await _create_event(
        app_client,
        app_auth_headers,
        title="Interview A",
        start=_BASE,
        end=_BASE + timedelta(hours=1),
    )
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE + timedelta(minutes=30)),
            "end": _iso(_BASE + timedelta(minutes=90)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    ids = [c["id"] for c in r.json()["conflicts"]]
    assert ids == [ev_id]


async def test_two_overlaps_returned_in_start_order(
    app_client: AsyncClient, app_auth_headers: dict
):
    later_id = await _create_event(
        app_client,
        app_auth_headers,
        title="Interview B",
        start=_BASE + timedelta(minutes=30),
        end=_BASE + timedelta(hours=2),
    )
    earlier_id = await _create_event(
        app_client,
        app_auth_headers,
        title="Interview A",
        start=_BASE,
        end=_BASE + timedelta(hours=1),
    )
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE + timedelta(minutes=15)),
            "end": _iso(_BASE + timedelta(hours=3)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["conflicts"]]
    assert ids == [earlier_id, later_id]


async def test_cancelled_event_is_excluded(
    app_client: AsyncClient, app_auth_headers: dict
):
    ev_id = await _create_event(
        app_client,
        app_auth_headers,
        title="Was going to happen",
        start=_BASE,
        end=_BASE + timedelta(hours=1),
    )
    await _set_status(ev_id, EventStatus.cancelled)
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE + timedelta(minutes=15)),
            "end": _iso(_BASE + timedelta(minutes=45)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["conflicts"] == []


async def test_exclude_event_id_skips_self(
    app_client: AsyncClient, app_auth_headers: dict
):
    ev_id = await _create_event(
        app_client,
        app_auth_headers,
        title="Editing this one",
        start=_BASE,
        end=_BASE + timedelta(hours=1),
    )
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE),
            "end": _iso(_BASE + timedelta(hours=1)),
            "exclude_event_id": ev_id,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["conflicts"] == []


async def test_end_time_null_assumes_one_hour(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Events without an explicit end_time are treated as 1h long."""
    ev_id = await _create_event(
        app_client,
        app_auth_headers,
        title="Open-ended",
        start=_BASE,
        end=None,
    )
    # Window 30-90min after start → must overlap (event runs to BASE+60min).
    overlapping = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE + timedelta(minutes=30)),
            "end": _iso(_BASE + timedelta(minutes=90)),
        },
        headers=app_auth_headers,
    )
    assert overlapping.status_code == 200
    assert [c["id"] for c in overlapping.json()["conflicts"]] == [ev_id]

    # Window starting 90min after BASE → no overlap.
    after = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE + timedelta(minutes=90)),
            "end": _iso(_BASE + timedelta(minutes=120)),
        },
        headers=app_auth_headers,
    )
    assert after.status_code == 200
    assert after.json()["conflicts"] == []


async def test_invalid_window_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE + timedelta(hours=2)),
            "end": _iso(_BASE + timedelta(hours=1)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422


async def test_window_over_seven_days_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE),
            "end": _iso(_BASE + timedelta(days=8)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422


async def test_user_scoping_isolates_recruiters(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Recruiter A's events must not appear in recruiter B's conflict view."""
    admin_id = await _me_id(app_client, app_auth_headers)
    recruiter_id, recruiter_email, recruiter_pw = await _seed_recruiter()

    # Admin creates a busy slot on their own calendar.
    await _create_event(
        app_client,
        app_auth_headers,
        title="Admin's interview",
        start=_BASE,
        end=_BASE + timedelta(hours=1),
    )

    recruiter_headers = await _login(app_client, recruiter_email, recruiter_pw)
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE),
            "end": _iso(_BASE + timedelta(hours=1)),
        },
        headers=recruiter_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == recruiter_id
    assert body["conflicts"] == []

    # Recruiter cannot peek at the admin's calendar via user_id override.
    forbidden = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE),
            "end": _iso(_BASE + timedelta(hours=1)),
            "user_id": admin_id,
        },
        headers=recruiter_headers,
    )
    assert forbidden.status_code == 403


async def test_admin_can_query_other_user(
    app_client: AsyncClient, app_auth_headers: dict
):
    recruiter_id, _, _ = await _seed_recruiter()

    # Insert event directly for recruiter (POST would assign created_by=admin).
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="Recruiter slot",
            event_type=EventType.interview,
            start_time=_BASE,
            end_time=_BASE + timedelta(hours=1),
            created_by=recruiter_id,
            status=EventStatus.scheduled,
        )
        db.add(ev)
        await db.commit()
        ev_id = ev.id

    r = await app_client.get(
        "/api/calendar/conflicts",
        params={
            "start": _iso(_BASE),
            "end": _iso(_BASE + timedelta(hours=1)),
            "user_id": recruiter_id,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == recruiter_id
    assert [c["id"] for c in body["conflicts"]] == [ev_id]


# ── /api/calendar/conflicts-summary ──────────────────────────────────────────


async def test_summary_pairs_three_overlapping(
    app_client: AsyncClient, app_auth_headers: dict
):
    a = await _create_event(
        app_client,
        app_auth_headers,
        title="A 9-10",
        start=_BASE,
        end=_BASE + timedelta(hours=1),
    )
    b = await _create_event(
        app_client,
        app_auth_headers,
        title="B 9:30-10:30",
        start=_BASE + timedelta(minutes=30),
        end=_BASE + timedelta(minutes=90),
    )
    c = await _create_event(
        app_client,
        app_auth_headers,
        title="C 11-12 (no overlap)",
        start=_BASE + timedelta(hours=2),
        end=_BASE + timedelta(hours=3),
    )
    r = await app_client.get(
        "/api/calendar/conflicts-summary",
        params={
            "start": _iso(_BASE - timedelta(hours=1)),
            "end": _iso(_BASE + timedelta(hours=4)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    pairs = r.json()["pairs"]
    # JSON object keys are strings.
    assert sorted(pairs[str(a)]) == [b]
    assert sorted(pairs[str(b)]) == [a]
    assert pairs[str(c)] == []


async def test_summary_excludes_cancelled(
    app_client: AsyncClient, app_auth_headers: dict
):
    a = await _create_event(
        app_client,
        app_auth_headers,
        title="A",
        start=_BASE,
        end=_BASE + timedelta(hours=1),
    )
    b = await _create_event(
        app_client,
        app_auth_headers,
        title="B (cancelled)",
        start=_BASE + timedelta(minutes=30),
        end=_BASE + timedelta(minutes=90),
    )
    await _set_status(b, EventStatus.cancelled)

    r = await app_client.get(
        "/api/calendar/conflicts-summary",
        params={
            "start": _iso(_BASE),
            "end": _iso(_BASE + timedelta(hours=2)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    pairs = r.json()["pairs"]
    assert pairs[str(a)] == []
    assert str(b) not in pairs


# ── Auth ─────────────────────────────────────────────────────────────────────


async def test_conflicts_requires_auth(app_client: AsyncClient):
    r = await app_client.get(
        "/api/calendar/conflicts",
        params={"start": _iso(_BASE), "end": _iso(_BASE + timedelta(hours=1))},
    )
    assert r.status_code in (401, 403)
