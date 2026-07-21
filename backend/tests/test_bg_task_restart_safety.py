"""Restart / multi-worker safety for three background loops (audyt P1/P2).

The bug shape shared by all three: dedup / claim state lived only in an
in-process ``set`` that reset on every restart (Coolify rebuilds on each push)
and diverged per uvicorn worker. Result: reminders/alerts re-sent on restart and
duplicated across workers; LinkedIn syncs double-paid across workers.

Fixes make the dedup DURABLE (a stamp persisted on the row) and the send ATOMIC
(``SELECT ... FOR UPDATE SKIP LOCKED``). These tests run against real Postgres
and assert that a SECOND loop pass — simulating a restart with fresh in-memory
state — does NOT re-send/re-alert, and that a concurrent claim can't double-pick
the same LinkedIn candidate.

Fixtures follow the `test_rejection_email_integration.py` pattern: ORM for
candidates/users, raw SQL for jobs/clients (ORM `Job` has newer columns than the
local/CI schema), explicit FK-ordered cleanup.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate, CandidateStatus
from app.models.notification import Notification
from app.models.pipeline_template import PipelineStageDef, StageCategoryEnum
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole


# ── Finding 1: calendar T-15min reminder ────────────────────────────────────


@pytest_asyncio.fixture
async def calendar_seed():
    """A creator user + a scheduled event inside the T-15min reminder window."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        creator = User(
            email=f"cal-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="Cal Creator",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(creator)
        await db.flush()

        event = CalendarEvent(
            title=f"Interview {suffix}",
            event_type=EventType.interview,
            start_time=datetime.now(timezone.utc) + timedelta(minutes=15),
            status=EventStatus.scheduled,
            created_by=creator.id,
        )
        db.add(event)
        await db.commit()
        ids = {"user_id": creator.id, "event_id": event.id}

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM notifications WHERE user_id = :uid"),
            {"uid": ids["user_id"]},
        )
        await db.execute(
            text("DELETE FROM calendar_events WHERE id = :eid"),
            {"eid": ids["event_id"]},
        )
        await db.execute(
            text("DELETE FROM users WHERE id = :uid"), {"uid": ids["user_id"]}
        )
        await db.commit()


