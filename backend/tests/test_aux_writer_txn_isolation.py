"""Auxiliary writers must not own the caller's request transaction (M3-TX-01).

Three best-effort side-effect writers used to ``commit()``/``rollback()`` the
CALLER's session (the request session from ``Depends(get_db)``):

* ``match_score_cache`` — write-through score cache
* ``match_telemetry_service`` — append-only impression/outcome telemetry
* ``index_outbox_service`` — durable reindex enqueue

A transient failure in any of them could therefore COMMIT or ROLLBACK the
unrelated business operation. Each now performs its write on a DEDICATED
``AsyncSessionLocal`` so a cache/telemetry/enqueue failure can never touch the
caller's transaction.

This module proves that two ways:

1. Structurally (AST): none of the public entry points call ``db.commit`` /
   ``db.rollback`` on the passed-in session any more.
2. Behaviourally (real Postgres): with a still-pending write on the caller's
   session, the aux writer neither commits (a separate session cannot see the
   pending row) nor rolls it back (the caller can still see and commit it) — and
   the aux write itself persists on its own session. A forced enqueue failure is
   swallowed and leaves the caller's transaction intact.

DB-backed (CI provisions Postgres + runs the migrations).
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import index_outbox_service as outbox
from app.services import match_score_cache as cache
from app.services import match_telemetry_service as tel
from app.services.match_telemetry_service import ImpressionEntry
from app.services.scoring_service import LayerResult, ScoreBreakdown

# entity/event ids well above any real row so cleanup is safe.
BASE = 990500


def _scratch_event() -> str:
    return f"txniso-{uuid.uuid4().hex}"


def _mk_breakdown(candidate_id: int, job_id: int) -> ScoreBreakdown:
    zero = LayerResult(points=0.0, max_points=0.0)
    return ScoreBreakdown(
        candidate_id=candidate_id,
        job_id=job_id,
        total=0.0,
        semantic=zero,
        skills=zero,
        salary=zero,
        location=zero,
        availability=zero,
    )


# ── 1. Structural (AST) ───────────────────────────────────────────────────────


def _db_commit_or_rollback_calls(func) -> list[str]:
    """Return every ``db.commit`` / ``db.rollback`` call in ``func``'s body.

    The session the endpoints own is named ``db`` in all six functions, so a
    call whose receiver is the ``db`` name is exactly "this function finalized
    the caller's transaction". Writes on the dedicated session (named ``s``) are
    intentionally ignored.
    """
    src = textwrap.dedent(inspect.getsource(func))
    hits: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"commit", "rollback"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "db"
        ):
            hits.append(node.func.attr)
    return hits


@pytest.mark.parametrize(
    "func",
    [
        cache.get_cached_or_compute,
        cache.bulk_get_or_compute,
        tel.record_impressions,
        tel.record_outcome,
        outbox.schedule_or_embed_candidate,
        outbox.schedule_or_embed_job,
    ],
    ids=lambda f: f.__name__,
)
def test_aux_writer_does_not_finalize_caller_session(func):
    hits = _db_commit_or_rollback_calls(func)
    assert hits == [], (
        f"{func.__name__} still calls db.{{commit,rollback}} on the caller's "
        f"session: {hits}. A best-effort side-effect must run on its own session."
    )


# ── 2a. Telemetry behavioural isolation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_record_impressions_does_not_touch_caller_txn(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    run_id = f"txniso-{uuid.uuid4().hex[:12]}"
    scratch = _scratch_event()
    caller = AsyncSessionLocal()
    try:
        # Caller opens a transaction with an UNCOMMITTED business write.
        await caller.execute(
            text(
                "INSERT INTO match_outcomes (event_id, event_type) VALUES (:e, 'view')"
            ),
            {"e": scratch},
        )

        n = await tel.record_impressions(
            caller,
            run_id=run_id,
            surface="txniso",
            entries=[ImpressionEntry(candidate_id=1, rank=0)],
        )
        assert n == 1  # impression persisted on the aux writer's own session

        async with AsyncSessionLocal() as other:
            leaked = await other.scalar(
                text("SELECT count(*) FROM match_outcomes WHERE event_id = :e"),
                {"e": scratch},
            )
            assert leaked == 0, "aux writer committed the caller's transaction"
            imp = await other.scalar(
                text("SELECT count(*) FROM match_impressions WHERE run_id = :r"),
                {"r": run_id},
            )
            assert imp == 1  # telemetry landed independently

        still = await caller.scalar(
            text("SELECT count(*) FROM match_outcomes WHERE event_id = :e"),
            {"e": scratch},
        )
        assert still == 1, "aux writer rolled back the caller's transaction"
        await caller.rollback()
    finally:
        await caller.rollback()
        await caller.close()
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM match_impressions WHERE run_id = :r"), {"r": run_id}
            )
            await db.execute(
                text("DELETE FROM match_outcomes WHERE event_id = :e"), {"e": scratch}
            )
            await db.commit()


# ── 2b. Outbox enqueue behavioural isolation ──────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_or_embed_candidate_isolates_enqueue(monkeypatch):
    monkeypatch.setattr(settings, "AI_INDEX_OUTBOX_ENABLED", True)
    ent = BASE + 1
    scratch = _scratch_event()
    caller = AsyncSessionLocal()
    try:
        await caller.execute(
            text(
                "INSERT INTO match_outcomes (event_id, event_type) VALUES (:e, 'view')"
            ),
            {"e": scratch},
        )

        # Candidate `ent` does not exist ⇒ enqueues a delete event on its own
        # session. Either way the caller's transaction must be untouched.
        ok = await outbox.schedule_or_embed_candidate(ent, caller)
        assert ok is True

        async with AsyncSessionLocal() as other:
            leaked = await other.scalar(
                text("SELECT count(*) FROM match_outcomes WHERE event_id = :e"),
                {"e": scratch},
            )
            assert leaked == 0, "enqueue committed the caller's transaction"
            evt = await other.scalar(
                text("SELECT count(*) FROM match_index_outbox WHERE entity_id = :i"),
                {"i": ent},
            )
            assert evt == 1  # enqueue persisted independently

        still = await caller.scalar(
            text("SELECT count(*) FROM match_outcomes WHERE event_id = :e"),
            {"e": scratch},
        )
        assert still == 1, "enqueue rolled back the caller's transaction"
        await caller.rollback()
    finally:
        await caller.rollback()
        await caller.close()
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM match_index_outbox WHERE entity_id = :i"), {"i": ent}
            )
            await db.execute(
                text("DELETE FROM match_outcomes WHERE event_id = :e"), {"e": scratch}
            )
            await db.commit()


@pytest.mark.asyncio
async def test_enqueue_failure_never_rolls_back_caller(monkeypatch):
    """The core M3-TX-01 regression: an enqueue failure must not roll back the
    caller's business write. The old wrapper called ``db.rollback()`` here."""
    monkeypatch.setattr(settings, "AI_INDEX_OUTBOX_ENABLED", True)

    class _Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom enqueue")

    monkeypatch.setattr(outbox, "IndexOutboxEvent", _Boom)

    ent = BASE + 2
    scratch = _scratch_event()
    caller = AsyncSessionLocal()
    try:
        await caller.execute(
            text(
                "INSERT INTO match_outcomes (event_id, event_type) VALUES (:e, 'view')"
            ),
            {"e": scratch},
        )

        # Enqueue blows up inside its own session; the wrapper must swallow it,
        # never raise, and leave the caller's transaction untouched.
        ok = await outbox.schedule_or_embed_candidate(ent, caller)
        assert ok is True

        still = await caller.scalar(
            text("SELECT count(*) FROM match_outcomes WHERE event_id = :e"),
            {"e": scratch},
        )
        assert still == 1, "aux-writer failure rolled back the caller's transaction"

        # The caller can still commit its own work on the intact session.
        await caller.commit()
        async with AsyncSessionLocal() as other:
            committed = await other.scalar(
                text("SELECT count(*) FROM match_outcomes WHERE event_id = :e"),
                {"e": scratch},
            )
            assert committed == 1
    finally:
        await caller.rollback()
        await caller.close()
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM match_outcomes WHERE event_id = :e"), {"e": scratch}
            )
            await db.commit()


# ── 2c. Cache write is best-effort + fully isolated ───────────────────────────


@pytest.mark.asyncio
async def test_persist_breakdowns_is_best_effort_and_isolated():
    """A cache write for a non-existent (candidate, job) fails the FK on the
    dedicated session. It must be swallowed (never raise) and write nothing —
    proving the write is self-contained and cannot poison a caller session."""
    bad = _mk_breakdown(candidate_id=BASE + 3, job_id=BASE + 3)
    await cache._persist_breakdowns(
        [bad], profile_id=0, compute_start=datetime.now(timezone.utc)
    )  # must not raise

    async with AsyncSessionLocal() as db:
        n = await db.scalar(
            text(
                "SELECT count(*) FROM candidate_job_match_scores "
                "WHERE candidate_id = :c"
            ),
            {"c": BASE + 3},
        )
    assert n == 0
