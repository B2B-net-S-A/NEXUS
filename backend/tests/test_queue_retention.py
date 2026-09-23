"""Audyt 22.09 r2 (DATA-03/04/PROD-10): retencja kolejek i przeglądów auto.

Realny Postgres. Baza testowa jest wspólna, więc asercje dotyczą tylko
wierszy założonych w teście.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_search_run import CandidateSearchRun
from app.models.client import Client
from app.models.job import Job
from app.models.user import User, UserRole
from app.tasks import candidate_search_retention as search_retention
from app.tasks import queue_retention

NOW = datetime.now(timezone.utc)
OLD = NOW - timedelta(days=60)


async def _world(db):
    tag = uuid.uuid4().hex[:8]
    client = Client(name=f"QR {tag}")
    db.add(client)
    await db.flush()
    job = Job(title=f"QR job {tag}", client_id=client.id)
    cand = Candidate(name="QR", lastname=tag, email=f"qr-{tag}@example.com")
    db.add_all([job, cand])
    await db.flush()
    return client, job, cand


async def _ids(db, table: str, ids: list[int]) -> set[int]:
    rows = await db.execute(
        text(f"SELECT id FROM {table} WHERE id = ANY(:ids)"), {"ids": ids}
    )
    return {r[0] for r in rows}


@pytest.mark.asyncio
async def test_prune_keeps_decisions_in_flight_events_and_latest_indexed_hash():
    async with AsyncSessionLocal() as db:
        client, job, cand = await _world(db)
        ins_log = text(
            "INSERT INTO candidate_auto_match_log (candidate_id, job_id, "
            "profile_revision, trigger, decision, run_id, created_at) "
            "VALUES (:c, :j, :r, 'test', :d, 'qr-test', :t) "
            "RETURNING id"
        )
        log = {}
        for name, decision, when in (
            ("old_below", "below_threshold", OLD),
            ("old_added", "added", OLD),
            ("old_proposed", "proposed", OLD),
            ("new_below", "below_threshold", NOW),
        ):
            log[name] = (
                await db.execute(
                    ins_log,
                    {"c": cand.id, "j": job.id, "r": name, "d": decision, "t": when},
                )
            ).scalar_one()
        ins_mo = text(
            "INSERT INTO candidate_match_outbox (job_id, trigger, status, created_at) "
            "VALUES (:j, 'test', :s, :t) RETURNING id"
        )
        mo = {
            "old_done": (
                await db.execute(ins_mo, {"j": job.id, "s": "done", "t": OLD})
            ).scalar_one(),
            "old_pending": (
                await db.execute(ins_mo, {"j": job.id, "s": "pending", "t": OLD})
            ).scalar_one(),
        }
        ins_io = text(
            "INSERT INTO match_index_outbox (entity_type, entity_id, entity_revision, "
            "desired_hash, operation, status, indexed_hash, attempts, created_at, "
            "updated_at) VALUES ('candidate', :e, :rev, 'h', 'upsert', :s, :ih, 0, "
            ":t, :t) RETURNING id"
        )
        io = {}
        for name, rev, status, ih in (
            ("old_done_1", 1, "done", "h1"),
            ("old_done_2", 2, "done", "h2"),
            ("old_dead", 3, "dead", None),
        ):
            io[name] = (
                await db.execute(
                    ins_io,
                    {"e": cand.id, "rev": rev, "s": status, "ih": ih, "t": OLD},
                )
            ).scalar_one()
        await db.commit()

    try:
        await queue_retention.prune_once()
        async with AsyncSessionLocal() as db:
            assert await _ids(db, "candidate_auto_match_log", list(log.values())) == {
                log["old_added"],
                log["old_proposed"],
                log["new_below"],
            }
            assert await _ids(db, "candidate_match_outbox", list(mo.values())) == {
                mo["old_pending"]
            }
            # Najnowszy `done` z haszem zostaje — to on mówi reconcilerowi,
            # co jest w indeksie. `dead` nie jest `done`, zostaje.
            assert await _ids(db, "match_index_outbox", list(io.values())) == {
                io["old_done_2"],
                io["old_dead"],
            }
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM match_index_outbox WHERE id = ANY(:i)"),
                {"i": list(io.values())},
            )
            await db.execute(
                text("DELETE FROM candidate_match_outbox WHERE id = ANY(:i)"),
                {"i": list(mo.values())},
            )
            await db.commit()


def test_outbox_retention_never_drops_below_the_auto_review_event_window(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "QUEUE_OUTBOX_RETENTION_DAYS", 3)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_EVENT_LOOKBACK_DAYS", 14)
    assert queue_retention._outbox_days() == 15


def test_defaults():
    from app.core.config import Settings

    fields = Settings.model_fields
    assert fields["AUTOMATION_LOG_RETENTION_DAYS"].default == 30
    assert fields["AUTO_FULL_REVIEW_RETENTION_DAYS"].default == 2
    assert fields["QUEUE_RETENTION_ENABLED"].default is True


@pytest.mark.asyncio
async def test_automatic_reviews_expire_after_two_days_manual_after_seven():
    async with AsyncSessionLocal() as db:
        try:
            tag = uuid.uuid4().hex
            user = User(
                name="QR",
                email=f"qr-{tag}@example.com",
                password_hash="unused",
                role=UserRole.admin,
                is_active=True,
            )
            client = Client(name=f"QR search {tag}")
            db.add_all([user, client])
            await db.flush()
            three_days = NOW - timedelta(days=3)

            def _run(origin):
                return CandidateSearchRun(
                    id=str(uuid.uuid4()),
                    created_by=user.id,
                    client_id=client.id,
                    job_id=None,
                    state="complete",
                    request_fingerprint=uuid.uuid4().hex * 2,
                    request_context={},
                    version_trace={"origin": origin} if origin else {},
                    population_size=0,
                    metrics={},
                    completed_at=three_days,
                    created_at=three_days,
                )

            auto_run, manual_run, older_manual = _run("auto"), _run(None), _run(None)
            older_manual.completed_at = three_days - timedelta(hours=1)
            db.add_all([auto_run, manual_run, older_manual])
            await db.flush()
            expired = set(
                await search_retention.expired_run_ids(
                    db,
                    cutoff=NOW - timedelta(days=7),
                    limit=10_000,
                    auto_cutoff=NOW - timedelta(days=2),
                )
            )
            assert auto_run.id in expired
            assert manual_run.id not in expired
            assert older_manual.id not in expired
        finally:
            await db.rollback()
