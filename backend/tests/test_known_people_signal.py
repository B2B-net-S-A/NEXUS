"""Znani zespołowi wyżej w „Propozycjach z bazy” (badanie 06.10, decyzje 07.10.2026).

Prawdziwy Postgres; Qdrant (podobne rekrutacje) zaślepiony. Baza testowa jest
wspólna, więc każdy test zakłada własnego klienta, rekrutacje i osoby.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import job_proposals as proposals
from app.services import known_people_signal as kps


def test_history_evidence_keeps_ids_stages_and_dates_only():
    clean = proposals.sanitize_evidence(
        {
            "history": {
                "points": 5.04,
                "similar": [
                    {
                        "job_id": 7,
                        "stage": "cv_sent",
                        "at": "2026-07-14T10:00:00",
                        "title": "X",
                    },
                    {"job_id": "8", "stage": "verified"},
                ],
                "recent": {
                    "job_id": 9,
                    "stage": "verified",
                    "at": "2026-09-24",
                    "note": "tajne",
                },
                "rate": 160,
            }
        }
    )
    assert clean == {
        "history": {
            "points": 5.0,
            "similar": [{"job_id": 7, "stage": "cv_sent", "at": "2026-07-14T10:00:00"}],
            "recent": {"job_id": 9, "stage": "verified", "at": "2026-09-24"},
        }
    }
    assert proposals.sanitize_evidence({"history": {"points": 0}}) is None


def test_signal_is_off_by_default():
    from app.core.config import Settings

    assert Settings.model_fields["KNOWN_PEOPLE_BOOST_ENABLED"].default is False
    assert Settings.model_fields["KNOWN_PEOPLE_RECENT_DAYS"].default == 90


async def _world() -> dict:
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Known client {tag}")
        other = Client(name=f"Known other {tag}")
        db.add_all([client, other])
        await db.flush()
        target = Job(
            title=f"Target {tag}", client_id=client.id, status=JobStatus.published
        )
        similar = Job(
            title=f"Similar {tag}", client_id=other.id, status=JobStatus.closed
        )
        elsewhere = Job(
            title=f"Elsewhere {tag}", client_id=other.id, status=JobStatus.published
        )
        old_same = Job(
            title=f"Old same client {tag}", client_id=client.id, status=JobStatus.closed
        )
        people = [
            Candidate(
                name="Znany",
                lastname=f"{i}-{tag}",
                email=f"known-{i}-{tag}@example.com",
            )
            for i in range(4)
        ]
        db.add_all([target, similar, elsewhere, old_same, *people])
        await db.flush()
        a, b, c, d = (p.id for p in people)

        def stage(cid, jid, st, days_ago, **kw):
            return CandidateStage(
                candidate_id=cid,
                job_id=jid,
                stage=st,
                moved_at=now - timedelta(days=days_ago),
                **kw,
            )

        db.add_all(
            [
                # a: zweryfikowany przy podobnej rekrutacji dawno temu
                stage(a, similar.id, PipelineStage.verified, 300),
                # b: zweryfikowany 20 dni temu gdzie indziej
                stage(b, elsewhere.id, PipelineStage.verified, 20),
                # c: przy podobnej, ale ten sam klient go odrzucił po wysłaniu CV
                stage(c, similar.id, PipelineStage.cv_sent, 200),
                stage(c, old_same.id, PipelineStage.cv_sent, 100),
                stage(c, old_same.id, PipelineStage.rejected, 99, ended_by="client"),
                # d: zweryfikowany 200 dni temu gdzie indziej — poza oknem 90 dni
                stage(d, elsewhere.id, PipelineStage.verified, 200),
            ]
        )
        await db.commit()
        return {"target": target.id, "similar": similar.id, "people": (a, b, c, d)}


@pytest.mark.asyncio
async def test_points_reasons_window_and_same_client_rejection(monkeypatch):
    world = await _world()
    monkeypatch.setattr(settings, "KNOWN_PEOPLE_BOOST_ENABLED", True)

    async def _similar(_db, _job_id):
        return {world["similar"]: 0.8}

    monkeypatch.setattr(kps, "_similar_jobs", _similar)
    a, b, c, d = world["people"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["target"])
        known = await kps.known_people_for_job(db, job)

    assert known[a].points == pytest.approx(2.5 * 0.8)
    assert known[a].evidence()["similar"][0]["job_id"] == world["similar"]
    assert known[b].points == pytest.approx(3.0)
    assert known[b].recent["stage"] == "verified"
    assert c not in known, "odrzucony przez tego samego klienta nie dostaje punktów"
    assert d not in known, "weryfikacja sprzed 90 dni to nie „niedawno”"


@pytest.mark.asyncio
async def test_flag_off_means_no_signal():
    world = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["target"])
        assert await kps.known_people_for_job(db, job) == {}


@pytest.mark.asyncio
async def test_inbox_orders_by_score_plus_history_points_and_keeps_the_score():
    world = await _world()
    a, b, _, _ = world["people"]
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db,
            world["target"],
            [
                {"candidate_id": a, "score": 75},
                {
                    "candidate_id": b,
                    "score": 71,
                    "evidence": {"history": {"points": 6.0}},
                },
            ],
            "full_base",
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows, total = await proposals.list_for_job(db, job_id=world["target"], limit=10)
    assert total == 2
    assert [r.candidate_id for r in rows] == [b, a]
    assert rows[0].score == 71
