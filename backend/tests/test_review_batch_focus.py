"""Rekrutacja wybrana na dziś w porcji (zgłoszenie rekruterów 16.11.2026) — prawdziwy Postgres.

Rekruterzy umawiają się rano, kto robi który request. Wybór rekrutacji na dziś
(``review_batch_focus``): osoby przychodzą najpierw z wybranej, z innych
rekrutacji schodzi tylko nadwyżka ponad porcję, kto wybrał pierwszy, bierze
najlepszych, a przebieg porcji co 5 minut i rano tego nie cofa. Baza testowa
jest wspólna: asercje dotyczą własnych wierszy.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import new_column_autofill as autofill
from app.services import review_batch as rb
from app.services import review_batch_focus as focus

# Poniedziałek 09.11.2026, 9:00 w Warszawie: przebieg porcji tylko w dni robocze.
_WORKDAY = datetime(2026, 11, 9, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw")).astimezone(
    timezone.utc
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _user(role: UserRole = UserRole.recruiter) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rbf-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Focus"),
            name=f"RBF {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _world(people: int, *, recruiters: list[int], scores=None) -> dict:
    """Rekrutacja P1 Pilne z zespołem i pulą od progu (domyślnie 90%)."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RBF client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RBF job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
            recruiter_id=recruiters[0],
            priority=JobPriority.urgent,
        )
        candidates = [
            Candidate(name="RBF", lastname=f"{i}-{tag}") for i in range(people)
        ]
        db.add_all([job, *candidates])
        await db.flush()
        for uid in recruiters[1:]:
            db.add(JobCollaborator(job_id=job.id, user_id=uid, source="manual"))
        ids = [c.id for c in candidates]
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job.id,
                    candidate_id=cid,
                    score=Decimal(str((scores or {}).get(i, 90))),
                    run_id="run-rbf",
                    evidence={"matched_must": ["Java"], "missing_must": []},
                )
                for i, cid in enumerate(ids)
            ]
        )
        await db.commit()
        return {"job_id": job.id, "ids": ids}


async def _fill(job_id: int) -> list[int]:
    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, job_id, now=_now(), batch=True)
        await db.commit()
        return added


async def _owned(job_id: int) -> dict[int, list[int]]:
    """Osoba → kandydaci z jej kart porcji w rekrutacji."""
    async with AsyncSessionLocal() as db:
        out: dict[int, list[int]] = {}
        for card in await rb.pending_cards(db, job_ids=[job_id]):
            if card.owner_id is not None:
                out.setdefault(card.owner_id, []).append(card.candidate_id)
        return {uid: sorted(ids) for uid, ids in out.items()}


async def _choose(user_id: int, job_id, *, at: datetime | None = None) -> dict:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        result = await focus.choose(db, user, job_id, now=at or _now())
        await db.commit()
        return result


@pytest.fixture
def batch_on(monkeypatch):
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)

    async def _settings(_db):
        return rb.BatchSettings(minimum=4)

    monkeypatch.setattr(rb, "read_settings", _settings)
    monkeypatch.setattr(autofill._state, "last_plan", None)
    return monkeypatch


async def test_choice_takes_from_the_chosen_job_and_keeps_the_count(batch_on):
    r = await _user()
    a = await _world(10, recruiters=[r])
    b = await _world(10, recruiters=[r])
    await _fill(a["job_id"])
    await _fill(b["job_id"])
    # Porcja 4 z dwóch rekrutacji P1 na zmianę.
    assert {uid: len(ids) for uid, ids in (await _owned(a["job_id"])).items()} == {r: 2}

    result = await _choose(r, b["job_id"])

    assert result["added"] == 2 and result["released"] == 2
    assert await _owned(a["job_id"]) == {}
    async with AsyncSessionLocal() as db:
        logged = (
            await db.scalars(
                select(Activity).where(
                    Activity.action == focus.FOCUS_ACTION, Activity.user_id == r
                )
            )
        ).all()
    assert [row.details for row in logged] == [
        {"job_id": b["job_id"], "added": 2, "released": 2}
    ]
    assert len((await _owned(b["job_id"]))[r]) == 4
    async with AsyncSessionLocal() as db:
        user = await db.get(User, r)
        status = await rb.status_for(db, user, now=_now())
        queue = await rb.review_queue(db, user, now=_now())
    assert status.required == 4 and status.focus["job_id"] == b["job_id"]
    assert {card.job_id for card in queue} == {b["job_id"]}


async def test_first_to_choose_gets_the_best_people(batch_on):
    x, y = await _user(), await _user()
    shared = await _world(6, recruiters=[x, y], scores={i: 95 - i for i in range(6)})
    best, rest = shared["ids"][:4], shared["ids"][4:]

    first = await _choose(x, shared["job_id"])
    second = await _choose(y, shared["job_id"])

    owned = await _owned(shared["job_id"])
    assert owned[x] == sorted(best) and owned[y] == sorted(rest)
    assert first["added"] == 4 and second["added"] == 2
    async with AsyncSessionLocal() as db:
        chosen = await focus.read_focus(db)
    assert chosen[x].at < chosen[y].at


