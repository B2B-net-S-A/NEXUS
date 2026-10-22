"""„Pasuje też do” na prawdziwej bazie (14.10.2026, D1–D2).

Kontrakty:

- pula = rekrutacje opublikowane w pracy, bez rekrutacji, z której pytamy,
  i bez tych, w których osoba ma JAKIKOLWIEK wiersz etapu (w toku albo
  zamknięta karta);
- trasa oddaje najwyżej 3 rekrutacje z oceny (zawężenie i ocena podmienione);
- „+ Dodaj” ze źródłem ``also_fits`` = ręczne dodanie (rezerwacja jak zawsze),
  wpis w historii z rekrutacją źródłową i dzwonek do rekrutera rekrutacji B —
  nie do osoby, która dodała;
- karta Tablicy niesie inne rekrutacje, w których osoba stoi w „Nowych”/
  „Screeningu” — bez bieżącej, bez zamkniętych i bez późniejszych etapów.

Baza testowa jest wspólna i nieczyszczona: każdy test tworzy własne dane
i asertuje wyłącznie po nich.
"""

from __future__ import annotations

import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.test_my_people import T0, _candidate, _job, _stage, _user

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


async def _in_work(db, *, status="published", work_state="searching", recruiter=None):
    job = await _job(db, status=status)
    job.work_state = work_state
    if recruiter is not None:
        job.recruiter_id = recruiter.id
    await db.flush()
    return job


@needs_db
@pytest.mark.asyncio
async def test_pool_skips_origin_closed_cards_and_jobs_not_in_work():
    from app.core.database import AsyncSessionLocal
    from app.services.also_fits import open_pool_job_ids

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        cand = await _candidate(db)
        origin = await _in_work(db)
        good = await _in_work(db)
        to_review = await _in_work(db, work_state="to_review")
        finished = await _in_work(db, work_state="finished")
        closed = await _in_work(db, status="closed")
        draft = await _in_work(db, status="draft")
        rejected_there = await _in_work(db)
        in_progress = await _in_work(db)
        await _stage(db, cand=cand, job=origin, stage="new", by=me, at=T0)
        await _stage(db, cand=cand, job=rejected_there, stage="rejected", by=me, at=T0)
        await _stage(db, cand=cand, job=in_progress, stage="screening", by=me, at=T0)
        await db.commit()

        pool = set(
            await open_pool_job_ids(db, candidate_id=cand.id, from_job_id=origin.id)
        )
        mine = {
            origin.id,
            good.id,
            to_review.id,
            finished.id,
            closed.id,
            draft.id,
            rejected_there.id,
            in_progress.id,
        }
        assert pool & mine == {good.id, to_review.id}


