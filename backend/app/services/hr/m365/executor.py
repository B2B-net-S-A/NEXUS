"""Wykonawca kolejki ``hr_m365_operations`` (pętla co 60 s, ``run_once``).

Tryby (``HR_M365_MODE``):

* ``off`` — nic nie wychodzi; operacje czekają w kolejce (nie znikają),
* ``simulate`` — ten sam przebieg co ``live`` na ``SimulatedMailboxOps``:
  dokładne żądania (metoda, ścieżka, ciało) lądują w ``simulated_request``,
  status ``simulated``; stan skrzynki nie jest zapisywany,
* ``live`` — Graph przez rejestrację HR, tylko skrzynki z
  ``HR_M365_MAILBOX_ALLOWLIST`` (pusta = wszystkie); pozostałe czekają
  z ``last_error = not_allowlisted`` i odroczonym ``next_attempt_at``.

Rezerwacja: ``SELECT … FOR UPDATE SKIP LOCKED`` (paczka ≤ 20) i status
``running`` z dzierżawą w ``next_attempt_at`` — dwa procesy nie wykonają tej
samej operacji, a operacja z przerwanego przebiegu wraca po wygaśnięciu
dzierżawy. Błąd 403/429/5xx/sieci: ``attempts + 1`` i odroczenie
5 min → 30 min → 2 h → 6 h, po 6 próbach ``failed``. W ``last_error`` jest
kategoria błędu, nigdy treść odpowiedzi Graph.

Każda operacja sprawdza wniosek (``leave_requests``, tylko odczyt) przed
zapisem w skrzynce: anulowany urlop nie dostanie autoodpowiedzi z operacji,
która czekała na ponowienie, a przekierowanie bez zgody osoby się nie
otworzy, nawet jeśli kolejność operacji w kolejce się rozjechała.

Graph trzyma JEDEN harmonogram autoodpowiedzi, a wcześniejszy urlop nadpisuje
późniejszy. Zdjęcie naszej autoodpowiedzi (anulowanie) dokłada więc
``set_oof`` najbliższego innego zatwierdzonego urlopu osoby — inaczej
późniejszy urlop zostałby bez autoodpowiedzi (przegląd 16.10.2026, D17).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from collections.abc import Awaitable, Callable, Collection
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, local_day_start_utc
from app.models.hr_leave import (
    HrM365MailboxState,
    HrM365Operation,
    LeaveRequest,
    LeaveRequestDay,
)
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import audit
from app.services.hr.calendar import load_calendar
from app.services.hr.leave_m365 import LeaveSnapshot, plan_operations
from app.services.hr.leave_policy import forward_target_allowed
from app.services.hr.m365 import (
    calendar_event,
    forward_rules,
    oof_state,
    oof_template,
    outbox,
)
from app.services.hr.m365.ops import GraphMailboxOps, MailboxError, MailboxOps
from app.services.hr.m365.simulated import SimulatedMailboxOps
from app.services.hr_foundation_schema import EmploymentStatus

logger = logging.getLogger(__name__)

MODES = ("off", "simulate", "live")
BATCH_SIZE = 20
MAX_ATTEMPTS = 6
RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
)
#: Dzierżawa operacji w toku — po tym czasie przerwany przebieg oddaje ją kolejce.
LEASE = timedelta(minutes=15)
NOT_ALLOWLISTED_DELAY = timedelta(hours=1)

#: Powody odroczenia, które nie są błędem (karta pokazuje je jako „czeka”).
DEFERRAL_REASONS = ("not_allowlisted", "waiting_for_window", "other_leave_oof")
#: Ile kolejnych urlopów osoby przeglądamy, szukając następcy autoodpowiedzi.
NEXT_LEAVES_SCAN = 10

_WARSAW = ZoneInfo(DEFAULT_TZ)


def current_mode() -> str:
    mode = (settings.HR_M365_MODE or "off").strip().lower()
    return mode if mode in MODES else "off"


def allowlist() -> frozenset[str]:
    raw = settings.HR_M365_MAILBOX_ALLOWLIST or ""
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def mailbox_allowed(upn: str, allowed: frozenset[str]) -> bool:
    return not allowed or upn.lower() in allowed


def mailbox_address(user: Optional[User]) -> Optional[str]:
    if user is None:
        return None
    address = (user.microsoft_upn or user.email or "").strip()
    return address or None


def company_domains() -> list[str]:
    return settings.sso_allowed_domains_list


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def warsaw_today(now: datetime) -> date:
    return now.astimezone(_WARSAW).date()


def warsaw_hour(now: datetime) -> int:
    return now.astimezone(_WARSAW).hour


@dataclass
class Outcome:
    """Wynik jednej operacji.

    ``done`` / ``skipped`` kończą operację; ``deferred`` wraca do kolejki na
    ``retry_at`` bez liczenia próby; ``error`` liczy próbę.
    """

    kind: str
    reason: Optional[str] = None
    retry_at: Optional[datetime] = None
    error: Optional[MailboxError] = None


@dataclass
class MailboxDraft:
    """Zmiany stanu skrzynki z jednej operacji (zapis tylko w trybie live)."""

    events: dict[str, str]
    custom_oof: Optional[bool] = None
    touched: bool = False


@dataclass
class Context:
    db: AsyncSession
    ops: MailboxOps
    mode: str
    now: datetime
    today: date
    op: HrM365Operation
    user: User
    upn: str
    leave: Optional[LeaveRequest]
    mailbox: MailboxDraft
    notes: dict[str, Any] = field(default_factory=dict)


def _date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _bad_payload() -> Outcome:
    return Outcome("error", error=MailboxError(None, category="bad_payload"))


# ── Autoodpowiedź ─────────────────────────────────────────────────────────────


async def _contact(
    db: AsyncSession, user_id: int, substitute_user_id: Optional[int]
) -> Optional[oof_template.Contact]:
    """Zastępca → przełożony (aktywny) → skrzynka administracji."""

    if substitute_user_id:
        substitute = await db.get(User, substitute_user_id)
        if substitute is not None and substitute.is_active and substitute.email:
            return oof_template.Contact("substitute", substitute.email, substitute.name)
    manager_id = await db.scalar(
        select(EmployeeProfile.manager_user_id).where(
            EmployeeProfile.user_id == user_id
        )
    )
    if manager_id:
        manager = await db.get(User, manager_id)
        manager_status = await db.scalar(
            select(EmployeeProfile.employment_status).where(
                EmployeeProfile.user_id == manager_id
            )
        )
        if (
            manager is not None
            and manager.is_active
            and manager.email
            and manager_status != EmploymentStatus.exited
        ):
            return oof_template.Contact("manager", manager.email, manager.name)
    office = (settings.ADMIN_CASES_MAILBOX or "").strip()
    return oof_template.Contact("office", office) if office else None


async def _set_oof(ctx: Context) -> Outcome:
    payload = ctx.op.payload or {}
    start, end = _date(payload.get("start")), _date(payload.get("end"))
    if start is None or end is None:
        return _bad_payload()
    if ctx.leave is not None and ctx.leave.status != "approved":
        return Outcome("skipped", "leave_not_active")
    if end < ctx.today:
        return Outcome("skipped", "leave_ended")

    current = await ctx.ops.get_auto_replies(ctx.upn)
    if oof_state.user_custom_active(current, ctx.now):
        # Własna autoodpowiedź osoby zostaje; Kadry widzą skrzynkę w karcie.
        ctx.mailbox.custom_oof = True
        return Outcome("skipped", "user_custom")
    if not oof_state.matches_leave(current, start, end):
        until = oof_state.blocking_until(current, start, ctx.today)
        if until is not None:
            return Outcome("deferred", "other_leave_oof", retry_at=until)

    return_on = _date(payload.get("return_on")) or end + timedelta(days=1)
    contact = await _contact(ctx.db, ctx.op.user_id, payload.get("substitute_user_id"))
    setting = oof_template.build_setting(
        start=start,
        end=end,
        return_on=return_on,
        employee_name=ctx.user.name,
        contact=contact,
        internal_custom=payload.get("internal_message"),
        external_custom=payload.get("external_message"),
    )
    await ctx.ops.set_auto_replies(ctx.upn, setting)
    ctx.mailbox.custom_oof = False
    return Outcome("done")


async def _other_leave_with_window(ctx: Context, start: date, end: date) -> bool:
    query = select(LeaveRequest.id).where(
        LeaveRequest.user_id == ctx.op.user_id,
        LeaveRequest.status == "approved",
        LeaveRequest.start_date == start,
        LeaveRequest.end_date == end,
    )
    if ctx.op.leave_request_id is not None:
        query = query.where(LeaveRequest.id != ctx.op.leave_request_id)
    return (await ctx.db.scalar(query.limit(1))) is not None


async def leave_day_totals(
    db: AsyncSession, leave_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Suma dni (ułamków) wniosków — pół dnia nie dostaje autoodpowiedzi."""

    if not leave_ids:
        return {}
    rows = await db.execute(
        select(LeaveRequestDay.leave_request_id, func.sum(LeaveRequestDay.fraction))
        .where(LeaveRequestDay.leave_request_id.in_(leave_ids))
        .group_by(LeaveRequestDay.leave_request_id)
    )
    return {leave_id: Decimal(total or 0) for leave_id, total in rows.all()}


