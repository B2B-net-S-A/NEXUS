"""Nocny raport: stawka z kontraktu a stawka linii zamówienia MD (audyt A5).

Synchronizacja kontrakt → zamówienie celowo pomija linie zamówień zbiorczych
(``contract_order_sync``, ``order_group_id``): stawkę linii prowadzi Delivery
Lead, a marża i MRR wciąż biorą ją z kontraktu. Różnica niczego nie psuje przy
zapisie, tylko po cichu zawyża albo zaniża wynik, więc Finanse dostają listę.

Raport niczego nie poprawia. Dotyczy ostatniego zamkniętego miesiąca, bo dopiero
za niego jest zużycie MD, a więc skutek w złotówkach. Każdy wiersz mówi, kogo i
ile dotyczy, bez identyfikatorów z bazy: Finanse szukają po osobie, kliencie,
kwocie i miesiącu.

Kontrakt bez stawki to brak danych, a nie rozjazd (szkice z obsady), a kontrakt
z szablonu w innej walucie niż linia nie daje się porównać bez kursu — takie
pozycje są tylko policzone.

Pozycja „godzinowy kontrakt zaokrąglony” (945 zł/MD to 118,125 zł/h, a kontrakt
ma 118 zł/h) to rozjazd pozorny, więc idzie na koniec listy z oznaczeniem.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.app_setting import AppSetting
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.md_consumption import ClientOrderMdConsumption
from app.services.client_identity import client_display_name
from app.services.client_order_lines import consultant_display_name
from app.services.order_rate_snapshots import contract_rate_in_unit

SETTING_KEY = "contract_order_rate_divergences"
#: Różnica poniżej grosza to reszta z przeliczenia jednostek.
_TOLERANCE = Decimal("0.01")
_HOURS_PER_MD = Decimal(8)
#: Kontrakt godzinowy w pełnych złotych: do 0,50 zł/h, czyli 4 zł/MD.
_ROUNDING_PER_MD = Decimal("4.00")
_ORDER_STATUSES = (ClientOrderStatus.active, ClientOrderStatus.completed)
_CONTRACT_STATUSES = (
    ContractStatus.active,
    ContractStatus.ending,
    ContractStatus.ended,
)

Leg = Literal["revenue", "cost"]
LEG_LABELS: dict[Leg, str] = {"revenue": "przychód", "cost": "koszt"}


@dataclass(frozen=True)
class Divergence:
    person: str
    client_name: str
    order_number: str
    leg: Leg
    leg_label: str
    month: str
    currency: str
    contract_rate: str
    order_rate: str
    difference: str
    md: Optional[str]
    effect: Optional[str]
    rounding: bool
    #: Karta zamówień klienta, żeby przejść do sprawy; nie idzie do tekstu.
    link: str


def report_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    next_first = date(year + (month == 12), month % 12 + 1, 1)
    return date(year, month, 1), date.fromordinal(next_first.toordinal() - 1)


def _plain(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _order_number(order: ClientOrder) -> str:
    group = order.order_group
    return (group.order_number if group else None) or order.title or "bez numeru"


def _is_rounding(contract: Contract, difference: Decimal) -> bool:
    return (
        RateUnit(contract.rate_unit) == RateUnit.hourly
        and abs(difference) <= _ROUNDING_PER_MD
    )


def _sort_key(row: Divergence) -> tuple[bool, Decimal, Decimal, str]:
    effect = abs(Decimal(row.effect)) if row.effect is not None else Decimal(0)
    return (row.rounding, -effect, -abs(Decimal(row.difference)), row.person.lower())


async def _line_orders(
    db: AsyncSession, first_day: date, last_day: date
) -> list[ClientOrder]:
    return list(
        await db.scalars(
            select(ClientOrder)
            .join(Contract, Contract.id == ClientOrder.contract_id)
            .options(
                selectinload(ClientOrder.client),
                selectinload(ClientOrder.order_group),
                selectinload(ClientOrder.contract).selectinload(Contract.candidate),
                selectinload(ClientOrder.contract).selectinload(
                    Contract.client_rate_schedule
                ),
                selectinload(ClientOrder.contract).selectinload(
                    Contract.candidate_rate_schedule
                ),
            )
            .where(
                ClientOrder.order_group_id.is_not(None),
                ClientOrder.status.in_(_ORDER_STATUSES),
                Contract.status.in_(_CONTRACT_STATUSES),
                or_(
                    ClientOrder.md_rate_revenue.is_not(None),
                    ClientOrder.md_rate_cost.is_not(None),
                ),
                or_(
                    ClientOrder.start_date.is_(None), ClientOrder.start_date <= last_day
                ),
                or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= first_day),
            )
        )
    )


async def _md_by_order(
    db: AsyncSession, order_ids: list[int], period: str
) -> dict[int, Decimal]:
    if not order_ids:
        return {}
    rows = await db.execute(
        select(
            ClientOrderMdConsumption.order_id, ClientOrderMdConsumption.md_reported
        ).where(
            ClientOrderMdConsumption.order_id.in_(order_ids),
            ClientOrderMdConsumption.period_month == period,
        )
    )
    return {int(order_id): Decimal(md) for order_id, md in rows}


def _contract_leg(
    contract: Contract, order: ClientOrder, leg: Leg, on_day: date
) -> tuple[Optional[Decimal], str, str]:
    """(stawka kontraktu za MD albo brak, waluta kontraktu, waluta linii)."""

    if leg == "revenue":
        rate = contract.effective_client_rate(on_day)
        currency = contract.resolved_rate_client_currency
        line_currency = order.rate_client_currency
    else:
        rate = contract.effective_candidate_rate(on_day)
        currency = contract.resolved_rate_candidate_currency
        line_currency = order.rate_candidate_currency
    return (
        contract_rate_in_unit(rate, contract, RateUnit.daily),
        currency,
        (line_currency or order.currency or "PLN").upper(),
    )


def _line_divergences(
    order: ClientOrder,
    *,
    period: str,
    last_day: date,
    md: Optional[Decimal],
    counters: dict[str, int],
) -> list[Divergence]:
    contract = order.contract
    on_day = min(order.end_date or last_day, last_day)
    out: list[Divergence] = []
    for leg, line_rate in (
        ("revenue", order.md_rate_revenue),
        ("cost", order.md_rate_cost),
    ):
        if line_rate is None:
            continue
        contract_rate, currency, line_currency = _contract_leg(
            contract, order, leg, on_day
        )
        if contract_rate is None or contract_rate <= 0:
            counters["no_contract_rate"] += 1
            continue
        if currency != line_currency:
            counters["other_currency"] += 1
            continue
        difference = Decimal(line_rate) - contract_rate
        if abs(difference) < _TOLERANCE:
            continue
        out.append(
            Divergence(
                person=consultant_display_name(order),
                client_name=client_display_name(order.client),
                order_number=_order_number(order),
                leg=leg,
                leg_label=LEG_LABELS[leg],
                month=period,
                currency=currency,
                contract_rate=_plain(contract_rate),
                order_rate=_plain(Decimal(line_rate)),
                difference=_plain(difference),
                md=_plain(md) if md is not None else None,
                effect=_plain(difference * md) if md is not None else None,
                rounding=_is_rounding(contract, difference),
                link=f"/clients/{order.client_id}?tab=zamowienia",
            )
        )
    return out


async def build_report(
    db: AsyncSession, *, today: date, generated_at: Optional[datetime] = None
) -> dict[str, Any]:
    """Świeże rozjazdy ostatniego zamkniętego miesiąca (nic nie zapisuje)."""

    year, month = report_month(today)
    period = f"{year:04d}-{month:02d}"
    first_day, last_day = _month_bounds(year, month)
    orders = await _line_orders(db, first_day, last_day)
    consumption = await _md_by_order(db, [order.id for order in orders], period)
    counters = {"no_contract_rate": 0, "other_currency": 0}
    rows: list[Divergence] = []
    for order in orders:
        rows.extend(
            _line_divergences(
                order,
                period=period,
                last_day=last_day,
                md=consumption.get(order.id),
                counters=counters,
            )
        )
    rows.sort(key=_sort_key)
    return {
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "month": period,
        "checked_lines": len(orders),
        "skipped": counters,
        "rows": [asdict(row) for row in rows],
    }


async def refresh(db: AsyncSession, *, today: date) -> dict[str, Any]:
    """Przelicza raport i zapisuje go jako stan na tę noc."""

    report = await build_report(db, today=today)
    statement = insert(AppSetting).values(key=SETTING_KEY, value=report)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value},
        )
    )
    return report


async def latest(db: AsyncSession) -> Optional[dict[str, Any]]:
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SETTING_KEY)
    )
    return value if isinstance(value, dict) else None


__all__ = [
    "Divergence",
    "LEG_LABELS",
    "SETTING_KEY",
    "build_report",
    "latest",
    "refresh",
    "report_month",
]
