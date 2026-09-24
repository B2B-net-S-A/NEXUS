"""„Moi ludzie" — lista rekrutera wyliczana z historii pipeline'u (21.09.2026).

Kontrakty (decyzje Artura):

- właściciel pary = PIERWSZY weryfikator; późniejszy weryfikator jej nie dostaje;
- para bez ``cv_sent`` nie tworzy listy — liczy się człowiek, który poszedł do klienta;
- para bez weryfikacji (import) → właściciel = pierwszy wysyłający;
- uśpienie chowa osobę (grupa „Uśpieni"), zdjęcie uśpienia ją przywraca;
- przypięcie dokłada osobę spoza wyliczenia;
- globalna blacklista wyklucza, żywa umowa przenosi do „Pracują";
- każdy widzi wyłącznie swoją listę (trasa czyta ``current_user``).

Baza testowa jest wspólna i nieczyszczona, więc każdy test tworzy własnych
użytkowników i asertuje wyłącznie po SWOICH kandydatach.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

T0 = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


async def _user(db, role: str = "recruiter"):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"my-people-{marker}@example.com",
        name=f"Rekruter {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _job(db, *, status: str = "published"):
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    marker = uuid.uuid4().hex[:10]
    client = Client(name=f"my-people-client-{marker}")
    db.add(client)
    await db.flush()
    job = Job(title=f"Java Dev {marker}", client_id=client.id, status=JobStatus(status))
    db.add(job)
    await db.flush()
    return job


async def _candidate(db, **kw):
    from app.models.candidate import Candidate

    cand = Candidate(name="Ola", lastname=f"Mp{uuid.uuid4().hex[:8]}", **kw)
    db.add(cand)
    await db.flush()
    return cand


async def _stage(db, *, cand, job, stage: str, by, at: datetime):
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    row = CandidateStage(
        candidate_id=cand.id,
        job_id=job.id,
        stage=PipelineStage(stage),
        moved_by=by.id if by else None,
        moved_at=at,
    )
    db.add(row)
    await db.flush()
    return row


def _ids(people) -> set[int]:
    return {r.candidate_id for r in people.rows}


@needs_db
@pytest.mark.asyncio
async def test_first_verifier_owns_the_person_even_if_someone_else_sent_the_cv():
    from app.core.database import AsyncSessionLocal
    from app.services.my_people import load_my_people

    async with AsyncSessionLocal() as db:
        first, second, sender = await _user(db), await _user(db), await _user(db)
        job = await _job(db)
        cand = await _candidate(db)
        await _stage(db, cand=cand, job=job, stage="verified", by=first, at=T0)
        await _stage(
            db,
            cand=cand,
            job=job,
            stage="verified",
            by=second,
            at=T0 + timedelta(days=1),
        )
        await _stage(
            db,
            cand=cand,
            job=job,
            stage="cv_sent",
            by=sender,
            at=T0 + timedelta(days=2),
        )
        await db.commit()

        assert cand.id in _ids(await load_my_people(db, first.id))
        assert cand.id not in _ids(await load_my_people(db, second.id))
        # Wysyłający nie jest właścicielem, gdy istnieje weryfikacja.
        assert cand.id not in _ids(await load_my_people(db, sender.id))

        [row] = [
            r
            for r in (await load_my_people(db, first.id)).rows
            if r.candidate_id == cand.id
        ]
        assert row.furthest_stage == "cv_sent"
        assert row.sent_count == 1
        assert row.last_sent_client_name.startswith("my-people-client-")
        assert row.source == "auto"


@needs_db
@pytest.mark.asyncio
async def test_verified_but_never_sent_is_not_on_the_list():
    from app.core.database import AsyncSessionLocal
    from app.services.my_people import load_my_people

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        job = await _job(db)
        cand = await _candidate(db)
        await _stage(db, cand=cand, job=job, stage="verified", by=me, at=T0)
        await db.commit()
        assert cand.id not in _ids(await load_my_people(db, me.id))


@needs_db
@pytest.mark.asyncio
async def test_pair_without_verification_belongs_to_the_first_sender():
    from app.core.database import AsyncSessionLocal
    from app.services.my_people import load_my_people

    async with AsyncSessionLocal() as db:
        sender, later = await _user(db), await _user(db)
        job = await _job(db)
        cand = await _candidate(db)
        await _stage(db, cand=cand, job=job, stage="cv_sent", by=sender, at=T0)
        await _stage(
            db, cand=cand, job=job, stage="cv_sent", by=later, at=T0 + timedelta(days=3)
        )
        await db.commit()
        assert cand.id in _ids(await load_my_people(db, sender.id))
        assert cand.id not in _ids(await load_my_people(db, later.id))


@needs_db
@pytest.mark.asyncio
async def test_furthest_stage_and_grouping_by_primary_category():
    from app.core.database import AsyncSessionLocal
    from app.models.competence_category import (
        CandidateCompetenceCategory,
        CompetenceCategory,
    )
    from app.services.my_people import load_my_people
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        job_a, job_b = await _job(db), await _job(db)
        cand = await _candidate(db)
        cc = (await db.scalars(select(CompetenceCategory).limit(1))).first()
        if cc is None:
            pytest.skip("brak zasianych kategorii kompetencji")
        db.add(
            CandidateCompetenceCategory(
                candidate_id=cand.id, competence_category_id=cc.id, is_primary=True
            )
        )
        await _stage(db, cand=cand, job=job_a, stage="verified", by=me, at=T0)
        await _stage(
            db, cand=cand, job=job_a, stage="cv_sent", by=me, at=T0 + timedelta(days=1)
        )
        await _stage(
            db,
            cand=cand,
            job=job_a,
            stage="client_interview",
            by=me,
            at=T0 + timedelta(days=5),
        )
        await _stage(
            db,
            cand=cand,
            job=job_b,
            stage="verified",
            by=me,
            at=T0 + timedelta(days=20),
        )
        await _stage(
            db, cand=cand, job=job_b, stage="cv_sent", by=me, at=T0 + timedelta(days=21)
        )
        await db.commit()

        [row] = [
            r
            for r in (await load_my_people(db, me.id)).rows
            if r.candidate_id == cand.id
        ]
        assert row.furthest_stage == "client_interview"
        assert row.sent_count == 2
        assert row.category_id == cc.id
        assert row.last_sent_at == T0 + timedelta(days=21)
        assert row.last_sent_job_title == job_b.title


@needs_db
@pytest.mark.asyncio
async def test_snooze_hides_and_unsnooze_restores(app_client):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        job = await _job(db)
        cand = await _candidate(db)
        await _stage(db, cand=cand, job=job, stage="verified", by=me, at=T0)
        await _stage(
            db, cand=cand, job=job, stage="cv_sent", by=me, at=T0 + timedelta(days=1)
        )
        await db.commit()
        uid, cid = me.id, cand.id

    headers = {
        "Authorization": f"Bearer {create_access_token(subject=uid, role='recruiter')}"
    }

    def row(body):
        return next(r for r in body["rows"] if r["candidate_id"] == cid)

    resp = await app_client.get("/api/my-people", headers=headers)
    assert resp.status_code == 200, resp.text
    assert row(resp.json())["snoozed"] is False

    resp = await app_client.post(
        f"/api/my-people/{cid}/snooze", headers=headers, json={"reason": "found_job"}
    )
    assert resp.status_code == 204, resp.text
    body = (await app_client.get("/api/my-people", headers=headers)).json()
    assert row(body)["snoozed"] is True
    assert row(body)["snooze_reason"] == "found_job"

    resp = await app_client.delete(f"/api/my-people/{cid}/snooze", headers=headers)
    assert resp.status_code == 204
    body = (await app_client.get("/api/my-people", headers=headers)).json()
    assert row(body)["snoozed"] is False


@needs_db
@pytest.mark.asyncio
async def test_unsnooze_of_a_pinned_person_restores_the_pin(app_client):
    """CAND-07: osoba przypięta (np. ze stałego linku) po „Uśpij” → „Przywróć”
    wraca na listę jako przypięta, zamiast zniknąć razem z wierszem."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.my_people import MyPeopleOverride

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        cand = await _candidate(db)
        await db.commit()
        uid, cid = me.id, cand.id
    headers = {
        "Authorization": f"Bearer {create_access_token(subject=uid, role='recruiter')}"
    }

    def ids(body):
        return {r["candidate_id"]: r for r in body["rows"]}

    assert (
        await app_client.post(f"/api/my-people/{cid}/pin", headers=headers)
    ).status_code == 204
    assert (
        await app_client.post(
            f"/api/my-people/{cid}/snooze", headers=headers, json={"reason": "other"}
        )
    ).status_code == 204
    # Drugie uśpienie (np. zmiana powodu) nie gubi pamięci przypięcia.
    assert (
        await app_client.post(
            f"/api/my-people/{cid}/snooze",
            headers=headers,
            json={"reason": "no_contact"},
        )
    ).status_code == 204
    body = (await app_client.get("/api/my-people", headers=headers)).json()
    assert ids(body)[cid]["snoozed"] is True

    assert (
        await app_client.delete(f"/api/my-people/{cid}/snooze", headers=headers)
    ).status_code == 204
    body = (await app_client.get("/api/my-people", headers=headers)).json()
    row = ids(body).get(cid)
    assert row is not None, "przypięta osoba zniknęła po przywróceniu"
    assert row["snoozed"] is False and row["source"] == "pinned"
    async with AsyncSessionLocal() as db:
        ov = await db.scalar(
            select(MyPeopleOverride).where(
                MyPeopleOverride.user_id == uid,
                MyPeopleOverride.candidate_id == cid,
            )
        )
        assert ov.kind == "pinned" and ov.restore_kind is None

    # Odpięcie uśpionej osoby: po „Przywróć” już jej nie ma.
    await app_client.post(
        f"/api/my-people/{cid}/snooze", headers=headers, json={"reason": "other"}
    )
    await app_client.delete(f"/api/my-people/{cid}/pin", headers=headers)
    await app_client.delete(f"/api/my-people/{cid}/snooze", headers=headers)
    body = (await app_client.get("/api/my-people", headers=headers)).json()
    assert cid not in ids(body)


