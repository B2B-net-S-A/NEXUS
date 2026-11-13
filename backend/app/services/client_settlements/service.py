"""Rozliczenia klientów E1: miesiąc klienta, karta osoby, przyjęcie RCP, reguły.

Kontrakt odpowiedzi: roadmapa E1.3 i ``frontend/src/lib/api/client-settlements.ts``.

* Osoby miesiąca to kontrakty klienta, które w tym miesiącu trwały, plus każdy
  kontrakt z rozliczeniem albo RCP za ten miesiąc.
* „Brak RCP” nie ma wiersza; RCP bez wiersza (wpłynęło, nikt jeszcze nie
  ruszał) to „Do sprawdzenia”.
* Przyjęcie liczy rozliczenie od nowa na bieżącym stanie zamówienia, zdejmuje MD
  przez ``upsert_consumption`` (źródło ``settlement``, nadpisanie miesiąca, nie
  dokładanie) i przyjmuje RCP w ``cp_documents`` (sygnał „wystaw fakturę”).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_sales_invoice import ClientSalesInvoiceLink
from app.models.client_settlement import (
    ClientSettlement,
    ClientSettlementExtra,
    ClientSettlementRuleSet,
)
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract, ContractStatus
from app.models.md_consumption import ClientOrderMdConsumption
from app.models.user import User
from app.core.scheduling import DEFAULT_TZ
from app.services.client_order_lines import (
    format_period_month,
    month_bounds,
    record_event,
    upsert_consumption,
)
from app.services.client_settlements import (
    acceptance_mail,
    contractor_invoices,
    kesu,
    kesu_flow,
    rcp_bnp,
    rcp_checks,
    rules_catalog,
    timesheet,
)
from app.services.client_settlements import settings as module_settings
from app.services.client_settlements.engine import Inputs, OrderState, Result, compute
from app.services.client_settlements_schema import FIX_REASON_MAX
from app.services.consultant_portal import documents as portal_documents
from app.services.hr.payroll_periods import add_months
from app.services.multi_consultant_orders import EVENT_MANUAL_EDIT, format_md
from app.services.person_workdays import business_days

logger = logging.getLogger(__name__)

SOURCE_SETTLEMENT = "settlement"
ACTUAL, ESTIMATE = "actual", "estimate"
OPEN_STATUSES = ("checking", "ok", "warnings", "no_md")
#: Kontrakty, które w ogóle mogły pracować (szkic i anulowany nie).
WORKING_CONTRACT_STATUSES = (
    ContractStatus.active,
    ContractStatus.ending,
    ContractStatus.ended,
)
ORDER_STATUSES = (
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
    ClientOrderStatus.completed,
)
MD_MAX = Decimal("31")
#: Zapłata konsultanta po mailowej akceptacji, gdy podpisujący KEŚU jest nieobecny.
PAY_ON_MAIL = "pay_on_mail"
#: „Imię Nazwisko” jak na liście kontraktów; puste części pomija.
_FULL_NAME = func.nullif(func.concat_ws(" ", Candidate.name, Candidate.lastname), "")


class SettlementError(Exception):
    """Odmowa z komunikatem dla Finansów."""

    def __init__(self, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Person:
    contract: Contract
    name: str


def _dec(value: Optional[Decimal], places: int = 3) -> Optional[str]:
    return None if value is None else f"{Decimal(value):.{places}f}"


# ── Odczyt ───────────────────────────────────────────────────────────────────


async def _rule_set(
    db: AsyncSession, client_id: int, month: str
) -> Optional[ClientSettlementRuleSet]:
    return await db.scalar(
        select(ClientSettlementRuleSet)
        .where(
            ClientSettlementRuleSet.client_id == client_id,
            ClientSettlementRuleSet.effective_from <= month,
        )
        .order_by(ClientSettlementRuleSet.effective_from.desc())
        .limit(1)
    )


async def rules_for(
    db: AsyncSession, client_id: int, month: str
) -> dict[str, dict[str, Any]]:
    found = await _rule_set(db, client_id, month)
    return rules_catalog.effective(found.rules if found else None)


async def _people(db: AsyncSession, client_id: int, month: str) -> list[Person]:
    first, last = month_bounds(month)
    year, mon = (int(x) for x in month.split("-"))
    with_activity = select(ClientSettlement.contract_id).where(
        ClientSettlement.client_id == client_id, ClientSettlement.period_month == month
    )
    with_report = select(CpDocument.contract_id).where(
        CpDocument.kind == "report",
        CpDocument.period_year == year,
        CpDocument.period_month == mon,
        CpDocument.contract_id.is_not(None),
    )
    rows = await db.execute(
        select(Contract, _FULL_NAME)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            Contract.client_id == client_id,
            or_(
                and_(
                    Contract.status.in_(WORKING_CONTRACT_STATUSES),
                    or_(Contract.start_date.is_(None), Contract.start_date <= last),
                    or_(Contract.end_date.is_(None), Contract.end_date >= first),
                ),
                Contract.id.in_(with_activity),
                Contract.id.in_(with_report),
            ),
        )
        .order_by(Candidate.lastname, Candidate.name, Contract.id)
    )
    return [
        Person(contract, name or f"Kontrakt {contract.id}")
        for contract, name in rows.all()
    ]


async def _order_for(
    db: AsyncSession, contract_id: int, month: str
) -> Optional[ClientOrder]:
    first, last = month_bounds(month)
    return await db.scalar(
        select(ClientOrder)
        .where(
            ClientOrder.contract_id == contract_id,
            ClientOrder.status.in_(ORDER_STATUSES),
            or_(ClientOrder.start_date.is_(None), ClientOrder.start_date <= last),
            or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= first),
        )
        .order_by(
            (ClientOrder.status == ClientOrderStatus.active).desc(),
            ClientOrder.start_date.desc().nullslast(),
            ClientOrder.id.desc(),
        )
        .limit(1)
    )


async def _order_state(
    db: AsyncSession, order: Optional[ClientOrder], month: str
) -> Optional[OrderState]:
    if order is None:
        return None
    number = None
    if order.order_group_id is not None:
        number = await db.scalar(
            select(ClientOrderGroup.order_number).where(
                ClientOrderGroup.id == order.order_group_id
            )
        )
    available = None
    if order.md_remaining is not None:
        this_month = await db.scalar(
            select(ClientOrderMdConsumption.md_reported).where(
                ClientOrderMdConsumption.order_id == order.id,
                ClientOrderMdConsumption.period_month == month,
            )
        )
        available = Decimal(order.md_remaining) + Decimal(this_month or 0)
    return OrderState(
        order_id=order.id,
        number=number,
        md_total=order.md_total,
        md_available=available,
        rate_cost=order.md_rate_cost,
        rate_revenue=order.md_rate_revenue,
    )


async def _onboarding_used(db: AsyncSession, contract_id: int, month: str) -> Decimal:
    used = await db.scalar(
        select(func.coalesce(func.sum(ClientSettlement.md_onboarding), 0)).where(
            ClientSettlement.contract_id == contract_id,
            ClientSettlement.kind == "actual",
            ClientSettlement.status == "accepted",
            ClientSettlement.period_month < month,
        )
    )
    return Decimal(used or 0)


RCP_MIMES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
MAIL_MIMES = ("application/vnd.ms-outlook", "message/rfc822")


def month_end(month: str) -> datetime:
    """Początek następnego miesiąca w kalendarzu firmy: granica estymacji (E5.3)."""

    year, mon = (int(x) for x in month.split("-"))
    year, mon = add_months(year, mon, 1)
    return datetime(year, mon, 1, tzinfo=ZoneInfo(DEFAULT_TZ))


async def _month_reports(
    db: AsyncSession, contract_id: int, month: str, *, kind: str = ACTUAL
) -> list[CpDocument]:
    """Pliki RCP miesiąca. Przy estymacji (E5.3) plan to pliki sprzed końca
    miesiąca, a RCP faktyczne — pliki od pierwszego dnia następnego."""

    year, mon = (int(x) for x in month.split("-"))
    stmt = select(CpDocument).where(
        CpDocument.contract_id == contract_id,
        CpDocument.kind == "report",
        CpDocument.period_year == year,
        CpDocument.period_month == mon,
        CpDocument.status != "rejected",
    )
    if kind == ESTIMATE:
        stmt = stmt.where(CpDocument.created_at < month_end(month))
    elif await _settlement(db, contract_id, month, kind=ESTIMATE) is not None:
        stmt = stmt.where(CpDocument.created_at >= month_end(month))
    return list((await db.scalars(stmt.order_by(CpDocument.created_at.desc()))).all())


async def _report(
    db: AsyncSession, contract_id: int, month: str, *, kind: str = ACTUAL
) -> Optional[CpDocument]:
    """RCP miesiąca: najnowszy PDF albo XLSX; inny plik, gdy RCP nie ma."""

    return await _pick_report(await _month_reports(db, contract_id, month, kind=kind))


def _is_mail_printout(doc: CpDocument) -> bool:
    """PDF z wydrukiem maila (E2.3) to dowód zgody, nie RCP."""

    if doc.mime != acceptance_mail.PDF:
        return False
    try:
        content = portal_documents.path_for(doc.file_path).read_bytes()
    except OSError:
        return False
    return bool(acceptance_mail.read(content, doc.mime))


async def _pick_report(reports: list[CpDocument]) -> Optional[CpDocument]:
    """RCP spośród plików miesiąca (najnowsze pierwsze): PDF albo XLSX, ale nie
    wydruk maila — konsultant często dosyła go po RCP."""

    candidates = [d for d in reports if d.mime in RCP_MIMES]
    if len(candidates) > 1:
        for doc in candidates:
            if not await asyncio.to_thread(_is_mail_printout, doc):
                return doc
    return candidates[0] if candidates else (reports[0] if reports else None)


async def _settlement(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    kind: str = ACTUAL,
    for_update: bool = False,
) -> Optional[ClientSettlement]:
    stmt = select(ClientSettlement).where(
        ClientSettlement.contract_id == contract_id,
        ClientSettlement.period_month == month,
        ClientSettlement.kind == kind,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def integration_by_contract(
    db: AsyncSession, contract_ids: list[int], month: str
) -> dict[int, Decimal]:
    """Przyjęte koszty integracji osób w miesiącu (E5.1) — obniżają marżę.
    Inne rodzaje dodatków (``kind``) marży tu nie zmieniają."""

    if not contract_ids:
        return {}
    rows = await db.execute(
        select(
            ClientSettlementExtra.contract_id,
            func.sum(ClientSettlementExtra.amount),
        )
        .where(
            ClientSettlementExtra.contract_id.in_(contract_ids),
            ClientSettlementExtra.period_month == month,
            ClientSettlementExtra.kind == "integration",
            ClientSettlementExtra.status == "approved",
        )
        .group_by(ClientSettlementExtra.contract_id)
    )
    return {int(cid): Decimal(total) for cid, total in rows.all() if total}


def _margin(
    cost: Optional[Decimal],
    revenue: Optional[Decimal],
    integration: Decimal = Decimal("0"),
) -> tuple[Optional[str], Optional[str]]:
    if cost is None or revenue is None:
        return None, None
    margin = Decimal(revenue) - Decimal(cost) - integration
    pct = None if Decimal(revenue) == 0 else margin / Decimal(revenue) * 100
    return _dec(margin, 2), _dec(pct, 1)


def _row(
    person: Person,
    s: Optional[ClientSettlement],
    has_report: bool,
    amounts: bool,
    integration: Decimal = Decimal("0"),
) -> dict[str, Any]:
    status = s.status if s else ("checking" if has_report else "missing")
    margin, pct = (
        _margin(s.amount_cost, s.amount_revenue, integration) if s else (None, None)
    )
    remaining = None
    if s and s.checks:
        remaining = next(
            (
                c.get("remaining_after")
                for c in s.checks
                if isinstance(c, dict) and "remaining_after" in c
            ),
            None,
        )
    issue = None
    if s and s.status == "needs_fix":
        issue = s.fix_reason
    elif s and s.status != "accepted":
        # Najpierw błąd, potem uwaga: „Brakuje MD” ważniejsze niż brak pliku.
        found = [
            check
            for group in s.checks
            for check in (group.get("checks") or [])
            if check.get("state") in ("warn", "fail")
        ]
        found.sort(key=lambda check: check.get("state") != "fail")
        issue = found[0]["title"] if found else None
    return {
        "contract_id": person.contract.id,
        "settlement_id": s.id if s else None,
        "person": person.name,
        "order_number": None,
        "status": status,
        "issues": issue,
        "md_regular": _dec(s.md_regular) if s else None,
        "md_extra": _dec(s.md_extra) if s and s.md_extra else None,
        "md_charged": _dec(s.md_charged) if s else None,
        "md_remaining_after": remaining,
        "amount_cost": _dec(s.amount_cost, 2) if s and amounts else None,
        "amount_revenue": _dec(s.amount_revenue, 2) if s and amounts else None,
        "integration_cost": _dec(integration, 2) if amounts and integration else None,
        "margin": margin if amounts else None,
        "margin_pct": pct if amounts else None,
        "contractor_invoice": "none",
        "client_invoice": "ready" if s and s.status == "accepted" else "waiting",
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "todo": sum(1 for r in rows if r["status"] in OPEN_STATUSES),
        "missing": sum(1 for r in rows if r["status"] == "missing"),
        "needs_fix": sum(1 for r in rows if r["status"] == "needs_fix"),
        "accepted": sum(1 for r in rows if r["status"] == "accepted"),
        "all": len(rows),
    }


async def month_view(
    db: AsyncSession, client_id: int, month: str, *, amounts: bool
) -> dict[str, Any]:
    client = await db.get(Client, client_id)
    if client is None:
        raise SettlementError("Nie ma takiego klienta.", status=404)
    people = await _people(db, client_id, month)
    ids = [p.contract.id for p in people]
    settlements = (
        {
            s.contract_id: s
            for s in (
                await db.scalars(
                    select(ClientSettlement).where(
                        ClientSettlement.contract_id.in_(ids),
                        ClientSettlement.period_month == month,
                        ClientSettlement.kind == "actual",
                    )
                )
            ).all()
        }
        if ids
        else {}
    )
    year, mon = (int(x) for x in month.split("-"))
    report_filter = [
        CpDocument.contract_id.in_(ids),
        CpDocument.kind == "report",
        CpDocument.period_year == year,
        CpDocument.period_month == mon,
        CpDocument.status != "rejected",
    ]
    if await estimate_allowed(db, client_id, month):
        # Pliki sprzed końca miesiąca to plan (E5.3) — ma własny ekran.
        report_filter.append(CpDocument.created_at >= month_end(month))
    reports = (
        set(
            (
                await db.scalars(select(CpDocument.contract_id).where(*report_filter))
            ).all()
        )
        if ids
        else set()
    )
    numbers = await _order_numbers(db, ids, month)
    rules = await rules_for(db, client_id, month)
    invoices = await contractor_invoices.for_month(db, ids, month)
    issued = await _issued_orders(
        db, [s.order_id for s in settlements.values() if s.order_id], month
    )
    integration = await integration_by_contract(db, ids, month) if amounts else {}
    rows = []
    for person in people:
        settlement = settlements.get(person.contract.id)
        row = _row(
            person,
            settlement,
            person.contract.id in reports,
            amounts,
            integration.get(person.contract.id, Decimal("0")),
        )
        row["order_number"] = numbers.get(person.contract.id)
        row["contractor_invoice"] = contractor_invoices.state(
            settlement, invoices.get(person.contract.id, []), rules
        )
        if settlement is not None and settlement.order_id in issued:
            row["client_invoice"] = "issued"
        elif row["client_invoice"] == "ready" and waits_for_signature(
            settlement, rules
        ):
            row["client_invoice"] = "awaiting_signature"
        row["kesu"] = kesu_summary(settlement)
        rows.append(row)
    return {
        "client_id": client_id,
        "client_name": client.name,
        "month": month,
        "can_see_amounts": amounts,
        "counts": _counts(rows),
        "batch_ready": sum(1 for r in rows if r["status"] == "ok"),
        "rows": rows,
    }


async def _issued_orders(
    db: AsyncSession, order_ids: list[int], month: str
) -> set[int]:
    """Linie zamówienia, których grupa ma już fakturę do klienta za ten miesiąc (E5.1)."""

    if not order_ids:
        return set()
    year, mon = (int(x) for x in month.split("-"))
    rows = await db.scalars(
        select(ClientOrder.id)
        .join(
            ClientSalesInvoiceLink,
            ClientSalesInvoiceLink.order_group_id == ClientOrder.order_group_id,
        )
        .where(
            ClientOrder.id.in_(order_ids),
            ClientSalesInvoiceLink.period_year == year,
            ClientSalesInvoiceLink.period_month == mon,
        )
    )
    return set(rows.all())


async def _order_numbers(
    db: AsyncSession, contract_ids: list[int], month: str
) -> dict[int, str]:
    if not contract_ids:
        return {}
    first, last = month_bounds(month)
    rows = await db.execute(
        select(ClientOrder.contract_id, ClientOrderGroup.order_number)
        .join(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .where(
            ClientOrder.contract_id.in_(contract_ids),
            ClientOrder.status.in_(ORDER_STATUSES),
            or_(ClientOrder.start_date.is_(None), ClientOrder.start_date <= last),
            or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= first),
        )
        .order_by(ClientOrder.start_date.asc().nullsfirst(), ClientOrder.id)
    )
    return {contract_id: number for contract_id, number in rows.all()}


async def _contract(db: AsyncSession, contract_id: int) -> Person:
    row = (
        await db.execute(
            select(Contract, _FULL_NAME)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.id == contract_id)
        )
    ).first()
    if row is None:
        raise SettlementError("Nie ma takiego kontraktu.", status=404)
    return Person(row[0], row[1] or f"Kontrakt {contract_id}")


async def detail(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    amounts: bool,
    kind: str = ACTUAL,
) -> dict[str, Any]:
    person = await _contract(db, contract_id)
    client = await db.get(Client, person.contract.client_id)
    s = await _settlement(db, contract_id, month, kind=kind)
    year, mon = (int(x) for x in month.split("-"))
    docs = (
        await db.scalars(
            select(CpDocument)
            .where(
                CpDocument.contract_id == contract_id,
                CpDocument.period_year == year,
                CpDocument.period_month == mon,
                CpDocument.status != "rejected",
            )
            .order_by(CpDocument.created_at)
        )
    ).all()
    order = await _order_for(db, contract_id, month)
    state = await _order_state(db, order, month)
    total_md = None
    if s and s.md_regular is not None:
        # Suma pozycji „Ile wychodzi z RCP” — z linią ponad zamówienie (ujemną).
        total_md = _dec(
            Decimal(s.md_regular) + Decimal(s.md_extra or 0) - (md_over(s) or 0)
        )
    lines = [
        {
            **line,
            "rate": line.get("rate") if amounts else None,
            "net": line.get("net") if amounts else None,
        }
        for line in (s.lines if s else [])
    ]
    remaining = None
    if s:
        remaining = next(
            (c.get("remaining_after") for c in s.checks if "remaining_after" in c), None
        )
    invoices = (await contractor_invoices.for_month(db, [contract_id], month)).get(
        contract_id, []
    )
    rules = await rules_for(db, person.contract.client_id, month)
    estimate = (
        await _settlement(db, contract_id, month, kind=ESTIMATE)
        if kind == ACTUAL
        else None
    )
    return {
        "contract_id": contract_id,
        "settlement_id": s.id if s else None,
        "kind": kind,
        "estimate": None
        if estimate is None
        else {
            "status": estimate.status,
            "md_regular": _dec(estimate.md_regular),
            "md_charged": _dec(estimate.md_charged),
        },
        "person": person.name,
        "client_name": client.name if client else "",
        "month": month,
        "order_number": state.number if state else None,
        "contract_number": None,
        "status": s.status
        if s
        else ("checking" if any(d.kind == "report" for d in docs) else "missing"),
        "fix_reason": s.fix_reason if s else None,
        "documents": [
            {
                "id": d.id,
                "kind": d.kind,
                "file_name": d.file_name,
                "channel": d.channel,
                "mime": d.mime,
                "received_at": d.created_at.isoformat(),
            }
            for d in docs
        ],
        "md_regular": _dec(s.md_regular) if s else None,
        "md_extra": _dec(s.md_extra) if s else None,
        "md_source": s.md_source if s else None,
        "lines": lines,
        "total_md": total_md,
        "total_net": _dec(s.amount_cost, 2) if s and amounts else None,
        "checks": [c for c in (s.checks if s else []) if "remaining_after" not in c],
        "order": None
        if state is None
        else {
            "md_total": _dec(state.md_total),
            "md_charged": _dec(s.md_charged) if s else None,
            "md_remaining_after": remaining,
        },
        "contractor_invoice": _with_payment(
            contractor_invoices.card(s, invoices, rules, amounts=amounts), s, rules
        ),
        "kesu": kesu_card(
            s, person=person.name, month=month, rules=rules, amounts=amounts
        )
        if kind == ACTUAL
        else None,
    }


def _with_payment(
    card: dict[str, Any],
    s: Optional[ClientSettlement],
    rules: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pay = payment(s, rules)
    if pay is not None:
        card["checks"] = [
            *card["checks"],
            {"state": pay["state"], "title": pay["title"], "detail": pay["detail"]},
        ]
    return card


# ── Zapis ────────────────────────────────────────────────────────────────────


def meta_of(s: Optional[ClientSettlement]) -> dict[str, Any]:
    """Dane przy kontrolach: pozostałość MD, nadwyżka, KEŚU, zapłata po mailu."""

    for item in (s.checks if s else None) or []:
        if isinstance(item, dict) and "remaining_after" in item:
            return item
    return {}


def _store(s: ClientSettlement, result: Result, order: Optional[OrderState]) -> None:
    kept = meta_of(s).get(PAY_ON_MAIL)
    s.status = result.status
    s.md_onboarding = result.md_onboarding
    s.md_charged = result.md_charged
    s.amount_cost = result.amount_cost
    s.amount_revenue = result.amount_revenue
    s.lines = result.lines
    # Pozostałość po zejściu trzymamy przy kontrolach, żeby lista miesiąca nie
    # pytała zamówień osoba po osobie.
    meta: dict[str, Any] = {
        "remaining_after": _dec(result.md_remaining_after),
        "md_over": _dec(result.md_over),
        **(result.meta or {}),
    }
    if kept:
        # Decyzja Finansów o zapłacie po mailu przeżywa przeliczenie (E6.3).
        meta[PAY_ON_MAIL] = kept
    s.checks = [*result.checks, meta]
    s.order_id = order.order_id if order else None


def md_over(s: ClientSettlement) -> Optional[Decimal]:
    """MD ponad pulę zamówienia zapisane przy przeliczeniu (bez zejścia i zapłaty)."""

    for item in s.checks or []:
        if isinstance(item, dict) and item.get("md_over"):
            return Decimal(str(item["md_over"]))
    return None


def _onboarding_eligible(contract: Contract, month: str) -> bool:
    """Nowy konsultant: kontrakt od tego albo poprzedniego miesiąca."""

    if contract.start_date is None:
        return False
    first, _last = month_bounds(month)
    previous_first = (first - timedelta(days=1)).replace(day=1)
    return contract.start_date >= previous_first


def _read_rcp(
    content: bytes, mime: str
) -> tuple[Optional[rcp_bnp.ParsedRcp], list[rcp_bnp.SignatureInfo]]:
    parsed = rcp_bnp.parse(content, mime)
    signatures = rcp_bnp.signatures(content) if mime == "application/pdf" else []
    return parsed, signatures


async def read_rcp(
    content: bytes, mime: str
) -> tuple[Optional[rcp_bnp.ParsedRcp], list[rcp_bnp.SignatureInfo]]:
    """Odczyt i podpis w wątku: walidator pyHanko odpala własną pętlę zdarzeń
    (w pętli FastAPI zwracał „PDF bez podpisu”), a parser PDF to praca CPU."""

    return await asyncio.to_thread(_read_rcp, content, mime)


async def _mails(
    report: CpDocument, reports: list[CpDocument]
) -> list[acceptance_mail.MailMessage]:
    """Wiadomości z maili miesiąca (E2.3): ``.msg``, ``.eml`` i wydruk PDF poza RCP.
    PDF bez nagłówków maila (np. faktura kosztowa) nic nie wnosi."""

    found: list[acceptance_mail.MailMessage] = []
    for doc in reports:
        if doc.id == report.id or doc.mime not in acceptance_mail.MIMES:
            continue
        try:
            content = portal_documents.path_for(doc.file_path).read_bytes()
        except OSError:
            continue
        found.extend(await asyncio.to_thread(acceptance_mail.read, content, doc.mime))
    return found


async def _proof(
    report: Optional[CpDocument],
    reports: list[CpDocument],
    *,
    month: str,
    person_name: str,
    rules: dict[str, dict[str, Any]],
) -> Optional[rcp_checks.ProofResult]:
    """Odczyt RCP z pliku i kontrole (E2). Brak pliku RCP = ``None``."""

    if report is None or report.mime not in RCP_MIMES:
        return None
    try:
        content = portal_documents.path_for(report.file_path).read_bytes()
    except OSError as exc:
        logger.warning(
            "rozliczenia: pliku RCP %s nie da się odczytać (%s)",
            report.id,
            type(exc).__name__,
        )
        return None
    parsed, signatures = await read_rcp(content, report.mime)
    mails = await _mails(report, reports)
    has_mail = any(d.mime in MAIL_MIMES for d in reports) or bool(mails)
    if parsed is None:
        # Nie szablon RCP BNP: może Time Sheet w godzinach (E6.2).
        sheet = await asyncio.to_thread(timesheet.parse, content, report.mime)
        if sheet is not None:
            return timesheet.evaluate(
                sheet,
                month=month,
                person_name=person_name,
                has_mail=has_mail,
                rules=rules,
                working_days=len(business_days(*month_bounds(month))),
            )
    return rcp_checks.evaluate(
        parsed,
        signatures,
        mime=report.mime,
        month=month,
        person_name=person_name,
        has_mail=has_mail,
        rules=rules,
        mails=mails,
    )


async def _recompute(
    db: AsyncSession, s: ClientSettlement
) -> tuple[Result, Optional[OrderState], Optional[ClientOrder]]:
    person = await _contract(db, s.contract_id)
    order = await _order_for(db, s.contract_id, s.period_month)
    state = await _order_state(db, order, s.period_month)
    reports = await _month_reports(db, s.contract_id, s.period_month, kind=s.kind)
    report = await _pick_report(reports)
    rules = await rules_for(db, s.client_id, s.period_month)
    proof: Optional[rcp_checks.ProofResult] = None
    if kesu_flow.has_source(reports):
        # KEŚU z Jiry (E6.3): arkusz albo mail z arkuszem, podpisy w PDF-ach.
        proof = await kesu_flow.proof(
            db,
            reports,
            contract_id=s.contract_id,
            month=s.period_month,
            person_name=person.name,
            order_rate_md=state.rate_revenue if state else None,
            rules=rules,
        )
        if proof is not None:
            source = proof.meta["kesu"].get("document_id")
            report = next((d for d in reports if d.id == source), report)
    s.report_document_id = report.id if report else None
    if proof is None:
        proof = await _proof(
            report, reports, month=s.period_month, person_name=person.name, rules=rules
        )
    # Wpis Finansów wygrywa z odczytem pliku; bez wpisu MD bierzemy z RCP.
    if proof is not None and proof.md_regular is not None and s.md_source != "manual":
        s.md_regular = proof.md_regular
        s.md_extra = proof.md_extra or None
        s.md_source = "rcp"
    result = compute(
        Inputs(
            md_regular=s.md_regular,
            md_extra=s.md_extra,
            rules=rules,
            order=state,
            onboarding_used_before=await _onboarding_used(
                db, s.contract_id, s.period_month
            ),
            has_report=report is not None,
            onboarding_eligible=_onboarding_eligible(person.contract, s.period_month),
            proof=proof,
        )
    )
    return result, state, order


async def _get_or_create(
    db: AsyncSession,
    contract_id: int,
    month: str,
    actor: Optional[User],
    *,
    kind: str = ACTUAL,
) -> ClientSettlement:
    person = await _contract(db, contract_id)
    s = await _settlement(db, contract_id, month, kind=kind, for_update=True)
    if s is None:
        s = ClientSettlement(
            contract_id=contract_id,
            client_id=person.contract.client_id,
            period_month=month,
            kind=kind,
            status="checking",
            lines=[],
            checks=[],
            updated_by=actor.id if actor else None,
        )
        db.add(s)
        await db.flush()
    return s


def _clean_md(value: Optional[Decimal], label: str) -> Optional[Decimal]:
    if value is None:
        return None
    if value < 0 or value > MD_MAX:
        raise SettlementError(f"{label}: podaj od 0 do {MD_MAX} MD.", status=422)
    return value


async def set_md(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    md_regular: Decimal,
    md_extra: Optional[Decimal],
    actor: User,
    kind: str = ACTUAL,
) -> ClientSettlement:
    """MD z RCP wpisane przez Finanse (E1; od E2 z odczytu pliku). Zmiana po
    przyjęciu cofa stan do ponownej decyzji, zejście MD zostaje do niej."""

    s = await _get_or_create(db, contract_id, month, actor, kind=kind)
    s.md_regular = _clean_md(md_regular, "Dni zwykłe")
    s.md_extra = _clean_md(md_extra, "Praca dodatkowa")
    s.md_source = "manual"
    s.fix_reason = None
    s.updated_by = actor.id
    result, state, _order = await _recompute(db, s)
    _store(s, result, state)
    return s


async def _estimate_guard(
    db: AsyncSession, s: ClientSettlement, result: Result
) -> None:
    """E5.3: estymację przyjmujemy po przyjęciu poprzedniego miesiąca (zejście MD
    już jest), a RCP faktyczne za miesiąc z estymacją — nie ponad estymację."""

    if s.kind == ESTIMATE:
        actual = await _settlement(db, s.contract_id, s.period_month)
        if actual is not None and actual.status == "accepted":
            raise SettlementError(
                "RCP faktyczne za ten miesiąc jest już przyjęte. Plan zostaje "
                "do faktury klienta, zejście MD idzie z RCP faktycznego."
            )
        year, mon = (int(x) for x in s.period_month.split("-"))
        year, mon = add_months(year, mon, -1)
        previous = f"{year}-{mon:02d}"
        before = await _settlement(db, s.contract_id, previous)
        if before is None or before.status != "accepted":
            raise SettlementError(
                f"Najpierw przyjmij RCP za {format_period_month(previous)}: "
                "estymacja liczy się od tego, co zostanie po nim na zamówieniu."
            )
        return
    estimate = await _settlement(db, s.contract_id, s.period_month, kind=ESTIMATE)
    if (
        estimate is not None
        and estimate.status == "accepted"
        and estimate.md_charged is not None
        and result.md_charged is not None
        and result.md_charged > estimate.md_charged
    ):
        over = result.md_charged - estimate.md_charged
        raise SettlementError(
            f"RCP ponad estymację o {format_md(over)} MD. Więcej niż w estymacji "
            "nie przyjmujemy, bo zjadłoby MD z nowego zamówienia."
        )


async def _refuse_split_month(
    db: AsyncSession, contract_id: int, order_id: int, month: str
) -> None:
    """Miesiąc podzielony między dwa zamówienia osoby (import przy zmianie
    zamówienia, ``apply_md_consumption``): przyjęcie nadpisałoby jedną linię,
    a wpis drugiej zostałby — MD liczone dwa razy. Odmawiamy (FIN-MD-01)."""

    other = await db.scalar(
        select(func.count())
        .select_from(ClientOrderMdConsumption)
        .join(ClientOrder, ClientOrder.id == ClientOrderMdConsumption.order_id)
        .where(
            ClientOrder.contract_id == contract_id,
            ClientOrder.id != order_id,
            ClientOrderMdConsumption.period_month == month,
            ClientOrderMdConsumption.md_reported != 0,
        )
    )
    if other:
        raise SettlementError(
            "Ten miesiąc ma już zejście MD na innym zamówieniu tej osoby "
            "(podział przy zmianie zamówienia). Popraw zejście w zamówieniach; "
            "przyjęcie nadpisałoby jedną linię i MD policzyłyby się dwa razy."
        )


async def accept(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    actor: User,
    now: datetime,
    kind: str = ACTUAL,
) -> ClientSettlement:
    s = await _settlement(db, contract_id, month, kind=kind, for_update=True)
    if s is None or s.md_regular is None:
        raise SettlementError("Najpierw wpisz MD z RCP.")
    result, state, order = await _recompute(db, s)
    _store(s, result, state)
    await _estimate_guard(db, s, result)
    if result.status == "no_md":
        raise SettlementError(
            "Brak MD na zamówieniu: faktura czeka na nowe zamówienie albo wyjątek Finansów."
        )
    if result.blocking:
        failed = next(
            (
                c["title"]
                for g in result.checks
                for c in (g.get("checks") or [])
                if c.get("state") == "fail"
            ),
            "reguła klienta",
        )
        raise SettlementError(
            f"Reguła klienta blokuje przyjęcie: {failed}. "
            "Odeślij RCP do poprawy albo zmień poziom reguły."
        )
    rules = await rules_for(db, s.client_id, month)
    if (
        order is not None
        and result.md_charged is not None
        and rules["order.charge_on_accept"]["level"] != "off"
    ):
        await _refuse_split_month(db, contract_id, order.id, month)
        _row_, previous, remaining = await upsert_consumption(
            db,
            order=order,
            period_month=month,
            md_reported=result.md_charged,
            source=SOURCE_SETTLEMENT,
            user_id=actor.id,
            status="accepted",
            note="Przyjęte RCP (Rozliczenia)",
        )
        if order.order_group_id is not None:
            overwritten = (
                f", nadpisano wcześniejsze {format_md(previous)} MD"
                if previous and previous != result.md_charged
                else ""
            )
            record_event(
                db,
                group_id=order.order_group_id,
                order_id=order.id,
                event_type=EVENT_MANUAL_EDIT,
                description=(
                    f"Rozliczenia — zejście MD za {format_period_month(month)}: "
                    f"{format_md(result.md_charged)} MD z przyjętego RCP{overwritten}. "
                    f"Pozostało {format_md(remaining)} MD."
                ),
                payload={
                    "changed": ["zejście MD"],
                    "period_month": month,
                    "md_reported": str(result.md_charged),
                    "previous": str(previous),
                    "source": SOURCE_SETTLEMENT,
                    "settlement_id": s.id,
                    "md_remaining": str(remaining),
                },
                user_id=actor.id,
            )
    s.status = "accepted"
    s.accepted_by = actor.id
    s.accepted_at = now
    s.updated_by = actor.id
    if s.report_document_id is not None:
        document = await db.get(CpDocument, s.report_document_id)
        if document is not None and document.status == "received":
            await portal_documents.accept(db, document.id, actor_id=actor.id, now=now)
    # Maile z akceptacją i inne pliki miesiąca idą razem z RCP, ale bez drugiego
    # maila „możesz wystawić fakturę” (inaczej ich karty wisiałyby w back office).
    for other in await _month_reports(db, contract_id, month, kind=kind):
        if other.id != s.report_document_id and other.status == "received":
            other.status = "accepted"
            other.decided_by = actor.id
            other.decided_at = now
            other.updated_at = now
    return s


async def needs_fix(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    reason: str,
    actor: User,
    now: datetime,
    kind: str = ACTUAL,
) -> ClientSettlement:
    clean = reason.replace("\x00", "").strip()[:FIX_REASON_MAX]
    if len(clean) < 5:
        raise SettlementError("Napisz, co trzeba poprawić.", status=422)
    s = await _get_or_create(db, contract_id, month, actor, kind=kind)
    if s.status == "accepted":
        raise SettlementError("RCP jest już przyjęte. Popraw MD i przyjmij ponownie.")
    s.status = "needs_fix"
    s.fix_reason = clean
    s.updated_by = actor.id
    report = await _report(db, contract_id, month, kind=kind)
    if report is not None and report.status == "received":
        await portal_documents.reject(
            db, report.id, actor_id=actor.id, reason=clean, now=now
        )
    return s


async def accept_batch(
    db: AsyncSession,
    client_id: int,
    month: str,
    *,
    actor: User,
    now: datetime,
    kind: str = ACTUAL,
) -> int:
    """Przyjmuje tylko RCP „Bez uwag”; każde liczone od nowa jak pojedyncze."""

    ids = (
        await db.scalars(
            select(ClientSettlement.contract_id).where(
                ClientSettlement.client_id == client_id,
                ClientSettlement.period_month == month,
                ClientSettlement.kind == kind,
                ClientSettlement.status == "ok",
            )
        )
    ).all()
    accepted = 0
    for contract_id in ids:
        try:
            s = await accept(db, contract_id, month, actor=actor, now=now, kind=kind)
        except SettlementError:
            continue
        accepted += s.status == "accepted"
    return accepted


async def estimate_allowed(db: AsyncSession, client_id: int, month: str) -> bool:
    """Reguła ``cl.estimate`` klienta obejmuje ten miesiąc (np. grudzień BNP)."""

    rule = (await rules_for(db, client_id, month))["cl.estimate"]
    if rule["level"] == "off":
        return False
    months = {
        part.strip().lstrip("0")
        for part in str(rule["params"].get("months", "")).split(",")
    }
    return month.split("-")[1].lstrip("0") in months


async def kind_for_upload(
    db: AsyncSession, contract_id: int, month: str, uploaded_at: datetime
) -> str:
    """Plik za miesiąc, który jeszcze trwa, u klienta z estymacją = plan (E5.3)."""

    if uploaded_at >= month_end(month):
        return ACTUAL
    contract = await db.get(Contract, contract_id)
    if contract is None or not await estimate_allowed(db, contract.client_id, month):
        return ACTUAL
    return ESTIMATE


async def refresh_for_document(db: AsyncSession, document: CpDocument) -> None:
    """Po wgraniu RCP (panel albo mail, E2.4): rozliczenie miesiąca liczy się od
    nowa z pliku. Przyjęte rozliczenie zostaje — nowy plik czeka na Finanse."""

    if document.kind != "report" or document.contract_id is None:
        return
    if not await module_settings.is_enabled(db):
        return
    month = f"{document.period_year}-{document.period_month:02d}"
    # Domyślna data z bazy nie zawsze jest już w obiekcie po flush.
    uploaded = document.created_at or datetime.now(ZoneInfo(DEFAULT_TZ))
    kind = await kind_for_upload(db, document.contract_id, month, uploaded)
    s = await _get_or_create(db, document.contract_id, month, None, kind=kind)
    if s.status == "accepted":
        # Podpisane KEŚU przychodzi po przyjęciu (E6.3): odświeżamy tylko stan
        # KEŚU (podpisy), bez zmiany przyjętych MD i kwot.
        await _refresh_kesu(db, s)
        return
    result, state, _order = await _recompute(db, s)
    _store(s, result, state)
    if s.md_regular is None:
        s.status = "checking"


# ── KEŚU (E6.3) ──────────────────────────────────────────────────────────────

#: Pola KEŚU z kwotami: tylko dla kont z dostępem do kwot.
KESU_AMOUNTS = (
    "rate_md",
    "rate_contract",
    "rate_order",
    "fee_gross",
    "extra_costs",
    "total_gross",
)


def kesu_state(s: Optional[ClientSettlement]) -> Optional[str]:
    data = meta_of(s).get("kesu")
    return str(data["state"]) if isinstance(data, dict) and data.get("state") else None


def kesu_summary(s: Optional[ClientSettlement]) -> Optional[dict[str, Any]]:
    """KEŚU na liście miesiąca: stan, opiekun, czas akceptacji, godziny (bez kwot)."""

    data = meta_of(s).get("kesu")
    if not isinstance(data, dict):
        return None
    return {
        "state": data.get("state"),
        "state_label": kesu.STATE_LABELS.get(str(data.get("state")), ""),
        "approver": data.get("approver"),
        "accepted_at": data.get("accepted_at"),
        "hours": data.get("hours"),
        "days": data.get("days"),
    }


def waits_for_signature(
    s: Optional[ClientSettlement], rules: dict[str, dict[str, Any]]
) -> bool:
    """Faktura do klienta czeka na podpis klienta na KEŚU (``cl.after_signed_document``)."""

    state = kesu_state(s)
    return (
        state is not None
        and state != kesu.SIGNED
        and rules["cl.after_signed_document"]["level"] != "off"
    )


def payment(
    s: Optional[ClientSettlement], rules: dict[str, dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """Kiedy wolno zapłacić konsultantowi (``pay.after_client_signature``).

    Po podpisie klienta na KEŚU; awaryjnie (``pay.mail_accept_fallback``) po
    mailowej akceptacji, gdy podpisujący jest nieobecny — wtedy podpisane KEŚU
    zostaje do sprawdzenia później. ``None`` = reguła wyłączona albo bez KEŚU.
    """

    state = kesu_state(s)
    rule = rules["pay.after_client_signature"]["level"]
    if state is None or rule == "off":
        return None
    on_mail = meta_of(s).get(PAY_ON_MAIL)
    fallback = rules["pay.mail_accept_fallback"]["level"] != "off"
    if state == kesu.SIGNED:
        return {
            "state": "ok",
            "title": "Można zapłacić: KEŚU podpisane przez klienta",
            "detail": "Podpisane KEŚU po zapłacie po mailu sprawdzone."
            if on_mail
            else None,
            "can_pay": True,
            "on_mail": bool(on_mail),
            "can_use_mail": False,
        }
    if on_mail:
        return {
            "state": "warn",
            "title": "Można zapłacić po akceptacji mailowej",
            "detail": "Podpisujący nieobecny. Podpisane KEŚU sprawdzimy, gdy wróci.",
            "can_pay": True,
            "on_mail": True,
            "can_use_mail": False,
        }
    return {
        "state": "fail" if rule == "block" else "warn",
        "title": "Zapłata czeka na podpis klienta na KEŚU",
        "detail": "Gdy podpisujący jest nieobecny i nie ma zastępstwa, można zapłacić "
        "po akceptacji mailowej."
        if fallback
        else None,
        "can_pay": False,
        "on_mail": False,
        "can_use_mail": fallback,
    }


def kesu_card(
    s: Optional[ClientSettlement],
    *,
    person: str,
    month: str,
    rules: dict[str, dict[str, Any]],
    amounts: bool,
) -> Optional[dict[str, Any]]:
    data = meta_of(s).get("kesu")
    if not isinstance(data, dict):
        return None
    block: dict[str, Any] = {k: v for k, v in data.items() if k != "document_id"}
    if not amounts:
        block.update({key: None for key in KESU_AMOUNTS})
    contract, order = data.get("rate_contract"), data.get("rate_order")
    block["rate_differs"] = bool(
        contract and order and abs(Decimal(contract) - Decimal(order)) > Decimal("0.01")
    )
    block["state_label"] = kesu.STATE_LABELS.get(str(data.get("state")), "")
    block["mail"] = kesu.mail_draft(
        person=person,
        month=month,
        approver=data.get("approver"),
        approver_email=data.get("approver_email"),
    )
    block["payment"] = payment(s, rules)
    block["invoice_waits"] = waits_for_signature(s, rules)
    block["package_ready"] = data.get("rate_md") is not None
    return block


async def pay_on_mail(
    db: AsyncSession, contract_id: int, month: str, *, actor: User, now: datetime
) -> ClientSettlement:
    """Finanse: podpisujący KEŚU nieobecny, płacimy po mailowej akceptacji."""

    s = await _settlement(db, contract_id, month, for_update=True)
    if s is None or kesu_state(s) is None:
        raise SettlementError("Ta osoba nie ma KEŚU za ten miesiąc.")
    rules = await rules_for(db, s.client_id, month)
    if rules["pay.mail_accept_fallback"]["level"] == "off":
        raise SettlementError(
            "Reguła klienta nie pozwala płacić po mailowej akceptacji."
        )
    if kesu_state(s) == kesu.SIGNED:
        raise SettlementError("KEŚU jest już podpisane przez klienta.")
    meta = meta_of(s)
    if not meta.get("kesu", {}).get("approver"):
        raise SettlementError("Brak maila z Jiry z akceptacją opiekuna.")
    stamp = {"by": actor.id, "at": now.isoformat()}
    s.checks = [
        *(c for c in s.checks if c is not meta),
        {**meta, PAY_ON_MAIL: stamp},
    ]
    s.updated_by = actor.id
    return s


async def _refresh_kesu(db: AsyncSession, s: ClientSettlement) -> None:
    if kesu_state(s) is None:
        return
    person = await _contract(db, s.contract_id)
    reports = await _month_reports(db, s.contract_id, s.period_month, kind=s.kind)
    order = await _order_for(db, s.contract_id, s.period_month)
    proof = await kesu_flow.proof(
        db,
        reports,
        contract_id=s.contract_id,
        month=s.period_month,
        person_name=person.name,
        order_rate_md=order.md_rate_revenue if order else None,
        rules=await rules_for(db, s.client_id, s.period_month),
    )
    if proof is None:
        return
    meta = meta_of(s)
    fresh = {g["title"]: g for g in proof.groups}
    s.checks = [
        *(
            fresh.get(c.get("title"), c) if isinstance(c, dict) else c
            for c in s.checks
            if c is not meta
        ),
        {**meta, "kesu": proof.meta["kesu"]},
    ]


async def kesu_package(
    db: AsyncSession, contract_id: int, month: str
) -> tuple[bytes, str]:
    """Paczka PDF do podpisu spółki: KEŚU ze stawką i faktury kosztów."""

    person = await _contract(db, contract_id)
    reports = await _month_reports(db, contract_id, month)
    rules = await rules_for(db, person.contract.client_id, month)
    order = await _order_for(db, contract_id, month)
    try:
        content = await kesu_flow.package(
            db,
            reports,
            contract_id=contract_id,
            month=month,
            rules=rules,
            order_rate_md=order.md_rate_revenue if order else None,
        )
    except Exception as exc:  # noqa: BLE001 — PDF z zewnątrz bywa uszkodzony
        logger.warning("rozliczenia KEŚU: paczka nie powstała (%s)", type(exc).__name__)
        raise SettlementError(
            "Nie udało się złożyć paczki: jedna z faktur kosztów ma nieczytelny PDF. "
            "Pobierz pliki osobno z karty osoby."
        ) from None
    if content is None:
        raise SettlementError(
            "Nie ma KEŚU albo stawki klienta, więc paczki nie da się złożyć.",
            status=404,
        )
    return content, kesu.package_name(person.name, month)


# ── Klienci i reguły ─────────────────────────────────────────────────────────


async def clients_overview(db: AsyncSession, month: str) -> list[dict[str, Any]]:
    first, last = month_bounds(month)
    counts = await db.execute(
        select(Client.id, Client.name, func.count(Contract.id))
        .join(Contract, Contract.client_id == Client.id)
        .where(
            Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
            or_(Contract.start_date.is_(None), Contract.start_date <= last),
        )
        .group_by(Client.id, Client.name)
        .order_by(func.count(Contract.id).desc(), Client.name)
    )
    with_rules = set(
        (await db.scalars(select(ClientSettlementRuleSet.client_id).distinct())).all()
    )
    todo: dict[int, int] = defaultdict(int)
    for client_id, n in (
        await db.execute(
            select(ClientSettlement.client_id, func.count())
            .where(
                ClientSettlement.period_month == month,
                ClientSettlement.status.in_(OPEN_STATUSES),
            )
            .group_by(ClientSettlement.client_id)
        )
    ).all():
        todo[client_id] = n
    return [
        {
            "client_id": cid,
            "name": name,
            "active_contracts": n,
            "rules_set": cid in with_rules,
            "todo": todo.get(cid, 0),
        }
        for cid, name, n in counts.all()
    ]


async def rules_screen(db: AsyncSession, client_id: int, month: str) -> dict[str, Any]:
    client = await db.get(Client, client_id)
    if client is None:
        raise SettlementError("Nie ma takiego klienta.", status=404)
    found = await _rule_set(db, client_id, month)
    if found is None:
        # Najbliższa przyszła wersja też się liczy: Finanse ustawiają reguły od
        # bieżącego miesiąca, a ekran otwiera się na miesiącu rozliczanym.
        found = await db.scalar(
            select(ClientSettlementRuleSet)
            .where(ClientSettlementRuleSet.client_id == client_id)
            .order_by(ClientSettlementRuleSet.effective_from.desc())
            .limit(1)
        )
    effective = (
        rules_catalog.effective(found.rules)
        if found
        else {
            k: {"level": r.level, "params": dict(r.params)}
            for k, r in rules_catalog.RULES.items()
        }
    )
    return {
        "client_id": client_id,
        "client_name": client.name,
        "effective_from": found.effective_from if found else None,
        "sections": rules_catalog.as_screen(effective),
    }


async def save_rules(
    db: AsyncSession,
    client_id: int,
    *,
    effective_from: str,
    items: list[dict[str, Any]],
    actor: User,
) -> None:
    if await db.get(Client, client_id) is None:
        raise SettlementError("Nie ma takiego klienta.", status=404)
    month_bounds(effective_from)
    try:
        cleaned = rules_catalog.clean_for_save(items)
    except rules_catalog.RulesError as exc:
        raise SettlementError(str(exc), status=422) from exc
    current = await _rule_set(db, client_id, effective_from)
    merged = (
        rules_catalog.effective(current.rules if current else None) if current else {}
    )
    merged.update(cleaned)
    existing = await db.scalar(
        select(ClientSettlementRuleSet).where(
            ClientSettlementRuleSet.client_id == client_id,
            ClientSettlementRuleSet.effective_from == effective_from,
        )
    )
    if existing is None:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from=effective_from,
                rules=merged,
                updated_by=actor.id,
            )
        )
    else:
        existing.rules = merged
        existing.updated_by = actor.id


async def copy_rules(
    db: AsyncSession, client_id: int, source_client_id: int, *, month: str, actor: User
) -> None:
    source = await _rule_set(db, source_client_id, "9999-12")
    if source is None:
        raise SettlementError("Ten klient nie ma reguł do skopiowania.", status=404)
    items = [{"key": k, **v} for k, v in rules_catalog.effective(source.rules).items()]
    await save_rules(db, client_id, effective_from=month, items=items, actor=actor)


def today_month(today: date) -> str:
    return f"{today.year}-{today.month:02d}"
