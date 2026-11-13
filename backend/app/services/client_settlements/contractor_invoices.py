"""Faktury kontraktorów z KSeF (roadmapa E4).

Pobieranie zakupów (``services/hr/ksef/sync.py``, ``Subject2``) przy włączonym
module rozliczeń oddaje tu każdą fakturę od NIP-u spoza danych Płac, zanim
policzy ją jako „pominiętą” albo kosztową:

* NIP kontraktu (``candidates.nip`` albo ``partner_nip`` z generatora umów
  B2B) → faktura zapisana jako ``known`` i przypięta do kontraktu i miesiąca,
* NIP nieznany, a sprzedawca nazywa się jak dokładnie jedna osoba z kontraktu
  bez NIP-u (imię i nazwisko w nazwie sprzedawcy; kwota rozstrzyga imienników)
  → ``suggested``: podpowiedź „NIP kontraktora” dla Finansów (E4.0, decyzja
  Artura z 09.11.2026). Zatwierdzenie zapisuje NIP osobie i od tej chwili
  faktury wiążą się same; odrzucenie zostawia fakturę bez osoby,
* reszta wraca do pobierania bez zmian.

Zapis z samych metadanych (sprzedawca, numer, daty, kwoty — jak faktury
kosztowe, ``approvals/cost_invoices.py``), bez pobierania XML-a: limit pobrań
zostaje dla Płac. Dlatego termin płatności liczymy od numeru KSeF (data
przyjęcia) i reguły ``ci.payment_days``, nie z treści faktury.

Kontrole korekt (netto, VAT i brutto łańcucha, dokument korygowany, stan
przed) i biała lista VAT: ``invoice_chain``; treść korekt z XML-a i status
z wykazu MF zbiera ``contractor_details`` przy pobieraniu z KSeF.

Kwota oczekiwana = wyliczenie z RCP (``amount_cost``) plus zatwierdzone dodatki
osoby za ten miesiąc (``extras.py``: polecenie, weryfikacja techniczna,
szkolenie, delegacja). Różnica równa zgłoszonemu, a niezatwierdzonemu dodatkowi
daje stan ``extra_pending`` („czeka na zatwierdzenie dodatku”), nie „inną kwotę”.

Miesiąc faktury: ten z miesiąca wystawienia i poprzedniego, w którym rozliczenie
ma tę samą kwotę (z zatwierdzonymi dodatkami); bez równej kwoty — wystawiona od 25. dnia rozlicza bieżący
miesiąc, wcześniej poprzedni (faktury za październik przychodzą 30.10–05.11).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client_settlement import ClientContractorInvoice, ClientSettlement
from app.models.contract import Contract, ContractStatus
from app.models.user import User
from app.services.client_settlements import extras as settlement_extras
from app.services.client_settlements import invoice_chain
from app.services.client_settlements.rcp_checks import name_tokens
from app.services.hr import white_list
from app.services.hr.approvals.cost_invoices import fields_from_metadata
from app.services.hr.payroll_periods import add_months

logger = logging.getLogger(__name__)

KNOWN, SUGGESTED, CONFIRMED, REJECTED = "known", "suggested", "confirmed", "rejected"
BOUND = (KNOWN, CONFIRMED)
#: Faktura za ostatni miesiąc przychodzi po zakończeniu kontraktu.
ENDED_GRACE = timedelta(days=92)
LATE_ISSUE_DAY = 25

#: Stan faktury kontraktora w wierszu miesiąca (kontrakt API E1.3).
NONE, CAN_ISSUE, IN_KSEF, DIFFERS, NIP_CHECK, EXTRA_PENDING = (
    "none",
    "can_issue",
    "in_ksef",
    "differs",
    "nip_check",
    "extra_pending",
)


class ContractorInvoiceError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def clean_nip(raw: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) == 10 else None


@dataclass(frozen=True)
class Contractor:
    contract_id: int
    candidate_id: Optional[int]
    tokens: frozenset[str]
    nip: Optional[str]


@dataclass
class ContractorIndex:
    by_nip: dict[str, list[Contractor]] = field(default_factory=dict)
    without_nip: list[Contractor] = field(default_factory=list)
    #: (NIP, kontrakt) odrzucone przez Finanse — bez ponownej podpowiedzi.
    rejected: set[tuple[str, int]] = field(default_factory=set)


async def load_index(db: AsyncSession, today: date) -> ContractorIndex:
    partner = (
        select(B2BGeneratedContract.partner_nip)
        .where(
            B2BGeneratedContract.contract_id == Contract.id,
            B2BGeneratedContract.partner_nip.is_not(None),
        )
        .order_by(B2BGeneratedContract.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(
            Contract.id,
            Contract.candidate_id,
            Candidate.name,
            Candidate.lastname,
            Candidate.nip,
            partner,
        )
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            or_(
                Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
                and_(
                    Contract.status == ContractStatus.ended,
                    or_(
                        Contract.end_date.is_(None),
                        Contract.end_date >= today - ENDED_GRACE,
                    ),
                ),
            )
        )
        .order_by(Contract.id)
    )
    index = ContractorIndex()
    for contract_id, candidate_id, first, last, own_nip, partner_nip in rows.all():
        nip = clean_nip(own_nip) or clean_nip(partner_nip)
        tokens = frozenset(name_tokens(f"{first or ''} {last or ''}"))
        person = Contractor(int(contract_id), candidate_id, tokens, nip)
        if nip:
            index.by_nip.setdefault(nip, []).append(person)
        elif len(tokens) >= 2:
            index.without_nip.append(person)
    rejected = await db.execute(
        select(
            ClientContractorInvoice.seller_nip, ClientContractorInvoice.contract_id
        ).where(
            ClientContractorInvoice.nip_state == REJECTED,
            ClientContractorInvoice.contract_id.is_not(None),
        )
    )
    index.rejected = {(nip, int(cid)) for nip, cid in rejected.all()}
    return index


def _month(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


async def _amounts(
    db: AsyncSession, contract_ids: Iterable[int], months: list[str]
) -> dict[tuple[int, str], Decimal]:
    rows = await db.execute(
        select(
            ClientSettlement.contract_id,
            ClientSettlement.period_month,
            ClientSettlement.amount_cost,
        ).where(
            ClientSettlement.contract_id.in_(list(contract_ids)),
            ClientSettlement.period_month.in_(months),
            ClientSettlement.kind == "actual",
            ClientSettlement.amount_cost.is_not(None),
        )
    )
    out = {(int(c), m): Decimal(a) for c, m, a in rows.all()}
    # Faktura z doliczonym dodatkiem (polecenie, delegacja) też ma „równą kwotę”.
    for month in months:
        found = await settlement_extras.expected_by_contract(
            db, sorted({c for c, m in out if m == month}), month
        )
        for contract_id, extra in found.items():
            out[(contract_id, month)] += extra.approved
    return out


def _months(issue: Optional[date]) -> list[str]:
    if issue is None:
        return []
    year, month = add_months(issue.year, issue.month, -1)
    return [_month(issue), f"{year}-{month:02d}"]


def _default_period(issue: Optional[date]) -> Optional[str]:
    months = _months(issue)
    if not months:
        return None
    return months[0] if issue.day >= LATE_ISSUE_DAY else months[1]


async def _place(
    db: AsyncSession,
    people: list[Contractor],
    issue: Optional[date],
    net: Optional[Decimal],
) -> tuple[Optional[Contractor], Optional[str]]:
    """Osoba i miesiąc: równa kwota rozliczenia rozstrzyga, potem dzień wystawienia."""

    months = _months(issue)
    if net is not None and months:
        amounts = await _amounts(db, (p.contract_id for p in people), months)
        hits = [
            (person, month)
            for person in people
            for month in months
            if amounts.get((person.contract_id, month)) == net
        ]
        if len({person.contract_id for person, _ in hits}) == 1:
            return hits[0]
    if len({p.contract_id for p in people}) == 1:
        return people[0], _default_period(issue)
    return None, _default_period(issue)


def _suggestion_people(
    index: ContractorIndex, seller_nip: str, seller_name: Optional[str]
) -> list[Contractor]:
    seller = name_tokens(seller_name)
    if not seller:
        return []
    return [
        person
        for person in index.without_nip
        if person.tokens <= seller
        and (seller_nip, person.contract_id) not in index.rejected
    ]


def _buyer_nip(item: dict[str, Any]) -> Optional[str]:
    identifier = (item.get("buyer") or {}).get("identifier") or {}
    value = identifier.get("value") if isinstance(identifier, dict) else None
    return str(value)[:16] if value else None


def _acquired(item: dict[str, Any]) -> Optional[datetime]:
    from app.services.hr.ksef.client import parse_instant  # noqa: PLC0415

    raw = item.get("acquisitionDate") or item.get("permanentStorageDate")
    return parse_instant(raw) if isinstance(raw, str) else None


async def consider(
    db: AsyncSession, index: ContractorIndex, item: dict[str, Any], ksef_number: str
) -> Optional[str]:
    """Zapis faktury kontraktora z rekordu metadanych; ``None`` = nie kontraktor.

    Zwraca ``nip_state`` zapisanej (albo już zapisanej) faktury."""

    fields = fields_from_metadata(item)
    if fields is None:
        return None
    nip = fields["seller_nip"]
    state = KNOWN
    people = index.by_nip.get(nip) or []
    if not people:
        people = _suggestion_people(index, nip, fields["seller_name"])
        state = SUGGESTED
    if not people:
        return None
    person, period = await _place(
        db, people, fields["issue_date"], fields["net_amount"]
    )
    if person is None and state == SUGGESTED:
        # Dwóch imienników, kwota nie rozstrzyga — bez podpowiedzi.
        return None
    statement = insert(ClientContractorInvoice).values(
        ksef_number=ksef_number,
        seller_nip=nip,
        seller_name=fields["seller_name"],
        buyer_nip=_buyer_nip(item),
        invoice_number=fields["invoice_number"],
        invoice_type=fields["ksef_invoice_type"],
        issue_date=fields["issue_date"],
        acquired_at=_acquired(item),
        currency=fields["currency"],
        net_amount=fields["net_amount"],
        vat_amount=fields["vat_amount"],
        gross_amount=fields["gross_amount"],
        contract_id=person.contract_id if person else None,
        period_month=period,
        nip_state=state,
    )
    await db.execute(
        statement.on_conflict_do_nothing(
            constraint="uq_client_contractor_invoices_ksef"
        )
    )
    return state


# ── Decyzje Finansów (E4.0) ──────────────────────────────────────────────────


async def _suggested(db: AsyncSession, invoice_id: int) -> ClientContractorInvoice:
    invoice = await db.get(ClientContractorInvoice, invoice_id, with_for_update=True)
    if invoice is None:
        raise ContractorInvoiceError("Nie ma takiej faktury.", status=404)
    if invoice.nip_state != SUGGESTED or invoice.contract_id is None:
        raise ContractorInvoiceError("Ta faktura nie czeka na zatwierdzenie NIP-u.")
    return invoice


async def approve_nip(
    db: AsyncSession, invoice_id: int, actor: User, now: datetime
) -> ClientContractorInvoice:
    invoice = await _suggested(db, invoice_id)
    contract = await db.get(Contract, invoice.contract_id)
    candidate = (
        await db.get(Candidate, contract.candidate_id, with_for_update=True)
        if contract is not None and contract.candidate_id is not None
        else None
    )
    if candidate is None:
        raise ContractorInvoiceError("Kontrakt nie ma osoby, której można zapisać NIP.")
    current = clean_nip(candidate.nip)
    if current and current != invoice.seller_nip:
        raise ContractorInvoiceError(
            "Osoba ma już inny NIP. Popraw go w karcie kandydata, jeśli się zmienił."
        )
    candidate.nip = invoice.seller_nip
    # Pozostałe podpowiedzi tego NIP-u dla tej osoby idą za decyzją.
    same = await db.scalars(
        select(ClientContractorInvoice).where(
            ClientContractorInvoice.seller_nip == invoice.seller_nip,
            ClientContractorInvoice.nip_state == SUGGESTED,
            ClientContractorInvoice.contract_id.in_(
                select(Contract.id).where(Contract.candidate_id == candidate.id)
            ),
        )
    )
    for row in {invoice, *same}:
        row.nip_state = CONFIRMED
        row.decided_by = actor.id
        row.decided_at = now
    await db.flush()
    logger.info(
        "client_settlements: NIP z KSeF zatwierdzony (faktura %s, kontrakt %s)",
        invoice.id,
        invoice.contract_id,
    )
    return invoice


async def reject_nip(
    db: AsyncSession, invoice_id: int, actor: User, now: datetime
) -> ClientContractorInvoice:
    invoice = await _suggested(db, invoice_id)
    invoice.nip_state = REJECTED
    invoice.decided_by = actor.id
    invoice.decided_at = now
    await db.flush()
    return invoice


# ── Odczyt: wiersz miesiąca i karta osoby (E4.2) ─────────────────────────────


async def for_month(
    db: AsyncSession, contract_ids: list[int], month: str
) -> dict[int, list[ClientContractorInvoice]]:
    if not contract_ids:
        return {}
    rows = await db.scalars(
        select(ClientContractorInvoice)
        .where(
            ClientContractorInvoice.contract_id.in_(contract_ids),
            ClientContractorInvoice.period_month == month,
            ClientContractorInvoice.nip_state != REJECTED,
        )
        .order_by(ClientContractorInvoice.issue_date, ClientContractorInvoice.id)
    )
    out: dict[int, list[ClientContractorInvoice]] = {}
    for row in rows:
        out.setdefault(int(row.contract_id), []).append(row)
    return out


def _param(rules: dict[str, Any], key: str, name: str) -> str:
    return str(rules[key]["params"].get(name, "")).strip()


def _tolerance(rules: dict[str, Any]) -> Decimal:
    try:
        return abs(
            Decimal(_param(rules, "ci.amount", "tolerance").replace(",", ".") or "0")
        )
    except InvalidOperation:
        return Decimal("0")


def _net(invoices: list[ClientContractorInvoice]) -> Optional[Decimal]:
    values = [i.net_amount for i in invoices]
    if any(v is None for v in values):
        return None
    return sum((Decimal(v) for v in values), Decimal("0"))


def expected(
    settlement: Optional[ClientSettlement],
    extras: Optional[settlement_extras.Totals],
) -> Optional[Decimal]:
    """Oczekiwana kwota faktury: wyliczenie z RCP + zatwierdzone dodatki."""

    if settlement is None or settlement.amount_cost is None:
        return None
    return Decimal(settlement.amount_cost) + (extras.approved if extras else 0)


def state(
    settlement: Optional[ClientSettlement],
    invoices: list[ClientContractorInvoice],
    rules: dict[str, Any],
    extras: Optional[settlement_extras.Totals] = None,
) -> str:
    bound = [i for i in invoices if i.nip_state in BOUND]
    if bound:
        want = expected(settlement, extras)
        if want is None or rules["ci.amount"]["level"] == "off":
            return IN_KSEF
        net = _net(bound)
        tolerance = _tolerance(rules)
        if net is not None and abs(net - want) <= tolerance:
            return IN_KSEF
        if (
            net is not None
            and extras is not None
            and extras.explains(net - want, tolerance)
        ):
            return EXTRA_PENDING
        return DIFFERS
    if any(i.nip_state == SUGGESTED for i in invoices):
        return NIP_CHECK
    if settlement is not None and settlement.status == "accepted":
        return CAN_ISSUE
    return NONE


def _pln(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    text = f"{Decimal(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} zł"


def _payment_days(rules: dict[str, Any]) -> Optional[int]:
    if rules["ci.payment_days"]["level"] == "off":
        return None
    try:
        days = int(_param(rules, "ci.payment_days", "days"))
    except ValueError:
        return None
    return days if 0 < days <= 120 else None


def _due(invoice: ClientContractorInvoice, days: Optional[int]) -> Optional[date]:
    if days is None or invoice.acquired_at is None:
        return None
    return invoice.acquired_at.date() + timedelta(days=days)


def _iso(day: Optional[date]) -> Optional[str]:
    return day.isoformat() if day else None


def card(
    settlement: Optional[ClientSettlement],
    invoices: list[ClientContractorInvoice],
    rules: dict[str, Any],
    *,
    amounts: bool,
    extras: Optional[settlement_extras.Totals] = None,
) -> dict[str, Any]:
    """Blok „Faktura kontraktora” karty osoby: stan, faktury i kontrole."""

    days = _payment_days(rules)
    checks: list[dict[str, Any]] = []
    bound = [i for i in invoices if i.nip_state in BOUND]
    for invoice in invoices:
        if invoice.nip_state == SUGGESTED:
            checks.append(
                {
                    "state": "warn",
                    "title": "NIP z KSeF do zatwierdzenia",
                    "detail": f"Sprzedawca: {invoice.seller_name or 'bez nazwy'}, NIP {invoice.seller_nip}.",
                }
            )
    if bound:
        net = _net(bound)
        want = expected(settlement, extras)
        added = extras.approved if extras else Decimal("0")
        level = rules["ci.amount"]["level"]
        if want is not None and net is not None and level != "off" and amounts:
            diff = net - want
            tolerance = _tolerance(rules)
            basis = (
                f"wyliczenie {_pln(want - added)} + zatwierdzone dodatki {_pln(added)}"
                if added
                else f"wyliczenie {_pln(want)}"
            )
            if abs(diff) <= tolerance:
                checks.append(
                    {
                        "state": "ok",
                        "title": "Kwota równa wyliczeniu z RCP i dodatkom"
                        if added
                        else "Kwota równa wyliczeniu z RCP",
                    }
                )
            elif extras is not None and extras.explains(diff, tolerance):
                # Koszt dodatkowy potwierdza rozliczający (travel.extra_costs_confirm):
                # tylko uwaga, nigdy błąd.
                checks.append(
                    {
                        "state": "warn",
                        "title": "Czeka na zatwierdzenie dodatku",
                        "detail": f"Faktura {_pln(net)} netto, {basis}; różnica {_pln(diff)} to zgłoszony dodatek.",
                    }
                )
            else:
                checks.append(
                    {
                        "state": "fail" if level == "block" else "warn",
                        "title": "Inna kwota niż wyliczenie z RCP",
                        "detail": f"Faktura {_pln(net)} netto, {basis}, różnica {_pln(diff)}.",
                    }
                )
        checks.extend(invoice_chain.chain_checks(bound, amounts=amounts))
        need = clean_nip(_param(rules, "ci.buyer_nip", "nip"))
        if need and rules["ci.buyer_nip"]["level"] != "off":
            wrong = [i for i in bound if clean_nip(i.buyer_nip) != need]
            if wrong:
                checks.append(
                    {
                        "state": "fail"
                        if rules["ci.buyer_nip"]["level"] == "block"
                        else "warn",
                        "title": "NIP nabywcy inny niż w regułach klienta",
                        "detail": f"Na fakturze: {wrong[0].buyer_nip or 'brak'}.",
                    }
                )
            else:
                checks.append({"state": "ok", "title": "NIP nabywcy zgodny"})
        checks.extend(
            invoice_chain.whitelist_checks(
                bound, amounts=amounts, mode=white_list.current_mode()
            )
        )
        due = _due(bound[0], days)
        if due is not None:
            checks.append(
                {
                    "state": "none",
                    "title": f"Termin płatności: {due.strftime('%d.%m.%Y')}",
                    "detail": f"{days} dni od numeru KSeF.",
                }
            )
    elif (
        settlement is not None
        and settlement.status == "accepted"
        and not any(i.nip_state == SUGGESTED for i in invoices)
    ):
        checks.append({"state": "none", "title": "Czeka na fakturę w KSeF"})
    return {
        "state": state(settlement, invoices, rules, extras),
        "invoices": [
            {
                "id": i.id,
                "ksef_number": i.ksef_number,
                "invoice_number": i.invoice_number,
                "issue_date": i.issue_date.isoformat() if i.issue_date else None,
                "acquired_at": i.acquired_at.isoformat() if i.acquired_at else None,
                "seller_name": i.seller_name,
                "seller_nip": i.seller_nip,
                "nip_state": i.nip_state,
                "is_correction": invoice_chain.is_correction(i),
                "net_amount": f"{i.net_amount:.2f}"
                if amounts and i.net_amount is not None
                else None,
                "gross_amount": f"{i.gross_amount:.2f}" if amounts else None,
                "due_date": _iso(_due(i, days)),
            }
            for i in invoices
        ],
        "checks": checks,
    }