@needs_db
@pytest.mark.asyncio
async def test_pin_adds_a_person_without_history_and_is_private(app_client):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token

    async with AsyncSessionLocal() as db:
        me, other = await _user(db), await _user(db)
        cand = await _candidate(db)
        await db.commit()
        me_id, other_id, cid = me.id, other.id, cand.id

    mine = {
        "Authorization": f"Bearer {create_access_token(subject=me_id, role='recruiter')}"
    }
    theirs = {
        "Authorization": f"Bearer {create_access_token(subject=other_id, role='recruiter')}"
    }

    assert (
        await app_client.post(f"/api/my-people/{cid}/pin", headers=mine)
    ).status_code == 204
    body = (await app_client.get("/api/my-people", headers=mine)).json()
    [pinned] = [r for r in body["rows"] if r["candidate_id"] == cid]
    assert pinned["source"] == "pinned"

    other_body = (await app_client.get("/api/my-people", headers=theirs)).json()
    assert cid not in {r["candidate_id"] for r in other_body["rows"]}

    assert (
        await app_client.post("/api/my-people/999999999/pin", headers=mine)
    ).status_code == 404


@needs_db
@pytest.mark.asyncio
async def test_blacklisted_is_excluded_and_working_goes_to_its_own_group(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import CandidateStatus
    from app.services import my_people as svc

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        job = await _job(db)
        banned = await _candidate(db, status=CandidateStatus.blacklisted)
        working = await _candidate(db)
        for cand in (banned, working):
            await _stage(db, cand=cand, job=job, stage="verified", by=me, at=T0)
            await _stage(
                db,
                cand=cand,
                job=job,
                stage="cv_sent",
                by=me,
                at=T0 + timedelta(days=1),
            )
        await db.commit()

        real = svc.current_employment_client_ids

        async def fake(db_, ids, **kw):
            out = await real(db_, ids, **kw)
            if working.id in out:
                out[working.id] = {job.client_id}
            return out

        monkeypatch.setattr(svc, "current_employment_client_ids", fake)
        people = await svc.load_my_people(db, me.id)

    assert banned.id not in _ids(people)
    [row] = [r for r in people.rows if r.candidate_id == working.id]
    assert row.working is True
    assert working.id not in {r.candidate_id for r in people.active}


@needs_db
@pytest.mark.asyncio
async def test_summary_counts_unseen_matches_and_seen_clears_them(app_client):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.my_people import MyPeopleJobMatch

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        job = await _job(db)
        cand = await _candidate(db)
        await _stage(db, cand=cand, job=job, stage="verified", by=me, at=T0)
        await _stage(
            db, cand=cand, job=job, stage="cv_sent", by=me, at=T0 + timedelta(days=1)
        )
        new_job = await _job(db)
        db.add(
            MyPeopleJobMatch(
                user_id=me.id, job_id=new_job.id, candidate_id=cand.id, score=81
            )
        )
        await db.commit()
        uid, job_id = me.id, new_job.id

    headers = {
        "Authorization": f"Bearer {create_access_token(subject=uid, role='recruiter')}"
    }
    body = (await app_client.get("/api/my-people/summary", headers=headers)).json()
    assert body["new_matches"] == 1
    assert body["jobs_with_matches"] == 1
    assert body["latest_matches"][0]["job_id"] == job_id

    resp = await app_client.post(
        "/api/my-people/matches/seen", headers=headers, json={"job_id": job_id}
    )
    assert resp.json() == {"updated": 1}
    body = (await app_client.get("/api/my-people/summary", headers=headers)).json()
    assert body["new_matches"] == 0


def test_router_is_mounted():
    from app.main import app

    # `app.routes` nie jest płaską listą od FastAPI 0.139 — ścieżki z OpenAPI.
    paths = set(app.openapi()["paths"])
    for path in (
        "/api/my-people",
        "/api/my-people/summary",
        "/api/my-people/for-job/{job_id}",
        "/api/my-people/{candidate_id}/snooze",
        "/api/my-people/{candidate_id}/pin",
        "/api/my-people/matches/seen",
    ):
        assert path in paths, path


def test_jarvis_my_people_tools_hide_working_and_mark_unscored():
    """Jarvis widzi tylko osoby do przepięcia, a brak wyniku to NIE zero."""
    from app.services.jarvis.tools import TOOLS_BY_NAME

    listed = TOOLS_BY_NAME["my_people"].shape(
        {
            "active_count": 1,
            "working_count": 1,
            "snoozed_count": 1,
            "rows": [
                {
                    "candidate_id": 1,
                    "full_name": "A",
                    "working": False,
                    "snoozed": False,
                },
                {
                    "candidate_id": 2,
                    "full_name": "B",
                    "working": True,
                    "snoozed": False,
                },
                {
                    "candidate_id": 3,
                    "full_name": "C",
                    "working": False,
                    "snoozed": True,
                },
            ],
        },
        {},
    )
    assert [p["candidate_id"] for p in listed["people"]] == [1]

    for_job = TOOLS_BY_NAME["my_people_for_job"].shape(
        {
            "job_id": 9,
            "job_title": "Java",
            "in_job_count": 0,
            "degraded": False,
            "rows": [
                {
                    "candidate_id": 1,
                    "full_name": "A",
                    "score": None,
                    "eligibility": None,
                },
                {
                    "candidate_id": 2,
                    "full_name": "B",
                    "score": 80,
                    "eligibility": {"reason": "Weto HM", "assignment_allowed": False},
                },
            ],
        },
        {"job_id": 9},
    )
    rows = {p["candidate_id"]: p for p in for_job["people"]}
    assert rows[1]["score"] == "niepoliczony"
    assert rows[2]["nie_mozna_dodac"] is True
    assert TOOLS_BY_NAME["my_people"].tier == "read"
    assert TOOLS_BY_NAME["my_people_for_job"].tier == "read"



def test_days_since_counts_the_company_calendar_day_not_utc() -> None:
    """Audyt 24.09.2026: wysyłka o 23:30 UTC to już następny dzień w Warszawie.
    Dzień znacznika liczymy w strefie firmy, jak ``business_today()``."""
    from datetime import date

    from app.services.my_people import _days_since

    late_evening_utc = datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc)
    # W Warszawie to 23.09 01:30 — dzień przed „dziś” 24.09.
    assert _days_since(late_evening_utc, date(2026, 9, 24)) == 1
    assert _days_since(None, date(2026, 9, 24)) is None
