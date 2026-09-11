"""The "Dopasowanie" tab and the canonical ring measured in its own session.

Two defects shared one cause — ``display_fit`` ran on the REQUEST session:

* a failed measurement rolled that session back, which expires every object
  loaded through it, the authenticated ``current_user`` included; the next
  attribute read in the route was a ``MissingGreenlet`` 500 instead of the
  justification with a "not measured" ring;
* ``score_candidates`` attaches reviewed requirement evidence to the ORM
  candidate it scores. On the request session that is the same identity-mapped
  instance the legacy prose path scores next, so the legacy breakdown (and the
  prose ``input_hash`` and the stored legacy cache row) depended on whether the
  ring was computed first.

Real Postgres, real user row, real route. Only the paid/external parts are
stubbed: the LLM call and its quota gate, and the vector providers.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text

import app.models  # noqa: F401  (register every mapper)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.match_justification import CandidateMatchJustification
from app.models.requirement_verification import RequirementVerification
from app.models.user import User, UserRole
from app.services import canonical_fit
from app.services import match_justification_service as mjs
from app.services.requirement_contract import requirements_for_job
from app.services.requirement_verification import (
    criteria_fingerprint,
    group_key,
    source_fingerprint,
)


async def _seed() -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Fit isolation {tag}")
        recruiter = User(
            email=f"fit-isolation-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Fit"),
            name="Fit Isolation",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add_all([client, recruiter])
        await db.flush()
        job = Job(
            title=f"Kotlin developer {tag}",
            client_id=client.id,
            must_skills=["Kotlin"],
            description="Backend w Kotlinie.",
        )
        # Keyword-wise the candidate LACKS the must-have: only a recruiter's
        # reviewed verification says it is met.
        candidate = Candidate(
            name="Izolacja",
            lastname=f"Pomiaru {tag}",
            email=f"fit-isolation-{tag}@example.com",
            skills=["Python"],
            raw_cv_text="Python developer, Django, PostgreSQL.",
        )
        db.add_all([job, candidate])
        await db.commit()
        return {
            "client_id": client.id,
            "user_id": recruiter.id,
            "job_id": job.id,
            "candidate_id": candidate.id,
        }


async def _verify_must_as_met(world: dict) -> None:
    """A CURRENT reviewed verification: same criteria, same candidate source."""
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        candidate = await db.get(Candidate, world["candidate_id"])
        contract = requirements_for_job(job)
        (must,) = [g for g in contract.all_of if g.level == "must"]
        db.add(
            RequirementVerification(
                job_id=job.id,
                candidate_id=candidate.id,
                reviewer_id=world["user_id"],
                group_key=group_key(must),
                requirement=must.model_dump(),
                requirements_fingerprint=criteria_fingerprint(contract),
                source_fingerprint=source_fingerprint(candidate),
                status="met",
                evidence="Dwa lata w Kotlinie w poprzednim projekcie.",
                usage_context="Rozmowa telefoniczna",
                verified_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _cleanup(world: dict) -> None:
    """This test's rows only (the shared test database is never wiped)."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateMatchJustification).where(
                CandidateMatchJustification.job_id == world["job_id"]
            )
        )
        await db.execute(
            delete(RequirementVerification).where(
                RequirementVerification.job_id == world["job_id"]
            )
        )
        await db.commit()


@asynccontextmanager
async def _admitted(db, feature, *, user_id=None, units=1):
    yield None


