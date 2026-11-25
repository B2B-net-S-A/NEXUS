"""„Do faktury” — co zafakturować klientowi za miesiąc, policzone z zamówień.

Nic nie zapisujemy: pozycje liczą się przy odczycie z danych, które już są
w NEXUSIE, więc import zużycia MD za miesiąc od razu zmienia porównanie
z fakturą z KSeF.

Wiersz = zamówienie, które się fakturuje:

* **zamówienie MD** (grupa z numerem klienta, osoby jako linie) — dla każdej
  osoby zużycie MD z miesiąca × jej stawka przychodowa (``md_rate_revenue``,
  PLN/MD; zamówienie w obcej walucie — ``rate_client``, bez przeliczania
  kursem, patrz ``_group_currency``). Wspólna pula MD (``shared_md_orders.uses_shared_md_pool`` — sama
  flaga ``is_md_budget_based`` z 0246 nie rozstrzyga): zejście puli z podziałem
  na osoby (``breakdown`` albo wiersze importu, ``shared_md_month_people``),
  bez podziału — jedna pozycja, jeśli wszystkie osoby mają tę samą stawkę;
  inaczej kwoty nie liczymy (Finanse widzą „brak podziału puli”),
* **zamówienie kosztowe** — rozlicza FAKTURĘ, nie MD: linie nie mają
  budżetu MD (``md_total IS NULL``) i import MD ich nie dotyka, więc kwoty
  „do faktury” NEXUS nie liczy — ustalają ją Finanse. Wiersz ma jedną pozycję
  (osoby z zamówienia) i budżet zamówienia (``CostBudget``): kwota oraz to, co
  zostało przed fakturami za ten miesiąc — pula ``budget_amount`` + korekta
  minus faktury z wcześniejszych miesięcy rozliczone przez
  ``cost_orders.settle_group`` (arkusz Finansów,
  ``client_order_invoice_consumptions``). Faktura z KSeF jest sprawdzana
  z tą resztą (``ledger.check``). Kwota z kolumny „Faktura” arkusza za ten
  miesiąc zostaje obok jako zapas „wg arkusza Finansów”, gdy faktury z KSeF
  jeszcze nie ma,
* **zamówienie okresowe** (samodzielne ``client_orders``) — stawka klienta
  według jednostki zamówienia: miesięczna × miesiąc, godzinowa × godziny
  z zamówienia (``billing_hours_per_month``, domyślnie 168 h), dzienna ×
  dni (godziny ÷ 8). Częściowy miesiąc (start albo koniec w środku) liczymy
  proporcją dni roboczych (pon–pt bez świąt ustawowych). To kwota według
  zamówienia, nie według raportu godzin klienta — różnicę sprawdzają Finanse.

Osoba bez zużycia MD za miesiąc ma pozycję bez kwoty („czeka na zużycie
MD”) — kwota wiersza jest wtedy nieznana, a nie zaniżona. Linia osoby
liczy się w miesiącu wtedy, gdy jej okres obejmuje miesiąc choćby jednym
dniem (ta sama reguła co import MD: ``line_settles_in_month``); anulowane
i szkice (poza kosztowymi) nie.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.work_time import HOURS_PER_MD_DEC, HOURS_PER_MONTH
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_CANCELLED,
    GROUP_STATUS_DRAFT,
    ClientOrderGroup,
    ClientOrderGroupMdConsumption,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    ClientOrderMdConsumption,
)
from app.services.client_order_lines import line_settles_in_month
from app.services.hr.calendar import month_range
from app.services.order_burn_rate import workdays_between
from app.services.order_engagement_separation import AUTO_DRAFT_TITLE_PLACEHOLDER
from app.services.order_rate_snapshots import convert_order_rate
from app.services.order_revenue_steps import priced_for_month
from app.services.shared_md_orders import (
    shared_md_import_breakdowns,
    shared_md_month_people,
    uses_shared_md_pool,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
COST_NOTE = "zamówienie kosztowe — kwotę faktury ustalają Finanse"
_SETTLING = (ClientOrderStatus.active, ClientOrderStatus.completed)
_NOT_BILLED_GROUPS = (GROUP_STATUS_DRAFT, GROUP_STATUS_CANCELLED)
UNIT_LABELS = {"md": "MD", "hours": "h", "days": "dni", "month": "mies."}
_SAP_PREFIX = re.compile(r"^SAP[\s:-]*(\d+)$", re.IGNORECASE)
#: „Zamówienie nr 3/07/2026/BL” i „3/07/2026/BL” to ten sam numer zamówienia.
TITLE_PREFIX = re.compile(r"^\s*zam[óo]wienie\s+(nr\.?\s*)?", re.IGNORECASE)
#: Reszta tytułu jest numerem, gdy to jeden wyraz z cyfrą (jak ``number_from_title``).
_TITLE_NUMBER = re.compile(r"[\w./-]{2,40}")
#: Znak kancelaryjny przed numerem („L.dz. KIR/DAZ/…”, „LDZ.dz.KIR/…”): faktura go nie podaje.
_REGISTRY_PREFIX = re.compile(r"^\s*l\.?\s*dz\.?(?:\s*dz\.?)?\s*", re.IGNORECASE)
#: Numer grupy z dopiskiem po myślniku („4500000777- Wsparcie on-site”); „1234567-9” to jeden numer.
_DESCRIBED_NUMBER = re.compile(r"^([\w./]*\d[\w./]*)\s*[-–—]\s+\S")
#: Krótszy początek („2026 — opis”) związałby fakturę po dacie.
_DESCRIBED_NUMBER_MIN = 6


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def plain(value: Optional[Decimal]) -> Optional[str]:
    """Liczba bez zbędnych zer (``21.000000`` → ``21``, ``19.5`` zostaje)."""

    if value is None:
        return None
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized.quantize(Decimal("1")), "f")
    return format(normalized, "f")


@dataclass(frozen=True)
class BillingLine:
    """Pozycja „do faktury” jednej osoby (albo puli) w wierszu zamówienia."""

    order_id: Optional[int]
    consultant: str
    basis: str
    quantity: Optional[Decimal]
    unit_price: Optional[Decimal]
    net: Optional[Decimal]
    currency: str
    note: Optional[str] = None
    #: Kwota z kolumny „Faktura” arkusza Finansów (zamówienia kosztowe).
    sheet_invoiced: Optional[Decimal] = None

    @property
    def unit(self) -> str:
        return UNIT_LABELS.get(self.basis, "")


@dataclass(frozen=True)
class CostBudget:
    """Budżet zamówienia kosztowego widziany z miesiąca usługi."""

    #: Kwota zamówienia (``budget_amount``).
    amount: Decimal
    #: Zostało przed fakturami za ten miesiąc: pula (kwota + korekta) minus
    #: faktury z wcześniejszych miesięcy rozliczone w budżecie. Faktura za ten
    #: miesiąc z arkusza Finansów się tu nie odejmuje — to ta sama faktura,
    #: którą porównujemy z KSeF.
    available: Decimal


@dataclass(frozen=True)
class BillingRow:
    """Zamówienie do zafakturowania w miesiącu."""

    client_id: int
    kind: str  # md | cost | periodic
    group_id: Optional[int]
    order_id: Optional[int]
    order_number: str
    currency: str
    lines: tuple[BillingLine, ...] = field(default_factory=tuple)
    #: Tylko zamówienie kosztowe: budżet i linie osób (jedna pozycja na wiersz).
    budget: Optional[CostBudget] = None
    member_ids: frozenset[int] = frozenset()

    @property
    def key(self) -> str:
        return f"g{self.group_id}" if self.group_id is not None else f"o{self.order_id}"

    @property
    def expected_net(self) -> Optional[Decimal]:
        """Suma pozycji; ``None``, gdy którejś kwoty nie da się policzyć.

        Zamówienie kosztowe zawsze ``None`` — kwotę faktury ustalają Finanse.
        """

        if not self.lines or any(line.net is None for line in self.lines):
            return None
        return money(sum((line.net for line in self.lines), Decimal("0")))

    @property
    def missing(self) -> int:
        """Pozycje, którym brakuje danych (zużycia MD, stawki) — bez kosztowych."""

        return sum(
            1 for line in self.lines if line.net is None and line.basis != "cost"
        )

    @property
    def sheet_invoiced(self) -> Optional[Decimal]:
        values = [line.sheet_invoiced for line in self.lines if line.sheet_invoiced]
        return money(sum(values, Decimal("0"))) if values else None

    @property
    def line_order_ids(self) -> frozenset[int]:
        return frozenset(line.order_id for line in self.lines if line.order_id)

    def line_for(self, order_id: int) -> Optional[BillingLine]:
        return next((line for line in self.lines if line.order_id == order_id), None)


@dataclass(frozen=True)
class OrderRef:
    """Numer zamówienia klienta — do szukania w treści faktury."""

    client_id: int
    group_id: Optional[int]
    order_id: Optional[int]
    number: str

    @property
    def key(self) -> str:
        return f"g{self.group_id}" if self.group_id is not None else f"o{self.order_id}"

    def variants(self) -> tuple[str, ...]:
        """Numer i jego postaci bez prefiksu ``SAP`` (Polkomtel zapisuje „SAP 45…”)
        i bez „Zamówienie nr” z tytułu: faktura podaje „nr zamówienia: 9001/2026”,
        a tytuł to „Zamówienie nr 9001/2026”. Tytuł opisowy numeru nie daje."""

        found = [self.number]
        sap = _SAP_PREFIX.match(self.number)
        if sap:
            found.append(sap.group(1))
        bare = TITLE_PREFIX.sub("", self.number).strip()
        if (
            bare != self.number
            and _TITLE_NUMBER.fullmatch(bare)
            and any(ch.isdigit() for ch in bare)
        ):
            found.append(bare)
        for value in self._cleaned(bare):
            if value not in found:
                found.append(value)
        return tuple(found)

    def _cleaned(self, bare: str) -> list[str]:
        """Numer zapisany z ozdobnikiem, którego faktura nie powtarza (audyt 25.11.2026).

        Znak kancelaryjny „L.dz.” zdejmujemy zawsze. Dopisek po myślniku i dwa
        numery sklejone ukośnikiem („OIT/0001/2025/IT/OIT/0002/2026/IT”) czytamy
        tylko w numerze grupy: to pole na numer, a tytuł samodzielnego zamówienia
        bywa opisem, z którego numeru nie bierzemy.
        """

        found: list[str] = []
        unprefixed = _REGISTRY_PREFIX.sub("", bare).strip()
        if unprefixed != bare and _is_number(unprefixed):
            found.append(unprefixed)
        if self.group_id is None:
            return found
        described = _DESCRIBED_NUMBER.match(self.number)
        if described and len(described.group(1)) >= _DESCRIBED_NUMBER_MIN:
            found.append(described.group(1))
        prefix = self.number.split("/", 1)[0]
        if prefix.isalpha() and len(prefix) >= 2 and f"/{prefix}/" in self.number:
            first, *rest = self.number.split(f"/{prefix}/")
            found.extend(
                part
                for part in [first, *(f"{prefix}/{tail}" for tail in rest)]
                if _is_number(part)
            )
        return found


def _is_number(value: str) -> bool:
    return bool(_TITLE_NUMBER.fullmatch(value)) and any(ch.isdigit() for ch in value)


def _consultant(order: ClientOrder) -> str:
    contract = order.contract
    candidate = contract.candidate if contract is not None else None
    if candidate is not None:
        name = f"{candidate.name or ''} {candidate.lastname or ''}".strip()
        if name:
            return name
    return f"konsultant (zamówienie #{order.id})"


def _contract_ok(order: ClientOrder) -> bool:
    contract = order.contract
    return contract is None or contract.status != ContractStatus.void


def period_fraction(
    start: Optional[date], end: Optional[date], first: date, last: date
) -> tuple[Decimal, Optional[str]]:
    """Część miesiąca, w której zamówienie trwało — po dniach roboczych."""

    begin = max(start or first, first)
    finish = min(end or last, last)
    total = workdays_between(first, last)
    if begin <= first and finish >= last:
        return Decimal("1"), None
    worked = workdays_between(begin, finish)
    if total <= 0:
        return Decimal("0"), None
    note = f"częściowy miesiąc: {worked} z {total} dni roboczych"
    return Decimal(worked) / Decimal(total), note


def _periodic_line(order: ClientOrder, first: date, last: date) -> BillingLine:
    currency = (order.rate_client_currency or order.currency or "PLN").upper()
    name = _consultant(order)
    fraction, partial = period_fraction(order.start_date, order.end_date, first, last)
    rate = order.rate_client
    if rate is None:
        return BillingLine(
            order_id=order.id,
            consultant=name,
            basis="month",
            quantity=None,
            unit_price=None,
            net=None,
            currency=currency,
            note="zamówienie bez stawki klienta",
        )
    price = Decimal(rate)
    unit = order.rate_unit or RateUnit.monthly
    hours = Decimal(order.billing_hours_per_month or HOURS_PER_MONTH)
    if unit == RateUnit.hourly:
        quantity = (hours * fraction).quantize(CENT, rounding=ROUND_HALF_UP)
        basis = "hours"
        note = partial or f"{plain(hours)} h w miesiącu wg zamówienia"
        net = money(quantity * price)
    elif unit == RateUnit.daily:
        days = hours / HOURS_PER_MD_DEC
        quantity = (days * fraction).quantize(CENT, rounding=ROUND_HALF_UP)
        basis = "days"
        note = partial or f"{plain(days)} dni w miesiącu wg zamówienia"
        net = money(quantity * price)
    else:
        # Kwota z pełnej proporcji; ilość tylko do pokazania.
        quantity = fraction.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        basis = "month"
        note = partial
        net = money(fraction * price)
    return BillingLine(
        order_id=order.id,
        consultant=name,
        basis=basis,
        quantity=quantity,
        unit_price=price,
        net=net,
        currency=currency,
        note=note,
    )


def _line_currency(order: ClientOrder) -> str:
    return (order.rate_client_currency or order.currency or "PLN").upper()


def _group_currency(lines: list[ClientOrder]) -> str:
    """Waluta wiersza zamówienia MD.

    Linie w różnych walutach zostają na stawkach PLN/MD: suma EUR + PLN nie
    ma sensu, a przeliczać na walutę faktury nie wolno.
    """

    currencies = {_line_currency(order) for order in lines}
    return currencies.pop() if len(currencies) == 1 else "PLN"


def _client_md_rate(order: ClientOrder, currency: str) -> Optional[Decimal]:
    """Stawka za MD w walucie wiersza.

    ``md_rate_revenue`` jest zawsze w PLN/MD (materializator przelicza kursem
    z dnia startu), a stawkę z zamówienia niesie ``rate_client``. Brak tej
    stawki w obcej walucie to brak kwoty, nie kwota w złotych.
    """

    if currency == "PLN":
        return order.md_rate_revenue
    return convert_order_rate(
        order.rate_client,
        order.rate_unit or RateUnit.daily,
        RateUnit.daily,
        order.billing_hours_per_month or HOURS_PER_MONTH,
    )


def _md_line(order: ClientOrder, md: Optional[Decimal], currency: str) -> BillingLine:
    name = _consultant(order)
    rate = _client_md_rate(order, currency)
    if md is None:
        return BillingLine(
            order_id=order.id,
            consultant=name,
            basis="md",
            quantity=None,
            unit_price=Decimal(rate) if rate is not None else None,
            net=None,
            currency=currency,
            note="czeka na zużycie MD za miesiąc",
        )
    if rate is None:
        return BillingLine(
            order_id=order.id,
            consultant=name,
            basis="md",
            quantity=md,
            unit_price=None,
            net=None,
            currency=currency,
            note="osoba bez stawki MD do klienta",
        )
    return BillingLine(
        order_id=order.id,
        consultant=name,
        basis="md",
        quantity=md,
        unit_price=Decimal(rate),
        net=money(md * Decimal(rate)),
        currency=currency,
    )


def _pool_lines(
    group: ClientOrderGroup,
    lines: list[ClientOrder],
    pool: Optional[ClientOrderGroupMdConsumption],
    import_split: dict[str, list[tuple[int, Decimal]]],
) -> list[BillingLine]:
    """Wspólna pula MD: podział z panelu albo importu, inaczej jedna stawka dla wszystkich."""

    currency = _group_currency(lines)
    if pool is None:
        return [_md_line(order, None, currency) for order in lines]
    split: dict[int, Decimal] = {}
    for part in pool.breakdown or []:
        try:
            split[int(part["order_id"])] = Decimal(str(part["md"]))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    if not pool.breakdown:
        people, _source = shared_md_month_people(pool, import_split)
        split = dict(people or [])
    if split:
        return [
            _md_line(order, split.get(order.id), currency)
            for order in lines
            if order.id in split
        ]
    rates = {rate for order in lines if (rate := _client_md_rate(order, currency))}
    if len(rates) == 1 and lines:
        rate = next(iter(rates))
        md = Decimal(pool.md_reported)
        return [
            BillingLine(
                order_id=None,
                consultant=f"wspólna pula MD ({len(lines)} os.)",
                basis="md",
                quantity=md,
                unit_price=Decimal(rate),
                net=money(md * Decimal(rate)),
                currency=currency,
            )
        ]
    return [
        BillingLine(
            order_id=None,
            consultant="wspólna pula MD",
            basis="md",
            quantity=Decimal(pool.md_reported),
            unit_price=None,
            net=None,
            currency=currency,
            note="osoby mają różne stawki, a zejście puli nie ma podziału na osoby",
        )
    ]


def _cost_line(
    members: list[ClientOrder], sheet_by_line: dict[int, Decimal]
) -> BillingLine:
    """Jedna pozycja zamówienia kosztowego: osoby, bez kwoty, z zapasem z arkusza."""

    sheet = [sheet_by_line[order.id] for order in members if order.id in sheet_by_line]
    return BillingLine(
        order_id=None,
        consultant=", ".join(_consultant(order) for order in members),
        basis="cost",
        quantity=None,
        unit_price=None,
        net=None,
        currency="PLN",
        note=COST_NOTE,
        sheet_invoiced=money(sum(sheet, Decimal("0"))) if sheet else None,
    )


def _cost_budget(group: ClientOrderGroup, settled_before: Decimal) -> CostBudget:
    """Lustro ``cost_orders.settle_group``: pula nie schodzi poniżej zera."""

    amount = money(Decimal(group.budget_amount))
    pool = max(amount + money(Decimal(group.budget_manual_adjustment or 0)), ZERO)
    return CostBudget(amount=amount, available=max(pool - money(settled_before), ZERO))


async def _settled_before(
    db: AsyncSession, group_ids: list[int], period: str
) -> dict[int, Decimal]:
    """Faktury z arkusza Finansów rozliczone w budżecie przed miesiącem ``period``."""

    if not group_ids:
        return {}
    rows = await db.execute(
        select(
            ClientOrder.order_group_id,
            func.coalesce(func.sum(ClientOrderInvoiceConsumption.settled_amount), 0),
        )
        .join(ClientOrder, ClientOrder.id == ClientOrderInvoiceConsumption.order_id)
        .where(
            ClientOrder.order_group_id.in_(group_ids),
            ClientOrderInvoiceConsumption.period_month < period,
        )
        .group_by(ClientOrder.order_group_id)
    )
    return {int(group_id): Decimal(total) for group_id, total in rows.all()}


async def billing_rows(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    client_ids: Optional[Collection[int]] = None,
) -> list[BillingRow]:
    """Wiersze „do faktury” za miesiąc (``client_ids=None`` — wszyscy klienci)."""

    first, last = month_range(year, month)
    period = month_key(year, month)
    clients = sorted(set(client_ids)) if client_ids is not None else None
    if clients is not None and not clients:
        return []

    order_query = (
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract).selectinload(Contract.candidate))
        .where(
            ClientOrder.status.in_((*_SETTLING, ClientOrderStatus.draft)),
            (ClientOrder.start_date.is_(None)) | (ClientOrder.start_date <= last),
            (ClientOrder.end_date.is_(None)) | (ClientOrder.end_date >= first),
        )
    )
    if clients is not None:
        order_query = order_query.where(ClientOrder.client_id.in_(clients))
    # Stawka przychodowa z pierwszego dnia miesiąca — aneks stawki klienta
    # zmienia ją od swojego dnia, miesiące wcześniej zostają po starej
    # (``services/order_revenue_steps.py``).
    orders = await priced_for_month(
        db, list((await db.scalars(order_query)).all()), first
    )

    group_ids = {o.order_group_id for o in orders if o.order_group_id is not None}
    groups: dict[int, ClientOrderGroup] = {}
    if group_ids:
        groups = {
            g.id: g
            for g in await db.scalars(
                select(ClientOrderGroup).where(
                    ClientOrderGroup.id.in_(group_ids),
                    ClientOrderGroup.status.not_in(_NOT_BILLED_GROUPS),
                )
            )
        }
    line_ids = [o.id for o in orders if o.order_group_id in groups]
    md_by_line: dict[int, Decimal] = {}
    sheet_by_line: dict[int, Decimal] = {}
    pools: dict[int, ClientOrderGroupMdConsumption] = {}
    if line_ids:
        md_by_line = {
            int(order_id): Decimal(md)
            for order_id, md in (
                await db.execute(
                    select(
                        ClientOrderMdConsumption.order_id,
                        ClientOrderMdConsumption.md_reported,
                    ).where(
                        ClientOrderMdConsumption.order_id.in_(line_ids),
                        ClientOrderMdConsumption.period_month == period,
                    )
                )
            ).all()
        }
        sheet_by_line = {
            int(order_id): Decimal(amount)
            for order_id, amount in (
                await db.execute(
                    select(
                        ClientOrderInvoiceConsumption.order_id,
                        ClientOrderInvoiceConsumption.invoice_amount,
                    ).where(
                        ClientOrderInvoiceConsumption.order_id.in_(line_ids),
                        ClientOrderInvoiceConsumption.period_month == period,
                    )
                )
            ).all()
        }
        pools = {
            p.group_id: p
            for p in await db.scalars(
                select(ClientOrderGroupMdConsumption).where(
                    ClientOrderGroupMdConsumption.group_id.in_(list(groups)),
                    ClientOrderGroupMdConsumption.period_month == period,
                )
            )
        }

    import_splits = {
        group_id: await shared_md_import_breakdowns(db, group_id)
        for group_id, pool in pools.items()
        if pool.source == "import" and not pool.breakdown
    }

    settled_before = await _settled_before(
        db, [gid for gid, group in groups.items() if group.is_cost_based], period
    )

    by_group: dict[int, list[ClientOrder]] = defaultdict(list)
    rows: list[BillingRow] = []
    for order in sorted(orders, key=lambda o: (o.start_date or first, o.id)):
        if not _contract_ok(order):
            continue
        if order.order_group_id is not None:
            group = groups.get(order.order_group_id)
            if group is None:
                continue
            if not line_settles_in_month(
                order,
                period,
                contract=order.contract,
                include_draft=bool(group.is_cost_based),
            ):
                continue
            by_group[group.id].append(order)
            continue
        if order.status not in _SETTLING:
            continue
        title = (order.title or "").strip()
        if not title or title == AUTO_DRAFT_TITLE_PLACEHOLDER:
            title = f"zamówienie #{order.id}"
        line = _periodic_line(order, first, last)
        rows.append(
            BillingRow(
                client_id=order.client_id,
                kind="periodic",
                group_id=None,
                order_id=order.id,
                order_number=title,
                currency=line.currency,
                lines=(line,),
            )
        )

    for group_id, members in by_group.items():
        group = groups[group_id]
        budget: Optional[CostBudget] = None
        currency = "PLN"
        if group.is_cost_based:
            lines = [_cost_line(members, sheet_by_line)]
            budget = _cost_budget(group, settled_before.get(group_id, ZERO))
        else:
            currency = _group_currency(members)
            if uses_shared_md_pool(group):
                lines = _pool_lines(
                    group,
                    members,
                    pools.get(group_id),
                    import_splits.get(group_id, {}),
                )
            else:
                lines = [
                    _md_line(order, md_by_line.get(order.id), currency)
                    for order in members
                ]
        rows.append(
            BillingRow(
                client_id=group.client_id,
                kind="cost" if group.is_cost_based else "md",
                group_id=group.id,
                order_id=None,
                order_number=(group.order_number or "").strip() or f"#{group.id}",
                currency=currency,
                lines=tuple(lines),
                budget=budget,
                member_ids=frozenset(order.id for order in members)
                if budget is not None
                else frozenset(),
            )
        )
    rows.sort(key=lambda row: (row.client_id, row.order_number.lower(), row.key))
    return rows


async def order_refs(db: AsyncSession, client_ids: Iterable[int]) -> list[OrderRef]:
    """Numery zamówień klientów (każdy okres) — numer samodzielnego zamówienia to tytuł."""

    ids = sorted(set(client_ids))
    if not ids:
        return []
    refs: list[OrderRef] = []
    for group_id, client_id, number in (
        await db.execute(
            select(
                ClientOrderGroup.id,
                ClientOrderGroup.client_id,
                ClientOrderGroup.order_number,
            ).where(
                ClientOrderGroup.client_id.in_(ids),
                ClientOrderGroup.status != GROUP_STATUS_CANCELLED,
            )
        )
    ).all():
        if number and str(number).strip():
            refs.append(
                OrderRef(int(client_id), int(group_id), None, str(number).strip())
            )
    for order_id, client_id, title in (
        await db.execute(
            select(ClientOrder.id, ClientOrder.client_id, ClientOrder.title).where(
                ClientOrder.client_id.in_(ids),
                ClientOrder.order_group_id.is_(None),
                ClientOrder.status != ClientOrderStatus.cancelled,
            )
        )
    ).all():
        text_ = str(title or "").strip()
        if text_ and text_ != AUTO_DRAFT_TITLE_PLACEHOLDER:
            refs.append(OrderRef(int(client_id), None, int(order_id), text_))
    return refs


__all__ = [
    "COST_NOTE",
    "TITLE_PREFIX",
    "BillingLine",
    "BillingRow",
    "CostBudget",
    "OrderRef",
    "billing_rows",
    "money",
    "month_key",
    "order_refs",
    "period_fraction",
    "plain",
]
