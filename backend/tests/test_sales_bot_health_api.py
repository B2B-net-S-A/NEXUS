"""Select real latest attempts across kinds and public/Cognism people channels."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.api.sales_bots import _latest_runs
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesSignalRun


@pytest.mark.asyncio
async def test_latest_attempts_ignore_stats_window_and_keep_people_channels_separate():
    async with AsyncSessionLocal() as db:
        # Roll back the test rows. Start after existing fixture data so this test
        # can share the suite database without deleting anybody else's rows.
        previous = await db.scalar(select(func.max(SalesSignalRun.started_at)))
        base = max(
            previous or datetime.now(timezone.utc), datetime.now(timezone.utc)
        ) + timedelta(days=1)
        attempts = [
            SalesSignalRun(
                kind="signals",
                status="received",
                started_at=base,
                request={},
                report={"leads": 1},
            ),
            SalesSignalRun(
                kind="winback",
                status="expired",
                started_at=base + timedelta(minutes=1),
                request={},
                report={},
            ),
            SalesSignalRun(
                kind="question",
                status="received",
                started_at=base,
                request={},
                report={"results_new": 1},
            ),
            SalesSignalRun(
                kind="people",
                status="received",
                started_at=base,
                request={"source": "public"},
                report={"added": 1},
            ),
            SalesSignalRun(
                kind="people",
                status="started",
                started_at=base + timedelta(minutes=1),
                request={"source": "cognism"},
                report={},
            ),
        ]
        db.add_all(attempts)
        await db.flush()
        try:
            latest = await _latest_runs(db, now=base + timedelta(days=30))
            assert latest["leads"].id == attempts[1].id
            assert latest["leads"].outcome == "expired"
            assert (
                latest["research"].id == attempts[2].id
            )  # older than 7d, still visible
            assert latest["contacts"].id == attempts[3].id
            assert latest["contacts"].outcome == "saved"
            assert latest["cognism"].id == attempts[4].id
            assert latest["cognism"].outcome == "waiting"
        finally:
            await db.rollback()
