"""Import „Mojego miesiąca” z Compassa: timesheety, obecność, opisy.

Tabele i reguły:

* ``timesheets`` + ``timesheet_entries`` → ``timesheets`` (``compass_id``)
  i wpisy. Status ``rejected`` (w praktyce nieużywany) to szkic z notatką
  zwrotu. Akceptacja własnego timesheetu (Compass jej nie blokował) →
  ``approved_by`` pusty. Wpisy dostają ``source = 'compass_import'``, poza
  auto-wpisami płatnego urlopu kontraktora (``leave_paid``) — te zostają
  ``leave_paid``, bo „Mój miesiąc” uzgadnia je z urlopami po źródle i wpis
  z innym źródłem dałby w szkicu podwójne godziny. ``pdf_hash`` przechodzi
  bez zmian; po zapisie suma liczona na zaimportowanych wpisach
  (``time_hash``) musi być równa — rozjazd to licznik w raporcie, nie błąd.
* ``attendance_records`` → ``attendance_days`` tylko jako wyjątki od
  domyślnego miejsca pracy z kartoteki. Statusy urlopowe są pomijane: urlop
  żyje w ``leave_request_days`` (w Compassie skasowanie wiersza obecności
  odblokowywało godziny w dniu urlopu).
* ``timesheet_role_defaults`` → ``timesheet_role_defaults`` (rola Compassa →
  rola NEXUSA; rola bez odpowiednika = opis wyłączony do decyzji Kadr),
* ``timesheet_user_templates`` → ``timesheet_templates``.

Ponowny import nie nadpisuje NEXUSA: timesheet w zamkniętym miesiącu płac
(``payroll_locked``) albo zmieniony w NEXUSIE po imporcie (akceptacja,
zwrot, cofnięcie) i dzień obecności poprawiony w NEXUSIE dostają „bez zmian”
(gdy paczka mówi to samo) albo „conflict” — nigdy „update”.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Mapping, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_ops import HrImportBatch
from app.models.hr_time import (
    AttendanceDay,
    Timesheet,
    TimesheetEntry,
    TimesheetRoleDefault,
    TimesheetTemplate,
)
from app.services.hr.time_hash import HashEntry, compute_timesheet_hash
from app.services.hr_leave_schema import LEAVE_TYPES
from app.services.hr_time_schema import (
    LOCATIONS,
    OVERTIME_REASON_MIN_LENGTH,
)

from .bundle import Bundle
from .common import (
    NO_PROFILE,
    ImportPlan,
    People,
    changed_fields,
    decimal,
    join_notes,
    load_people,
    module_map,
    parse_date,
    parse_datetime,
    parse_uuid,
    small_int,
    source_id,
    text,
)
from .core import ModulePlan, RowPlan, changed_in_nexus, remember

MODULE = "time"
TIMESHEETS = "timesheets"
ENTRIES = "timesheet_entries"
ATTENDANCE = "attendance_records"
ROLE_DEFAULTS = "timesheet_role_defaults"
TEMPLATES = "timesheet_user_templates"

SELF_APPROVAL = "akceptacja własnego timesheetu — akceptujący pominięty"
HASH_MISMATCH = "suma kontrolna PDF różna od wpisów"
CHANGED_IN_NEXUS = "timesheet zmieniony w NEXUSIE po imporcie — bez nadpisania"
LOCKED_IN_PAYROLL = "timesheet w zamkniętym miesiącu płac — bez nadpisania"
ATTENDANCE_CHANGED_IN_NEXUS = (
    "dzień obecności zmieniony w NEXUSIE po imporcie — bez nadpisania"
)
NO_DESCRIPTION = "(bez opisu)"
OVERTIME_FALLBACK = "Nadgodziny zatwierdzone w Compassie"
_HASH = re.compile(r"^[0-9a-f]{64}$")

#: Role Compassa → role NEXUSA (``internal`` i ``manager`` nie mają odpowiednika).
ROLE_MAP: dict[str, str] = {
    "admin": "admin",
    "finanse": "finance",
    "talent_community": "talent_community_manager",
}
#: Źródła wpisów, które import może zastąpić przy ponownym przebiegu.
IMPORT_SOURCES = frozenset({"compass_import", "leave_paid"})

HEADER_FIELDS = (
    "status",
    "submitted_at",
    "return_note",
    "approved_by",
    "approved_at",
    "pdf_hash",
)


def _entry(
    row: Mapping[str, Any], people: People, notes: list[str]
) -> Optional[dict[str, Any]]:
    work_date = parse_date(row.get("work_date"))
    hours = decimal(row.get("hours"))
    if work_date is None or hours is None or not Decimal("0") <= hours <= 24:
        notes.append("wpis z niepoprawną datą albo godzinami pominięty")
        return None
    description = text(row.get("description"))
    if description is None:
        description = NO_DESCRIPTION
        notes.append("wpis bez opisu")
    is_overtime = bool(row.get("is_overtime_override"))
    reason = text(row.get("override_reason")) if is_overtime else None
    if is_overtime and (reason is None or len(reason) < OVERTIME_REASON_MIN_LENGTH):
        reason = OVERTIME_FALLBACK
        notes.append("nadgodziny bez uzasadnienia")
    return {
        "work_date": work_date,
        "hours": hours.quantize(Decimal("0.01")),
        "project": text(row.get("project"), 200),
        "description": description,
        "source": "leave_paid"
        if row.get("source") == "leave_paid"
        else "compass_import",
        "is_overtime": is_overtime,
        "overtime_reason": reason,
        "overtime_by": people.account(row.get("override_by")) if is_overtime else None,
    }


def _entry_key(entry: Mapping[str, Any]) -> tuple:
    return (
        entry["work_date"],
        Decimal(entry["hours"]).quantize(Decimal("0.01")),
        entry["project"] or "",
        entry["description"],
        entry["source"],
        bool(entry["is_overtime"]),
        entry["overtime_reason"] or "",
    )


def _hash_of(entries: list[Mapping[str, Any]]) -> str:
    return compute_timesheet_hash(
        HashEntry(
            work_date=entry["work_date"],
            hours=entry["hours"],
            project=entry["project"],
            description=entry["description"],
        )
        for entry in entries
    )


async def _plan_timesheets(
    db: AsyncSession,
    bundle: Bundle,
    people: People,
    mapping: dict,
    result: ImportPlan,
) -> None:
    entries_by_sheet: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for entry in bundle.rows(ENTRIES):
        entries_by_sheet[str(entry.get("timesheet_id"))].append(entry)
    sheet_ids = {str(row.get("id")) for row in bundle.rows(TIMESHEETS)}
    orphans = sum(
        len(rows) for key, rows in entries_by_sheet.items() if key not in sheet_ids
    )
    if orphans:
        result.extra["entries_without_timesheet"] = orphans

    for row in bundle.rows(TIMESHEETS):
        sid = source_id(TIMESHEETS, row)
        compass_id = parse_uuid(row.get("id"))
        if compass_id is None:
            result.rows.append(RowPlan(sid, "skip", "wiersz bez id"))
            continue
        user_id = people.subject(row.get("user_id"))
        if user_id is None:
            result.rows.append(RowPlan(sid, "skip", NO_PROFILE))
            continue
        year, month = small_int(row.get("year")), small_int(row.get("month"))
        if (
            year is None
            or month is None
            or not (2020 <= year <= 2100 and 1 <= month <= 12)
        ):
            result.rows.append(
                RowPlan(sid, "skip", "timesheet bez poprawnego miesiąca")
            )
            continue
        notes: list[str] = []
        status = row.get("status")
        if status == "rejected":
            status = "draft"
        if status not in ("draft", "submitted", "approved"):
            result.rows.append(RowPlan(sid, "skip", "nieznany status timesheetu"))
            continue
        approved_by = people.account(row.get("approved_by"))
        if approved_by is not None and approved_by == user_id:
            approved_by = None
            notes.append(SELF_APPROVAL)
        pdf_hash = text(row.get("pdf_hash"))
        if pdf_hash is not None and not _HASH.match(pdf_hash):
            pdf_hash = None
            notes.append("niepoprawna suma kontrolna PDF pominięta")
        entries = [
            entry
            for entry in (
                _entry(item, people, notes) for item in entries_by_sheet[str(row["id"])]
            )
            if entry is not None
        ]
        if pdf_hash is not None and _hash_of(entries) != pdf_hash:
            notes.append(HASH_MISMATCH)
        header = {
            "status": status,
            "submitted_at": parse_datetime(row.get("submitted_at")),
            "return_note": text(row.get("rejection_note"))
            if status == "draft"
            else None,
            "approved_by": approved_by if status == "approved" else None,
            "approved_at": parse_datetime(row.get("approved_at"))
            if status == "approved"
            else None,
            "pdf_hash": pdf_hash,
        }
        payload = {
            "user_id": user_id,
            "year": year,
            "month": month,
            "compass_id": compass_id,
            "header": header,
            "entries": entries,
            "created_at": parse_datetime(row.get("created_at")),
        }
        reason = join_notes(dict.fromkeys(notes))
        existing = await db.scalar(
            select(Timesheet).where(Timesheet.compass_id == compass_id)
        )
        if existing is None:
            taken = await db.scalar(
                select(Timesheet.id).where(
                    Timesheet.user_id == user_id,
                    Timesheet.year == year,
                    Timesheet.month == month,
                )
            )
            if taken is not None:
                result.rows.append(
                    RowPlan(
                        sid,
                        "conflict",
                        "timesheet tego miesiąca jest już w NEXUSIE",
                        payload,
                    )
                )
            else:
                result.rows.append(RowPlan(sid, "create", reason, payload))
            continue
        payload["timesheet_id"] = existing.id
        current = list(
            await db.scalars(
                select(TimesheetEntry).where(TimesheetEntry.timesheet_id == existing.id)
            )
        )
        current_keys = sorted(
            _entry_key(
                {
                    "work_date": e.work_date,
                    "hours": e.hours,
                    "project": e.project,
                    "description": e.description,
                    "source": e.source,
                    "is_overtime": e.is_overtime,
                    "overtime_reason": e.overtime_reason,
                }
            )
            for e in current
        )
        same_entries = current_keys == sorted(_entry_key(e) for e in entries)
        same = same_entries and not changed_fields(existing, header)
        if not same_entries and any(e.source not in IMPORT_SOURCES for e in current):
            result.rows.append(RowPlan(sid, "conflict", CHANGED_IN_NEXUS, payload))
            continue
        if existing.payroll_locked:
            if same:
                result.rows.append(RowPlan(sid, "unchanged", reason, payload))
            else:
                result.rows.append(RowPlan(sid, "conflict", LOCKED_IN_PAYROLL, payload))
            continue
        if await changed_in_nexus(db, mapping.get(sid), existing.updated_at):
            if same:
                result.rows.append(RowPlan(sid, "unchanged", reason, payload))
            else:
                result.rows.append(RowPlan(sid, "conflict", CHANGED_IN_NEXUS, payload))
            continue
        payload["replace_entries"] = not same_entries
        action = "unchanged" if same else "update"
        result.rows.append(RowPlan(sid, action, reason, payload))


async def _plan_attendance(
    db: AsyncSession,
    bundle: Bundle,
    people: People,
    mapping: dict,
    result: ImportPlan,
) -> None:
    for row in bundle.rows(ATTENDANCE):
        sid = source_id(ATTENDANCE, row)
        user_id = people.subject(row.get("user_id"))
        if user_id is None:
            result.rows.append(RowPlan(sid, "skip", NO_PROFILE))
            continue
        day = parse_date(row.get("date"))
        status = row.get("status")
        if day is None:
            result.rows.append(RowPlan(sid, "skip", "dzień bez daty"))
            continue
        if status in LEAVE_TYPES:
            result.rows.append(
                RowPlan(sid, "skip", "urlop — żyje we wnioskach urlopowych")
            )
            continue
        if status not in ("active", "business_trip"):
            result.rows.append(RowPlan(sid, "skip", "nieznany status obecności"))
            continue
        location: Optional[str] = None
        if status == "active":
            location = row.get("location") if row.get("location") in LOCATIONS else None
            profile = people.profile(user_id)
            default = profile.default_location if profile else None
            if location is None or location == default:
                result.rows.append(
                    RowPlan(sid, "skip", "zgodne z domyślnym miejscem pracy")
                )
                continue
        values = {
            "status": status,
            "location": location,
            "note": text(row.get("note"), 500),
        }
        payload = {"user_id": user_id, "day": day, "values": values}
        existing = await db.scalar(
            select(AttendanceDay).where(
                AttendanceDay.user_id == user_id, AttendanceDay.day == day
            )
        )
        if existing is None:
            result.rows.append(RowPlan(sid, "create", "", payload))
            continue
        payload["attendance_id"] = existing.id
        changed = changed_fields(existing, values)
        if not changed:
            result.rows.append(RowPlan(sid, "unchanged", "", payload))
        elif sid in mapping and await changed_in_nexus(
            db, mapping[sid], existing.updated_at
        ):
            result.rows.append(
                RowPlan(sid, "conflict", ATTENDANCE_CHANGED_IN_NEXUS, payload)
            )
        elif sid in mapping:
            result.rows.append(RowPlan(sid, "update", "", payload))
        else:
            result.rows.append(
                RowPlan(sid, "conflict", "dzień obecności wpisany już w NEXUSIE")
            )


async def _plan_role_defaults(
    db: AsyncSession, bundle: Bundle, people: People, mapping: dict, result: ImportPlan
) -> None:
    for row in bundle.rows(ROLE_DEFAULTS):
        sid = source_id(ROLE_DEFAULTS, row)
        compass_role = row.get("applies_to_role")
        if compass_role == "consultant":
            result.rows.append(
                RowPlan(sid, "skip", "rola konsultanta — zostaje w Akademii")
            )
            continue
        label = text(row.get("label"), 120)
        description = text(row.get("default_description"), 2000)
        if label is None or description is None:
            result.rows.append(RowPlan(sid, "skip", "opis bez etykiety albo treści"))
            continue
        notes: list[str] = []
        role = ROLE_MAP.get(compass_role) if compass_role else None
        active = bool(row.get("is_active", True))
        if compass_role and role is None:
            active = False
            notes.append(
                "rola Compassa bez odpowiednika — opis wyłączony do decyzji Kadr"
            )
        values = {
            "label": label,
            "applies_to_role": role,
            "project": text(row.get("project"), 200),
            "default_description": description,
            "is_active": active,
            "sort_order": small_int(row.get("sort_order")) or 0,
        }
        payload = {
            "values": values,
            "created_by": people.account(row.get("created_by")),
        }
        known = mapping.get(sid)
        existing = (
            await db.get(TimesheetRoleDefault, int(known.target_id)) if known else None
        )
        reason = join_notes(notes)
        if existing is None:
            twin = await db.scalar(
                select(TimesheetRoleDefault.id).where(
                    TimesheetRoleDefault.label == label,
                    TimesheetRoleDefault.default_description == description,
                    (
                        TimesheetRoleDefault.applies_to_role.is_(None)
                        if role is None
                        else TimesheetRoleDefault.applies_to_role == role
                    ),
                )
            )
            action = "unchanged" if twin is not None else "create"
            result.rows.append(RowPlan(sid, action, reason, payload))
            continue
        payload["default_id"] = existing.id
        action = "update" if changed_fields(existing, values) else "unchanged"
        result.rows.append(RowPlan(sid, action, reason, payload))


async def _plan_templates(
    db: AsyncSession, bundle: Bundle, people: People, mapping: dict, result: ImportPlan
) -> None:
    for row in bundle.rows(TEMPLATES):
        sid = source_id(TEMPLATES, row)
        user_id = people.subject(row.get("user_id"))
        if user_id is None:
            result.rows.append(RowPlan(sid, "skip", NO_PROFILE))
            continue
        name = text(row.get("name"), 80)
        description = text(row.get("description"), 2000)
        if name is None or description is None:
            result.rows.append(RowPlan(sid, "skip", "fragment bez nazwy albo treści"))
            continue
        values = {
            "name": name,
            "description": description,
            "project": text(row.get("project"), 200),
            "sort_order": small_int(row.get("sort_order")) or 0,
        }
        payload = {"user_id": user_id, "values": values}
        known = mapping.get(sid)
        existing = (
            await db.get(TimesheetTemplate, int(known.target_id)) if known else None
        )
        if existing is not None:
            payload["template_id"] = existing.id
            action = "update" if changed_fields(existing, values) else "unchanged"
            result.rows.append(RowPlan(sid, action, "", payload))
            continue
        same_name = await db.scalar(
            select(TimesheetTemplate).where(
                TimesheetTemplate.user_id == user_id, TimesheetTemplate.name == name
            )
        )
        if same_name is None:
            result.rows.append(RowPlan(sid, "create", "", payload))
        elif not changed_fields(same_name, values):
            result.rows.append(RowPlan(sid, "unchanged", "", payload))
        else:
            result.rows.append(
                RowPlan(sid, "conflict", "fragment o tej nazwie jest już w NEXUSIE")
            )


async def plan(db: AsyncSession, bundle: Bundle) -> ModulePlan:
    result = ImportPlan(module=MODULE)
    people = await load_people(db, bundle)
    mapping = await module_map(db, MODULE)
    await _plan_timesheets(db, bundle, people, mapping, result)
    await _plan_attendance(db, bundle, people, mapping, result)
    await _plan_role_defaults(db, bundle, people, mapping, result)
    await _plan_templates(db, bundle, people, mapping, result)
    tables = Counter(row.source_id.split(":", 1)[0] for row in result.rows)
    result.extra["rows_per_table"] = dict(tables)
    return result


def _entry_rows(
    timesheet_id: int, entries: list[dict[str, Any]]
) -> list[TimesheetEntry]:
    return [TimesheetEntry(timesheet_id=timesheet_id, **entry) for entry in entries]


async def _write_timesheet(
    db: AsyncSession, row: RowPlan, written: dict[str, int]
) -> Optional[Timesheet]:
    payload = row.payload
    if row.action == "create":
        sheet = Timesheet(
            user_id=payload["user_id"],
            year=payload["year"],
            month=payload["month"],
            compass_id=payload["compass_id"],
            **payload["header"],
        )
        if payload["created_at"] is not None:
            sheet.created_at = payload["created_at"]
        db.add(sheet)
        await db.flush()
        db.add_all(_entry_rows(sheet.id, payload["entries"]))
        written["timesheets_created"] += 1
        written["entries_written"] += len(payload["entries"])
    else:
        sheet = await db.get(Timesheet, payload["timesheet_id"])
        for key, value in payload["header"].items():
            setattr(sheet, key, value)
        if payload.get("replace_entries"):
            await db.execute(
                delete(TimesheetEntry).where(TimesheetEntry.timesheet_id == sheet.id)
            )
            db.add_all(_entry_rows(sheet.id, payload["entries"]))
            written["entries_written"] += len(payload["entries"])
        written["timesheets_updated"] += 1
    await db.flush()
    return sheet


async def _hash_matches(db: AsyncSession, sheet: Timesheet) -> bool:
    entries = await db.scalars(
        select(TimesheetEntry).where(TimesheetEntry.timesheet_id == sheet.id)
    )
    computed = compute_timesheet_hash(
        HashEntry(e.work_date, e.hours, e.project, e.description) for e in entries
    )
    return computed == sheet.pdf_hash


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {
        "timesheets_created": 0,
        "timesheets_updated": 0,
        "entries_written": 0,
        "hash_mismatch": 0,
        "attendance_written": 0,
        "role_defaults_written": 0,
        "templates_written": 0,
    }
    for row in module_plan.rows:
        if row.action not in ("create", "update"):
            continue
        table = row.source_id.split(":", 1)[0]
        payload = row.payload
        if table == TIMESHEETS:
            sheet = await _write_timesheet(db, row, written)
            if sheet.pdf_hash is not None and not await _hash_matches(db, sheet):
                written["hash_mismatch"] += 1
            target_table, target_id = "timesheets", sheet.id
        elif table == ATTENDANCE:
            if row.action == "create":
                day = AttendanceDay(
                    user_id=payload["user_id"],
                    day=payload["day"],
                    created_by=actor_user_id,
                    **payload["values"],
                )
                db.add(day)
            else:
                day = await db.get(AttendanceDay, payload["attendance_id"])
                for key, value in payload["values"].items():
                    setattr(day, key, value)
            await db.flush()
            written["attendance_written"] += 1
            target_table, target_id = "attendance_days", day.id
        elif table == ROLE_DEFAULTS:
            if row.action == "create":
                default = TimesheetRoleDefault(
                    created_by=payload["created_by"], **payload["values"]
                )
                db.add(default)
            else:
                default = await db.get(TimesheetRoleDefault, payload["default_id"])
                for key, value in payload["values"].items():
                    setattr(default, key, value)
            await db.flush()
            written["role_defaults_written"] += 1
            target_table, target_id = "timesheet_role_defaults", default.id
        elif table == TEMPLATES:
            if row.action == "create":
                template = TimesheetTemplate(
                    user_id=payload["user_id"], **payload["values"]
                )
                db.add(template)
            else:
                template = await db.get(TimesheetTemplate, payload["template_id"])
                for key, value in payload["values"].items():
                    setattr(template, key, value)
            await db.flush()
            written["templates_written"] += 1
            target_table, target_id = "timesheet_templates", template.id
        else:
            continue
        await remember(
            db,
            module=MODULE,
            source_id=row.source_id,
            target_table=target_table,
            target_id=target_id,
            decision="auto",
            batch=batch,
        )
    await db.flush()
    return written