async def test_two_people_choosing_at_once_share_the_pool_without_overlap(batch_on):
    x, y = await _user(), await _user()
    shared = await _world(6, recruiters=[x, y], scores={i: 95 - i for i in range(6)})

    results = await asyncio.gather(
        _choose(x, shared["job_id"]), _choose(y, shared["job_id"])
    )

    owned = await _owned(shared["job_id"])
    assert sorted(len(ids) for ids in owned.values()) == [2, 4]
    assert set(owned[x]).isdisjoint(owned[y])
    assert sorted(result["added"] for result in results) == [2, 4]


async def test_choice_outside_own_jobs_is_refused(batch_on):
    r, other = await _user(), await _user()
    await _world(4, recruiters=[r])
    foreign = await _world(4, recruiters=[other])

    with pytest.raises(HTTPException) as exc:
        await _choose(r, foreign["job_id"])

    assert exc.value.status_code == 403
    async with AsyncSessionLocal() as db:
        assert r not in await focus.read_focus(db)
    assert await _owned(foreign["job_id"]) == {}


async def test_disabled_batch_refuses_the_choice(batch_on):
    r = await _user()
    job = await _world(4, recruiters=[r])
    batch_on.setattr(rb.settings, "REVIEW_BATCH_ENABLED", False, raising=False)

    with pytest.raises(HTTPException) as exc:
        await _choose(r, job["job_id"])

    assert exc.value.status_code == 409


async def test_taken_card_elsewhere_stays_with_the_person(batch_on):
    r = await _user()
    a = await _world(10, recruiters=[r])
    b = await _world(10, recruiters=[r])
    await _fill(a["job_id"])
    await _fill(b["job_id"])
    async with AsyncSessionLocal() as db:
        process = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == a["job_id"],
                    RecruitmentProcess.entry_meta[rb.OWNER_KEY].astext == str(r),
                )
            )
        ).first()
        process.entry_meta = {**process.entry_meta, "decided_at": _now().isoformat()}
        await db.commit()
        taken = process.candidate_id

    result = await _choose(r, b["job_id"])

    # „Biorę” w rekrutacji a zajmuje miejsce: z b przychodzi 1, a zdejmuje się 1.
    assert (await _owned(a["job_id"]))[r] == [taken]
    assert len((await _owned(b["job_id"]))[r]) == 3
    assert (result["added"], result["released"]) == (1, 1)


async def test_back_to_the_usual_order_keeps_the_people(batch_on):
    r = await _user()
    a = await _world(10, recruiters=[r])
    b = await _world(10, recruiters=[r])
    await _fill(a["job_id"])
    await _fill(b["job_id"])
    await _choose(r, b["job_id"])

    result = await _choose(r, None)

    assert result == {"focus": None, "released": 0, "added": 0}
    assert len((await _owned(b["job_id"]))[r]) == 4
    async with AsyncSessionLocal() as db:
        assert r not in await focus.read_focus(db)


@pytest.fixture
async def tick_world(batch_on):
    batch_on.setattr(
        autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", True, raising=False
    )

    async def _no_new(_db):
        return []

    batch_on.setattr(autofill, "_jobs_without_batch", _no_new)
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, autofill.BATCH_DAY_KEY)
        if row is not None:
            await db.delete(row)
            await db.commit()
    return batch_on


async def test_morning_plan_keeps_the_choice(tick_world):
    r = await _user()
    a = await _world(10, recruiters=[r])
    b = await _world(10, recruiters=[r])
    await _fill(a["job_id"])
    await _fill(b["job_id"])
    await _choose(r, b["job_id"])

    async def _only(_db):
        return [a["job_id"], b["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    result = await autofill.tick(now=_WORKDAY)

    # Bez wyboru plan rozdzieliłby porcję 2 + 2 i zdjął dwie karty z b.
    assert result["filled"] == {}
    assert await _owned(a["job_id"]) == {}
    assert len((await _owned(b["job_id"]))[r]) == 4


async def test_routes_choose_and_mark_the_queue(app_client, batch_on):
    from app.core.security import create_access_token

    r = await _user()
    lead = await _user(UserRole.delivery_lead)
    a = await _world(10, recruiters=[r])
    b = await _world(10, recruiters=[r])
    await _fill(a["job_id"])
    await _fill(b["job_id"])
    mine = {"Authorization": f"Bearer {create_access_token(r, 'recruiter')}"}
    dl = {"Authorization": f"Bearer {create_access_token(lead, 'delivery_lead')}"}

    options = await app_client.get("/api/review-batch/me/focus", headers=mine)
    assert options.status_code == 200
    assert {item["job_id"] for item in options.json()["items"]} == {
        a["job_id"],
        b["job_id"],
    }
    preview = await app_client.get(
        f"/api/review-batch/me/focus/{b['job_id']}", headers=mine
    )
    assert preview.json()["take"] == 2 and preview.json()["release"] == 2

    chosen = await app_client.put(
        "/api/review-batch/me/focus", json={"job_id": b["job_id"]}, headers=mine
    )
    assert chosen.status_code == 200 and chosen.json()["added"] == 2
    queue = await app_client.get("/api/review-batch/me/queue", headers=mine)
    assert queue.json()["items"] and all(
        item["why"]["chosen"] for item in queue.json()["items"]
    )

    refused = await app_client.put(
        "/api/review-batch/me/focus", json={"job_id": b["job_id"]}, headers=dl
    )
    assert refused.status_code == 403
