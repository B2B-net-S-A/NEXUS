"""Uzgadnianie skrzynek z urlopami — raz dziennie po 7:00 (Warszawa).

Siatka pod wykonawcą kolejki: sam niczego nie zapisuje w skrzynkach, tylko
czyta je i dokłada operacje do ``hr_m365_operations`` (te przechodzą przez
tryby, listę skrzynek i ponowienia wykonawcy). Dla każdej skrzynki zespołu:

1. **autoodpowiedź** — zatwierdzony urlop (co najmniej pełny dzień), który
   trwa albo zaczyna się jutro, a w skrzynce nie ma jego autoodpowiedzi →
   ``set_oof`` z nowym kluczem (dzień uzgadniania). Nie dokładamy, gdy:
   czeka operacja tego urlopu, osoba ma własną autoodpowiedź, albo nasza już
   raz weszła, a osoba ją wyłączyła (np. wróciła wcześniej). „Osoba
   wyłączyła” tylko wtedy, gdy ``set_oof`` tego urlopu był naszym ostatnim
   zapisem autoodpowiedzi w tej skrzynce — jeśli po nim weszła autoodpowiedź
   innego urlopu albo nasze zdjęcie (anulowanie wcześniejszego urlopu), stan
   skrzynki wynika z naszej operacji i autoodpowiedź wraca;
2. **przekierowania** — reguła NEXUSA albo Compassa bez urlopu, który właśnie
   trwa (urlop się skończył, został anulowany, zgoda cofnięta, albo urlopu
   w ogóle nie ma — sierota) → ``forward_rule_close``; urlop ze zgodą, który
   trwa i nie ma reguły → ``forward_rule_open``; reguła Compassa trwającego
   urlopu → przejęcie (``forward_rule_open`` przepisuje ją na NEXUSA);
3. **wydarzenia po symulacji** (tylko ``live``) — zatwierdzony urlop, który
   się nie skończył, a jego ostatnia operacja kalendarza to symulowane
   ``calendar_event_upsert`` → ``calendar_event_upsert`` na nowo.

Po przejściu ``simulate`` → ``live`` operacje ``simulated`` są dla
uzgadniania niewykonane (do ponowienia): w skrzynce nic się nie zmieniło.
W trybie ``simulate`` liczą się jak ``done`` — inaczej symulacja dokładałaby
operacje codziennie.

Rezerwacja w ``hr_job_runs`` (``kind = hr_m365_reconcile``, klucz = dzień):
drugi przebieg tego samego dnia nic nie robi. Odczyt skrzynki nieudany =
„nie wiadomo”, a nie „pusto” — wtedy niczego nie wnioskujemy.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Collection
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import HrM365Operation, LeaveRequest
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import job_runs
from app.services.hr.m365 import forward_rules, oof_state
from app.services.hr.m365.executor import (
    allowlist,
    current_mode,
    enqueue_at,
    forward_should_be_active,
    leave_day_totals,
    mailbox_address,
    save_mailbox_state,
    set_oof_payload,
    utc_now,
    warsaw_hour,
    warsaw_today,
)
from app.services.hr.m365.ops import GraphMailboxOps, MailboxError, MailboxOps
from app.services.hr.m365.simulated import SimulatedMailboxOps
from app.services.hr_foundation_schema import EmploymentStatus

logger = logging.getLogger(__name__)

JOB_KIND = "hr_m365_reconcile"
RECONCILE_HOUR = 7
#: Górna granica skrzynek na przebieg (zespół to dziś kilkadziesiąt osób).
MAX_MAILBOXES = 300

_LIVE_STATUSES = ("pending", "running")


def executed_statuses(mode: str) -> tuple[str, ...]:
    """Statusy „operacja weszła do skrzynki” w danym trybie.

    W ``live`` symulowana operacja niczego w skrzynce nie zmieniła — jest do
    ponowienia (przegląd 16.10.2026, D19).
    """

    return ("done",) if mode == "live" else ("done", "simulated")


async def _candidate_leaves(db: AsyncSession, today: date) -> list[LeaveRequest]:
    """Zatwierdzone urlopy, które trwają albo zaczynają się jutro."""

    rows = await db.scalars(
        select(LeaveRequest)
        .where(
            LeaveRequest.status == "approved",
            LeaveRequest.end_date >= today,
            LeaveRequest.start_date <= today + timedelta(days=1),
        )
        .order_by(LeaveRequest.start_date, LeaveRequest.id)
    )
    return list(rows.all())


async def _latest_ops(
    db: AsyncSession, leave_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, HrM365Operation], dict[uuid.UUID, HrM365Operation]]:
    """Ostatnia operacja autoodpowiedzi i ostatnia operacja przekierowania urlopu."""

    if not leave_ids:
        return {}, {}
    rows = await db.scalars(
        select(HrM365Operation)
        .where(
            HrM365Operation.leave_request_id.in_(leave_ids),
            HrM365Operation.kind.in_(
                ("set_oof", "forward_rule_open", "forward_rule_close")
            ),
        )
        .order_by(HrM365Operation.id)
    )
    oof: dict[uuid.UUID, HrM365Operation] = {}
    forward: dict[uuid.UUID, HrM365Operation] = {}
    for op in rows.all():
        target = oof if op.kind == "set_oof" else forward
        target[op.leave_request_id] = op  # type: ignore[index]
    return oof, forward


async def _last_oof_writes(
    db: AsyncSession, user_ids: Collection[int], executed: tuple[str, ...]
) -> dict[int, int]:
    """Id ostatniej naszej operacji, która zapisała autoodpowiedź, per osoba.

    ``set_oof`` wykonane zawsze pisze; ``clear_oof`` wykonane — tylko gdy
    zdjęło naszą autoodpowiedź (zastaną wyłączoną kończy jako ``skipped``).
    Kolejność według wykonania (``done_at``), nie kolejki: odroczona operacja
    wcześniejszego wiersza mogła wejść później.
    """

    if not user_ids:
        return {}
    rows = await db.execute(
        select(HrM365Operation.user_id, HrM365Operation.id)
        .where(
            HrM365Operation.user_id.in_(list(user_ids)),
            HrM365Operation.kind.in_(("set_oof", "clear_oof")),
            HrM365Operation.status.in_(executed),
        )
        .distinct(HrM365Operation.user_id)
        .order_by(
            HrM365Operation.user_id,
            HrM365Operation.done_at.desc().nulls_last(),
            HrM365Operation.id.desc(),
        )
    )
    return {user_id: op_id for user_id, op_id in rows.all()}


async def _simulated_calendar(
    db: AsyncSession, today: date
) -> dict[int, list[HrM365Operation]]:
    """Urlopy, których wydarzenie powstało tylko w symulacji (ostatnia operacja
    kalendarza to symulowane ``calendar_event_upsert``), per osoba."""

    ranked = (
        select(
            HrM365Operation.id,
            func.row_number()
            .over(
                partition_by=HrM365Operation.leave_request_id,
                order_by=HrM365Operation.id.desc(),
            )
            .label("rank"),
        )
        .join(LeaveRequest, LeaveRequest.id == HrM365Operation.leave_request_id)
        .where(
            HrM365Operation.kind.in_(
                ("calendar_event_upsert", "calendar_event_delete")
            ),
            LeaveRequest.status == "approved",
            LeaveRequest.end_date >= today,
        )
        .subquery()
    )
    rows = await db.scalars(
        select(HrM365Operation)
        .join(ranked, ranked.c.id == HrM365Operation.id)
        .where(
            ranked.c.rank == 1,
            HrM365Operation.kind == "calendar_event_upsert",
            HrM365Operation.status == "simulated",
        )
        .order_by(HrM365Operation.id)
    )
    out: dict[int, list[HrM365Operation]] = defaultdict(list)
    for op in rows.all():
        out[op.user_id].append(op)
    return out


async def _mailbox_users(
    db: AsyncSession, owner_ids: set[int], only: Optional[Collection[int]]
) -> list[User]:
    """Skrzynki zespołu (kartoteka nie ``exited``) i właściciele urlopów."""

    staff = select(EmployeeProfile.user_id).where(
        EmployeeProfile.employment_status != EmploymentStatus.exited
    )
    condition = User.is_active.is_(True) & User.id.in_(staff)
    if owner_ids:
        condition = condition | User.id.in_(owner_ids)
    query = select(User).where(condition)
    if only is not None:
        query = query.where(User.id.in_(list(only)))
    rows = await db.scalars(query.order_by(User.id).limit(MAX_MAILBOXES))
    return list(rows.all())


def _needs_oof(
    current: dict[str, Any],
    leave: LeaveRequest,
    latest: Optional[HrM365Operation],
    now: datetime,
    *,
    executed: tuple[str, ...],
    last_write_id: Optional[int],
) -> bool:
    if oof_state.matches_leave(current, leave.start_date, leave.end_date):
        return False
    if latest is not None and latest.status in _LIVE_STATUSES:
        return False
    if oof_state.user_custom_active(current, now):
        return False
    if (
        latest is not None
        and latest.status in executed
        and oof_state.is_disabled(current)
        and (last_write_id is None or last_write_id == latest.id)
    ):
        # Nasza autoodpowiedź weszła jako ostatni nasz zapis, a osoba ją
        # wyłączyła — nie włączamy na nowo. Późniejszy nasz zapis (inny urlop
        # albo zdjęcie przy anulowaniu) znaczy, że wyłączyliśmy ją my.
        return False
    return True


def _forward_open_pending(
    latest: Optional[HrM365Operation], executed: tuple[str, ...]
) -> bool:
    """Ostatnia operacja przekierowania to otwarcie, które czeka albo weszło."""

    return (
        latest is not None
        and latest.kind == "forward_rule_open"
        and latest.status in (*_LIVE_STATUSES, *executed)
    )


async def _reconcile(
    db: AsyncSession,
    ops: MailboxOps,
    mode: str,
    now: datetime,
    today: date,
    only: Optional[Collection[int]] = None,
) -> dict[str, Any]:
    counts: dict[str, Any] = defaultdict(int)
    executed = executed_statuses(mode)
    leaves = await _candidate_leaves(db, today)
    leave_ids = [leave.id for leave in leaves]
    totals = await leave_day_totals(db, leave_ids)
    latest_oof, latest_forward = await _latest_ops(db, leave_ids)
    by_user: dict[int, list[LeaveRequest]] = defaultdict(list)
    for leave in leaves:
        by_user[leave.user_id].append(leave)
    last_writes = await _last_oof_writes(db, set(by_user), executed)
    calendar_redo = await _simulated_calendar(db, today) if mode == "live" else {}

    allowed = allowlist() if mode == "live" else frozenset()
    day_key = today.isoformat()
    for user in await _mailbox_users(db, set(by_user) | set(calendar_redo), only):
        upn = mailbox_address(user)
        if upn is None:
            continue
        if allowed and upn.lower() not in allowed:
            counts["not_allowlisted"] += 1
            continue
        counts["mailboxes"] += 1
        user_leaves = by_user.get(user.id, [])
        error: Optional[str] = None
        custom_flag: Optional[bool] = None

        # 1. Autoodpowiedź.
        try:
            current = await ops.get_auto_replies(upn)
        except MailboxError as exc:
            current = None
            error = exc.label
            counts["read_errors"] += 1
        if current is not None:
            if not oof_state.user_custom_active(current, now):
                custom_flag = False
            for leave in user_leaves:
                total = totals.get(leave.id, Decimal("0"))
                if total < Decimal("1"):
                    continue  # pół dnia nie dostaje autoodpowiedzi
                if not _needs_oof(
                    current,
                    leave,
                    latest_oof.get(leave.id),
                    now,
                    executed=executed,
                    last_write_id=last_writes.get(user.id),
                ):
                    continue
                payload = await set_oof_payload(db, leave, total)
                if payload is None:
                    continue
                if await enqueue_at(
                    db,
                    user_id=user.id,
                    kind="set_oof",
                    dedupe_key=f"leave:{leave.id}:set_oof:reconcile:{day_key}",
                    payload=payload,
                    leave_request_id=leave.id,
                ):
                    counts["oof_enqueued"] += 1

        # 2. Przekierowania.
        try:
            rules = await ops.list_rules(upn)
        except MailboxError as exc:
            rules = None
            error = error or exc.label
            counts["read_errors"] += 1
        if rules is not None:
            active = {
                str(leave.id): leave
                for leave in user_leaves
                if forward_should_be_active(leave, today)
            }
            managed: list[tuple[dict[str, Any], str]] = []
            for rule in rules:
                leave_id = forward_rules.parse_leave_id(rule.get("displayName"))
                if leave_id and rule.get("id"):
                    managed.append((rule, leave_id))
            stray_ids = {leave_id for _, leave_id in managed if leave_id not in active}
            existing = await _existing_leaves(db, stray_ids, user.id)
            seen: set[str] = set()
            for rule, leave_id in managed:
                seen.add(leave_id)
                leave = active.get(leave_id)
                if leave is not None:
                    if forward_rules.is_compass_rule(rule.get("displayName")):
                        if await enqueue_at(
                            db,
                            user_id=user.id,
                            kind="forward_rule_open",
                            dedupe_key=f"leave:{leave_id}:forward_rule_open:takeover",
                            payload=_forward_payload(leave, "takeover"),
                            leave_request_id=leave.id,
                        ):
                            counts["forward_takeover"] += 1
                    continue
                if await enqueue_at(
                    db,
                    user_id=user.id,
                    kind="forward_rule_close",
                    dedupe_key=f"reconcile:{day_key}:forward_rule_close:{user.id}:{leave_id}",
                    payload={
                        "leave_id": leave_id,
                        "rule_name": rule.get("displayName"),
                        "reason": "orphan" if leave_id not in existing else "ended",
                    },
                    leave_request_id=uuid.UUID(leave_id)
                    if leave_id in existing
                    else None,
                ):
                    counts["forward_close_enqueued"] += 1
            for leave_id, leave in active.items():
                if leave_id in seen or _forward_open_pending(
                    latest_forward.get(leave.id), executed
                ):
                    continue
                if await enqueue_at(
                    db,
                    user_id=user.id,
                    kind="forward_rule_open",
                    dedupe_key=f"leave:{leave_id}:forward_rule_open:reconcile:{day_key}",
                    payload=_forward_payload(leave, "reconcile"),
                    leave_request_id=leave.id,
                ):
                    counts["forward_open_enqueued"] += 1

        # 3. Wydarzenia, które powstały tylko w symulacji.
        for op in calendar_redo.get(user.id, []):
            if await enqueue_at(
                db,
                user_id=user.id,
                kind="calendar_event_upsert",
                dedupe_key=f"leave:{op.leave_request_id}:calendar_event_upsert:reconcile:{day_key}",
                payload=dict(op.payload or {}),
                leave_request_id=op.leave_request_id,
            ):
                counts["calendar_enqueued"] += 1

        if mode == "live":
            await save_mailbox_state(
                db,
                user.id,
                custom_oof=custom_flag,
                last_error=error,
                reconciled_at=now if error is None else None,
            )
        await db.commit()
    return dict(counts)


async def _existing_leaves(
    db: AsyncSession, leave_ids: set[str], user_id: int
) -> set[str]:
    """Które id z nazw reguł to urlopy TEJ osoby w NEXUSIE (reszta to sieroty)."""

    parsed = []
    for value in leave_ids:
        try:
            parsed.append(uuid.UUID(value))
        except ValueError:
            continue
    if not parsed:
        return set()
    rows = await db.scalars(
        select(LeaveRequest.id).where(
            LeaveRequest.id.in_(parsed), LeaveRequest.user_id == user_id
        )
    )
    return {str(value) for value in rows.all()}


def _forward_payload(leave: LeaveRequest, reason: str) -> dict[str, Any]:
    return {
        "start": leave.start_date.isoformat(),
        "end": leave.end_date.isoformat(),
        "substitute_user_id": leave.substitute_user_id,
        "rule_name": forward_rules.rule_name(str(leave.id)),
        "reason": reason,
    }


async def run_once(
    db: AsyncSession,
    *,
    ops: Optional[MailboxOps] = None,
    mode: Optional[str] = None,
    now: Optional[datetime] = None,
    user_ids: Optional[Collection[int]] = None,
) -> dict[str, Any]:
    """Jeden przebieg dziennie po 7:00; wcześniej i powtórnie — nic.

    ``user_ids`` zawęża przegląd do wskazanych skrzynek (testy).
    """

    mode = mode or current_mode()
    if mode == "off":
        return {"status": "disabled"}
    now = now or utc_now()
    today = warsaw_today(now)
    if warsaw_hour(now) < RECONCILE_HOUR:
        return {"mode": mode, "skipped": "before_07"}
    if mode == "live" and ops is None:
        from app.services.hr.m365.auth import credentials_configured

        if not credentials_configured():
            return {"mode": mode, "skipped": "no_credentials"}

    run_id = await job_runs.claim(db, JOB_KIND, today.isoformat(), now)
    if run_id is None:
        return {"mode": mode, "skipped": "already_ran"}

    own_ops = ops is None
    active_ops: MailboxOps = ops or (
        SimulatedMailboxOps() if mode == "simulate" else GraphMailboxOps()
    )
    try:
        counts = await _reconcile(db, active_ops, mode, now, today, user_ids)
    except Exception as exc:  # noqa: BLE001 — przebieg do ponowienia, nie cichy sukces
        logger.exception("hr_m365_reconcile failed")
        await db.rollback()
        await job_runs.finish(
            db, run_id, status="failed", counts={}, error=type(exc).__name__
        )
        return {"mode": mode, "failed": type(exc).__name__}
    finally:
        if own_ops:
            await active_ops.aclose()
    await job_runs.finish(db, run_id, status="done", counts=counts)
    return {"mode": mode, **counts}
