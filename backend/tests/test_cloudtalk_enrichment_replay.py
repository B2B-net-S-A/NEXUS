"""P1-CLOUDTALK-01 — CloudTalk webhook enrichment must not replay, and an
ambiguous phone match must be observable.

Two hardening guards on ``app.api.calls._process_cloudtalk_payload``:

(a) Replay guard — CloudTalk redelivers the same transcript-ready webhook on
    retry. Enrichment is expensive (LLM) and idempotent per call, so a second
    delivery of the same ``cloudtalk_call_id`` must NOT spawn a second Champion
    Profile suggestion. We assert a replayed transcript yields exactly ONE
    suggestion and calls the enrichment path exactly once.

(b) Ambiguous last-9 lookup — two candidates sharing the last nine phone digits
    used to be resolved by an unordered ``LIMIT 1`` (non-deterministic, silent
    misattribution). The fix orders by newest id and logs a warning when the
    match count > 1. We assert the warning fires and the newest id is chosen.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import app.services.champion_draft_service as champion_draft_service
from app.api.calls import _process_cloudtalk_payload
from app.core.database import AsyncSessionLocal
from app.models.call import Call
from app.models.candidate import Candidate
from app.models.champion_suggestion import (
    ChampionProfileSuggestion,
    SuggestionSource,
)
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage

pytestmark = pytest.mark.asyncio


def _body(ct_id: str, external_number: str, **call_extra) -> bytes:
    call = {"id": ct_id, "external_number": external_number}
    call.update(call_extra)
    return json.dumps({"call": call}).encode()


# ── (a) replay guard ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def enrichable_candidate():
    """Candidate + client + job + stage so the transcript path reaches enrichment."""
    unique = uuid.uuid4().hex[:8]
    phone = "+48 601-234-567"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"CT Client {unique}")
        db.add(client)
        await db.flush()
        job = Job(title=f"CT Job {unique}", client_id=client.id)
        db.add(job)
        await db.flush()
        cand = Candidate(
            name=f"CT-{unique}",
            lastname="Enrich",
            email=f"ct-enrich-{unique}@example.com",
            phone=phone,
        )
        db.add(cand)
        await db.flush()
        db.add(CandidateStage(candidate_id=cand.id, job_id=job.id))
        await db.commit()
        ids = {"candidate_id": cand.id, "client_id": client.id, "job_id": job.id}

    yield {**ids, "phone": phone}

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ChampionProfileSuggestion).where(
                ChampionProfileSuggestion.job_id == ids["job_id"]
            )
        )
        await db.execute(delete(Call).where(Call.candidate_id == ids["candidate_id"]))
        await db.execute(
            delete(CandidateStage).where(
                CandidateStage.candidate_id == ids["candidate_id"]
            )
        )
        await db.execute(delete(Job).where(Job.id == ids["job_id"]))
        await db.execute(delete(Candidate).where(Candidate.id == ids["candidate_id"]))
        await db.execute(delete(Client).where(Client.id == ids["client_id"]))
        await db.commit()


async def test_replayed_transcript_enriches_exactly_once(
    enrichable_candidate: dict, monkeypatch
) -> None:
    """Redelivering the same transcript webhook must not create a 2nd suggestion."""
    ct_id = f"ct-replay-{uuid.uuid4().hex[:6]}"
    call_count = {"n": 0}

    async def fake_enrich(db, *, job_id, source_ref=None, **kwargs):
        # Stand in for the real LLM enrichment: persist a suggestion sourced from
        # THIS call so the replay guard has something to detect on redelivery.
        call_count["n"] += 1
        db.add(
            ChampionProfileSuggestion(
                job_id=job_id,
                source_type=SuggestionSource.cloudtalk_call,
                source_ref=source_ref,
                payload={},
            )
        )
        await db.commit()
        return None

    monkeypatch.setattr(champion_draft_service, "enrich_from_call", fake_enrich)

    body = _body(
        ct_id,
        "48601234567",
        transcript="TRANSCRIPT-BODY",
        summary="sum",
        status="completed",
    )
    logger = logging.getLogger("test.cloudtalk.replay")

    # First delivery — enriches.
    async with AsyncSessionLocal() as db:
        first = await _process_cloudtalk_payload(body, db, logger)
    # Second delivery — identical payload (CloudTalk retry) — must skip enrichment.
    async with AsyncSessionLocal() as db:
        second = await _process_cloudtalk_payload(body, db, logger)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert call_count["n"] == 1, "enrichment must run once across the replay"

    async with AsyncSessionLocal() as db:
        suggestions = (
            await db.scalars(
                select(ChampionProfileSuggestion).where(
                    ChampionProfileSuggestion.source_type
                    == SuggestionSource.cloudtalk_call,
                    ChampionProfileSuggestion.source_ref == ct_id,
                )
            )
        ).all()
    assert len(suggestions) == 1, (
        "a replayed transcript must yield exactly ONE suggestion"
    )


# ── (b) ambiguous last-9 lookup ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def two_candidates_same_last9():
    """Two candidates whose phones share the same trailing nine digits."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        older = Candidate(
            name=f"Older-{unique}",
            lastname="Dup",
            email=f"older-{unique}@example.com",
            phone="+48 601234567",
        )
        db.add(older)
        await db.flush()
        newer = Candidate(
            name=f"Newer-{unique}",
            lastname="Dup",
            email=f"newer-{unique}@example.com",
            phone="0048601234567",  # same last-9 = 601234567
        )
        db.add(newer)
        await db.commit()
        await db.refresh(older)
        await db.refresh(newer)
        ids = {"older_id": older.id, "newer_id": newer.id}

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Call).where(
                Call.candidate_id.in_([ids["older_id"], ids["newer_id"]])
            )
        )
        await db.execute(
            delete(Candidate).where(
                Candidate.id.in_([ids["older_id"], ids["newer_id"]])
            )
        )
        await db.commit()


async def test_ambiguous_last9_logs_warning_and_picks_newest(
    two_candidates_same_last9: dict, caplog
) -> None:
    """A last-9 shared by 2 candidates must warn and deterministically pick newest."""
    ct_id = f"ct-ambig-{uuid.uuid4().hex[:6]}"
    body = _body(ct_id, "48601234567", duration=30, status="completed")
    logger = logging.getLogger("app.api.calls")

    with caplog.at_level(logging.WARNING, logger="app.api.calls"):
        async with AsyncSessionLocal() as db:
            result = await _process_cloudtalk_payload(body, db, logger)

    assert result["status"] == "ok"
    assert result["candidate_matched"] is True

    warned = [
        r
        for r in caplog.records
        if "matched" in r.message and "candidates" in r.message
    ]
    assert warned, "an ambiguous last-9 match must emit an observable warning"

    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))
    assert row is not None
    assert row.candidate_id == two_candidates_same_last9["newer_id"], (
        "the deterministic pick must be the newest candidate id"
    )
