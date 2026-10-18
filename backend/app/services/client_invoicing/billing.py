"""„Do faktury” — co zafakturować klientowi za miesiąc, policzone z zamówień.

Nic nie zapisujemy: pozycje liczą się przy odczycie z danych, które już są
w NEXUSIE, więc import zużycia MD za miesiąc od razu zmienia porównanie
z fakturą z KSeF.

Wiersz = zamówienie, które się fakturuje:

* **zamówienie MD** (grupa z numerem klienta, osoby jako linie) — dla każdej
  osoby zużycie MD z miesiąca × jej stawka przychodowa (``md_rate_revenue``,
  PLN/MD). Wspólna pula MD: zejście puli z podziałem na osoby (``breakdown``),
  bez podziału — jedna pozycja, jeśli wszystkie osoby mają tę samą stawkę;
  inaczej kwoty nie liczymy (Finanse widzą „brak podziału puli”),
* **zamówienie kosztowe** — tak samo zużycie MD × stawka; kwota z kolumny
  „Faktura” arkusza Finansów (``client_order_invoice_consumptions``) zostaje
  obok jako zapas „zafakturowano wg arkusza”, gdy faktury z KSeF jeszcze nie
  ma (odczyt z KSeF zastępuje import, import zostaje),
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

from sqlalchemy import select
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

CENT = Decimal("0.01")
_SETTLING = (ClientOrderStatus.active, ClientOrderStatus.completed)
_NOT_BILLED_GROUPS = (GROUP_STATUS_DRAFT, GROUP_STATUS_CANCELLED)
UNIT_LABELS = {"md": "MD", "hours": "h", "days": "dni", "month": "mies."}
_SAP_PREFIX = re.compile(r"^SAP[\s:-]*(\d+)$", re.IGNORECASE)


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
class BillingRow:
    """Zamówienie do zafakturowania w miesiącu."""

    client_id: int
    kind: str  # md | cost | periodic
    group_id: Optional[int]
    order_id: Optional[int]
    order_number: str
    currency: str
    lines: tuple[BillingLine, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return f"g{self.group_id}" if self.group_id is not None else f"o{self.order_id}"

    @property
    def expected_net(self) -> Optional[Decimal]:
        """Suma pozycji; ``None``, gdy którejś kwoty nie da się policzyć."""

        if not self.lines or any(line.net is None for line in self.lines):
            return None
        return money(sum((line.net for line in self.lines), Decimal("0")))

    @property
    def missing(self) -> int:
        return sum(1 for line in self.lines if line.net is None)

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
        """Numer i jego postać bez prefiksu ``SAP`` (Polkomtel zapisuje „SAP 45…”)."""

        found = _SAP_PREFIX.match(self.number)
        return (self.number, found.group(1)) if found else (self.number,)


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


def _md_line(
    order: ClientOrder,
    md: Optional[Decimal],
    *,
    sheet: Optional[Decimal] = None,
) -> BillingLine:
    name = _consultant(order)
    rate = order.md_rate_revenue
    if md is None:
        return BillingLine(
            order_id=order.id,
            consultant=name,
            basis="md",
            quantity=None,
            unit_price=Decimal(rate) if rate is not None else None,
            net=None,
            currency="PLN",
            note="czeka na zużycie MD za miesiąc",
            sheet_invoiced=sheet,
        )
    if rate is None:
        return BillingLine(
            order_id=order.id,
            consultant=name,
            basis="md",
            quantity=md,
            unit_price=None,
            net=None,
            currency="PLN",
            note="osoba bez stawki MD do klienta",
            sheet_invoiced=sheet,
        )
    return BillingLine(
        order_id=order.id,
        consultant=name,
        basis="md",
        quantity=md,
        unit_price=Decimal(rate),
        net=money(md * Decimal(rate)),
        currency="PLN",
        sheet_invoiced=sheet,
    )


def _pool_lines(
    group: ClientOrderGroup,
    lines: list[ClientOrder],
    pool: Optional[ClientOrderGroupMdConsumption],
) -> list[BillingLine]:
    """Wspólna pula MD: podział z panelu zamówienia albo jedna stawka dla wszystkich."""

    if pool is None:
        return [_md_line(order, None) for order in lines]
    split: dict[int, Decimal] = {}
    for part in pool.breakdown or []:
        try:
            split[int(part["order_id"])] = Decimal(str(part["md"]))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    if split:
        return [
            _md_line(order, split.get(order.id)) for order in lines if order.id in split
        ]
    rates = {order.md_rate_revenue for order in lines if order.md_rate_revenue}
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
                currency="PLN",
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
            currency="PLN",
            note="osoby mają różne stawki, a zejście puli nie ma podziału na osoby",
        )
    ]


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
    orders = list((await db.scalars(order_query)).all())

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
        if group.is_md_budget_based:
            lines = _pool_lines(group, members, pools.get(group_id))
        else:
            lines = [
                _md_line(
                    order,
                    md_by_line.get(order.id),
                    sheet=sheet_by_line.get(order.id) if group.is_cost_based else None,
                )
                for order in members
            ]
        rows.append(
            BillingRow(
                client_id=group.client_id,
                kind="cost" if group.is_cost_based else "md",
                group_id=group.id,
                order_id=None,
                order_number=(group.order_number or "").strip() or f"#{group.id}",
                currency="PLN",
                lines=tuple(lines),
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
    "BillingLine",
    "BillingRow",
    "OrderRef",
    "billing_rows",
    "money",
    "month_key",
    "order_refs",
    "period_fraction",
    "plain",
]
