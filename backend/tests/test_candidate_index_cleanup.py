"""Admin index cleanup — orphan candidate points and jobs without a vector.

Real Postgres for everything the database decides (which rows exist, what the
outbox holds); Qdrant is a fake that only knows point ids. The test database is
shared and never cleaned, so assertions are about THIS test's ids, never about
global counts.
"""

import typing
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.index_outbox import IndexOutboxEvent
from app.models.job import Job
from app.services import index_cleanup
from app.services import index_outbox_service as outbox


class _PointsOnly:
    """Qdrant scroll over ids only, paged like the real client."""

    def __init__(self, collections: dict[str, list]):
        self.collections = collections
        self.scrolls: list[dict] = []

    def scroll(self, *, collection_name, limit, offset, with_payload, with_vectors):
        self.scrolls.append(
            {"payload": with_payload, "vectors": with_vectors, "offset": offset}
        )
        ids = self.collections[collection_name]
        start = offset or 0
        page = [SimpleNamespace(id=pid) for pid in ids[start : start + limit]]
        following = start + limit
        return page, following if following < len(ids) else None

    def close(self):
        pass


async def _seed(db):
    unique = uuid.uuid4().hex[:10]
    client = Client(name=f"Index cleanup {unique}")
    db.add(client)
    await db.flush()
    alive = [
        Candidate(name="Index", lastname=f"Cleanup {unique}-{i}") for i in range(2)
    ]
    stamped_with_point = Job(title="Python developer", client_id=client.id)
    unstamped_with_point = Job(title="Java developer", client_id=client.id)
    stamped_without_point = Job(title="Go developer", client_id=client.id)
    nothing_to_embed = Job(title="", client_id=client.id)
    db.add_all(
        [
            *alive,
            stamped_with_point,
            unstamped_with_point,
            stamped_without_point,
            nothing_to_embed,
        ]
    )
    await db.flush()
    stamped_with_point.embedding_id = str(stamped_with_point.id)
    stamped_without_point.embedding_id = str(stamped_without_point.id)
    await db.flush()
    top = await db.scalar(select(func.max(Candidate.id)))
    orphans = [top + 10_000_001, top + 10_000_002]
    return SimpleNamespace(
        alive=[c.id for c in alive],
        orphans=orphans,
        stamped_with_point=stamped_with_point.id,
        unstamped_with_point=unstamped_with_point.id,
        stamped_without_point=stamped_without_point.id,
        nothing_to_embed=nothing_to_embed.id,
    )


def _install(monkeypatch, seeded, *, page: int = 3):
    fake = _PointsOnly(
        {
            "cands": [*seeded.alive, *seeded.orphans, "4b1f0c3e-uuid-point"],
            "jobs": [seeded.stamped_with_point, seeded.unstamped_with_point],
        }
    )

    async def run_inline(fn):
        return fn()

    monkeypatch.setattr(index_cleanup, "_SCROLL_PAGE", page)
    monkeypatch.setattr(index_cleanup.embeddings, "_get_qdrant_client", lambda: fake)
    monkeypatch.setattr(index_cleanup.embeddings, "_run_qdrant", run_inline)
    monkeypatch.setattr(
        index_cleanup.embeddings, "candidates_collection_name", lambda: "cands"
    )
    monkeypatch.setattr(
        index_cleanup.embeddings, "jobs_collection_name", lambda: "jobs"
    )
    return fake


async def _events(db, entity_type, ids):
    """Plain rows — ORM objects would not survive the test's rollback."""
    rows = (
        await db.execute(
            select(
                IndexOutboxEvent.entity_id,
                IndexOutboxEvent.operation,
                IndexOutboxEvent.desired_hash,
                IndexOutboxEvent.entity_revision,
            ).where(
                IndexOutboxEvent.entity_type == entity_type,
                IndexOutboxEvent.entity_id.in_(ids),
            )
        )
    ).all()
    return [
        SimpleNamespace(
            entity_id=entity_id,
            operation=operation,
            desired_hash=desired_hash,
            entity_revision=revision,
        )
        for entity_id, operation, desired_hash, revision in rows
    ]


