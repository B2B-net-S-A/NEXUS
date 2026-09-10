"""Host CI PostgreSQL integration: durable membership, ownership and leases."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.user import User, UserRole
from app.services import candidate_search_store as store
from app.services.full_candidate_scan import CandidateEvaluation


@pytest.mark.asyncio
async def test_durable_run_accounts_for_entire_snapshot_and_preserves_unknown():
    async with AsyncSessionLocal() as db:
        try:
            unique = uuid.uuid4().hex
            user = User(
                name="Search test",
                email=f"search-{unique}@example.com",
                password_hash="test-unused",
                role=UserRole.admin,
                is_active=True,
            )
            client = Client(name=f"Search client {unique}")
            cand = Candidate(name="Search", lastname="Fixture")
            db.add_all([user, client, cand])
            await db.flush()
            run = await store.create_run(
                db,
                actor_id=user.id,
                client_id=client.id,
                job_id=None,
                request_fingerprint="f" * 64,
                request_context={},
                version_trace={},
            )
            assert run.population_size >= 1
            assert await store.owned_run(db, run.id, user.id + 1000000) is None
            assert not await store.population_changed(db, run.id)
            token = await store.claim_run(db, run.id)
            assert token
            assert await store.claim_run(db, run.id) is None
            await store.save_metrics(db, run.id, token, {"attempts": 1})
            await db.refresh(run)
            # Telemetry replaces metrics; the durable claim counter survives it.
            assert run.metrics == {"attempts": 1, "claims": 1}
            with pytest.raises(ValueError, match="unaccounted"):
                await store.finish_run(db, run.id, token)
            while batch := await store.pending_batch(db, run.id, limit=1000):
                await store.save_batch(
                    db,
                    run.id,
                    token,
                    batch,
                    [
                        CandidateEvaluation(
                            item.candidate_id,
                            item.version,
                            True,
                            None if item.candidate_id == cand.id else 80,
                            "missing_index"
                            if item.candidate_id == cand.id
                            else "measured",
                        )
                        for item in batch
                    ],
                    metrics={"attempts": 1, "cost_complete": False},
                )
            counts = await store.finish_run(db, run.id, token)
            assert counts["evaluated"] == run.population_size
            assert counts["needs_verification"] == 1
            assert run.state == "partial"
            assert run.metrics["elapsed_ms"] >= 0
            assert run.metrics["cost_complete"] is False
            rows, total = await store.result_page(db, run.id, min_score=90)
            assert total == 1 and rows[0].candidate_id == cand.id
            cand.name = "Updated"
            await db.flush()
            # Use a distinct timestamp: PostgreSQL now() is transaction-stable.
            cand.updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
            await db.flush()
            assert await store.population_changed(db, run.id)
            # Counters classify one primary reason per excluded row. Old or
            # unknown reason payloads remain accounted for instead of vanishing.
            from sqlalchemy import update
            from app.models.candidate_search_run import CandidateSearchResult

            for reasons, expected in [
                (["over_budget", "missing_must"], "over_budget"),
                ([], "unknown"),
                (["old_policy"], "unknown"),
            ]:
                await db.execute(
                    update(CandidateSearchResult)
                    .where(
                        CandidateSearchResult.run_id == run.id,
                        CandidateSearchResult.candidate_id == cand.id,
                    )
                    .values(eligible=False, exclusion_reasons=reasons)
                )
                totals = await store.run_counts(db, run.id)
                assert totals["excluded"] == 1
                assert sum(totals["exclusion_reasons"].values()) == 1
                assert totals["exclusion_reasons"][expected] == 1
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_expired_worker_cannot_finalize_after_another_claim():
    async with AsyncSessionLocal() as db:
        try:
            unique = uuid.uuid4().hex
            user = User(
                name="Lease test",
                email=f"lease-{unique}@example.com",
                password_hash="test-unused",
                role=UserRole.admin,
                is_active=True,
            )
            client = Client(name=f"Lease client {unique}")
            db.add_all([user, client])
            await db.flush()
            run = await store.create_run(
                db,
                actor_id=user.id,
                client_id=client.id,
                job_id=None,
                request_fingerprint="e" * 64,
                request_context={},
                version_trace={},
            )
            old_token = await store.claim_run(db, run.id)
            run.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.flush()
            new_token = await store.claim_run(db, run.id)
            assert old_token and new_token and old_token != new_token
            with pytest.raises(store.SearchLeaseLost):
                await store.finish_run(db, run.id, old_token)
            with pytest.raises(store.SearchLeaseLost):
                await store.save_metrics(db, run.id, old_token, {"attempts": 99})
        finally:
            await db.rollback()


async def _actor_and_client(db, label: str):
    unique = uuid.uuid4().hex
    user = User(
        name=f"{label} test",
        email=f"{label}-{unique}@example.com",
        password_hash="test-unused",
        role=UserRole.admin,
        is_active=True,
    )
    client = Client(name=f"{label} client {unique}")
    db.add_all([user, client])
    await db.flush()
    return user, client


def _bare_run(user, client, *, state="queued", **values):
    from app.models.candidate_search_run import CandidateSearchRun

    return CandidateSearchRun(
        id=str(uuid.uuid4()),
        created_by=user.id,
        client_id=client.id,
        job_id=values.pop("job_id", None),
        state=state,
        request_fingerprint=values.pop("request_fingerprint", "c" * 64),
        request_context={},
        version_trace={},
        population_size=values.pop("population_size", 0),
        metrics=values.pop("metrics", {}),
        **values,
    )


@pytest.mark.asyncio
async def test_claims_are_counted_durably_and_a_failed_run_is_terminal():
    from sqlalchemy import func, select
    from app.models.candidate_search_run import CandidateSearchRun

    async with AsyncSessionLocal() as db:
        try:
            user, client = await _actor_and_client(db, "claims")
            run = _bare_run(user, client)
            db.add(run)
            await db.flush()
            first = await store.claim_run(db, run.id)
            await db.refresh(run)
            assert store.claim_count(run.metrics) == 1
            # A telemetry checkpoint replaces metrics without resetting claims.
            await store.save_metrics(db, run.id, first, {"schema": "t", "attempts": 1})
            run.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.flush()
            second = await store.claim_run(db, run.id)
            await db.refresh(run)
            assert second and store.claim_count(run.metrics) == 2
            assert run.metrics["schema"] == "t"
            # Only the current lease owner may fail the run.
            assert not await store.fail_run(db, run.id, "ValueError", token=first)
            assert await store.fail_run(db, run.id, "ValueError", token=second)
            await db.refresh(run)
            assert run.state == "failed" and run.error_code == "ValueError"
            assert run.completed_at is not None
            assert run.lease_token is None and run.lease_expires_at is None
            # Terminal: never claimed again, and it frees the author's slot.
            assert await store.claim_run(db, run.id) is None
            active = await db.scalar(
                select(func.count())
                .select_from(CandidateSearchRun)
                .where(
                    CandidateSearchRun.created_by == user.id,
                    CandidateSearchRun.state.in_(store.ACTIVE_STATES),
                )
            )
            assert active == 0
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_released_lease_is_reclaimed_at_once_and_counted():
    async with AsyncSessionLocal() as db:
        try:
            user, client = await _actor_and_client(db, "release")
            run = _bare_run(user, client)
            db.add(run)
            await db.flush()
            token = await store.claim_run(db, run.id, lease_seconds=300)
            assert await store.claim_run(db, run.id) is None
            assert not await store.release_run(db, run.id, "someone-else")
            assert await store.release_run(db, run.id, token)
            assert await store.claim_run(db, run.id)
            await db.refresh(run)
            assert store.claim_count(run.metrics) == 2
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_reaper_fails_only_claimed_runs_without_progress_or_live_lease():
    async with AsyncSessionLocal() as db:
        try:
            user, client = await _actor_and_client(db, "reaper")
            now = datetime.now(timezone.utc)
            long_ago = now - timedelta(minutes=45)
            stalled = _bare_run(
                user,
                client,
                state="running",
                lease_expires_at=long_ago,
                updated_at=long_ago,
            )
            leased = _bare_run(
                user,
                client,
                state="running",
                lease_expires_at=now + timedelta(minutes=5),
                updated_at=long_ago,
            )
            recent = _bare_run(
                user,
                client,
                state="running",
                lease_expires_at=now - timedelta(minutes=1),
                updated_at=now - timedelta(minutes=5),
            )
            waiting = _bare_run(user, client, state="queued", updated_at=long_ago)
            db.add_all([stalled, leased, recent, waiting])
            await db.flush()
            reaped = await store.reap_stalled_runs(
                db, stalled_after=timedelta(minutes=30)
            )
            assert stalled.id in reaped
            assert not {leased.id, recent.id, waiting.id} & set(reaped)
            await db.refresh(stalled)
            assert stalled.state == "failed" and stalled.error_code == "stalled"
            assert stalled.completed_at is not None
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_candidate_erasure_removes_rows_and_fails_only_active_runs():
    from sqlalchemy import select
    from app.models.candidate_search_run import CandidateSearchResult

    async with AsyncSessionLocal() as db:
        try:
            user, client = await _actor_and_client(db, "erasure")
            erased, other = (
                Candidate(name="Erased", lastname="Person"),
                Candidate(name="Other", lastname="Person"),
            )
            db.add_all([erased, other])
            await db.flush()
            finished = _bare_run(user, client, state="complete", population_size=2)
            active = _bare_run(user, client, population_size=2)
            db.add_all([finished, active])
            await db.flush()
            for run_id in (finished.id, active.id):
                for cid in (erased.id, other.id):
                    db.add(
                        CandidateSearchResult(
                            run_id=run_id,
                            candidate_id=cid,
                            candidate_version="v1",
                            state="evaluated" if run_id == finished.id else "pending",
                            evidence={"breakdown": {"total": 80}},
                        )
                    )
            await db.flush()
            token = await store.claim_run(db, active.id)

            result = await store.erase_candidate(db, erased.id)

            assert result == {"search_rows_deleted": 2, "search_runs_failed": 1}
            remaining = [
                tuple(row)
                for row in await db.execute(
                    select(
                        CandidateSearchResult.run_id, CandidateSearchResult.candidate_id
                    ).where(CandidateSearchResult.run_id.in_([finished.id, active.id]))
                )
            ]
            assert sorted(remaining) == sorted(
                [(finished.id, other.id), (active.id, other.id)]
            )
            await db.refresh(finished)
            await db.refresh(active)
            assert finished.state == "complete"
            assert active.state == "failed"
            assert active.error_code == "candidate_erased"
            # The worker that held the lease can no longer write or finalize.
            with pytest.raises(store.SearchLeaseLost):
                await store.save_metrics(db, active.id, token, {})
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_full_run_filters_before_paging_and_counts_unknown_scores():
    from app.services.full_search_filters import ResultFilters

    async with AsyncSessionLocal() as db:
        try:
            unique = uuid.uuid4().hex
            user = User(
                name="Filter test",
                email=f"filter-{unique}@example.com",
                password_hash="unused",
                role=UserRole.admin,
                is_active=True,
            )
            client = Client(name=f"Filter client {unique}")
            candidates = [Candidate(name="Filter", lastname=str(i)) for i in range(25)]
            db.add_all([user, client, *candidates])
            await db.flush()
            target_ids = {c.id for c in candidates}
            python_ids = {c.id for c in candidates[-5:]}
            unknown_id = candidates[-1].id
            run = await store.create_run(
                db,
                actor_id=user.id,
                client_id=client.id,
                job_id=None,
                request_fingerprint="f" * 64,
                request_context={},
                version_trace={},
            )
            token = await store.claim_run(db, run.id)
            while batch := await store.pending_batch(db, run.id, limit=1000):
                await store.save_batch(
                    db,
                    run.id,
                    token,
                    batch,
                    [
                        CandidateEvaluation(
                            item.candidate_id,
                            item.version,
                            item.candidate_id in target_ids,
                            None
                            if item.candidate_id == unknown_id
                            else 70
                            if item.candidate_id in python_ids
                            else 95,
                            "missing_index"
                            if item.candidate_id == unknown_id
                            else "measured",
                            evidence={
                                "filters": {
                                    "skills": [
                                        "python"
                                        if item.candidate_id in python_ids
                                        else "java"
                                    ],
                                    "rate": "unknown"
                                    if item.candidate_id == unknown_id
                                    else "ok",
                                    "locations": [
                                        "warszawa"
                                        if item.candidate_id in python_ids
                                        else "kraków"
                                    ],
                                }
                            },
                        )
                        for item in batch
                    ],
                )
            await store.finish_run(db, run.id, token)
            rows, total = await store.result_page(
                db,
                run.id,
                limit=2,
                filters=ResultFilters(skill="Python", location="Warszawa"),
            )
            assert total == 5 and len(rows) == 2
            assert all(r.candidate_id in python_ids for r in rows)
            last, total = await store.result_page(
                db, run.id, offset=4, limit=2, filters=ResultFilters(skill="Python")
            )
            assert total == 5 and [r.candidate_id for r in last] == [unknown_id]
            unknown, total = await store.result_page(
                db, run.id, min_score=99, filters=ResultFilters(rate="unknown")
            )
            assert total == 1 and unknown[0].fit_score is None
            counts = await store.run_counts(db, run.id)
            assert counts["strong"] == 20
            from app.models.job import Job
            from app.models.recruitment_pipeline import CandidateStage

            job = Job(title="Filter request", client_id=client.id)
            db.add(job)
            await db.flush()
            db.add(CandidateStage(job_id=job.id, candidate_id=unknown_id))
            await db.flush()
            in_process, total = await store.result_page(
                db, run.id, filters=ResultFilters(stage="in", job_id=job.id)
            )
            assert total == 1 and in_process[0].candidate_id == unknown_id
            outside, total = await store.result_page(
                db, run.id, limit=100, filters=ResultFilters(stage="out", job_id=job.id)
            )
            assert total == 24 and all(
                row.candidate_id != unknown_id for row in outside
            )
        finally:
            await db.rollback()
