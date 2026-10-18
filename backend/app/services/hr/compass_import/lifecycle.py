"""Import spraw wejścia i odejścia z Compassa.

Tabele Compassa (małe: kilka spraw, kilkadziesiąt zadań):

* odejście: ``exit_interviews`` (źródło prawdy w kodzie Compassa) albo jego
  lustro ``exit_cases`` (to samo id; na produkcji obie mogą istnieć) →
  ``lifecycle_cases`` z ``kind = 'offboarding'``, zadania z
  ``offboarding_tasks`` (Compass wiąże je z osobą, nie ze sprawą — trafiają
  do najnowszej nieanulowanej sprawy odejścia tej osoby),
* wejście: ``onboarding_progress`` albo ``onboarding_cases`` (to samo id) →
  ``kind = 'onboarding'``, zadania z ``onboarding_tasks`` (``progress_id``).

Statusy i pętla ``lifecycle_jobs.run_once``: pętla przekazuje pracę i wyłącza
konta WYŁĄCZNIE w sprawach ``active``. Import nie zakłada spraw ``active``:

* sprawa zamknięta w Compassie (osoba ``exited``, ankieta przejrzana albo
  zarchiwizowana, wejście ukończone) → ``done``, a zadania nieodhaczone →
  ``skipped`` — bez przekazania pracy i bez wyłączania kont,
* sprawa anulowana → ``cancelled``,
* sprawa w toku → ``draft``: Kadry uruchamiają ją w NEXUSIE świadomie
  („Rozpocznij”), dopiero wtedy działa przekazanie pracy i wyłączenie konta.

Powód odejścia przechodzi tylko jako słownik (``role_misfit`` → ``role_fit``,
``personal`` → ``other``); wolny tekst powodu i odpowiedzi ankiety zostają
w Compassie — sprawa odejścia nie trzyma danych o zdrowiu.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.hr_ops import HrImportBatch
from app.services.hr_lifecycle_schema import EXIT_REASONS, LIVE_CASE_STATUSES

from .bundle import Bundle
from .common import (
    NO_PROFILE,
    ImportPlan,
    People,
    changed_fields,
    join_notes,
    load_people,
    parse_date,
    parse_datetime,
    parse_uuid,
    small_int,
    text,
)
from .core import ModulePlan, RowPlan, remember

MODULE = "lifecycle"
EXIT_TABLE = "exit_cases"
ONBOARDING_TABLE = "onboarding_cases"

EXIT_REASON_MAP: dict[str, str] = {
    "new_opportunity": "new_opportunity",
    "compensation": "compensation",
    "role_misfit": "role_fit",
    "management": "management",
    "work_life_balance": "work_life_balance",
    "career_growth": "career_growth",
    "personal": "other",
    "other": "other",
}
OFFBOARDING_CATEGORY: dict[str, str] = {
    "access_revoke": "accounts",
    "equipment_return": "equipment",
    "final_settlement": "documents",
    "docs_archive": "documents",
    "knowledge_transfer": "other",
    "other": "other",
}
ONBOARDING_CATEGORY: dict[str, str] = {
    "docs": "documents",
    "access": "accounts",
    "training": "training",
    "meeting": "meeting",
    "equipment": "equipment",
    "other": "other",
}
#: Kto wykonuje: rola Compassa → wykonawca NEXUSA (bez opiekuna-„buddy”).
ASSIGNEE_MAP: dict[str, str] = {
    "employee": "person",
    "manager": "manager",
    "buddy": "manager",
    "tcm": "people_admin",
    "finanse": "people_admin",
    "admin": "it",
}
DRAFT_NOTE = "sprawa w toku w Compassie — szkic do uruchomienia przez Kadry"
SKIPPED_TASKS = "zadania nieodhaczone w zamkniętej sprawie — pominięte"
CASE_FIELDS = (
    "status",
    "start_date",
    "last_working_day",
    "owner_user_id",
    "manager_user_id",
    "exit_reason",
    "started_at",
    "completed_at",
    "cancelled_at",
    "cancelled_by",
)
assert set(EXIT_REASON_MAP.values()) <= set(EXIT_REASONS)


def exit_rows(bundle: Bundle) -> list[dict[str, Any]]:
    """Sprawy odejścia: ``exit_interviews`` wygrywa z lustrem ``exit_cases``."""

    rows: dict[str, dict[str, Any]] = {}
    for row in bundle.rows("exit_cases"):
        rows[str(row.get("id"))] = dict(row)
    for row in bundle.rows("exit_interviews"):
        key = str(row.get("id"))
        rows[key] = {
            **rows.get(key, {}),
            **row,
            "person_type": "employee",
            "person_id": row.get("user_id"),
        }
    return list(rows.values())


def onboarding_rows(bundle: Bundle) -> list[dict[str, Any]]:
    """Sprawy wejścia: ``onboarding_progress`` wygrywa z lustrem ``onboarding_cases``."""

    rows: dict[str, dict[str, Any]] = {}
    for row in bundle.rows("onboarding_cases"):
        rows[str(row.get("id"))] = dict(row)
    for row in bundle.rows("onboarding_progress"):
        key = str(row.get("id"))
        status = (
            "cancelled"
            if row.get("cancelled_at")
            else "completed"
            if row.get("completed_at")
            else "active"
        )
        rows[key] = {
            **rows.get(key, {}),
            **row,
            "person_type": "employee",
            "person_id": row.get("user_id"),
            "status": status,
        }
    return list(rows.values())


def _closed_at(row: Mapping[str, Any], *keys: str) -> Optional[datetime]:
    for key in keys:
        moment = parse_datetime(row.get(key))
        if moment is not None:
            return moment
    return None


def _task(
    row: Mapping[str, Any],
    *,
    categories: Mapping[str, str],
    people: People,
    case: Mapping[str, Any],
) -> dict[str, Any]:
    assignee_kind = ASSIGNEE_MAP.get(str(row.get("responsible_role")), "people_admin")
    assignee_user_id = None
    if assignee_kind == "person":
        assignee_user_id = case["user_id"]
    elif assignee_kind == "manager":
        assignee_user_id = case["manager_user_id"]
    done_at = parse_datetime(row.get("completed_at"))
    if done_at is not None:
        status = "done"
    elif case["status"] in ("done", "cancelled"):
        done_at = case["completed_at"] or case["cancelled_at"]
        # Pominięte zadanie potrzebuje daty zamknięcia; bez niej zostaje otwarte.
        status = "skipped" if done_at is not None else "open"
    else:
        status = "open"
    return {
        "position": small_int(row.get("position")) or 0,
        "title": text(row.get("title"), 200) or "Zadanie z Compassa",
        "category": categories.get(str(row.get("category")), "other"),
        "assignee_kind": assignee_kind,
        "assignee_user_id": assignee_user_id,
        "due_date": parse_date(row.get("due_date")),
        "status": status,
        "done_by": people.account(row.get("completed_by"))
        if status == "done"
        else None,
        "done_at": done_at,
        "note": text(row.get("notes"), 500),
    }


def _task_key(task: Mapping[str, Any]) -> tuple:
    return (
        task["position"],
        task["title"],
        task["category"],
        task["assignee_kind"],
        task["due_date"],
        task["status"],
        task["note"] or "",
    )


def _case_values(
    row: Mapping[str, Any], *, kind: str, people: People, user_id: int
) -> tuple[Optional[dict[str, Any]], list[str], Optional[str]]:
    """Pola sprawy NEXUSA albo powód pominięcia (trzeci element)."""

    notes: list[str] = []
    compass_profile = people.compass_row(row.get("person_id")) or {}
    profile = people.profile(user_id)
    raw_status = str(row.get("status") or "")
    exited = compass_profile.get("employment_status") == "exited" or (
        profile is not None and profile.employment_status == "exited"
    )
    if raw_status == "cancelled" or row.get("cancelled_at"):
        status = "cancelled"
    elif kind == "offboarding" and (exited or raw_status in ("reviewed", "archived")):
        status = "done"
    elif kind == "onboarding" and raw_status in ("completed", "reviewed", "archived"):
        status = "done"
    else:
        status = "draft"
        notes.append(DRAFT_NOTE)

    start_date = last_working_day = None
    if kind == "offboarding":
        last_working_day = (
            parse_date(compass_profile.get("termination_date"))
            or (profile.last_working_day if profile else None)
            or parse_date(row.get("end_date"))
        )
        if last_working_day is None:
            return None, notes, "odejście bez ostatniego dnia pracy"
    else:
        start_date = (
            parse_date(row.get("start_date"))
            or parse_date(compass_profile.get("work_start_date"))
            or parse_date(compass_profile.get("hired_at"))
            or (profile.work_start_date or profile.hired_on if profile else None)
        )
        if start_date is None:
            start_date = parse_date(row.get("started_at"))
            if start_date is not None:
                notes.append("data startu z początku sprawy w Compassie")
        if start_date is None:
            return None, notes, "wejście bez daty startu"

    manager = people.account(row.get("manager_snapshot"))
    if manager is None and profile is not None:
        manager = profile.manager_user_id
    if manager == user_id:
        manager = None
    exit_reason = (
        EXIT_REASON_MAP.get(str(row.get("exit_reason")))
        if kind == "offboarding" and row.get("exit_reason")
        else None
    )
    created = parse_datetime(row.get("started_at")) or parse_datetime(
        row.get("created_at")
    )
    values = {
        "status": status,
        "start_date": start_date,
        "last_working_day": last_working_day,
        "owner_user_id": people.account(row.get("owner_id") or row.get("created_by")),
        "manager_user_id": manager,
        "exit_reason": exit_reason,
        "started_at": created if status != "draft" else None,
        "completed_at": _closed_at(
            row, "completed_at", "reviewed_at", "updated_at", "created_at"
        )
        if status == "done"
        else None,
        "cancelled_at": _closed_at(row, "cancelled_at", "updated_at", "created_at")
        if status == "cancelled"
        else None,
        "cancelled_by": people.account(row.get("cancelled_by"))
        if status == "cancelled"
        else None,
    }
    return values, notes, None


async def plan(db: AsyncSession, bundle: Bundle) -> ModulePlan:
    result = ImportPlan(module=MODULE)
    people = await load_people(db, bundle)

    offboarding_tasks: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for task in bundle.rows("offboarding_tasks"):
        offboarding_tasks[str(task.get("user_id"))].append(task)
    onboarding_tasks: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for task in bundle.rows("onboarding_tasks"):
        onboarding_tasks[str(task.get("progress_id"))].append(task)

    exits = exit_rows(bundle)
    # Zadania odejścia → najnowsza nieanulowana sprawa osoby (inaczej najnowsza).
    exit_for_person: dict[str, str] = {}
    for row in sorted(
        exits,
        key=lambda r: (
            r.get("status") != "cancelled" and not r.get("cancelled_at"),
            str(r.get("created_at") or ""),
        ),
    ):
        if row.get("person_id"):
            exit_for_person[str(row["person_id"])] = str(row.get("id"))
    unattached = sum(
        len(tasks)
        for person, tasks in offboarding_tasks.items()
        if person not in exit_for_person
    )
    if unattached:
        result.extra["offboarding_tasks_without_case"] = unattached

    claimed_live: set[tuple[int, str]] = set()
    task_counts: Counter[str] = Counter()
    sources = [(EXIT_TABLE, "offboarding", row) for row in exits] + [
        (ONBOARDING_TABLE, "onboarding", row) for row in onboarding_rows(bundle)
    ]
    for table, kind, row in sources:
        sid = f"{table}:{row.get('id')}"
        compass_id = parse_uuid(row.get("id"))
        if compass_id is None:
            result.rows.append(RowPlan(sid, "skip", "wiersz bez id"))
            continue
        if row.get("person_type", "employee") != "employee":
            result.rows.append(
                RowPlan(sid, "skip", "sprawa kontraktora — poza kartoteką pracowników")
            )
            continue
        if not row.get("person_id") or row.get("is_anonymous"):
            result.rows.append(RowPlan(sid, "skip", "anonimowa ankieta — bez osoby"))
            continue
        user_id = people.subject(row.get("person_id"))
        if user_id is None:
            result.rows.append(RowPlan(sid, "skip", NO_PROFILE))
            continue
        values, notes, refusal = _case_values(
            row, kind=kind, people=people, user_id=user_id
        )
        if values is None:
            result.rows.append(RowPlan(sid, "skip", refusal or ""))
            continue

        case_view = {**values, "user_id": user_id}
        if kind == "offboarding":
            source_tasks = (
                offboarding_tasks.get(str(row["person_id"]), [])
                if exit_for_person.get(str(row["person_id"])) == str(row.get("id"))
                else []
            )
            categories = OFFBOARDING_CATEGORY
        else:
            source_tasks = onboarding_tasks.get(str(row.get("id")), [])
            categories = ONBOARDING_CATEGORY
        tasks = [
            _task(task, categories=categories, people=people, case=case_view)
            for task in source_tasks
        ]
        if any(task["status"] == "skipped" for task in tasks):
            notes.append(SKIPPED_TASKS)
        task_counts[kind] += len(tasks)
        payload = {
            "user_id": user_id,
            "kind": kind,
            "compass_id": compass_id,
            "values": values,
            "tasks": tasks,
            "created_at": parse_datetime(row.get("created_at")),
        }
        reason = join_notes(notes)
        existing = await db.scalar(
            select(LifecycleCase).where(LifecycleCase.compass_id == compass_id)
        )
        if existing is not None:
            payload["case_id"] = existing.id
            current = await db.scalars(
                select(LifecycleTask).where(LifecycleTask.case_id == existing.id)
            )
            same_tasks = sorted(
                _task_key(
                    {
                        key: getattr(task, key)
                        for key in (
                            "position",
                            "title",
                            "category",
                            "assignee_kind",
                            "due_date",
                            "status",
                            "note",
                        )
                    }
                )
                for task in current
            ) == sorted(_task_key(task) for task in tasks)
            if not same_tasks:
                result.rows.append(
                    RowPlan(
                        sid,
                        "conflict",
                        "zadania sprawy zmienione w NEXUSIE po imporcie — bez nadpisania",
                        payload,
                    )
                )
                continue
            changed = changed_fields(existing, values)
            if changed and existing.status not in ("draft", values["status"]):
                # Kadry uruchomiły albo zamknęły sprawę w NEXUSIE — import jej
                # nie cofa (np. ``active`` z powrotem do szkicu).
                result.rows.append(
                    RowPlan(
                        sid,
                        "conflict",
                        "sprawa prowadzona dalej w NEXUSIE — bez nadpisania",
                        payload,
                    )
                )
                continue
            result.rows.append(
                RowPlan(sid, "update" if changed else "unchanged", reason, payload)
            )
            continue
        if values["status"] in LIVE_CASE_STATUSES:
            live = (user_id, kind) in claimed_live or (
                await db.scalar(
                    select(LifecycleCase.id).where(
                        LifecycleCase.user_id == user_id,
                        LifecycleCase.kind == kind,
                        LifecycleCase.status.in_(LIVE_CASE_STATUSES),
                    )
                )
            ) is not None
            if live:
                result.rows.append(
                    RowPlan(
                        sid,
                        "conflict",
                        "sprawa tej osoby w toku jest już w NEXUSIE",
                        payload,
                    )
                )
                continue
            claimed_live.add((user_id, kind))
        result.rows.append(RowPlan(sid, "create", reason, payload))
    result.extra["tasks_per_kind"] = dict(task_counts)
    return result


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {"cases_created": 0, "cases_updated": 0, "tasks_written": 0}
    for row in module_plan.rows:
        if row.action not in ("create", "update"):
            continue
        payload = row.payload
        if row.action == "create":
            case = LifecycleCase(
                user_id=payload["user_id"],
                kind=payload["kind"],
                compass_id=payload["compass_id"],
                created_by=actor_user_id,
                **payload["values"],
            )
            if payload["created_at"] is not None:
                case.created_at = payload["created_at"]
            db.add(case)
            await db.flush()
            db.add_all(
                LifecycleTask(case_id=case.id, **task) for task in payload["tasks"]
            )
            written["cases_created"] += 1
            written["tasks_written"] += len(payload["tasks"])
        else:
            case = await db.get(LifecycleCase, payload["case_id"])
            for key, value in payload["values"].items():
                setattr(case, key, value)
            written["cases_updated"] += 1
        await db.flush()
        await remember(
            db,
            module=MODULE,
            source_id=row.source_id,
            target_table="lifecycle_cases",
            target_id=case.id,
            decision="auto",
            batch=batch,
        )
    await db.flush()
    return written
