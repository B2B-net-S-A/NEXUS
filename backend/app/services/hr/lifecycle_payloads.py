"""Odczyt spraw wejścia i odejścia — zapytania i kształty odpowiedzi tras.

Serwis spraw (lifecycle_service) zapisuje; tu jest to, co karta sprawy,
lista i szablony pokazują: zadania sprawy, przekazania pracy, imiona osób,
link do sprawy i słowniki odpowiedzi.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.hr_lifecycle import (
    LifecycleCase,
    LifecycleTask,
    LifecycleTemplate,
    LifecycleTemplateItem,
    WorkHandover,
)
from app.models.user import User
from app.services.hr_lifecycle_schema import LIVE_CASE_STATUSES, TRANSFER_KINDS


async def case_tasks(db: AsyncSession, case_id: int) -> list[LifecycleTask]:
    return list(
        await db.scalars(
            select(LifecycleTask)
            .where(LifecycleTask.case_id == case_id)
            .order_by(
                LifecycleTask.due_date.asc().nulls_last(),
                LifecycleTask.position,
                LifecycleTask.id,
            )
        )
    )


def handover_started(case: LifecycleCase, handovers: list[WorkHandover]) -> bool:
    return case.handover_executed_at is not None or any(
        row.status == "done" for row in handovers
    )


async def case_handovers(db: AsyncSession, case_id: int) -> list[WorkHandover]:
    rows = await db.scalars(select(WorkHandover).where(WorkHandover.case_id == case_id))
    order = {kind: index for index, kind in enumerate(TRANSFER_KINDS)}
    return sorted(rows, key=lambda row: order.get(row.work_kind, 99))


async def person_name(db: AsyncSession, case: LifecycleCase) -> str:
    if case.user_id is not None:
        name = await db.scalar(select(User.name).where(User.id == case.user_id))
        if name:
            return name
    return case.pending_name or "nowa osoba"


def case_link(case: LifecycleCase) -> str:
    if case.audience == "consultant" and case.contract_id is not None:
        return f"/contracts/{case.contract_id}?tab=onboarding"
    if case.kind == "offboarding" and case.user_id is not None:
        return f"/people/{case.user_id}/offboarding"
    return f"/people/new/{case.id}"


def template_payload(
    template: LifecycleTemplate,
    items: list[LifecycleTemplateItem],
    *,
    can_edit: bool = False,
    live_cases_behind: int = 0,
) -> dict[str, Any]:
    return {
        "id": template.id,
        "kind": template.kind,
        "audience": template.audience,
        "version": template.version,
        "name": template.name,
        "is_active": template.is_active,
        "employment_type": template.employment_type,
        "department": template.department,
        "can_edit": can_edit,
        "live_cases_behind": live_cases_behind,
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "category": item.category,
                "assignee_kind": item.assignee_kind,
                "due_offset_days": item.due_offset_days,
                "description": item.description,
                "required": item.required,
                "requires_file": item.requires_file,
                "conditions": item.conditions or {},
                "key": item.key,
                "added_in_version": item.added_in_version,
            }
            for item in items
        ],
    }


async def live_cases_behind(db: AsyncSession, template: LifecycleTemplate) -> int:
    """Trwające sprawy tej ścieżki na starszej wersji (baner „Dociągnij”)."""

    from sqlalchemy import func, or_  # noqa: PLC0415

    return int(
        await db.scalar(
            select(func.count())
            .select_from(LifecycleCase)
            .where(
                LifecycleCase.template_id == template.id,
                LifecycleCase.status.in_(LIVE_CASE_STATUSES),
                or_(
                    LifecycleCase.template_version.is_(None),
                    LifecycleCase.template_version < template.version,
                ),
            )
        )
        or 0
    )


async def _names(db: AsyncSession, ids: Iterable[Optional[int]]) -> dict[int, str]:
    """Imiona kont — zbiór wołającego zostaje nietknięty."""

    wanted = {user_id for user_id in ids if user_id is not None}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {user_id: name for user_id, name in rows.all()}


def task_payload(
    task: LifecycleTask,
    names: dict[int, str],
    *,
    can_toggle: bool,
    today: date,
    mirror: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Zadanie sprawy. ``mirror`` — zadanie prowadzi inny moduł (zestaw sprzętu
    odhacza recepcja w Sprzęcie): stan stamtąd, odhaczenie tylko tam."""

    status = mirror["status"] if mirror else task.status
    return {
        "id": task.id,
        "title": task.title,
        "category": task.category,
        "assignee_kind": task.assignee_kind,
        "assignee_user_id": task.assignee_user_id,
        "assignee_name": names.get(task.assignee_user_id)
        if task.assignee_user_id
        else None,
        "due_date": task.due_date,
        "status": status,
        "overdue": status == "open"
        and task.due_date is not None
        and task.due_date < today,
        "done_at": task.done_at,
        "done_by_name": names.get(task.done_by) if task.done_by else None,
        "note": task.note,
        "description": task.description,
        "required": task.required,
        "requires_file": task.requires_file,
        "key": task.key,
        "source": task.source,
        "source_label": task.source_label,
        "from_template": task.template_item_id is not None,
        "mirror": mirror,
        "can_toggle": can_toggle and mirror is None,
    }


