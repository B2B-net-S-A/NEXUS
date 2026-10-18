"""Sondy `/api/health` modułów HR (``app/services/hr/health.py``).

Każdy test działa w transakcji wycofywanej na końcu: czyści tabelę sondy, wkłada
swoje wiersze i sprawdza werdykt — cudze wiersze z innych testów nie przeszkadzają.
Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.admin_case import AdminMailIngestState
from app.models.app_setting import AppSetting
from app.models.hr_leave import HrM365Operation
from app.models.hr_ops import HrJobRun
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.hr import health
from app.services.hr.m365 import secret_expiry
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

NOW = datetime(2091, 3, 7, 12, 0, tzinfo=timezone.utc)
TODAY = date(2091, 3, 7)


@pytest.fixture
def m365_env(monkeypatch):
    """Rejestracja „NEXUS Kadry” bez daty sekretu i bez innych odbiorców na żywo."""

    monkeypatch.setattr(settings, "HR_M365_CLIENT_SECRET_EXPIRES_ON", None)
    monkeypatch.setattr(settings, "EQUIPMENT_INTUNE_MODE", "off")
    monkeypatch.delenv("ADMIN_CASES_MAIL_INGEST_ENABLED", raising=False)
    return monkeypatch


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
async def test_m365_probe(m365_env) -> None:
    m365_env.setattr(settings, "HR_M365_MODE", "simulate")
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
            assert await health.m365_state(db, now=NOW) == "degraded: operations"
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_m365_probe_recent_failure_and_off(m365_env) -> None:
    monkeypatch = m365_env
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
            # Na żywo bez daty sekretu — nie wiemy, kiedy wszystko stanie.
            assert (
                await health.m365_state(db, now=NOW)
                == "degraded: operations,secret_expiry_unknown"
            )
            monkeypatch.setattr(settings, "HR_M365_MODE", "off")
            assert await health.m365_state(db, now=NOW) == "disabled"
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_m365_probe_secret_expiry(m365_env) -> None:
    def expires_in(days: int) -> None:
        m365_env.setattr(
            settings, "HR_M365_CLIENT_SECRET_EXPIRES_ON", TODAY + timedelta(days=days)
        )

    async with AsyncSessionLocal() as db:
        try:
            await db.execute(delete(HrM365Operation))
            m365_env.setattr(settings, "HR_M365_MODE", "simulate")
            # Symulacja bez daty: sekretu nic jeszcze nie używa.
            assert await health.m365_state(db, now=NOW) == "healthy"
            expires_in(31)
            assert await health.m365_state(db, now=NOW) == "healthy"
            expires_in(30)
            assert (
                await health.m365_state(db, now=NOW)
                == "degraded: secret_expires_in_30d"
            )
            expires_in(1)
            assert (
                await health.m365_state(db, now=NOW) == "degraded: secret_expires_in_1d"
            )
            expires_in(0)
            assert await health.m365_state(db, now=NOW) == "unhealthy: secret_expired"
            expires_in(-3)
            assert await health.m365_state(db, now=NOW) == "unhealthy: secret_expired"

            # Urlopy wyłączone: sekret liczy się tylko, gdy rejestracji używa
            # na żywo Intune albo czytnik administracja@.
            m365_env.setattr(settings, "HR_M365_MODE", "off")
            expires_in(12)
            assert await health.m365_state(db, now=NOW) == "disabled"
            m365_env.setattr(settings, "EQUIPMENT_INTUNE_MODE", "live")
            assert (
                await health.m365_state(db, now=NOW)
                == "degraded: secret_expires_in_12d"
            )
            m365_env.setattr(settings, "EQUIPMENT_INTUNE_MODE", "off")
            m365_env.setenv("ADMIN_CASES_MAIL_INGEST_ENABLED", "true")
            m365_env.setenv("ADMIN_CASES_MAILBOX", "administracja@example.com")
            expires_in(-1)
            assert await health.m365_state(db, now=NOW) == "unhealthy: secret_expired"
        finally:
            await db.rollback()


def test_secret_status_states(m365_env) -> None:
    assert secret_expiry.status(TODAY) == {
        "expires_on": None,
        "days_left": None,
        "state": "not_set",
    }
    m365_env.setattr(settings, "HR_M365_MODE", "live")
    assert secret_expiry.status(TODAY)["state"] == "missing"
    m365_env.setattr(settings, "HR_M365_CLIENT_SECRET_EXPIRES_ON", date(2091, 5, 1))
    assert secret_expiry.status(TODAY) == {
        "expires_on": "2091-05-01",
        "days_left": 55,
        "state": "ok",
    }
    assert [
        secret_expiry.alert_step(days) for days in (45, 31, 30, 15, 14, 8, 7, 2, 1)
    ] == [
        None,
        None,
        "30d",
        "30d",
        "14d",
        "14d",
        "7d",
        "7d",
        "1d",
    ]
    assert secret_expiry.alert_step(0) == secret_expiry.alert_step(-9) == "expired"


def test_secret_expiry_setting_never_blocks_startup() -> None:
    from app.core.config import Settings

    good = Settings(HR_M365_CLIENT_SECRET_EXPIRES_ON="2027-04-30")
    assert good.HR_M365_CLIENT_SECRET_EXPIRES_ON == date(2027, 4, 30)
    assert (
        Settings(HR_M365_CLIENT_SECRET_EXPIRES_ON=" ").HR_M365_CLIENT_SECRET_EXPIRES_ON
        is None
    )
    with pytest.warns(UserWarning, match="HR_M365_CLIENT_SECRET_EXPIRES_ON"):
        typo = Settings(HR_M365_CLIENT_SECRET_EXPIRES_ON="30.04.2027")
    assert typo.HR_M365_CLIENT_SECRET_EXPIRES_ON is None


@pytest.mark.asyncio
async def test_secret_alert_once_per_threshold_only_to_admins(m365_env) -> None:
    from tests.hr.m365_helpers import at, make_user

    expires = date(2091, 4, 30)

    def days_before(days: int, hour: int = 8) -> datetime:
        return at(expires - timedelta(days=days), hour)

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(HrJobRun).where(HrJobRun.kind == secret_expiry.JOB_KIND)
        )
        admin = await make_user(db, role="admin", profile=False)
        recruiter = await make_user(db, profile=False)
        await db.commit()

        no_date = await secret_expiry.run_once(db, now=days_before(20))
        m365_env.setattr(settings, "HR_M365_CLIENT_SECRET_EXPIRES_ON", expires)
        far = await secret_expiry.run_once(db, now=days_before(45))
        night = await secret_expiry.run_once(db, now=days_before(20, hour=6))
        # Pętla stała do 20. dnia przed terminem: idzie tylko bieżący próg (30).
        first = await secret_expiry.run_once(db, now=days_before(20))
        again = await secret_expiry.run_once(db, now=days_before(19))
        steps = [
            await secret_expiry.run_once(db, now=days_before(days))
            for days in (14, 7, 1, 0)
        ]
        after = await secret_expiry.run_once(db, now=days_before(-2))
        # Rotacja: nowy termin zaczyna drabinę od nowa.
        m365_env.setattr(
            settings, "HR_M365_CLIENT_SECRET_EXPIRES_ON", date(2093, 4, 30)
        )
        rotated = await secret_expiry.run_once(db, now=days_before(-2))

        rows = (
            await db.scalars(
                select(Notification)
                .where(
                    Notification.user_id.in_([admin.id, recruiter.id]),
                    Notification.notification_type
                    == NotificationType.automation_failing,
                )
                .order_by(Notification.id)
            )
        ).all()

    assert no_date == {"status": "no_date"}
    assert far == {"status": "ok", "days_left": 45}
    assert night == {"status": "too_early"}
    assert first["status"] == "notified" and first["step"] == "30d"
    assert first["notified"] >= 1
    assert again == {"status": "already_sent", "days_left": 19}
    assert [step["step"] for step in steps] == ["14d", "7d", "1d", "expired"]
    assert after == {"status": "already_sent", "days_left": -2}
    assert rotated["status"] == "ok"
    assert {row.user_id for row in rows} == {admin.id}
    assert [row.title for row in rows] == [
        "Sekret aplikacji „NEXUS Kadry” wygasa za 20 dni",
        "Sekret aplikacji „NEXUS Kadry” wygasa za 14 dni",
        "Sekret aplikacji „NEXUS Kadry” wygasa za 7 dni",
        "Sekret aplikacji „NEXUS Kadry” wygasa jutro",
        "Sekret aplikacji „NEXUS Kadry” wygasa dziś",
    ]
    assert secret_expiry.alert_text(expires, -2)[0].endswith("wygasł")
    assert all(row.link == "/settings/hr" for row in rows)
    assert "Termin: 30.04.2091" in rows[0].message
    assert "HR_M365_CLIENT_SECRET_EXPIRES_ON" in rows[0].message


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
