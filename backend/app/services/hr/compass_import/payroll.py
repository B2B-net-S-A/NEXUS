"""Import stawek i premii z Compassa (``user_rates``, ``bonuses``).

Reguły:

* ``user_rates`` → ``employee_rates`` (historia z ``effective_to``,
  ``compass_id``). Dwie otwarte stawki jednej osoby (Compass domykał
  poprzednią wyzwalaczem, którego nie widać w kodzie) — starsza zostaje
  domknięta dniem przed kolejną. Osoba, której historię stawek prowadzi już
  NEXUS (stawka bez ``compass_id``), dostaje „conflict” zamiast mieszania.
* ``bonuses`` → ``hr_bonuses`` (``source = 'compass_import'``, ``compass_id``,
  ``source_key = 'compass:<uuid>'``). Status ``assigned``/``cancelled`` bez
  zmian (dawne ``pending`` → ``proposed``, ``paid`` → ``assigned``),
  ``champions_league`` → ``league`` (premia kwartalna dostaje miesiąc końca
  kwartału). Nikt nie proponuje ani nie przyznaje premii sobie: taki
  ``proposed_by`` jest pomijany (CHECK-i ``hr_bonuses``).
* raport niesie liczby wierszy, w tym liczbę wierszy per waluta — nigdy kwot.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_ops import HrImportBatch
from app.models.hr_payroll import EmployeeRate, HrBonus
from app.services.hr_payroll_schema import (
    BONUS_MAX,
    CURRENCIES,
    RATE_MAX,
    REASON_MAX_LENGTH,
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
    parse_date,
    parse_datetime,
    parse_uuid,
    small_int,
    source_id,
    text,
)
from .core import ModulePlan, RowPlan, remember

MODULE = "payroll"
RATES = "user_rates"
BONUSES = "bonuses"

SELF_PROPOSED = "premia zaproponowana samemu sobie — proponujący pominięty"
CATEGORY_MAP: dict[str, str] = {
    "sales": "sales",
    "delivery_lead": "delivery_lead",
    "recruiter": "recruiter",
    "custom": "custom",
    "champions_league": "league",
}
STATUS_MAP: dict[str, str] = {
    "assigned": "assigned",
    "cancelled": "cancelled",
    "pending": "proposed",
    "paid": "assigned",
}
#: Pola premii z Compassa zapisywane w ``rule_snapshot`` (reguła i liczby źródła).
SNAPSHOT_FIELDS = (
    "category",
    "client_name",
    "sales_client_name",
    "sales_service_description",
    "delivery_candidate_name",
    "delivery_margin_amount",
    "delivery_margin_percent",
    "recruiter_candidate_name",
    "recruiter_margin_per_hour",
    "recruiter_calculated_tier",
    "period_quarter",
    "place_rank",
    "custom_email_memo",
    "notes",
)


def _rates_by_user(
    rows: tuple[Mapping[str, Any], ...], people: People
) -> dict[int, list[Mapping[str, Any]]]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        user_id = people.subject(row.get("user_id"))
        effective_from = parse_date(row.get("effective_from"))
        # Stawka nie od 1. dnia nie wchodzi do łańcucha (idzie do decyzji).
        if (
            user_id is not None
            and effective_from is not None
            and effective_from.day == 1
        ):
            grouped[user_id].append(row)
    for items in grouped.values():
        items.sort(key=lambda item: str(item.get("effective_from") or ""))
    return grouped


async def _plan_rates(
    db: AsyncSession, bundle: Bundle, people: People, result: ImportPlan
) -> None:
    rows = bundle.rows(RATES)
    by_user = _rates_by_user(rows, people)
    #: Domknięcie starszej otwartej stawki dniem przed kolejną.
    closing: dict[str, Any] = {}
    for items in by_user.values():
        for current, following in zip(items, items[1:]):
            next_from = parse_date(following.get("effective_from"))
            if current.get("effective_to") in (None, "") and next_from is not None:
                closing[str(current.get("id"))] = next_from - timedelta(days=1)

    manual_users = set(
        await db.scalars(
            select(EmployeeRate.user_id).where(EmployeeRate.compass_id.is_(None))
        )
    )
    claimed_from: set[tuple[int, Any]] = set()
    claimed_open: set[int] = set()
    for row in rows:
        sid = source_id(RATES, row)
        compass_id = parse_uuid(row.get("id"))
        user_id = people.subject(row.get("user_id"))
        if compass_id is None:
            result.rows.append(RowPlan(sid, "skip", "wiersz bez id"))
            continue
        if user_id is None:
            result.rows.append(RowPlan(sid, "skip", NO_PROFILE))
            continue
        rate = decimal(row.get("hourly_rate"))
        currency = row.get("currency")
        if rate is None or not Decimal("0") <= rate <= Decimal(RATE_MAX):
            result.rows.append(RowPlan(sid, "skip", "stawka poza zakresem"))
            continue
        if currency not in CURRENCIES:
            result.rows.append(RowPlan(sid, "skip", "nieznana waluta"))
            continue
        effective_from = parse_date(row.get("effective_from"))
        if effective_from is None or effective_from.day != 1:
            result.rows.append(
                RowPlan(sid, "conflict", "stawka nie od 1. dnia miesiąca")
            )
            continue
        notes: list[str] = []
        effective_to = parse_date(row.get("effective_to"))
        if effective_to is None and str(row.get("id")) in closing:
            effective_to = closing[str(row.get("id"))]
            notes.append("druga otwarta stawka — domknięta przed kolejną")
        if effective_to is not None and effective_to < effective_from:
            result.rows.append(
                RowPlan(sid, "conflict", "stawka kończy się przed startem")
            )
            continue
        values = {
            "hourly_rate": rate.quantize(Decimal("0.01")),
            "currency": currency,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "reason": text(row.get("reason"), REASON_MAX_LENGTH),
            "set_by": people.account(row.get("set_by")),
        }
        payload = {"user_id": user_id, "compass_id": compass_id, "values": values}
        reason = join_notes(notes)
        existing = await db.scalar(
            select(EmployeeRate).where(EmployeeRate.compass_id == compass_id)
        )
        if existing is not None:
            payload["rate_id"] = existing.id
            action = "update" if changed_fields(existing, values) else "unchanged"
            result.rows.append(RowPlan(sid, action, reason, payload))
            continue
        if user_id in manual_users:
            result.rows.append(
                RowPlan(sid, "conflict", "historia stawek prowadzona już w NEXUSIE")
            )
            continue
        taken_from = (user_id, effective_from) in claimed_from or (
            await db.scalar(
                select(EmployeeRate.id).where(
                    EmployeeRate.user_id == user_id,
                    EmployeeRate.effective_from == effective_from,
                )
            )
        ) is not None
        if taken_from:
            result.rows.append(
                RowPlan(sid, "conflict", "dwie stawki od tego samego dnia")
            )
            continue
        if effective_to is None:
            open_in_db = await db.scalar(
                select(EmployeeRate.id).where(
                    EmployeeRate.user_id == user_id, EmployeeRate.effective_to.is_(None)
                )
            )
            if user_id in claimed_open or open_in_db is not None:
                result.rows.append(RowPlan(sid, "conflict", "druga otwarta stawka"))
                continue
            claimed_open.add(user_id)
        claimed_from.add((user_id, effective_from))
        result.rows.append(RowPlan(sid, "create", reason, payload))


def _snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = {
        key: row.get(key) for key in SNAPSHOT_FIELDS if row.get(key) not in (None, "")
    }
    return {"compass": snapshot}


async def _plan_bonuses(
    db: AsyncSession, bundle: Bundle, people: People, result: ImportPlan
) -> None:
    for row in bundle.rows(BONUSES):
        sid = source_id(BONUSES, row)
        compass_id = parse_uuid(row.get("id"))
        if compass_id is None:
            result.rows.append(RowPlan(sid, "skip", "wiersz bez id"))
            continue
        recipient = people.subject(row.get("recipient_user_id"))
        if recipient is None:
            result.rows.append(RowPlan(sid, "skip", NO_PROFILE))
            continue
        amount = decimal(row.get("amount"))
        if amount is None or not Decimal("0") < amount <= Decimal(BONUS_MAX):
            result.rows.append(RowPlan(sid, "skip", "kwota premii poza zakresem"))
            continue
        currency = row.get("currency")
        if currency not in CURRENCIES:
            result.rows.append(RowPlan(sid, "skip", "nieznana waluta"))
            continue
        category = CATEGORY_MAP.get(str(row.get("category")))
        status = STATUS_MAP.get(str(row.get("status")))
        if category is None:
            result.rows.append(RowPlan(sid, "skip", "nieznana kategoria premii"))
            continue
        if status is None:
            result.rows.append(RowPlan(sid, "skip", "nieznany status premii"))
            continue
        notes: list[str] = []
        if row.get("status") == "paid":
            notes.append("premia wypłacona — przyznana")
        year = small_int(row.get("period_year"))
        month = small_int(row.get("period_month"))
        quarter = small_int(row.get("period_quarter"))
        if month is None and quarter is not None and 1 <= quarter <= 4:
            month = quarter * 3
            notes.append("premia kwartalna — miesiąc końca kwartału")
        if (
            year is None
            or month is None
            or not (2020 <= year <= 2100 and 1 <= month <= 12)
        ):
            result.rows.append(RowPlan(sid, "skip", "premia bez okresu"))
            continue
        proposed_by = people.account(row.get("proposed_by"))
        if proposed_by is not None and proposed_by == recipient:
            proposed_by = None
            notes.append(SELF_PROPOSED)
        created_at = parse_datetime(row.get("created_at"))
        cancelled = status == "cancelled"
        values = {
            "recipient_user_id": recipient,
            "proposed_by": proposed_by,
            "amount": amount.quantize(Decimal("0.01")),
            "currency": currency,
            "category": category,
            "period_year": year,
            "period_month": month,
            "status": status,
            "source": "compass_import",
            "source_key": f"compass:{compass_id}",
            "rule_snapshot": _snapshot(row),
            "description": text(row.get("reason"), 1000),
            "assigned_by": proposed_by if status == "assigned" else None,
            "assigned_at": created_at if status == "assigned" else None,
            "cancelled_by": people.account(row.get("cancelled_by"))
            if cancelled
            else None,
            "cancelled_at": parse_datetime(row.get("cancelled_at"))
            if cancelled
            else None,
            "cancel_reason": "manual" if cancelled else None,
            "cancel_note": text(row.get("cancellation_reason")) if cancelled else None,
        }
        if status == "assigned" and values["assigned_at"] is None:
            result.rows.append(RowPlan(sid, "skip", "premia bez daty przyznania"))
            continue
        payload = {"compass_id": compass_id, "values": values, "created_at": created_at}
        reason = join_notes(notes)
        existing = await db.scalar(
            select(HrBonus).where(
                (HrBonus.compass_id == compass_id)
                | (HrBonus.source_key == values["source_key"])
            )
        )
        if existing is None:
            result.rows.append(RowPlan(sid, "create", reason, payload))
            continue
        payload["bonus_id"] = existing.id
        action = "update" if changed_fields(existing, values) else "unchanged"
        result.rows.append(RowPlan(sid, action, reason, payload))


async def plan(db: AsyncSession, bundle: Bundle) -> ModulePlan:
    result = ImportPlan(module=MODULE)
    people = await load_people(db, bundle)
    await _plan_rates(db, bundle, people, result)
    await _plan_bonuses(db, bundle, people, result)
    # Suma kontrolna dla porównania z Compassem: wiersze per waluta, bez kwot.
    for table, key in (
        (RATES, "rate_rows_per_currency"),
        (BONUSES, "bonus_rows_per_currency"),
    ):
        result.extra[key] = dict(
            Counter(
                row.payload["values"]["currency"]
                for row in result.rows
                if row.source_id.startswith(f"{table}:")
                and row.action in ("create", "update", "unchanged")
            )
        )
    return result


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {"rates_written": 0, "bonuses_written": 0}
    for row in module_plan.rows:
        if row.action not in ("create", "update"):
            continue
        payload = row.payload
        if row.source_id.startswith(f"{RATES}:"):
            if row.action == "create":
                rate = EmployeeRate(
                    user_id=payload["user_id"],
                    compass_id=payload["compass_id"],
                    **payload["values"],
                )
                db.add(rate)
            else:
                rate = await db.get(EmployeeRate, payload["rate_id"])
                for key, value in payload["values"].items():
                    setattr(rate, key, value)
            await db.flush()
            written["rates_written"] += 1
            target_table, target_id = "employee_rates", rate.id
        else:
            if row.action == "create":
                bonus = HrBonus(compass_id=payload["compass_id"], **payload["values"])
                if payload["created_at"] is not None:
                    bonus.created_at = payload["created_at"]
                db.add(bonus)
            else:
                bonus = await db.get(HrBonus, payload["bonus_id"])
                for key, value in payload["values"].items():
                    setattr(bonus, key, value)
            await db.flush()
            written["bonuses_written"] += 1
            target_table, target_id = "hr_bonuses", bonus.id
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
