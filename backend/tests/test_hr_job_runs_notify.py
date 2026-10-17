"""Wspólne rezerwacje przebiegów (``hr/job_runs``) i powiadomienia (``hr/notify``)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.hr_ops import HrJobRun
from app.models.notification import NotificationType
from app.services.hr import job_runs, notify


def _kind() -> str:
    return f"test_{uuid.uuid4().hex[:10]}"


@pytest.mark.asyncio
async def test_claim_once_then_none_while_running_and_after_done() -> None:
    kind = _kind()
    async with AsyncSessionLocal() as db:
        now = local_now()
        first = await job_runs.claim(db, kind, "2026-10-17", now)
        assert first is not None
        assert await job_runs.claim(db, kind, "2026-10-17", now) is None
        await job_runs.finish(db, first, status="done", counts={"sent": 2})
        assert await job_runs.claim(db, kind, "2026-10-17", now) is None
        row = await db.get(HrJobRun, first)
        await db.refresh(row)
        assert (row.status, row.counts, row.finished_at is not None) == (
            "done",
            {"sent": 2},
            True,
        )


@pytest.mark.asyncio
async def test_claim_retakes_failed_and_stale_but_done_only_on_request() -> None:
    kind = _kind()
    async with AsyncSessionLocal() as db:
        now = local_now()
        run_id = await job_runs.claim(db, kind, "p", now)
        await job_runs.finish(db, run_id, status="failed", counts={}, error="x")
        assert await job_runs.claim(db, kind, "p", now) == run_id

        # Porzucona rezerwacja (proces padł) — po STALE_CLAIM wolno przejąć.
        await db.execute(
            update(HrJobRun)
            .where(HrJobRun.id == run_id)
            .values(claimed_at=now - job_runs.STALE_CLAIM - timedelta(minutes=1))
        )
        await db.commit()
        assert await job_runs.claim(db, kind, "p", now) == run_id

        await job_runs.finish(db, run_id, status="done", counts={})
        assert await job_runs.claim(db, kind, "p", now) is None
        assert await job_runs.claim(db, kind, "p", now, retake_done=True) == run_id


@pytest.mark.asyncio
async def test_mark_once_is_true_only_the_first_time_and_needs_caller_commit() -> None:
    kind = _kind()
    async with AsyncSessionLocal() as db:
        assert await job_runs.mark_once(db, kind, "user:7") is True
        assert await job_runs.mark_once(db, kind, "user:7") is False
        await db.rollback()
        # Bez commitu wołającego znacznika nie ma — wchodzi razem z pracą.
        assert await job_runs.mark_once(db, kind, "user:7") is True
        await db.commit()
        rows = await db.scalars(select(HrJobRun).where(HrJobRun.kind == kind))
        assert [row.status for row in rows] == ["done"]


@pytest.mark.asyncio
async def test_notify_each_dedupes_skips_and_survives_one_failing_recipient(
    monkeypatch,
) -> None:
    calls: list[int] = []

    async def fake_emit(db, *, user_id, **kwargs):  # noqa: ANN001
        calls.append(user_id)
        if user_id == 2:
            raise RuntimeError("awaria jednego odbiorcy")
        return object() if user_id != 4 else None  # 4 = duplikat dobowy

    monkeypatch.setattr("app.services.notification_triggers.emit", fake_emit)
    async with AsyncSessionLocal() as db:
        sent = await notify.notify_each(
            db,
            [1, 2, 1, None, 3, 4, 5],
            exclude=[5, None],
            title="t",
            message="m",
            ntype=NotificationType.hr_leave_decided,
            link="/my-time",
        )
    assert calls == [1, 2, 3, 4]
    assert sent == 2


@pytest.mark.asyncio
async def test_switched_off_loops_answer_the_same_disabled_status() -> None:
    """Wyłączony moduł albo tryb ``off`` = ``{"status": "disabled"}`` w każdej
    pętli (wcześniej trzy kształty: ``skipped``, ``status: module_off``, ``mode``)."""

    from datetime import datetime, timezone

    from app.models.app_setting import AppSetting
    from app.services.hr import lifecycle_jobs, payroll_jobs, student_reminders
    from app.services.hr.m365 import executor, profile_sync, reconcile
    from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

    disabled = {"status": "disabled"}
    morning = datetime(2091, 3, 5, 9, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        previous = None if row is None else row.value
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value={}))
        await db.flush()
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        row.value = {key: False for key in HR_MODULE_KEYS}
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            assert await lifecycle_jobs.run_once(db) == disabled
            assert await payroll_jobs.run_once(db) == disabled
            assert (
                await student_reminders.student_contribution_reminders(
                    db, today=morning.date()
                )
                == disabled
            )
            assert (
                await profile_sync.run_once(db, mode="simulate", now=morning)
                == disabled
            )
            for loop in (executor, reconcile, profile_sync):
                assert await loop.run_once(db, mode="off", now=morning) == disabled
    finally:
        async with AsyncSessionLocal() as db:
            row = await db.get(AppSetting, HR_MODULES_SETTING)
            row.value = previous or {key: False for key in HR_MODULE_KEYS}
            await db.commit()
