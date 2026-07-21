"""P1-CALENDAR-01 — resource-level access policy for calendar events.

Before this policy the calendar was gated by *role* only: any operational user
could LIST every event, GET any event by id, and PATCH/DELETE anyone else's
event, leaking attendee emails / descriptions / candidate references / meeting
links across the whole org.

These tests pin the resource rule:

* LIST is SQL-scoped to events the caller owns or attends (admin/HoR see all).
* GET of an event the caller has no relationship with → 404 (anti-enumeration;
  existence is not revealed), identical to a non-existent id.
* PATCH/DELETE by a non-owner participant → 403; by a stranger → 404.
* A non-owner participant sees a redacted projection (other attendees' emails
  and the description are hidden).
* admin / head_of_recruitment reach any event, and their mutations are audited.

Uses the in-process ``app_client`` + ``app_auth_headers`` fixtures (admin).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

# Far-future fixed window so seeded events sit in a predictable slice.
_BASE = datetime(2029, 3, 5, 9, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def _me_id(client: AsyncClient, headers: dict) -> int:
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


async def _seed_user(role: UserRole, tag: str) -> tuple[int, str, str]:
    """Create a fresh user with ``role``; return (id, email, plaintext_pw)."""
    suffix = uuid.uuid4().hex[:8]
    email = f"cal-{tag}-{suffix}@example.com"
    password = f"C4lTest_{suffix}!Pw"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"{tag} {suffix}",
            role=role,
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


async def _seed_event(
    *,
    owner_id: int,
    attendees: list | None = None,
    title: str = "Private event",
    description: str | None = "internal secret notes",
) -> int:
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title=title,
            description=description,
            event_type=EventType.interview,
            start_time=_BASE,
            end_time=_BASE + timedelta(hours=1),
            attendees=attendees or [],
            created_by=owner_id,
            status=EventStatus.scheduled,
        )
        db.add(ev)
        await db.commit()
        await db.refresh(ev)
        return ev.id


async def _audit_rows(event_id: int, action: str) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        return (
            (
                await db.execute(
                    select(Activity).where(
                        Activity.entity_type == "calendar_event",
                        Activity.entity_id == event_id,
                        Activity.action == action,
                    )
                )
            )
            .scalars()
            .all()
        )


# ── LIST scoping ──────────────────────────────────────────────────────────────


async def test_list_scopes_to_owned_and_attended(
    app_client: AsyncClient, app_auth_headers: dict
):
    a_id, a_email, a_pw = await _seed_user(UserRole.recruiter, "owner")
    b_id, b_email, b_pw = await _seed_user(UserRole.recruiter, "stranger")
    p_id, p_email, p_pw = await _seed_user(UserRole.recruiter, "participant")

    a_event = await _seed_event(owner_id=a_id, attendees=[p_email], title="A owns")
    b_event = await _seed_event(owner_id=b_id, attendees=[], title="B owns")

    a_headers = await _login(app_client, a_email, a_pw)
    b_headers = await _login(app_client, b_email, b_pw)
    p_headers = await _login(app_client, p_email, p_pw)

    params = {
        "from_date": _iso(_BASE - timedelta(hours=1)),
        "to_date": _iso(_BASE + timedelta(hours=2)),
    }

    a_list = await app_client.get(
        "/api/calendar/events", params=params, headers=a_headers
    )
    assert a_list.status_code == 200, a_list.text
    a_ids = {e["id"] for e in a_list.json()}
    assert a_event in a_ids and b_event not in a_ids

    b_list = await app_client.get(
        "/api/calendar/events", params=params, headers=b_headers
    )
    assert b_list.status_code == 200
    b_ids = {e["id"] for e in b_list.json()}
    assert b_event in b_ids and a_event not in b_ids

    # Participant P sees A's event (they are an attendee).
    p_list = await app_client.get(
        "/api/calendar/events", params=params, headers=p_headers
    )
    assert p_list.status_code == 200
    p_ids = {e["id"] for e in p_list.json()}
    assert a_event in p_ids and b_event not in p_ids


async def test_admin_lists_all(app_client: AsyncClient, app_auth_headers: dict):
    a_id, *_ = await _seed_user(UserRole.recruiter, "owner")
    a_event = await _seed_event(owner_id=a_id, title="A owns")
    r = await app_client.get(
        "/api/calendar/events",
        params={
            "from_date": _iso(_BASE - timedelta(hours=1)),
            "to_date": _iso(_BASE + timedelta(hours=2)),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    assert a_event in {e["id"] for e in r.json()}


# ── GET anti-enumeration ──────────────────────────────────────────────────────


async def test_get_foreign_event_is_404_like_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    a_id, *_ = await _seed_user(UserRole.recruiter, "owner")
    _b_id, b_email, b_pw = await _seed_user(UserRole.recruiter, "stranger")
    a_event = await _seed_event(owner_id=a_id)

    b_headers = await _login(app_client, b_email, b_pw)

    foreign = await app_client.get(f"/api/calendar/events/{a_event}", headers=b_headers)
    missing = await app_client.get("/api/calendar/events/99999999", headers=b_headers)
    # A real-but-forbidden id and a non-existent id are indistinguishable.
    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json()["detail"] == missing.json()["detail"]


# ── PATCH / DELETE gating ─────────────────────────────────────────────────────


async def test_stranger_cannot_mutate_foreign_event(
    app_client: AsyncClient, app_auth_headers: dict
):
    a_id, *_ = await _seed_user(UserRole.recruiter, "owner")
    _b_id, b_email, b_pw = await _seed_user(UserRole.recruiter, "stranger")
    a_event = await _seed_event(owner_id=a_id)
    b_headers = await _login(app_client, b_email, b_pw)

    patch = await app_client.patch(
        f"/api/calendar/events/{a_event}",
        json={"title": "hijacked"},
        headers=b_headers,
    )
    delete = await app_client.delete(
        f"/api/calendar/events/{a_event}", headers=b_headers
    )
    assert patch.status_code == 404
    assert delete.status_code == 404

    # Event untouched.
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, a_event)
        assert ev is not None and ev.title == "Private event"


async def test_participant_cannot_mutate_but_can_view(
    app_client: AsyncClient, app_auth_headers: dict
):
    a_id, *_ = await _seed_user(UserRole.recruiter, "owner")
    _p_id, p_email, p_pw = await _seed_user(UserRole.recruiter, "participant")
    a_event = await _seed_event(owner_id=a_id, attendees=[p_email])
    p_headers = await _login(app_client, p_email, p_pw)

    # Can view.
    got = await app_client.get(f"/api/calendar/events/{a_event}", headers=p_headers)
    assert got.status_code == 200
    # Cannot mutate → 403 (they legitimately know it exists).
    patch = await app_client.patch(
        f"/api/calendar/events/{a_event}",
        json={"title": "nope"},
        headers=p_headers,
    )
    delete = await app_client.delete(
        f"/api/calendar/events/{a_event}", headers=p_headers
    )
    assert patch.status_code == 403
    assert delete.status_code == 403


# ── Participant projection ────────────────────────────────────────────────────


async def test_participant_projection_redacts_others(
    app_client: AsyncClient, app_auth_headers: dict
):
    a_id, *_ = await _seed_user(UserRole.recruiter, "owner")
    _p_id, p_email, p_pw = await _seed_user(UserRole.recruiter, "participant")
    other = "someone-else@example.com"
    a_event = await _seed_event(
        owner_id=a_id,
        attendees=[p_email, other],
        description="internal salary note",
    )
    p_headers = await _login(app_client, p_email, p_pw)

    r = await app_client.get(f"/api/calendar/events/{a_event}", headers=p_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Description (internal notes) redacted for a non-owner participant.
    assert body["description"] is None
    # Only the requester's own attendee entry is exposed; the other is hidden.
    assert body["attendees"] == [p_email]


async def test_participant_projection_dict_attendee_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    """M365 stores attendees as ``[{"address": email}]`` — still gated + shaped."""
    a_id, *_ = await _seed_user(UserRole.recruiter, "owner")
    _p_id, p_email, p_pw = await _seed_user(UserRole.recruiter, "participant")
    a_event = await _seed_event(
        owner_id=a_id,
        attendees=[{"address": p_email}, {"address": "other@example.com"}],
    )
    p_headers = await _login(app_client, p_email, p_pw)

    r = await app_client.get(f"/api/calendar/events/{a_event}", headers=p_headers)
    assert r.status_code == 200, r.text
    assert r.json()["attendees"] == [{"address": p_email}]


async def test_owner_sees_full_event(app_client: AsyncClient, app_auth_headers: dict):
    a_id, a_email, a_pw = await _seed_user(UserRole.recruiter, "owner")
    other = "colleague@example.com"
    a_event = await _seed_event(
        owner_id=a_id, attendees=[a_email, other], description="my private notes"
    )
    a_headers = await _login(app_client, a_email, a_pw)

    r = await app_client.get(f"/api/calendar/events/{a_event}", headers=a_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "my private notes"
    assert set(body["attendees"]) == {a_email, other}


# ── Owner mutation still works ────────────────────────────────────────────────


async def test_owner_can_patch_and_delete_own(
    app_client: AsyncClient, app_auth_headers: dict
):
    a_id, a_email, a_pw = await _seed_user(UserRole.recruiter, "owner")
    a_event = await _seed_event(owner_id=a_id)
    a_headers = await _login(app_client, a_email, a_pw)

    patch = await app_client.patch(
        f"/api/calendar/events/{a_event}",
        json={"title": "renamed by owner"},
        headers=a_headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["title"] == "renamed by owner"

    delete = await app_client.delete(
        f"/api/calendar/events/{a_event}", headers=a_headers
    )
    assert delete.status_code == 204


# ── Admin / HoR override + audit ──────────────────────────────────────────────


async def test_admin_override_access_and_audited(
    app_client: AsyncClient, app_auth_headers: dict
):
    admin_id = await _me_id(app_client, app_auth_headers)
    a_id, *_ = await _seed_user(UserRole.recruiter, "owner")
    a_event = await _seed_event(owner_id=a_id)

    # Admin can view someone else's event.
    got = await app_client.get(
        f"/api/calendar/events/{a_event}", headers=app_auth_headers
    )
    assert got.status_code == 200

    # Admin mutation succeeds and is audited with override=True.
    patch = await app_client.patch(
        f"/api/calendar/events/{a_event}",
        json={"title": "admin touched"},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200, patch.text

    rows = await _audit_rows(a_event, "calendar_event_updated")
    assert len(rows) == 1
    assert rows[0].user_id == admin_id
    assert rows[0].details.get("override") is True


async def test_head_of_recruitment_override(
    app_client: AsyncClient, app_auth_headers: dict
):
    a_id, *_ = await _seed_user(UserRole.recruiter, "owner")
    _h_id, h_email, h_pw = await _seed_user(UserRole.head_of_recruitment, "hor")
    a_event = await _seed_event(owner_id=a_id)
    h_headers = await _login(app_client, h_email, h_pw)

    got = await app_client.get(f"/api/calendar/events/{a_event}", headers=h_headers)
    assert got.status_code == 200

    listed = await app_client.get(
        "/api/calendar/events",
        params={
            "from_date": _iso(_BASE - timedelta(hours=1)),
            "to_date": _iso(_BASE + timedelta(hours=2)),
        },
        headers=h_headers,
    )
    assert listed.status_code == 200
    assert a_event in {e["id"] for e in listed.json()}


async def test_owner_delete_is_audited(app_client: AsyncClient, app_auth_headers: dict):
    a_id, a_email, a_pw = await _seed_user(UserRole.recruiter, "owner")
    a_event = await _seed_event(owner_id=a_id)
    a_headers = await _login(app_client, a_email, a_pw)

    delete = await app_client.delete(
        f"/api/calendar/events/{a_event}", headers=a_headers
    )
    assert delete.status_code == 204

    rows = await _audit_rows(a_event, "calendar_event_deleted")
    assert len(rows) == 1
    assert rows[0].user_id == a_id
    assert rows[0].details.get("override") is False
