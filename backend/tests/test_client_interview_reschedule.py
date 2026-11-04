"""„Zmień termin” rozmowy u klienta z panelu osoby (zgłoszenie 04.11.2026).

Klient przełożył rozmowę na przyszły tydzień: prep dało się przełożyć z panelu,
rozmowy nie. Edycję wydarzenia miał tylko właściciel, więc Delivery Lead
rekrutacji nie mógł poprawić terminu. Każdy test zakłada własne dane.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.client_interview_slot_request import (
    SLOT_STATUS_CONFIRMED,
    ClientInterviewSlotRequest,
)
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"iv-move-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"Iv_m0ve_{tag}!"),
            name=f"Iv move {role.value} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    token = create_access_token(uid, role.value, roles=[role.value])
    return uid, {"Authorization": f"Bearer {token}"}


def _in_days(days: int) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        minute=0, second=0, microsecond=0
    )


async def _interview(
    *,
    start: datetime | None = None,
    external_source: str | None = None,
    external_id: str | None = None,
) -> dict:
    """Rekruter jest właścicielem rozmowy, DL prowadzi rekrutację."""
    recruiter_id, recruiter_headers = await _user(UserRole.recruiter)
    dl_id, dl_headers = await _user(UserRole.delivery_lead)
    start = start or _in_days(1)
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"IvMove-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"IvMove-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter_id,
            delivery_lead_id=dl_id,
        )
        candidate = Candidate(
            name="Ola",
            lastname=f"Przeklad-{tag}",
            email=f"iv-move-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.client_interview,
                moved_by=recruiter_id,
                moved_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        event = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.client_interview,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            candidate_id=candidate.id,
            job_id=job.id,
            client_id=client.id,
            created_by=recruiter_id,
            operational_owner_id=recruiter_id,
            external_source=external_source,
            external_id=external_id,
        )
        db.add(event)
        await db.commit()
        return {
            "recruiter_id": recruiter_id,
            "recruiter_headers": recruiter_headers,
            "dl_id": dl_id,
            "dl_headers": dl_headers,
            "event_id": event.id,
            "candidate_id": candidate.id,
            "job_id": job.id,
            "client_id": client.id,
            "start": start,
        }


async def _reschedule(client: AsyncClient, pair: dict, headers: dict[str, str], **body):
    return await client.post(
        f"/api/interview-cycle/events/{pair['event_id']}/reschedule",
        headers=headers,
        json=body,
    )


async def _event(event_id: int) -> CalendarEvent:
    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event is not None
        return event


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


async def test_delivery_lead_moves_an_interview_owned_by_the_recruiter(
    app_client: AsyncClient,
) -> None:
    pair = await _interview()
    new_start = _in_days(7)

    res = await _reschedule(
        app_client, pair, pair["dl_headers"], start=new_start.isoformat()
    )

    assert res.status_code == 200, res.text
    event = await _event(pair["event_id"])
    # To samo wydarzenie: debrief, telefon i prepy zostają przy tej rundzie.
    assert event.start_time == new_start
    assert event.status == EventStatus.scheduled
    # Bez podanej długości zostaje ta, którą rozmowa miała.
    assert event.end_time == new_start + timedelta(minutes=30)
    [notif] = await _changes(pair["recruiter_id"])
    assert notif.title.startswith("Rozmowa u klienta przełożona na ")
    assert await _changes(pair["dl_id"]) == []


async def test_recruiter_of_the_pair_moves_and_sets_the_length(
    app_client: AsyncClient,
) -> None:
    pair = await _interview()
    new_start = _in_days(5)

    res = await _reschedule(
        app_client,
        pair,
        pair["recruiter_headers"],
        start=new_start.isoformat(),
        duration_minutes=90,
    )

    assert res.status_code == 200, res.text
    assert res.json()["event_id"] == pair["event_id"]
    event = await _event(pair["event_id"])
    assert event.end_time == new_start + timedelta(minutes=90)
    assert len(await _changes(pair["dl_id"])) == 1


async def test_recruiter_outside_the_recruitment_cannot_move(
    app_client: AsyncClient,
) -> None:
    pair = await _interview()
    _, outsider = await _user(UserRole.recruiter)

    res = await _reschedule(app_client, pair, outsider, start=_in_days(7).isoformat())

    assert res.status_code == 403, res.text
    assert (await _event(pair["event_id"])).start_time == pair["start"]


async def test_interview_that_started_cannot_be_moved(
    app_client: AsyncClient,
) -> None:
    pair = await _interview(start=datetime.now(timezone.utc) - timedelta(minutes=5))

    res = await _reschedule(
        app_client, pair, pair["dl_headers"], start=_in_days(7).isoformat()
    )

    assert res.status_code == 409, res.text
    assert "zaczęła" in res.json()["detail"]


async def test_cancelled_interview_cannot_be_moved(app_client: AsyncClient) -> None:
    pair = await _interview()
    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, pair["event_id"])
        event.status = EventStatus.cancelled
        await db.commit()

    res = await _reschedule(
        app_client, pair, pair["dl_headers"], start=_in_days(7).isoformat()
    )

    assert res.status_code == 409, res.text


async def test_new_term_in_the_past_is_refused(app_client: AsyncClient) -> None:
    pair = await _interview()

    res = await _reschedule(
        app_client,
        pair,
        pair["dl_headers"],
        start=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )

    assert res.status_code == 422, res.text
    assert (await _event(pair["event_id"])).start_time == pair["start"]


async def test_other_persons_outlook_meeting_stays_with_its_organizer(
    app_client: AsyncClient,
) -> None:
    """Spotkanie z uczestnikami: zmiana poszłaby do ludzi spoza firmy cudzym
    kalendarzem — ta sama granica co przy przełożeniu z wniosku o terminy."""
    pair = await _interview(
        external_source="microsoft365", external_id=uuid.uuid4().hex
    )

    res = await _reschedule(
        app_client, pair, pair["dl_headers"], start=_in_days(7).isoformat()
    )

    assert res.status_code == 409, res.text
    assert "Outlook" in res.json()["detail"]
    assert (await _event(pair["event_id"])).start_time == pair["start"]


async def _pending_reply(pair: dict) -> int:
    async with AsyncSessionLocal() as db:
        req = ClientInterviewSlotRequest(
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            client_id=pair["client_id"],
            created_by=pair["dl_id"],
            recruiter_id=pair["recruiter_id"],
            slots=[
                {
                    "start": pair["start"].isoformat(),
                    "end": (pair["start"] + timedelta(minutes=30)).isoformat(),
                }
            ],
            duration_minutes=30,
            status=SLOT_STATUS_CONFIRMED,
            chosen_index=0,
            event_id=pair["event_id"],
            client_reply_pending=True,
        )
        db.add(req)
        await db.commit()
        return req.id


async def _reply_pending(request_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        req = await db.get(ClientInterviewSlotRequest, request_id)
        assert req is not None
        return req.client_reply_pending


async def test_moving_drops_the_reply_with_the_old_term(
    app_client: AsyncClient,
) -> None:
    """„Odpisz klientowi” podsuwało gotowy tekst ze starym terminem."""
    pair = await _interview()
    request_id = await _pending_reply(pair)

    res = await _reschedule(
        app_client, pair, pair["dl_headers"], start=_in_days(7).isoformat()
    )

    assert res.status_code == 200, res.text
    assert await _reply_pending(request_id) is False


async def test_moving_in_the_week_view_drops_the_reply_too(
    app_client: AsyncClient,
) -> None:
    pair = await _interview()
    request_id = await _pending_reply(pair)
    new_start = _in_days(7)

    res = await app_client.patch(
        f"/api/calendar/events/{pair['event_id']}",
        headers=pair["recruiter_headers"],
        json={
            "start_time": new_start.isoformat(),
            "end_time": (new_start + timedelta(minutes=30)).isoformat(),
        },
    )

    assert res.status_code == 200, res.text
    assert await _reply_pending(request_id) is False


async def test_screen_offers_the_button_only_to_people_of_the_pair(
    app_client: AsyncClient,
) -> None:
    pair = await _interview()
    _, outsider = await _user(UserRole.recruiter)
    url = f"/api/interview-cycle/events/{pair['event_id']}"

    for headers, expected in (
        (pair["dl_headers"], True),
        (pair["recruiter_headers"], True),
        (outsider, False),
    ):
        res = await app_client.get(url, headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["can_reschedule"] is expected


async def test_details_are_offered_only_to_those_who_can_open_the_event(
    app_client: AsyncClient,
) -> None:
    """DL dostawał na „Szczegółach” błąd, bo wydarzenie widzi tylko właściciel."""
    pair = await _interview()
    url = f"/api/interview-cycle/events/{pair['event_id']}"

    as_dl = await app_client.get(url, headers=pair["dl_headers"])
    as_owner = await app_client.get(url, headers=pair["recruiter_headers"])

    assert as_dl.json()["can_open_details"] is False
    assert as_owner.json()["can_open_details"] is True
