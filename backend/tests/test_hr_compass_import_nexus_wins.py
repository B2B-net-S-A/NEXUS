"""Ponowny import z Compassa nie nadpisuje tego, co zmieniono w NEXUSIE.

Od 18.10.2026 kartoteki, stawki, premie i czas prowadzi NEXUS, a Compass jest
tylko do odczytu. Paczka z Compassa ma więc stan sprzed przełączenia: każda
różnica w wierszu zapisanym wcześniej przez import, a potem zmienionym
w NEXUSIE (przełożeni przepięci w „Strukturze”, premia przyznana w Płacach,
dzień obecności usunięty w „Moim miesiącu”), jest zmianą NEXUSA, nie Compassa.

Testy bez bazy: sesja to atrapa, która oddaje kolejne odpowiedzi ``scalar``.
Dane fikcyjne (repo publiczne).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.hr_ops import HrImportIdMap
from app.models.hr_payroll import EmployeeRate, HrBonus
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement
from app.services.hr import compass_import
from app.services.hr.compass_import import payroll as payroll_import
from app.services.hr.compass_import import profiles as profiles_import
from app.services.hr.compass_import import time as time_import
from app.services.hr.compass_import.common import ImportPlan, People

APPLIED_AT = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)
LATER = APPLIED_AT + timedelta(minutes=40)
EARLIER = APPLIED_AT - timedelta(minutes=1)


def _bundle(tables: dict[str, list[dict]]) -> compass_import.Bundle:
    raw = json.dumps(
        {
            "format": "compass-bundle",
            "version": 1,
            "exported_at": "2026-10-19T08:00:00+02:00",
            "tables": tables,
        }
    ).encode()
    return compass_import.parse_bundle(raw)


def _mapping(module: str, source_id: str, target_id: object) -> HrImportIdMap:
    return HrImportIdMap(
        module=module,
        source_id=source_id,
        target_table="x",
        target_id=str(target_id),
        decision="auto",
        batch_id=1,
    )


# ── Kartoteki ────────────────────────────────────────────────────────────────


def _profile_row(compass_id: str, manager_id: str) -> dict:
    return {
        "id": compass_id,
        "email": "osoba-a@example.com",
        "full_name": "Osoba A",
        "role": "internal",
        "is_external": False,
        "employment_type": "uop",
        "employment_status": "active",
        "default_location": "remote",
        "manager_id": manager_id,
        "leave_entitlement_days": 26,
        "leave_carried_over_days": 0,
        "leave_used_initial_days": 0,
    }


def _manager_row(compass_id: str) -> dict:
    return {**_profile_row(compass_id, ""), "email": "osoba-m@example.com"}


async def _plan_profile(monkeypatch, *, profile_updated_at: datetime) -> list:
    person, manager = str(uuid.uuid4()), str(uuid.uuid4())
    bundle = _bundle(
        {"profiles": [_profile_row(person, manager), _manager_row(manager)]}
    )

    async def users(_db):
        return {"osoba-a@example.com": 7, "osoba-m@example.com": 9}

    async def mapped(_db, _module, source_id):
        return _mapping("profiles", source_id, 1)

    monkeypatch.setattr(profiles_import, "_users_by_email", users)
    monkeypatch.setattr(profiles_import, "mapped_target", mapped)
    monkeypatch.setattr(profiles_import, "business_today", lambda: date(2026, 10, 19))

    def profile(user_id: int, manager_user_id) -> EmployeeProfile:
        # Kartoteka po imporcie 18.10: wartości z paczki, ale przełożony
        # przepięty w NEXUSIE (Compass ma 9, NEXUS 42).
        return EmployeeProfile(
            id=user_id,
            user_id=user_id,
            employment_type="uop",
            employment_status="active",
            default_location="remote",
            can_log_overtime=False,
            manager_user_id=manager_user_id,
            compass_profile_id=uuid.UUID(person if user_id == 7 else manager),
            updated_at=profile_updated_at,
        )

    def entitlement(user_id: int) -> LeaveEntitlement:
        return LeaveEntitlement(
            user_id=user_id,
            year=2026,
            entitlement_days=Decimal("26"),
            carried_over_days=Decimal("0"),
            used_initial_days=Decimal("0"),
            updated_at=EARLIER,
        )

    answers = {
        7: [profile(7, 42), entitlement(7)],
        9: [profile(9, None), entitlement(9)],
    }
    queue: list = []
    for user_id in (7, 9):
        queue.extend(answers[user_id])

    async def scalar(statement, *args, **kwargs):
        text = str(statement)
        if "hr_import_batches" in text:
            return APPLIED_AT
        return queue.pop(0)

    db = SimpleNamespace(scalar=AsyncMock(side_effect=scalar))
    plan = await profiles_import.plan(db, bundle)
    return plan.rows


@pytest.mark.asyncio
async def test_profile_changed_in_nexus_after_import_is_not_overwritten(monkeypatch):
    rows = await _plan_profile(monkeypatch, profile_updated_at=LATER)
    person = rows[0]
    assert person.action == "conflict"
    assert person.reason == profiles_import.CHANGED_IN_NEXUS
    assert person.payload.get("nexus_changed") is True


@pytest.mark.asyncio
async def test_profile_not_touched_in_nexus_still_follows_the_bundle(monkeypatch):
    rows = await _plan_profile(monkeypatch, profile_updated_at=EARLIER)
    assert rows[0].action == "update"
    assert "manager_user_id" in rows[0].payload["changes"]


@pytest.mark.asyncio
async def test_apply_skips_profile_changed_in_nexus():
    profile = EmployeeProfile(user_id=7, manager_user_id=42)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=profile),
        flush=AsyncMock(),
        add=lambda _obj: None,
    )
    plan = compass_import.ModulePlan(
        module="profiles",
        rows=[
            compass_import.core.RowPlan(
                "profiles:x",
                "conflict",
                profiles_import.CHANGED_IN_NEXUS,
                {
                    "user_id": 7,
                    "compass_profile_id": str(uuid.uuid4()),
                    "fields": {"manager_user_id": 9},
                    "entitlement": {},
                    "year": 2026,
                    "manual": False,
                    "nexus_changed": True,
                },
            )
        ],
    )
    written = await profiles_import.apply(db, plan, SimpleNamespace(id=2), 1)
    assert profile.manager_user_id == 42
    assert written["profiles_updated"] == 0
    db.scalar.assert_not_awaited()


# ── Płace ────────────────────────────────────────────────────────────────────


def _people() -> People:
    return People(
        accounts={"compass-r": 7},
        profiles={7: EmployeeProfile(user_id=7)},
        rows={},
    )


def _bonus_row(compass_id: str) -> dict:
    return {
        "id": compass_id,
        "recipient_user_id": "compass-r",
        "amount": "500.00",
        "currency": "PLN",
        "category": "recruiter",
        "status": "pending",
        "period_year": 2026,
        "period_month": 9,
        "created_at": "2026-09-30T10:00:00+02:00",
    }


@pytest.mark.asyncio
async def test_bonus_decided_in_nexus_is_not_reverted_to_proposed():
    compass_id = str(uuid.uuid4())
    sid = f"bonuses:{compass_id}"
    existing = HrBonus(
        id=11,
        compass_id=uuid.UUID(compass_id),
        recipient_user_id=7,
        amount=Decimal("500.00"),
        currency="PLN",
        category="recruiter",
        period_year=2026,
        period_month=9,
        status="assigned",  # Płace przyznały ją w NEXUSIE 19.10
        source="compass_import",
        source_key=f"compass:{compass_id}",
        updated_at=LATER,
    )

    async def scalar(statement, *args, **kwargs):
        if "hr_import_batches" in str(statement):
            return APPLIED_AT
        return existing

    db = SimpleNamespace(scalar=AsyncMock(side_effect=scalar))
    result = ImportPlan(module="payroll")
    await payroll_import._plan_bonuses(
        db,
        _bundle({"bonuses": [_bonus_row(compass_id)]}),
        _people(),
        {sid: _mapping("payroll", sid, 11)},
        result,
    )
    assert [row.action for row in result.rows] == ["conflict"]
    assert result.rows[0].reason == payroll_import.CHANGED_IN_NEXUS


@pytest.mark.asyncio
async def test_rate_corrected_in_nexus_is_not_reverted():
    compass_id = str(uuid.uuid4())
    sid = f"user_rates:{compass_id}"
    existing = EmployeeRate(
        id=5,
        user_id=7,
        compass_id=uuid.UUID(compass_id),
        hourly_rate=Decimal("120.00"),  # Płace poprawiły z 110 na 120
        currency="PLN",
        effective_from=date(2026, 10, 1),
        effective_to=None,
        updated_at=LATER,
    )

    async def scalar(statement, *args, **kwargs):
        if "hr_import_batches" in str(statement):
            return APPLIED_AT
        return existing

    async def scalars(statement, *args, **kwargs):
        return []

    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=scalar), scalars=AsyncMock(side_effect=scalars)
    )
    row = {
        "id": compass_id,
        "user_id": "compass-r",
        "hourly_rate": "110.00",
        "currency": "PLN",
        "effective_from": "2026-10-01",
        "effective_to": None,
    }
    result = ImportPlan(module="payroll")
    await payroll_import._plan_rates(
        db,
        _bundle({"user_rates": [row]}),
        _people(),
        {sid: _mapping("payroll", sid, 5)},
        result,
    )
    assert [r.action for r in result.rows] == ["conflict"]
    assert result.rows[0].reason == payroll_import.CHANGED_IN_NEXUS


# ── Czas ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attendance_day_removed_in_nexus_does_not_come_back():
    compass_id = str(uuid.uuid4())
    sid = f"attendance_records:{compass_id}"
    people = People(
        accounts={"compass-r": 7},
        profiles={7: EmployeeProfile(user_id=7, default_location="remote")},
        rows={},
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    result = ImportPlan(module="time")
    await time_import._plan_attendance(
        db,
        _bundle(
            {
                "attendance_records": [
                    {
                        "id": compass_id,
                        "user_id": "compass-r",
                        "date": "2026-10-06",
                        "status": "active",
                        "location": "onsite",
                    }
                ]
            }
        ),
        people,
        {sid: _mapping("time", sid, 3)},
        result,
    )
    assert [row.action for row in result.rows] == ["skip"]
    assert result.rows[0].reason == time_import.REMOVED_IN_NEXUS


@pytest.mark.asyncio
async def test_template_removed_in_nexus_does_not_come_back():
    compass_id = str(uuid.uuid4())
    sid = f"timesheet_user_templates:{compass_id}"
    db = SimpleNamespace(
        get=AsyncMock(return_value=None), scalar=AsyncMock(return_value=None)
    )
    result = ImportPlan(module="time")
    await time_import._plan_templates(
        db,
        _bundle(
            {
                "timesheet_user_templates": [
                    {
                        "id": compass_id,
                        "user_id": "compass-r",
                        "name": "Spotkania",
                        "description": "Spotkania zespołu",
                    }
                ]
            }
        ),
        _people(),
        {sid: _mapping("time", sid, 4)},
        result,
    )
    assert [row.action for row in result.rows] == ["skip"]
    assert result.rows[0].reason == time_import.REMOVED_IN_NEXUS


@pytest.mark.asyncio
async def test_role_default_removed_in_nexus_does_not_come_back():
    compass_id = str(uuid.uuid4())
    sid = f"timesheet_role_defaults:{compass_id}"
    db = SimpleNamespace(
        get=AsyncMock(return_value=None), scalar=AsyncMock(return_value=None)
    )
    result = ImportPlan(module="time")
    await time_import._plan_role_defaults(
        db,
        _bundle(
            {
                "timesheet_role_defaults": [
                    {
                        "id": compass_id,
                        "applies_to_role": "admin",
                        "label": "Administracja",
                        "default_description": "Prace administracyjne",
                    }
                ]
            }
        ),
        _people(),
        {sid: _mapping("time", sid, 6)},
        result,
    )
    assert [row.action for row in result.rows] == ["skip"]
    assert result.rows[0].reason == time_import.REMOVED_IN_NEXUS
