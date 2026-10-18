"""Lista osób dla Compassa (Akademia): kto pracuje, komu podlega, od/do kiedy.

Bez stawek, premii, nieobecności, powodu odejścia i formy zatrudnienia;
osoby, które odeszły, zostają ze statusem ``exited``; pusta lista to awaria.
Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr.roster_export import (
    ROSTER_FIELDS,
    RosterEmptyError,
    roster_payload,
)

_FORBIDDEN_KEYS = {
    "rate",
    "rates",
    "hourly_rate",
    "salary",
    "bonus",
    "bonuses",
    "leave",
    "leaves",
    "absence",
    "absences",
    "exit_reason",
    "employment_type",
    "phone",
}


@pytest.mark.asyncio
async def test_roster_carries_people_without_money_or_absences() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        boss = User(
            email=f"Roster-Boss-{tag}@Example.com",
            name=f"Szefowa Przykładowa {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        worker = User(
            email=f"roster-worker-{tag}@example.com",
            name=f"Pracownik Przykładowy {tag}",
            role=UserRole.employee,
            roles=["employee"],
            is_active=True,
        )
        gone = User(
            email=f"roster-gone-{tag}@example.com",
            name=f"Były Pracownik {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=False,
        )
        no_profile = User(
            email=f"roster-consultant-{tag}@example.com",
            name=f"Konsultant {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add_all([boss, worker, gone, no_profile])
        await db.flush()
        db.add_all(
            [
                EmployeeProfile(user_id=boss.id, department="Rekrutacja"),
                EmployeeProfile(
                    user_id=worker.id,
                    manager_user_id=boss.id,
                    employment_type="uop",
                    job_title="Rekruter",
                    department="Rekrutacja",
                    phone="+48 600 000 000",
                    work_start_date=date(2026, 3, 2),
                ),
                EmployeeProfile(
                    user_id=gone.id,
                    employment_status="exited",
                    last_working_day=date(2026, 9, 30),
                    exited_at=datetime(2026, 10, 1, 0, 5, tzinfo=timezone.utc),
                ),
            ]
        )
        await db.commit()

        payload = await roster_payload(db)

    assert payload["count"] == len(payload["people"])
    by_email = {row["email"]: row for row in payload["people"]}
    row = by_email[f"roster-worker-{tag}@example.com"]
    assert set(row) == set(ROSTER_FIELDS)
    assert not set(row) & _FORBIDDEN_KEYS
    assert row["manager_email"] == f"roster-boss-{tag}@example.com"
    assert row["employment_status"] == "active"
    assert row["work_start_date"] == "2026-03-02"
    assert row["account_active"] is True

    exited = by_email[f"roster-gone-{tag}@example.com"]
    assert exited["employment_status"] == "exited"
    assert exited["account_active"] is False
    assert exited["last_working_day"] == "2026-09-30"

    # Konto bez kartoteki (np. konsultant u klienta) nie jest na liście.
    assert f"roster-consultant-{tag}@example.com" not in by_email
    # Adresy małymi literami — odbiorca łączy po e-mailu.
    assert f"roster-boss-{tag}@example.com" in by_email


class _EmptyResult:
    def all(self) -> list:
        return []


class _EmptySession:
    async def execute(self, _statement):
        return _EmptyResult()


@pytest.mark.asyncio
async def test_empty_roster_is_refused_not_exported() -> None:
    with pytest.raises(RosterEmptyError):
        await roster_payload(_EmptySession())  # type: ignore[arg-type]