async def set_oof_payload(
    db: AsyncSession, leave: LeaveRequest, total: Decimal
) -> Optional[dict]:
    """Ładunek ``set_oof`` jak przy akceptacji; ``None`` = urlop bez pełnego dnia."""

    calendar = await load_calendar(db, leave.start_date, leave.end_date)
    snapshot = LeaveSnapshot(
        id=str(leave.id),
        user_id=leave.user_id,
        start=leave.start_date,
        end=leave.end_date,
        half_day=leave.half_day,
        total_days=total,
        substitute_user_id=leave.substitute_user_id,
        forward_mail_consent=leave.forward_mail_consent,
        oof_internal_message=leave.oof_internal_message,
        oof_external_message=leave.oof_external_message,
        return_on=calendar.next_working_day_after(leave.end_date),
    )
    for planned in plan_operations("approved", snapshot, today=leave.start_date):
        if planned.kind == "set_oof":
            return planned.payload
    return None


async def _hand_over_oof(ctx: Context) -> None:
    """Po zdjęciu naszej autoodpowiedzi: ``set_oof`` najbliższego innego urlopu.

    Wcześniejszy urlop nadpisał harmonogram późniejszego (Graph trzyma jeden),
    więc bez tego anulowanie wcześniejszego zostawia późniejszy bez
    autoodpowiedzi, a uzgadnianie nie miałoby czego naprawić przed jego
    początkiem. Urlop bez pełnego dnia nie dostaje autoodpowiedzi — szukamy
    dalej.
    """

    query = select(LeaveRequest).where(
        LeaveRequest.user_id == ctx.op.user_id,
        LeaveRequest.status == "approved",
        LeaveRequest.end_date >= ctx.today,
    )
    if ctx.op.leave_request_id is not None:
        query = query.where(LeaveRequest.id != ctx.op.leave_request_id)
    leaves = list(
        (
            await ctx.db.scalars(
                query.order_by(LeaveRequest.start_date, LeaveRequest.id).limit(
                    NEXT_LEAVES_SCAN
                )
            )
        ).all()
    )
    totals = await leave_day_totals(ctx.db, [leave.id for leave in leaves])
    for leave in leaves:
        payload = await set_oof_payload(
            ctx.db, leave, totals.get(leave.id, Decimal("0"))
        )
        if payload is None:
            continue
        await enqueue_at(
            ctx.db,
            user_id=ctx.op.user_id,
            kind="set_oof",
            dedupe_key=f"leave:{leave.id}:set_oof:after_clear:{ctx.op.id}",
            payload=payload,
            leave_request_id=leave.id,
            not_before=ctx.now,
        )
        return


