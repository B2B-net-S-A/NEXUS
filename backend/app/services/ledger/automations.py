"""Automaty księgi (K3a): PK cykliczne i RMK — wzory, raty, dokumenty miesiąca.

Plan „Księgowość w NEXUSIE” (13.11.2026): ręczne polecenia księgowania
(najem, abonamenty, polisy) znikają, bo NEXUS robi je sam co miesiąc.

* **PK cykliczne**: wzór (pozycje dekretu w groszach, MPK, kontrahent) i zakres
  miesięcy; co miesiąc jeden PK ze źródłem ``ledger_recurring`` /
  ``<id>:RRRR-MM`` w ostatnim dniu miesiąca.
* **RMK** (rozliczenia międzyokresowe kosztów czynne, np. polisy opłacone
  z góry): kwota całkowita w ``months`` ratach od pierwszego miesiąca; rata =
  kwota // liczba miesięcy, ostatnia = reszta (suma rat = kwota). PK Wn konto
  kosztu (MPK) / Ma konto RMK, źródło ``ledger_prepayment`` / ``<id>:RRRR-MM``.
* **Zatwierdzona przeszłość jest nietykalna**: wzoru ani RMK z zatwierdzonym
  miesiącem nie zmienia się i nie usuwa (409) — zmiana kwoty przerobiłaby
  zamknięte miesiące na problemy do storna. Wzór kończy się datą
  (``end_month`` nie wcześniej niż ostatni zatwierdzony miesiąc), nowa kwota =
  nowy wzór od następnego miesiąca. Szkice księgowanie miesiąca przebudowuje
  samo (maszyna „Źródeł”).
* Wzory i RMK zakłada lista „Księgowi” albo admin (bramka w trasie).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.ledger import (
    LedgerDocument,
    LedgerPeriod,
    LedgerPrepayment,
    LedgerRecurring,
)
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import documents, engine
from app.services.ledger.documents import DocumentSpec
from app.services.ledger.engine import LineIn
from app.services.ledger_automation_schema import (
    MONTHS_MAX,
    NAME_MAX,
    RECURRING_LINES_MAX,
    REFERENCE_MAX,
)
from app.services.ledger_schema import DESCRIPTION_MAX

RECURRING_SOURCE = "ledger_recurring"
PREPAYMENT_SOURCE = "ledger_prepayment"
LOCKED = (
    "{what} ma zatwierdzone miesiące w dzienniku — nie zmienia się go ani nie usuwa. "
    "Zakończ go datą i załóż nowy od następnego miesiąca."
)


# ── Harmonogram (bez bazy) ───────────────────────────────────────────────────


def first_of(day: date) -> date:
    return date(day.year, day.month, 1)


def month_index(start: date, month: date) -> int:
    return (month.year - start.year) * 12 + month.month - start.month


def last_day(month: date) -> date:
    return date(month.year, month.month, monthrange(month.year, month.month)[1])


def installment(total: int, months: int, number: int) -> int:
    """Rata ``number`` (1…months): równa część, ostatnia = reszta."""

    base = total // months
    return total - base * (months - 1) if number == months else base


def month_key(source_id: int, month: date) -> str:
    return f"{source_id}:{month.year}-{month.month:02d}"


def recurring_spec(template: LedgerRecurring, month: date) -> Optional[DocumentSpec]:
    if not template.active or month < template.start_month:
        return None
    if template.end_month is not None and month > template.end_month:
        return None
    lines = [
        LineIn(
            side=str(item.get("side")),
            account=str(item.get("account") or ""),
            amount=int(item.get("amount") or 0),
            mpk=item.get("mpk") or None,
            counterparty_id=item.get("counterparty_id") or None,
            description=str(item.get("description") or ""),
        )
        for item in template.lines or []
    ]
    end = last_day(month)
    return DocumentSpec(
        doc_type="PK",
        op_date=end,
        doc_date=end,
        lines=lines,
        description=(template.description or template.name)[:DESCRIPTION_MAX],
        source_type=RECURRING_SOURCE,
        source_id=month_key(template.id, month),
        meta={"source": "recurring", "template": template.id},
    )


def prepayment_spec(item: LedgerPrepayment, month: date) -> Optional[DocumentSpec]:
    number = month_index(item.start_month, month) + 1
    if not item.active or not 1 <= number <= item.months:
        return None
    amount = installment(item.total_amount, item.months, number)
    if amount == 0:
        return None
    end = last_day(month)
    reference = f" ({item.reference})" if item.reference else ""
    text = f"{item.name}{reference} — rata {number}/{item.months}"
    return DocumentSpec(
        doc_type="PK",
        op_date=end,
        doc_date=end,
        lines=[
            LineIn(
                side="debit",
                account=item.cost_account,
                amount=amount,
                mpk=item.mpk,
                description=text[:120],
            ),
            LineIn(
                side="credit",
                account=item.prepaid_account,
                amount=amount,
                counterparty_id=item.counterparty_id,
                description=text[:120],
            ),
        ],
        description=text[:DESCRIPTION_MAX],
        counterparty_id=item.counterparty_id,
        source_type=PREPAYMENT_SOURCE,
        source_id=month_key(item.id, month),
        meta={"source": "prepayment", "prepayment": item.id, "installment": number},
    )


# ── Odczyt ───────────────────────────────────────────────────────────────────


async def _posted(db: AsyncSession, source_type: str) -> dict[int, dict[str, Any]]:
    """Zaksięgowane miesiące per wzór: liczba szkiców, zatwierdzonych, ostatni zatw."""

    rows = await db.execute(
        select(
            LedgerDocument.source_id,
            LedgerDocument.status,
            LedgerPeriod.month,
            func.extract("year", LedgerDocument.op_date),
        )
        .join(LedgerPeriod, LedgerPeriod.id == LedgerDocument.period_id)
        .where(
            LedgerDocument.source_type == source_type,
            LedgerDocument.reversed_by_id.is_(None),
        )
    )
    out: dict[int, dict[str, Any]] = {}
    for source_id, status, month, year in rows.all():
        owner = int(str(source_id).split(":", 1)[0])
        item = out.setdefault(owner, {"draft": 0, "approved": 0, "last_approved": None})
        item[status] = item.get(status, 0) + 1
        if status == "approved":
            day = date(int(year), int(month), 1)
            if item["last_approved"] is None or day > item["last_approved"]:
                item["last_approved"] = day
    return out


def _month_text(day: Optional[date]) -> Optional[str]:
    return f"{day.year}-{day.month:02d}" if day else None


async def overview(db: AsyncSession) -> dict[str, Any]:
    recurring = (
        await db.scalars(select(LedgerRecurring).order_by(LedgerRecurring.name))
    ).all()
    prepayments = (
        await db.scalars(
            select(LedgerPrepayment).order_by(LedgerPrepayment.start_month)
        )
    ).all()
    posted_r = await _posted(db, RECURRING_SOURCE)
    posted_p = await _posted(db, PREPAYMENT_SOURCE)
    names = dict(
        (
            await db.execute(
                select(FinanceCounterparty.id, FinanceCounterparty.name).where(
                    FinanceCounterparty.id.in_(
                        {p.counterparty_id for p in prepayments if p.counterparty_id}
                        or {0}
                    )
                )
            )
        ).all()
    )
    empty = {"draft": 0, "approved": 0, "last_approved": None}
    return {
        "recurring": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "lines": t.lines,
                "total": sum(
                    int(i.get("amount") or 0)
                    for i in t.lines
                    if i.get("side") == "debit"
                ),
                "start_month": _month_text(t.start_month),
                "end_month": _month_text(t.end_month),
                "active": t.active,
                "draft": posted_r.get(t.id, empty)["draft"],
                "approved": posted_r.get(t.id, empty)["approved"],
                "last_approved": _month_text(
                    posted_r.get(t.id, empty)["last_approved"]
                ),
            }
            for t in recurring
        ],
        "prepayments": [
            {
                "id": p.id,
                "name": p.name,
                "reference": p.reference,
                "counterparty": (
                    {"id": p.counterparty_id, "name": names.get(p.counterparty_id)}
                    if p.counterparty_id
                    else None
                ),
                "cost_account": p.cost_account,
                "prepaid_account": p.prepaid_account,
                "mpk": p.mpk,
                "total_amount": p.total_amount,
                "start_month": _month_text(p.start_month),
                "months": p.months,
                "installment": installment(p.total_amount, p.months, 1),
                "active": p.active,
                "draft": posted_p.get(p.id, empty)["draft"],
                "approved": posted_p.get(p.id, empty)["approved"],
                "last_approved": _month_text(
                    posted_p.get(p.id, empty)["last_approved"]
                ),
            }
            for p in prepayments
        ],
    }


# ── Zapis (bez commita; bramka lista „Księgowi” w trasie) ────────────────────


def _clean_name(raw: str, label: str = "Nazwa") -> str:
    value = " ".join((raw or "").split())
    if not value:
        raise LedgerError(f"{label}: podaj nazwę.", status=422)
    return value[:NAME_MAX]


def _month(raw: Optional[date], label: str) -> Optional[date]:
    return first_of(raw) if raw else None


async def _clean_lines(
    db: AsyncSession, raw: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(raw) > RECURRING_LINES_MAX:
        raise LedgerError(
            f"Wzór ma najwyżej {RECURRING_LINES_MAX} pozycji.", status=422
        )
    lines = [engine.clean_line(item, index) for index, item in enumerate(raw, start=1)]
    plan = await documents.load_plan(db)
    engine.ensure_valid(lines, plan)
    for line in lines:
        if line.counterparty_id is not None:
            await documents._counterparty_exists(db, line.counterparty_id)
    return [
        {
            "side": line.side,
            "account": line.account,
            "amount": line.amount,
            "mpk": line.mpk,
            "counterparty_id": line.counterparty_id,
            "description": line.description,
        }
        for line in lines
    ]


async def _locked(db: AsyncSession, source_type: str, owner_id: int) -> Optional[date]:
    """Ostatni zatwierdzony miesiąc wzoru (``None`` = nic zatwierdzonego)."""

    return (await _posted(db, source_type)).get(owner_id, {}).get("last_approved")


async def save_recurring(
    db: AsyncSession,
    values: dict[str, Any],
    *,
    actor_id: int,
    template_id: Optional[int] = None,
) -> LedgerRecurring:
    if template_id is None:
        template = LedgerRecurring(created_by=actor_id)
        db.add(template)
        last_approved = None
    else:
        template = await db.get(LedgerRecurring, template_id, with_for_update=True)
        if template is None:
            raise LedgerError("Nie ma takiego wzoru.", status=404)
        last_approved = await _locked(db, RECURRING_SOURCE, template.id)
    # Klucze podane w żądaniu (``end_month: null`` czyści datę końca).
    changes = set(values)
    if last_approved is not None and changes - {"end_month"}:
        raise LedgerError(LOCKED.format(what="Wzór"), status=409)
    if "name" in changes or template_id is None:
        template.name = _clean_name(values.get("name") or "")
    if "description" in changes:
        template.description = " ".join((values["description"] or "").split())[
            :DESCRIPTION_MAX
        ]
    if "lines" in changes or template_id is None:
        template.lines = await _clean_lines(db, values.get("lines") or [])
    if "start_month" in changes or template_id is None:
        start = _month(values.get("start_month"), "Pierwszy miesiąc")
        if start is None:
            raise LedgerError("Podaj pierwszy miesiąc wzoru.", status=422)
        template.start_month = start
    if "end_month" in changes:
        end = _month(values["end_month"], "Ostatni miesiąc")
        if last_approved is not None and end is not None and end < last_approved:
            raise LedgerError(
                "Ostatni miesiąc nie może być wcześniejszy niż ostatni zatwierdzony "
                f"({last_approved.month:02d}.{last_approved.year}).",
                status=409,
            )
        template.end_month = end
    if template.end_month is not None and template.end_month < template.start_month:
        raise LedgerError("Ostatni miesiąc jest przed pierwszym.", status=422)
    await db.flush()
    return template


async def save_prepayment(
    db: AsyncSession,
    values: dict[str, Any],
    *,
    actor_id: int,
    item_id: Optional[int] = None,
) -> LedgerPrepayment:
    if item_id is None:
        item = LedgerPrepayment(created_by=actor_id)
        db.add(item)
    else:
        item = await db.get(LedgerPrepayment, item_id, with_for_update=True)
        if item is None:
            raise LedgerError("Nie ma takiego rozliczenia RMK.", status=404)
        if await _locked(db, PREPAYMENT_SOURCE, item.id) is not None:
            raise LedgerError(LOCKED.format(what="Rozliczenie RMK"), status=409)
    plan = await documents.load_plan(db)
    item.name = _clean_name(values.get("name") or "")
    item.reference = " ".join((values.get("reference") or "").split())[:REFERENCE_MAX]
    for key, label in (
        ("cost_account", "Konto kosztu"),
        ("prepaid_account", "Konto RMK"),
    ):
        number = engine.clean_line(
            {"side": "debit", "account": values.get(key), "amount": 1}, 1
        ).account
        resolved, problem = engine.resolve(number, plan)
        if resolved is None:
            raise LedgerError(f"{label}: {problem}", status=422)
        setattr(item, key, number)
    item.mpk = (values.get("mpk") or "").strip()[:16] or None
    item.counterparty_id = values.get("counterparty_id") or None
    await documents._counterparty_exists(db, item.counterparty_id)
    total = int(values.get("total_amount") or 0)
    if total <= 0:
        raise LedgerError("Kwota RMK musi być większa od zera.", status=422)
    months = int(values.get("months") or 0)
    if not 1 <= months <= MONTHS_MAX:
        raise LedgerError(f"Liczba miesięcy: od 1 do {MONTHS_MAX}.", status=422)
    start = _month(values.get("start_month"), "Pierwszy miesiąc")
    if start is None:
        raise LedgerError("Podaj pierwszy miesiąc rozliczenia.", status=422)
    item.total_amount, item.months, item.start_month = total, months, start
    await db.flush()
    return item


async def remove(db: AsyncSession, kind: str, owner_id: int) -> None:
    """Usunięcie wzoru albo RMK (bez commita) — tylko bez zatwierdzonych miesięcy."""

    model, source, what = (
        (LedgerRecurring, RECURRING_SOURCE, "Wzór")
        if kind == "recurring"
        else (LedgerPrepayment, PREPAYMENT_SOURCE, "Rozliczenie RMK")
    )
    row = await db.get(model, owner_id, with_for_update=True)
    if row is None:
        raise LedgerError("Nie ma takiej pozycji.", status=404)
    if await _locked(db, source, owner_id) is not None:
        raise LedgerError(LOCKED.format(what=what), status=409)
    row.active = False
    await db.flush()
