"""Rozliczenie kosztów na „5” (K2): miesięczne PK z MPK z danych NEXUSA.

Plan „Księgowość w NEXUSIE” (13.11.2026): opis działu Finanse robią dziś ręcznie
w eBI24; NEXUS zna klienta z kontraktu i pion z kartoteki osoby, więc liczy
podział sam. Dekretu E2 (koszty rodzajowe, zespół 4) nie zmieniamy — co
miesiąc powstaje jedno polecenie księgowania: Wn konta „5” z MPK, Ma konto
rozliczenia kosztów (490).

* **Z czego**: zapisy miesiąca, jak w dzienniku — zatwierdzone FVZ okresu ze
  źródłem w kolejce kosztów (``finance_cost_entry``), także później odwrócone,
  i zatwierdzone storna takich FVZ zaksięgowane w tym okresie (z MPK faktury
  pierwotnej). Storno w kwietniu odejmuje koszt w kwietniu, a zamknięty marzec
  zostaje zgodny (przegląd poprawności 14.11.2026). Kwota = Wn − Ma pozycji na
  kontach rodzaju „koszt” (rodzaj z planu kont po prefiksie numeru, także konta
  już nieksięgowalnego — zmiana planu nie gubi zaksięgowanych kosztów).
* **MPK**: faktura kontraktora → klient kontraktu (``K<id klienta>``); faktura
  osoby zespołu → pion z kartoteki (``FO`` / ``BO``); dokument akceptacji →
  klient wniosku, inaczej pion wnioskującego; reszta → koszty ogólne (``OG``,
  do czasu klucza podziału biura od Finansów).
* **D2**: koszty z faktur osób zespołu idą osobnym PK z wrażliwością
  ``payroll`` na jednym koncie kosztów zespołu, z pionem tylko w MPK pozycji —
  suma pionu bywa kwotą jednej osoby, a obroty kont pokazują sumy każdemu
  z „Modułem Finanse”.
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.client import Client
from app.models.client_settlement import ClientContractorInvoice
from app.models.contract import Contract
from app.models.finance_ledger import FinanceCostEntry
from app.models.hr_approval import ApprovalDocument, ApprovalRequest
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import PayrollInvoice
from app.models.ledger import LedgerDocument, LedgerLine
from app.services.hr.structure import DIVISION_LABELS
from app.services.ledger.documents import DocumentSpec
from app.services.ledger.engine import LineIn, PlanAccount
from app.services.ledger.settings import AllocationAccounts
from app.services.ledger_schema import DESCRIPTION_MAX, LINE_TEXT_MAX

SOURCE_TYPE = "cost_allocation"
COST_SOURCE = "finance_cost_entry"
OVERHEAD = "OG"
DIVISION_CODES: dict[str, str] = {"front_office": "FO", "back_office": "BO"}
KIND_ACCOUNT: dict[str, str] = {
    "client": "client_account",
    "front_office": "front_office_account",
    "back_office": "back_office_account",
    "overhead": "overhead_account",
}


@dataclass(frozen=True)
class Mpk:
    code: str
    kind: str
    label: str


def mpk_of(
    source_type: str,
    *,
    contract_client: Optional[int],
    payroll_division: Optional[str],
    request_client: Optional[int],
    requester_division: Optional[str],
) -> tuple[str, Optional[int], Optional[str]]:
    """Źródło faktury → (rodzaj MPK, id klienta, pion)."""

    if source_type == "contractor_invoice" and contract_client:
        return "client", contract_client, None
    if source_type == "payroll_invoice" and payroll_division in DIVISION_CODES:
        return payroll_division, None, payroll_division
    if source_type == "approval_document":
        if request_client:
            return "client", request_client, None
        if requester_division in DIVISION_CODES:
            return requester_division, None, requester_division
    return "overhead", None, None


def source_id(year: int, month: int, *, payroll: bool) -> str:
    return f"{year}-{month:02d}" + ("-payroll" if payroll else "")


def allocation_spec(
    year: int,
    month: int,
    totals: dict[Mpk, int],
    accounts: AllocationAccounts,
    *,
    payroll: bool,
) -> Optional[DocumentSpec]:
    """PK rozliczenia kosztów: Wn konta „5” z MPK, Ma 490; ``None`` = nic do podziału."""

    lines: list[LineIn] = []
    total = 0
    for mpk in sorted(totals, key=lambda item: (item.kind != "client", item.code)):
        amount = totals[mpk]
        if amount == 0:
            continue
        total += amount
        account = (
            accounts.team_account
            if payroll
            else getattr(accounts, KIND_ACCOUNT[mpk.kind])
        )
        lines.append(
            LineIn(
                side="debit" if amount > 0 else "credit",
                account=account,
                amount=abs(amount),
                mpk=mpk.code,
                description=mpk.label[:LINE_TEXT_MAX],
            )
        )
    if not lines:
        return None
    if total:
        lines.append(
            LineIn(
                side="credit" if total > 0 else "debit",
                account=accounts.settlement_account,
                amount=abs(total),
                description="Rozliczenie kosztów",
            )
        )
    last = date(year, month, monthrange(year, month)[1])
    scope = " — faktury osób zespołu" if payroll else ""
    return DocumentSpec(
        doc_type="PK",
        op_date=last,
        doc_date=last,
        lines=lines,
        description=f"Rozliczenie kosztów na MPK {month:02d}.{year}{scope}"[
            :DESCRIPTION_MAX
        ],
        source_type=SOURCE_TYPE,
        source_id=source_id(year, month, payroll=payroll),
        sensitivity="payroll" if payroll else None,
        meta={"source": "allocation"},
    )


def account_kind(number: str, plan: dict[str, PlanAccount]) -> Optional[str]:
    """Rodzaj konta z planu: to konto albo najbliższe nadrzędne po prefiksie.

    Celowo bez reguł księgowalności (``engine.resolve``): konto, pod którym
    założono analitykę albo które wyłączono, dalej nosi zaksięgowane koszty.
    """

    parts = number.split("-")
    for cut in range(len(parts), 0, -1):
        account = plan.get("-".join(parts[:cut]))
        if account is not None:
            return account.kind
    return None


async def _cost_by_entry(
    db: AsyncSession, period_id: int, plan: dict[str, PlanAccount], *, payroll: bool
) -> dict[int, int]:
    """Koszt okresu (Wn − Ma na kontach „koszt”) per wpis kolejki kosztów.

    FVZ zaksięgowane w okresie (także odwrócone później) i storna FVZ
    zaksięgowane w okresie — storno czerwone ma kwoty ujemne, więc odejmuje się
    samo, w miesiącu, w którym je zaksięgowano.
    """

    original = aliased(LedgerDocument)
    signed = case(
        (LedgerLine.side == "debit", LedgerLine.amount), else_=-LedgerLine.amount
    )
    entry = case(
        (LedgerDocument.reverses_id.is_(None), LedgerDocument.source_id),
        else_=original.source_id,
    )
    rows = await db.execute(
        select(entry, LedgerLine.account, func.sum(signed))
        .select_from(LedgerDocument)
        .join(LedgerLine, LedgerLine.document_id == LedgerDocument.id)
        .outerjoin(original, original.id == LedgerDocument.reverses_id)
        .where(
            LedgerDocument.period_id == period_id,
            LedgerDocument.status == "approved",
            or_(
                LedgerDocument.source_type == COST_SOURCE,
                and_(
                    LedgerDocument.doc_type == "ST",
                    original.source_type == COST_SOURCE,
                ),
            ),
            (
                LedgerDocument.sensitivity.is_not(None)
                if payroll
                else LedgerDocument.sensitivity.is_(None)
            ),
        )
        .group_by(entry, LedgerLine.account)
    )
    out: dict[int, int] = defaultdict(int)
    for raw_id, account, amount in rows.all():
        if account_kind(account, plan) != "cost":
            continue
        if raw_id and raw_id.isdigit():
            out[int(raw_id)] += int(amount or 0)
    return dict(out)


async def _mpk_by_entry(db: AsyncSession, entry_ids: list[int]) -> dict[int, Mpk]:
    entry = FinanceCostEntry
    payroll_profile = EmployeeProfile.__table__.alias("payroll_profile")
    requester_profile = EmployeeProfile.__table__.alias("requester_profile")
    rows = await db.execute(
        select(
            entry.id,
            entry.source_type,
            Contract.client_id,
            payroll_profile.c.division,
            ApprovalRequest.client_id,
            requester_profile.c.division,
        )
        .select_from(entry)
        .outerjoin(
            ClientContractorInvoice,
            and_(
                entry.source_type == "contractor_invoice",
                ClientContractorInvoice.id == entry.source_id,
            ),
        )
        .outerjoin(Contract, Contract.id == ClientContractorInvoice.contract_id)
        .outerjoin(
            PayrollInvoice,
            and_(
                entry.source_type == "payroll_invoice",
                PayrollInvoice.id == entry.source_id,
            ),
        )
        .outerjoin(payroll_profile, payroll_profile.c.user_id == PayrollInvoice.user_id)
        .outerjoin(
            ApprovalDocument,
            and_(
                entry.source_type == "approval_document",
                ApprovalDocument.id == entry.source_id,
            ),
        )
        .outerjoin(
            ApprovalRequest, ApprovalRequest.id == ApprovalDocument.approval_request_id
        )
        .outerjoin(
            requester_profile,
            requester_profile.c.user_id == ApprovalRequest.requester_user_id,
        )
        .where(entry.id.in_(entry_ids or [0]))
    )
    kinds: dict[int, tuple[str, Optional[int], Optional[str]]] = {}
    for entry_id, source_type, contract_client, p_div, r_client, r_div in rows.all():
        kinds[entry_id] = mpk_of(
            source_type,
            contract_client=contract_client,
            payroll_division=p_div,
            request_client=r_client,
            requester_division=r_div,
        )
    client_ids = {client for _, client, _ in kinds.values() if client}
    names: dict[int, str] = {}
    if client_ids:
        names = dict(
            (
                await db.execute(
                    select(Client.id, Client.name).where(Client.id.in_(client_ids))
                )
            ).all()
        )
    out: dict[int, Mpk] = {}
    for entry_id, (kind, client, division) in kinds.items():
        if kind == "client" and client:
            out[entry_id] = Mpk(
                f"K{client}", kind, names.get(client) or f"Klient {client}"
            )
        elif division:
            out[entry_id] = Mpk(
                DIVISION_CODES[division], kind, DIVISION_LABELS[division]
            )
        else:
            out[entry_id] = Mpk(OVERHEAD, "overhead", "Koszty ogólne")
    return out


async def month_totals(
    db: AsyncSession, period_id: int, plan: dict[str, PlanAccount], *, payroll: bool
) -> dict[Mpk, int]:
    """Koszty zatwierdzonych FVZ okresu zsumowane po MPK (grosze)."""

    by_entry = await _cost_by_entry(db, period_id, plan, payroll=payroll)
    if not by_entry:
        return {}
    mpks = await _mpk_by_entry(db, list(by_entry))
    overhead = Mpk(OVERHEAD, "overhead", "Koszty ogólne")
    totals: dict[Mpk, int] = defaultdict(int)
    for entry_id, amount in by_entry.items():
        totals[mpks.get(entry_id, overhead)] += amount
    return dict(totals)


async def pending_cost_documents(
    db: AsyncSession, period_id: int, *, payroll: bool
) -> int:
    """FVZ okresu w buforze — wejdą do rozliczenia dopiero po zatwierdzeniu."""

    return int(
        await db.scalar(
            select(func.count())
            .select_from(LedgerDocument)
            .where(
                LedgerDocument.period_id == period_id,
                LedgerDocument.status == "draft",
                LedgerDocument.source_type == COST_SOURCE,
                (
                    LedgerDocument.sensitivity.is_not(None)
                    if payroll
                    else LedgerDocument.sensitivity.is_(None)
                ),
            )
        )
        or 0
    )