@needs_db
@pytest.mark.asyncio
async def test_route_returns_scored_jobs_for_a_recruiter(app_client, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.services import auto_match_service, my_people_matching

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        cand = await _candidate(db)
        origin = await _in_work(db)
        fits_job = await _in_work(db)
        weak_job = await _in_work(db)
        await _stage(db, cand=cand, job=origin, stage="new", by=me, at=T0)
        from app.models.client import Client

        client = await db.get(Client, fits_job.client_id)
        client.display_name = "Nazwa z NEXUSA"
        await db.commit()
        uid, cid, origin_id = me.id, cand.id, origin.id
        fits_id, weak_id = fits_job.id, weak_job.id

    async def similarity(text, *, jobs_collection, ids):
        return {fits_id: 0.9, weak_id: 0.8}

    async def fits(db, *, job, candidates, profile_user_id):
        score = 84 if job.id == fits_id else 52
        return [
            SimpleNamespace(
                candidate_id=cid,
                score=score,
                measurement="measured",
                decision=None,
                hidden=False,
                breakdown=SimpleNamespace(matching_must=["Angular"], gap_must=[]),
            )
        ]

    monkeypatch.setattr(auto_match_service, "scoped_similarity", similarity)
    monkeypatch.setattr(my_people_matching, "fits_for_job", fits)
    headers = {
        "Authorization": f"Bearer {create_access_token(subject=uid, role='recruiter')}"
    }
    resp = await app_client.get(
        f"/api/candidates/{cid}/also-fits",
        params={"from_job_id": origin_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert [j["job_id"] for j in body["jobs"]] == [fits_id]
    assert body["jobs"][0]["score"] == 84
    assert body["jobs"][0]["matching_must"] == ["Angular"]
    # Nazwa klienta jak wszędzie w aplikacji (display_name przed nazwą źródłową).
    assert body["jobs"][0]["client_name"] == "Nazwa z NEXUSA"
    # Osoba bez umowy u nas — bez źródła „nasz konsultant” (R2, 22.10.2026).
    assert body["source"] is None and body["returns_to_market_on"] is None


@needs_db
@pytest.mark.asyncio
async def test_route_requires_from_job_id(app_client, app_auth_headers):
    resp = await app_client.get("/api/candidates/1/also-fits", headers=app_auth_headers)
    assert resp.status_code == 422


@needs_db
@pytest.mark.asyncio
async def test_add_from_also_fits_rings_job_recruiter_not_the_actor(app_client):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.activity import Activity
    from app.models.notification import Notification, NotificationType
    from app.models.recruitment_process import RecruitmentProcess

    async with AsyncSessionLocal() as db:
        actor = await _user(db)
        owner = await _user(db)
        cand = await _candidate(db)
        origin = await _in_work(db, recruiter=actor)
        target = await _in_work(db, recruiter=owner)
        # „Dodaj do wszystkich”: druga rekrutacja tego samego rekrutera tego dnia.
        second = await _in_work(db, recruiter=owner)
        await _stage(db, cand=cand, job=origin, stage="new", by=actor, at=T0)
        await db.commit()
        actor_id, owner_id, cid = actor.id, owner.id, cand.id
        origin_id, target_id, second_id = origin.id, target.id, second.id

    headers = {
        "Authorization": f"Bearer {create_access_token(subject=actor_id, role='recruiter')}"
    }
    for job_id in (target_id, second_id):
        resp = await app_client.post(
            f"/api/jobs/{job_id}/proposals/bulk",
            json={
                "candidate_ids": [cid],
                "initial_stage_legacy": "new",
                "source": "also_fits",
                "origin_job_id": origin_id,
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["added"] == [cid]

    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.notification_type == NotificationType.also_fits_added,
                    Notification.user_id.in_([owner_id, actor_id]),
                    Notification.link.like(f"%candidate={cid}"),
                )
            )
        ).all()
        # Jeden dzwonek na rekrutację — dedup dzienny nie zjada drugiego.
        assert {b.user_id for b in bells} == {owner_id}
        assert sorted(b.link for b in bells) == sorted(
            [f"/jobs/{target_id}?candidate={cid}", f"/jobs/{second_id}?candidate={cid}"]
        )
        assert {b.related_entity_type for b in bells} == {"candidate_stage"}
        trail = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == cid,
                    Activity.action == "also_fits_added",
                )
            )
        ).all()
        assert sorted(t.details["job_id"] for t in trail) == sorted(
            [target_id, second_id]
        )
        assert {t.details["from_job_id"] for t in trail} == {origin_id}
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == cid,
                RecruitmentProcess.job_id == target_id,
            )
        )
        assert process is not None
        assert process.entry_source == "added_manual"
        assert process.claimed_by_user_id == actor_id


@needs_db
@pytest.mark.asyncio
async def test_kanban_card_lists_other_jobs_waiting_in_new_or_screening(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        cand = await _candidate(db)
        board = await _in_work(db)
        waiting = await _in_work(db)
        screening = await _in_work(db)
        sent = await _in_work(db)
        closed = await _in_work(db, status="closed")
        await _stage(db, cand=cand, job=board, stage="new", by=me, at=T0)
        await _stage(db, cand=cand, job=waiting, stage="new", by=me, at=T0)
        await _stage(
            db,
            cand=cand,
            job=screening,
            stage="screening",
            by=me,
            at=T0 + timedelta(days=1),
        )
        await _stage(db, cand=cand, job=sent, stage="cv_sent", by=me, at=T0)
        await _stage(db, cand=cand, job=closed, stage="new", by=me, at=T0)
        await db.commit()
        cid, board_id = cand.id, board.id
        waiting_id, screening_id = waiting.id, screening.id

    resp = await app_client.get(
        f"/api/pipeline/kanban/{board_id}", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    cards = [
        item
        for column in resp.json()["columns"]
        for item in column["items"]
        if item["candidate_id"] == cid
    ]
    assert len(cards) == 1
    others = cards[0]["other_open_jobs"]
    assert [o["job_id"] for o in others] == [screening_id, waiting_id]
    assert [o["column"] for o in others] == ["screening", "new"]