@pytest.fixture
def no_providers(monkeypatch):
    """No Voyage/Qdrant/Claude in tests: stub the external edges only."""
    monkeypatch.setattr(mjs, "ai_feature", _admitted)

    async def prose(*, prompt, system_prompt, model, max_tokens):
        return {
            "summary": "Mocny backend, brak potwierdzonego Kotlina w CV.",
            "pros": ["Python i Django w produkcji"],
            "watchouts": ["Potwierdzić Kotlin"],
        }

    monkeypatch.setattr(mjs, "_call_claude_json", prose)
    monkeypatch.setattr(canonical_fit, "request_vector", AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_failed_measurement_serves_the_tab_with_an_unmeasured_ring(
    app_client: AsyncClient, no_providers, monkeypatch
):
    monkeypatch.setattr(
        "app.services.embedding_service.similarity_for_candidate_ids",
        AsyncMock(return_value={}),
    )

    async def measurement_breaks_mid_query(session, context, candidates):
        # A genuine failed statement: it poisons the transaction it ran in.
        await session.execute(text("SELECT * FROM fit_isolation_no_such_table"))

    monkeypatch.setattr(
        canonical_fit, "score_candidates", measurement_breaks_mid_query
    )
    world = await _seed()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(world["user_id"], UserRole.recruiter.value)
    }
    path = f"/api/candidates/{world['candidate_id']}/scoring/{world['job_id']}"
    try:
        tab = await app_client.get(path, headers=headers)
        assert tab.status_code == 200, tab.text
        body = tab.json()
        # The number is missing and says why — the prose is still served.
        assert body["score"] is None
        assert body["score_measurement"] == "unavailable"
        assert body["summary"].startswith("Mocny backend")

        rated = await app_client.post(
            f"{path}/feedback", json={"rating": 1}, headers=headers
        )
        assert rated.status_code == 200, rated.text
        assert rated.json()["score"] is None
        assert rated.json()["rating"] == 1
        async with AsyncSessionLocal() as db:
            rated_by = await db.scalar(
                select(CandidateMatchJustification.rated_by).where(
                    CandidateMatchJustification.job_id == world["job_id"]
                )
            )
        assert rated_by == world["user_id"]
    finally:
        await _cleanup(world)


async def _legacy_prose_input(session, world: dict) -> tuple[dict, str, object]:
    candidate = await session.get(Candidate, world["candidate_id"])
    job = await session.get(Job, world["job_id"])
    breakdown = (await mjs._compute_breakdown(candidate, job, session)).as_dict()
    return breakdown, mjs._input_hash(candidate, job, breakdown), candidate


@pytest.mark.asyncio
async def test_the_ring_cannot_change_the_legacy_breakdown_the_prose_is_hashed_from(
    no_providers, monkeypatch
):
    # Neutral semantic layer and NO cache write, so every computation below is
    # a fresh one: a warm legacy cache would hide the leak instead of proving
    # its absence.
    monkeypatch.setattr(
        "app.services.embedding_service.similarity_for_candidate_ids",
        AsyncMock(side_effect=RuntimeError("voyage down")),
    )
    world = await _seed()
    try:
        await _verify_must_as_met(world)
        async with AsyncSessionLocal() as session:
            baseline, baseline_hash, _ = await _legacy_prose_input(session, world)
        assert baseline["gap_must"] and not baseline["matching_must"]

        # Control: were the ring measured on the SAME session (the old code),
        # the current "met" verification would reach the legacy breakdown. The
        # identity map holds instances weakly, so the leak needs the request to
        # keep the candidate alive — as any code holding the row does; `held`
        # makes that worst case deterministic.
        async with AsyncSessionLocal() as shared:

            @asynccontextmanager
            async def same_session():
                yield shared

            monkeypatch.setattr(mjs, "AsyncSessionLocal", same_session)
            held = await shared.get(Candidate, world["candidate_id"])
            await mjs.display_fit(world["candidate_id"], world["job_id"], user_id=None)
            leaked, leaked_hash, candidate = await _legacy_prose_input(shared, world)
            assert candidate is held
        monkeypatch.setattr(mjs, "AsyncSessionLocal", AsyncSessionLocal)
        assert leaked["matching_must"] == baseline["gap_must"]
        assert leaked_hash != baseline_hash

        # The route's order of events on one request session, the candidate
        # alive there while the ring is measured — now in its own session.
        async with AsyncSessionLocal() as request_session:
            held = await request_session.get(Candidate, world["candidate_id"])
            await mjs.display_fit(world["candidate_id"], world["job_id"], user_id=None)
            after, after_hash, candidate = await _legacy_prose_input(
                request_session, world
            )
            assert candidate is held
        assert after == baseline
        assert after_hash == baseline_hash
        assert "_reviewed_requirements" not in vars(candidate)
    finally:
        await _cleanup(world)
