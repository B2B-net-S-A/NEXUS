"""Sondy `/api/health` modułów HR (``app/services/hr/health.py``).

Każdy test działa w transakcji wycofywanej na końcu: czyści tabelę sondy, wkłada
swoje wiersze i sprawdza werdykt — cudze wiersze z innych testów nie przeszkadzają.
Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.admin_case import AdminMailIngestState
from app.models.app_setting import AppSetting
from app.models.hr_leave import HrM365Operation
from app.models.hr_ops import HrJobRun
from app.models.user import User, UserRole
from app.services.hr import health
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

NOW = datetime(2091, 3, 7, 12, 0, tzinfo=timezone.utc)


async def _user(db) -> User:
    user = User(
        email=f"probe-{uuid.uuid4().hex[:10]}@example.com",
        name="Osoba Przykładowa",
        role=UserRole.recruiter,
        roles=["recruiter"],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _op(user_id: int, status: str, *, created_at: datetime, next_attempt_at: datetime):
    return HrM365Operation(
        user_id=user_id,
        kind="set_oof",
        dedupe_key=f"probe:{uuid.uuid4().hex}",
        payload={},
        status=status,
        next_attempt_at=next_attempt_at,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_m365_probe(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HR_M365_MODE", "simulate")
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(delete(HrM365Operation))
            user = await _user(db)
            # Zrobione i świeżo zaplanowane = zdrowo.
            db.add(_op(user.id, "done", created_at=NOW, next_attempt_at=NOW))
            db.add(
                _op(
                    user.id,
                    "pending",
                    created_at=NOW,
                    next_attempt_at=NOW - timedelta(minutes=5),
                )
            )
            await db.flush()
            assert await health.m365_state(db, now=NOW) == "healthy"

            # Stara porażka sprzed tygodnia już nie alarmuje.
            db.add(
                _op(
                    user.id,
                    "failed",
                    created_at=NOW - timedelta(days=8),
                    next_attempt_at=NOW,
                )
            )
            await db.flush()
            assert await health.m365_state(db, now=NOW) == "healthy"

            # Operacja po terminie dłużej niż 30 min = kolejka stoi.
            db.add(
                _op(
                    user.id,
                    "pending",
                    created_at=NOW,
                    next_attempt_at=NOW - timedelta(hours=1),
                )
            )
            await db.flush()
            assert await health.m365_state(db, now=NOW) == "degraded"
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_m365_probe_recent_failure_and_off(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(delete(HrM365Operation))
            user = await _user(db)
            db.add(
                _op(
                    user.id,
                    "failed",
                    created_at=NOW - timedelta(days=1),
                    next_attempt_at=NOW,
                )
            )
            await db.flush()
            monkeypatch.setattr(settings, "HR_M365_MODE", "live")
            assert await health.m365_state(db, now=NOW) == "degraded"
            monkeypatch.setattr(settings, "HR_M365_MODE", "off")
            assert await health.m365_state(db, now=NOW) == "disabled"
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_hr_jobs_probe(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HR_LOOPS_ENABLED", True)
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(delete(HrJobRun))
            db.add(
                HrJobRun(
                    kind="probe_done",
                    period_key="2091-03-07",
                    status="done",
                    claimed_at=NOW - timedelta(hours=3),
                    finished_at=NOW - timedelta(hours=3),
                )
            )
            db.add(
                HrJobRun(
                    kind="probe_old_failure",
                    period_key="2091-03-01",
                    status="failed",
                    claimed_at=NOW - timedelta(days=6),
                )
            )
            db.add(
                HrJobRun(
                    kind="probe_running",
                    period_key="2091-03-07",
                    status="claimed",
                    claimed_at=NOW - timedelta(minutes=20),
                )
            )
            await db.flush()
            assert await health.hr_jobs_state(db, now=NOW) == "healthy"

            # Przebieg zabity w połowie (rezerwacja bez końca > 2 h).
            db.add(
                HrJobRun(
                    kind="probe_stuck",
                    period_key="2091-03-07",
                    status="claimed",
                    claimed_at=NOW - timedelta(hours=3),
                )
            )
            await db.flush()
            assert await health.hr_jobs_state(db, now=NOW) == "degraded"

            monkeypatch.setattr(settings, "HR_LOOPS_ENABLED", False)
            assert await health.hr_jobs_state(db, now=NOW) == "disabled"
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_admin_cases_mail_probe(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_CASES_MAIL_INGEST_ENABLED", raising=False)
    async with AsyncSessionLocal() as db:
        try:
            assert await health.admin_cases_mail_state(db, now=NOW) == "disabled"

            monkeypatch.setenv("ADMIN_CASES_MAIL_INGEST_ENABLED", "true")
            monkeypatch.setenv("ADMIN_CASES_MAILBOX", "administracja@example.com")
            await db.execute(
                delete(AppSetting).where(AppSetting.key == HR_MODULES_SETTING)
            )
            db.add(
                AppSetting(
                    key=HR_MODULES_SETTING,
                    value={key: key == "cases" for key in HR_MODULE_KEYS},
                )
            )
            await db.execute(delete(AdminMailIngestState))
            await db.flush()
            # Włączony, ale jeszcze bez żadnego przebiegu.
            assert await health.admin_cases_mail_state(db, now=NOW) == "degraded"

            state = AdminMailIngestState(
                mailbox="administracja@example.com",
                last_run_finished_at=NOW - timedelta(minutes=4),
                last_status="ok",
            )
            db.add(state)
            await db.flush()
            assert await health.admin_cases_mail_state(db, now=NOW) == "healthy"

            state.last_status = "error"
            await db.flush()
            assert await health.admin_cases_mail_state(db, now=NOW) == "degraded"

            state.last_status = "ok"
            state.last_run_finished_at = NOW - timedelta(hours=2)
            await db.flush()
            assert await health.admin_cases_mail_state(db, now=NOW) == "degraded"
        finally:
            await db.rollback()
