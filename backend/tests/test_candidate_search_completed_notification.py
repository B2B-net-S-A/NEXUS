"""Bell entry when a full candidate search ends (17.09.2026).

A full search (Talent Radar, AI Matching on a recruitment) takes ~3 minutes;
the author used to watch a spinner. The worker now adds a
``candidate_search_completed`` notification in the SAME transaction that moves
the run to its terminal state, so the state transition makes it exactly-once.

Runs against the real test database with a zero-population run, so the worker
reaches ``finish_run`` without scoring anything; the query embedding is stubbed.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import app.models  # noqa: F401  (register every mapper)
import pytest
from sqlalchemy import func, select, text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate_search_run import CandidateSearchRun
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import candidate_search_store as store
from app.services import candidate_search_worker as worker
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_job

NTYPE = NotificationType.candidate_search_completed


async def _seed_run(*, with_job: bool, claims: int = 0) -> tuple[str, int, int | None]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        author = User(
            email=f"search-done-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Search"),
            name=f"Search Done {tag}",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"SearchDoneClient-{tag}")
        db.add_all([author, client])
        await db.flush()
        job_id = None
        if with_job:
            job = Job(
                title=f"SearchDoneJob-{tag}",
                status=JobStatus.published,
                client_id=client.id,
                recruiter_id=author.id,
            )
            db.add(job)
            await db.flush()
            job_id = job.id
        run = CandidateSearchRun(
            id=str(uuid.uuid4()),
            created_by=author.id,
            client_id=client.id,
            job_id=job_id,
            state="queued",
            request_fingerprint="f" * 64,
            request_context=build_request_context(
                make_job(), DEFAULT_PROFILE
            ).as_dict(),
            version_trace={},
            population_size=0,
            metrics={store.CLAIMS_KEY: claims} if claims else {},
        )
        db.add(run)
        await db.commit()
        return run.id, author.id, job_id


async def _notifications(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type == NTYPE,
                    )
                )
            ).all()
        )


async def _state(run_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateSearchRun.state).where(CandidateSearchRun.id == run_id)
        )


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    async def no_vector(_query):
        return None

    monkeypatch.setattr(worker, "request_vector", no_vector)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_job", [True, False])
async def test_finished_run_notifies_its_author_once(with_job: bool):
    run_id, author_id, job_id = await _seed_run(with_job=with_job)

    await worker.execute_run(run_id)

    assert await _state(run_id) == "complete"
    (entry,) = await _notifications(author_id)
    assert entry.title == "Przegląd bazy zakończony"
    assert entry.message == "0 kandydatów w wynikach"
    assert entry.link == (
        f"/jobs/{job_id}?tab=similar" if with_job else "/talent-radar"
    )
    assert entry.related_entity_type == "candidate_search_run"
    assert entry.related_entity_id is None


@pytest.mark.asyncio
async def test_a_stale_worker_finishing_again_adds_nothing():
    run_id, author_id, _ = await _seed_run(with_job=True)
    async with AsyncSessionLocal() as db:
        token = await store.claim_run(db, run_id, lease_seconds=300)
        await db.commit()

    await worker._execute_claimed(run_id, token)
    with pytest.raises(store.SearchLeaseLost):
        # Same lease after the run already finished: the state transition
        # refuses, so no second entry can ride along with it.
        await worker._execute_claimed(run_id, token)
    await worker.execute_run(run_id)  # nothing left to claim

    assert len(await _notifications(author_id)) == 1


@pytest.mark.asyncio
async def test_a_failing_notification_never_blocks_finishing_the_run(monkeypatch):
    run_id, author_id, _ = await _seed_run(with_job=True)

    async def broken(*_args, **_kwargs):
        raise RuntimeError("section policy unavailable")

    monkeypatch.setattr(worker, "notification_recipient_has_access", broken)

    await worker.execute_run(run_id)

    assert await _state(run_id) == "complete"
    assert await _notifications(author_id) == []


@pytest.mark.asyncio
async def test_exhausted_run_tells_the_author_it_failed():
    run_id, author_id, job_id = await _seed_run(with_job=True, claims=worker.MAX_CLAIMS)

    await worker.execute_run(run_id)

    assert await _state(run_id) == "failed"
    (entry,) = await _notifications(author_id)
    assert entry.title == "Przegląd bazy nie powiódł się"
    assert entry.message == "Uruchom go ponownie."
    assert entry.link == f"/jobs/{job_id}?tab=similar"


@pytest.mark.asyncio
async def test_failure_reported_by_a_replaced_worker_adds_nothing():
    """A worker whose lease was replaced reports its failure after the new
    owner already failed the run: ``fail_run`` refuses, so no second entry."""
    run_id, author_id, _ = await _seed_run(with_job=True, claims=worker.MAX_CLAIMS)
    await worker.execute_run(run_id)  # new owner: exhausted → failed + entry
    assert len(await _notifications(author_id)) == 1

    await worker._record_failure(run_id, "replaced-lease", RuntimeError("late"))

    assert await _state(run_id) == "failed"
    assert len(await _notifications(author_id)) == 1


@pytest.mark.asyncio
async def test_reaped_stalled_run_tells_the_author_it_failed():
    from app.tasks import candidate_search_worker as loop

    run_id, author_id, _ = await _seed_run(with_job=False)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE candidate_search_runs SET state = 'running',"
                " lease_expires_at = NULL, updated_at = now() - make_interval(mins => :mins)"
                " WHERE id = :id"
            ),
            {"id": run_id, "mins": int(loop.STALLED_AFTER / timedelta(minutes=1)) + 5},
        )
        await db.commit()

    await loop._reap_stalled()
    await loop._reap_stalled()  # already failed: no second transition

    assert await _state(run_id) == "failed"
    (entry,) = await _notifications(author_id)
    assert entry.link == "/talent-radar"
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == author_id)
            )
        ) == 1