async def case_payload(
    db: AsyncSession,
    case: LifecycleCase,
    *,
    viewer: User,
    scope: str,
    with_work: bool = True,
) -> dict[str, Any]:
    from app.services.hr.handover import WORK_KINDS, work_summary  # noqa: PLC0415
    from app.services.hr.lifecycle_access import can_toggle  # noqa: PLC0415
    from app.services.hr.lifecycle_dates import handover_moment  # noqa: PLC0415

    tasks = await case_tasks(db, case.id)
    handovers = await case_handovers(db, case.id) if case.kind == "offboarding" else []
    mirrors = await task_mirrors(db, case, tasks)
    ids = {
        case.manager_user_id,
        case.owner_user_id,
        case.user_id,
        *(task.assignee_user_id for task in tasks),
        *(task.done_by for task in tasks),
        *(row.receiver_user_id for row in handovers),
    }
    names = await _names(db, ids)
    today = business_today()
    template = (
        await db.get(LifecycleTemplate, case.template_id) if case.template_id else None
    )
    statuses = [
        mirrors[task.id]["status"] if task.id in mirrors else task.status
        for task in tasks
    ]
    started = handover_started(case, handovers)
    payload: dict[str, Any] = {
        "id": case.id,
        "kind": case.kind,
        "status": case.status,
        "user_id": case.user_id,
        "person_name": await person_name(db, case),
        "pending_email": case.pending_email if scope == "admin" else None,
        "template_id": case.template_id,
        "template_name": template.name if template else None,
        "audience": case.audience,
        "contract_id": case.contract_id,
        "template_version": case.template_version,
        "template_current_version": template.version if template else None,
        "start_date": case.start_date,
        "last_working_day": case.last_working_day,
        "deactivate_on": case.deactivate_on,
        "handover_at": handover_moment(case.last_working_day)
        if case.last_working_day
        else None,
        "manager_user_id": case.manager_user_id,
        "manager_name": names.get(case.manager_user_id)
        if case.manager_user_id
        else None,
        "owner_name": names.get(case.owner_user_id) if case.owner_user_id else None,
        "started_at": case.started_at,
        "handover_executed_at": case.handover_executed_at,
        "account_closed_at": case.account_closed_at,
        "account_close_result": case.account_close_result,
        "completed_at": case.completed_at,
        "cancelled_at": case.cancelled_at,
        "scope": scope,
        "can_manage": scope == "admin",
        "can_cancel": scope == "admin"
        and case.status in LIVE_CASE_STATUSES
        and case.account_closed_at is None
        and not started,
        "can_add_task": scope in ("admin", "manager")
        and case.status in LIVE_CASE_STATUSES,
        "tasks": [
            task_payload(
                task,
                names,
                can_toggle=can_toggle(scope, viewer, task),  # type: ignore[arg-type]
                today=today,
                mirror=mirrors.get(task.id),
            )
            for task in tasks
        ],
        "progress": {
            "done": sum(1 for status in statuses if status != "open"),
            "total": len(tasks),
            "overdue": sum(
                1
                for task, status in zip(tasks, statuses)
                if status == "open" and task.due_date and task.due_date < today
            ),
        },
    }
    if scope in ("admin", "manager"):
        payload["exit_initiator"] = case.exit_initiator
        payload["exit_reason"] = case.exit_reason
        payload["exit_note"] = case.exit_note
        if case.kind == "onboarding":
            payload["profile_values"] = case.profile_values or {}
    if case.kind == "offboarding":
        counts: dict[str, int] = {}
        if with_work and case.user_id is not None and case.last_working_day is not None:
            counts = await work_summary(
                db, case.user_id, last_working_day=case.last_working_day
            )
        by_kind = {row.work_kind: row for row in handovers}
        payload["work"] = [
            {
                "kind": kind.key,
                "label": kind.label,
                "note": kind.note,
                "transferable": kind.transferable,
                "count": counts.get(kind.key),
                "receiver_user_id": by_kind[kind.key].receiver_user_id
                if kind.key in by_kind
                else None,
                "receiver_name": names.get(by_kind[kind.key].receiver_user_id)
                if kind.key in by_kind and by_kind[kind.key].receiver_user_id
                else None,
                "status": by_kind[kind.key].status if kind.key in by_kind else None,
                "planned_count": by_kind[kind.key].item_count
                if kind.key in by_kind
                else None,
                "result": by_kind[kind.key].result if kind.key in by_kind else None,
                "error": by_kind[kind.key].error if kind.key in by_kind else None,
            }
            for kind in WORK_KINDS
        ]
    return payload


