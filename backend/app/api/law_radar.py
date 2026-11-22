"""Ekran „Przepisy” (``/compliance``): zmiany w prawie, zadania, dziennik, biegi.

Dostęp (decyzja z ``docs/claude/przepisy/radar-przepisow-dwa-boty.md``):
administrator, Head of Recruitment z tytułu roli oraz każdy z uprawnieniem
„Moduł Finanse”, „Płace”, „Kadry” albo „Kontrakty i zamówienia” — to osoby,
których dotyczą role zmian (zarząd, księgowość, płace, umowy, rekrutacja).
Nowego uprawnienia nie ma. Ręczny start Zbieracza tylko administrator.

Przy wyłączonym ``LAW_RADAR_ENABLED`` listy odpowiadają ``{"enabled": false}``
(ekran mówi „Radar wyłączony”), a zapisy 409.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, require_onboarded_user
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.law_radar import (
    LawChange,
    LawChangeEvent,
    LawChangeProbe,
    LawChangeTask,
    LawRadarItem,
    LawRadarRun,
)
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.law_radar import collect, flow, runs, schema
from app.services.permission_denial import ensure_any_permission
from app.services.sales.bot_tasks.base import numbers_only

router = APIRouter()

#: Uprawnienia, które otwierają „Przepisy” (bez nowego uprawnienia).
COMPLIANCE_PERMISSIONS: tuple[ProductAction, ...] = (
    ProductAction.finance_module,
    ProductAction.payroll,
    ProductAction.people_admin,
    ProductAction.contracts_orders_edit,
)
COMPLIANCE_ROLES: tuple[UserRole, ...] = (UserRole.admin, UserRole.head_of_recruitment)

DISABLED_DETAIL = "Radar przepisów jest wyłączony."
CHANGE_NOT_FOUND = "Nie ma takiej zmiany."
TASK_NOT_FOUND = "Nie ma takiego zadania."
NOTE_REQUIRED = "„Nie dotyczy” wymaga powodu."
NO_PERSON = "Nie ma takiej aktywnej osoby."
NOT_CONFIGURED = (
    "Zbieracz nie ma jeszcze adresu webhooka — ustaw go workflowem „Coolify set env”."
)
COLLECT_RUNNING = "Zbieracz już pracuje nad biegiem #{run_id}."
DEADLINE_WINDOW_DAYS = 60
TOP_TITLES = 3
RUNS_LISTED = 10
NOTE_MAX = 1000

URGENCY_ORDER = case(
    {"now": 0, "soon": 1, "watch": 2}, value=LawChange.urgency, else_=3
)

RoleFilter = Literal[schema.ROLES]  # type: ignore[valid-type]
StatusValue = Literal[schema.STATUSES]  # type: ignore[valid-type]


async def require_compliance_access(
    current_user: User = Depends(require_onboarded_user),
) -> User:
    """Admin i Head of Recruitment z roli, reszta z jednego z uprawnień."""

    if current_user.has_any_role(*COMPLIANCE_ROLES):
        return current_user
    ensure_any_permission(current_user, *COMPLIANCE_PERMISSIONS)
    return current_user


require_compliance_access.required_permissions = COMPLIANCE_PERMISSIONS  # type: ignore[attr-defined]


ComplianceUser = Depends(require_compliance_access)


def _ensure_enabled() -> None:
    if not runs.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, DISABLED_DETAIL)


# ── Odczyt ─────────────────────────────────────────────────────────────


def _change_row(change: LawChange) -> dict[str, Any]:
    return {
        "id": change.id,
        "title": change.title,
        "summary": list(change.summary or []),
        "roles": list(change.roles or []),
        "urgency": change.urgency,
        "stage": change.stage,
        "effective_on": change.effective_on,
        "deadline": change.deadline,
        "legal_ref": change.legal_ref,
        "status": change.status,
        "decision_note": change.decision_note,
        "decided_at": change.decided_at,
        "created_at": change.created_at,
        "updated_at": change.updated_at,
    }


def _probe_row(probe: LawChangeProbe) -> dict[str, Any]:
    return {
        "key": probe.probe_key,
        "value": probe.value,
        "text": probe.text,
        "link": probe.link,
        "computed_at": probe.computed_at,
    }


def _filters(role: Optional[str], change_status: Optional[str]) -> list[Any]:
    clauses: list[Any] = []
    if role:
        clauses.append(LawChange.roles.contains([role]))
    if change_status:
        clauses.append(LawChange.status == change_status)
    return clauses


@router.get("/changes")
async def list_changes(
    role: Optional[RoleFilter] = None,
    change_status: Optional[StatusValue] = Query(default=None, alias="status"),
    _user: User = ComplianceUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not runs.enabled():
        return {"enabled": False, "changes": []}
    changes = (
        (
            await db.execute(
                select(LawChange)
                .where(*_filters(role, change_status))
                .order_by(
                    URGENCY_ORDER,
                    LawChange.deadline.asc().nulls_last(),
                    LawChange.updated_at.desc(),
                )
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    ids = [change.id for change in changes]
    probes_by: dict[int, list[dict[str, Any]]] = {cid: [] for cid in ids}
    tasks_by: dict[int, dict[str, int]] = {cid: {"open": 0, "done": 0} for cid in ids}
    verified_by: dict[int, int] = {}
    if ids:
        verified_counts = await db.execute(
            select(LawRadarItem.change_id, func.count())
            .where(LawRadarItem.change_id.in_(ids), LawRadarItem.gate == "verified")
            .group_by(LawRadarItem.change_id)
        )
        verified_by = dict(verified_counts.all())
        for probe in (
            await db.execute(
                select(LawChangeProbe)
                .where(LawChangeProbe.change_id.in_(ids))
                .order_by(LawChangeProbe.probe_key)
            )
        ).scalars():
            probes_by[probe.change_id].append(_probe_row(probe))
        for change_id, done, count in (
            await db.execute(
                select(
                    LawChangeTask.change_id,
                    LawChangeTask.done_at.is_not(None),
                    func.count(),
                )
                .where(LawChangeTask.change_id.in_(ids))
                .group_by(LawChangeTask.change_id, LawChangeTask.done_at.is_not(None))
            )
        ).all():
            tasks_by[change_id]["done" if done else "open"] += int(count)
    return {
        "enabled": True,
        "changes": [
            {
                **_change_row(c),
                "probes": probes_by[c.id],
                "tasks": tasks_by[c.id],
                "verified_sources": verified_by.get(c.id, 0),
            }
            for c in changes
        ],
    }


async def _change(db: AsyncSession, change_id: int, *, lock: bool = False) -> LawChange:
    query = select(LawChange).where(LawChange.id == change_id)
    if lock:
        query = query.with_for_update()
    change = await db.scalar(query)
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CHANGE_NOT_FOUND)
    return change


async def _names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    wanted = sorted(i for i in ids if i is not None)
    if not wanted:
        return {}
    return dict(
        (await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))).all()
    )


def _task_row(task: LawChangeTask, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": task.id,
        "text": task.text,
        "role": task.role,
        "source": task.source,
        "assignee": (
            {"id": task.assignee_user_id, "name": names.get(task.assignee_user_id)}
            if task.assignee_user_id
            else None
        ),
        "due_on": task.due_on,
        "done": task.done_at is not None,
        "done_at": task.done_at,
    }


@router.get("/changes/{change_id}")
async def get_change(
    change_id: int,
    _user: User = ComplianceUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not runs.enabled():
        return {"enabled": False}
    change = await _change(db, change_id)
    items = (
        (
            await db.execute(
                select(LawRadarItem)
                .where(LawRadarItem.change_id == change_id)
                .order_by(LawRadarItem.published.desc(), LawRadarItem.id)
            )
        )
        .scalars()
        .all()
    )
    tasks = (
        (
            await db.execute(
                select(LawChangeTask)
                .where(LawChangeTask.change_id == change_id)
                .order_by(LawChangeTask.done_at.is_not(None), LawChangeTask.id)
            )
        )
        .scalars()
        .all()
    )
    events = (
        (
            await db.execute(
                select(LawChangeEvent)
                .where(LawChangeEvent.change_id == change_id)
                .order_by(LawChangeEvent.created_at.desc(), LawChangeEvent.id.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    found_probes = (
        (
            await db.execute(
                select(LawChangeProbe)
                .where(LawChangeProbe.change_id == change_id)
                .order_by(LawChangeProbe.probe_key)
            )
        )
        .scalars()
        .all()
    )
    names = await _names(
        db,
        {t.assignee_user_id for t in tasks}
        | {e.user_id for e in events}
        | {change.decided_by},
    )
    return {
        "enabled": True,
        "change": {
            **_change_row(change),
            "decided_by": names.get(change.decided_by) if change.decided_by else None,
        },
        "items": [
            {
                "id": item.id,
                "source": item.source,
                "klass": item.klass,
                "gate": item.gate,
                "title": item.title,
                "url": item.url,
                "published": item.published,
                "act_ref": item.act_ref,
                "print_no": item.print_no,
                "stage": item.stage,
                "quote": item.quote,
                "official": item.official or {},
            }
            for item in items
        ],
        "tasks": [_task_row(task, names) for task in tasks],
        "events": [
            {
                "id": event.id,
                "kind": event.kind,
                "from": event.from_value,
                "to": event.to_value,
                "note": event.note,
                "task_id": event.task_id,
                "by": names.get(event.user_id) if event.user_id else None,
                "bot": event.run_id is not None and event.user_id is None,
                "at": event.created_at,
            }
            for event in events
        ],
        "probes": [_probe_row(p) for p in found_probes],
    }


# ── Decyzje i zadania ──────────────────────────────────────────────────


class ChangeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StatusValue
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


@router.patch("/changes/{change_id}")
async def decide_change(
    change_id: int,
    body: ChangeDecision,
    user: User = ComplianceUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_enabled()
    note = (body.note or "").strip() or None
    if body.status == "not_applicable" and not note:
        raise HTTPException(422, NOTE_REQUIRED)
    change = await _change(db, change_id, lock=True)
    now = datetime.now(timezone.utc)
    previous = change.status
    if previous == body.status and note is None:
        return {"enabled": True, "change": _change_row(change)}
    change.status = body.status
    if note is not None:
        change.decision_note = note
    change.decided_by = user.id
    change.decided_at = now
    change.updated_at = now
    db.add(
        LawChangeEvent(
            change_id=change.id,
            kind="status",
            from_value=previous,
            to_value=body.status,
            note=note,
            user_id=user.id,
        )
    )
    await db.commit()
    await db.refresh(change)
    return {"enabled": True, "change": _change_row(change)}


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=schema.TASK_TEXT_MAX)
    role: Optional[RoleFilter] = None
    due_on: Optional[date] = None
    assignee_user_id: Optional[int] = None


async def _active_person(db: AsyncSession, user_id: Optional[int]) -> Optional[int]:
    if user_id is None:
        return None
    active = await db.scalar(
        select(User.id).where(User.id == user_id, User.is_active.is_(True))
    )
    if active is None:
        raise HTTPException(422, NO_PERSON)
    return user_id


@router.post("/changes/{change_id}/tasks", status_code=status.HTTP_201_CREATED)
async def add_task(
    change_id: int,
    body: TaskCreate,
    user: User = ComplianceUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_enabled()
    text = " ".join(body.text.split())
    if not text:
        raise HTTPException(422, "Wpisz treść zadania.")
    change = await _change(db, change_id)
    assignee = await _active_person(db, body.assignee_user_id)
    task = LawChangeTask(
        change_id=change.id,
        text=text,
        role=body.role,
        source="user",
        due_on=body.due_on,
        assignee_user_id=assignee,
        created_by=user.id,
    )
    db.add(task)
    await db.flush()
    db.add(
        LawChangeEvent(
            change_id=change.id, kind="task_added", task_id=task.id, user_id=user.id
        )
    )
    await db.commit()
    await db.refresh(task)
    return _task_row(task, await _names(db, {task.assignee_user_id}))


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: Optional[bool] = None
    assignee_user_id: Optional[int] = None
    due_on: Optional[date] = None


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    body: TaskUpdate,
    user: User = ComplianceUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_enabled()
    task = await db.scalar(
        select(LawChangeTask).where(LawChangeTask.id == task_id).with_for_update()
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, TASK_NOT_FOUND)
    now = datetime.now(timezone.utc)
    sent = body.model_fields_set
    kind: Optional[str] = None
    if (
        "done" in sent
        and body.done is not None
        and body.done != (task.done_at is not None)
    ):
        task.done_at = now if body.done else None
        task.done_by = user.id if body.done else None
        kind = "task_done" if body.done else "task_reopened"
    edited = False
    if "assignee_user_id" in sent and body.assignee_user_id != task.assignee_user_id:
        task.assignee_user_id = await _active_person(db, body.assignee_user_id)
        edited = True
    if "due_on" in sent and body.due_on != task.due_on:
        task.due_on = body.due_on
        edited = True
    if kind is None and not edited:
        return _task_row(task, await _names(db, {task.assignee_user_id}))
    task.updated_at = now
    db.add(
        LawChangeEvent(
            change_id=task.change_id,
            kind=kind or "task_updated",
            task_id=task.id,
            user_id=user.id,
        )
    )
    await db.commit()
    await db.refresh(task)
    return _task_row(task, await _names(db, {task.assignee_user_id}))


# ── Pasek modułu i biegi ───────────────────────────────────────────────


@router.get("/summary")
async def summary(
    role: Optional[RoleFilter] = None,
    _user: User = ComplianceUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not runs.enabled():
        return {"enabled": False, "to_decide": 0, "deadlines": 0, "top": []}
    today = business_today()
    role_clause = _filters(role, None)
    open_clause = LawChange.status.in_(schema.OPEN_STATUSES)
    to_decide = await db.scalar(
        select(func.count())
        .select_from(LawChange)
        .where(LawChange.status == "new", *role_clause)
    )
    deadlines = await db.scalar(
        select(func.count())
        .select_from(LawChange)
        .where(
            open_clause,
            LawChange.deadline >= today,
            LawChange.deadline <= today + timedelta(days=DEADLINE_WINDOW_DAYS),
            *role_clause,
        )
    )
    top = (
        await db.execute(
            select(LawChange.id, LawChange.title, LawChange.urgency, LawChange.deadline)
            .where(open_clause, *role_clause)
            .order_by(
                URGENCY_ORDER,
                LawChange.deadline.asc().nulls_last(),
                LawChange.id.desc(),
            )
            .limit(TOP_TITLES)
        )
    ).all()
    return {
        "enabled": True,
        "to_decide": int(to_decide or 0),
        "deadlines": int(deadlines or 0),
        "deadline_window_days": DEADLINE_WINDOW_DAYS,
        "top": [
            {"id": cid, "title": title, "urgency": urgency, "deadline": deadline}
            for cid, title, urgency, deadline in top
        ],
    }


def _run_row(
    run: LawRadarRun, source_counts: Optional[dict[str, int]] = None
) -> dict[str, Any]:
    summary = numbers_only(run.report or {})
    if source_counts is not None:
        summary["saved_sources"] = source_counts
        for source in collect.SUBSCRIPTION_SOURCES:
            key = f"{source}_skip_reason"
            reason = (run.report or {}).get(key)
            if reason in collect.SKIP_REASONS:
                summary[key] = reason
    return {
        "id": run.id,
        "kind": run.kind,
        "status": run.status,
        "started_at": run.started_at,
        "received_at": run.received_at,
        "error": run.error,
        "summary": summary,
    }


@router.get("/runs")
async def list_runs(
    _user: User = ComplianceUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    configured = {kind: runs.configured(kind) for kind in schema.RUN_KINDS}
    if not runs.enabled():
        return {"enabled": False, "configured": configured, "runs": []}
    rows = (
        (
            await db.execute(
                select(LawRadarRun).order_by(LawRadarRun.id.desc()).limit(RUNS_LISTED)
            )
        )
        .scalars()
        .all()
    )
    counts_by_run = {
        run.id: dict.fromkeys(collect.SUBSCRIPTION_SOURCES, 0)
        for run in rows
        if run.kind == collect.KIND and run.status == "received"
    }
    if counts_by_run:
        counts = await db.execute(
            select(LawRadarItem.run_id, LawRadarItem.source, func.count())
            .where(
                LawRadarItem.run_id.in_(list(counts_by_run)),
                LawRadarItem.source.in_(collect.SUBSCRIPTION_SOURCES),
            )
            .group_by(LawRadarItem.run_id, LawRadarItem.source)
        )
        for run_id, source, count in counts:
            counts_by_run[run_id][source] = count
    return {
        "enabled": True,
        "configured": configured,
        "runs": [_run_row(run, counts_by_run.get(run.id)) for run in rows],
    }


@router.post("/runs/collect", status_code=status.HTTP_201_CREATED)
async def start_collect(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ręczny start Zbieracza (także przy wyłączonej fladze: próba rutyny)."""

    if not runs.configured(collect.KIND):
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_CONFIGURED)
    running = await flow.open_run(db, collect.KIND)
    if running is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, COLLECT_RUNNING.format(run_id=running.id)
        )
    run = await flow.start_collect(
        db, now=datetime.now(timezone.utc), requested_by_user_id=admin.id
    )
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_CONFIGURED)
    return _run_row(run)
