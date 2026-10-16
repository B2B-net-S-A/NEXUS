"""Microsoft 365 dla urlopów — karta w Ustawieniach → Kadry („Ludzie w NEXUSIE”).

Tryb (``HR_M365_MODE``), kolejka operacji (oczekujące, nieudane,
zasymulowane z podglądem dokładnego żądania), „Ponów” i skrzynki, w których
zachowaliśmy własną autoodpowiedź osoby. Za uprawnieniem „Kadry”
(``people_admin``; admin ma wszystkie). Przełącznik modułu nie zamyka karty —
Kadry przygotowują przełączenie, zanim moduł urlopów zostanie włączony.

Odpowiedzi nie niosą rodzaju nieobecności (D6) — operacje go nie znają.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.hr_leave import HrM365MailboxState, HrM365Operation
from app.models.hr_ops import HrJobRun
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.hr import audit
from app.services.hr.m365 import executor
from app.services.hr.m365.auth import credentials_configured
from app.services.hr.m365.reconcile import JOB_KIND as RECONCILE_KIND

router = APIRouter()

OperationStatus = Literal[
    "pending", "running", "failed", "simulated", "skipped", "done"
]
OPERATION_STATUSES: tuple[str, ...] = get_args(OperationStatus)
RETRYABLE_STATUSES = ("failed", "pending")
NOT_RETRYABLE_DETAIL = "Tę operację można ponowić tylko, gdy czeka albo się nie udała."
NOT_FOUND_DETAIL = "Nie ma takiej operacji."


def require_hr_m365_admin():
    """Kadry (``people_admin``) albo admin."""

    async def _check(
        current_user: User = Depends(require_permission(ProductAction.people_admin)),
    ) -> User:
        return current_user

    return _check


HrM365Admin = Annotated[User, Depends(require_hr_m365_admin())]


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _operation_out(op: HrM365Operation, user_name: Optional[str]) -> dict[str, Any]:
    payload = op.payload or {}
    return {
        "id": op.id,
        "kind": op.kind,
        "status": op.status,
        "user_id": op.user_id,
        "user_name": user_name,
        "leave_request_id": str(op.leave_request_id) if op.leave_request_id else None,
        "window_start": payload.get("start"),
        "window_end": payload.get("end"),
        "attempts": op.attempts,
        "next_attempt_at": _iso(op.next_attempt_at),
        "last_error": op.last_error,
        "deferred": op.status == "pending"
        and op.last_error in executor.DEFERRAL_REASONS,
        "created_at": _iso(op.created_at),
        "done_at": _iso(op.done_at),
        "simulated_request": op.simulated_request,
    }


@router.get("/status")
async def m365_status(
    _: HrM365Admin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    counts = dict(
        (
            await db.execute(
                select(HrM365Operation.status, func.count(HrM365Operation.id)).group_by(
                    HrM365Operation.status
                )
            )
        ).all()
    )
    deferred = await db.scalar(
        select(func.count(HrM365Operation.id)).where(
            HrM365Operation.status == "pending",
            HrM365Operation.last_error.in_(executor.DEFERRAL_REASONS),
        )
    )
    last_run = await db.scalar(
        select(HrJobRun)
        .where(HrJobRun.kind == RECONCILE_KIND)
        .order_by(HrJobRun.claimed_at.desc())
        .limit(1)
    )
    custom_rows = (
        await db.execute(
            select(
                HrM365MailboxState.user_id,
                User.name,
                HrM365MailboxState.last_reconciled_at,
            )
            .join(User, User.id == HrM365MailboxState.user_id)
            .where(HrM365MailboxState.custom_oof_detected.is_(True))
            .order_by(User.name)
        )
    ).all()
    error_rows = (
        await db.execute(
            select(HrM365MailboxState.user_id, User.name, HrM365MailboxState.last_error)
            .join(User, User.id == HrM365MailboxState.user_id)
            .where(HrM365MailboxState.last_error.is_not(None))
            .order_by(User.name)
        )
    ).all()
    return {
        "mode": executor.current_mode(),
        "credentials_configured": credentials_configured(),
        "allowlist": sorted(executor.allowlist()),
        "counts": {key: int(counts.get(key, 0)) for key in OPERATION_STATUSES},
        "deferred": int(deferred or 0),
        "last_reconcile": (
            {
                "day": last_run.period_key,
                "status": last_run.status,
                "finished_at": _iso(last_run.finished_at),
                "counts": last_run.counts or {},
            }
            if last_run
            else None
        ),
        "custom_oof_mailboxes": [
            {"user_id": uid, "name": name, "last_reconciled_at": _iso(at)}
            for uid, name, at in custom_rows
        ],
        "mailbox_errors": [
            {"user_id": uid, "name": name, "last_error": error}
            for uid, name, error in error_rows
        ],
    }


@router.get("/operations")
async def list_operations(
    _: HrM365Admin,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[OperationStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    query = select(HrM365Operation, User.name).join(
        User, User.id == HrM365Operation.user_id
    )
    count_query = select(func.count(HrM365Operation.id))
    if status_filter is not None:
        # „Oczekujące” obejmują też operacje w trakcie wykonania.
        statuses = (
            ("pending", "running") if status_filter == "pending" else (status_filter,)
        )
        query = query.where(HrM365Operation.status.in_(statuses))
        count_query = count_query.where(HrM365Operation.status.in_(statuses))
    order = (
        HrM365Operation.next_attempt_at.asc()
        if status_filter == "pending"
        else HrM365Operation.id.desc()
    )
    rows = (
        await db.execute(query.order_by(order, HrM365Operation.id).limit(limit))
    ).all()
    return {
        "items": [_operation_out(op, name) for op, name in rows],
        "total": int(await db.scalar(count_query) or 0),
    }


@router.post("/operations/{operation_id}/retry")
async def retry_operation(
    operation_id: int,
    current_user: HrM365Admin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    op = await db.scalar(
        select(HrM365Operation)
        .where(HrM365Operation.id == operation_id)
        .with_for_update()
    )
    if op is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    if op.status not in RETRYABLE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_RETRYABLE_DETAIL)
    previous = op.status
    await executor.retry(db, op)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=op.user_id,
        entity_type="hr_m365_operation",
        entity_id=op.id,
        action="m365_operation_retried",
        details={"kind": op.kind, "previous_status": previous},
    )
    await db.commit()
    user_name = await db.scalar(select(User.name).where(User.id == op.user_id))
    return _operation_out(op, user_name)