async def _clear_oof(ctx: Context) -> Outcome:
    payload = ctx.op.payload or {}
    start, end = _date(payload.get("start")), _date(payload.get("end"))
    if start is None or end is None:
        return _bad_payload()
    current = await ctx.ops.get_auto_replies(ctx.upn)
    if oof_state.is_disabled(current):
        # Nic nie zapisujemy — uzgadnianie nie może wziąć tego za nasze
        # wyłączenie autoodpowiedzi innego urlopu (wyłączyła ją osoba).
        return Outcome("skipped", "already_disabled")
    if not oof_state.matches_leave(current, start, end):
        # Cudza autoodpowiedź albo innego urlopu — nie ruszamy.
        return Outcome("skipped", "not_owned")
    if await _other_leave_with_window(ctx, start, end):
        # Nowy zatwierdzony urlop w tych samych dniach przejął autoodpowiedź.
        return Outcome("skipped", "other_leave_same_window")
    await ctx.ops.set_auto_replies(ctx.upn, {"status": "disabled"})
    await _hand_over_oof(ctx)
    return Outcome("done")


# ── Kalendarz ─────────────────────────────────────────────────────────────────


def _window(start: date, end: date) -> tuple[datetime, datetime]:
    return local_day_start_utc(start), local_day_start_utc(end + timedelta(days=1))


