"""Kontrola miesiąca: przebieg, zapis spraw, decyzje Finansów, widok (0784).

* ``run`` — przebieg pętli: reguła ``rules.evaluate`` na zamkniętych miesiącach
  (``collect.load_inputs``), zapis spraw do ``month_check_cases`` i liczników
  miesięcy do ``app_settings['month_check_last_run']``.
* Sprawa znaleziona drugi raz zostaje w swoim stanie (Finanse już ją widziały),
  dostaje bieżącą kwotę i faktury. Sprawa, której przebieg już nie znajduje,
  zamyka się sama (``closed``, bez autora) — tylko w miesiącu i rodzaju, które
  ten przebieg sprawdzał (``cost_without_sale`` i ``sale_without_cost`` dopiero
  po 15. dniu następnego miesiąca). Zamknięta sprawa, która wraca, jest znowu
  ``new``.
* ``decide`` — „Wyjaśnione” (z powodem), „Do korekty” i „Otwórz ponownie”.
* ``month_view`` — wiersze i podsumowanie miesiąca dla „Przebiegu miesiąca”.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.month_check_case import MonthCheckCase
from app.models.user import User
from app.services.month_check import collect, rules

logger = logging.getLogger(__name__)

RUN_KEY = "month_check_last_run"
NEW, TO_CORRECT, EXPLAINED, CLOSED = "new", "to_correct", "explained", "closed"
OPEN_STATES = (NEW, TO_CORRECT)
REASON_MAX = 1000

KIND_LABELS = {
    rules.HOURS_MISMATCH: "Inne godziny u klienta i u konsultanta",
    rules.COST_WITHOUT_SALE: "Konsultant zafakturował, klient nie",
    rules.SALE_WITHOUT_COST: "Klient zafakturowany, brak faktury konsultanta",
    rules.OVER_WORKING_DAYS: "Więcej godzin niż dni roboczych",
}
ISSUE_LABELS = {rules.NO_CONTRACT: "brak kontraktu", rules.NO_ORDER: "brak zamówienia"}


class MonthCheckError(Exception):
    """Odmowa z komunikatem dla człowieka (trasa zamienia na 404/409)."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _evaluated(finding_kind: str, month: str, today: date) -> bool:
    if finding_kind in rules.DEADLINE_KINDS:
        return today > rules.deadline(month)
    return True


async def save(
    db: AsyncSession,
    result: rules.Result,
    months: list[str],
    today: date,
    now: datetime,
) -> dict[str, int]:
    """Zapis spraw przebiegu; zwraca liczniki (nowe, odświeżone, zamknięte, wróciły)."""

    rows = {
        r.case_key: r
        for r in (
            await db.scalars(
                select(MonthCheckCase).where(MonthCheckCase.period_month.in_(months))
            )
        ).all()
    }
    counts = {"new": 0, "updated": 0, "closed": 0, "reopened": 0}
    seen: set[str] = set()
    for f in result.findings:
        seen.add(f.key)
        row = rows.get(f.key)
        if row is None:
            db.add(
                MonthCheckCase(
                    case_key=f.key,
                    kind=f.kind,
                    period_month=f.month,
                    candidate_id=f.candidate_id,
                    contract_id=f.contract_id,
                    client_id=f.client_id,
                    amount=f.amount,
                    currency=f.currency,
                    data_issue=f.data_issue,
                    details=f.details,
                    state=NEW,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            counts["new"] += 1
            continue
        row.contract_id = f.contract_id
        row.client_id = f.client_id
        row.amount = f.amount
        row.currency = f.currency
        row.data_issue = f.data_issue
        row.details = f.details
        row.last_seen_at = now
        if row.state == CLOSED:
            row.state = NEW
            row.closed_at = None
            row.first_seen_at = now
            row.reason = None
            row.decided_by = None
            row.decided_at = None
            counts["reopened"] += 1
        else:
            counts["updated"] += 1
    for key, row in rows.items():
        if key in seen or row.state == CLOSED:
            continue
        if not _evaluated(row.kind, row.period_month, today):
            continue
        row.state = CLOSED
        row.closed_at = now
        counts["closed"] += 1
    return counts


async def _store_run(
    db: AsyncSession, result: rules.Result, raw: dict[str, Any], now: datetime
) -> None:
    previous = await db.get(AppSetting, RUN_KEY)
    stats = dict((previous.value or {}).get("months", {})) if previous else {}
    for month, st in result.stats.items():
        stats[month] = st.as_dict()
    value = {"executed_at": now.isoformat(), "months": stats, "raw": raw}
    stmt = pg_insert(AppSetting).values(key=RUN_KEY, value=value)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key], set_={"value": stmt.excluded.value}
        )
    )


