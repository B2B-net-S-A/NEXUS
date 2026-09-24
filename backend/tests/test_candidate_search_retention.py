"""Retencja pełnego przeglądu bazy — realny Postgres (decyzja 10.09.2026).

Pilnuje trzech rzeczy, z których każda psuje się po cichu:

1. Stary, ZAKOŃCZONY przegląd znika (razem z wynikami), inaczej tabela wyników
   rośnie o całą bazę kandydatów przy każdym kliknięciu.
2. Najnowszy przegląd z wynikami na (autor, OTWARTA rekrutacja) — a bez
   rekrutacji jeden na autora — zostaje dłużej niż 7 dni: powrót do rekrutacji
   po urlopie nie może skończyć się pustym ekranem. Ochrona ma granice:
   rekrutacja zamknięta nic nie chroni, a nic nie jest chronione dłużej niż
   ``CANDIDATE_SEARCH_RETENTION_PROTECT_MAX_DAYS`` (tabela rośnie z czasem,
   nie z liczbą par autor × request).
3. Aktywnych przeglądów retencja nie dotyka nigdy.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.models.client import Client
from app.models.job import Job
from app.models.user import User, UserRole
from app.tasks import candidate_search_retention as retention


def _run(user, client, *, state, completed_at=None, **values):
    return CandidateSearchRun(
        id=str(uuid.uuid4()),
        created_by=user.id,
        client_id=client.id,
        job_id=values.pop("job_id", None),
        state=state,
        request_fingerprint=values.pop("fingerprint", "a" * 64),
        request_context={},
        version_trace={},
        population_size=0,
        metrics={},
        completed_at=completed_at,
        created_at=values.pop("created_at", completed_at or datetime.now(timezone.utc)),
    )


@pytest.mark.asyncio
async def test_selection_keeps_newest_result_per_author_and_request_and_all_active():
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)
    recent = now - timedelta(days=1)
    cutoff = now - timedelta(days=7)
    async with AsyncSessionLocal() as db:
        try:
            unique = uuid.uuid4().hex
            user = User(
                name="Retention",
                email=f"retention-{unique}@example.com",
                password_hash="unused",
                role=UserRole.admin,
                is_active=True,
            )
            other_user = User(
                name="Retention other",
                email=f"retention-other-{unique}@example.com",
                password_hash="unused",
                role=UserRole.admin,
                is_active=True,
            )
            client = Client(name=f"Retention client {unique}")
            db.add_all([user, other_user, client])
            await db.flush()
            job = Job(title="Retention job", client_id=client.id)
            closed_job = Job(
                title="Retention closed job", client_id=client.id, status="closed"
            )
            cap_job = Job(title="Retention cap job", client_id=client.id)
            db.add_all([job, closed_job, cap_job])
            await db.flush()
            j = {"job_id": job.id}
            runs = {
                # Saved recruitment: the newest finished run is recent, so both
                # older finished runs (a failure included) expire.
                "job_old_complete": _run(
                    user, client, state="complete", completed_at=old, **j
                ),
                "job_old_failed": _run(
                    user, client, state="failed", completed_at=old, **j
                ),
                "job_recent": _run(
                    user, client, state="partial", completed_at=recent, **j
                ),
                # Another author's only run for the same job is old — kept.
                "other_author_only": _run(
                    other_user, client, state="complete", completed_at=old, **j
                ),
                # A closed recruitment protects nothing: its only run expires.
                "closed_job_only": _run(
                    user,
                    client,
                    state="complete",
                    completed_at=old,
                    job_id=closed_job.id,
                ),
                # Protection is capped: the only run of an open recruitment
                # expires once it is older than PROTECT_MAX_DAYS.
                "job_only_beyond_cap": _run(
                    other_user,
                    client,
                    state="complete",
                    completed_at=now
                    - timedelta(
                        days=settings.CANDIDATE_SEARCH_RETENTION_PROTECT_MAX_DAYS + 5
                    ),
                    job_id=cap_job.id,
                ),
                # Ad-hoc Radar: ONE protected run per author, whatever the
                # request fingerprint (a new request is not a new partition).
                "radar_only_old": _run(
                    user,
                    client,
                    state="complete",
                    completed_at=old,
                    fingerprint="b" * 64,
                ),
                "radar_older": _run(
                    user,
                    client,
                    state="complete",
                    completed_at=old - timedelta(days=1),
                    fingerprint="c" * 64,
                ),
                "radar_newest_old": _run(
                    user,
                    client,
                    state="partial",
                    completed_at=old + timedelta(hours=1),
                    fingerprint="c" * 64,
                ),
                # A failure never protects itself, even as the newest run.
                "radar_failed_only": _run(
                    user, client, state="failed", completed_at=old, fingerprint="d" * 64
                ),
                # Legacy finished row without completed_at: created_at decides.
                "radar_legacy": _run(
                    user, client, state="failed", created_at=old, fingerprint="e" * 64
                ),
                # Active runs are never touched, however old.
                "active_queued": _run(
                    user, client, state="queued", created_at=old, **j
                ),
                "active_running": _run(
                    user, client, state="running", created_at=old, fingerprint="f" * 64
                ),
            }
            db.add_all(runs.values())
            await db.flush()

            expired = set(
                await retention.expired_run_ids(db, cutoff=cutoff, limit=10_000)
            )
            ids = {name: run.id for name, run in runs.items()}
            assert {
                ids["job_old_complete"],
                ids["job_old_failed"],
                ids["closed_job_only"],
                ids["job_only_beyond_cap"],
                ids["radar_only_old"],
                ids["radar_older"],
                ids["radar_failed_only"],
                ids["radar_legacy"],
            } <= expired
            assert (
                not {
                    ids["job_recent"],
                    ids["other_author_only"],
                    ids["radar_newest_old"],
                    ids["active_queued"],
                    ids["active_running"],
                }
                & expired
            )
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_purge_deletes_results_in_batches_then_the_run_and_prune_honours_cutoff(
    monkeypatch,
):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)
    recent = now - timedelta(days=1)
    unique = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        user = User(
            name="Purge",
            email=f"purge-{unique}@example.com",
            password_hash="unused",
            role=UserRole.admin,
            is_active=True,
        )
        client = Client(name=f"Purge client {unique}")
        db.add_all([user, client])
        await db.flush()
        expired = _run(
            user, client, state="complete", completed_at=old, fingerprint="1" * 64
        )
        newest = _run(
            user, client, state="complete", completed_at=old, fingerprint="2" * 64
        )
        older = _run(
            user,
            client,
            state="partial",
            completed_at=old - timedelta(days=1),
            fingerprint="2" * 64,
        )
        # `expired` is protected as the newest of its request until a newer
        # result arrives; make it the older one of a pair instead.
        replacement = _run(
            user, client, state="complete", completed_at=recent, fingerprint="1" * 64
        )
        db.add_all([expired, newest, older, replacement])
        await db.flush()
        for run in (expired, older):
            db.add_all(
                CandidateSearchResult(
                    run_id=run.id,
                    candidate_id=cid,
                    candidate_version="v1",
                    state="evaluated",
                )
                for cid in range(1, 8)
            )
        await db.commit()
        user_id, client_id = user.id, client.id
        all_ids = [expired.id, newest.id, older.id, replacement.id]

    try:
        async with AsyncSessionLocal() as db:
            # Batches smaller than the row count: several commits, one run.
            assert await retention.purge_run(db, expired.id, batch_size=3) == 7
        async with AsyncSessionLocal() as db:
            assert await db.get(CandidateSearchRun, expired.id) is None
            assert not await db.scalar(
                select(func.count())
                .select_from(CandidateSearchResult)
                .where(CandidateSearchResult.run_id == expired.id)
            )

        # The full cycle with the real selection. Ad hoc runs are protected ONE
        # per author, so only `replacement` (the author's newest) survives —
        # `newest` belonged to another request, which is no longer a partition.
        # Other suites may have committed their own old runs; the assertion is
        # about ours, the limit only bounds work.
        monkeypatch.setattr(retention, "RUNS_PER_CYCLE", 10_000)
        stats = await retention.prune_once(days=7, now=now)
        assert stats["runs"] >= 2 and stats["results"] >= 7
        async with AsyncSessionLocal() as db:
            left = set(
                await db.scalars(
                    select(CandidateSearchRun.id).where(
                        CandidateSearchRun.id.in_(all_ids)
                    )
                )
            )
        assert left == {replacement.id}
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateSearchRun).where(CandidateSearchRun.id.in_(all_ids))
            )
            await db.execute(delete(Client).where(Client.id == client_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


@pytest.mark.asyncio
async def test_disabled_retention_returns_before_the_loop(monkeypatch):
    monkeypatch.setattr(settings, "CANDIDATE_SEARCH_RETENTION_ENABLED", False)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("a disabled loop must not wait or prune")

    monkeypatch.setattr(retention.asyncio, "sleep", forbidden)
    monkeypatch.setattr(retention, "prune_once", forbidden)
    await retention.candidate_search_retention_loop()
