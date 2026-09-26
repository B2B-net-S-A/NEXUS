"""Runda 7 audytu (N7-5): backfill członkostw w pulach talentów.

Do rundy 7 błąd `IntegrityError` jednego wiersza robił `db.rollback()` CAŁEJ
sesji: przepadały niezacommitowane członkostwa z paczki (policzone już jako
`added`), a leniwe doczytanie wygaszonego wiersza kończyło bieg
`MissingGreenlet`. Każde ponowne uruchomienie dopisywało też `Activity`
„nic się nie zmieniło” dla całej historii `cv_sent`.
Prawdziwy Postgres; dane z unikalnym, dalekim rokiem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import talent_pool_backfill as backfill
from app.services.talent_pool_auto_add import AutoAddResult

pytestmark = pytest.mark.asyncio

# Rok, którego nie używa żaden inny test — bieg czyta `moved_at >= since`.
_SINCE = datetime(2187, 1, 1, tzinfo=timezone.utc)


async def _stages(count: int) -> tuple[str, list[int]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Backfill r7 {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Backfill r7 {tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.flush()
        ids = []
        for index in range(count):
            cand = Candidate(
                name="Backfill",
                lastname=f"R7-{tag}-{index}",
                email=f"bf-r7-{tag}-{index}@example.com",
            )
            db.add(cand)
            await db.flush()
            ids.append(cand.id)
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=_SINCE.replace(day=1 + index),
                )
            )
        await db.commit()
    return tag, ids


async def test_one_failing_row_does_not_roll_back_the_rest_of_the_batch(
    monkeypatch,
) -> None:
    tag, ids = await _stages(3)
    calls: list[int] = []

    async def fake_add(*, db, candidate_id, job, log_noops, **_kw):
        calls.append(candidate_id)
        if candidate_id == ids[1]:
            raise IntegrityError("INSERT", {}, Exception("fk"))
        db.add(
            Activity(
                entity_type="talent_pool",
                entity_id=0,
                action="r7_backfill_probe",
                details={"tag": tag, "candidate_id": candidate_id},
            )
        )
        return AutoAddResult(status="added", pool_name=f"R7 {tag}")

    monkeypatch.setattr(backfill, "auto_add_on_cv_sent", fake_add)

    stats = await backfill.run_membership_backfill(since=_SINCE, commit=True)

    mine = [c for c in calls if c in ids]
    # Drugi wiersz próbowany dwa razy (ponowienie), reszta raz.
    assert mine == [ids[0], ids[1], ids[1], ids[2]]
    assert stats["errors"] >= 1
    async with AsyncSessionLocal() as db:
        saved = (
            await db.execute(
                select(Activity.details).where(Activity.action == "r7_backfill_probe")
            )
        ).scalars()
        saved_ids = sorted(
            d["candidate_id"] for d in saved if (d or {}).get("tag") == tag
        )
    # Zapis z wiersza sprzed błędu przetrwał — dawniej rollback sesji go cofał.
    assert saved_ids == [ids[0], ids[2]]


async def test_rerun_asks_for_no_noop_activity(monkeypatch) -> None:
    _tag, ids = await _stages(1)
    seen: list[bool] = []

    async def fake_add(*, candidate_id, log_noops, **_kw):
        if candidate_id in ids:
            seen.append(log_noops)
        return AutoAddResult(status="already_in_pool")

    monkeypatch.setattr(backfill, "auto_add_on_cv_sent", fake_add)

    await backfill.run_membership_backfill(since=_SINCE, commit=True)

    assert seen == [False]