#: Stan zadania recepcji (moduł Sprzęt) → stan zadania sprawy.
_EQUIPMENT_STATUS: dict[str, str] = {
    "otwarte": "open",
    "zrobione": "done",
    "anulowane": "skipped",
}


async def task_mirrors(
    db: AsyncSession, case: LifecycleCase, tasks: list[LifecycleTask]
) -> dict[int, dict[str, Any]]:
    """Zadania sprawy prowadzone w innym module (bez dubla, jedna prawda).

    Zestaw sprzętu wejścia konsultanta (``equipment_kit``) to zadanie recepcji
    ``contract:{id}:start``, które zakłada hak Sprzętu — gdy istnieje, lista
    wejścia pokazuje jego stan, a odhacza się je w Sprzęcie. Bez zadania
    recepcji (moduł wyłączony, zestaw już wydany) pozycja jest zwykłym zadaniem.
    """

    from app.models.equipment import EquipmentTask  # noqa: PLC0415
    from app.services.hr_lifecycle_schema import KEY_EQUIPMENT_KIT  # noqa: PLC0415

    if case.audience != "consultant" or case.contract_id is None:
        return {}
    kit = [task for task in tasks if task.key == KEY_EQUIPMENT_KIT]
    if not kit:
        return {}
    row = (
        await db.execute(
            select(EquipmentTask.id, EquipmentTask.status).where(
                EquipmentTask.source_key == f"contract:{case.contract_id}:start"
            )
        )
    ).first()
    if row is None:
        return {}
    mirror = {
        "module": "equipment",
        "task_id": row.id,
        "status": _EQUIPMENT_STATUS.get(row.status, "open"),
        "note": "Odhacza recepcja w Sprzęcie.",
    }
    return {task.id: mirror for task in kit}


async def latest_case_for(db: AsyncSession, user_id: int) -> Optional[LifecycleCase]:
    """Ostatnia sprawa osoby (żywa przed zamkniętą)."""

    rows = list(
        await db.scalars(
            select(LifecycleCase)
            .where(LifecycleCase.user_id == user_id)
            .order_by(LifecycleCase.created_at.desc(), LifecycleCase.id.desc())
        )
    )
    live = [row for row in rows if row.status in LIVE_CASE_STATUSES]
    return (live or rows or [None])[0]


__all__ = [
    "live_cases_behind",
    "task_mirrors",
    "case_handovers",
    "case_link",
    "case_payload",
    "case_tasks",
    "handover_started",
    "latest_case_for",
    "person_name",
    "task_payload",
    "template_payload",
]
