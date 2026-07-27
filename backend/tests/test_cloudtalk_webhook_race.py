"""Concurrency test — CloudTalk webhook upsert must be atomic.

CloudTalk delivers SEPARATE webhook POSTs per event (call-ended,
transcript-ready, recording-ready) for the SAME call, plus retries. When two
events both SELECT null on ``cloudtalk_call_id`` before either commits, the
naive SELECT-then-INSERT would have both INSERT the same unique id — the loser
raises ``IntegrityError`` → uncaught → 500 to CloudTalk, and the dropped event
is exactly the transcript-ready payload that drives Champion enrichment.

The fix (:func:`app.api.calls._process_cloudtalk_payload`) wraps the INSERT in a
SAVEPOINT and, on conflict, re-selects the row the racing event created and
merges its own fields in. This test drives two genuinely concurrent sessions at
the same ``cloudtalk_call_id`` and asserts they converge on ONE row with BOTH
events' data — and that neither call raises.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.api.calls import _process_cloudtalk_payload
from app.core.database import AsyncSessionLocal
from app.models.call import Call
from app.models.candidate import Candidate


@pytest_asyncio.fixture
async def seeded_candidate():
    """Create a candidate with a PL-formatted phone, yield, then cleanup."""
    unique = uuid.uuid4().hex[:8]
    phone = "+48 601-234-567"

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Race-{unique}",
            lastname="Test",
            email=f"race-cand-{unique}@example.com",
            phone=phone,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        candidate_id = cand.id

    yield {"id": candidate_id, "phone": phone}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Call).where(Call.candidate_id == candidate_id))
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()


def _body(ct_id: str, **call_extra) -> bytes:
    call = {"id": ct_id, "external_number": "48601234567"}
    call.update(call_extra)
    return json.dumps({"call": call}).encode()


def _barriered_session(barrier: asyncio.Barrier):
    """A session whose FIRST ``scalar`` (the initial ``Call`` SELECT) blocks on a
    barrier before returning.

    This pins the race deterministically: both coroutines complete their
    ``SELECT ... WHERE cloudtalk_call_id = ct_id`` (each sees null, since neither
    has committed) and only then are released to run the INSERT together — so one
    provably hits the unique-constraint conflict and takes the merge branch. The
    later candidate/user lookups are not barriered.
    """
    db = AsyncSessionLocal()
    original_scalar = db.scalar
    seen = {"n": 0}

    async def scalar_wrap(*args, **kwargs):
        seen["n"] += 1
        result = await original_scalar(*args, **kwargs)
        if seen["n"] == 1:  # the handler's initial Call SELECT
            await barrier.wait()
        return result

    db.scalar = scalar_wrap  # type: ignore[method-assign]
    return db


@pytest.mark.asyncio
async def test_concurrent_events_same_ct_id_converge_on_single_row(
    seeded_candidate: dict,
    caplog,
) -> None:
    """Two concurrent INSERT-path events must produce ONE row, no IntegrityError.

    Both sessions run on their own connection and are held at a barrier right
    after their initial ``SELECT ... WHERE cloudtalk_call_id = ct_id`` — both see
    null and both head down the INSERT branch. The winner INSERTs; the loser hits
    the unique constraint, catches it, re-selects, and applies its own fields.
    Final state: a single Call carrying BOTH events' data.
    """
    logger = logging.getLogger("test.cloudtalk.race")
    ct_id = f"ct-race-{uuid.uuid4().hex[:6]}"

    # call-ended carries duration; transcript-ready carries the transcript.
    # Whichever wins the INSERT, the other's field must still land on the row.
    body_call_ended = _body(ct_id, duration=90, status="completed")
    body_transcript = _body(ct_id, transcript="RACE-TRANSCRIPT", summary="race-summary")

    barrier = asyncio.Barrier(2)

    async def run(body: bytes) -> dict:
        db = _barriered_session(barrier)
        try:
            return await _process_cloudtalk_payload(body, db, logger)
        finally:
            await db.close()

    with caplog.at_level(logging.INFO, logger="test.cloudtalk.race"):
        results = await asyncio.gather(run(body_call_ended), run(body_transcript))

    # Neither concurrent event 500-ed: both returned a normal ok result.
    for result in results:
        assert result["status"] == "ok"
        assert result["candidate_matched"] is True

    # Prove the conflict path actually executed (not a lucky serialization):
    # exactly one event took the "concurrent insert … merging" branch.
    assert any("concurrent insert" in rec.message for rec in caplog.records), (
        "expected one event to hit the IntegrityError/merge branch"
    )

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(select(Call).where(Call.cloudtalk_call_id == ct_id))
        ).all()
        assert len(rows) == 1, "concurrent events must converge on exactly ONE row"
        row = rows[0]
        assert row.candidate_id == seeded_candidate["id"]
        # Both events' data survived the merge, independent of who won the race.
        assert row.transcript == "RACE-TRANSCRIPT", (
            "transcript event's data must land on the row"
        )
        assert row.duration_seconds == 90, "call-ended event's data must land"


@pytest.mark.asyncio
async def test_sequential_replay_still_updates_single_row(
    seeded_candidate: dict,
) -> None:
    """Happy-path regression guard: sequential events still UPDATE, not INSERT.

    Exercises the non-racing path through the same code so the SAVEPOINT
    refactor did not change single-delivery / ordered-replay behavior.
    """
    logger = logging.getLogger("test.cloudtalk.race")
    ct_id = f"ct-seq-{uuid.uuid4().hex[:6]}"

    async with AsyncSessionLocal() as db:
        first = await _process_cloudtalk_payload(
            _body(ct_id, duration=60, status="completed"), db, logger
        )
    assert first["status"] == "ok"

    async with AsyncSessionLocal() as db:
        second = await _process_cloudtalk_payload(
            _body(ct_id, transcript="LATER-TRANSCRIPT"), db, logger
        )
    assert second["status"] == "ok"

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(select(Call).where(Call.cloudtalk_call_id == ct_id))
        ).all()
        assert len(rows) == 1, "sequential replay must UPDATE, not INSERT"
        row = rows[0]
        assert row.transcript == "LATER-TRANSCRIPT"
        assert row.duration_seconds == 60  # preserved from the first event
