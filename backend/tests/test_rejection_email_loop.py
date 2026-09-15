"""`rejection_email_loop._tick` — which queued rejection e-mails get dispatched.

Behavioural against the real Postgres: rows are seeded in
``scheduled_rejection_emails`` and ``dispatch`` is replaced with a recorder, so
the test proves the SELECT (status, due time, ordering, batch limit) and the
per-row isolation of the loop, not the Graph send itself.

The database is shared across the run and never cleaned, so the seeded due
rows sit a century in the past: ordering is ``scheduled_at ASC``, which keeps
them at the head of the queue regardless of what other suites left behind.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.rejection_email import RejectionEmailStatus, ScheduledRejectionEmail
from app.models.user import User, UserRole
from app.tasks import rejection_email_loop as loop_mod


_CENTURY = timedelta(days=36500)


async def _seed_queue(
    *, due_offsets_minutes: list[int], future: int, cancelled_due: int
) -> dict:
    """Seed one candidate/job and one scheduled e-mail per stage row.

    ``due_offsets_minutes`` — due pending rows, minutes after "a century ago"
    (smaller = older = dispatched first). ``future`` pending rows are not due
    yet; ``cancelled_due`` rows are due but not pending.
    """
    u = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rej-loop-{u}@example.com",
            password_hash=hash_password("x"),
            name="Rej Loop",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"RejLoop {u}")
        cand = Candidate(
            name="Rej", lastname=f"Loop-{u}", email=f"cand-{u}@example.com"
        )
        db.add_all([user, client, cand])
        await db.flush()
        job = Job(
            title=f"RejLoop job {u}", status=JobStatus.published, client_id=client.id
        )
        db.add(job)
        await db.flush()

        plan: list[tuple[str, datetime, RejectionEmailStatus]] = []
        for off in due_offsets_minutes:
            plan.append(
                (
                    "due",
                    now - _CENTURY + timedelta(minutes=off),
                    RejectionEmailStatus.pending,
                )
            )
        for i in range(future):
            plan.append(
                ("future", now + timedelta(hours=1 + i), RejectionEmailStatus.pending)
            )
        for i in range(cancelled_due):
            plan.append(
                (
                    "cancelled",
                    now - _CENTURY - timedelta(minutes=1 + i),
                    RejectionEmailStatus.cancelled,
                )
            )

        ids: dict[str, list[int]] = {"due": [], "future": [], "cancelled": []}
        for kind, when, status in plan:
            stage = CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.rejected,
                moved_at=now,
            )
            db.add(stage)
            await db.flush()
            mail = ScheduledRejectionEmail(
                candidate_stage_id=stage.id,
                candidate_id=cand.id,
                job_id=job.id,
                recruiter_id=user.id,
                to_email=f"cand-{u}@example.com",
                subject="Dziękujemy",
                body_html="<p>x</p>",
                status=status,
                scheduled_at=when,
            )
            db.add(mail)
            await db.flush()
            ids[kind].append(mail.id)
        await db.commit()
        return {
            "ids": ids,
            "user_id": user.id,
            "client_id": client.id,
            "candidate_id": cand.id,
            "job_id": job.id,
        }


async def _cleanup(seed: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ScheduledRejectionEmail).where(
                ScheduledRejectionEmail.candidate_id == seed["candidate_id"]
            )
        )
        await db.execute(
            delete(CandidateStage).where(CandidateStage.job_id == seed["job_id"])
        )
        await db.execute(delete(Job).where(Job.id == seed["job_id"]))
        await db.execute(delete(Candidate).where(Candidate.id == seed["candidate_id"]))
        await db.execute(delete(Client).where(Client.id == seed["client_id"]))
        await db.execute(delete(User).where(User.id == seed["user_id"]))
        await db.commit()


async def test_tick_dispatches_due_pending_rows_in_their_own_session(monkeypatch):
    seed = await _seed_queue(due_offsets_minutes=[0, 1, 2], future=1, cancelled_due=1)
    dispatched: list[int] = []
    sessions: list[object] = []

    async def _fake_dispatch(db, row_id):
        sessions.append(db)  # keep a reference so ids cannot be recycled
        dispatched.append(row_id)

    monkeypatch.setattr(loop_mod, "dispatch", _fake_dispatch)
    monkeypatch.setattr(loop_mod.asyncio, "sleep", AsyncMock())
    try:
        await loop_mod._tick()
    finally:
        await _cleanup(seed)

    ids = seed["ids"]
    assert dispatched[: len(ids["due"])] == ids["due"], "oldest due rows first"
    assert not set(ids["future"]) & set(dispatched), "not-due rows are skipped"
    assert not set(ids["cancelled"]) & set(dispatched), "non-pending rows are skipped"
    assert len(dispatched) <= loop_mod.BATCH_LIMIT
    assert len({id(s) for s in sessions}) == len(sessions), (
        "each id gets a fresh session"
    )


async def test_tick_respects_batch_limit(monkeypatch):
    seed = await _seed_queue(due_offsets_minutes=[0, 1, 2], future=0, cancelled_due=0)
    dispatched: list[int] = []

    async def _fake_dispatch(db, row_id):
        dispatched.append(row_id)

    monkeypatch.setattr(loop_mod, "BATCH_LIMIT", 2)
    monkeypatch.setattr(loop_mod, "dispatch", _fake_dispatch)
    monkeypatch.setattr(loop_mod.asyncio, "sleep", AsyncMock())
    try:
        await loop_mod._tick()
    finally:
        await _cleanup(seed)

    assert dispatched == seed["ids"]["due"][:2]


async def test_failure_on_one_row_does_not_stop_the_rest(monkeypatch):
    seed = await _seed_queue(due_offsets_minutes=[0, 1, 2], future=0, cancelled_due=0)
    due = seed["ids"]["due"]
    attempted: list[int] = []

    async def _flaky_dispatch(db, row_id):
        attempted.append(row_id)
        if row_id == due[0]:
            raise RuntimeError("graph exploded")

    sleep = AsyncMock()
    monkeypatch.setattr(loop_mod, "dispatch", _flaky_dispatch)
    monkeypatch.setattr(loop_mod.asyncio, "sleep", sleep)
    try:
        await loop_mod._tick()
    finally:
        await _cleanup(seed)

    assert attempted[:3] == due, "rows after the failing one are still dispatched"
    assert sleep.await_count == len(attempted), "stagger after every row, failed or not"


async def test_cancellation_inside_dispatch_propagates(monkeypatch):
    seed = await _seed_queue(due_offsets_minutes=[0, 1], future=0, cancelled_due=0)

    monkeypatch.setattr(
        loop_mod, "dispatch", AsyncMock(side_effect=asyncio.CancelledError)
    )
    monkeypatch.setattr(loop_mod.asyncio, "sleep", AsyncMock())
    try:
        with pytest.raises(asyncio.CancelledError):
            await loop_mod._tick()
    finally:
        await _cleanup(seed)


async def test_loop_survives_a_failing_tick(monkeypatch):
    tick = AsyncMock(side_effect=[RuntimeError("db down"), None])
    sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError])
    monkeypatch.setattr(loop_mod, "_tick", tick)
    monkeypatch.setattr(loop_mod.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await loop_mod.rejection_email_loop()

    assert tick.await_count == 2, "a crashed tick must not end the loop"
    assert [c.args for c in sleep.await_args_list] == [
        (loop_mod.GRACE_PERIOD_SECONDS,),
        (loop_mod.TICK_INTERVAL_SECONDS,),
        (loop_mod.TICK_INTERVAL_SECONDS,),
    ]


async def test_rows_are_left_pending_by_tick_itself(monkeypatch):
    """`_tick` only schedules work; state transitions belong to `dispatch`."""
    seed = await _seed_queue(due_offsets_minutes=[0], future=0, cancelled_due=0)
    monkeypatch.setattr(loop_mod, "dispatch", AsyncMock())
    monkeypatch.setattr(loop_mod.asyncio, "sleep", AsyncMock())
    try:
        await loop_mod._tick()
        async with AsyncSessionLocal() as db:
            status = await db.scalar(
                select(ScheduledRejectionEmail.status).where(
                    ScheduledRejectionEmail.id == seed["ids"]["due"][0]
                )
            )
        assert status == RejectionEmailStatus.pending
    finally:
        await _cleanup(seed)