@pytest.mark.asyncio
async def test_plan_lists_orphans_and_jobs_missing_a_vector_without_writing(
    monkeypatch,
):
    async with AsyncSessionLocal() as db:
        try:
            seeded = await _seed(db)
            fake = _install(monkeypatch, seeded)
            before = await db.scalar(select(func.count(IndexOutboxEvent.id)))
            plan = await index_cleanup.build_plan(db)
            after = await db.scalar(select(func.count(IndexOutboxEvent.id)))
        finally:
            await db.rollback()

    assert before == after, "the plan is read-only"
    orphans = set(plan["orphan_candidate_point_ids"])
    assert set(seeded.orphans) <= orphans
    assert not set(seeded.alive) & orphans, "a live candidate is never an orphan"
    assert plan["unaddressable_point_ids"] == {"candidates": 1, "jobs": 0}

    missing = set(plan["jobs_missing_point"])
    unstamped = set(plan["jobs_unstamped"])
    embed = set(plan["jobs_to_embed"])
    assert seeded.stamped_without_point in missing & embed
    assert seeded.unstamped_with_point in unstamped & embed
    assert seeded.stamped_with_point not in missing | unstamped | embed
    assert seeded.nothing_to_embed in set(plan["jobs_without_text"])
    assert seeded.nothing_to_embed not in embed
    assert len(plan["fingerprint"]) == 64
    # Ids only: no payload, no vectors, every page followed.
    assert {(s["payload"], s["vectors"]) for s in fake.scrolls} == {(False, False)}
    assert any(s["offset"] for s in fake.scrolls)


@pytest.mark.asyncio
async def test_approval_queues_exactly_the_reviewed_plan_once(monkeypatch):
    monkeypatch.setattr(index_cleanup, "worker_enabled", lambda: False)
    async with AsyncSessionLocal() as db:
        try:
            seeded = await _seed(db)
            _install(monkeypatch, seeded)
            plan = await index_cleanup.build_plan(db)
            counts = plan["counts"]
            first = await index_cleanup.enqueue_reviewed_cleanup(
                db,
                expected_fingerprint=plan["fingerprint"],
                orphan_count=counts["orphan_candidate_points"],
                job_count=counts["jobs_to_embed"],
            )
            my_jobs = [
                seeded.stamped_without_point,
                seeded.unstamped_with_point,
                seeded.stamped_with_point,
                seeded.nothing_to_embed,
            ]
            candidate_events = await _events(
                db, "candidate", [*seeded.orphans, *seeded.alive]
            )
            job_events = await _events(db, "job", my_jobs)
            again = await index_cleanup.enqueue_reviewed_cleanup(
                db,
                expected_fingerprint=plan["fingerprint"],
                orphan_count=counts["orphan_candidate_points"],
                job_count=counts["jobs_to_embed"],
            )
            repeated = len(
                await _events(db, "candidate", [*seeded.orphans, *seeded.alive])
            ) + len(await _events(db, "job", my_jobs))
        finally:
            await db.rollback()

    assert {e.entity_id for e in candidate_events} == set(seeded.orphans), (
        "deletes only for orphan points — never for a live candidate"
    )
    assert {e.operation for e in candidate_events} == {"delete"}
    assert {e.desired_hash for e in candidate_events} == {outbox.ORPHAN_POINT_DELETE}
    assert all(e.entity_revision > 0 for e in candidate_events)
    assert {e.operation for e in job_events} == {"upsert"}
    assert {e.entity_id for e in job_events} == {
        seeded.stamped_without_point,
        seeded.unstamped_with_point,
    }
    assert first["queued_orphan_deletes"] == 2
    assert first["worker_enabled"] is False
    # Repeating the approval while the worker is off queues nothing new.
    assert again["queued_orphan_deletes"] == 0
    assert again["queued_job_embeds"] == 0
    assert again["orphan_deletes_already_open"] == 2
    assert repeated == len(candidate_events) + len(job_events)


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["fingerprint", "orphan_count", "job_count"])
async def test_changed_plan_or_counts_queue_nothing(monkeypatch, tamper):
    async with AsyncSessionLocal() as db:
        try:
            seeded = await _seed(db)
            _install(monkeypatch, seeded)
            plan = await index_cleanup.build_plan(db)
            approval = {
                "expected_fingerprint": plan["fingerprint"],
                "orphan_count": plan["counts"]["orphan_candidate_points"],
                "job_count": plan["counts"]["jobs_to_embed"],
            }
            if tamper == "fingerprint":
                approval["expected_fingerprint"] = "0" * 64
            else:
                approval[tamper] += 1
            with pytest.raises(index_cleanup.CleanupPlanChanged):
                await index_cleanup.enqueue_reviewed_cleanup(db, **approval)
            events = await _events(db, "candidate", seeded.orphans)
        finally:
            await db.rollback()
    assert events == []


