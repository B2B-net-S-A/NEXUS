"""„Moi ludzie" × nowa rekrutacja — dzwonek i zakładka „Do tej rekrutacji".

Kontrakty:

- jeden dzwonek na (odbiorca, rekrutacja), z nazwiskami osób ponad progiem;
- osoba już w tej rekrutacji nie jest polecana;
- wynik niezmierzony (``None``) nie trafia do powiadomienia i nie jest zerem;
- ``hidden`` (globalna blacklista, duplikat) odpada, ostrzeżenie zostaje;
- ponowne zdarzenie tej samej rekrutacji nie budzi rekrutera drugi raz;
- awaria Qdranta w panelu to ``degraded``, nie „nikt nie pasuje";
- błąd tego kroku w workerze nie cofa auto-matcha, awaria Qdranta ponawia.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from tests.test_my_people import T0, _candidate, _job, _stage, _user

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


def _fake_scores(mapping, *, hidden=(), warn=None):
    from app.services.my_people_matching import ScoredPerson

    async def fake(db, *, job, candidate_ids, profile_user_id, pool_limit):
        out = []
        for cid in candidate_ids:
            if cid not in mapping:
                continue
            out.append(
                ScoredPerson(
                    candidate_id=cid,
                    score=mapping[cid],
                    measurement="measured"
                    if mapping[cid] is not None
                    else "missing_vector",
                    eligibility=(warn or {}).get(cid),
                    hidden=cid in hidden,
                )
            )
        return out

    return fake


async def _owned(db, owner, job_from):
    cand = await _candidate(db)
    await _stage(db, cand=cand, job=job_from, stage="verified", by=owner, at=T0)
    await _stage(
        db,
        cand=cand,
        job=job_from,
        stage="cv_sent",
        by=owner,
        at=T0 + timedelta(days=1),
    )
    return cand


@needs_db
@pytest.mark.asyncio
async def test_one_bell_per_recipient_with_the_people_above_threshold(monkeypatch):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.my_people import MyPeopleJobMatch
    from app.models.notification import Notification, NotificationType
    from app.services import my_people_matching as mpm

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        old_job = await _job(db, status="closed")
        new_job = await _job(db)
        strong, weak, unmeasured, banned, already = [
            await _owned(db, me, old_job) for _ in range(5)
        ]
        await _stage(
            db, cand=already, job=new_job, stage="new", by=me, at=T0 + timedelta(days=9)
        )
        await db.commit()

        monkeypatch.setattr(
            mpm,
            "score_people_for_job",
            _fake_scores(
                {
                    strong.id: 88,
                    weak.id: 51,
                    unmeasured.id: None,
                    banned.id: 99,
                    already.id: 97,
                },
                hidden={banned.id},
            ),
        )
        result = await mpm.run_for_job(db, new_job)
        await db.commit()

        matches = (
            await db.scalars(
                select(MyPeopleJobMatch).where(
                    MyPeopleJobMatch.user_id == me.id,
                    MyPeopleJobMatch.job_id == new_job.id,
                )
            )
        ).all()
        assert {m.candidate_id for m in matches} == {strong.id}
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == me.id,
                    Notification.notification_type == NotificationType.my_people_match,
                )
            )
        ).all()
        assert len(bells) == 1
        assert bells[0].link == f"/jobs/{new_job.id}?people=1"
        assert strong.lastname in bells[0].message
        assert weak.lastname not in bells[0].message
        assert result["notified"] >= 1

        # To samo zdarzenie drugi raz (istotna zmiana rekrutacji) — bez dzwonka.
        again = await mpm.run_for_job(db, new_job)
        await db.commit()
        assert again.get("stored", 0) == 0
        bells_after = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == me.id,
                    Notification.notification_type == NotificationType.my_people_match,
                )
            )
        ).all()
        assert len(bells_after) == 1


@needs_db
@pytest.mark.asyncio
async def test_draft_job_sends_nothing(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.services import my_people_matching as mpm

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        old_job, draft = await _job(db, status="closed"), await _job(db, status="draft")
        await _owned(db, me, old_job)
        await db.commit()
        called = False

        async def boom(*a, **kw):
            nonlocal called
            called = True
            return []

        monkeypatch.setattr(mpm, "score_people_for_job", boom)
        assert (await mpm.run_for_job(db, draft)) == {"skipped": "job_not_published"}
        assert called is False


@needs_db
@pytest.mark.asyncio
async def test_panel_for_job_marks_degraded_when_vectors_are_down(
    app_client, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.services import auto_match_service as ams
    from app.services import my_people_matching as mpm

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        old_job, new_job = await _job(db, status="closed"), await _job(db)
        cand = await _owned(db, me, old_job)
        await db.commit()
        uid, job_id, cid = me.id, new_job.id, cand.id

    async def down(*a, **kw):
        raise ams.AutoMatchUnavailable("vector store unavailable")

    monkeypatch.setattr(mpm, "scoped_similarity", down)
    headers = {
        "Authorization": f"Bearer {create_access_token(subject=uid, role='recruiter')}"
    }
    resp = await app_client.get(f"/api/my-people/for-job/{job_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is True
    [row] = [r for r in body["rows"] if r["candidate_id"] == cid]
    assert row["score"] is None
    assert row["measurement"] == "unavailable"


@needs_db
@pytest.mark.asyncio
async def test_panel_for_job_scores_and_hides_ineligible(app_client, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.services import my_people_matching as mpm

    async with AsyncSessionLocal() as db:
        me = await _user(db)
        old_job, new_job = await _job(db, status="closed"), await _job(db)
        good, hidden, in_job = [await _owned(db, me, old_job) for _ in range(3)]
        await _stage(
            db, cand=in_job, job=new_job, stage="new", by=me, at=T0 + timedelta(days=4)
        )
        await db.commit()
        uid, job_id = me.id, new_job.id
        good_id, hidden_id, in_job_id = good.id, hidden.id, in_job.id

    warn = {
        good_id: {
            "reason_code": "client_nda",
            "reason": "NDA",
            "assignment_allowed": True,
        }
    }
    monkeypatch.setattr(
        mpm,
        "score_people_for_job",
        _fake_scores({good_id: 77, hidden_id: 90}, hidden={hidden_id}, warn=warn),
    )
    headers = {
        "Authorization": f"Bearer {create_access_token(subject=uid, role='recruiter')}"
    }
    body = (
        await app_client.get(f"/api/my-people/for-job/{job_id}", headers=headers)
    ).json()
    ids = {r["candidate_id"] for r in body["rows"]}
    assert good_id in ids
    assert hidden_id not in ids
    assert in_job_id not in ids
    assert body["in_job_count"] >= 1
    [row] = [r for r in body["rows"] if r["candidate_id"] == good_id]
    assert row["score"] == 77
    assert row["eligibility"]["reason_code"] == "client_nda"


@pytest.mark.asyncio
async def test_worker_step_isolates_failures_but_propagates_vector_outage(monkeypatch):
    from types import SimpleNamespace

    from app.services import auto_match_service as ams
    from app.services import my_people_matching as mpm
    from app.tasks import candidate_auto_match as worker

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Db:
        async def get(self, model, pk):
            return SimpleNamespace(id=pk)

        def begin_nested(self):
            return _Nested()

    async def crash(db, job):
        raise RuntimeError("boom")

    monkeypatch.setattr(mpm, "run_for_job", crash)
    out = await worker._run_my_people(_Db(), SimpleNamespace(job_id=5))
    assert out == {"error": "RuntimeError"}

    async def outage(db, job):
        raise ams.AutoMatchUnavailable("down")

    monkeypatch.setattr(mpm, "run_for_job", outage)
    with pytest.raises(ams.AutoMatchUnavailable):
        await worker._run_my_people(_Db(), SimpleNamespace(job_id=5))


def test_notification_type_is_routed_to_a_section():
    from app.models.notification import NotificationType
    from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE

    assert NotificationType.my_people_match in NOTIFICATION_SECTION_BY_TYPE
