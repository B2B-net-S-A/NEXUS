"""Przekierowania poczty w karcie Microsoft 365 (Compass ``AdminForwardRules``, faza 41c).

Reguła skrzynki odbiorczej nie wygasa sama, a w Compassie dwie reguły
przeżyły swoje urlopy o kilka dni, zanim zastępcy zgłosili cudzą pocztę.
Karta pokazuje więc Kadrom dwa widoki:

* ``saved_forwards`` — co NEXUS wie z bazy (bez Graph, tanio): wnioski ze
  zgodą na przekierowanie, które trwają albo nadejdą, i wnioski, których
  reguła mogła zostać w skrzynce (ostatnia operacja to wykonane otwarcie,
  a urlop już nie trwa albo zgodę wyłączono),
* ``check_mailboxes`` — „Sprawdź skrzynki”: odczyt reguł na żywo ze skrzynek
  w zakresie (lista próbna), bez zapisu. Pokazuje też reguły NEXUSA albo
  Compassa, o których baza nie wie (sierota bez wniosku), i urlopy, które
  powinny przekierowywać, a reguły nie mają. Przy trybie innym niż ``live``
  odczytu nie ma — wynik mówi to zdaniem, zamiast udawać „czysto”.

``close_rule`` zamyka regułę przez kolejkę (``forward_rule_close``) — także
regułę bez wniosku. Reguły trwającego urlopu ze zgodą tak nie zamkniemy
(wykonawca uznałby ją za potrzebną): od tego jest wyłączenie przekierowania
we wniosku z powodem (``leave_edit.forward_off_by_hr``).

Odpowiedzi nie niosą rodzaju nieobecności (D6) ani adresów skrzynek.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import HrM365Operation, LeaveRequest
from app.models.user import User
from app.services.hr.m365 import forward_rules
from app.services.hr.m365.executor import (
    allowlist,
    current_mode,
    enqueue_at,
    forward_should_be_active,
    mailbox_address,
    mailbox_allowed,
)
from app.services.hr.m365.ops import GraphMailboxOps, MailboxError, MailboxOps
from app.services.hr.m365.reconcile import executed_statuses, mailbox_users

Health = Literal["ok", "waiting", "missing", "orphan", "unknown"]

MODE_OFF = (
    "Microsoft 365 jest wyłączony (tryb „Wyłączone”) — NEXUS nie czyta skrzynek. "
    "Lista pokazuje to, co zapisano w NEXUSIE."
)
MODE_SIMULATE = (
    "W trybie symulacji NEXUS nie czyta prawdziwych skrzynek — sprawdzenie "
    "działa w trybie „Na żywo”."
)
NO_CREDENTIALS = "Aplikacja NEXUSA w Microsoft 365 nie ma poświadczeń — skrzynek nie da się odczytać."
STILL_NEEDED = (
    "Ta reguła należy do trwającej nieobecności ze zgodą osoby — wyłącz "
    "przekierowanie we wniosku (z powodem), wtedy kolejka zamknie regułę."
)
NOT_MANAGED = "To nie jest reguła zastępstwa NEXUSA ani Compassa."


class ForwardAdminError(RuntimeError):
    """Odmowa po polsku (409)."""


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    return value.isoformat() if value else None


async def _names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids = {uid for uid in ids if uid}
    if not ids:
        return {}
    return dict(
        (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    )


def _health(leave: LeaveRequest, today: date) -> Health:
    if forward_should_be_active(leave, today):
        return "ok"
    if (
        leave.status == "approved"
        and leave.forward_mail_consent
        and leave.substitute_user_id is not None
        and leave.start_date > today
    ):
        return "waiting"
    return "orphan"


def _reason(leave: Optional[LeaveRequest], today: date) -> Optional[str]:
    if leave is None:
        return "Reguła nie pasuje do żadnego wniosku w NEXUSIE."
    if not leave.forward_mail_consent:
        return "Przekierowanie wyłączono, a reguła mogła zostać w skrzynce."
    if leave.status != "approved":
        return "Wniosek nie jest zatwierdzony — reguła nie powinna działać."
    if leave.end_date < today:
        return f"Nieobecność skończyła się {leave.end_date.strftime('%d.%m.%Y')}."
    if leave.start_date > today:
        return (
            f"Nieobecność zaczyna się dopiero {leave.start_date.strftime('%d.%m.%Y')}."
        )
    return None


async def _latest_forward_ops(
    db: AsyncSession, leave_ids: list[uuid.UUID]
) -> dict[uuid.UUID, HrM365Operation]:
    if not leave_ids:
        return {}
    rows = await db.scalars(
        select(HrM365Operation)
        .where(
            HrM365Operation.leave_request_id.in_(leave_ids),
            HrM365Operation.kind.in_(("forward_rule_open", "forward_rule_close")),
        )
        .order_by(HrM365Operation.id)
    )
    latest: dict[uuid.UUID, HrM365Operation] = {}
    for op in rows.all():
        latest[op.leave_request_id] = op  # type: ignore[index]
    return latest


def _row(
    leave: LeaveRequest,
    names: dict[int, str],
    *,
    today: date,
    last_op: Optional[HrM365Operation],
) -> dict[str, Any]:
    health = _health(leave, today)
    return {
        "leave_request_id": str(leave.id),
        "user_id": leave.user_id,
        "user_name": names.get(leave.user_id),
        "substitute_user_id": leave.substitute_user_id,
        "substitute_name": names.get(leave.substitute_user_id)
        if leave.substitute_user_id
        else None,
        "start_date": _iso(leave.start_date),
        "end_date": _iso(leave.end_date),
        "status": leave.status,
        "consent": leave.forward_mail_consent,
        "health": health,
        "reason": None if health in ("ok", "waiting") else _reason(leave, today),
        "last_operation": None
        if last_op is None
        else {
            "id": last_op.id,
            "kind": last_op.kind,
            "status": last_op.status,
            "last_error": last_op.last_error,
        },
    }


async def saved_forwards(db: AsyncSession, *, today: date) -> dict[str, Any]:
    """Przekierowania zapisane w NEXUSIE — bez odczytu skrzynek."""

    mode = current_mode()
    executed = executed_statuses(mode)
    live = await db.scalars(
        select(LeaveRequest)
        .where(
            LeaveRequest.status == "approved",
            LeaveRequest.forward_mail_consent.is_(True),
            LeaveRequest.substitute_user_id.is_not(None),
            LeaveRequest.end_date >= today,
        )
        .order_by(LeaveRequest.start_date, LeaveRequest.id)
        .limit(500)
    )
    leaves = {leave.id: leave for leave in live.all()}
    # Reguła mogła zostać: ostatnia operacja przekierowania to wykonane otwarcie.
    ranked = (
        select(
            HrM365Operation.leave_request_id.label("leave_id"),
            HrM365Operation.kind,
            HrM365Operation.status,
            func.row_number()
            .over(
                partition_by=HrM365Operation.leave_request_id,
                order_by=HrM365Operation.id.desc(),
            )
            .label("rank"),
        )
        .where(
            HrM365Operation.leave_request_id.is_not(None),
            HrM365Operation.kind.in_(("forward_rule_open", "forward_rule_close")),
        )
        .subquery()
    )
    stale_ids = list(
        (
            await db.scalars(
                select(ranked.c.leave_id).where(
                    ranked.c.rank == 1,
                    ranked.c.kind == "forward_rule_open",
                    ranked.c.status.in_(executed),
                )
            )
        ).all()
    )
    missing = [leave_id for leave_id in stale_ids if leave_id not in leaves]
    if missing:
        for leave in (
            await db.scalars(select(LeaveRequest).where(LeaveRequest.id.in_(missing)))
        ).all():
            if not forward_should_be_active(leave, today):
                leaves[leave.id] = leave
    ordered = sorted(
        leaves.values(), key=lambda leave: (leave.start_date, str(leave.id))
    )
    names = await _names(
        db,
        {leave.user_id for leave in ordered}
        | {leave.substitute_user_id for leave in ordered if leave.substitute_user_id},
    )
    latest = await _latest_forward_ops(db, [leave.id for leave in ordered])
    rows = [
        _row(leave, names, today=today, last_op=latest.get(leave.id))
        for leave in ordered
    ]
    order = {"orphan": 0, "missing": 1, "ok": 2, "waiting": 3, "unknown": 4}
    rows.sort(key=lambda row: order[row["health"]])
    return {"mode": mode, "today": today.isoformat(), "items": rows}


def _unavailable(mode: str, ops: Optional[MailboxOps]) -> Optional[str]:
    if mode == "off":
        return MODE_OFF
    if mode == "simulate" and ops is None:
        return MODE_SIMULATE
    if ops is None:
        from app.services.hr.m365.auth import credentials_configured

        if not credentials_configured():
            return NO_CREDENTIALS
    return None


async def check_mailboxes(
    db: AsyncSession,
    *,
    today: date,
    ops: Optional[MailboxOps] = None,
    mode: Optional[str] = None,
    user_ids: Optional[list[int]] = None,
) -> dict[str, Any]:
    """„Sprawdź skrzynki” — reguły zastępstw na żywo, bez zapisu w skrzynkach."""

    mode = mode or current_mode()
    blocked = _unavailable(mode, ops)
    if blocked is not None:
        return {"available": False, "mode": mode, "message": blocked, "items": []}
    allowed = allowlist()
    rows = await db.scalars(
        select(LeaveRequest).where(
            or_(
                LeaveRequest.forward_mail_consent.is_(True),
                LeaveRequest.id.in_(
                    select(HrM365Operation.leave_request_id).where(
                        HrM365Operation.kind == "forward_rule_open"
                    )
                ),
            )
        )
    )
    leaves = {str(leave.id): leave for leave in rows.all()}
    own_ops = ops is None
    active_ops: MailboxOps = ops or GraphMailboxOps()
    items: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    scanned = 0
    read_users: set[int] = set()
    try:
        for user in await mailbox_users(db, set(), user_ids):
            upn = mailbox_address(user)
            if upn is None or not mailbox_allowed(upn, allowed):
                continue
            try:
                found = await active_ops.list_rules(upn)
            except MailboxError as exc:
                unreadable.append(
                    {"user_id": user.id, "name": user.name, "error": exc.label}
                )
                continue
            scanned += 1
            read_users.add(user.id)
            for rule in found:
                leave_id = forward_rules.parse_leave_id(rule.get("displayName"))
                if not leave_id or not rule.get("id"):
                    continue
                leave = leaves.get(leave_id)
                if leave is not None and leave.user_id != user.id:
                    leave = (
                        None  # nazwa wskazuje cudzy wniosek — dla tej skrzynki sierota
                    )
                health: Health = (
                    "unknown"
                    if leave is None
                    else "ok"
                    if forward_should_be_active(leave, today)
                    else "orphan"
                )
                items.append(
                    {
                        "rule_id": str(rule["id"]),
                        "rule_name": rule.get("displayName"),
                        "owner": "compass"
                        if forward_rules.is_compass_rule(rule.get("displayName"))
                        else "nexus",
                        "leave_request_id": leave_id,
                        "known": leave is not None,
                        "user_id": user.id,
                        "user_name": user.name,
                        "start_date": _iso(leave.start_date) if leave else None,
                        "end_date": _iso(leave.end_date) if leave else None,
                        "substitute_user_id": leave.substitute_user_id
                        if leave
                        else None,
                        "health": health,
                        "reason": None if health == "ok" else _reason(leave, today),
                    }
                )
    finally:
        if own_ops:
            await active_ops.aclose()
    seen = {item["leave_request_id"] for item in items}
    names = await _names(
        db,
        {item["substitute_user_id"] for item in items if item["substitute_user_id"]}
        | {leave.user_id for leave in leaves.values()}
        | {
            leave.substitute_user_id
            for leave in leaves.values()
            if leave.substitute_user_id
        },
    )
    for item in items:
        item["substitute_name"] = names.get(item.pop("substitute_user_id") or 0)
    for leave_id, leave in leaves.items():
        if leave_id in seen or leave.user_id not in read_users:
            continue
        if not forward_should_be_active(leave, today):
            continue
        items.append(
            {
                "rule_id": None,
                "rule_name": None,
                "owner": None,
                "leave_request_id": leave_id,
                "known": True,
                "user_id": leave.user_id,
                "user_name": names.get(leave.user_id),
                "start_date": _iso(leave.start_date),
                "end_date": _iso(leave.end_date),
                "substitute_name": names.get(leave.substitute_user_id or 0),
                "health": "missing",
                "reason": "Nieobecność trwa i ma zgodę, ale w skrzynce nie ma reguły — "
                "poczta nie trafia do zastępcy.",
            }
        )
    order = {"orphan": 0, "unknown": 0, "missing": 1, "ok": 2, "waiting": 3}
    items.sort(key=lambda item: (order[item["health"]], item["user_name"] or ""))
    return {
        "available": True,
        "mode": mode,
        "message": None,
        "scanned": scanned,
        "unreadable": unreadable,
        "items": items,
    }


async def close_rule(
    db: AsyncSession,
    *,
    user_id: int,
    leave_request_id: str,
    today: date,
    actor_id: int,
    now: datetime,
) -> dict[str, Any]:
    """Operacja ``forward_rule_close`` dla reguły z nazwą ``… zastępstwo · {id}``."""

    try:
        leave_uuid = uuid.UUID(leave_request_id)
    except ValueError as exc:
        raise ForwardAdminError(NOT_MANAGED) from exc
    user = await db.get(User, user_id)
    if user is None:
        raise ForwardAdminError("Nie ma takiej osoby.")
    leave = await db.get(LeaveRequest, leave_uuid)
    if leave is not None and leave.user_id != user_id:
        leave = None
    if leave is not None and forward_should_be_active(leave, today):
        raise ForwardAdminError(STILL_NEEDED)
    key = str(leave_uuid)
    dedupe = f"admin:{user_id}:{key}:forward_rule_close:{now.isoformat()}"
    await enqueue_at(
        db,
        user_id=user_id,
        kind="forward_rule_close",
        dedupe_key=dedupe,
        payload={
            "leave_id": key,
            "rule_name": forward_rules.rule_name(key),
            "reason": "admin",
            "requested_by": actor_id,
        },
        leave_request_id=leave.id if leave is not None else None,
    )
    return {"queued": True, "leave_request_id": key, "known": leave is not None}


__all__ = [
    "ForwardAdminError",
    "check_mailboxes",
    "close_rule",
    "saved_forwards",
]
