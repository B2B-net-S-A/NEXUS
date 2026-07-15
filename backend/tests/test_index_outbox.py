"""Tests for the indexing outbox state machine (plan PR5).

Exercises enqueue flag-gating, the wrapper's flag-off inline fallback, and the
worker's claim/process/compare-and-set/dead-letter logic with an injected fake
reindex fn (no Voyage/Qdrant). DB-backed (CI Postgres + migration 0171).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.index_outbox import IndexOutboxEvent
from app.services import index_outbox_service as outbox

# entity ids well above any real row so cleanup is safe.
BASE = 990000


async def _cleanup() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM match_index_outbox WHERE entity_id >= :b"), {"b": BASE}
        )
        await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _clean():
    await _cleanup()
    yield
    await _cleanup()


@pytest.mark.asyncio
async def test_enqueue_noop_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "AI_INDEX_OUTBOX_ENABLED", False)
    async with AsyncSessionLocal() as db:
        await outbox.enqueue(
            db,
            entity_type="candidate",
            entity_id=BASE + 1,
            revision=1,
            desired_hash="h",
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        n = await db.scalar(
            text("SELECT count(*) FROM match_index_outbox WHERE entity_id = :e"),
            {"e": BASE + 1},
        )
    assert n == 0


@pytest.mark.asyncio
async def test_wrapper_flag_off_embeds_inline(monkeypatch):
    monkeypatch.setattr(settings, "AI_INDEX_OUTBOX_ENABLED", False)
    called = {}

    async def _fake_embed(cid, db):
        called["id"] = cid
        return True

    monkeypatch.setattr(
        "app.services.embedding_service.embed_candidate", _fake_embed
    )
    async with AsyncSessionLocal() as db:
        ok = await outbox.schedule_or_embed_candidate(BASE + 2, db)
    assert ok is True
    assert called["id"] == BASE + 2
    # No outbox row created on the inline path.
    async with AsyncSessionLocal() as db:
        n = await db.scalar(
            text("SELECT count(*) FROM match_index_outbox WHERE entity_id = :e"),
            {"e": BASE + 2},
        )
    assert n == 0


async def _insert_event(**kw) -> int:
    defaults = dict(
        entity_type="candidate",
        entity_id=BASE + 10,
        entity_revision=100,
        desired_hash="deadbeef",
        operation="upsert",
        status="processing",
        attempts=0,
    )
    defaults.update(kw)
    async with AsyncSessionLocal() as db:
        ev = IndexOutboxEvent(**defaults)
        db.add(ev)
        await db.commit()
        await db.refresh(ev)
        return ev.id


@pytest.mark.asyncio
async def test_process_success_marks_done_and_records_hash():
    ev_id = await _insert_event(entity_id=BASE + 11, desired_hash="abc123")

    async def _ok(_t, _i, _op):
        return True

    async with AsyncSessionLocal() as db:
        ev = await db.get(IndexOutboxEvent, ev_id)
        status = await outbox.process_event(db, ev, reindex_fn=_ok)
        await db.commit()
    assert status == "done"
    async with AsyncSessionLocal() as db:
        ev = await db.get(IndexOutboxEvent, ev_id)
        assert ev.status == "done"
        assert ev.indexed_hash == "abc123"
        assert ev.indexed_revision == 100


@pytest.mark.asyncio
async def test_process_failure_then_dead_after_max(monkeypatch):
    monkeypatch.setattr(settings, "AI_INDEX_MAX_ATTEMPTS", 5)

    async def _boom(_t, _i, _op):
        raise RuntimeError("qdrant down")

    # Fresh event → first failure is 'failed'.
    ev_id = await _insert_event(entity_id=BASE + 12, attempts=0)
    async with AsyncSessionLocal() as db:
        ev = await db.get(IndexOutboxEvent, ev_id)
        status = await outbox.process_event(db, ev, reindex_fn=_boom)
        await db.commit()
    assert status == "failed"

    # Already at 4 attempts → next failure tips into 'dead'.
    ev_id2 = await _insert_event(entity_id=BASE + 13, attempts=4)
    async with AsyncSessionLocal() as db:
        ev = await db.get(IndexOutboxEvent, ev_id2)
        status = await outbox.process_event(db, ev, reindex_fn=_boom)
        await db.commit()
    assert status == "dead"


@pytest.mark.asyncio
async def test_superseded_event_skips_reindex():
    # A newer revision already indexed done for the same entity.
    await _insert_event(
        entity_id=BASE + 14,
        status="done",
        entity_revision=200,
        indexed_revision=200,
    )
    stale_id = await _insert_event(
        entity_id=BASE + 14, status="processing", entity_revision=100
    )
    calls = {"n": 0}

    async def _spy(_t, _i, _op):
        calls["n"] += 1
        return True

    async with AsyncSessionLocal() as db:
        ev = await db.get(IndexOutboxEvent, stale_id)
        status = await outbox.process_event(db, ev, reindex_fn=_spy)
        await db.commit()
    assert status == "done"
    assert calls["n"] == 0  # compare-and-set skipped the reindex


@pytest.mark.asyncio
async def test_drain_once_processes_pending():
    await _insert_event(entity_id=BASE + 15, status="pending")
    await _insert_event(entity_id=BASE + 16, status="pending")

    async def _ok(_t, _i, _op):
        return True

    async with AsyncSessionLocal() as db:
        counts = await outbox.drain_once(db, batch=10, reindex_fn=_ok)
    assert counts.get("done", 0) >= 2