async def _find_events(
    ctx: Context, start: date, end: date, transaction_ids: frozenset[str]
) -> list[dict[str, Any]]:
    window_start, window_end = _window(start, end)
    found = await ctx.ops.find_events(ctx.upn, window_start, window_end)
    return [
        event
        for event in found
        if event.get("id") and event.get("transactionId") in transaction_ids
    ]


async def _calendar_upsert(ctx: Context) -> Outcome:
    payload = ctx.op.payload or {}
    start, end = _date(payload.get("start")), _date(payload.get("end"))
    transaction = payload.get("transaction_id")
    if start is None or end is None or not transaction:
        return _bad_payload()
    if ctx.leave is not None and ctx.leave.status != "approved":
        return Outcome("skipped", "leave_not_active")
    if end < ctx.today:
        return Outcome("skipped", "leave_ended")

    half_day = payload.get("half_day")
    patch_body = calendar_event.event_body(start=start, end=end, half_day=half_day)
    known = ctx.mailbox.events.get(transaction)
    if known:
        try:
            await ctx.ops.update_event(ctx.upn, known, patch_body)
            return Outcome("done")
        except MailboxError as exc:
            if exc.status != 404:
                raise
            # Osoba usunęła wydarzenie w Outlooku — zakładamy od nowa.
            ctx.mailbox.events.pop(transaction, None)
            ctx.mailbox.touched = True

    try:
        created = await ctx.ops.create_event(
            ctx.upn,
            calendar_event.event_body(
                start=start, end=end, half_day=half_day, transaction=transaction
            ),
        )
    except MailboxError as exc:
        if exc.status != 409:
            raise
        # ``transactionId`` już użyty (odpowiedź poprzedniej próby zginęła) —
        # odszukujemy wydarzenie i doprowadzamy je do bieżącego kształtu.
        matches = await _find_events(ctx, start, end, frozenset({transaction}))
        if not matches:
            raise
        created = matches[0]
        await ctx.ops.update_event(ctx.upn, created["id"], patch_body)
    event_id = created.get("id")
    if event_id:
        ctx.mailbox.events[transaction] = str(event_id)
        ctx.mailbox.touched = True
    return Outcome("done")


