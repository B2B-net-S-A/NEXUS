"""Import wniosków urlopowych z ``leave_requests`` Compassa.

Reguły:

* wniosek zachowuje id z Compassa (UUID), ``source = 'compass_import'``,
* dni wniosku liczy kalendarz firmy (``requested_days`` — ta sama funkcja co
  przy składaniu wniosku w NEXUSIE); ``paid`` ma tylko urlop z puli: na umowie
  o pracę każdy dzień, na B2B pierwsze dni do ``paid_days`` Compassa
  (pół dnia niepodzielne, jak w Compassie), na zleceniu żaden — puli tam nie
  ma (D6, ``leave_policy.pool_applies``); dni płatne z Compassa idą jako
  bezpłatne z uwagą w raporcie,
* dni są aktywne dla wniosków oczekujących i zatwierdzonych; nakładka na inny
  aktywny dzień tej osoby (w NEXUSIE albo wcześniej w tej paczce) to wiersz
  „conflict” do decyzji — Compass przepuszczał nakładki przy wpisie za
  pracownika, NEXUS ich nie przyjmuje (indeks częściowy),
* nikt nie decyduje o własnym wniosku: ``decided_by`` równy osobie → pusty
  (w Compassie admin zatwierdzał sam siebie),
* zgoda na przekierowanie poczty przechodzi tylko z wniosku złożonego przez
  samą osobę i tylko z zastępcą (Compass pozwalał ją włączyć przełożonemu),
* import nie wysyła powiadomień ani operacji Microsoft 365,
* wniosek zmieniony w NEXUSIE po imporcie (decyzja, anulowanie, przeliczenie
  dni) zostaje w wersji NEXUSA: „bez zmian”, gdy paczka mówi to samo,
  inaczej „conflict” do decyzji — nigdy „update” (anulowany urlop nie wraca
  jako zatwierdzony bez autoodpowiedzi i bez śladu),
* oczekujący wniosek osoby na B2B albo zleceniu wchodzi jako zgłoszenie
  przyjęte (etap 2, D5): ``approved`` bez decydującego, z datą złożenia jako
  datą przyjęcia; raport importu liczy takie wiersze
  (``extra.contractor_pending_reported``, same liczby).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_ops import HrImportBatch
from app.services.hr.calendar import WorkCalendar, load_calendar
from app.services.hr.employment_terms import reports_absence
from app.services.hr.leave_policy import (
    ACTIVE_DAY_UNIQUE,
    POOL_TYPES,
    pool_applies,
    requested_days,
    split_days,
)
from app.services.hr_leave_schema import (
    ACTIVE_STATUSES,
    HALF_DAYS,
    LEAVE_STATUSES,
    LEAVE_TYPES,
)

from .bundle import Bundle
from .common import (
    NO_PROFILE,
    ImportPlan,
    decimal,
    join_notes,
    load_people,
    module_map,
    parse_date,
    parse_datetime,
    parse_uuid,
    source_id,
    text,
)
from .core import ModulePlan, RowPlan, changed_in_nexus, remember

MODULE = "leave"
TABLE = "leave_requests"

OVERLAP = "nakłada się na inny aktywny wniosek tej osoby"
SELF_DECISION = "decyzja o własnym wniosku — decydujący pominięty"
FORWARD_ON_BEHALF = "zgoda na przekierowanie z wpisu za pracownika — pominięta"
CHANGED_IN_NEXUS = "wniosek zmieniony w NEXUSIE po imporcie — zostaje wersja NEXUSA"
REPORTED_FROM_PENDING = (
    "oczekujący wniosek z B2B/zlecenia — przyjęty jako zgłoszenie (bez akceptacji)"
)
MANDATE_PAID_DROPPED = (
    "dni płatne z Compassa na zleceniu — bez puli, wchodzą jako bezpłatne"
)

#: Pola wniosku porównywane przy ponownym imporcie.
REQUEST_FIELDS = (
    "user_id",
    "leave_type",
    "status",
    "start_date",
    "end_date",
    "half_day",
    "note",
    "substitute_user_id",
    "forward_mail_consent",
    "oof_internal_message",
    "oof_external_message",
    "paid_days",
    "unpaid_days",
    "decided_by",
    "decided_at",
    "decision_note",
    "created_by",
    "source",
)

DayRow = tuple[date, Decimal, bool]


def plan_request_days(
    calendar: WorkCalendar,
    *,
    start: date,
    end: date,
    half_day: Optional[str],
    leave_type: str,
    employment_type: Optional[str],
    compass_paid_days: Optional[Decimal],
) -> list[DayRow]:
    """Dni robocze wniosku z flagą ``paid`` (dzień z puli płatnej)."""

    days = requested_days(calendar, start, end, half_day)
    if leave_type not in POOL_TYPES or not pool_applies(employment_type):
        return [(day, fraction, False) for day, fraction in days]
    if not reports_absence(employment_type):
        return [(day, fraction, True) for day, fraction in days]
    budget = compass_paid_days or Decimal("0")
    planned: list[DayRow] = []
    for day, fraction in days:
        paid = fraction <= budget
        if paid:
            budget -= fraction
        planned.append((day, fraction, paid))
    return planned


async def _calendar_for(db: AsyncSession, rows: tuple[Mapping[str, Any], ...]):
    starts = [parse_date(row.get("start_date")) for row in rows]
    ends = [parse_date(row.get("end_date")) for row in rows]
    starts = [day for day in starts if day is not None]
    ends = [day for day in ends if day is not None]
    if not starts or not ends:
        return WorkCalendar()
    return await load_calendar(db, min(starts), max(ends))


async def _clashing_day(
    db: AsyncSession, *, user_id: int, request_id: uuid.UUID, days: list[date]
) -> Optional[date]:
    if not days:
        return None
    return await db.scalar(
        select(LeaveRequestDay.day)
        .where(
            LeaveRequestDay.user_id == user_id,
            LeaveRequestDay.active.is_(True),
            LeaveRequestDay.day.in_(days),
            LeaveRequestDay.leave_request_id != request_id,
        )
        .limit(1)
    )


async def _current_days(db: AsyncSession, request_id: uuid.UUID) -> list[tuple]:
    rows = await db.execute(
        select(
            LeaveRequestDay.day,
            LeaveRequestDay.fraction,
            LeaveRequestDay.paid,
            LeaveRequestDay.active,
        )
        .where(LeaveRequestDay.leave_request_id == request_id)
        .order_by(LeaveRequestDay.day)
    )
    return [tuple(row) for row in rows.all()]


async def _matches(
    db: AsyncSession, existing: LeaveRequest, fields: dict[str, Any], days: list
) -> bool:
    same_fields = all(getattr(existing, key) == value for key, value in fields.items())
    return same_fields and await _current_days(db, existing.id) == days


async def plan(db: AsyncSession, bundle: Bundle) -> ModulePlan:
    result = ImportPlan(module=MODULE)
    people = await load_people(db, bundle)
    mapping = await module_map(db, MODULE)
    rows = tuple(
        sorted(
            bundle.rows(TABLE),
            key=lambda row: (str(row.get("created_at") or ""), str(row.get("id"))),
        )
    )
    calendar = await _calendar_for(db, rows)
    #: Aktywne dni zaplanowane wcześniej w tej paczce: (osoba, dzień).
    claimed: set[tuple[int, date]] = set()

    for row in rows:
        sid = source_id(TABLE, row)
        request_id = parse_uuid(row.get("id"))
        if request_id is None:
            result.rows.append(RowPlan(sid, "skip", "wiersz bez id"))
            continue
        user_id = people.subject(row.get("user_id"))
        if user_id is None:
            result.rows.append(RowPlan(sid, "skip", NO_PROFILE))
            continue
        leave_type = row.get("leave_type")
        status = row.get("status")
        if leave_type not in LEAVE_TYPES:
            result.rows.append(RowPlan(sid, "skip", "nieznany rodzaj nieobecności"))
            continue
        if status not in LEAVE_STATUSES:
            result.rows.append(RowPlan(sid, "skip", "nieznany status wniosku"))
            continue
        start = parse_date(row.get("start_date"))
        end = parse_date(row.get("end_date"))
        if start is None or end is None or end < start:
            result.rows.append(RowPlan(sid, "skip", "wniosek bez poprawnych dat"))
            continue

        notes: list[str] = []
        half_day = row.get("half_day") if row.get("half_day") in HALF_DAYS else None
        if start != end:
            half_day = None
        decided_by = people.account(row.get("decided_by"))
        if decided_by is not None and decided_by == user_id:
            decided_by = None
            notes.append(SELF_DECISION)
        substitute = people.account(row.get("substitute_id"))
        if substitute == user_id:
            substitute = None
        if row.get("substitute_id") and substitute is None:
            notes.append("zastępca bez konta w NEXUSIE")
        consent = bool(row.get("forward_mail_enabled")) and substitute is not None
        created_by = people.account(row.get("created_by"))
        on_behalf = (
            bool(row.get("created_on_behalf"))
            or row.get("source") == "on_behalf"
            or (created_by is not None and created_by != user_id)
        )
        if consent and on_behalf:
            consent = False
            notes.append(FORWARD_ON_BEHALF)
        if row.get("documentation_url"):
            notes.append("załącznik zostaje w magazynie Compassa")

        profile = people.profile(user_id)
        employment_type = profile.employment_type if profile else None
        # D5: na B2B i zleceniu nieobecność to zgłoszenie — nikt jej nie
        # akceptuje, więc oczekujący wniosek z Compassa wchodzi jako przyjęty.
        reported = status == "pending" and reports_absence(employment_type)
        if reported:
            status = "approved"
            decided_by = None
            notes.append(REPORTED_FROM_PENDING)
        compass_paid = decimal(row.get("paid_days"))
        compass_unpaid = decimal(row.get("unpaid_days"))
        if (
            leave_type in POOL_TYPES
            and not pool_applies(employment_type)
            and (compass_paid or Decimal("0")) > 0
        ):
            notes.append(MANDATE_PAID_DROPPED)
        days = plan_request_days(
            calendar,
            start=start,
            end=end,
            half_day=half_day,
            leave_type=leave_type,
            employment_type=employment_type,
            compass_paid_days=compass_paid,
        )
        # ``paid_days`` / ``unpaid_days`` tak, jak liczy je NEXUS (jedna reguła).
        split = split_days(
            ((fraction, paid) for _, fraction, paid in days), leave_type=leave_type
        )
        paid_days, unpaid_days, total = split.paid, split.unpaid, split.total
        compass_total = (compass_paid or Decimal("0")) + (
            compass_unpaid or Decimal("0")
        )
        if not days:
            notes.append("wniosek bez dni roboczych")
        elif compass_total > 0 and compass_total != total:
            notes.append("liczba dni roboczych inna niż w Compassie")

        active = status in ACTIVE_STATUSES
        fields = {
            "user_id": user_id,
            "leave_type": leave_type,
            "status": status,
            "start_date": start,
            "end_date": end,
            "half_day": half_day,
            "note": text(row.get("note")),
            "substitute_user_id": substitute,
            "forward_mail_consent": consent,
            "oof_internal_message": text(row.get("oof_internal_message")),
            "oof_external_message": text(row.get("oof_external_message")),
            "paid_days": paid_days,
            "unpaid_days": unpaid_days,
            "decided_by": decided_by,
            "decided_at": parse_datetime(
                row.get("created_at") if reported else row.get("decided_at")
            )
            if status in ("approved", "rejected")
            else None,
            "decision_note": text(row.get("decision_note")),
            "created_by": created_by,
            "source": "compass_import",
        }
        payload = {
            "request_id": request_id,
            "fields": fields,
            "days": [(day, fraction, paid, active) for day, fraction, paid in days],
            "created_at": parse_datetime(row.get("created_at")),
        }

        existing = await db.get(LeaveRequest, request_id)
        if existing is not None and sid not in mapping:
            result.rows.append(
                RowPlan(sid, "conflict", "wniosek o tym id jest już w NEXUSIE", payload)
            )
            continue
        if existing is not None and await changed_in_nexus(
            db, mapping.get(sid), existing.updated_at
        ):
            if await _matches(db, existing, fields, payload["days"]):
                result.rows.append(RowPlan(sid, "unchanged", "", payload))
            else:
                result.rows.append(RowPlan(sid, "conflict", CHANGED_IN_NEXUS, payload))
            continue
        if active:
            day_list = [day for day, _, _ in days]
            in_bundle = any((user_id, day) in claimed for day in day_list)
            clash = await _clashing_day(
                db, user_id=user_id, request_id=request_id, days=day_list
            )
            if in_bundle or clash is not None:
                result.rows.append(RowPlan(sid, "conflict", OVERLAP, payload))
                continue
            claimed.update((user_id, day) for day in day_list)

        if reported:
            result.extra["contractor_pending_reported"] = (
                result.extra.get("contractor_pending_reported", 0) + 1
            )
        reason = join_notes(notes)
        if existing is None:
            result.rows.append(RowPlan(sid, "create", reason, payload))
            continue
        same = await _matches(db, existing, fields, payload["days"])
        action = "unchanged" if same else "update"
        result.rows.append(RowPlan(sid, action, reason, payload))
    return result


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {
        "requests_created": 0,
        "requests_updated": 0,
        "days_written": 0,
        "conflicts_at_write": 0,
    }
    for row in module_plan.rows:
        if row.action not in ("create", "update"):
            continue
        payload = row.payload
        request_id: uuid.UUID = payload["request_id"]
        try:
            async with db.begin_nested():
                if row.action == "create":
                    request = LeaveRequest(id=request_id, **payload["fields"])
                    if payload["created_at"] is not None:
                        request.created_at = payload["created_at"]
                    db.add(request)
                else:
                    request = await db.get(LeaveRequest, request_id)
                    for key, value in payload["fields"].items():
                        setattr(request, key, value)
                    await db.execute(
                        delete(LeaveRequestDay).where(
                            LeaveRequestDay.leave_request_id == request_id
                        )
                    )
                await db.flush()
                db.add_all(
                    LeaveRequestDay(
                        leave_request_id=request_id,
                        user_id=payload["fields"]["user_id"],
                        day=day,
                        fraction=fraction,
                        paid=paid,
                        active=active,
                    )
                    for day, fraction, paid, active in payload["days"]
                )
                await db.flush()
        except IntegrityError as exc:
            # Wyścig z wnioskiem złożonym między planem a zapisem: nakładka
            # to pozycja do decyzji, nie przerwany import.
            if ACTIVE_DAY_UNIQUE in str(exc.orig):
                written["conflicts_at_write"] += 1
                continue
            raise
        written[
            "requests_created" if row.action == "create" else "requests_updated"
        ] += 1
        written["days_written"] += len(payload["days"])
        await remember(
            db,
            module=MODULE,
            source_id=row.source_id,
            target_table="leave_requests",
            target_id=request_id,
            decision="auto",
            batch=batch,
        )
    await db.flush()
    return written