async def _count_reminder_notifications(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return len(
            (
                await db.scalars(
                    select(Notification.id).where(Notification.user_id == user_id)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_calendar_reminder_sends_once_and_stamps(calendar_seed):
    """First dispatch sends the reminder and persists reminder_sent_at."""
    from app.api.calendar import _dispatch_reminder

    ids = calendar_seed
    with patch("app.api.ws.notify_user", new=AsyncMock()) as ws_push:
        await _dispatch_reminder(ids["event_id"])

    assert ws_push.await_count == 1
    assert await _count_reminder_notifications(ids["user_id"]) == 1

    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, ids["event_id"])
        assert event.reminder_sent_at is not None


@pytest.mark.asyncio
async def test_calendar_reminder_not_resent_after_restart(calendar_seed):
    """A second pass (fresh in-memory state, i.e. a restart) must NOT re-send —
    the durable reminder_sent_at stamp survives and blocks the resend."""
    from app.api.calendar import _dispatch_reminder

    ids = calendar_seed
    with patch("app.api.ws.notify_user", new=AsyncMock()):
        await _dispatch_reminder(ids["event_id"])
    # Simulate restart: process died, in-memory dedup gone. Loop re-scans and
    # dispatches again for the same event id.
    with patch("app.api.ws.notify_user", new=AsyncMock()) as ws_push2:
        await _dispatch_reminder(ids["event_id"])

    assert ws_push2.await_count == 0  # no second push
    assert await _count_reminder_notifications(ids["user_id"]) == 1  # no duplicate


@pytest.mark.asyncio
async def test_calendar_reminder_loop_scan_excludes_stamped(calendar_seed):
    """The loop's own SELECT filters out already-stamped events, so a restarted
    loop never even hands a sent event to the dispatcher."""
    from app.api.calendar import _dispatch_reminder

    ids = calendar_seed
    with patch("app.api.ws.notify_user", new=AsyncMock()):
        await _dispatch_reminder(ids["event_id"])

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        due_ids = (
            await db.scalars(
                select(CalendarEvent.id).where(
                    CalendarEvent.start_time >= now + timedelta(minutes=14),
                    CalendarEvent.start_time <= now + timedelta(minutes=16),
                    CalendarEvent.status == EventStatus.scheduled,
                    CalendarEvent.reminder_sent_at.is_(None),
                )
            )
        ).all()
    assert ids["event_id"] not in due_ids


# ── Finding 2: Slack SLA-breach alert ───────────────────────────────────────


@pytest_asyncio.fixture
async def sla_seed():
    """A candidate parked past SLA on a stage_def with sla_max_days=5."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"sla-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="SLA Recruiter",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(recruiter)
        await db.flush()

        candidate = Candidate(
            name="Jan",
            lastname=f"Sla{suffix}",
            email=f"sla-cand-{suffix}@example.com",
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.flush()

        client_id = (
            await db.execute(
                text("INSERT INTO clients (name) VALUES (:name) RETURNING id"),
                {"name": f"Client {suffix}"},
            )
        ).scalar_one()
        job_id = (
            await db.execute(
                text(
                    "INSERT INTO jobs "
                    "(title, status, priority, recruiter_id, client_id, "
                    " recruitment_type, remote_policy) "
                    "VALUES (:title, 'published', 'medium', :rec, :client, "
                    "        'body_leasing', 'hybrid') RETURNING id"
                ),
                {"title": f"Role {suffix}", "rec": recruiter.id, "client": client_id},
            )
        ).scalar_one()

        # A template row is required by the stage_def FK.
        template_id = (
            await db.execute(
                text(
                    "INSERT INTO pipeline_templates (name) VALUES (:name) RETURNING id"
                ),
                {"name": f"Tmpl {suffix}"},
            )
        ).scalar_one()

        stage_def = PipelineStageDef(
            template_id=template_id,
            name=f"Interview {suffix}",
            order=1,
            category=StageCategoryEnum.internal,
            is_terminal=False,
            sla_max_days=5,
        )
        db.add(stage_def)
        await db.flush()

        stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=job_id,
            stage=PipelineStage.interview,
            stage_def_id=stage_def.id,
            moved_at=datetime.now(timezone.utc) - timedelta(days=30),  # 30d > 5d SLA
            moved_by=recruiter.id,
        )
        db.add(stage)
        await db.commit()

        ids = {
            "recruiter_id": recruiter.id,
            "candidate_id": candidate.id,
            "client_id": client_id,
            "job_id": job_id,
            "template_id": template_id,
            "stage_def_id": stage_def.id,
            "stage_id": stage.id,
        }

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM candidate_stages WHERE id = :sid"),
            {"sid": ids["stage_id"]},
        )
        await db.execute(
            text("DELETE FROM pipeline_stage_defs WHERE id = :sdid"),
            {"sdid": ids["stage_def_id"]},
        )
        await db.execute(
            text("DELETE FROM pipeline_templates WHERE id = :tid"),
            {"tid": ids["template_id"]},
        )
        await db.execute(
            text("DELETE FROM candidates WHERE id = :cid"),
            {"cid": ids["candidate_id"]},
        )
        await db.execute(
            text("DELETE FROM jobs WHERE id = :jid"), {"jid": ids["job_id"]}
        )
        await db.execute(
            text("DELETE FROM clients WHERE id = :clid"), {"clid": ids["client_id"]}
        )
        await db.execute(
            text("DELETE FROM users WHERE id = :uid"), {"uid": ids["recruiter_id"]}
        )
        await db.commit()


async def _my_breach(candidate_id: int) -> dict:
    from app.tasks.slack_sla_alerts import _compute_breaches

    async with AsyncSessionLocal() as db:
        breaches = await _compute_breaches(db)
    mine = [b for b in breaches if b["candidate_id"] == candidate_id]
    assert len(mine) == 1, f"expected exactly one breach for candidate, got {mine}"
    return mine[0]


@pytest.mark.asyncio
async def test_slack_sla_alert_dispatch_stamps_on_success(sla_seed):
    """A successful dispatch posts to Slack once and stamps sla_alerted_at."""
    from app.tasks import slack_sla_alerts

    ids = sla_seed
    breach = await _my_breach(ids["candidate_id"])
    assert breach["sla_alerted_at"] is None

    with patch.object(
        slack_sla_alerts, "_post_to_slack", AsyncMock(return_value=True)
    ) as post:
        sent = await slack_sla_alerts._dispatch_alert("https://hook", breach)

    assert sent is True
    assert post.await_count == 1
    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateStage, ids["stage_id"])
        assert row.sla_alerted_at is not None


@pytest.mark.asyncio
async def test_slack_sla_alert_not_resent_after_restart(sla_seed):
    """Second pass with fresh in-memory state (restart) must NOT re-alert:
    the durable sla_alerted_at stamp drops the breach from the new-breach filter
    AND the dispatcher's own re-check refuses to post again."""
    from app.tasks import slack_sla_alerts

    ids = sla_seed
    breach = await _my_breach(ids["candidate_id"])
    with patch.object(slack_sla_alerts, "_post_to_slack", AsyncMock(return_value=True)):
        await slack_sla_alerts._dispatch_alert("https://hook", breach)

    # Fresh compute (as a restarted loop would): breach now carries the stamp,
    # so the loop's new-breach filter excludes it.
    breach2 = await _my_breach(ids["candidate_id"])
    assert breach2["sla_alerted_at"] is not None
    new_breaches = [b for b in [breach2] if b["sla_alerted_at"] is None]
    assert new_breaches == []

    # Defense-in-depth: even if a stale dict slipped through, the dispatcher
    # re-checks under the lock and refuses to post a second time.
    with patch.object(
        slack_sla_alerts, "_post_to_slack", AsyncMock(return_value=True)
    ) as post2:
        sent = await slack_sla_alerts._dispatch_alert("https://hook", breach2)
    assert sent is False
    assert post2.await_count == 0


@pytest.mark.asyncio
async def test_slack_sla_alert_failed_post_leaves_unstamped(sla_seed):
    """A non-2xx Slack response must NOT stamp the row, so the next tick retries."""
    from app.tasks import slack_sla_alerts

    ids = sla_seed
    breach = await _my_breach(ids["candidate_id"])
    with patch.object(
        slack_sla_alerts, "_post_to_slack", AsyncMock(return_value=False)
    ):
        sent = await slack_sla_alerts._dispatch_alert("https://hook", breach)

    assert sent is False
    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateStage, ids["stage_id"])
        assert row.sla_alerted_at is None  # un-stamped → retried next tick


# ── Finding 3: LinkedIn sync claim (FOR UPDATE SKIP LOCKED) ──────────────────


@pytest_asyncio.fixture
async def linkedin_seed():
    """A stale, active candidate eligible for a Proxycurl refresh."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Lin",
            lastname=f"Sync{suffix}",
            email=f"li-{suffix}@example.com",
            status=CandidateStatus.active,
            linkedin=f"https://www.linkedin.com/in/testuser-{suffix}",
            linkedin_synced_at=None,  # never synced → stale
        )
        db.add(candidate)
        await db.commit()
        cid = candidate.id

    yield cid

    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM candidates WHERE id = :cid"), {"cid": cid})
        await db.commit()


@pytest.mark.asyncio
async def test_linkedin_claim_blocks_second_worker(linkedin_seed):
    """Worker A's FOR UPDATE SKIP LOCKED claim must make worker B skip the same
    candidate — otherwise both workers pay for the same Proxycurl enrichment."""
    cid = linkedin_seed

    async with AsyncSessionLocal() as db_a:
        claimed_a = await db_a.scalar(
            select(Candidate)
            .where(Candidate.id == cid)
            .with_for_update(skip_locked=True)
        )
        assert claimed_a is not None  # worker A holds the row lock (uncommitted)

        # Worker B, concurrently, tries to claim the SAME candidate.
        async with AsyncSessionLocal() as db_b:
            claimed_b = await db_b.scalar(
                select(Candidate)
                .where(Candidate.id == cid)
                .with_for_update(skip_locked=True)
            )
        # B is skipped: the row is locked by A → no double Proxycurl call.
        assert claimed_b is None
        # A rolls back on context exit (no real sync in this claim test).


@pytest.mark.asyncio
async def test_linkedin_claim_available_when_unlocked(linkedin_seed):
    """Sanity: with no competing lock, the claim returns the candidate."""
    cid = linkedin_seed
    async with AsyncSessionLocal() as db:
        claimed = await db.scalar(
            select(Candidate)
            .where(Candidate.id == cid)
            .with_for_update(skip_locked=True)
        )
        assert claimed is not None
        assert claimed.id == cid
