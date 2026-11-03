"""Zakładka „Źródła”: liczby, osoby za liczbą i kto co widzi.

Pod ochroną:

1. Liczba i lista osób pod nią to ten sam zbiór, na każdym poziomie.
2. Portale liczą etap PO zgłoszeniu; wcześniejsza weryfikacja się nie liczy, a powrót
   po wcześniejszej tak.
3. Linki trzymają regułę „Kto co przyniósł”: etap w rekrutacji linku.
4. Cudze wyniki linków nie wychodzą do rekrutera.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.client import Client
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.insights_link_people import compute_link_people
from app.services.insights_sources import (
    compute_link_breakdown,
    compute_people,
    compute_portal_offers,
    compute_sources,
)


def _window() -> tuple[datetime, datetime]:
    # Baza testowa nie jest czyszczona, więc każdy test ma własne okno w przyszłości.
    start = datetime(2047, 1, 1, tzinfo=timezone.utc) + timedelta(
        days=random.randint(0, 5000)
    )
    return start, start + timedelta(days=5)


async def _candidate(db, *, created_at: datetime, name: str = "Ola") -> int:
    candidate = Candidate(
        name=name,
        lastname=f"Źródło-{uuid.uuid4().hex[:6]}",
        email=f"zrodla-{uuid.uuid4().hex[:10]}@example.com",
        created_at=created_at,
    )
    db.add(candidate)
    await db.flush()
    return candidate.id


async def _job(db, title: str = "Rekrutacja") -> int:
    client = Client(name=f"Zrodla-{uuid.uuid4().hex[:6]}")
    db.add(client)
    await db.flush()
    job = Job(
        title=f"{title} {uuid.uuid4().hex[:6]}",
        location="Warszawa",
        status=JobStatus.published,
        remote_policy=RemotePolicy.hybrid,
        client_id=client.id,
    )
    db.add(job)
    await db.flush()
    return job.id


def _event(candidate_id: int, at: datetime, utm: str | None, offer: str = "Tester"):
    return CandidateSourceEvent(
        candidate_id=candidate_id,
        channel=SourceChannel.posting,
        utm_source=utm,
        utm_medium="job_board",
        note=f"Źródło: Portal — oferta: {offer}",
        captured_at=at,
    )


def _stage(candidate_id: int, job_id: int, stage: PipelineStage, at: datetime):
    return CandidateStage(
        candidate_id=candidate_id, job_id=job_id, stage=stage, moved_at=at
    )


async def _owner(db) -> int:
    user = User(
        email=f"zrodla-wlasciciel-{uuid.uuid4().hex[:8]}@example.com",
        name=f"Właściciel {uuid.uuid4().hex[:4]}",
        password_hash=hash_password("T3st_Zrodla!long"),
        role=UserRole.recruiter,
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user.id


async def _link_application(
    db, *, owner_id: int, job_id: int | None, candidate_id: int, at: datetime
) -> None:
    token = uuid.uuid4().hex
    digest = uuid.uuid4().hex
    db.add(
        CandidateInviteLink(
            token=token,
            created_by=owner_id,
            kind="job" if job_id else "recruiter",
            job_id=job_id,
            slug=None if job_id else f"zrodla-{uuid.uuid4().hex[:10]}",
            token_sha256=digest,
        )
    )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="applied_via_invite",
            details={"invite_token_sha256": digest, "was_duplicate": False},
            created_at=at,
        )
    )


async def _people(db, since, until, **kwargs) -> dict:
    return await compute_people(db, since=since, until=until, **kwargs)


@pytest.mark.asyncio
async def test_portal_counts_only_stages_after_the_application() -> None:
    since, until = _window()
    day = since + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        job_id = await _job(db)
        # Nowa osoba: dwa zgłoszenia, po pierwszym weryfikacja i CV.
        new_person = await _candidate(db, created_at=day - timedelta(minutes=1))
        db.add(_event(new_person, day, "pracuj", "Tester"))
        db.add(_event(new_person, day + timedelta(hours=1), "pracuj", "Analityk"))
        db.add(
            _stage(new_person, job_id, PipelineStage.verified, day + timedelta(hours=2))
        )
        db.add(
            _stage(new_person, job_id, PipelineStage.cv_sent, day + timedelta(hours=3))
        )
        # Znana osoba: weryfikacja PRZED zgłoszeniem się nie liczy.
        known = await _candidate(db, created_at=day - timedelta(days=30))
        db.add(_stage(known, job_id, PipelineStage.verified, day - timedelta(days=20)))
        db.add(_event(known, day, "pracuj", "Tester"))
        # Etap „Z ogłoszenia” to jeszcze nie rekrutacja.
        waiting = await _candidate(db, created_at=day - timedelta(days=30))
        db.add(_event(waiting, day, "pracuj", "Tester"))
        db.add(_stage(waiting, job_id, PipelineStage.posting, day + timedelta(hours=1)))
        # Poza oknem, inne źródło i bez znacznika: nie liczą się.
        outside = await _candidate(db, created_at=day - timedelta(days=30))
        db.add(_event(outside, since - timedelta(days=1), "pracuj"))
        other = await _candidate(db, created_at=day - timedelta(days=30))
        db.add(_event(other, day, "linkedin"))
        db.add(_event(other, day, None))
        await db.commit()

        result = await compute_sources(db, since=since, until=until)

    pracuj = next(row for row in result["portals"] if row["source"] == "pracuj")
    assert pracuj["people"] == 3
    assert pracuj["applications"] == 4
    assert pracuj["fresh"] == 1
    assert pracuj["in_process"] == 1
    assert pracuj["verified"] == 1
    assert pracuj["cv_sent"] == 1
    assert pracuj["hired"] == 0


@pytest.mark.asyncio
async def test_person_returning_after_old_verification_counts_when_verified_again() -> (
    None
):
    since, until = _window()
    day = since + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        old_job, new_job = await _job(db), await _job(db)
        person = await _candidate(db, created_at=day - timedelta(days=90))
        db.add(
            _stage(person, old_job, PipelineStage.verified, day - timedelta(days=60))
        )
        db.add(_event(person, day, "pracuj"))
        db.add(
            _stage(person, new_job, PipelineStage.verified, day + timedelta(hours=2))
        )
        await db.commit()

        result = await compute_sources(db, since=since, until=until)

    pracuj = next(row for row in result["portals"] if row["source"] == "pracuj")
    assert pracuj["verified"] == 1


@pytest.mark.asyncio
async def test_jjit_row_takes_every_portal_key_and_total_counts_person_once() -> None:
    since, until = _window()
    day = since + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        both = await _candidate(db, created_at=day - timedelta(days=30))
        db.add(_event(both, day, "pracuj"))
        db.add(_event(both, day, "rocketjobs"))
        other = await _candidate(db, created_at=day - timedelta(days=30))
        db.add(_event(other, day, "jjit"))
        third = await _candidate(db, created_at=day - timedelta(days=30))
        db.add(_event(third, day, "justjoinit"))
        await db.commit()

        result = await compute_sources(db, since=since, until=until)

    by_source = {row["source"]: row for row in result["portals"]}
    assert by_source["jjit"]["label"] == "JustJoin.IT i RocketJobs"
    assert by_source["jjit"]["people"] == 3
    assert by_source["pracuj"]["people"] == 1
    assert result["portals_total"]["people"] == 3
    assert result["portals_total"]["applications"] == 4


@pytest.mark.asyncio
async def test_people_list_matches_the_number_on_every_level() -> None:
    since, until = _window()
    day = since + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        job_id = await _job(db, "Docelowa")
        advanced = await _candidate(
            db, created_at=day - timedelta(days=30), name="Daleka"
        )
        db.add(_event(advanced, day, "pracuj", "Tester"))
        db.add(
            _stage(advanced, job_id, PipelineStage.interview, day + timedelta(hours=1))
        )
        db.add(
            _stage(advanced, job_id, PipelineStage.cv_sent, day + timedelta(hours=2))
        )
        # Późniejsza wewnętrzna rozmowa nie cofa najdalszego etapu.
        db.add(
            _stage(advanced, job_id, PipelineStage.interview, day + timedelta(hours=3))
        )
        fresh = await _candidate(db, created_at=day, name="Świeża")
        db.add(_event(fresh, day, "pracuj", "Analityk"))
        await db.commit()

        table = await compute_sources(db, since=since, until=until)
        pracuj = next(row for row in table["portals"] if row["source"] == "pracuj")
        for metric in (
            "people",
            "applications",
            "fresh",
            "in_process",
            "cv_sent",
            "hired",
        ):
            listed = await _people(db, since, until, source="pracuj", metric=metric)
            expected = pracuj["people"] if metric == "applications" else pracuj[metric]
            assert listed["total"] == expected, metric
            assert len(listed["rows"]) == expected, metric

        offers = await compute_portal_offers(
            db, source="pracuj", since=since, until=until, limit=10, offset=0
        )
        assert offers["total"] == 2
        tester = next(row for row in offers["rows"] if row["offer"] == "Tester")
        assert tester["cv_sent"] == 1
        narrowed = await _people(
            db, since, until, source="pracuj", metric="cv_sent", offer="Tester"
        )
        assert narrowed["total"] == 1

        everyone = await _people(db, since, until, source="pracuj", metric="people")

    first, second = everyone["rows"]
    assert first["candidate_id"] == advanced
    assert first["stage"] == "cv_sent"
    assert first["job_title"].startswith("Docelowa")
    assert second["candidate_id"] == fresh
    assert second["stage"] is None
    assert second["offer"] == "Analityk"


@pytest.mark.asyncio
async def test_links_agree_with_who_brought_what() -> None:
    since, until = _window()
    day = since + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        owner = await _owner(db)
        link_job, other_job = await _job(db), await _job(db)
        by_general = await _candidate(db, created_at=day)
        await _link_application(
            db, owner_id=owner, job_id=None, candidate_id=by_general, at=day
        )
        db.add(
            _stage(by_general, other_job, PipelineStage.new, day + timedelta(hours=1))
        )
        by_job = await _candidate(db, created_at=day)
        await _link_application(
            db, owner_id=owner, job_id=link_job, candidate_id=by_job, at=day
        )
        # Etap w INNEJ rekrutacji niż link do rekrutacji się nie liczy.
        db.add(
            _stage(by_job, other_job, PipelineStage.verified, day + timedelta(hours=1))
        )
        await db.commit()

        table = await compute_sources(db, since=since, until=until)
        people_report = await compute_link_people(
            db,
            since=since,
            until=until,
            since_day=since.date(),
            until_day=until.date(),
        )
        breakdown = await compute_link_breakdown(
            db, source="link_general", since=since, until=until
        )
        scoped = await _people(
            db, since, until, source="link_general", metric="people", owner_id=owner
        )

    by_source = {row["source"]: row for row in table["career"]}
    assert by_source["link_general"]["in_process"] == 1
    assert by_source["link_job"]["in_process"] == 0
    assert by_source["link_job"]["verified"] == 0
    assert table["career_total"]["people"] == 2
    row = next(r for r in people_report["rows"] if r["user_id"] == owner)
    assert row["applications_general"] == by_source["link_general"]["applications"]
    assert row["applications_job"] == by_source["link_job"]["applications"]
    assert row["in_process"] == table["career_total"]["in_process"]
    assert [r["key"] for r in breakdown["rows"]] == [owner]
    assert scoped["total"] == 1
    assert scoped["rows"][0]["link_owner"] is not None


async def _login(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"zrodla-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Zrd"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Źródła {unique}",
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
async def test_recruiter_sees_people_without_foreign_link_results(
    app_client: AsyncClient,
) -> None:
    since, until = _window()
    day = since + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        owner = await _owner(db)
        job_id = await _job(db, "Cudza")
        person = await _candidate(db, created_at=day)
        await _link_application(
            db, owner_id=owner, job_id=None, candidate_id=person, at=day
        )
        db.add(_stage(person, job_id, PipelineStage.verified, day + timedelta(hours=1)))
        await db.commit()
    params = {
        "period": "custom",
        "date_from": since.date().isoformat(),
        "date_to": (until - timedelta(days=1)).date().isoformat(),
    }
    recruiter = await _login(app_client, UserRole.recruiter)
    hor = await _login(app_client, UserRole.head_of_recruitment)

    table = await app_client.get(
        "/api/insights/sources", params=params, headers=recruiter
    )
    assert table.status_code == 200, table.text

    links = await app_client.get(
        "/api/insights/sources/links",
        params={**params, "source": "link_general"},
        headers=recruiter,
    )
    assert links.status_code == 403

    by_owner = await app_client.get(
        "/api/insights/sources/people",
        params={
            **params,
            "source": "link_general",
            "metric": "people",
            "owner_id": owner,
        },
        headers=recruiter,
    )
    assert by_owner.status_code == 403

    listing = {**params, "source": "link_general", "metric": "people"}
    seen = await app_client.get(
        "/api/insights/sources/people", params=listing, headers=recruiter
    )
    assert seen.status_code == 200, seen.text
    row = seen.json()["rows"][0]
    assert row["stage"] == "verified"
    assert row["link_owner"] is None

    manager = await app_client.get(
        "/api/insights/sources/people", params=listing, headers=hor
    )
    row = manager.json()["rows"][0]
    assert row["link_owner"] is not None


@pytest.mark.asyncio
async def test_board_gets_no_sources(app_client: AsyncClient) -> None:
    board = await _login(app_client, UserRole.board)
    resp = await app_client.get(
        "/api/insights/sources",
        params={"period": "month", "offset": 0},
        headers=board,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unknown_metric_and_bad_range_are_refused(
    app_client: AsyncClient,
) -> None:
    hor = await _login(app_client, UserRole.head_of_recruitment)
    bad_metric = await app_client.get(
        "/api/insights/sources/people",
        params={"source": "pracuj", "metric": "fresh; DROP TABLE users"},
        headers=hor,
    )
    assert bad_metric.status_code == 422
    no_dates = await app_client.get(
        "/api/insights/sources", params={"period": "custom"}, headers=hor
    )
    assert no_dates.status_code == 422