async def run(
    db: AsyncSession, today: date, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Jeden przebieg kontroli dla trzech zamkniętych miesięcy (commit tutaj)."""

    moment = now or datetime.now(timezone.utc)
    months = rules.closed_months(today)
    data, raw = await collect.load_inputs(db, today, months)
    result = rules.evaluate(data)
    counts = await save(db, result, months, today, moment)
    await _store_run(db, result, raw, moment)
    await db.commit()
    return {
        "months": months,
        "findings": len(result.findings),
        **counts,
    }


# ── Decyzje Finansów ─────────────────────────────────────────────────────────


async def decide(
    db: AsyncSession,
    case_id: int,
    action: str,
    user: User,
    *,
    reason: Optional[str] = None,
    now: Optional[datetime] = None,
) -> MonthCheckCase:
    row = await db.get(MonthCheckCase, case_id)
    if row is None:
        raise MonthCheckError("Nie ma takiej sprawy.", 404)
    text = " ".join((reason or "").split())[:REASON_MAX]
    if action == EXPLAINED:
        if len(text) < 3:
            raise MonthCheckError("Wpisz, dlaczego to się zgadza.", 422)
        row.state = EXPLAINED
        row.reason = text
    elif action == TO_CORRECT:
        row.state = TO_CORRECT
        row.reason = text or None
    elif action == NEW:
        if row.state == CLOSED:
            raise MonthCheckError(
                "Zamkniętej sprawy nie otwiera się ręcznie — wróci sama, jeśli rozbieżność się powtórzy."
            )
        row.state = NEW
        row.reason = None
    else:  # pragma: no cover — trasa waliduje akcję
        raise MonthCheckError("Nieznana akcja.", 422)
    row.decided_by = user.id
    row.decided_at = now or datetime.now(timezone.utc)
    await db.flush()
    return row


# ── Widok ────────────────────────────────────────────────────────────────────


def _money(value: Optional[Decimal], amounts: bool) -> Optional[str]:
    if not amounts or value is None:
        return None
    return str(value)


def _details(details: dict[str, Any], amounts: bool) -> dict[str, Any]:
    if amounts:
        return details
    hidden = {"client_net", "contractor_net", "expected_cost", "cost_rate"}
    out = {k: v for k, v in details.items() if k not in hidden}
    if "contractor_invoices" in out:
        out["contractor_invoices"] = [
            {k: v for k, v in d.items() if k != "net"}
            for d in out["contractor_invoices"]
        ]
    return out


async def names(
    db: AsyncSession, rows: list[MonthCheckCase]
) -> tuple[dict[int, str], dict[int, str]]:
    people = {r.candidate_id for r in rows}
    clients = {r.client_id for r in rows if r.client_id}
    person = {
        int(i): f"{a or ''} {b or ''}".strip()
        for i, a, b in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_(people or {0})
                )
            )
        ).all()
    }
    client = {
        int(i): (d or n or "")
        for i, d, n in (
            await db.execute(
                select(Client.id, Client.display_name, Client.name).where(
                    Client.id.in_(clients or {0})
                )
            )
        ).all()
    }
    return person, client


def case_dict(
    row: MonthCheckCase,
    person: dict[int, str],
    client: dict[int, str],
    *,
    amounts: bool,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "kind_label": KIND_LABELS.get(row.kind, row.kind),
        "month": row.period_month,
        "candidate_id": row.candidate_id,
        "person": person.get(row.candidate_id, ""),
        "contract_id": row.contract_id,
        "client_id": row.client_id,
        "client": client.get(row.client_id, "") if row.client_id else "",
        "amount": _money(row.amount, amounts),
        "currency": row.currency,
        "data_issue": row.data_issue,
        "data_issue_label": ISSUE_LABELS.get(row.data_issue or ""),
        "details": _details(row.details or {}, amounts),
        "state": row.state,
        "reason": row.reason,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }


async def last_run(db: AsyncSession) -> dict[str, Any]:
    stored = await db.get(AppSetting, RUN_KEY)
    return dict(stored.value or {}) if stored else {}


def summary(
    rows: list[MonthCheckCase], stats: Optional[dict[str, Any]], *, amounts: bool
) -> dict[str, Any]:
    """Podsumowanie miesiąca: zgodne osobo-miesiące, sprawy, kwota, co otwarte."""

    open_rows = [r for r in rows if r.state in OPEN_STATES]
    by_state = {
        s: sum(1 for r in rows if r.state == s)
        for s in (NEW, TO_CORRECT, EXPLAINED, CLOSED)
    }

    def total(items: list[MonthCheckCase]) -> Optional[str]:
        if not amounts:
            return None
        return str(
            sum((abs(r.amount) for r in items if r.amount is not None), Decimal(0))
        )

    live = [r for r in rows if r.state != CLOSED]
    return {
        "person_months": (stats or {}).get("person_months"),
        "matched": (stats or {}).get("matched"),
        "skipped": (stats or {}).get("skipped", {}),
        "overtime_confirmed": (stats or {}).get("overtime_confirmed"),
        "cases": len(live),
        "cases_amount": total(live),
        "open": len(open_rows),
        "open_amount": total(open_rows),
        "by_state": by_state,
        "by_kind": {k: sum(1 for r in live if r.kind == k) for k in rules.KINDS},
    }


async def month_view(
    db: AsyncSession, month: str, *, amounts: bool, today: date
) -> dict[str, Any]:
    rows = list(
        (
            await db.scalars(
                select(MonthCheckCase)
                .where(MonthCheckCase.period_month == month)
                .order_by(MonthCheckCase.state, MonthCheckCase.kind, MonthCheckCase.id)
            )
        ).all()
    )
    person, client = await names(db, rows)
    run_info = await last_run(db)
    stats = (run_info.get("months") or {}).get(month)
    order = {NEW: 0, TO_CORRECT: 1, EXPLAINED: 2, CLOSED: 3}
    rows.sort(
        key=lambda r: (
            order.get(r.state, 9),
            -(abs(r.amount) if r.amount is not None else Decimal(0)),
            r.id,
        )
    )
    return {
        "month": month,
        "checked_at": run_info.get("executed_at") if stats else None,
        "waits_until": rules.deadline(month).isoformat()
        if today <= rules.deadline(month)
        else None,
        "summary": summary(rows, stats, amounts=amounts),
        "cases": [case_dict(r, person, client, amounts=amounts) for r in rows],
        "amounts": amounts,
    }