async def _calendar_delete(ctx: Context) -> Outcome:
    payload = ctx.op.payload or {}
    transaction = payload.get("transaction_id")
    if not transaction:
        return _bad_payload()
    targets: list[str] = []
    known = ctx.mailbox.events.get(transaction)
    if known:
        targets.append(known)
    if ctx.leave is not None:
        # Wydarzenie bez zapamiętanego id i wydarzenie Compassa (``leave-{id}``)
        # urlopu z importu — szukamy w oknie urlopu.
        leave_id = str(ctx.leave.id)
        found = await _find_events(
            ctx,
            ctx.leave.start_date,
            ctx.leave.end_date,
            calendar_event.known_transaction_ids(leave_id),
        )
        targets.extend(
            str(event["id"]) for event in found if str(event["id"]) not in targets
        )
    for event_id in targets:
        try:
            await ctx.ops.delete_event(ctx.upn, event_id)
        except MailboxError as exc:
            if exc.status != 404:  # 404 = już usunięte (np. ręcznie w Outlooku)
                raise
    if transaction in ctx.mailbox.events:
        ctx.mailbox.events.pop(transaction, None)
        ctx.mailbox.touched = True
    ctx.notes["deleted"] = len(targets)
    return Outcome("done")


# ── Przekierowanie poczty ─────────────────────────────────────────────────────


def forward_should_be_active(leave: LeaveRequest, today: date) -> bool:
    return (
        leave.status == "approved"
        and leave.forward_mail_consent
        and leave.substitute_user_id is not None
        and forward_rules.window_state(leave.start_date, leave.end_date, today)
        == "open"
    )


async def enqueue_at(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    dedupe_key: str,
    payload: dict[str, Any],
    leave_request_id: Optional[uuid.UUID],
    not_before: Optional[datetime] = None,
) -> bool:
    """``outbox.enqueue`` z opcjonalnym terminem pierwszej próby."""

    created = await outbox.enqueue(
        db,
        user_id=user_id,
        kind=kind,
        dedupe_key=dedupe_key,
        payload=payload,
        leave_request_id=leave_request_id,
    )
    if created and not_before is not None:
        await db.execute(
            update(HrM365Operation)
            .where(
                HrM365Operation.dedupe_key == dedupe_key[:200],
                HrM365Operation.status == "pending",
            )
            .values(next_attempt_at=not_before)
        )
    return created


async def _forward_open(ctx: Context) -> Outcome:
    leave = ctx.leave
    if leave is None or leave.user_id != ctx.op.user_id:
        return Outcome("skipped", "leave_missing")
    if leave.status != "approved":
        return Outcome("skipped", "leave_not_active")
    if not leave.forward_mail_consent or leave.substitute_user_id is None:
        return Outcome("skipped", "no_consent")
    window = forward_rules.window_state(leave.start_date, leave.end_date, ctx.today)
    if window == "after":
        return Outcome("skipped", "leave_ended")
    if window == "before":
        # Poczta płynie do zastępcy dopiero od pierwszego dnia urlopu.
        return Outcome(
            "deferred",
            "waiting_for_window",
            retry_at=local_day_start_utc(leave.start_date),
        )
    substitute = await ctx.db.get(User, leave.substitute_user_id)
    if substitute is None or not substitute.is_active or not substitute.email:
        return Outcome(
            "error", error=MailboxError(None, category="substitute_unavailable")
        )

    leave_id = str(leave.id)
    if not forward_target_allowed(substitute.email, company_domains()):
        # Poczta nie wychodzi poza firmę: reguły nie otwieramy, a regułę tego
        # urlopu z przejęcia (Compass) zdejmujemy. W ``last_error`` sama kategoria.
        for rule in await ctx.ops.list_rules(ctx.upn):
            if (
                rule.get("id")
                and forward_rules.parse_leave_id(rule.get("displayName")) == leave_id
            ):
                await _delete_rule(ctx, str(rule["id"]))
        return Outcome(
            "error", error=MailboxError(None, category="substitute_outside_company")
        )
    body = forward_rules.rule_body(
        leave_id=leave_id,
        substitute_email=substitute.email,
        substitute_name=substitute.name,
        company_domains=company_domains(),
    )
    rules = await ctx.ops.list_rules(ctx.upn)
    mine = [
        rule
        for rule in rules
        if rule.get("id")
        and forward_rules.parse_leave_id(rule.get("displayName")) == leave_id
    ]
    if mine:
        # Reguła NEXUSA przed regułą Compassa; przejęta reguła Compassa dostaje
        # naszą nazwę, filtry i bieżącego zastępcę (jedno żądanie, ten sam id).
        mine.sort(
            key=lambda rule: forward_rules.is_compass_rule(rule.get("displayName"))
        )
        keep, *extra = mine
        await ctx.ops.update_rule(ctx.upn, str(keep["id"]), body)
        for rule in extra:
            await _delete_rule(ctx, str(rule["id"]))
    else:
        await ctx.ops.create_rule(ctx.upn, body)

    # Zamknięcie zaraz po ostatnim dniu (uzgadnianie o 7:00 jest siatką).
    await enqueue_at(
        ctx.db,
        user_id=ctx.op.user_id,
        kind="forward_rule_close",
        dedupe_key=f"leave:{leave_id}:forward_rule_close:end:{leave.end_date.isoformat()}",
        payload={
            "start": leave.start_date.isoformat(),
            "end": leave.end_date.isoformat(),
            "substitute_user_id": leave.substitute_user_id,
            "rule_name": forward_rules.rule_name(leave_id),
            "reason": "ended",
        },
        leave_request_id=leave.id,
        not_before=local_day_start_utc(leave.end_date + timedelta(days=1)),
    )
    if ctx.mode == "live":
        audit.record(
            ctx.db,
            actor_user_id=None,
            subject_user_id=ctx.op.user_id,
            entity_type="leave_request",
            entity_id=leave_id,
            action="m365_forward_opened",
            details={"operation_id": ctx.op.id, "substitute_user_id": substitute.id},
        )
    return Outcome("done")


