"""Spotkania przy zamknięciu karty (zgłoszenie 09.11.2026).

Kto zamknął kartę, ten odwołuje jej prepy i rozmowy, także prep założony
w kalendarzu Delivery Leada. Inna osoba i karta otwarta dostają odmowę.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.notification import Notification
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services.m365 import teams_prep_graph
from app.services.m365.graph_client import GraphRequestError
from tests.test_prep_meetings_flow import FakeGraph, _at, _create, _pair, _user, graph  # noqa: F401

pytestmark = pytest.mark.asyncio


def _soon(hours: int = 24) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


async def _event(
    job_id: int | None,
    candidate_id: int,
    event_type: EventType,
    owner: int | None,
    start: datetime,
    title: str = "Spotkanie",
    status: EventStatus = EventStatus.scheduled,
) -> int:
    async with AsyncSessionLocal() as db:
        event = CalendarEvent(
            title=title,
            event_type=event_type,
            status=status,
            start_time=start,
            end_time=start + timedelta(hours=1),
            candidate_id=candidate_id,
            job_id=job_id,
            created_by=owner,
            operational_owner_id=owner,
        )
        db.add(event)
        await db.commit()
        return event.id


async def _close_card(job_id: int, candidate_id: int, user: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                job_id=job_id,
                candidate_id=candidate_id,
                stage=PipelineStage.rejected,
                moved_by=user,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _status(event_id: int) -> EventStatus:
    async with AsyncSessionLocal() as db:
        return (await db.get(CalendarEvent, event_id)).status


def _url(job_id: int, candidate_id: int, suffix: str = "") -> str:
    return f"/api/interview-cycle/pairs/{job_id}/{candidate_id}/meetings{suffix}"


async def test_list_shows_upcoming_and_hides_outlook_twin(app_client: AsyncClient):
    rec, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    job, cand = await _pair(recruiter_id=rec, dl_id=dl)
    start = _soon()
    interview = await _event(job, cand, EventType.client_interview, rec, start)
    await _event(None, cand, EventType.meeting, None, start, title="Kopia")
    outlook = await _event(
        None, cand, EventType.meeting, dl, _soon(30), title="Z Outlooka"
    )
    await _event(job, cand, EventType.prep_call, dl, _soon(-5))
    await _event(
        job, cand, EventType.prep_call, dl, _soon(), status=EventStatus.cancelled
    )

    response = await app_client.get(_url(job, cand), headers=rec_h)

    assert response.status_code == 200
    rows = response.json()
    assert [(r["event_id"], r["kind"], r["cancellable"]) for r in rows] == [
        (interview, "client_interview", True),
        (outlook, "outlook", False),
    ]


async def test_person_who_closed_the_card_cancels_someone_elses_meeting(
    app_client: AsyncClient,
):
    rec, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    job, cand = await _pair(recruiter_id=rec, dl_id=dl)
    interview = await _event(job, cand, EventType.client_interview, dl, _soon())
    await _close_card(job, cand, rec)

    response = await app_client.post(
        _url(job, cand, "/close"),
        headers=rec_h,
        json={"cancel_event_ids": [interview]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"cancelled": [interview], "asked": [], "failed": []}
    assert await _status(interview) == EventStatus.cancelled


async def test_open_card_is_refused(app_client: AsyncClient):
    rec, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    job, cand = await _pair(recruiter_id=rec, dl_id=dl)
    interview = await _event(job, cand, EventType.client_interview, rec, _soon())

    response = await app_client.post(
        _url(job, cand, "/close"),
        headers=rec_h,
        json={"cancel_event_ids": [interview]},
    )

    assert response.status_code == 409
    assert await _status(interview) == EventStatus.scheduled


async def test_someone_who_did_not_close_the_card_is_refused(app_client: AsyncClient):
    rec, _ = await _user(UserRole.recruiter, "Ola Rekruter")
    other, other_h = await _user(UserRole.recruiter, "Ela Inna")
    dl, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    job, cand = await _pair(recruiter_id=rec, dl_id=dl)
    interview = await _event(job, cand, EventType.client_interview, rec, _soon())
    await _close_card(job, cand, rec)

    response = await app_client.post(
        _url(job, cand, "/close"),
        headers=other_h,
        json={"cancel_event_ids": [interview]},
    )

    assert response.status_code == 403
    assert await _status(interview) == EventStatus.scheduled


async def test_event_of_another_pair_is_ignored(app_client: AsyncClient):
    rec, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    job, cand = await _pair(recruiter_id=rec, dl_id=dl)
    other_job, other_cand = await _pair(recruiter_id=rec, dl_id=dl)
    foreign = await _event(
        other_job, other_cand, EventType.client_interview, dl, _soon()
    )
    await _close_card(job, cand, rec)

    response = await app_client.post(
        _url(job, cand, "/close"), headers=rec_h, json={"cancel_event_ids": [foreign]}
    )

    assert response.status_code == 200
    assert response.json()["cancelled"] == []
    assert await _status(foreign) == EventStatus.scheduled


async def test_outlook_invite_cannot_be_cancelled_only_asked_for(
    app_client: AsyncClient,
):
    rec, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    job, cand = await _pair(recruiter_id=rec, dl_id=dl)
    invite = await _event(
        None, cand, EventType.meeting, dl, _soon(), title="Z Outlooka"
    )
    await _close_card(job, cand, rec)

    refused = await app_client.post(
        _url(job, cand, "/close"), headers=rec_h, json={"cancel_event_ids": [invite]}
    )
    assert refused.json()["cancelled"] == []
    assert await _status(invite) == EventStatus.scheduled

    asked = await app_client.post(
        _url(job, cand, "/close"), headers=rec_h, json={"ask_event_ids": [invite]}
    )

    assert asked.json()["asked"] == [invite]
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(select(Notification).where(Notification.user_id == dl))
        ).all()
    assert any(n.related_entity_id == invite for n in rows)


async def _prep_of_dl(client, dl: int, dl_h, rec: int, job: int, cand: int) -> int:
    response = await _create(
        client,
        dl_h,
        candidate_id=cand,
        job_id=job,
        prep_no=1,
        organizer_user_id=dl,
        start=_at(24),
        end=_at(24.75),
        attendee_user_ids=[rec],
        client_request_id=f"pair-{job}",
    )
    assert response.status_code == 201, response.text
    return response.json()["event_id"]


async def test_prep_in_the_dl_calendar_is_cancelled_by_the_recruiter(
    app_client: AsyncClient,
    graph: FakeGraph,
    monkeypatch,  # noqa: F811
):
    calls: list[str] = []

    async def cancel_event(upn, graph_event_id, comment):
        calls.append(upn)
        return "cancelled"

    monkeypatch.setattr(teams_prep_graph, "cancel_event", cancel_event)
    rec, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl, dl_h = await _user(UserRole.delivery_lead, "Kasia Lead")
    job, cand = await _pair(recruiter_id=rec, dl_id=dl)
    prep = await _prep_of_dl(app_client, dl, dl_h, rec, job, cand)
    await _close_card(job, cand, rec)

    response = await app_client.post(
        _url(job, cand, "/close"), headers=rec_h, json={"cancel_event_ids": [prep]}
    )

    assert response.json()["cancelled"] == [prep]
    assert calls and calls[0].startswith("prep-delivery_lead-")
    assert await _status(prep) == EventStatus.cancelled


async def test_outlook_refusal_is_reported_and_other_meetings_still_go(
    app_client: AsyncClient,
    graph: FakeGraph,
    monkeypatch,  # noqa: F811
):
    async def cancel_event(upn, graph_event_id, comment):
        raise GraphRequestError(403, "refused")

    monkeypatch.setattr(teams_prep_graph, "cancel_event", cancel_event)
    rec, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl, dl_h = await _user(UserRole.delivery_lead, "Kasia Lead")
    job, cand = await _pair(recruiter_id=rec, dl_id=dl)
    prep = await _prep_of_dl(app_client, dl, dl_h, rec, job, cand)
    interview = await _event(job, cand, EventType.client_interview, rec, _soon(30))
    await _close_card(job, cand, rec)

    response = await app_client.post(
        _url(job, cand, "/close"),
        headers=rec_h,
        json={"cancel_event_ids": [prep, interview]},
    )

    body = response.json()
    assert body["cancelled"] == [interview]
    assert [row["event_id"] for row in body["failed"]] == [prep]
    assert await _status(prep) == EventStatus.scheduled
