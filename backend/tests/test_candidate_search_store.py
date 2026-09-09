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
            assert run.metrics == {"attempts": 1}
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
