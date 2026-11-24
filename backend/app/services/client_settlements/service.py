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
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
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
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus, EngagementModel
from app.models.contract_candidate_rate import ContractCandidateRate
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
    copyright_statement,
    confirmation_ergo,
    contractor_invoices,
    declared,
    ewidencja_orlen,
    extras as settlement_extras,
    hours_summary,
    kesu,
    kcp,
    kesu_flow,
    mail_declaration,
    mail_nn,
    mail_text,
    order_split,
    protocol_collective,
    protocol_orlen,
    rcp_bnp,
    rcp_checks,
    rules_catalog,
    redmine_timelog,
    report_ca,
    screenshot_ocr,
    signoffs,
    timesheet,
    timesheet_bik,
    timesheet_fieldglass,
    timesheet_pko,
    timesheet_plus,
)
from app.services.client_settlements import auto_accept
from app.services.client_settlements import settings as module_settings
from app.services.client_settlements.engine import (
    Inputs,
    OrderState,
    Result,
    SplitPart,
    compute,
)
from app.services.client_settlements_schema import FIX_REASON_MAX
from app.services.consultant_portal import documents as portal_documents
from app.services.hr.payroll_periods import add_months
from app.services.multi_consultant_orders import EVENT_MANUAL_EDIT, format_md
from app.services.order_revenue_steps import PricedOrder, priced_one
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
#: Wysyłka KCP do klienta i jego akceptacja mailem (E6.5, `client_acceptance`).
CLIENT_ACCEPTANCE = "client_acceptance"
#: Przyjęte przez automat ``order.auto_accept_clean`` (chwila przyjęcia).
AUTO_ACCEPTED = "auto_accepted"
#: Finanse odesłały „Do poprawy”: automat już tego rozliczenia nie bierze.
AUTO_ACCEPT_OFF = "auto_accept_off"
#: Podział miesiąca na zamówienia z maila klienta (``engine.Result.orders``).
ORDERS = "orders"
#: Zamówienia, z których przyjęcie zdjęło MD za miesiąc: tylko ich wpisy
#: ``settlement`` kolejne przyjęcie może wyzerować (własny podział, FIN-MD-01).
CHARGED_ORDERS = "charged_orders"
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
    order = await db.scalar(
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
    # Stawka przychodowa z pierwszego dnia miesiąca rozliczenia — aneks stawki
    # klienta zmienia ją od swojego dnia (``services/order_revenue_steps.py``).
    return await priced_one(db, order, first)


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
    rate_cost, rate_revenue = md_rates(order)
    return OrderState(
        order_id=order.id,
        number=number,
        md_total=order.md_total,
        md_available=available,
        rate_cost=rate_cost,
        rate_revenue=rate_revenue,
    )


#: Godziny w MD dla linii ze stawką godzinową (jak ``fields.md_hours`` domyślnie).
HOURS_PER_MD = Decimal("8")


def md_rates(order: Any) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Stawki MD linii. Kolumny MD wypełnia linia wielo-konsultantowa; zwykłe
    zamówienie trzyma stawkę w ``rate_client`` / ``rate_candidate`` według
    ``rate_unit``. Stawka godzinowa w zł (PKO: bez puli MD) daje 8 h × stawka,
    dzienna w zł (Alior, Velo, ERSTE: 64 zamówienia w próbie 23.11.2026) jest
    stawką MD wprost. Waluta obca bez kolumn MD zostaje bez stawki."""

    cost = getattr(order, "md_rate_cost", None)
    revenue = getattr(order, "md_rate_revenue", None)
    unit = getattr(order, "rate_unit", None)
    unit = getattr(unit, "value", unit)
    currency = (getattr(order, "rate_client_currency", None) or "PLN").upper()
    per_md = {"hourly": HOURS_PER_MD, "daily": Decimal("1")}.get(unit)
    if per_md is not None and currency == "PLN":
        client_rate = getattr(order, "rate_client", None)
        candidate_rate = getattr(order, "rate_candidate", None)
        if revenue is None and client_rate is not None:
            revenue = Decimal(client_rate) * per_md
        if cost is None and candidate_rate is not None:
            cost = Decimal(candidate_rate) * per_md
    return cost, revenue


async def _onboarding_used(db: AsyncSession, contract_id: int, month: str) -> Decimal:
    """MD wdrożeniowe z wcześniejszych miesięcy kontraktu, także nieprzyjętych.

    Policzony miesiąc startu już dał MD za 0 zł do swojej faktury. Gdy pula
    liczyła tylko przyjęte rozliczenia, kolejny miesiąc liczony przed przyjęciem
    dawał je drugi raz (próba IX–X 2026, BNP: kwota o 2 MD za niska)."""

    used = await db.scalar(
        select(func.coalesce(func.sum(ClientSettlement.md_onboarding), 0)).where(
            ClientSettlement.contract_id == contract_id,
            ClientSettlement.kind == "actual",
            ClientSettlement.period_month < month,
        )
    )
    return Decimal(used or 0)


RCP_MIMES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Time Sheet klienta z makrami (PKO, E6.1): czytamy tylko wartości.
    timesheet_pko.XLSM,
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


def _is_blank_sheet(doc: CpDocument) -> bool:
    """Pusty szablon raportu BIK, np. wzór od rozliczeń w cytowanym wątku: przy
    innym pliku miesiąca nie jest RCP (IX 2026: wygrywał z tabelą 176 h)."""

    if doc.mime != timesheet_bik.XLSX:
        return False
    try:
        content = portal_documents.path_for(doc.file_path).read_bytes()
    except OSError:
        return False
    return timesheet_bik.is_blank(content, doc.mime)


def _not_report(doc: CpDocument) -> bool:
    return _is_mail_printout(doc) or _is_blank_sheet(doc)


async def _pick_report(reports: list[CpDocument]) -> Optional[CpDocument]:
    """RCP spośród plików miesiąca (najnowsze pierwsze): PDF albo XLSX, ale nie
    wydruk maila — konsultant często dosyła go po RCP — ani pusty szablon."""

    candidates = [d for d in reports if d.mime in RCP_MIMES]
    if len(candidates) > 1:
        for doc in candidates:
            if not await asyncio.to_thread(_not_report, doc):
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
    # „fail” — reguła klienta blokuje przyjęcie; „warn” — uwaga, którą Finanse
    # mogą przyjąć na karcie osoby. Ekrany miesiąca liczą je osobno.
    issue_level: Optional[str] = None
    found = (
        [
            check
            for group in s.checks
            for check in (group.get("checks") or [])
            if check.get("state") in ("warn", "fail")
        ]
        if s
        else []
    )
    if s and s.status == "needs_fix":
        issue = s.fix_reason
        issue_level = "fail"
    elif s and s.status != "accepted":
        # Najpierw błąd, potem uwaga: „Brakuje MD” ważniejsze niż brak pliku.
        found.sort(key=lambda check: check.get("state") != "fail")
        issue = found[0]["title"] if found else None
        issue_level = found[0].get("state") if found else None
    return {
        "contract_id": person.contract.id,
        "settlement_id": s.id if s else None,
        "person": person.name,
        "order_number": None,
        "status": status,
        "issues": issue,
        "issue_level": issue_level,
        # Przyjęte mimo uwag albo błędów: rozstrzygnął człowiek, nie automat.
        "accepted_issue": bool(s and s.status == "accepted" and found),
        # „rcp” — MD odczytał automat z pliku, „manual” — wpisały Finanse.
        "md_source": s.md_source if s else None,
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
        "accepted_auto": _accepted_auto(s),
    }


def _accepted_auto(s: Optional[ClientSettlement]) -> bool:
    return bool(s and s.status == "accepted" and meta_of(s).get(AUTO_ACCEPTED))


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
    from app.services.client_settlements import client_acceptance

    acceptance = client_acceptance.params(rules)
    invoices = await contractor_invoices.for_month(db, ids, month)
    extra_items = await settlement_extras.for_contracts(db, ids, month)
    added = {cid: settlement_extras.totals(items) for cid, items in extra_items.items()}
    issued = await _issued_orders(
        db, [i for s in settlements.values() for i in settlement_order_ids(s)], month
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
        cost_add, revenue_add = settlement_extras.margin_shift(
            extra_items.get(person.contract.id, [])
        )
        if amounts and settlement is not None and (cost_add or revenue_add):
            # Zatwierdzone dodatki: koszt miesiąca; fakturowane klientowi — też przychód.
            row["margin"], row["margin_pct"] = _margin(
                None
                if settlement.amount_cost is None
                else settlement.amount_cost + cost_add,
                None
                if settlement.amount_revenue is None
                else settlement.amount_revenue + revenue_add,
                integration.get(person.contract.id, Decimal("0")),
            )
        row["order_number"] = split_numbers(settlement) or numbers.get(
            person.contract.id
        )
        row["contractor_invoice"] = contractor_invoices.state(
            settlement,
            invoices.get(person.contract.id, []),
            rules,
            added.get(person.contract.id),
        )
        # Dodatki do zatwierdzenia (polecenie, delegacja) — znacznik w wierszu.
        row["extras_pending"] = len(
            getattr(added.get(person.contract.id), "pending", ())
        )
        ordered = settlement_order_ids(settlement)
        if ordered and all(order_id in issued for order_id in ordered):
            # Przy podziale: faktura na każde zamówienie z maila klienta.
            row["client_invoice"] = "issued"
        elif row["client_invoice"] == "ready" and waits_for_signature(
            settlement, rules
        ):
            row["client_invoice"] = "awaiting_signature"
        elif row["client_invoice"] == "ready" and client_acceptance.waiting(
            settlement, rules
        ):
            row["client_invoice"] = "awaiting_client"
        row["client_acceptance"] = (
            client_acceptance.summary(settlement) if acceptance is not None else None
        )
        row["kesu"] = kesu_summary(settlement)
        rows.append(row)
    return {
        "client_id": client_id,
        "client_name": client.name,
        "month": month,
        "can_see_amounts": amounts,
        "counts": _counts(rows),
        "batch_ready": sum(1 for r in rows if r["status"] == "ok"),
        # Ile „Bez uwag” przyjmie automat (bez rozliczeń po „Do poprawy”).
        "auto_accept": auto_accept.info(
            rules,
            month,
            sum(
                1
                for r in rows
                if r["status"] == "ok"
                and not meta_of(settlements.get(r["contract_id"])).get(AUTO_ACCEPT_OFF)
            ),
        ),
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
        select(
            ClientOrder.contract_id, ClientOrderGroup.order_number, ClientOrder.title
        )
        .outerjoin(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .where(
            ClientOrder.contract_id.in_(contract_ids),
            ClientOrder.status.in_(ORDER_STATUSES),
            or_(ClientOrder.start_date.is_(None), ClientOrder.start_date <= last),
            or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= first),
        )
        .order_by(ClientOrder.start_date.asc().nullsfirst(), ClientOrder.id)
    )
    out: dict[int, str] = {}
    for contract_id, number, title in rows.all():
        # PKO, Velo: numer zamówienia stoi w tytule linii (E6.1), grupa go nie ma.
        found = number or number_from_title(title)
        if found:
            out[contract_id] = found
    return out


async def _sole_agreements(
    db: AsyncSession, contract_id: int, month: str
) -> frozenset[str]:
    """Numery umów wykonawczych (``protocol_collective.contract_key``), na których
    w miesiącu pracuje tylko ten kontrakt.

    CeZ zawiera umowę wykonawczą na osobę, ale bywa ich kilka na umowę (CeZ/242)
    albo zastępstwo od połowy miesiąca. Liczą się linie zamówień z miesiąca
    (bez anulowanych); druga osoba na tej samej umowie = umowa nikogo nie wskazuje.
    """

    first, last = month_bounds(month)
    in_month = (
        ClientOrder.status.in_(ORDER_STATUSES),
        ClientOrder.contract_id.is_not(None),
        or_(ClientOrder.start_date.is_(None), ClientOrder.start_date <= last),
        or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= first),
    )
    groups = select(ClientOrder.order_group_id).where(
        ClientOrder.contract_id == contract_id, *in_month
    )
    rows = await db.execute(
        select(ClientOrderGroup.order_number, ClientOrder.contract_id)
        .join(ClientOrder, ClientOrder.order_group_id == ClientOrderGroup.id)
        .where(ClientOrderGroup.id.in_(groups), *in_month)
    )
    people: dict[str, set[int]] = {}
    for number, other in rows.all():
        key = protocol_collective.contract_key(number)
        if key is not None:
            people.setdefault(key, set()).add(other)
    return frozenset(key for key, ids in people.items() if ids == {contract_id})


_ORDER_PREFIX = re.compile(r"^\s*zam[óo]wienie\s+(nr\.?\s*)?", re.IGNORECASE)


def number_from_title(title: Optional[str]) -> Optional[str]:
    """„Zamówienie nr 9001/2026” → „9001/2026”; tytuł opisowy → ``None``."""

    if not title:
        return None
    text = _ORDER_PREFIX.sub("", title).strip()
    if re.fullmatch(r"[\w./-]{2,40}", text) and re.search(r"\d", text):
        return text
    return None


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
    extra_items = (await settlement_extras.for_contracts(db, [contract_id], month)).get(
        contract_id, []
    )
    from app.services.client_settlements import client_acceptance

    acceptance = client_acceptance.params(rules)
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
        "order_number": split_numbers(s) or (state.number if state else None),
        "contract_number": None,
        "status": s.status
        if s
        else ("checking" if any(d.kind == "report" for d in docs) else "missing"),
        "fix_reason": s.fix_reason if s else None,
        # Czas firmy: front bierze godzinę wprost z napisu (`dayTime`).
        "accepted_at": s.accepted_at.astimezone(ZoneInfo(DEFAULT_TZ)).isoformat()
        if s and s.accepted_at
        else None,
        "accepted_auto": _accepted_auto(s),
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
        "checks": [
            *(
                c
                for c in (s.checks if s else [])
                if "remaining_after" not in c and signoffs.SIGNED_KEY not in c
            ),
            *(
                [client_acceptance.check_group(s, acceptance)]
                if acceptance is not None and kind == ACTUAL
                else []
            ),
        ],
        # KCP w PDF do pobrania (E6.5): od konsultanta albo złożona z Redmine.
        "kcp_pdf": bool(
            acceptance is not None and s is not None and s.report_document_id
        ),
        # Przy podziale pula i zejście każdego zamówienia stoją w kontrolach.
        "order": None
        if state is None or split_orders(s)
        else {
            "md_total": _dec(state.md_total),
            "md_charged": _dec(s.md_charged) if s else None,
            "md_remaining_after": remaining,
        },
        "contractor_invoice": _with_payment(
            contractor_invoices.card(
                s,
                invoices,
                rules,
                amounts=amounts,
                extras=settlement_extras.totals(extra_items),
            ),
            s,
            rules,
        ),
        "extras": await settlement_extras.block(
            db, contract_id, month, amounts=amounts, items=extra_items
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


def split_orders(s: Optional[ClientSettlement]) -> list[dict[str, Any]]:
    """Podział rozliczenia na zamówienia z maila klienta, zapisany przy ostatnim
    przeliczeniu (``engine.Result.orders``); pusty = całość na ``order_id``."""

    return [
        o
        for o in meta_of(s).get(ORDERS) or []
        if isinstance(o, dict) and o.get("order_id")
    ]


def settlement_order_ids(s: Optional[ClientSettlement]) -> list[int]:
    """Linie zamówień rozliczenia: wszystkie z podziału albo ``order_id``."""

    parts = split_orders(s)
    if parts:
        return [int(o["order_id"]) for o in parts]
    return [s.order_id] if s is not None and s.order_id else []


def split_numbers(s: Optional[ClientSettlement]) -> Optional[str]:
    """Numery zamówień z podziału („A, B”); bez podziału ``None``."""

    numbers = [str(o["number"]) for o in split_orders(s) if o.get("number")]
    return ", ".join(numbers) or None


def _store(s: ClientSettlement, result: Result, order: Optional[OrderState]) -> None:
    kept = meta_of(s).get(PAY_ON_MAIL)
    accepted_by_client = meta_of(s).get(CLIENT_ACCEPTANCE)
    auto_off = meta_of(s).get(AUTO_ACCEPT_OFF)
    charged = meta_of(s).get(CHARGED_ORDERS)
    signed = signoffs.marker(s.checks)
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
    if result.orders:
        meta[ORDERS] = [dict(o) for o in result.orders]
    if charged:
        # Linie zdjęte przy przyjęciu: kolejne przyjęcie wyzeruje tylko je.
        meta[CHARGED_ORDERS] = charged
    if kept:
        # Decyzja Finansów o zapłacie po mailu przeżywa przeliczenie (E6.3).
        meta[PAY_ON_MAIL] = kept
    if accepted_by_client:
        # Wysyłka KCP do klienta i jego akceptacja (E6.5) też.
        meta[CLIENT_ACCEPTANCE] = accepted_by_client
    if auto_off:
        # „Do poprawy” wyłącza automat dla tego rozliczenia na stałe.
        meta[AUTO_ACCEPT_OFF] = auto_off
    s.checks = [*result.checks, meta]
    # Podpisany arkusz albo protokół (E6) zostaje przy przeliczeniu.
    s.checks = signoffs.with_marker(s.checks, signed)
    # Przy podziale zamówieniem rozliczenia jest to z największą częścią MD.
    main = next((o for o in result.orders if o.get("main")), None)
    s.order_id = main["order_id"] if main else (order.order_id if order else None)


def _set_meta(s: ClientSettlement, key: str, value: Any) -> None:
    """Wpis w danych przy kontrolach (``meta_of``); ``None`` usuwa klucz."""

    checks = [c for c in (s.checks or []) if "remaining_after" not in c]
    meta = {"remaining_after": None, **meta_of(s)}
    if value is None:
        meta.pop(key, None)
    else:
        meta[key] = value
    s.checks = [*checks, meta]


def md_over(s: ClientSettlement) -> Optional[Decimal]:
    """MD ponad pulę zamówienia zapisane przy przeliczeniu (bez zejścia i zapłaty)."""

    for item in s.checks or []:
        if isinstance(item, dict) and item.get("md_over"):
            return Decimal(str(item["md_over"]))
    return None


def _onboarding_eligible(
    contract: Contract, month: str, *, rule_in_start_month: bool = True
) -> bool:
    """Nowy konsultant: kontrakt od tego albo poprzedniego miesiąca.

    Kontrakt z poprzedniego miesiąca dostaje resztę puli tylko wtedy, gdy
    w miesiącu startu reguła już działała. Bez niej MD wdrożeniowe dały Finanse
    na fakturze za miesiąc startu (BNP: pozycja ``_onbording``), a NEXUS dawał
    je drugi raz w kolejnym miesiącu."""

    if contract.start_date is None:
        return False
    first, _last = month_bounds(month)
    if contract.start_date >= first:
        return True
    previous_first = (first - timedelta(days=1)).replace(day=1)
    return contract.start_date >= previous_first and rule_in_start_month


async def _onboarding_rule_in_start_month(
    db: AsyncSession, client_id: int, contract: Contract, month: str
) -> bool:
    """``order.onboarding_md`` działało w miesiącu startu kontraktu, gdy ten
    jest poprzednim miesiącem rozliczenia. Starszy albo bieżący start: ``True``,
    bo o uprawnieniu decyduje wtedy sama data (``_onboarding_eligible``)."""

    start = contract.start_date
    if start is None:
        return True
    first, _last = month_bounds(month)
    previous_first = (first - timedelta(days=1)).replace(day=1)
    if not previous_first <= start < first:
        return True
    rules = await rules_for(db, client_id, f"{start.year}-{start.month:02d}")
    return rules["order.onboarding_md"]["level"] != "off"


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


def _read_mails(reports: list[CpDocument]) -> list[mail_text.Mail]:
    mails = []
    for document in reports:
        if document.mime not in MAIL_MIMES:
            continue
        try:
            content = portal_documents.path_for(document.file_path).read_bytes()
        except OSError:
            continue
        mail = mail_text.read(content, document.mime)
        if mail is not None:
            # Akceptacja klienta bywa tylko w mailu załączonym do maila konsultanta
            # (PKO, próba IX–X 2026): każdy załączony mail to osobna wiadomość.
            mails.extend(mail_text.thread(mail))
    return mails


async def _acceptance(
    result: Optional[rcp_checks.ProofResult],
    reports: list[CpDocument],
    *,
    month: str,
    hours: Optional[Decimal],
    rules: dict[str, dict[str, Any]],
    senders: mail_text.Senders,
    sheet_month: Optional[str] = None,
    people: frozenset[str] = frozenset(),
    person_name: str = "",
) -> Optional[rcp_checks.ProofResult]:
    """``proof.accept_has_hours`` (E6.1): mail akceptacji z liczbą godzin albo MD
    za rozliczany miesiąc, potwierdzony przez klienta (``senders``). Brak =
    zadanie „Popraw akceptację” dla konsultanta.

    Bez takiego maila: zrzut ekranu akceptacji w plikach miesiąca (OCR), gdy
    nadawca na zrzucie to osoba klienta (``senders.people`` i ``people``:
    koordynator z Time Sheet). Id obrazu trafia do ``meta`` dla paczki.
    Konsultant (``person_name``) nie akceptuje sam siebie także na zrzucie: jego
    nazwisko bywa w kontaktach klienta (próba IX–X 2026)."""

    if rules["proof.accept_has_hours"]["level"] == "off":
        return result
    result = result or rcp_checks.ProofResult(md_regular=None, md_extra=None)
    mails = await asyncio.to_thread(_read_mails, reports)
    md = result.md_regular if hours is None else None
    verdict = mail_text.judge(
        mails,
        month=month,
        hours=hours,
        md=md,
        senders=senders,
        sheet_month=sheet_month,
    )
    if not verdict.ok:
        own = rcp_checks.name_tokens(person_name)
        shot = await _screenshot_acceptance(
            reports,
            month=month,
            hours=hours,
            md=md,
            people=frozenset(
                p
                for p in senders.people | people
                if not own or rcp_checks.name_tokens(p) != own
            ),
        )
        if shot is not None:
            verdict, image_id = shot
            result.meta[ACCEPTANCE_IMAGE] = image_id
    group = rcp_checks._Group(result, rules, "Akceptacja")
    if verdict.ok:
        group.ok(verdict.title, verdict.detail)
    else:
        group.fail("proof.accept_has_hours", verdict.title, verdict.detail)
        if group.checks:
            group.checks[-1]["todo"] = "Popraw akceptację"
    group.close()
    return result


#: Klucz w danych przy kontrolach: obraz zrzutu, z którego przeszła akceptacja.
ACCEPTANCE_IMAGE = "acceptance_image"


async def _screenshot_acceptance(
    reports: list[CpDocument],
    *,
    month: str,
    hours: Optional[Decimal],
    md: Optional[Decimal],
    people: frozenset[str],
) -> Optional[tuple[mail_text.Verdict, int]]:
    """Akceptacja ze zrzutu ekranu w plikach miesiąca: najnowsze obrazy, OCR
    tylko wtedy, gdy jest z czym porównać (liczba z dowodu i osoby klienta)."""

    if not people or (hours is None and md is None):
        return None
    images = sorted(
        (d for d in reports if d.mime in screenshot_ocr.IMAGE_MIMES),
        key=lambda d: (d.created_at, d.id),
        reverse=True,
    )
    for document in images[: screenshot_ocr.MAX_IMAGES]:
        try:
            content = portal_documents.path_for(document.file_path).read_bytes()
        except OSError:
            continue
        text = await asyncio.to_thread(
            screenshot_ocr.cached_text, document.sha256, content
        )
        verdict = mail_text.judge_screenshot(
            text, month=month, hours=hours, md=md, people=people
        )
        if verdict is not None:
            return verdict, document.id
    return None


async def _other_md(
    db: AsyncSession, contract: Optional[Contract], month: str
) -> Decimal:
    """MD tej samej osoby u innych klientów w miesiącu (``fields.md_month_limit``)."""

    if contract is None or contract.candidate_id is None:
        return Decimal("0")
    total = await db.scalar(
        select(func.coalesce(func.sum(ClientSettlement.md_regular), 0))
        .join(Contract, Contract.id == ClientSettlement.contract_id)
        .where(
            Contract.candidate_id == contract.candidate_id,
            Contract.client_id != contract.client_id,
            ClientSettlement.period_month == month,
            ClientSettlement.kind == ACTUAL,
            ClientSettlement.status != "needs_fix",
        )
    )
    return Decimal(total or 0)


async def _mails(
    report: Optional[CpDocument], reports: list[CpDocument]
) -> list[acceptance_mail.MailMessage]:
    """Wiadomości z maili miesiąca (E2.3): ``.msg``, ``.eml`` i wydruk PDF poza RCP
    (``report``; ``None`` = wszystkie pliki). PDF bez nagłówków maila (np.
    faktura kosztowa) nic nie wnosi."""

    found: list[acceptance_mail.MailMessage] = []
    for doc in reports:
        if (report is not None and doc.id == report.id) or (
            doc.mime not in acceptance_mail.MIMES
        ):
            continue
        try:
            content = portal_documents.path_for(doc.file_path).read_bytes()
        except OSError:
            continue
        found.extend(await asyncio.to_thread(acceptance_mail.read, content, doc.mime))
    return found


#: Pliki, z których czytnik bierze MD, gdy wybrany plik miesiąca nie jest
#: rozpoznany: oprócz RCP protokół Orlenu w DOCX, mail rozliczeń NN i „.xls”
#: grupy Polkomtel / Cyfrowy Polsat (KEŚU z tym samym typem czyta ``kesu_flow``).
READABLE_MIMES = (*RCP_MIMES, declared.DOCX, *MAIL_MIMES, kesu.KESU_MIME)


async def _proof(
    report: Optional[CpDocument],
    reports: list[CpDocument],
    *,
    month: str,
    person_name: str,
    rules: dict[str, dict[str, Any]],
    other_md: Decimal = Decimal("0"),
    consultant_mails: frozenset[int] = frozenset(),
    senders: mail_text.Senders = mail_text.Senders(),
    fixed: bool = False,
    agreements: frozenset[str] = frozenset(),
) -> Optional[rcp_checks.ProofResult]:
    """Odczyt RCP z pliku i kontrole (E2). Brak pliku RCP = ``None``.

    ``fixed``: projekt FIX — ``senders`` to domeny firmy, a mail akceptujący
    musi mieć słowo akceptacji (``mail_text.approved``), nie tylko nadawcę.
    ``agreements``: umowy wykonawcze tylko tej osoby w miesiącu
    (``_sole_agreements``) — wskazują ją w protokole z innym imieniem.

    Gdy wybranego pliku nie zna żaden czytnik (np. najnowszy plik miesiąca to
    faktura, a protokół przyszedł wcześniej), próbujemy pozostałych plików
    miesiąca. Wynik z innego pliku ma w ``meta["document_id"]`` jego id."""

    working_days = len(business_days(*month_bounds(month)))
    # Mail akceptujący w kontrolach pliku liczy się tylko od klienta (#3820, 23.11).
    if not _client_mail_rules_on(rules):
        client_mail: Optional[bool] = None
    elif fixed:
        mails_text = await asyncio.to_thread(_read_mails, reports)
        client_mail = mail_text.approved(mails_text, senders)
    else:
        client_mail = acceptance_mail.from_client(await _mails(None, reports), senders)
    common = dict(
        reports=reports,
        month=month,
        person_name=person_name,
        rules=rules,
        other_md=other_md,
        working_days=working_days,
        consultant_mails=consultant_mails,
        senders=senders,
        client_mail=client_mail,
        agreements=agreements,
    )
    if report is not None and report.mime in RCP_MIMES:
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
        if parsed is not None:
            bnp = rcp_checks.evaluate(
                parsed,
                signatures,
                mime=report.mime,
                month=month,
                person_name=person_name,
                has_mail=any(d.mime in MAIL_MIMES for d in reports) or bool(mails),
                rules=rules,
                # Domena i data zgody tylko z cudzych wiadomości: prośba konsultanta
                # z jego skrzynki u klienta to nie zgoda klienta.
                mails=[m for m in mails if not senders.is_consultant(m.sender)],
                client_mail=client_mail,
                acceptor=senders.who,
            )
            if bnp.md_regular is not None:
                return bnp
            # Szablon RCP bez MD (np. raport BIK w PDF z tabelą „Imię i nazwisko”):
            # inny czytnik tego pliku może znać jego wzór.
            other = await _read_file(
                report, content, has_mail_extra=bool(mails), **common
            )
            return other if other is not None and other.md_regular is not None else bnp
        result = await _read_file(report, content, has_mail_extra=bool(mails), **common)
        if result is not None:
            return result
    other = await _other_files(report, **common)
    if other is not None:
        return other
    if report is None or report.mime not in RCP_MIMES:
        return await _acceptance(
            None, reports, month=month, hours=None, rules=rules, senders=senders
        )
    return rcp_checks.evaluate(
        None,
        [],
        mime=report.mime,
        month=month,
        person_name=person_name,
        has_mail=False,
        rules=rules,
    )


async def _other_files(
    report: Optional[CpDocument],
    *,
    reports: list[CpDocument],
    **common: Any,
) -> Optional[rcp_checks.ProofResult]:
    """Pierwszy inny plik miesiąca z MD z czytnika; bez MD pierwszy rozpoznany."""

    recognized: Optional[rcp_checks.ProofResult] = None
    tried = report.id if report is not None and report.mime in RCP_MIMES else None
    for doc in reports:
        if doc.id == tried or doc.mime not in READABLE_MIMES:
            continue
        try:
            content = portal_documents.path_for(doc.file_path).read_bytes()
        except OSError:
            continue
        if doc.mime in RCP_MIMES and await asyncio.to_thread(
            rcp_bnp.parse, content, doc.mime
        ):
            continue  # RCP BNP wybiera ``_pick_report``; tu tylko inne wzory.
        result = await _read_file(doc, content, reports=reports, **common)
        if result is None:
            continue
        result.meta["document_id"] = doc.id
        if result.md_regular is not None:
            return result
        recognized = recognized or result
    return recognized


async def _read_file(
    doc: CpDocument,
    content: bytes,
    *,
    reports: list[CpDocument],
    month: str,
    person_name: str,
    rules: dict[str, dict[str, Any]],
    other_md: Decimal,
    working_days: int,
    has_mail_extra: bool = False,
    consultant_mails: frozenset[int] = frozenset(),
    senders: mail_text.Senders = mail_text.Senders(),
    client_mail: Optional[bool] = None,
    agreements: frozenset[str] = frozenset(),
) -> Optional[rcp_checks.ProofResult]:
    """Czytniki wzorów spoza RCP BNP dla jednego pliku; ``None`` = nie rozpoznany.

    ``consultant_mails``: maile od samego konsultanta kontraktu, z których reguła
    ``report.consultant_declaration`` czyta deklarację dni pracy."""

    mime = doc.mime
    has_mail = any(d.mime in MAIL_MIMES for d in reports) or has_mail_extra

    async def accepted(
        result: rcp_checks.ProofResult,
        hours: Optional[Decimal],
        sheet_month: Optional[str],
        people: frozenset[str] = frozenset(),
    ) -> rcp_checks.ProofResult:
        """``sheet_month``: miesiąc pliku z godzinami (akceptacja bez liczby).
        ``people``: osoby klienta z pliku (koordynator), nadawcy zrzutu akceptacji."""

        return await _acceptance(
            result,
            reports,
            month=month,
            hours=hours,
            rules=rules,
            senders=senders,
            sheet_month=sheet_month,
            people=people,
            person_name=person_name,
        )

    def declared_result(found: declared.Declared) -> rcp_checks.ProofResult:
        return declared.evaluate(
            found,
            month=month,
            person_name=person_name,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
        )

    if mime == kesu.KESU_MIME:
        # Raport Polkomtelu (HTML) albo rozliczenie Cyfrowego Polsatu (XML), oba „.xls”.
        sheet = await asyncio.to_thread(timesheet_plus.parse, content)
        found_plus = timesheet_plus.declared_for(sheet, person_name) if sheet else None
        if found_plus is None:
            return None
        return await accepted(
            declared_result(found_plus), found_plus.hours, found_plus.month
        )
    if mime in MAIL_MIMES:
        # Mail koordynatora z godzinami zaakceptowanymi przez klienta (CeZ).
        summary = await asyncio.to_thread(hours_summary.parse, content, mime)
        if summary is not None:
            found_summary = protocol_collective.evaluate(
                summary,
                month=month,
                doc_month=_doc_month(doc),
                person_name=person_name,
                rules=rules,
                working_days=working_days,
                other_md=other_md,
            )
            if found_summary is not None:
                return found_summary
        # Akceptacja klienta z MD w treści (NN).
        nn = await asyncio.to_thread(mail_nn.parse, content, mime)
        if nn is not None:
            return declared_result(nn)
        # Deklaracja konsultanta w treści maila (reguła klienta, mLeasing 23.11.2026).
        if doc.id not in consultant_mails or not _on(rules, mail_declaration.RULE):
            return None
        said = await asyncio.to_thread(mail_declaration.parse, content, mime, month)
        if said is None:
            return None
        return mail_declaration.evaluate(
            said,
            month=month,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
        )
    if mime == declared.DOCX:
        orlen = await asyncio.to_thread(protocol_orlen.parse, content, mime)
        if orlen is None:
            return None
        return await accepted(declared_result(orlen), orlen.hours, orlen.month)
    # Protokół odbioru zbiorczy (CeZ, PFRON): godziny kilku osób w jednym PDF-ie.
    protocol = await asyncio.to_thread(protocol_collective.parse, content, mime)
    if protocol is not None:
        return protocol_collective.evaluate(
            protocol,
            month=month,
            doc_month=_doc_month(doc),
            person_name=person_name,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
            agreements=agreements,
        )
    # Raport zbiorczy Credit Agricole: kilka osób w jednym arkuszu, MD z „TE”.
    ca = await asyncio.to_thread(report_ca.parse, content, mime)
    if ca is not None:
        return report_ca.evaluate(
            ca,
            month=month,
            person_name=person_name,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
        )
    # KCP Banku Pocztowego albo eksport Redmine, z którego KCP składa NEXUS (E6.5).
    card = await asyncio.to_thread(redmine_timelog.read_card, content, mime, month)
    if card is not None:
        found, outside = card
        return kcp.evaluate(
            found,
            month=month,
            person_name=person_name,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
            outside_month=outside,
        )
    # Szablon klienta w godzinach z makrami (E6.1, PKO).
    pko = await asyncio.to_thread(timesheet_pko.parse, content, mime)
    if pko is not None:
        result = timesheet_pko.evaluate(
            pko,
            month=month,
            person_name=person_name,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
            file_name=doc.file_name,
        )
        return await accepted(
            result,
            pko.total_hours if pko.entries else None,
            timesheet_pko.sheet_month(pko, month, doc.file_name),
            pko.acceptors,
        )
    # Tygodnie z SAP Fieldglass (EY): eksport „timeSheet.worker.list”.
    fieldglass = await asyncio.to_thread(timesheet_fieldglass.parse, content, mime)
    if fieldglass is not None:
        result = timesheet_fieldglass.evaluate(
            fieldglass,
            month=month,
            person_name=person_name,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
        )
        md = result.md_regular
        return await accepted(
            result, md * timesheet.per_md(rules) if md else None, month if md else None
        )
    # Time Sheet w godzinach (E6.2): XLSX, polski wariant albo PDF.
    sheet = await asyncio.to_thread(timesheet.parse, content, mime)
    if sheet is not None:
        result = timesheet.evaluate(
            sheet,
            month=month,
            person_name=person_name,
            has_mail=has_mail,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
            client_mail=client_mail,
            acceptor=senders.who,
        )
        return await accepted(
            result, sheet.total_hours if sheet.entries else None, sheet.month
        )
    # Raport godzin BIK: szablon klienta, jego PDF albo tabela dni.
    bik = await asyncio.to_thread(timesheet_bik.parse, content, mime)
    if bik is not None:
        result = timesheet_bik.evaluate(
            bik,
            month=month,
            person_name=person_name,
            rules=rules,
            working_days=working_days,
            other_md=other_md,
        )
        return await accepted(
            result, bik.total_hours if bik.total_hours > 0 else None, bik.month
        )
    # Potwierdzenie godzin ERGO, protokół Orlenu i ewidencja czasu Orlenu w PDF.
    for reader in (confirmation_ergo, protocol_orlen, ewidencja_orlen):
        found_doc = await asyncio.to_thread(reader.parse, content, mime)
        if found_doc is not None:
            return await accepted(
                declared_result(found_doc), found_doc.hours, found_doc.month
            )
    return None


def _doc_month(doc: CpDocument) -> Optional[str]:
    """Okres dokumentu z nazwy pliku albo tematu; zgadnięty z daty maila = brak."""

    if doc.period_guessed or doc.period_year is None or doc.period_month is None:
        return None
    return f"{doc.period_year}-{doc.period_month:02d}"


def _on(rules: dict[str, dict[str, Any]], key: str) -> bool:
    return rules[key]["level"] != "off"


#: Kontrole, które potrzebują domen klienta (``acceptance_senders``).
CLIENT_MAIL_RULES = (
    "proof.accept_has_hours",
    "proof.excel_with_mail",
    "extra.mail_accept",
)


def _client_mail_rules_on(rules: dict[str, dict[str, Any]]) -> bool:
    return any(_on(rules, key) for key in CLIENT_MAIL_RULES)


#: Kto akceptuje godziny w projekcie FIX (decyzja Artura z 24.11.2026).
FIX_ACCEPTOR = "PM-a firmy"


def fix_senders() -> mail_text.Senders:
    """Projekt FIX: klient odbiera produkt protokołem, godziny podwykonawcy to
    koszt firmy i akceptuje je ktoś z firmy (zwykle PM). Akceptujący = domeny
    firmy (``identity._company_domains`` i SSO), ze słowem akceptacji w mailu."""

    from app.core.config import settings
    from app.services.consultant_portal import identity
    from app.services.m365.matcher import PUBLIC_EMAIL_DOMAINS

    company = identity._company_domains() | set(settings.sso_allowed_domains_list)
    # Bez skonfigurowanych domen firmy ``Senders`` przyjąłby każdy adres spoza
    # ``own``; poczta publiczna (podwykonawca z gmaila) nigdy nie akceptuje.
    return mail_text.Senders(
        client=frozenset(d for d in company if d),
        own=frozenset(PUBLIC_EMAIL_DOMAINS),
        who=FIX_ACCEPTOR,
    )


def _fix_note(proof: rcp_checks.ProofResult, rules: dict[str, dict[str, Any]]) -> None:
    group = rcp_checks._Group(proof, rules, "Projekt FIX")
    group.info(
        "Godziny to koszt firmy: akceptuje PM firmy",
        "Kontrakt w modelu „FIX / produkt”. Klient odbiera produkt protokołem "
        "odbioru, więc faktura do klienta idzie z protokołu, nie z godzin. "
        "Limit MD etapu pilnuje zamówienie MD etapu.",
    )
    group.close()


async def acceptance_senders(
    db: AsyncSession, client_id: int, rules: dict[str, dict[str, Any]]
) -> mail_text.Senders:
    """Domeny, z których klient akceptuje godziny (``proof.accept_has_hours``).

    Domena z ``proof.excel_with_mail``, ``extra.mail_accept`` i adresu
    ``cl.client_acceptance``, domeny
    kontaktów klienta i rejestru domen klientów (``known_clients``, po NIP-ie).
    Domeny firmy, skrzynek konsultantów u klienta i poczty publicznej nie należą
    do klienta: piszą z nich nasi ludzie i konsultanci."""

    from app.core.config import settings
    from app.services import support_mail_route
    from app.services.consultant_portal import identity
    from app.services.m365.matcher import PUBLIC_EMAIL_DOMAINS
    from app.services.order_policies import known_clients

    own = (
        identity._company_domains()
        | identity._personal_domains()
        | set(settings.sso_allowed_domains_list)
        | PUBLIC_EMAIL_DOMAINS
    )
    found = {
        domain
        for key in ("proof.excel_with_mail", "extra.mail_accept")
        for domain in acceptance_mail.domains(
            str(rules[key]["params"].get("domain") or "")
        )
    }
    email = str(rules["cl.client_acceptance"]["params"].get("email") or "")
    if "@" in email:
        found.add(email.strip().lower().rpartition("@")[2])
    found.update(await support_mail_route._contact_domains(db, client_id))
    nip = await db.scalar(select(Client.nip).where(Client.id == client_id))
    number = re.sub(r"[\s-]", "", nip or "").upper()
    keys = {
        key for key, ids in known_clients.KNOWN_REGISTRY_IDS.items() if number in ids
    }
    found.update(
        d for d, key in known_clients.KNOWN_SENDER_DOMAINS.items() if key in keys
    )
    # Nadawca zrzutu ekranu akceptacji widać tylko z nazwiska (decyzja Artura z 24.11).
    people = await db.scalars(
        select(Contact.name).where(Contact.client_id == client_id, Contact.name != "")
    )
    return mail_text.Senders(
        client=frozenset(d for d in found if d and d not in own),
        own=frozenset(own),
        people=frozenset(name.strip() for name in people if name and name.strip()),
    )


async def _mail_addresses(reports: list[CpDocument]) -> set[str]:
    """Adresy nadawców z maili miesiąca: sam mail, cytaty, maile w mailu, wydruk PDF."""

    found = {m.sender for m in await _mails(None, reports) if m.sender}
    texts = await asyncio.to_thread(_read_mails, reports)
    return found | mail_text.addresses(texts)


async def _without_consultant(
    db: AsyncSession,
    senders: mail_text.Senders,
    reports: list[CpDocument],
    contract_id: int,
    month: str,
) -> mail_text.Senders:
    """``senders`` bez samego konsultanta kontraktu (próba IX–X 2026).

    U kilku klientów konsultant ma skrzynkę w domenie klienta, tej samej co
    kierownik. Jego mail z fakturą albo cytat jego wiadomości wyglądał jak
    wiadomość klienta, a jego „Potwierdzam” jak akceptacja. Adres należy do
    konsultanta, gdy czytnik poczty wskazuje nim ten kontrakt
    (``identity.sender_contract_ids``, jak ``mailbox._client_wrote``). Pytamy tylko
    o adresy, które ``senders`` przyjąłby jako akceptującego. Dzień z perspektywy
    rozliczanego miesiąca: przeliczenie po 60 dniach od końca kontraktu nadal
    rozpoznaje jego konsultanta."""

    from app.core.scheduling import business_today
    from app.services.consultant_portal import identity

    candidates = sorted(
        a for a in await _mail_addresses(reports) if senders.accepts_from(a)
    )
    if not candidates:
        return senders
    today = min(business_today(), month_bounds(month)[1])
    mine: set[str] = set()
    for address in candidates:
        if contract_id in await identity.sender_contract_ids(db, address, today=today):
            mine.add(address)
    return replace(senders, consultant=senders.consultant | mine) if mine else senders


async def _consultant_mails(
    db: AsyncSession,
    reports: list[CpDocument],
    contract_id: int,
    rules: dict[str, dict[str, Any]],
) -> frozenset[int]:
    """Maile miesiąca, których nadawca to konsultant tego kontraktu (adres
    z kontraktu, z kartoteki albo skrzynka firmowa). Tylko przy włączonej
    ``report.consultant_declaration``: deklaracja od kogoś innego nie liczy się."""

    if not _on(rules, mail_declaration.RULE):
        return frozenset()
    from app.core.scheduling import business_today
    from app.services.consultant_portal import identity

    today = business_today()
    found: set[int] = set()
    for doc in reports:
        if doc.mime not in MAIL_MIMES or not doc.sender_email:
            continue
        if contract_id in await identity.sender_contract_ids(
            db, doc.sender_email, today=today
        ):
            found.add(doc.id)
    return frozenset(found)


# ── Podział na zamówienia z maila klienta ────────────────────────────────────

#: Nazwa dowodu na karcie, gdy MD daje sam podział (BIK X 2026).
SPLIT_SOURCE = "Podział na zamówienia z maila klienta"


async def _mail_splits(
    reports: list[CpDocument],
) -> list[tuple[CpDocument, order_split.Split]]:
    """Podziały na zamówienia z maili miesiąca, najnowsze pierwsze (jak ``reports``)."""

    found: list[tuple[CpDocument, order_split.Split]] = []
    for doc in reports:
        if doc.mime not in MAIL_MIMES:
            continue
        try:
            content = portal_documents.path_for(doc.file_path).read_bytes()
        except OSError:
            continue
        split = await asyncio.to_thread(order_split.parse, content, doc.mime)
        if split is not None:
            found.append((doc, split))
    return found


def _split_row(
    splits: list[tuple[CpDocument, order_split.Split]],
    *,
    person_name: str,
    month: str,
    senders: mail_text.Senders,
) -> Optional[tuple[CpDocument, order_split.Split, order_split.Row]]:
    """Najnowszy podział osoby za miesiąc od klienta (``senders``). Zamówienia
    wskazuje klient, więc podział napisany u nas, bez cytatu klienta, nie wchodzi."""

    for doc, split in splits:
        row = order_split.row_for(split, person_name)
        if row is None or not senders.accepts_from(split.author):
            continue
        if split.month is not None and split.month != month:
            continue
        return doc, split, row
    return None


def _row_unit(
    split: order_split.Split,
    row: order_split.Row,
    md: Optional[Decimal],
    per_md: Decimal,
) -> str:
    """Jednostka liczb z tabeli bez jednostki. Przy MD rozliczenia: godziny, gdy
    dopiero suma wiersza / godziny w MD daje te MD, inaczej MD. Bez MD rozliczenia
    raz dla całej tabeli: MD, gdy każdy wiersz mieści się w miesiącu (``MD_MAX``),
    bo w tabeli w godzinach osoba z 16 h nie może dostać 16 MD."""

    if md is not None:
        total = order_split.total(row)
        as_hours = abs(total / per_md - Decimal(md)) < Decimal("0.001")
        as_md = abs(total - Decimal(md)) < Decimal("0.001")
        return order_split.HOURS if as_hours and not as_md else order_split.MD
    if all(order_split.total(r) <= MD_MAX for r in split.rows):
        return order_split.MD
    return order_split.HOURS


def _part_md(part: order_split.Part, unit: str, per_md: Decimal) -> Decimal:
    return (
        part.value / per_md if (part.unit or unit) == order_split.HOURS else part.value
    )


def _order_rank(
    order: ClientOrder, first: date, last: date
) -> tuple[bool, bool, int, int]:
    """Kolejność linii o tym samym numerze: trwająca w miesiącu, aktywna, najnowsza."""

    overlaps = (order.start_date is None or order.start_date <= last) and (
        order.end_date is None or order.end_date >= first
    )
    start = order.start_date.toordinal() if order.start_date else 0
    return (not overlaps, order.status != ClientOrderStatus.active, -start, -order.id)


async def _split_parts(
    db: AsyncSession,
    s: ClientSettlement,
    split: order_split.Split,
    row: order_split.Row,
    rules: dict[str, dict[str, Any]],
) -> tuple[tuple[SplitPart, ...], Optional[str]]:
    """Części podziału na liniach zamówień osoby: ``(części, powód odmowy)``.

    Numer z maila (z grupy zamówienia albo z tytułu linii bez grupy) szukamy
    wśród linii kontraktu w statusach jak ``_order_for``, także zakończonych
    i spoza miesiąca: klient wie, na które zamówienie fakturuje (decyzja Artura
    z 24.11.2026, też przy jednym numerze w mailu). Numer, którego osoba nie ma
    w NEXUS-ie, albo dwa numery na jednej linii = bez podziału, MD idą na jedno
    zamówienie."""

    first, last = month_bounds(s.period_month)
    found = (
        await db.execute(
            select(ClientOrder, ClientOrderGroup.order_number)
            .outerjoin(
                ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id
            )
            .where(
                ClientOrder.contract_id == s.contract_id,
                ClientOrder.status.in_(ORDER_STATUSES),
            )
        )
    ).all()
    by_key: dict[str, list[ClientOrder]] = defaultdict(list)
    numbers: dict[int, str] = {}
    for line, number in found:
        shown = number or number_from_title(line.title)
        key = order_split.order_key(shown)
        if key is not None and shown:
            by_key[key].append(line)
            numbers[line.id] = shown
    per_md = timesheet.per_md(rules)
    unit = _row_unit(split, row, s.md_regular, per_md)
    parts: list[SplitPart] = []
    missing: list[str] = []
    for part in row.parts:
        lines = by_key.get(order_split.order_key(part.order) or "")
        if not lines:
            missing.append(part.order)
            continue
        line = min(lines, key=lambda o: _order_rank(o, first, last))
        state = await _order_state(
            db, await priced_one(db, line, first), s.period_month
        )
        if state is not None and state.number is None:
            # Linia bez grupy (PKO, Velo): numer z tytułu, jak na liście miesiąca.
            state = replace(state, number=numbers[line.id])
        closed = line.status == ClientOrderStatus.completed or (
            line.end_date is not None and line.end_date < first
        )
        if state is not None:
            parts.append(SplitPart(state, _part_md(part, unit, per_md), closed=closed))
    if missing:
        return (), (
            f"Mail klienta wskazuje zamówienie {', '.join(missing)}, którego ta osoba "
            "nie ma w NEXUS-ie: dodaj linię zamówienia albo popraw numer. Do tego "
            "czasu MD idą na jedno zamówienie."
        )
    if len({p.order.order_id for p in parts}) != len(parts):
        return (), (
            "Dwa numery z maila klienta wskazują tę samą linię zamówienia w NEXUS-ie: "
            "MD idą na jedno zamówienie, podziel je ręcznie."
        )
    return tuple(parts), None


async def _split_proof(
    doc: CpDocument,
    split: order_split.Split,
    row: order_split.Row,
    reports: list[CpDocument],
    *,
    month: str,
    person_name: str,
    rules: dict[str, dict[str, Any]],
    senders: mail_text.Senders,
    other_md: Decimal,
) -> rcp_checks.ProofResult:
    """MD z podziału, gdy żaden plik miesiąca nie dał liczby (BIK X 2026: jedyny
    dokument to odpowiedź klienta „Akceptuję” z godzinami na zamówienia).

    Kontrole jak przy dokumencie z deklarowaną sumą (``declared``): miesiąc,
    osoba (wiersz tabeli albo imię i nazwisko w temacie wątku), limit MD; do tego
    ``proof.accept_has_hours`` na mailach miesiąca."""

    per_md = timesheet.per_md(rules)
    unit = _row_unit(split, row, None, per_md)
    units = {part.unit or unit for part in row.parts}
    hours = order_split.total(row) if units == {order_split.HOURS} else None
    named = row.person
    if named is None and rcp_checks.name_tokens(person_name) <= rcp_checks.name_tokens(
        split.subject
    ):
        named = person_name
    found = declared.Declared(
        source=SPLIT_SOURCE,
        consultant=named,
        month=split.month or _doc_month(doc),
        hours=hours,
        md=None
        if hours is not None
        else sum((_part_md(p, unit, per_md) for p in row.parts), Decimal("0")),
    )
    result = declared.evaluate(
        found,
        month=month,
        person_name=person_name,
        rules=rules,
        working_days=len(business_days(*month_bounds(month))),
        other_md=other_md,
    )
    accepted = await _acceptance(
        result,
        reports,
        month=month,
        hours=hours,
        rules=rules,
        senders=senders,
        sheet_month=found.month,
    )
    return accepted or result


async def _proof_senders(
    db: AsyncSession,
    s: ClientSettlement,
    rules: dict[str, dict[str, Any]],
    fixed: bool,
    reports: list[CpDocument],
) -> mail_text.Senders:
    """Akceptujący dla kontroli pliku: PM firmy przy FIX, domeny klienta przy
    regułach akceptacji mailowej, zawsze bez samego konsultanta (#3884)."""

    if fixed:
        senders = fix_senders()
    elif _client_mail_rules_on(rules):
        senders = await acceptance_senders(db, s.client_id, rules)
    else:
        return mail_text.Senders()
    return await _without_consultant(
        db, senders, reports, s.contract_id, s.period_month
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
            await _sync_kesu_extra(db, s, proof.meta["kesu"])
    fixed = (
        person.contract is not None
        and person.contract.engagement_model == EngagementModel.fixed
    )
    senders = mail_text.Senders()
    if proof is None:
        senders = await _proof_senders(db, s, rules, fixed, reports)
        proof = await _proof(
            report,
            reports,
            month=s.period_month,
            person_name=person.name,
            rules=rules,
            other_md=await _other_md(db, person.contract, s.period_month),
            consultant_mails=await _consultant_mails(db, reports, s.contract_id, rules),
            senders=senders,
            fixed=fixed,
            agreements=await _sole_agreements(db, s.contract_id, s.period_month),
        )
        if proof is not None and fixed:
            _fix_note(proof, rules)
        if proof is not None and (source := proof.meta.pop("document_id", None)):
            # MD z innego pliku miesiąca niż wybrany: ten plik jest dowodem.
            report = next((d for d in reports if d.id == source), report)
    # Podział na zamówienia z maila klienta (próba IX–X 2026: BIK, Polkomtel).
    splits = await _mail_splits(reports)
    hit = (
        _split_row(
            splits,
            person_name=person.name,
            month=s.period_month,
            # Zamówienia wskazuje klient: nie sam konsultant ze skrzynki u klienta.
            senders=await _without_consultant(
                db,
                await acceptance_senders(db, s.client_id, rules),
                reports,
                s.contract_id,
                s.period_month,
            ),
        )
        if splits
        else None
    )
    if hit is not None and not fixed and (proof is None or proof.md_regular is None):
        # Żaden plik nie dał MD: liczba z podziału od klienta (akceptację liczb
        # sprawdza jak przy innych dokumentach ``proof.accept_has_hours``).
        from_split = await _split_proof(
            *hit,
            reports,
            month=s.period_month,
            person_name=person.name,
            rules=rules,
            senders=await _proof_senders(db, s, rules, fixed, reports),
            other_md=await _other_md(db, person.contract, s.period_month),
        )
        if from_split.md_regular is not None:
            proof, report = from_split, hit[0]
    s.report_document_id = report.id if report else None
    # Wpis Finansów wygrywa z odczytem pliku; bez wpisu MD bierzemy z RCP.
    if proof is not None and proof.md_regular is not None and s.md_source != "manual":
        s.md_regular = proof.md_regular
        s.md_extra = proof.md_extra or None
        s.md_source = "rcp"
    proof = _signed_checks(proof, s, rules)
    proof = await _copyright_checks(proof, reports, s.period_month, rules)
    proof = await _rate_change_checks(db, s, proof, rules)
    split: tuple[SplitPart, ...] = ()
    if hit is not None and s.md_regular is not None:
        split, problem = await _split_parts(db, s, hit[1], hit[2], rules)
        if problem is not None:
            proof = proof or rcp_checks.ProofResult(md_regular=None, md_extra=None)
            group = rcp_checks._Group(proof, rules, "Podział na zamówienia")
            group.warn("Podział z maila klienta nie wszedł", problem)
            group.close()
    result = compute(
        Inputs(
            md_regular=s.md_regular,
            md_extra=s.md_extra,
            rules=rules,
            order=state,
            onboarding_used_before=await _onboarding_used(
                db, s.contract_id, s.period_month
            ),
            has_report=report is not None or signoffs.marker(s.checks) is not None,
            onboarding_eligible=_onboarding_eligible(
                person.contract,
                s.period_month,
                rule_in_start_month=await _onboarding_rule_in_start_month(
                    db, s.client_id, person.contract, s.period_month
                ),
            ),
            proof=proof,
            split=split,
        )
    )
    return result, state, order


async def _rate_change_checks(
    db: AsyncSession,
    s: ClientSettlement,
    proof: Optional[rcp_checks.ProofResult],
    rules: dict[str, dict[str, Any]],
) -> Optional[rcp_checks.ProofResult]:
    """Stawka kontraktora zmienia się w trakcie miesiąca (harmonogram kontraktu).

    Kwota kosztu idzie z jednej stawki linii zamówienia, a zapłacono po dwóch stawkach
    (próba IX–X 2026: zmiana 17.09 ze 100 na 105 zł/h, NEXUS liczył całość po 100 i dawał
    „ok”). Uwaga zamiast cichej złej kwoty: Finanse dzielą rozliczenie albo poprawiają kwotę.
    """

    first, last = month_bounds(s.period_month)
    steps = (
        await db.execute(
            select(ContractCandidateRate.effective_from, ContractCandidateRate.rate)
            .where(
                ContractCandidateRate.contract_id == s.contract_id,
                ContractCandidateRate.effective_from <= last,
            )
            .order_by(ContractCandidateRate.effective_from, ContractCandidateRate.id)
        )
    ).all()
    changes = [(day, rate) for day, rate in steps if first < day <= last]
    if not changes:
        return proof
    before = [rate for day, rate in steps if day <= first]
    proof = proof or rcp_checks.ProofResult(md_regular=None, md_extra=None)
    group = rcp_checks._Group(proof, rules, "Stawka kontraktora")
    old = rcp_checks._fmt(Decimal(before[-1])) if before else "?"
    for day, rate in changes:
        group.warn(
            f"Zmiana stawki {day:%d.%m}: {old} → {rcp_checks._fmt(Decimal(rate))}",
            "Kwota kosztu liczy się z jednej stawki zamówienia. Podziel rozliczenie "
            "na dni przed i po zmianie albo popraw kwotę przed zapłatą.",
        )
        old = rcp_checks._fmt(Decimal(rate))
    group.close()
    return proof


def _signed_checks(
    proof: Optional[rcp_checks.ProofResult],
    s: ClientSettlement,
    rules: dict[str, dict[str, Any]],
) -> Optional[rcp_checks.ProofResult]:
    """Arkusz zbiorczy osoby (E6.2, Velo): ``pay.per_person`` — zapłata po
    podpisanym arkuszu tej osoby, bez czekania na pozostałe."""

    if rules["pay.per_person"]["level"] == "off":
        return proof
    proof = proof or rcp_checks.ProofResult(md_regular=None, md_extra=None)
    group = rcp_checks._Group(proof, rules, "Arkusz zbiorczy")
    signed = signoffs.signed_state(s.checks, signoffs.SHEET)
    if signed and signed.get("complete"):
        when = str(signed.get("signed_at") or "")[:10]
        when = f"{when[8:10]}.{when[5:7]}" if len(when) == 10 else ""
        group.ok(
            "Arkusz podpisany przez klienta"
            + (f": {signed['signer']}" if signed.get("signer") else "")
            + (f", {when}" if when else ""),
        )
        md = signed.get("md")
        if (
            md
            and s.md_regular is not None
            and abs(Decimal(md) - Decimal(s.md_regular)) > Decimal("0.005")
        ):
            group.warn(
                f"W arkuszu {rcp_checks._fmt(Decimal(md))} MD, w Time Sheet "
                f"{rcp_checks._fmt(Decimal(s.md_regular))} MD",
                "Do zapłaty i faktury idzie MD z rozliczenia; sprawdź, który zapis jest dobry.",
            )
    else:
        group.fail(
            "pay.per_person",
            "Arkusz czeka na podpis klienta",
            "Zapłata po podpisanym arkuszu tej osoby.",
        )
    group.close()
    return proof


async def _copyright_checks(
    proof: Optional[rcp_checks.ProofResult],
    reports: list[CpDocument],
    month: str,
    rules: dict[str, dict[str, Any]],
) -> Optional[rcp_checks.ProofResult]:
    """``cl.copyright_statement`` (CeZ): oświadczenie o przeniesieniu autorskich
    praw majątkowych za miesiąc wśród plików osoby. Brak albo błąd wzoru = uwaga."""

    if rules["cl.copyright_statement"]["level"] == "off":
        return proof
    first, last = month_bounds(month)
    found: Optional[list[copyright_statement.Finding]] = None
    for doc in reports:
        if doc.mime not in ("application/pdf", declared.DOCX):
            continue
        try:
            content = portal_documents.path_for(doc.file_path).read_bytes()
        except OSError:
            continue
        pdf = doc.mime == "application/pdf"
        reader = declared.pdf_text if pdf else declared.docx_text
        text = await asyncio.to_thread(reader, content) or ""
        if not copyright_statement.is_statement(doc.file_name or "", text):
            continue
        signed = await asyncio.to_thread(rcp_bnp.signatures, content) if pdf else []
        findings = copyright_statement.judge(
            copyright_statement.parse(text),
            first=first,
            last=last,
            signed_at=[x.signed_at for x in signed if x.signed_at is not None],
        )
        if found is None or [f.state for f in findings] == ["ok"]:
            found = findings
    proof = proof or rcp_checks.ProofResult(md_regular=None, md_extra=None)
    group = rcp_checks._Group(proof, rules, "Oświadczenie o prawach autorskich")
    key = "cl.copyright_statement"
    if found is None:
        group.fail(
            key,
            "Brak oświadczenia o prawach autorskich",
            "CeZ przyjmuje fakturę z oświadczeniem każdej osoby na wzorze CeZ, "
            "podpisanym po końcu miesiąca, osobno na każdą umowę wykonawczą.",
        )
    for finding in found or []:
        if finding.state == "ok":
            group.ok(finding.title, finding.detail)
        else:
            group.fail(key, finding.title, finding.detail)
    group.close()
    return proof


async def recompute_and_store(db: AsyncSession, s: ClientSettlement) -> None:
    result, state, _order = await _recompute(db, s)
    _store(s, result, state)
    if s.md_regular is None:
        s.status = "checking"


async def contracts_with_settlement(
    db: AsyncSession, client_id: int, month: str
) -> set[int]:
    return set(
        (
            await db.scalars(
                select(ClientSettlement.contract_id).where(
                    ClientSettlement.client_id == client_id,
                    ClientSettlement.period_month == month,
                    ClientSettlement.kind == ACTUAL,
                    ClientSettlement.status != "needs_fix",
                )
            )
        ).all()
    )


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
    db: AsyncSession,
    contract_id: int,
    order_ids: set[int],
    month: str,
    *,
    own: frozenset[int] = frozenset(),
) -> list[ClientOrder]:
    """Miesiąc podzielony między zamówienia osoby poza tym przyjęciem (import przy
    zmianie zamówienia, ``apply_md_consumption``): przyjęcie nadpisałoby swoje
    linie, a wpis innej zostałby — MD liczone dwa razy. Odmawiamy (FIN-MD-01).

    Wyjątek to własny podział: wpis ``settlement`` na linii, z której zdjęło MD
    wcześniejsze przyjęcie tego rozliczenia (``own``, np. podział z maila klienta
    zmienił zamówienia). Takie linie zwracamy do wyzerowania."""

    rows = (
        await db.execute(
            select(ClientOrderMdConsumption.source, ClientOrder)
            .join(ClientOrder, ClientOrder.id == ClientOrderMdConsumption.order_id)
            .where(
                ClientOrder.contract_id == contract_id,
                ClientOrder.id.not_in(order_ids),
                ClientOrderMdConsumption.period_month == month,
                ClientOrderMdConsumption.md_reported != 0,
            )
        )
    ).all()
    stale: list[ClientOrder] = []
    for source, line in rows:
        if source != SOURCE_SETTLEMENT or line.id not in own:
            raise SettlementError(
                "Ten miesiąc ma już zejście MD na innym zamówieniu tej osoby "
                "(podział przy zmianie zamówienia). Popraw zejście w zamówieniach; "
                "przyjęcie nadpisałoby jedną linię i MD policzyłyby się dwa razy."
            )
        stale.append(line)
    return stale


def _session_order(order: Any) -> ClientOrder:
    """Linia zamówienia z sesji. ``PricedOrder`` (stawka z dnia miesiąca) jest
    tylko do odczytu, a zejście zapisuje na linii ``md_remaining``."""

    return order._order if isinstance(order, PricedOrder) else order


async def _charge(
    db: AsyncSession,
    s: ClientSettlement,
    order: ClientOrder,
    md: Decimal,
    *,
    month: str,
    actor_id: Optional[int],
    auto: bool,
    split: bool,
) -> None:
    """Zejście MD miesiąca z linii zamówienia (nadpisanie miesiąca) i wpis w historii grupy."""

    _row_, previous, remaining = await upsert_consumption(
        db,
        order=order,
        period_month=month,
        md_reported=md,
        source=SOURCE_SETTLEMENT,
        user_id=actor_id,
        status="accepted",
        note="Przyjęte RCP (Rozliczenia, automat)"
        if auto
        else "Przyjęte RCP (Rozliczenia)",
    )
    if order.order_group_id is None:
        return
    overwritten = (
        f", nadpisano wcześniejsze {format_md(previous)} MD"
        if previous and previous != md
        else ""
    )
    record_event(
        db,
        group_id=order.order_group_id,
        order_id=order.id,
        event_type=EVENT_MANUAL_EDIT,
        description=(
            f"Rozliczenia — zejście MD za {format_period_month(month)}: "
            f"{format_md(md)} MD z przyjętego RCP"
            + (" (podział według maila klienta)" if split else "")
            + f"{overwritten}. Pozostało {format_md(remaining)} MD."
            + (
                " Przyjął automat (reguła klienta „Przyjmuj RCP bez uwag "
                "automatycznie”)."
                if auto
                else ""
            )
        ),
        payload={
            "changed": ["zejście MD"],
            "period_month": month,
            "md_reported": str(md),
            "previous": str(previous),
            "source": SOURCE_SETTLEMENT,
            "settlement_id": s.id,
            "md_remaining": str(remaining),
            **({"auto": True} if auto else {}),
            **({"split": True} if split else {}),
        },
        user_id=actor_id,
    )


async def accept(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    actor: Optional[User],
    now: datetime,
    kind: str = ACTUAL,
    require_clean: bool = False,
    auto: bool = False,
) -> ClientSettlement:
    """Przyjęcie RCP. ``actor=None`` z ``auto=True`` to automat
    ``order.auto_accept_clean``; ``require_clean`` odmawia, gdy przeliczenie
    dało coś innego niż „Bez uwag”."""

    actor_id = actor.id if actor is not None else None
    s = await _settlement(db, contract_id, month, kind=kind, for_update=True)
    if s is None or s.md_regular is None:
        raise SettlementError("Najpierw wpisz MD z RCP.")
    if auto and meta_of(s).get(AUTO_ACCEPT_OFF):
        raise SettlementError("Po „Do poprawy” RCP przyjmują Finanse.")
    result, state, order = await _recompute(db, s)
    _store(s, result, state)
    if require_clean and result.status != "ok":
        raise SettlementError(
            "RCP ma uwagi po przeliczeniu: przyjmij je na karcie osoby."
        )
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
    # Podział z maila klienta: zejście z każdej linii osobno; bez niego jedna linia.
    parts = [(int(o["order_id"]), Decimal(str(o["md"]))) for o in result.orders]
    if not parts and order is not None and result.md_charged is not None:
        parts = [(order.id, result.md_charged)]
    if (
        parts
        and result.md_charged is not None
        and rules["order.charge_on_accept"]["level"] != "off"
    ):
        stale = await _refuse_split_month(
            db,
            contract_id,
            {order_id for order_id, _md in parts},
            month,
            own=frozenset(int(i) for i in meta_of(s).get(CHARGED_ORDERS) or []),
        )
        split = bool(result.orders)
        for line in stale:
            await _charge(
                db,
                s,
                line,
                Decimal("0"),
                month=month,
                actor_id=actor_id,
                auto=auto,
                split=True,
            )
        for order_id, md in parts:
            line = (
                _session_order(order)
                if order is not None and order.id == order_id
                else await db.get(ClientOrder, order_id)
            )
            if line is not None:
                await _charge(
                    db,
                    s,
                    line,
                    md,
                    month=month,
                    actor_id=actor_id,
                    auto=auto,
                    split=split,
                )
        # Wyjątek od FIN-MD-01 dotyczy tylko własnego podziału: linie zapamiętujemy
        # przy podziale, przy jednym zamówieniu zostaje dzisiejsza odmowa.
        _set_meta(
            s,
            CHARGED_ORDERS,
            sorted(order_id for order_id, _md in parts) if split else None,
        )
    s.status = "accepted"
    s.accepted_by = actor_id
    s.accepted_at = now
    s.updated_by = actor_id
    _set_meta(s, AUTO_ACCEPTED, now.isoformat() if auto else None)
    if s.report_document_id is not None:
        document = await db.get(CpDocument, s.report_document_id)
        if document is not None and document.status == "received":
            await portal_documents.accept(db, document.id, actor_id=actor_id, now=now)
    # Maile z akceptacją i inne pliki miesiąca idą razem z RCP, ale bez drugiego
    # maila „możesz wystawić fakturę” (inaczej ich karty wisiałyby w back office).
    for other in await _month_reports(db, contract_id, month, kind=kind):
        if other.id != s.report_document_id and other.status == "received":
            other.status = "accepted"
            other.decided_by = actor_id
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
    _set_meta(s, AUTO_ACCEPT_OFF, now.isoformat())
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
    actor: Optional[User],
    now: datetime,
    kind: str = ACTUAL,
    auto: bool = False,
) -> int:
    """Przyjmuje tylko RCP „Bez uwag”; każde liczone od nowa jak pojedyncze,
    a takie, które po przeliczeniu ma uwagi, zostaje. ``auto`` to poranny
    automat ``order.auto_accept_clean`` (pomija rozliczenia po „Do poprawy”)."""

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
            s = await accept(
                db,
                contract_id,
                month,
                actor=actor,
                now=now,
                kind=kind,
                require_clean=True,
                auto=auto,
            )
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

    if document.kind != "report":
        return
    if not await module_settings.is_enabled(db):
        return
    # Podpisany arkusz zbiorczy albo protokół od klienta (E6): po treści, nie po
    # nadawcy; rozpoznany plik nie jest RCP żadnej osoby.
    now = document.updated_at or datetime.now(ZoneInfo(DEFAULT_TZ))
    if await signoffs.apply(db, document, now=now):
        return
    if document.contract_id is None:
        # Odpowiedź klienta na paczkę KCP (E6.5): akceptacja wysłanych osób.
        from app.services.client_settlements import client_acceptance

        await client_acceptance.apply(db, document, now=now)
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


async def _sync_kesu_extra(
    db: AsyncSession, s: ClientSettlement, data: dict[str, Any]
) -> None:
    """Koszty dodatkowe z KEŚU → zgłoszony dodatek na fakturę dla klienta
    (jedna ścieżka kosztów z dodatkami Finansów, back office'u i panelu)."""

    if s.kind != ACTUAL:
        return
    try:
        gross = Decimal(str(data.get("extra_costs") or "0"))
    except ArithmeticError:
        gross = Decimal("0")
    await settlement_extras.sync_from_kesu(
        db,
        contract_id=s.contract_id,
        client_id=s.client_id,
        month=s.period_month,
        gross=gross,
        vat=kesu.VAT,
        now=datetime.now(timezone.utc),
    )


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
    await _sync_kesu_extra(db, s, proof.meta["kesu"])
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