@pytest.mark.asyncio
async def test_a_row_that_reappears_blocks_the_whole_approval(monkeypatch):
    """Re-read inside the enqueue transaction, after the plan's own read."""
    async with AsyncSessionLocal() as db:
        try:
            seeded = await _seed(db)
            _install(monkeypatch, seeded)
            plan = await index_cleanup.build_plan(db)
            real_build = index_cleanup.build_plan

            async def plan_then_row_returns(session):
                rebuilt = await real_build(session)
                session.add(
                    Candidate(id=seeded.orphans[0], name="Back", lastname="Again")
                )
                await session.flush()
                return rebuilt

            monkeypatch.setattr(index_cleanup, "build_plan", plan_then_row_returns)
            with pytest.raises(index_cleanup.CleanupPlanChanged):
                await index_cleanup.enqueue_reviewed_cleanup(
                    db,
                    expected_fingerprint=plan["fingerprint"],
                    orphan_count=plan["counts"]["orphan_candidate_points"],
                    job_count=plan["counts"]["jobs_to_embed"],
                )
            events = await _events(db, "candidate", seeded.orphans)
        finally:
            await db.rollback()
    assert [e for e in events if e.operation == "delete"] == []


@pytest.mark.asyncio
async def test_unreadable_index_is_unavailable_not_an_empty_plan(monkeypatch):
    async def outage(_fn):
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(index_cleanup.embeddings, "_run_qdrant", outage)
    async with AsyncSessionLocal() as db:
        try:
            with pytest.raises(index_cleanup.IndexUnavailable):
                await index_cleanup.build_plan(db)
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_worker_never_deletes_the_point_of_an_existing_candidate():
    """Processing-time re-check — the queue can wait days for the worker."""
    reindex = AsyncMock(return_value=True)
    async with AsyncSessionLocal() as db:
        try:
            live = Candidate(name="Worker", lastname=f"Guard {uuid.uuid4().hex[:8]}")
            db.add(live)
            await db.flush()
            gone_id = (await db.scalar(select(func.max(Candidate.id)))) + 10_000_003

            def event(entity_id, desired_hash):
                return IndexOutboxEvent(
                    entity_type="candidate",
                    entity_id=entity_id,
                    entity_revision=1,
                    desired_hash=desired_hash,
                    operation="delete",
                    status="processing",
                )

            orphan_now_alive = event(live.id, outbox.ORPHAN_POINT_DELETE)
            true_orphan = event(gone_id, outbox.ORPHAN_POINT_DELETE)
            quarantine = event(live.id, "")
            db.add_all([orphan_now_alive, true_orphan, quarantine])
            await db.flush()

            statuses = [
                await outbox.process_event(db, ev, reindex_fn=reindex)
                for ev in (orphan_now_alive, true_orphan, quarantine)
            ]
            withdrawn_note = orphan_now_alive.last_error
        finally:
            await db.rollback()

    assert statuses == ["done", "done", "done"]
    assert "withdrawn" in withdrawn_note
    # The live candidate's orphan delete never reached the index; the genuine
    # orphan and the quarantine delete (row stays, vector goes) both did.
    assert [c.args for c in reindex.await_args_list] == [
        ("candidate", gone_id, "delete"),
        ("candidate", live.id, "delete"),
    ]


def test_routes_are_admin_only():
    from app.api import admin_index_cleanup as api

    for handler in (api.index_cleanup_plan, api.index_cleanup_enqueue):
        hints = typing.get_type_hints(handler, include_extras=True)
        (dependency,) = [
            meta.dependency
            for meta in typing.get_args(hints["_admin"])[1:]
            if hasattr(meta, "dependency")
        ]
        assert "require_roles" in dependency.__qualname__
