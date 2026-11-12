"""Jedna rozmowa u klienta w dwóch rekrutacjach — jeden debrief (12.11.2026).

Zgłoszenie z 12.11.2026: kandydatka była w dwóch rekrutacjach tego samego
klienta (dwa requesty na Scrum Mastera) i miała JEDNĄ rozmowę u klienta,
wpisaną w obu: raz przy ruchu karty, raz przy zapisie pytań. Rekruterka
zapisała debrief w jednej rekrutacji, a kalendarz dalej pokazywał w drugiej
„Telefon po rozmowie · po terminie 167 h” z „Zapisz debrief”. Przepisywanie
tego samego debriefu to zbędna robota.

Ten sam kandydat, ten sam klient i ta sama godzina rozmowy to jedno
spotkanie: debrief zapisany pod którymkolwiek wpisem zamyka rundę wszędzie
(bramka ruchu, kroki i zadania ekranu „Rozmowy u klienta”).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.user import UserRole
from app.services.debrief_gate import missing_debrief
from tests.test_interview_cycle import _user


async def _client_with_two_jobs(*, recruiter_id: int, dl_id: int):
    """Klient, dwie jego rekrutacje i kandydatka w etapie rozmowy w obu."""
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"SharedClient-{tag}")
        other = Client(name=f"OtherClient-{tag}")
        db.add_all([client, other])
        await db.flush()
        jobs = [
            Job(
                title=f"SharedJob-{tag}-{n}",
                status=JobStatus.published,
                client_id=cid,
                recruiter_id=recruiter_id,
                delivery_lead_id=dl_id,
            )
            for n, cid in enumerate((client.id, client.id, other.id))
        ]
        cand = Candidate(
            name="Maria",
            lastname=f"Wspolna-{tag}",
            email=f"shared-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([*jobs, cand])
        await db.flush()
        db.add_all(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.client_interview,
                moved_by=recruiter_id,
            )
            for job in jobs
        )
        await db.commit()
        return cand.id, client.id, other.id, [job.id for job in jobs]


async def _interview(
    *, cand_id: int, job_id: int, client_id: int, start: datetime, owner_id: int
) -> int:
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.client_interview,
            start_time=start,
            end_time=start + timedelta(hours=1),
            status=EventStatus.completed,
            created_by=owner_id,
            operational_owner_id=owner_id,
            candidate_id=cand_id,
            job_id=job_id,
            client_id=client_id,
            attendees=[],
        )
        db.add(ev)
        await db.commit()
        return ev.id


async def _debrief(*, event_id: int, cand_id: int, job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            InterviewFeedback(
                calendar_event_id=event_id,
                candidate_id=cand_id,
                job_id=job_id,
                feedback_source=FeedbackSource.candidate_side,
                overall_impression=5,
                client_questions="Jak prowadzi Pani PI Planning?",
            )
        )
        await db.commit()


async def _gate(cand_id: int, job_id: int):
    async with AsyncSessionLocal() as db:
        return await missing_debrief(db, candidate_id=cand_id, job_id=job_id)


async def _setup():
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, _ = await _user(UserRole.delivery_lead)
    cand_id, client_id, other_id, jobs = await _client_with_two_jobs(
        recruiter_id=rec_id, dl_id=dl_id
    )
    start = (datetime.now(timezone.utc) - timedelta(days=7)).replace(
        second=0, microsecond=0
    )
    return rec_id, rec_h, cand_id, client_id, other_id, jobs, start


async def test_debrief_in_one_job_closes_the_same_meeting_in_the_other(
    app_client: AsyncClient,
):
    rec_id, rec_h, cand_id, client_id, _, jobs, start = await _setup()
    job_a, job_b, _ = jobs
    # Wpis z ruchu karty w A, wpis z zapisu pytań w B — ta sama godzina.
    await _interview(
        cand_id=cand_id, job_id=job_a, client_id=client_id, start=start, owner_id=rec_id
    )
    event_b = await _interview(
        cand_id=cand_id, job_id=job_b, client_id=client_id, start=start, owner_id=rec_id
    )
    assert await _gate(cand_id, job_a) is not None  # przed debriefem: bramka stoi

    await _debrief(event_id=event_b, cand_id=cand_id, job_id=job_b)

    assert await _gate(cand_id, job_b) is None
    assert await _gate(cand_id, job_a) is None

    overview = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    assert overview.status_code == 200, overview.text
    body = overview.json()
    item_a = next(
        i
        for i in body["items"]
        if i["candidate_id"] == cand_id and i["job_id"] == job_a
    )
    states = {s["key"]: s["state"] for s in item_a["steps"]}
    assert states["debrief"] == "done"
    assert item_a["debrief"] is not None
    assert not [
        t
        for t in body["todos"]
        if t["candidate_id"] == cand_id and t["kind"] in ("call_now", "debrief_overdue")
    ]


async def test_other_hour_or_other_client_is_a_separate_meeting():
    rec_id, _, cand_id, client_id, other_id, jobs, start = await _setup()
    job_a, job_b, job_other = jobs
    event_b = await _interview(
        cand_id=cand_id, job_id=job_b, client_id=client_id, start=start, owner_id=rec_id
    )
    # Ten sam klient, inna godzina — druga rozmowa, osobny debrief.
    later = await _interview(
        cand_id=cand_id,
        job_id=job_a,
        client_id=client_id,
        start=start + timedelta(hours=2),
        owner_id=rec_id,
    )
    # Ta sama godzina, inny klient — też nie to samo spotkanie.
    other = await _interview(
        cand_id=cand_id,
        job_id=job_other,
        client_id=other_id,
        start=start,
        owner_id=rec_id,
    )
    await _debrief(event_id=event_b, cand_id=cand_id, job_id=job_b)

    detail_a = await _gate(cand_id, job_a)
    assert detail_a is not None and detail_a["event_id"] == later
    detail_other = await _gate(cand_id, job_other)
    assert detail_other is not None and detail_other["event_id"] == other


async def test_cancelled_twin_entry_does_not_close_the_round():
    rec_id, _, cand_id, client_id, _, jobs, start = await _setup()
    job_a, job_b, _ = jobs
    await _interview(
        cand_id=cand_id, job_id=job_a, client_id=client_id, start=start, owner_id=rec_id
    )
    event_b = await _interview(
        cand_id=cand_id, job_id=job_b, client_id=client_id, start=start, owner_id=rec_id
    )
    await _debrief(event_id=event_b, cand_id=cand_id, job_id=job_b)
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, event_b)
        ev.status = EventStatus.cancelled
        await db.commit()

    assert await _gate(cand_id, job_a) is not None
