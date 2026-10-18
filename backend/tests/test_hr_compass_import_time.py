"""Import „Mojego miesiąca” z Compassa: timesheety, obecność, opisy.

Paczki fikcyjne, każdy test kończy się rollbackiem.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.hr_time import (
    AttendanceDay,
    Timesheet,
    TimesheetEntry,
    TimesheetRoleDefault,
    TimesheetTemplate,
)
from app.services.hr import compass_import
from app.services.hr.compass_import import time as time_import
from app.services.hr.time_hash import HashEntry, compute_timesheet_hash
from tests.test_hr_compass_import_leave import (
    assert_report_clean,
    make_bundle,
    make_person,
    run_import,
)


def _sheet(person: str, year: int, month: int, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": person,
        "year": year,
        "month": month,
        "status": "draft",
        "submitted_at": None,
        "approved_by": None,
        "approved_at": None,
        "rejection_note": None,
        "pdf_hash": None,
        "created_at": "2026-08-01T08:00:00+00:00",
        **values,
    }


def _entry(sheet: dict, day: str, hours, description: str, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "timesheet_id": sheet["id"],
        "work_date": day,
        "hours": hours,
        "project": None,
        "description": description,
        "source": "manual",
        "is_overtime_override": False,
        "override_reason": None,
        "override_by": None,
        **values,
    }


def _hash(entries: list[dict]) -> str:
    return compute_timesheet_hash(
        HashEntry(
            e["work_date"], Decimal(str(e["hours"])), e["project"], e["description"]
        )
        for e in entries
    )


@pytest.mark.asyncio
async def test_time_dry_run_apply_and_second_apply_changes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            worker, w_id, w_row = await make_person(db, f"{tag}-worker")
            boss, b_id, b_row = await make_person(db, f"{tag}-boss")
            contractor, c_id, c_row = await make_person(
                db, f"{tag}-b2b", employment_type="b2b"
            )
            _, n_id, n_row = await make_person(db, f"{tag}-none", with_profile=False)

            # Już w NEXUSIE: timesheet lipca osoby, dzień obecności, fragment opisu.
            db.add(Timesheet(user_id=worker.id, year=2026, month=7))
            db.add(
                AttendanceDay(
                    user_id=worker.id,
                    day=date(2026, 8, 5),
                    status="active",
                    location="remote",
                    note="Wpisane w NEXUSIE",
                )
            )
            db.add(
                TimesheetTemplate(
                    user_id=worker.id, name="Standard", description="Opis z NEXUSA"
                )
            )
            await db.flush()

            approved = _sheet(
                w_id,
                2026,
                8,
                status="approved",
                approved_by=b_id,
                approved_at="2026-09-02T10:00:00+00:00",
                submitted_at="2026-09-01T10:00:00+00:00",
            )
            approved_entries = [
                _entry(approved, "2026-08-03", 8, "Praca nad wdrożeniem X"),
                _entry(
                    approved,
                    "2026-08-03",
                    "2.5",
                    "Dyżur",
                    project="Projekt A",
                    is_overtime_override=True,
                    override_reason="Wdrożenie nocne",
                    override_by=b_id,
                ),
            ]
            approved["pdf_hash"] = _hash(approved_entries)
            self_approved = _sheet(
                w_id,
                2026,
                9,
                status="approved",
                approved_by=w_id,
                approved_at="2026-10-02T10:00:00+00:00",
                pdf_hash="0" * 64,
            )
            self_entries = [_entry(self_approved, "2026-09-01", 8, "Praca")]
            contractor_sheet = _sheet(c_id, 2026, 8)
            contractor_entries = [
                _entry(
                    contractor_sheet,
                    "2026-08-10",
                    8,
                    "Praca standardowa",
                    source="leave_paid",
                ),
                _entry(contractor_sheet, "2026-08-11", 6, "Analiza"),
            ]
            returned = _sheet(
                w_id, 2026, 10, status="rejected", rejection_note="Popraw opisy"
            )
            taken = _sheet(w_id, 2026, 7)
            no_profile = _sheet(n_id, 2026, 8)

            def attendance(day: str, status: str, location=None) -> dict:
                return {
                    "id": str(uuid.uuid4()),
                    "user_id": w_id,
                    "date": day,
                    "status": status,
                    "location": location,
                    "note": None,
                }

            remote = attendance("2026-08-03", "active", "remote")
            onsite = attendance("2026-08-04", "active", "onsite")
            vacation = attendance("2026-08-06", "vacation")
            trip = attendance("2026-08-07", "business_trip")
            clash = attendance("2026-08-05", "business_trip")

            def default(role, label: str) -> dict:
                return {
                    "id": str(uuid.uuid4()),
                    "applies_to_role": role,
                    "label": label,
                    "project": None,
                    "default_description": f"{label} — opis",
                    "is_active": True,
                    "sort_order": 0,
                    "created_by": b_id,
                }

            defaults = [
                default("admin", f"Admin {tag}"),
                default("internal", f"Wewnętrzny {tag}"),
                default("consultant", f"Konsultant {tag}"),
                default(None, f"Wszyscy {tag}"),
            ]
            templates = [
                {
                    "id": str(uuid.uuid4()),
                    "user_id": w_id,
                    "name": "Spotkania",
                    "description": "Spotkania zespołu",
                    "project": None,
                    "sort_order": 1,
                },
                {
                    "id": str(uuid.uuid4()),
                    "user_id": w_id,
                    "name": "Standard",
                    "description": "Opis z Compassa",
                    "project": None,
                    "sort_order": 2,
                },
            ]
            bundle = make_bundle(
                {
                    "profiles": [w_row, b_row, c_row, n_row],
                    "timesheets": [
                        approved,
                        self_approved,
                        contractor_sheet,
                        returned,
                        taken,
                        no_profile,
                    ],
                    "timesheet_entries": [
                        *approved_entries,
                        *self_entries,
                        *contractor_entries,
                    ],
                    "attendance_records": [remote, onsite, vacation, trip, clash],
                    "timesheet_role_defaults": defaults,
                    "timesheet_user_templates": templates,
                }
            )
            importer = compass_import.IMPORTERS["time"]

            batch, report, written = await run_import(db, "time", bundle)
            assert report["counts"] == {"create": 10, "conflict": 3, "skip": 4}
            reasons = report["reasons"]
            assert (
                reasons[time_import.SELF_APPROVAL + "; " + time_import.HASH_MISMATCH]
                == 1
            )
            assert reasons["timesheet tego miesiąca jest już w NEXUSIE"] == 1
            assert reasons["zgodne z domyślnym miejscem pracy"] == 1
            assert reasons["urlop — żyje we wnioskach urlopowych"] == 1
            assert reasons["dzień obecności wpisany już w NEXUSIE"] == 1
            assert reasons["fragment o tej nazwie jest już w NEXUSIE"] == 1
            assert reasons["osoba bez kartoteki w NEXUSIE"] == 1
            assert_report_clean(batch.report, "Praca nad wdrożeniem X", "Popraw opisy")
            assert written["timesheets_created"] == 4
            assert written["entries_written"] == 5
            # Suma kontrolna: zgodna dla sierpnia, rozjazd (licznik) dla września.
            assert written["hash_mismatch"] == 1

            august = await db.scalar(
                select(Timesheet).where(
                    Timesheet.compass_id == uuid.UUID(approved["id"])
                )
            )
            assert august.status == "approved"
            assert august.approved_by == boss.id
            assert august.pdf_hash == approved["pdf_hash"]
            entries = list(
                await db.scalars(
                    select(TimesheetEntry)
                    .where(TimesheetEntry.timesheet_id == august.id)
                    .order_by(TimesheetEntry.hours)
                )
            )
            assert {e.source for e in entries} == {"compass_import"}
            overtime = entries[0]
            assert overtime.is_overtime is True
            assert overtime.overtime_by == boss.id
            assert overtime.hours == Decimal("2.50")

            september = await db.scalar(
                select(Timesheet).where(
                    Timesheet.compass_id == uuid.UUID(self_approved["id"])
                )
            )
            assert september.status == "approved"
            assert september.approved_by is None

            october = await db.scalar(
                select(Timesheet).where(
                    Timesheet.compass_id == uuid.UUID(returned["id"])
                )
            )
            assert october.status == "draft"
            assert october.return_note == "Popraw opisy"

            contractor_month = await db.scalar(
                select(Timesheet).where(
                    Timesheet.compass_id == uuid.UUID(contractor_sheet["id"])
                )
            )
            sources = sorted(
                await db.scalars(
                    select(TimesheetEntry.source).where(
                        TimesheetEntry.timesheet_id == contractor_month.id
                    )
                )
            )
            assert sources == ["compass_import", "leave_paid"]

            exceptions = {
                row.day: (row.status, row.location)
                for row in await db.scalars(
                    select(AttendanceDay).where(AttendanceDay.user_id == worker.id)
                )
            }
            assert exceptions == {
                date(2026, 8, 3): ("active", "remote"),
                date(2026, 8, 5): ("active", "remote"),  # wpis NEXUSA zostaje
                date(2026, 8, 7): ("business_trip", None),
            }

            imported_defaults = {
                row.label: row
                for row in await db.scalars(
                    select(TimesheetRoleDefault).where(
                        TimesheetRoleDefault.label.like(f"% {tag}")
                    )
                )
            }
            assert imported_defaults[f"Admin {tag}"].applies_to_role == "admin"
            assert imported_defaults[f"Admin {tag}"].is_active is True
            assert imported_defaults[f"Wewnętrzny {tag}"].is_active is False
            assert imported_defaults[f"Wewnętrzny {tag}"].applies_to_role is None
            assert imported_defaults[f"Wszyscy {tag}"].applies_to_role is None
            assert f"Konsultant {tag}" not in imported_defaults

            standard = await db.scalar(
                select(TimesheetTemplate).where(
                    TimesheetTemplate.user_id == worker.id,
                    TimesheetTemplate.name == "Standard",
                )
            )
            assert standard.description == "Opis z NEXUSA"

            batch2, _ = await compass_import.dry_run(
                db,
                module="time",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert batch2.report["dry_run"]["counts"] == {
                "unchanged": 10,
                "conflict": 3,
                "skip": 4,
            }
            written2 = await compass_import.apply(
                db,
                batch=batch2,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert all(value == 0 for value in written2.values()), written2
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_time_dry_run_writes_nothing_and_skips_people_without_profile() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            worker, w_id, w_row = await make_person(db, f"{tag}-worker")
            _, n_id, n_row = await make_person(db, f"{tag}-none", with_profile=False)
            sheet = _sheet(w_id, 2026, 3)
            orphan = _sheet(n_id, 2026, 3)
            bundle = make_bundle(
                {
                    "profiles": [w_row, n_row],
                    "timesheets": [sheet, orphan],
                    "timesheet_entries": [_entry(sheet, "2026-03-02", 8, "Praca")],
                }
            )
            importer = compass_import.IMPORTERS["time"]
            batch, plan = await compass_import.dry_run(
                db,
                module="time",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan.counts() == {"create": 1, "skip": 1}
            assert batch.report["dry_run"]["reasons"] == {
                "osoba bez kartoteki w NEXUSIE": 1
            }
            assert (
                await db.scalar(
                    select(Timesheet.id).where(Timesheet.user_id == worker.id)
                )
                is None
            )
        finally:
            await db.rollback()
