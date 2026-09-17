"""Kontrakt wydarzenia kalendarza: walidacja i pola odpowiedzi (audyt 17.09.2026).

* Koniec przed początkiem przechodził przez `POST`/`PATCH` i dawał w siatce
  kafel o ujemnej wysokości — teraz 422 po polsku.
* `reminder_minutes` poza 0–1440 zapisywało obietnicę, której pętla
  przypomnień nie spełni.
* `needs_attention` i potwierdzenie kandydata były zapisywane, ale żadna
  odpowiedź ich nie niosła; `feedback_sources` pozwala oknu wydarzenia
  pokazać „Uzupełnij/Edytuj" bez zapytania per wydarzenie.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent
from app.models.interview_feedback import FeedbackSource, InterviewFeedback

_START = datetime(2039, 2, 7, 9, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def test_create_rejects_end_before_start(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    resp = await app_client.post(
        "/api/calendar/events",
        headers=app_auth_headers,
        json={
            "title": "Odwrócony czas",
            "start_time": _iso(_START),
            "end_time": _iso(_START - timedelta(minutes=30)),
        },
    )
    assert resp.status_code == 422, resp.text
    assert "Koniec wydarzenia musi być późniejszy" in resp.text


@pytest.mark.parametrize("minutes", [-1, 1441])
async def test_create_rejects_reminder_out_of_range(
    app_client: AsyncClient, app_auth_headers: dict, minutes: int
) -> None:
    resp = await app_client.post(
        "/api/calendar/events",
        headers=app_auth_headers,
        json={
            "title": "Przypomnienie",
            "start_time": _iso(_START),
            "reminder_minutes": minutes,
        },
    )
    assert resp.status_code == 422, resp.text
    assert "0–1440" in resp.text


async def test_patch_validates_against_the_stored_start(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    created = await app_client.post(
        "/api/calendar/events",
        headers=app_auth_headers,
        json={
            "title": "Do edycji",
            "start_time": _iso(_START),
            "end_time": _iso(_START + timedelta(hours=1)),
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=app_auth_headers,
        json={"end_time": _iso(_START - timedelta(hours=1))},
    )
    assert resp.status_code == 422, resp.text

    reminder = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=app_auth_headers,
        json={"reminder_minutes": 2000},
    )
    assert reminder.status_code == 422, reminder.text


async def test_response_carries_attention_confirmation_and_feedback_sources(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.models.candidate import Candidate, CandidateStatus

    created = await app_client.post(
        "/api/calendar/events",
        headers=app_auth_headers,
        json={
            "title": "Rozmowa z feedbackiem",
            "event_type": "interview",
            "start_time": _iso(_START),
            "end_time": _iso(_START + timedelta(hours=1)),
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["needs_attention"] is False
    assert body["feedback_sources"] == []
    assert body["external_source"] in (None, "manual")
    event_id = body["id"]

    confirmed_at = datetime(2039, 2, 6, 12, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Kontrakt",
            lastname="Odpowiedzi",
            email=f"kontrakt-{event_id}@example.com",
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.flush()
        event = await db.get(CalendarEvent, event_id)
        assert event is not None
        event.needs_attention = True
        event.candidate_confirmed_at = confirmed_at
        event.candidate_confirmation_source = "phone"
        db.add(
            InterviewFeedback(
                calendar_event_id=event_id,
                candidate_id=candidate.id,
                feedback_source=FeedbackSource.client_side,
            )
        )
        await db.commit()

    single = await app_client.get(
        f"/api/calendar/events/{event_id}", headers=app_auth_headers
    )
    assert single.status_code == 200, single.text
    got = single.json()
    assert got["needs_attention"] is True
    assert got["candidate_confirmation_source"] == "phone"
    assert got["candidate_confirmed_at"].startswith("2039-02-06")
    assert got["feedback_sources"] == ["client_side"]

    listed = await app_client.get(
        "/api/calendar/events",
        headers=app_auth_headers,
        params={
            "from_date": _iso(_START - timedelta(hours=1)),
            "to_date": _iso(_START + timedelta(hours=1)),
        },
    )
    assert listed.status_code == 200, listed.text
    row = next(r for r in listed.json() if r["id"] == event_id)
    assert row["feedback_sources"] == ["client_side"]
    assert row["needs_attention"] is True


async def test_invite_rejects_reminder_out_of_range(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    resp = await app_client.post(
        "/api/calendar/events/m365-invite",
        headers=app_auth_headers,
        json={
            "candidate_id": 1,
            "title": "x",
            "start": _iso(_START),
            "end": _iso(_START + timedelta(hours=1)),
            "reminder_minutes": 9999,
        },
    )
    assert resp.status_code == 422, resp.text
