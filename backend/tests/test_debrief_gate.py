"""Bramka „telefon po rozmowie u klienta” (pipeline v4, 23.09.2026).

Po rozmowie u klienta rekruter dzwoni do kandydata i zapisuje, o co pytał
klient. Karta nie idzie dalej, dopóki debrief NAJNOWSZEJ odbytej rozmowy nie
ma pytań albo jawnego „klient nie zadawał pytań”. Te testy pilnują:

* ``missing_debrief`` — kiedy bramka dotyczy pary, a kiedy nie (brak rozmowy,
  rozmowa przyszła, odwołana, debrief z pytaniami / z „nie pytał”);
* ``PUT …/debrief`` — pusta lista pytań bez potwierdzenia to 422;
* ``GET …/client-questions?client_id=`` — pula pytań klienta dla nowej
  rekrutacji, z tą samą granicą dostępu co rekrutacje klienta.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.user import User, UserRole
from app.services.debrief_gate import (
    DEBRIEF_REQUIRED_CODE,
    debrief_is_complete,
    missing_debrief,
)


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"gate-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"Ga7e_{tag}!pw"),
            name=f"Gate {role.value} {tag}",
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


async def _pair(*, recruiter_id: int | None = None) -> tuple[int, int, int]:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"GateClient-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"GateJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter_id,
        )
        cand = Candidate(
            name="Ewa",
            lastname=f"Bramka-{tag}",
            email=f"gate-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.commit()
        return job.id, cand.id, client.id


async def _event(
    *,
    cand_id: int,
    job_id: int,
    client_id: int,
    start: datetime,
    status: EventStatus = EventStatus.completed,
    owner_id: int | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.client_interview,
            start_time=start,
            end_time=start + timedelta(hours=1),
            status=status,
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


async def _feedback(
    *,
    event_id: int,
    cand_id: int,
    job_id: int,
    questions: str | None = None,
    no_questions: bool = False,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            InterviewFeedback(
                calendar_event_id=event_id,
                candidate_id=cand_id,
                job_id=job_id,
                feedback_source=FeedbackSource.candidate_side,
                overall_impression=5,
                client_questions=questions,
                no_client_questions=no_questions,
            )
        )
        await db.commit()


async def _gate(cand_id: int, job_id: int, now: datetime | None = None):
    async with AsyncSessionLocal() as db:
        return await missing_debrief(db, candidate_id=cand_id, job_id=job_id, now=now)


# ── Czysta reguła ───────────────────────────────────────────────────────────


def test_debrief_is_complete_rule():
    assert debrief_is_complete("Kafka?", False)
    assert debrief_is_complete(None, True)
    assert not debrief_is_complete(None, False)
    assert not debrief_is_complete(" \n  \n", False)


# ── missing_debrief ─────────────────────────────────────────────────────────


async def test_pair_without_client_interview_is_not_gated():
    job_id, cand_id, _ = await _pair()
    assert await _gate(cand_id, job_id) is None


async def test_future_interview_is_not_gated_yet():
    job_id, cand_id, client_id = await _pair()
    await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=datetime.now(timezone.utc) + timedelta(days=2),
        status=EventStatus.scheduled,
    )
    assert await _gate(cand_id, job_id) is None


async def test_cancelled_interview_is_not_gated():
    job_id, cand_id, client_id = await _pair()
    await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=datetime.now(timezone.utc) - timedelta(hours=3),
        status=EventStatus.cancelled,
    )
    assert await _gate(cand_id, job_id) is None


async def test_past_interview_without_debrief_is_gated():
    job_id, cand_id, client_id = await _pair()
    start = datetime.now(timezone.utc) - timedelta(hours=3)
    event_id = await _event(
        cand_id=cand_id, job_id=job_id, client_id=client_id, start=start
    )
    detail = await _gate(cand_id, job_id)
    assert detail is not None
    assert detail["code"] == DEBRIEF_REQUIRED_CODE == "DEBRIEF_REQUIRED"
    assert detail["event_id"] == event_id
    assert detail["candidate_id"] == cand_id
    assert detail["job_id"] == job_id
    assert detail["message"].startswith("Najpierw zadzwoń do kandydata")
    assert datetime.fromisoformat(detail["event_start"]) == start


async def test_debrief_without_questions_or_confirmation_still_gates():
    # Debrief zapisany przed bramką (pusta lista, bez „nie pytał”) nie wystarcza.
    job_id, cand_id, client_id = await _pair()
    event_id = await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    await _feedback(event_id=event_id, cand_id=cand_id, job_id=job_id)
    detail = await _gate(cand_id, job_id)
    assert detail is not None and detail["event_id"] == event_id


async def test_debrief_with_questions_opens_the_gate():
    job_id, cand_id, client_id = await _pair()
    event_id = await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    await _feedback(
        event_id=event_id, cand_id=cand_id, job_id=job_id, questions="Kafka?"
    )
    assert await _gate(cand_id, job_id) is None


async def test_debrief_with_no_client_questions_opens_the_gate():
    job_id, cand_id, client_id = await _pair()
    event_id = await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    await _feedback(
        event_id=event_id, cand_id=cand_id, job_id=job_id, no_questions=True
    )
    assert await _gate(cand_id, job_id) is None


async def test_only_latest_past_interview_counts():
    # Runda 1 ma debrief, runda 2 (późniejsza, już odbyta) — nie: bramka
    # pyta o rundę 2. Runda 3 w przyszłości nie jest jeszcze brana pod uwagę.
    job_id, cand_id, client_id = await _pair()
    now = datetime.now(timezone.utc)
    first = await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=now - timedelta(days=5),
    )
    await _feedback(event_id=first, cand_id=cand_id, job_id=job_id, questions="Q1")
    second = await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=now - timedelta(hours=2),
    )
    await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=now + timedelta(days=3),
        status=EventStatus.scheduled,
    )
    detail = await _gate(cand_id, job_id)
    assert detail is not None and detail["event_id"] == second
    # Ten sam stan widziany „przed” rundą 2 — debrief rundy 1 wystarcza.
    assert await _gate(cand_id, job_id, now=now - timedelta(days=1)) is None


# ── PUT debrief ─────────────────────────────────────────────────────────────


async def test_empty_debrief_needs_explicit_no_questions(app_client: AsyncClient):
    rec_id, rec_h = await _user(UserRole.recruiter)
    job_id, cand_id, client_id = await _pair(recruiter_id=rec_id)
    event_id = await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=datetime.now(timezone.utc) - timedelta(hours=2),
        owner_id=rec_id,
    )
    url = f"/api/interview-cycle/events/{event_id}/debrief"
    base = {"outcome": "medium", "offer_acceptance": "unknown", "questions": ["  "]}

    refused = await app_client.put(url, headers=rec_h, json=base)
    assert refused.status_code == 422, refused.text
    assert (
        "Wpisz pytania klienta albo zaznacz, że klient ich nie zadawał." in refused.text
    )
    assert "Value error" not in refused.text
    assert await _gate(cand_id, job_id) is not None

    saved = await app_client.put(
        url, headers=rec_h, json={**base, "no_client_questions": True}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["no_client_questions"] is True
    assert saved.json()["questions"] == []
    assert await _gate(cand_id, job_id) is None

    fetched = await app_client.get(url, headers=rec_h)
    assert fetched.json()["no_client_questions"] is True

    # Pytania wygrywają ze sprzecznym „nie pytał”.
    both = await app_client.put(
        url,
        headers=rec_h,
        json={**base, "questions": ["Jak testujesz?"], "no_client_questions": True},
    )
    assert both.status_code == 200, both.text
    assert both.json()["no_client_questions"] is False
    assert both.json()["questions"] == ["Jak testujesz?"]
    assert await _gate(cand_id, job_id) is None


# ── GET client-questions?client_id= ─────────────────────────────────────────


async def test_client_questions_by_client_for_team_and_oversight(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    outsider_id, outsider_h = await _user(UserRole.recruiter)
    _, admin_h = await _user(UserRole.admin)
    job_id, cand_id, client_id = await _pair(recruiter_id=rec_id)
    event_id = await _event(
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        start=datetime.now(timezone.utc) - timedelta(hours=2),
        owner_id=rec_id,
    )
    saved = await app_client.put(
        f"/api/interview-cycle/events/{event_id}/debrief",
        headers=rec_h,
        json={
            "outcome": "good",
            "offer_acceptance": "yes",
            "questions": ["Jak skalujesz Kafkę?"],
        },
    )
    assert saved.status_code == 200, saved.text

    url = f"/api/interview-cycle/client-questions?client_id={client_id}"
    mine = await app_client.get(url, headers=rec_h)
    assert mine.status_code == 200, mine.text
    assert [q["text"] for q in mine.json()] == ["Jak skalujesz Kafkę?"]

    admin = await app_client.get(url, headers=admin_h)
    assert admin.status_code == 200, admin.text
    assert [q["text"] for q in admin.json()] == ["Jak skalujesz Kafkę?"]

    # Rekruter spoza rekrutacji tego klienta nie czyta jego puli pytań.
    other = await app_client.get(url, headers=outsider_h)
    assert other.status_code == 403, other.text

    both = await app_client.get(
        f"/api/interview-cycle/client-questions?client_id={client_id}&job_id={job_id}",
        headers=rec_h,
    )
    assert both.status_code == 422
    neither = await app_client.get(
        "/api/interview-cycle/client-questions", headers=rec_h
    )
    assert neither.status_code == 422


async def test_client_questions_for_client_without_jobs_is_empty(
    app_client: AsyncClient,
):
    from app.models.client import Client

    _, rec_h = await _user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"GateEmpty-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        client_id = client.id
    resp = await app_client.get(
        f"/api/interview-cycle/client-questions?client_id={client_id}", headers=rec_h
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_column_is_mirrored_in_migration_and_entrypoint():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    migration = (root / "alembic/versions/0352_pipeline_v4.py").read_text()
    entrypoint = (root / "entrypoint.sh").read_text()
    needle = "no_client_questions BOOLEAN NOT NULL DEFAULT false"
    assert needle in migration
    assert needle in entrypoint
