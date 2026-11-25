"""Obserwacje stawek z faktur KSeF per kontrakt i miesiąc (wejście ``infer``).

Czyste funkcje (``match_item``, ``unit_hours``, ``cost_month``,
``build_inputs``) dostają wiersze jako proste struktury — testy bez bazy;
``load_inputs`` czyta je z bazy.

* **Pozycja faktury sprzedaży → kontrakt:** numer osoby u klienta z kartoteki
  (``client_external_ids``, potwierdzony; Nordea ``ID: M…``), a bez niego pełne
  imię i nazwisko osoby z kontraktem u tego klienta, trwającym w miesiącu
  faktury. Dwie osoby o tym samym imieniu i nazwisku albo dwa kontrakty jednej
  osoby u klienta w miesiącu = pozycja bez kontraktu. Pomijamy pozycje „szt.”
  (refaktury, hotele), nadgodziny, onboarding i korekty, ceny ≤ 0 i faktury
  w innej walucie niż zł.
* **Faktura konsultanta → osoba:** pełne imię i nazwisko w nazwie sprzedawcy,
  jedna osoba z kontraktem w całym NEXUSIE (inkubator wystawiający za wielu
  nie ma osoby w nazwie, więc nie pasuje).
* **Miesiąc faktury konsultanta** (nie ma okresu): wystawiona od 25. dnia =
  bieżący miesiąc, wcześniej = poprzedni; gdy poprzedni ma już fakturę
  z końca miesiąca, a bieżący ma godziny u klienta — bieżący (okno ±1).
* **Miesiąc bez dowodu:** korekta faktury konsultanta albo sprzedaży z osobą
  w tym miesiącu (godziny niepewne) i osoba z więcej niż jednym kontraktem
  w miesiącu (kosztu nie da się podzielić) — brak obserwacji kosztu.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.client_order import ClientOrder
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.client_settlement import ClientSettlement
from app.models.client_time_report import ClientExternalId
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_approval import ApprovalDocument
from app.services.client_settlements.rcp_checks import name_tokens
from app.services.client_settlements.time_reports import person_numbers
from app.services.contract_rate_history import infer
from app.services.hr.payroll_periods import add_months

LATE_ISSUE_DAY = 25
PLN = "PLN"
HOURS_PER_DAY = Decimal(8)
_HOUR_UNITS = {"godz", "h", "godzina", "godziny", "rbh"}
_DAY_UNITS = {"md", "osd", "dzien", "dni", "osobodzien"}
_EXTRA_ITEM = re.compile(
    r"nadgodzin|overtime|on-?bo?arding|onbording|dyżur|dyzur|weekend|korekt",
    re.IGNORECASE,
)
#: „Nordea Contact: Imię Nazwisko” to osoba klienta, nie konsultant.
_CONTACT = re.compile(r"contact\s*:\s*[^,;]*", re.IGNORECASE)
_SETTLED = "accepted"


def month_key(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def shift(month: str, delta: int) -> str:
    y, m = add_months(int(month[:4]), int(month[5:7]), delta)
    return f"{y}-{m:02d}"


def month_last(month: str) -> date:
    return date.fromordinal(infer.month_start(shift(month, 1)).toordinal() - 1)


def dec(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return None


def unit_hours(unit: Optional[str]) -> Optional[Decimal]:
    word = re.sub(r"[^a-z]+", "", " ".join(sorted(name_tokens(unit))))
    if word in _HOUR_UNITS:
        return Decimal(1)
    if word in _DAY_UNITS:
        return HOURS_PER_DAY
    return None


@dataclass(frozen=True)
class ContractRow:
    id: int
    candidate_id: int
    client_id: int
    start_date: Optional[date]
    end_date: Optional[date]
    hourly_pln: bool
    client_schedule: tuple[infer.Step, ...] = ()
    cost_schedule: tuple[infer.Step, ...] = ()
    client_scalar: Optional[Decimal] = None
    cost_scalar: Optional[Decimal] = None

    def live_in(self, month: str) -> bool:
        first = infer.month_start(month)
        if self.start_date and self.start_date > month_last(month):
            return False
        return not (self.end_date and self.end_date < first)


@dataclass(frozen=True)
class SalesRow:
    invoice_number: str
    client_id: Optional[int]
    month: Optional[str]
    issue_date: date
    currency: str
    correction: bool
    items: tuple[dict[str, Any], ...]
    #: Kontrakty z zamówień, do których faktura jest przypięta w miesiącu.
    linked_contracts: frozenset[int] = frozenset()


@dataclass(frozen=True)
class CostRow:
    invoice_number: str
    seller_name: str
    issue_date: date
    currency: str
    net: Decimal
    correction: bool


@dataclass
class World:
    contracts: dict[int, ContractRow]
    #: Imię i nazwisko osoby (tokeny) — tylko osoby z kontraktem.
    person_tokens: dict[int, frozenset[str]]
    #: (klient, numer osoby) → kontrakty z potwierdzonym numerem.
    person_numbers: dict[tuple[int, str], set[int]] = field(default_factory=dict)
    open_settlements: dict[int, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_client: dict[int, list[ContractRow]] = defaultdict(list)
        self.by_candidate: dict[int, list[ContractRow]] = defaultdict(list)
        for c in self.contracts.values():
            self.by_client[c.client_id].append(c)
            self.by_candidate[c.candidate_id].append(c)


def match_item(world: World, client_id: int, month: str, text: str) -> Optional[int]:
    """Kontrakt osoby z pozycji faktury do klienta albo ``None`` (niejednoznacznie)."""

    for number in person_numbers(text):
        hits = {
            cid
            for cid in world.person_numbers.get((client_id, number), set())
            if world.contracts[cid].live_in(month)
        }
        if len(hits) == 1:
            return next(iter(hits))
    tokens = words(_CONTACT.sub(" ", text))
    persons = {
        c.candidate_id
        for c in world.by_client.get(client_id, [])
        if len(world.person_tokens.get(c.candidate_id, ())) >= 2
        and world.person_tokens[c.candidate_id] <= tokens
    }
    if len(persons) != 1:
        return None
    person = next(iter(persons))
    live = [
        c
        for c in world.by_client[client_id]
        if c.candidate_id == person and c.live_in(month)
    ]
    return live[0].id if len(live) == 1 else None


def words(text: str) -> set[str]:
    """Słowa tekstu jak ``name_tokens``, ale „Contractor:Jan” to dwa słowa."""

    return name_tokens(re.sub(r"[^\w]+", " ", text or ""))


def match_seller(world: World, seller_name: str) -> Optional[int]:
    tokens = words(seller_name)
    persons = {
        p for p, pt in world.person_tokens.items() if len(pt) >= 2 and pt <= tokens
    }
    return next(iter(persons)) if len(persons) == 1 else None


@dataclass
class _Month:
    prices: set[Decimal] = field(default_factory=set)
    hours: Decimal = Decimal(0)
    corrected: bool = False
    evidence: list[str] = field(default_factory=list)


def cost_months(
    rows: Iterable[CostRow], hours_months: set[str]
) -> dict[str, list[CostRow]]:
    """Faktury jednej osoby rozłożone na miesiące (reguła 25. dnia + okno ±1)."""

    out: dict[str, list[CostRow]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r.issue_date):
        issued = month_key(row.issue_date)
        if row.issue_date.day >= LATE_ISSUE_DAY:
            out[issued].append(row)
            continue
        previous = shift(issued, -1)
        late_previous = any(
            r.issue_date.day >= LATE_ISSUE_DAY and month_key(r.issue_date) == previous
            for r in out.get(previous, [])
        )
        if late_previous and issued in hours_months and not out.get(issued):
            out[issued].append(row)
        else:
            out[previous].append(row)
    return out


def build_inputs(
    world: World,
    sales: Iterable[SalesRow],
    costs: Iterable[CostRow],
    months: set[str],
) -> list[infer.ContractInput]:
    per: dict[tuple[int, str], _Month] = defaultdict(_Month)
    for inv in sales:
        if inv.client_id is None or inv.month not in months or inv.currency != PLN:
            continue
        eligible = []
        for item in inv.items:
            if item.get("before_correction"):
                continue
            text = str(item.get("name") or "")
            hours_per_unit = unit_hours(item.get("unit"))
            price = dec(item.get("unit_price"))
            qty = dec(item.get("quantity"))
            if (
                hours_per_unit is None
                or price is None
                or price <= 0
                or _EXTRA_ITEM.search(text)
            ):
                continue
            contract_id = match_item(world, inv.client_id, inv.month, text)
            eligible.append((contract_id, hours_per_unit, price, qty))
        # Pozycja bez osoby („Praca kontraktora: 414097”): faktura przypięta do
        # zamówienia jednej osoby mówi, czyja jest — gdy żadna pozycja nie
        # nazywa nikogo.
        live_links = {
            cid
            for cid in inv.linked_contracts
            if cid in world.contracts and world.contracts[cid].live_in(inv.month)
        }
        if eligible and all(e[0] is None for e in eligible) and len(live_links) == 1:
            only = next(iter(live_links))
            eligible = [(only, h, p, q) for _, h, p, q in eligible]
        for contract_id, hours_per_unit, price, qty in eligible:
            if contract_id is None:
                continue
            slot = per[(contract_id, inv.month)]
            slot.prices.add(price / hours_per_unit)
            if inv.correction:
                slot.corrected = True
            elif qty is not None and qty > 0:
                slot.hours += qty * hours_per_unit
            if inv.invoice_number not in slot.evidence:
                slot.evidence.append(inv.invoice_number)

    client_obs: dict[int, list[infer.MonthObservation]] = defaultdict(list)
    for (contract_id, month), slot in per.items():
        if len({infer.snap(p) for p in slot.prices}) != 1:
            continue
        client_obs[contract_id].append(
            infer.MonthObservation(
                month=month,
                rate=next(iter(slot.prices)),
                hours=slot.hours,
                evidence=tuple(slot.evidence),
            )
        )

    by_person: dict[int, list[CostRow]] = defaultdict(list)
    for row in costs:
        if row.currency != PLN:
            continue
        person = match_seller(world, row.seller_name)
        if person is not None:
            by_person[person].append(row)
    cost_obs: dict[int, list[infer.MonthObservation]] = defaultdict(list)
    for person, rows in by_person.items():
        contracts = world.by_candidate.get(person, [])
        hours_months = {m for c in contracts for (cid, m) in per if cid == c.id}
        for month, docs in cost_months(rows, hours_months).items():
            if month not in months or any(d.correction for d in docs):
                continue
            live = [c for c in contracts if c.live_in(month)]
            if len(live) != 1:
                continue
            slot = per.get((live[0].id, month))
            if slot is None or slot.corrected or slot.hours <= 0:
                continue
            net = sum((d.net for d in docs), Decimal(0))
            if net <= 0:
                continue
            cost_obs[live[0].id].append(
                infer.MonthObservation(
                    month=month,
                    rate=net / slot.hours,
                    hours=slot.hours,
                    evidence=tuple(d.invoice_number for d in docs),
                )
            )

    out = []
    for c in world.contracts.values():
        if not client_obs.get(c.id) and not cost_obs.get(c.id):
            continue
        out.append(
            infer.ContractInput(
                contract_id=c.id,
                start_date=c.start_date,
                hourly_pln=c.hourly_pln,
                client_schedule=c.client_schedule,
                cost_schedule=c.cost_schedule,
                client_scalar=c.client_scalar,
                cost_scalar=c.cost_scalar,
                client_obs=tuple(client_obs.get(c.id, ())),
                cost_obs=tuple(cost_obs.get(c.id, ())),
                open_settlement_months=frozenset(world.open_settlements.get(c.id, ())),
            )
        )
    return out


# ── Baza ─────────────────────────────────────────────────────────────────────


def _steps(rows: Iterable[Any]) -> tuple[infer.Step, ...]:
    return tuple(
        infer.Step(effective_from=r.effective_from, rate=Decimal(r.rate))
        for r in sorted(rows, key=lambda r: (r.effective_from, r.id))
    )


def _hourly_pln(c: Contract) -> bool:
    unit = c.rate_unit.value if isinstance(c.rate_unit, RateUnit) else c.rate_unit
    currencies = {
        (c.rate_client_currency or c.currency or PLN),
        (c.rate_candidate_currency or c.currency or PLN),
    }
    return unit == RateUnit.hourly.value and currencies == {PLN}


async def load_world(db: AsyncSession) -> World:
    stmt = (
        select(Contract)
        .where(
            Contract.candidate_id.is_not(None),
            Contract.voided_at.is_(None),
            Contract.status != ContractStatus.void,
        )
        .options(
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.candidate_rate_schedule),
        )
    )
    contracts: dict[int, ContractRow] = {}
    for c in (await db.scalars(stmt)).all():
        contracts[c.id] = ContractRow(
            id=c.id,
            candidate_id=c.candidate_id,
            client_id=c.client_id,
            start_date=c.start_date,
            end_date=c.end_date,
            hourly_pln=_hourly_pln(c),
            client_schedule=_steps(c.client_rate_schedule),
            cost_schedule=_steps(c.candidate_rate_schedule),
            client_scalar=Decimal(c.rate_client) if c.rate_client is not None else None,
            cost_scalar=(
                Decimal(c.rate_candidate) if c.rate_candidate is not None else None
            ),
        )
    people = {c.candidate_id for c in contracts.values()}
    tokens: dict[int, frozenset[str]] = {}
    for cid, first, last in (
        await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname).where(
                Candidate.id.in_(people)
            )
        )
    ).all():
        tokens[cid] = frozenset(name_tokens(f"{first or ''} {last or ''}"))
    numbers: dict[tuple[int, str], set[int]] = defaultdict(set)
    for client_id, contract_id, value in (
        await db.execute(
            select(
                ClientExternalId.client_id,
                ClientExternalId.contract_id,
                ClientExternalId.value,
            ).where(
                ClientExternalId.kind == "client_person_no",
                ClientExternalId.state == "confirmed",
            )
        )
    ).all():
        if contract_id in contracts:
            numbers[(client_id, value.strip().upper())].add(contract_id)
    open_months: dict[int, set[str]] = defaultdict(set)
    for contract_id, month in (
        await db.execute(
            select(ClientSettlement.contract_id, ClientSettlement.period_month).where(
                ClientSettlement.status != _SETTLED
            )
        )
    ).all():
        open_months[contract_id].add(month)
    return World(
        contracts=contracts,
        person_tokens=tokens,
        person_numbers=dict(numbers),
        open_settlements=dict(open_months),
    )


async def _linked_contracts(
    db: AsyncSession, first_year: int, last_year: int
) -> dict[int, set[int]]:
    """Faktura → kontrakty z przypiętych zamówień (zamówienie albo linie grupy)."""

    out: dict[int, set[int]] = defaultdict(set)
    rows = await db.execute(
        select(ClientSalesInvoiceLink.invoice_id, ClientOrder.contract_id)
        .join(
            ClientOrder,
            or_(
                ClientOrder.id == ClientSalesInvoiceLink.order_id,
                and_(
                    ClientSalesInvoiceLink.order_id.is_(None),
                    ClientOrder.order_group_id == ClientSalesInvoiceLink.order_group_id,
                ),
            ),
        )
        .where(
            ClientSalesInvoiceLink.period_year.between(first_year, last_year),
            ClientOrder.contract_id.is_not(None),
        )
    )
    for invoice_id, contract_id in rows.all():
        out[invoice_id].add(contract_id)
    return out


async def load_inputs(
    db: AsyncSession,
    *,
    first_month: str,
    last_month: str,
    contract_ids: Optional[set[int]] = None,
) -> list[infer.ContractInput]:
    """Wejścia reguły dla kontraktów z fakturami w miesiącach [first, last]."""

    world = await load_world(db)
    months = set()
    m = first_month
    while m <= last_month:
        months.add(m)
        m = shift(m, 1)
    first_year, last_year = int(first_month[:4]), int(last_month[:4])
    links = await _linked_contracts(db, first_year, last_year)
    sales_stmt = select(ClientSalesInvoice).where(
        ClientSalesInvoice.period_year.between(first_year, last_year)
    )
    if contract_ids is not None:
        # Jeden kontrakt (decyzja na karcie): faktury jego klienta wystarczą;
        # dopasowanie osób i tak czyta wszystkich z kontraktami.
        clients = {
            world.contracts[c].client_id for c in contract_ids if c in world.contracts
        }
        sales_stmt = sales_stmt.where(ClientSalesInvoice.client_id.in_(clients))
    sales = [
        SalesRow(
            invoice_number=r.invoice_number,
            client_id=r.client_id,
            month=(
                f"{r.period_year}-{r.period_month:02d}"
                if r.period_year and r.period_month
                else None
            ),
            issue_date=r.issue_date,
            currency=r.currency,
            correction=r.invoice_kind == "correction",
            items=tuple(r.items or ()),
            linked_contracts=frozenset(links.get(r.id, ())),
        )
        for r in (await db.scalars(sales_stmt)).all()
    ]
    # Faktura za ostatni miesiąc przychodzi do ok. 20. dnia następnego.
    issued_from = infer.month_start(first_month)
    costs = [
        CostRow(
            invoice_number=r.invoice_number or r.ksef_number or str(r.id),
            seller_name=r.seller_name or "",
            issue_date=r.issue_date,
            currency=r.currency,
            net=Decimal(r.net_amount),
            correction=(r.ksef_invoice_type or "").lower().startswith("kor"),
        )
        for r in (
            await db.scalars(
                select(ApprovalDocument).where(
                    ApprovalDocument.source == "ksef",
                    ApprovalDocument.issue_date >= issued_from,
                    ApprovalDocument.net_amount.is_not(None),
                    ApprovalDocument.issue_date.is_not(None),
                )
            )
        ).all()
    ]
    inputs = build_inputs(world, sales, costs, months)
    if contract_ids is not None:
        inputs = [i for i in inputs if i.contract_id in contract_ids]
    return inputs