async def _delete_rule(ctx: Context, rule_id: str) -> None:
    try:
        await ctx.ops.delete_rule(ctx.upn, rule_id)
    except MailboxError as exc:
        if exc.status != 404:
            raise


async def _forward_close(ctx: Context) -> Outcome:
    payload = ctx.op.payload or {}
    leave = (
        ctx.leave
        if ctx.leave is not None and ctx.leave.user_id == ctx.op.user_id
        else None
    )
    leave_id = (
        str(leave.id)
        if leave is not None
        else payload.get("leave_id")
        or forward_rules.parse_leave_id(payload.get("rule_name"))
    )
    if not leave_id:
        return _bad_payload()
    leave_id = str(leave_id).lower()
    if leave is not None and forward_should_be_active(leave, ctx.today):
        # Zgoda wróciła albo urlop trwa — późniejsza operacja otwarcia wygrywa.
        return Outcome("skipped", "still_active")
    rules = await ctx.ops.list_rules(ctx.upn)
    targets = [
        str(rule["id"])
        for rule in rules
        if rule.get("id")
        and forward_rules.parse_leave_id(rule.get("displayName")) == leave_id
    ]
    for rule_id in targets:
        await _delete_rule(ctx, rule_id)
    ctx.notes["deleted"] = len(targets)
    if targets and ctx.mode == "live":
        audit.record(
            ctx.db,
            actor_user_id=None,
            subject_user_id=ctx.op.user_id,
            entity_type="leave_request",
            entity_id=leave_id,
            action="m365_forward_closed",
            details={
                "operation_id": ctx.op.id,
                "rules": len(targets),
                "reason": payload.get("reason") or "cancelled",
            },
        )
    return Outcome("done")


HANDLERS: dict[str, Callable[[Context], Awaitable[Outcome]]] = {
    "set_oof": _set_oof,
    "clear_oof": _clear_oof,
    "calendar_event_upsert": _calendar_upsert,
    "calendar_event_delete": _calendar_delete,
    "forward_rule_open": _forward_open,
    "forward_rule_close": _forward_close,
}


# ── Kolejka ───────────────────────────────────────────────────────────────────


