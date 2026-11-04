"""„Zespół” w „Moich ludziach” (25.10.2026) — czyja lista leży, dla HoR i admina.

``GET /api/my-people/team`` liczy każdą osobę zespołu tymi samymi definicjami
co jej dymek, ``GET /api/my-people/team/{user_id}`` pokazuje jej listę do
podglądu. Baza testowa jest wspólna — każdy test zakłada własne osoby
(zmyślone) i asertuje tylko po nich.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.my_people import IDLE_DAYS, MyPeople, PersonRow

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

T0 = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


def _person(cid: int, **kw) -> PersonRow:
    return PersonRow(candidate_id=cid, full_name=f"Osoba {cid}", **kw)


def test_idle_means_active_without_process_and_waiting_past_the_threshold() -> None:
    people = MyPeople(
        rows=[
            _person(1, days_since_last_send=IDLE_DAYS + 20),
            _person(2, days_since_last_send=IDLE_DAYS + 1),
            _person(3, days_since_last_send=IDLE_DAYS),  # równo próg — jeszcze nie
            _person(4, days_since_last_send=IDLE_DAYS + 5, active_processes=1),
            _person(5, days_since_last_send=IDLE_DAYS + 5, working=True),
            _person(6, days_since_last_send=IDLE_DAYS + 5, snoozed=True),
            _person(7, days_since_last_send=None),
        ]
    )
    # Najkrócej czekający najpierw.
    assert [r.candidate_id for r in people.idle] == [2, 1]


async def _user(db, role: str):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"team-{role}-{marker}@example.com",
        name=f"Zespół {role} {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _headers(user_id: int, role: str) -> dict[str, str]:
    from app.core.security import create_access_token

    return {
        "Authorization": f"Bearer {create_access_token(subject=user_id, role=role)}"
    }


async def _recruiter_with_idle_person(db):
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.my_people import MyPeopleJobMatch
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    recruiter = await _user(db, "recruiter")
    marker = uuid.uuid4().hex[:10]
    client = Client(name=f"team-client-{marker}")
    db.add(client)
    await db.flush()
    # Zamknięta rekrutacja = brak procesu w toku, więc osoba „czeka”.
    job = Job(title=f"Java {marker}", client_id=client.id, status=JobStatus.closed)
    open_job = Job(
        title=f"Go {marker}", client_id=client.id, status=JobStatus.published
    )
    cand = Candidate(name="Ola", lastname=f"Team{marker}")
    db.add_all([job, open_job, cand])
    await db.flush()
    for stage, at in (("verified", T0), ("cv_sent", T0 + timedelta(days=1))):
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage(stage),
                moved_by=recruiter.id,
                moved_at=at,
            )
        )
    db.add(
        MyPeopleJobMatch(
            user_id=recruiter.id, job_id=open_job.id, candidate_id=cand.id, score=80
        )
    )
    await db.flush()
    return recruiter, cand


@needs_db
@pytest.mark.asyncio
async def test_head_of_recruitment_sees_each_members_list_numbers(app_client) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        lead = await _user(db, "head_of_recruitment")
        recruiter, cand = await _recruiter_with_idle_person(db)
        finance = await _user(db, "finance")
        await db.commit()
        lead_id, rec_id, cand_id, fin_id = lead.id, recruiter.id, cand.id, finance.id

    headers = _headers(lead_id, "head_of_recruitment")
    resp = await app_client.get("/api/my-people/team", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["idle_days"] == IDLE_DAYS
    members = {m["user_id"]: m for m in body["members"]}
    assert members[rec_id]["total"] == 1
    assert members[rec_id]["idle"] == 1
    assert members[rec_id]["new_matches"] == 1
    assert members[rec_id]["roles"] == ["recruiter"]
    # Finanse nie budują listy — nie ma ich w zespole.
    assert fin_id not in members

    one = await app_client.get(f"/api/my-people/team/{rec_id}", headers=headers)
    assert one.status_code == 200, one.text
    assert [r["candidate_id"] for r in one.json()["rows"]] == [cand_id]

    outside = await app_client.get(f"/api/my-people/team/{fin_id}", headers=headers)
    assert outside.status_code == 404


@needs_db
@pytest.mark.asyncio
async def test_recruiter_cannot_open_the_team_view(app_client) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        recruiter, _ = await _recruiter_with_idle_person(db)
        other = await _user(db, "recruiter")
        await db.commit()
        rec_id, other_id = recruiter.id, other.id

    headers = _headers(other_id, "recruiter")
    assert (
        await app_client.get("/api/my-people/team", headers=headers)
    ).status_code == 403
    assert (
        await app_client.get(f"/api/my-people/team/{rec_id}", headers=headers)
    ).status_code == 403


@needs_db
@pytest.mark.asyncio
async def test_team_counts_match_each_members_own_list() -> None:
    """Zbiorcze liczniki = te same liczby co pełna lista osoby (26.10.2026)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.my_people import MyPeopleOverride
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.my_people import load_my_people, team_counts

    async with AsyncSessionLocal() as db:
        recruiter, idle_cand = await _recruiter_with_idle_person(db)
        other = await _user(db, "recruiter")
        marker = uuid.uuid4().hex[:8]
        client = Client(name=f"team-counts-{marker}")
        db.add(client)
        await db.flush()
        open_job = Job(
            title=f"Rust {marker}", client_id=client.id, status=JobStatus.published
        )
        in_process = Candidate(name="Ola", lastname=f"Proc{marker}")
        snoozed = Candidate(name="Ola", lastname=f"Snooze{marker}")
        pinned = Candidate(name="Ola", lastname=f"Pin{marker}")
        db.add_all([open_job, in_process, snoozed, pinned])
        await db.flush()
        # W toku w opublikowanej rekrutacji — na liście, ale nie „czeka”.
        for cand in (in_process, snoozed):
            for stage, at in (("verified", T0), ("cv_sent", T0 + timedelta(days=2))):
                db.add(
                    CandidateStage(
                        candidate_id=cand.id,
                        job_id=open_job.id,
                        stage=PipelineStage(stage),
                        moved_by=recruiter.id,
                        moved_at=at,
                    )
                )
        db.add_all(
            [
                MyPeopleOverride(
                    user_id=recruiter.id,
                    candidate_id=snoozed.id,
                    kind="snoozed",
                    reason="other",
                ),
                MyPeopleOverride(
                    user_id=recruiter.id, candidate_id=pinned.id, kind="pinned"
                ),
            ]
        )
        await db.commit()
        rec_id, other_id = recruiter.id, other.id

    async with AsyncSessionLocal() as db:
        counts = await team_counts(db, [rec_id, other_id])
        people = await load_my_people(db, rec_id)

    mine = counts[rec_id]
    assert mine.total == len(people.active) == 3  # czekająca, w procesie, przypięta
    assert mine.idle == len(people.idle) == 1
    assert mine.working == 0
    assert mine.new_matches == 1 and mine.jobs_with_matches == 1
    assert counts[other_id].total == 0
