"""The reconciler removes the need for writers to remember.

Three Traffit phases change fields that feed the embedding text and record no
reindex intent. Patching those three fixes three; the class of bug is "every
writer must remember", and only something that asks nobody closes it.

Uses the real DB (outbox rows + real entities), like `test_index_outbox.py`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.index_outbox import IndexOutboxEvent
from app.services import index_drift_reconciler as rec
from app.services import index_outbox_service as outbox


async def _fresh_candidate(db) -> Candidate:
    c = Candidate(
        name="Rec",
        lastname=f"Onciler-{uuid.uuid4().hex[:8]}",
        email=f"rec-{uuid.uuid4().hex[:10]}@example.com",
    )
    db.add(c)
    await db.flush()
    return c


async def _record_indexed(db, candidate: Candidate, *, hash_value: str) -> None:
    """Pretend the worker successfully indexed this entity with `hash_value`."""
    db.add(
        IndexOutboxEvent(
            entity_type=outbox.CANDIDATE,
            entity_id=candidate.id,
            entity_revision=1,
            desired_hash=hash_value,
            indexed_hash=hash_value,
            indexed_revision=1,
            operation="upsert",
            status="done",
        )
    )
    await db.flush()


async def _pending_ids(db, candidate_id: int) -> list[int]:
    # `record_bulk_reindex` uses `db.add()` and leaves committing to the caller,
    # so the rows are pending in the session until flushed.
    await db.flush()
    rows = await db.execute(
        text(
            "SELECT id FROM match_index_outbox WHERE entity_type='candidate' "
            "AND entity_id=:cid AND status='pending'"
        ),
        {"cid": candidate_id},
    )
    return [r[0] for r in rows.all()]


@pytest.mark.asyncio
async def test_content_change_without_any_reindex_intent_is_detected():
    """The whole point: nobody told the index anything, and it still notices."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)
        current = outbox.desired_state(outbox.CANDIDATE, cand).desired_hash
        await _record_indexed(db, cand, hash_value=current)

        # A writer changes a field that feeds the embedding text and — exactly
        # like the three Traffit phases — records nothing.
        cand.ai_summary = "Senior backend engineer, 8 lat w fintechu."
        await db.flush()

        result = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=cand.id - 1, batch=1
        )
        assert result.drifted == 1, "content changed but no reindex was enqueued"
        assert await _pending_ids(db, cand.id)
        await db.rollback()


@pytest.mark.asyncio
async def test_unchanged_entity_is_not_re_enqueued():
    """Otherwise every pass would re-embed the entire base — the reconciler
    would become the most expensive no-op in the system."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)
        current = outbox.desired_state(outbox.CANDIDATE, cand).desired_hash
        await _record_indexed(db, cand, hash_value=current)

        result = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=cand.id - 1, batch=1
        )
        assert result.drifted == 0
        assert not await _pending_ids(db, cand.id)
        await db.rollback()


@pytest.mark.asyncio
async def test_entity_the_outbox_never_saw_is_skipped_not_enqueued():
    """Those are the initial-population gap (`reembed --only-missing`), not
    drift. Counting them as drift would enqueue tens of thousands of re-embeds
    on the first tick and re-bill the entire import."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)  # no outbox history at all

        result = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=cand.id - 1, batch=1
        )
        assert result.unseen == 1
        assert result.drifted == 0
        assert not await _pending_ids(db, cand.id)
        await db.rollback()


@pytest.mark.asyncio
async def test_unseen_entities_can_be_opted_in():
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)

        result = await rec.reconcile_once(
            db,
            entity_type=outbox.CANDIDATE,
            cursor=cand.id - 1,
            batch=1,
            include_unseen=True,
        )
        assert result.unseen == 1
        assert await _pending_ids(db, cand.id)
        await db.rollback()


@pytest.mark.asyncio
async def test_a_pending_event_does_not_count_as_indexed():
    """A pending or failed row describes an INTENT, not the state of the index.
    Reading it as "already handled" would let a stale vector sit forever while
    the reconciler reported everything in order."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)
        db.add(
            IndexOutboxEvent(
                entity_type=outbox.CANDIDATE,
                entity_id=cand.id,
                entity_revision=1,
                desired_hash=outbox.desired_state(outbox.CANDIDATE, cand).desired_hash,
                operation="upsert",
                status="pending",
            )
        )
        await db.flush()

        result = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=cand.id - 1, batch=1
        )
        assert result.unseen == 1, "a pending event was mistaken for a done one"
        await db.rollback()


@pytest.mark.asyncio
async def test_cursor_walks_forward_and_reports_the_end_of_the_table():
    async with AsyncSessionLocal() as db:
        first = await _fresh_candidate(db)
        second = await _fresh_candidate(db)

        page = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=first.id - 1, batch=1
        )
        assert page.scanned == 1
        assert page.next_cursor == first.id

        page2 = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=page.next_cursor, batch=1
        )
        assert page2.next_cursor == second.id

        # Past the last row, but inside INTEGER range — candidates.id is int32,
        # so a sentinel like 10**12 fails in the driver rather than in the query.
        end = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=2**31 - 1, batch=1
        )
        assert end.next_cursor is None and end.scanned == 0
        await db.rollback()


def test_reconciler_ships_disabled():
    """It must not start before the provider health probes exist: with
    AI_INDEX_MAX_ATTEMPTS=5 a Voyage outage plus a reconciler feeding the
    worker burns the backlog into dead rows behind a green healthcheck."""
    from app.core.config import Settings

    assert Settings.model_fields["AI_INDEX_RECONCILER_ENABLED"].default is False