async def claim(
    db: AsyncSession,
    now: datetime,
    limit: int = BATCH_SIZE,
    *,
    user_ids: Optional[Collection[int]] = None,
) -> list[int]:
    """Rezerwuje paczkę operacji: oczekujące z terminem i te z wygasłą dzierżawą.

    ``user_ids`` zawęża przebieg do skrzynek wskazanych osób (testy, ręczne
    uruchomienie dla jednej skrzynki).
    """

    query = select(HrM365Operation.id).where(
        HrM365Operation.status.in_(("pending", "running")),
        HrM365Operation.next_attempt_at <= now,
    )
    if user_ids is not None:
        query = query.where(HrM365Operation.user_id.in_(list(user_ids)))
    rows = await db.execute(
        query.order_by(HrM365Operation.next_attempt_at, HrM365Operation.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    ids = list(rows.scalars().all())
    if ids:
        await db.execute(
            update(HrM365Operation)
            .where(HrM365Operation.id.in_(ids))
            .values(status="running", next_attempt_at=now + LEASE)
        )
    await db.commit()
    return ids


async def _load_mailbox(db: AsyncSession, user_id: int) -> MailboxDraft:
    row = await db.get(HrM365MailboxState, user_id)
    events = dict(((row.state if row else None) or {}).get("events") or {})
    return MailboxDraft(events=events)


async def save_mailbox_state(
    db: AsyncSession,
    user_id: int,
    *,
    events: Optional[dict[str, str]] = None,
    custom_oof: Optional[bool] = None,
    last_error: Any = ...,
    reconciled_at: Optional[datetime] = None,
) -> None:
    """Upsert stanu skrzynki; pola ``None``/``...`` zostają bez zmian."""

    row = await db.get(HrM365MailboxState, user_id)
    if row is None:
        row = HrM365MailboxState(user_id=user_id, state={})
        db.add(row)
        await db.flush()
    if events is not None:
        state = dict(row.state or {})
        state["events"] = dict(events)
        row.state = state
    if custom_oof is not None:
        row.custom_oof_detected = custom_oof
    if last_error is not ...:
        row.last_error = last_error
    if reconciled_at is not None:
        row.last_reconciled_at = reconciled_at


async def _execute(
    db: AsyncSession,
    op: HrM365Operation,
    ops: MailboxOps,
    mode: str,
    now: datetime,
    allowed: frozenset[str],
) -> tuple[Outcome, Optional[Context]]:
    user = await db.get(User, op.user_id)
    upn = mailbox_address(user)
    if user is None or upn is None:
        return Outcome(
            "error", error=MailboxError(None, category="no_mailbox_address")
        ), None
    if mode == "live" and not mailbox_allowed(upn, allowed):
        return Outcome(
            "deferred", "not_allowlisted", retry_at=now + NOT_ALLOWLISTED_DELAY
        ), None
    handler = HANDLERS.get(op.kind)
    if handler is None:
        return _bad_payload(), None
    leave = (
        await db.get(LeaveRequest, op.leave_request_id) if op.leave_request_id else None
    )
    ctx = Context(
        db=db,
        ops=ops,
        mode=mode,
        now=now,
        today=warsaw_today(now),
        op=op,
        user=user,
        upn=upn,
        leave=leave,
        mailbox=await _load_mailbox(db, op.user_id),
    )
    try:
        return await handler(ctx), ctx
    except MailboxError as exc:
        return Outcome("error", error=exc), ctx


async def _apply(
    db: AsyncSession,
    op: HrM365Operation,
    outcome: Outcome,
    ctx: Optional[Context],
    *,
    mode: str,
    now: datetime,
    requests: Optional[list[dict[str, Any]]],
) -> str:
    """Zapisuje wynik operacji (i w trybie live stan skrzynki); zwraca etykietę licznika."""

    if requests is not None:
        op.simulated_request = {
            "mailbox": ctx.upn if ctx else None,
            "requests": requests,
            "at": now.isoformat(),
        }
    label: str
    if outcome.kind in ("done", "skipped"):
        op.status = (
            "simulated"
            if mode == "simulate" and outcome.kind == "done"
            else outcome.kind
        )
        op.last_error = outcome.reason
        op.done_at = now
        op.next_attempt_at = now
        label = op.status
    elif outcome.kind == "deferred":
        op.status = "pending"
        op.last_error = outcome.reason
        op.next_attempt_at = outcome.retry_at or now + RETRY_DELAYS[0]
        label = "deferred"
    else:
        error = outcome.error or MailboxError(None, category="internal")
        op.attempts = (op.attempts or 0) + 1
        op.last_error = error.label
        if error.retryable and op.attempts < MAX_ATTEMPTS:
            op.status = "pending"
            op.next_attempt_at = (
                now + RETRY_DELAYS[min(op.attempts, len(RETRY_DELAYS)) - 1]
            )
            label = "retry"
        else:
            op.status = "failed"
            op.done_at = now
            op.next_attempt_at = now
            label = "failed"

    if mode == "live" and ctx is not None:
        error_label = op.last_error if label in ("retry", "failed") else None
        await save_mailbox_state(
            db,
            op.user_id,
            events=ctx.mailbox.events if ctx.mailbox.touched else None,
            custom_oof=ctx.mailbox.custom_oof,
            last_error=error_label,
        )
    return label


async def run_once(
    db: AsyncSession,
    *,
    ops: Optional[MailboxOps] = None,
    mode: Optional[str] = None,
    now: Optional[datetime] = None,
    limit: int = BATCH_SIZE,
    user_ids: Optional[Collection[int]] = None,
) -> dict[str, Any]:
    """Jeden przebieg wykonawcy (pętla co 60 s, przy trybie innym niż ``off``)."""

    mode = mode or current_mode()
    if mode == "off":
        return {"status": "disabled"}
    counts: dict[str, Any] = {"mode": mode}
    if mode == "live" and ops is None:
        from app.services.hr.m365.auth import credentials_configured

        if not credentials_configured():
            # Operacje czekają, aż rejestracja HR dostanie poświadczenia.
            counts["skipped"] = "no_credentials"
            return counts
    now = now or utc_now()
    ids = await claim(db, now, limit, user_ids=user_ids)
    counts["claimed"] = len(ids)
    if not ids:
        return counts

    allowed = allowlist()
    shared_ops: Optional[MailboxOps] = ops
    own_live_ops = mode == "live" and ops is None
    if own_live_ops:
        shared_ops = GraphMailboxOps()
    try:
        for op_id in ids:
            op = await db.get(HrM365Operation, op_id)
            if op is None or op.status != "running":
                continue
            op_ops = shared_ops
            recorder: Optional[SimulatedMailboxOps] = None
            if mode == "simulate" and op_ops is None:
                recorder = SimulatedMailboxOps()
                op_ops = recorder
            ctx: Optional[Context] = None
            try:
                outcome, ctx = await _execute(db, op, op_ops, mode, now, allowed)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 — jedna operacja nie zatrzymuje paczki
                logger.exception("hr_m365: operation %s (%s) crashed", op.id, op.kind)
                await db.rollback()
                op = await db.get(HrM365Operation, op_id)
                if op is None:
                    continue
                outcome, ctx = (
                    Outcome("error", error=MailboxError(None, category="internal")),
                    None,
                )
            label = await _apply(
                db,
                op,
                outcome,
                ctx,
                mode=mode,
                now=now,
                requests=recorder.requests if recorder is not None else None,
            )
            counts[label] = counts.get(label, 0) + 1
            if label in ("retry", "failed"):
                logger.warning(
                    "hr_m365: operation %s (%s) %s: %s",
                    op.id,
                    op.kind,
                    label,
                    op.last_error,
                )
            await db.commit()
    finally:
        if own_live_ops and shared_ops is not None:
            await shared_ops.aclose()
    return counts


async def retry(
    db: AsyncSession, op: HrM365Operation, *, now: Optional[datetime] = None
) -> None:
    """„Ponów” z karty: nieudana albo czekająca operacja wraca do kolejki od razu."""

    moment = now or utc_now()
    op.status = "pending"
    op.attempts = 0
    op.last_error = None
    op.done_at = None
    op.next_attempt_at = moment
