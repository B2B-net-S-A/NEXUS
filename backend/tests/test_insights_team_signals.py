"""Widok Zespół w /insights (24.09.2026): ludzie, „Do uwagi", rekrutacje bez ruchu.

Pod ochroną:

1. Porównanie z poprzednim okresem idzie po TYM SAMYM odcinku — 24 dni
   września przeciw całemu sierpniowi dałyby fałszywy spadek.
2. Rekrutacja bez ruchu = opublikowana i bez etapu od 14 dni; bez etapów liczy
   się od otwarcia. Zamknięta nie jest „bez ruchu".
3. Trasy widoku wymagają ``VIEW_TEAM_KPI`` — rekruter dostaje 403, nie cudze
   wyniki.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.analytics.periods import resolve_period
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.insights_team_signals import (
    previous_matching_window,
    stale_jobs,
    workdays_in_window,
)

WARSAW = ZoneInfo("Europe/Warsaw")


def test_month_in_progress_compares_with_same_stretch_of_previous_month() -> None:
    now = datetime(2026, 9, 24, 15, 0, tzinfo=WARSAW)
    period = resolve_period("month", offset=0, now=now)
    start, end = previous_matching_window(period, now)
    assert start == datetime(2026, 8, 1, tzinfo=WARSAW)
    assert end == datetime(2026, 8, 24, 15, 0, tzinfo=WARSAW)


def test_closed_month_compares_with_whole_previous_month() -> None:
    now = datetime(2026, 9, 24, 15, 0, tzinfo=WARSAW)
    period = resolve_period("month", offset=-1, now=now)
    start, end = previous_matching_window(period, now)
    assert start == datetime(2026, 7, 1, tzinfo=WARSAW)
    assert end == datetime(2026, 8, 1, tzinfo=WARSAW)


def test_quarter_wraps_the_year() -> None:
    now = datetime(2026, 2, 10, 12, 0, tzinfo=WARSAW)
    period = resolve_period("quarter", offset=0, now=now)
    start, _ = previous_matching_window(period, now)
    assert start == datetime(2025, 10, 1, tzinfo=WARSAW)


def test_workdays_stop_at_today_and_skip_holidays() -> None:
    start = datetime(2026, 11, 1, tzinfo=WARSAW)
    end = datetime(2026, 12, 1, tzinfo=WARSAW)
    # 1–13 listopada 2026: 11.11 to święto, 1.11 niedziela → 9 dni roboczych.
    assert workdays_in_window(start, end, date(2026, 11, 13)) == 9
    # Okres zamknięty liczy się do końca okna, nie do „dziś".
    assert workdays_in_window(start, end, date(2027, 1, 5)) == 20


async def _job(
    *, status: JobStatus, opened_days_ago: int, stage_days_ago: int | None
) -> int:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Stale-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Bez ruchu {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=status,
            remote_policy=RemotePolicy.hybrid,
            client_id=client.id,
            opened_at=now - timedelta(days=opened_days_ago),
        )
        db.add(job)
        await db.flush()
        if stage_days_ago is not None:
            cand = Candidate(
                name="Bez",
                lastname=f"Ruchu-{uuid.uuid4().hex[:4]}",
                email=f"stale-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add(cand)
            await db.flush()
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=now - timedelta(days=stage_days_ago),
                )
            )
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_stale_jobs_are_published_and_silent_for_14_days() -> None:
    silent = await _job(
        status=JobStatus.published, opened_days_ago=60, stage_days_ago=20
    )
    empty = await _job(
        status=JobStatus.published, opened_days_ago=30, stage_days_ago=None
    )
    fresh = await _job(status=JobStatus.published, opened_days_ago=60, stage_days_ago=2)
    closed = await _job(status=JobStatus.closed, opened_days_ago=60, stage_days_ago=40)
    new_empty = await _job(
        status=JobStatus.published, opened_days_ago=3, stage_days_ago=None
    )

    async with AsyncSessionLocal() as db:
        items = await stale_jobs(db, now=datetime.now(timezone.utc))
    by_id = {item["job_id"]: item for item in items}

    assert silent in by_id and by_id[silent]["people"] == 1
    assert by_id[silent]["days_without_move"] >= 19
    assert empty in by_id and by_id[empty]["people"] == 0
    assert fresh not in by_id
    assert closed not in by_id
    assert new_empty not in by_id


async def _login_as(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"team-signals-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Sig"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Sygnały {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_team_routes_answer_for_head_of_recruitment_and_refuse_recruiter(
    app_client: AsyncClient,
) -> None:
    hor = await _login_as(app_client, UserRole.head_of_recruitment)
    people = await app_client.get("/api/insights/team/people", headers=hor)
    assert people.status_code == 200, people.text
    body = people.json()
    assert {"rows", "totals", "previous_totals", "workdays"} <= set(body)
    for row in body["rows"]:
        assert "precision_pct" in row and "previous_placements" in row
        # Bez kwot: widok Zespół nie niesie pieniędzy.
        assert not any(key.endswith("_pln") for key in row)

    attention = await app_client.get("/api/insights/team/attention", headers=hor)
    assert attention.status_code == 200, attention.text
    kinds = {item["kind"] for item in attention.json()["items"]}
    assert kinds <= {"stale_jobs", "low_precision", "weak_preps"}

    stale = await app_client.get("/api/insights/recruitment/stale-jobs", headers=hor)
    assert stale.status_code == 200, stale.text

    recruiter = await _login_as(app_client, UserRole.recruiter)
    for url in (
        "/api/insights/team/people",
        "/api/insights/team/attention",
        "/api/insights/recruitment/stale-jobs",
    ):
        resp = await app_client.get(url, headers=recruiter)
        assert resp.status_code == 403, f"{url}: {resp.text}"
