"""Odwołanie wydarzenia z Outlooka (audyt 17.09.2026, kalendarz P1).

„Usuń" na wydarzeniu z Outlooka kasowało sam wiersz: spotkanie w Outlooku
zostawało bez odwołania, a najbliższa synchronizacja odtwarzała wpis.
Teraz:

* `POST /calendar/events/{id}/cancel` odwołuje w Outlooku (organizator) albo
  zdejmuje wpis z kalendarza twórcy (nie-organizator), a lokalnie zostawia
  wiersz ze statusem `cancelled`;
* awaria Grapha (5xx/429) = 502 i ZERO zmian lokalnie;
* brak aktywnego połączenia M365 twórcy = odwołanie tylko w NEXUSIE,
  `outlook="skipped"` (decyzja: miękkie odwołanie z komunikatem);
* `DELETE` na wydarzeniu z Outlooka = 409.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.activity import Activity
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.m365 import M365Connection
from app.models.user import User, UserRole
from app.services.m365 import calendar as m365_calendar
from app.services.m365.graph_client import GraphRequestError

_START = datetime(2038, 5, 4, 10, 0, tzinfo=timezone.utc)


async def _seed_owner(
    *, with_connection: bool, active: bool = True
) -> tuple[int, dict]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"cancel-{tag}@example.com",
            password_hash=hash_password(f"C4ncel_{tag}!pw"),
            name=f"Cancel {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if with_connection:
            db.add(
                M365Connection(
                    user_id=user.id,
                    tenant_id="test-tenant",
                    mailbox_upn=f"cancel-{tag}@example.com",
                    access_token_ct="ct-access",
                    refresh_token_ct="ct-refresh",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    is_active=active,
                )
            )
        await db.commit()
        headers = {
            "Authorization": f"Bearer {create_access_token(user.id, 'recruiter', roles=['recruiter'])}"
        }
        return user.id, headers


async def _seed_event(owner_id: int, *, outlook: bool = True) -> int:
    async with AsyncSessionLocal() as db:
        event = CalendarEvent(
            title="Rozmowa z Outlooka",
            event_type=EventType.interview,
            start_time=_START,
            end_time=_START + timedelta(hours=1),
            status=EventStatus.scheduled,
            created_by=owner_id,
            external_source="microsoft365" if outlook else "manual",
            external_id=f"graph-{uuid.uuid4().hex}" if outlook else None,
        )
        db.add(event)
        await db.commit()
        return event.id


async def _status(event_id: int) -> EventStatus:
    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event is not None
        return event.status


def _fake_cancel(result: Any):
    calls: list[str] = []

    async def fake(db, conn, graph_id, **_kw):
        calls.append(graph_id)
        if isinstance(result, Exception):
            raise result
        return result

    return fake, calls


@pytest.mark.parametrize("outcome", ["cancelled", "deleted", "gone"])
async def test_cancel_outlook_event_marks_cancelled_and_audits(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, outcome: str
) -> None:
    owner_id, _ = await _seed_owner(with_connection=True)
    event_id = await _seed_event(owner_id)
    fake, calls = _fake_cancel(outcome)
    monkeypatch.setattr(m365_calendar, "cancel_graph_event", fake)

    resp = await app_client.post(
        f"/api/calendar/events/{event_id}/cancel", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outlook"] == outcome
    assert body["event"]["status"] == "cancelled"
    assert len(calls) == 1
    assert await _status(event_id) == EventStatus.cancelled

    async with AsyncSessionLocal() as db:
        audit = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "calendar_event",
                    Activity.entity_id == event_id,
                    Activity.action == "calendar_event_cancelled",
                )
            )
        ).all()
    assert len(audit) == 1
    assert audit[0].details["outlook"] == outcome

    # Idempotencja: drugi raz nie woła Grapha i nie zmienia niczego.
    again = await app_client.post(
        f"/api/calendar/events/{event_id}/cancel", headers=app_auth_headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["outlook"] == "already_cancelled"
    assert len(calls) == 1


@pytest.mark.parametrize("status", [500, 503, 429])
async def test_graph_failure_is_502_without_local_change(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, status: int
) -> None:
    owner_id, _ = await _seed_owner(with_connection=True)
    event_id = await _seed_event(owner_id)
    fake, _ = _fake_cancel(GraphRequestError(status, "boom"))
    monkeypatch.setattr(m365_calendar, "cancel_graph_event", fake)

    resp = await app_client.post(
        f"/api/calendar/events/{event_id}/cancel", headers=app_auth_headers
    )
    assert resp.status_code == 502, resp.text
    assert "nic nie zostało zmienione" in resp.json()["detail"]
    assert await _status(event_id) == EventStatus.scheduled


@pytest.mark.parametrize("connection", ["missing", "inactive"])
async def test_without_active_connection_cancels_locally(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, connection: str
) -> None:
    owner_id, _ = await _seed_owner(
        with_connection=connection == "inactive", active=False
    )
    event_id = await _seed_event(owner_id)
    fake, calls = _fake_cancel("cancelled")
    monkeypatch.setattr(m365_calendar, "cancel_graph_event", fake)

    resp = await app_client.post(
        f"/api/calendar/events/{event_id}/cancel", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outlook"] == "skipped"
    assert calls == []
    assert await _status(event_id) == EventStatus.cancelled


async def test_manual_event_cancel_does_not_touch_graph(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    owner_id, _ = await _seed_owner(with_connection=True)
    event_id = await _seed_event(owner_id, outlook=False)
    fake, calls = _fake_cancel("cancelled")
    monkeypatch.setattr(m365_calendar, "cancel_graph_event", fake)

    resp = await app_client.post(
        f"/api/calendar/events/{event_id}/cancel", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outlook"] == "not_applicable"
    assert calls == []


async def test_delete_of_outlook_event_is_409(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    owner_id, _ = await _seed_owner(with_connection=True)
    event_id = await _seed_event(owner_id)

    resp = await app_client.delete(
        f"/api/calendar/events/{event_id}", headers=app_auth_headers
    )
    assert resp.status_code == 409, resp.text
    assert "Odwołaj" in resp.json()["detail"]
    assert await _status(event_id) == EventStatus.scheduled


async def test_participant_cannot_cancel_and_stranger_gets_404(
    app_client: AsyncClient,
) -> None:
    owner_id, _ = await _seed_owner(with_connection=False)
    event_id = await _seed_event(owner_id, outlook=False)
    _, stranger_headers = await _seed_owner(with_connection=False)

    resp = await app_client.post(
        f"/api/calendar/events/{event_id}/cancel", headers=stranger_headers
    )
    assert resp.status_code == 404, resp.text


async def test_outlook_owned_fields_cannot_be_patched_locally(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    owner_id, _ = await _seed_owner(with_connection=False)
    event_id = await _seed_event(owner_id)

    moved = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=app_auth_headers,
        json={"start_time": (_START + timedelta(hours=2)).isoformat()},
    )
    assert moved.status_code == 409, moved.text

    status_cancel = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=app_auth_headers,
        json={"status": "cancelled"},
    )
    assert status_cancel.status_code == 409, status_cancel.text

    metadata = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=app_auth_headers,
        json={"event_type": "screening", "reminder_minutes": 30},
    )
    assert metadata.status_code == 200, metadata.text
    assert metadata.json()["event_type"] == "screening"
    assert metadata.json()["reminder_minutes"] == 30
    assert metadata.json()["external_source"] == "microsoft365"


# ── `cancel_graph_event` — kolejność kroków po stronie Grapha ────────────────


class _FakeGraph:
    def __init__(self, post_error: int | None, delete_error: int | None) -> None:
        self.post_error = post_error
        self.delete_error = delete_error
        self.calls: list[tuple[str, str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, url, json=None, *, expect_json=True):
        self.calls.append(("POST", url, expect_json))
        if self.post_error:
            raise GraphRequestError(self.post_error, "x")
        return b""

    async def delete(self, url):
        self.calls.append(("DELETE", url, None))
        if self.delete_error:
            raise GraphRequestError(self.delete_error, "x")


@pytest.mark.parametrize(
    ("post_error", "delete_error", "expected", "methods"),
    [
        (None, None, "cancelled", ["POST"]),
        (403, None, "deleted", ["POST", "DELETE"]),
        (400, None, "deleted", ["POST", "DELETE"]),
        (404, None, "gone", ["POST"]),
        (403, 404, "gone", ["POST", "DELETE"]),
    ],
)
async def test_cancel_graph_event_steps(
    monkeypatch, post_error, delete_error, expected, methods
) -> None:
    fake = _FakeGraph(post_error, delete_error)
    monkeypatch.setattr(m365_calendar, "GraphClient", lambda conn, db: fake)

    outcome = await m365_calendar.cancel_graph_event(None, object(), "abc")
    assert outcome == expected
    assert [c[0] for c in fake.calls] == methods
    assert fake.calls[0] == ("POST", "/me/events/abc/cancel", False)


async def test_cancel_graph_event_reraises_server_errors(monkeypatch) -> None:
    fake = _FakeGraph(503, None)
    monkeypatch.setattr(m365_calendar, "GraphClient", lambda conn, db: fake)
    with pytest.raises(GraphRequestError):
        await m365_calendar.cancel_graph_event(None, object(), "abc")


async def test_head_of_recruitment_edits_foreign_event_but_cannot_cancel_or_delete(
    app_client: AsyncClient,
) -> None:
    """Decyzja 17.09.2026: HoR poprawia metadane cudzego wydarzenia, ale
    odwołać / usunąć (także statusem przez PATCH) może tylko właściciel
    albo admin — odwołanie z Outlooka idzie kalendarzem twórcy."""
    owner_id, _ = await _seed_owner(with_connection=False)
    manual_id = await _seed_event(owner_id, outlook=False)
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        hor = User(
            email=f"cancel-hor-{tag}@example.com",
            password_hash=hash_password(f"C4ncel_{tag}!pw"),
            name=f"HoR {tag}",
            role=UserRole.head_of_recruitment,
            roles=["head_of_recruitment"],
            is_active=True,
            profile_completed=True,
        )
        db.add(hor)
        await db.commit()
        hor_headers = {
            "Authorization": "Bearer "
            + create_access_token(
                hor.id, "head_of_recruitment", roles=["head_of_recruitment"]
            )
        }

    detail = await app_client.get(
        f"/api/calendar/events/{manual_id}", headers=hor_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_remove"] is False

    edit = await app_client.patch(
        f"/api/calendar/events/{manual_id}",
        headers=hor_headers,
        json={"reminder_minutes": 30},
    )
    assert edit.status_code == 200, edit.text

    for method, path, body in (
        ("POST", f"/api/calendar/events/{manual_id}/cancel", None),
        ("DELETE", f"/api/calendar/events/{manual_id}", None),
        ("PATCH", f"/api/calendar/events/{manual_id}", {"status": "cancelled"}),
    ):
        resp = await app_client.request(method, path, headers=hor_headers, json=body)
        assert resp.status_code == 403, (method, path, resp.text)
    assert await _status(manual_id) == EventStatus.scheduled
