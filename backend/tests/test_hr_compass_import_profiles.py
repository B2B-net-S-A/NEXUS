"""Import kartotek z Compassa: na sucho → zapis → drugi zapis bez zmian.

Paczka jest fikcyjna (repo publiczne): osoby „Osoba <znacznik>”, e-maile
``@example.com``, identyfikatory Compassa losowe. Test działa w jednej sesji
i kończy się rollbackiem — nic nie zostaje w bazie.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_ops import HrImportIdMap
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement
from app.models.user import User, UserRole
from app.services.hr import compass_import
from app.services.hr.compass_import import profiles as profiles_import


def _bundle(rows: list[dict]) -> compass_import.Bundle:
    raw = json.dumps(
        {
            "format": "compass-bundle",
            "version": 1,
            "exported_at": "2026-11-13T18:00:00+01:00",
            "tables": {"profiles": rows},
        }
    ).encode()
    return compass_import.parse_bundle(raw)


async def _account(db, marker: str, role: UserRole = UserRole.recruiter) -> User:
    user = User(
        email=f"import-{marker}@example.com",
        name=f"Osoba {marker}",
        role=role,
        roles=[role.value],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _row(marker: str, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "email": f"Import-{marker}@Example.com",
        "full_name": f"Osoba {marker}",
        "role": "internal",
        "is_external": False,
        "employment_type": "uop",
        "employment_status": "active",
        "default_location": "remote",
        "work_start_date": "2025-03-03",
        "hired_at": "2025-03-01",
        "termination_date": None,
        "job_title": "Rekruterka",
        "department": "Rekrutacja IT",
        "phone": None,
        "can_log_overtime": False,
        "leave_entitlement_days": 26,
        "leave_carried_over_days": "3.5",
        "leave_used_initial_days": "0",
        "manager_id": None,
        **values,
    }


@pytest.mark.asyncio
async def test_dry_run_apply_and_second_apply_changes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            boss = await _account(db, f"{tag}-boss", UserRole.head_of_recruitment)
            worker = await _account(db, f"{tag}-worker")
            manual = await _account(db, f"{tag}-manual")
            db.add(
                EmployeeProfile(
                    user_id=manual.id,
                    employment_type="b2b",
                    job_title="Tytuł wpisany ręcznie",
                    department=None,
                )
            )
            await db.flush()

            boss_row = _row(f"{tag}-boss", job_title="Head of Recruitment")
            rows = [
                boss_row,
                _row(f"{tag}-worker", manager_id=boss_row["id"], employment_type=None),
                _row(f"{tag}-manual", job_title="Inny tytuł z Compassa"),
                _row(f"{tag}-consultant", role="consultant"),
                _row(f"{tag}-external", is_external=True),
                _row(f"{tag}-noaccount"),
            ]
            bundle = _bundle(rows)
            importer = compass_import.IMPORTERS["profiles"]

            batch, plan = await compass_import.dry_run(
                db,
                module="profiles",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            report = batch.report["dry_run"]
            assert report["counts"] == {"create": 2, "conflict": 1, "skip": 3}
            assert report["reasons"]["brak konta w NEXUSIE"] == 1
            assert report["reasons"]["konsultant — zostaje w Akademii"] == 1
            assert report["reasons"]["osoba zewnętrzna"] == 1
            # Na sucho nic nie zapisuje.
            assert (
                await db.scalar(
                    select(EmployeeProfile).where(EmployeeProfile.user_id == worker.id)
                )
                is None
            )
            # Raport nie niesie imion ani e-maili.
            assert "Osoba" not in json.dumps(batch.report)
            assert "example.com" not in json.dumps(batch.report).lower()

            written = await compass_import.apply(
                db,
                batch=batch,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert written["profiles_created"] == 2
            assert batch.status == "applied"

            worker_profile = await db.scalar(
                select(EmployeeProfile).where(EmployeeProfile.user_id == worker.id)
            )
            assert worker_profile.manager_user_id == boss.id
            assert worker_profile.employment_type == "uop"  # NULL w Compassie = UoP
            assert worker_profile.default_location == "remote"
            assert str(worker_profile.compass_profile_id) == rows[1]["id"]
            pool = await db.scalar(
                select(LeaveEntitlement).where(
                    LeaveEntitlement.user_id == worker.id,
                    LeaveEntitlement.year == business_today().year,
                )
            )
            assert pool.entitlement_days == Decimal("26")
            assert pool.carried_over_days == Decimal("3.5")

            # Ręczna kartoteka wygrywa: tytuł zostaje, puste pole uzupełnione.
            manual_profile = await db.scalar(
                select(EmployeeProfile).where(EmployeeProfile.user_id == manual.id)
            )
            assert manual_profile.job_title == "Tytuł wpisany ręcznie"
            assert manual_profile.employment_type == "b2b"
            assert manual_profile.department == "Rekrutacja IT"
            mapping = await db.scalar(
                select(HrImportIdMap).where(
                    HrImportIdMap.module == "profiles",
                    HrImportIdMap.source_id == profiles_import.source_id(rows[2]),
                )
            )
            assert mapping.decision == "manual"

            # Drugi przebieg tej samej paczki: same „bez zmian” i pominięcia.
            batch2, plan2 = await compass_import.dry_run(
                db,
                module="profiles",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan2.counts() == {"unchanged": 3, "skip": 3}
            written2 = await compass_import.apply(
                db,
                batch=batch2,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert written2 == {
                "profiles_created": 0,
                "profiles_updated": 0,
                "entitlements_written": 0,
            }
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_apply_refuses_other_bundle_and_repeated_apply() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            await _account(db, tag)
            bundle = _bundle([_row(tag)])
            other = _bundle([_row(tag, job_title="Zmieniony")])
            importer = compass_import.IMPORTERS["profiles"]
            batch, _ = await compass_import.dry_run(
                db,
                module="profiles",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            with pytest.raises(compass_import.ImportFlowError):
                await compass_import.apply(
                    db,
                    batch=batch,
                    bundle=other,
                    planner=importer.plan,
                    applier=importer.apply,
                    actor_user_id=None,
                )
            await compass_import.apply(
                db,
                batch=batch,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            with pytest.raises(compass_import.ImportFlowError):
                await compass_import.apply(
                    db,
                    batch=batch,
                    bundle=bundle,
                    planner=importer.plan,
                    applier=importer.apply,
                    actor_user_id=None,
                )
        finally:
            await db.rollback()


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        json.dumps({"format": "other", "version": 1, "tables": {}}).encode(),
        json.dumps({"format": "compass-bundle", "version": 2, "tables": {}}).encode(),
        json.dumps(
            {"format": "compass-bundle", "version": 1, "tables": {"x": {}}}
        ).encode(),
        json.dumps(
            {"format": "compass-bundle", "version": 1, "tables": {"x": [1]}}
        ).encode(),
    ],
)
def test_bad_bundles_are_refused(raw: bytes) -> None:
    with pytest.raises(compass_import.BundleError):
        compass_import.parse_bundle(raw)


def test_normalize_maps_compass_values() -> None:
    fields, notes = profiles_import.normalize(
        {
            "employment_type": "zlecenie",
            "employment_status": "weird",
            "default_location": None,
            "hired_at": "2024-02-01T00:00:00+00:00",
            "termination_date": "2026-12-31",
            "job_title": "  Recepcja\x00 ",
        }
    )
    assert fields["employment_type"] == "zlecenie"
    assert fields["employment_status"] == "active"
    assert fields["default_location"] == "onsite"
    assert str(fields["hired_on"]) == "2024-02-01"
    assert str(fields["last_working_day"]) == "2026-12-31"
    assert fields["job_title"] == "Recepcja"
    assert notes == ["nieznany status — przyjęty „aktywny”"]
