"""Two consistency fixes, DB-backed (real Postgres in CI).

1. ``candidate_stage_cv_service.create_original_cv_snapshot`` used to
   ``db.rollback()`` the CALLER's shared session when a concurrent snapshot
   insert lost the UNIQUE race — discarding the whole business operation (the
   new CandidateStage + the rest of a bulk batch). Same class as M3-TX-01. It
   now inserts inside a SAVEPOINT (``begin_nested``): the concurrent-duplicate
   IntegrityError rolls back ONLY the snapshot insert, the caller's transaction
   survives, and exactly one snapshot remains.

2. ``contract_alerts`` deduped notifications with a non-atomic
   SELECT-then-INSERT, so overlapping / concurrent loop passes could insert
   DUPLICATE alerts. It now atomically claims each (category, threshold, entity)
   via ``contract_alert_dedup`` + ``INSERT ... ON CONFLICT DO NOTHING`` before
   creating the notifications.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services import candidate_stage_cv_service
from app.services.candidate_stage_cv_service import create_original_cv_snapshot
from app.tasks import contract_alerts
from app.tasks.contract_alerts import _claim_alert, run_contract_alerts_cycle


# ── Finding 1: CV-snapshot SAVEPOINT keeps the caller's transaction ───────────


async def test_concurrent_snapshot_race_preserves_caller_txn(monkeypatch) -> None:
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"cvtx-{u}@example.com",
            password_hash=hash_password("x"),
            name="Rec",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"CvTx {u}")
        cand = Candidate(name="Orig", lastname=f"Snap-{u}")
        db.add_all([user, client, cand])
        await db.flush()
        job = Job(title=f"CvTx Job {u}", client_id=client.id)
        db.add(job)
        await db.flush()
        stage = CandidateStage(candidate_id=cand.id, job_id=job.id, moved_by=user.id)
        db.add(stage)
        await db.commit()
        cand_id, stage_id, job_id = cand.id, job.id, stage.id

    marker = f"SURVIVED-{u}"

    # Simulate a concurrent create_stage that inserts the snapshot AFTER our
    # pre-check but BEFORE our flush — the exact UNIQUE race. Hook it onto
    # get_current_cv, which runs in that window.
    async def _racing_get_current_cv(db, candidate):
        async with AsyncSessionLocal() as other:
            other.add(
                CandidateStageCV(
                    candidate_stage_id=stage_id,
                    candidate_id=cand_id,
                    job_id=job_id,
                    original_snapshot_source="concurrent_race",
                )
            )
            await other.commit()
        return None

    monkeypatch.setattr(
        candidate_stage_cv_service, "get_current_cv", _racing_get_current_cv
    )

    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, cand_id)
        cand.name = marker  # unrelated business write on the caller's session
        stage = await db.get(CandidateStage, stage_id)

        # Loses the UNIQUE race → must NOT roll back the caller's session.
        row = await create_original_cv_snapshot(db, stage)
        assert row.candidate_stage_id == stage_id

        # The caller can still commit — the transaction was never aborted.
        await db.commit()

    async with AsyncSessionLocal() as db:
        survived = await db.scalar(
            select(Candidate.name).where(Candidate.id == cand_id)
        )
        snaps = await db.scalar(
            select(func.count(CandidateStageCV.id)).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
    assert survived == marker, (
        "aux snapshot writer rolled back the caller's business write"
    )
    assert snaps == 1, f"snapshot invariant broken: expected exactly 1, got {snaps}"


# ── Finding 2: contract_alerts atomic dedup ───────────────────────────────────


async def test_claim_alert_is_atomic_dedup() -> None:
    key = f"ending:30:test-{uuid.uuid4().hex[:12]}"
    async with AsyncSessionLocal() as db:
        first = await _claim_alert(db, key)
        await db.commit()
    async with AsyncSessionLocal() as db:
        second = await _claim_alert(db, key)
        await db.commit()
    assert first is True, "first claim of a fresh key must win"
    assert second is False, "second claim of the same key must lose (ON CONFLICT)"


async def test_contract_alerts_dedup_survives_racing_prefilter(monkeypatch) -> None:
    """The real race: neuter the SELECT pre-filter so BOTH passes think nothing
    was notified (exactly what overlapping / restarted loop passes see). Only
    the atomic ON CONFLICT claim can now stop duplicate notifications."""
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        staff = User(
            email=f"alertstaff-{u}@example.com",
            password_hash=hash_password("x"),
            name="DL",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        client = Client(name=f"Alert {u}")
        cand = Candidate(name="C", lastname=f"Alert-{u}")
        db.add_all([staff, client, cand])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            end_date=date.today() + timedelta(days=30),  # falls in the 30d window
        )
        db.add(contract)
        await db.commit()
        staff_uid, contract_id = staff.id, contract.id

    # Pre-filter always reports "nothing notified" → forces both passes to reach
    # the claim, reproducing the concurrent-pass race the fix targets.
    async def _no_prefilter(db, threshold):
        return set()

    monkeypatch.setattr(
        contract_alerts, "_contract_ids_already_notified", _no_prefilter
    )

    def _count_my_alerts(db):
        return db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == staff_uid,
                Notification.related_entity_type == "contract",
                Notification.related_entity_id == contract_id,
                Notification.notification_type.in_(
                    [
                        NotificationType.contract_ending,
                        NotificationType.contract_ending_90d,
                    ]
                ),
            )
        )

    await run_contract_alerts_cycle()
    async with AsyncSessionLocal() as db:
        after_first = await _count_my_alerts(db)

    await run_contract_alerts_cycle()  # racing second pass
    async with AsyncSessionLocal() as db:
        after_second = await _count_my_alerts(db)

    assert after_first == 1, (
        f"first pass should create exactly one alert for the staff user, "
        f"got {after_first}"
    )
    assert after_second == 1, (
        f"second (racing) pass duplicated the alert — atomic claim failed "
        f"(got {after_second})"
    )
