"""Dokument z maila, który powtarza zamówienie już zapisane w NEXUSIE.

Zgłoszenie z 28.11.2026: kolejka trzymała w „Do weryfikacji” PDF-y, których
zamówienie ktoś już założył ręcznie (ten sam numer, okres i stawka — stawka
bywa tylko w innej jednostce: 1200 zł/MD w PDF-ie, 150 zł/h w zamówieniu),
i osoby, które już są na linii zamówienia MD z tym numerem. Planer daje wtedy
``revision`` albo ``group``, bramka wstrzymuje, a człowiek musiał zamknąć
dokument, który niczego nie wnosi.

Reguła: dokument, w którym KAŻDY wiersz planu wskazuje JEDNO istniejące
zamówienie tej osoby (aktywne, wstrzymane albo zakończone) z tym samym
numerem, tym samym okresem, tą samą stawką (po przeliczeniu jednostki,
w granicy grosza), walutą i pulą, kolejka zamyka sama: ``dismissed`` z
powodem „To samo co zamówienie #N”. Pula (liczba MD, wartość) jest
porównywana tylko wtedy, gdy podają ją OBIE strony — zamówienie założone
ręcznie często jej nie ma, a dokument jednoosobowy niesie ją zawsze.

Każda różnica zostawia dokument w kolejce z powodem „odczyt różni się od #N:
stawka” — także błąd odczytu (18700 zł/MD zamiast 870): to nie zmiana
zamówienia, ale ma go zobaczyć człowiek.

Sprawdzenie idzie przy każdym ocenieniu dokumentu, który zostaje w kolejce:
odczyt nowego maila i „Przelicz plan” (w tym godzinowa ponowna weryfikacja),
więc dokumenty, które już czekają, zamykają się w najbliższym biegu — bez
skryptu na produkcji.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.work_time import HOURS_PER_MONTH
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import RateUnit
from app.models.order_mail import (
    GATE_AUTO,
    OUTCOME_DISMISSED,
    OUTCOME_NEEDS_REVIEW,
    OrderMailDocument,
)
from app.services.order_mail_gate import CODE_DIFFERS_FROM_ORDER, CODE_SAME_AS_ORDER
from app.services.order_mail_planner import titles_collide
from app.services.order_rate_snapshots import convert_order_rate

#: Zamówienie, które dokument może powtarzać. Szkic jeszcze nie obowiązuje
#: (dokument bywa właśnie jego treścią), anulowane — nie doszło do skutku,
#: więc ponownie przysłany PDF ma zobaczyć człowiek.
SAME_ORDER_STATUSES = (
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
    ClientOrderStatus.completed,
)
#: „W granicy grosza” — dla stawki po przeliczeniu jednostki i dla puli.
TOLERANCE = Decimal("0.01")

FIELD_PERIOD = "okres"
FIELD_RATE = "stawka"
FIELD_CURRENCY = "waluta"
FIELD_POOL = "pula"

_ROW_UNIT = {
    "hour": RateUnit.hourly,
    "day": RateUnit.daily,
    "month": RateUnit.monthly,
}


@dataclass(frozen=True)
class OrderSnapshot:
    """To, co dokument musi powtórzyć, żeby być „tym samym zamówieniem”."""

    id: int
    #: Tytuł zamówienia i — przy linii zamówienia MD/kosztowego — numer grupy.
    numbers: tuple[str, ...]
    start_date: Optional[date]
    end_date: Optional[date]
    rate_client: Optional[Decimal]
    rate_unit: Optional[str]
    billing_hours_per_month: Optional[int]
    currency: Optional[str]
    md_total: Optional[Decimal]
    total_value: Optional[Decimal]


@dataclass
class SameOrderCheck:
    #: Wypełnione wtedy i tylko wtedy, gdy dokument można zamknąć.
    same_order_ids: list[int] = field(default_factory=list)
    #: ``(osoba z wiersza, id zamówienia, pola)`` dla wierszy z różnicą.
    differences: list[tuple[str, int, list[str]]] = field(default_factory=list)

    @property
    def closes(self) -> bool:
        return bool(self.same_order_ids)


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOLERANCE


def _rate_matches(row: dict[str, Any], order: OrderSnapshot) -> bool:
    rate = _dec(row.get("rate_client"))
    if rate is None or order.rate_client is None or not order.rate_unit:
        return False
    order_unit = RateUnit(order.rate_unit)
    row_unit = _ROW_UNIT.get(row.get("rate_unit") or "")
    if row_unit is None:
        # Wiersz bez jednostki nie mówi, za co jest kwota — nie zgadujemy.
        return False
    in_row_unit = convert_order_rate(
        order.rate_client,
        order_unit,
        row_unit,
        order.billing_hours_per_month or HOURS_PER_MONTH,
    )
    return in_row_unit is not None and _close(rate, in_row_unit)


def _pool_matches(row: dict[str, Any], order: OrderSnapshot) -> bool:
    md = _dec(row.get("md_total"))
    if md is not None and order.md_total is not None and not _close(md, order.md_total):
        return False
    value = _dec(row.get("total_value"))
    if (
        value is not None
        and order.total_value is not None
        and not _close(value, order.total_value)
    ):
        return False
    return True


def row_differences(row: dict[str, Any], order: OrderSnapshot) -> list[str]:
    """Pola, w których wiersz planu różni się od zamówienia (pusta = to samo)."""
    out: list[str] = []
    period = (
        order.start_date.isoformat() if order.start_date else None,
        order.end_date.isoformat() if order.end_date else None,
    )
    if (row.get("start_date") or None, row.get("end_date") or None) != period:
        out.append(FIELD_PERIOD)
    if not _rate_matches(row, order):
        out.append(FIELD_RATE)
    currency = (row.get("currency") or "").strip().upper()
    if currency and currency != (order.currency or "PLN").upper():
        out.append(FIELD_CURRENCY)
    if not _pool_matches(row, order):
        out.append(FIELD_POOL)
    return out


def check_rows(
    proposal: Optional[dict[str, Any]],
    orders_by_contract: dict[int, list[OrderSnapshot]],
) -> SameOrderCheck:
    """Czysta reguła: czy KAŻDY wiersz planu to istniejące zamówienie.

    Wiersz bez kontraktu, bez numeru albo z kilkoma zamówieniami o tym numerze
    nie jest „tym samym” — dokument zostaje w kolejce bez nowego powodu,
    bo nie ma jednego zamówienia, z którym da się go porównać.
    """
    result = SameOrderCheck()
    proposal = proposal or {}
    rows = proposal.get("rows") or []
    if not rows or proposal.get("blocking"):
        return result
    same: list[int] = []
    for row in rows:
        number = row.get("title") or proposal.get("order_number")
        contract_id = row.get("contract_id")
        if not number or not contract_id:
            continue
        candidates = [
            o
            for o in orders_by_contract.get(contract_id, [])
            if any(titles_collide(n, number) for n in o.numbers)
        ]
        if len(candidates) != 1:
            continue
        diff = row_differences(row, candidates[0])
        if diff:
            result.differences.append(
                (row.get("row_name") or "", candidates[0].id, diff)
            )
        else:
            same.append(candidates[0].id)
    if len(same) == len(rows):
        result.same_order_ids = sorted(set(same))
    return result


def same_as_order_reason(order_ids: list[int]) -> str:
    listing = ", ".join(f"#{i}" for i in order_ids)
    return (
        f"To samo co zamówienie {listing} — numer, okres, stawka i pula się "
        "zgadzają; dokument zamknięty bez zmian"
    )


def differs_from_order_reason(row_name: str, order_id: int, fields: list[str]) -> str:
    prefix = f"„{row_name}”: " if row_name else ""
    return f"{prefix}odczyt różni się od #{order_id}: {', '.join(fields)}"


async def load_orders(
    db: AsyncSession, client_id: int, contract_ids: set[int]
) -> dict[int, list[OrderSnapshot]]:
    if not contract_ids:
        return {}
    pairs = (
        await db.execute(
            select(ClientOrder, ClientOrderGroup.order_number)
            .outerjoin(
                ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id
            )
            .where(
                ClientOrder.client_id == client_id,
                ClientOrder.contract_id.in_(contract_ids),
                ClientOrder.status.in_(SAME_ORDER_STATUSES),
            )
        )
    ).all()
    out: dict[int, list[OrderSnapshot]] = {}
    for order, group_number in pairs:
        value = order.total_value
        if value is None and order.md_total is not None and order.md_rate_revenue:
            value = order.md_total * order.md_rate_revenue
        unit = order.rate_unit
        out.setdefault(order.contract_id, []).append(
            OrderSnapshot(
                id=order.id,
                numbers=tuple(n for n in (order.title, group_number) if n),
                start_date=order.start_date,
                end_date=order.end_date,
                rate_client=order.rate_client,
                rate_unit=unit.value if hasattr(unit, "value") else unit,
                billing_hours_per_month=order.billing_hours_per_month,
                currency=order.rate_client_currency or order.currency,
                md_total=order.md_total,
                total_value=value,
            )
        )
    return out


async def close_when_same_as_existing(db: AsyncSession, row: OrderMailDocument) -> bool:
    """Zamknij dokument powtarzający zapisane zamówienie; różnicę dopisz do powodów.

    Woła się na dokumencie ocenionym bramką, który zostaje w kolejce. Zwraca
    ``True``, gdy dokument został zamknięty. Nie commituje.
    """
    from app.services.order_mail_ingest import gate_hold_pairs, set_gate_hold

    if (
        row.outcome != OUTCOME_NEEDS_REVIEW
        or row.gate_verdict == GATE_AUTO
        or not row.client_id
    ):
        return False
    proposal = getattr(row, "proposal", None) or {}
    contract_ids = {
        r["contract_id"] for r in proposal.get("rows") or [] if r.get("contract_id")
    }
    if not contract_ids:
        return False
    orders = await load_orders(db, row.client_id, contract_ids)
    check = check_rows(proposal, orders)
    if check.closes:
        set_gate_hold(
            row, [(CODE_SAME_AS_ORDER, same_as_order_reason(check.same_order_ids))]
        )
        row.document_meta = {
            **{k: v for k, v in (row.document_meta or {}).items() if k != "recheck"},
            # Ten sam stempel co „Odrzuć” w kolejce: odrzucony PO odczycie
            # zostaje oryginałem dla ponownie przysłanego PDF-a.
            "dismissed_from": OUTCOME_NEEDS_REVIEW,
            "same_as_orders": check.same_order_ids,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }
        row.outcome = OUTCOME_DISMISSED
        if row.id is not None:
            from app.services.dl_alerts import resolve_entity_alerts

            await resolve_entity_alerts(
                db, alert_type="order_mail_review", entity_key=f"order_mail:{row.id}"
            )
        return True
    if check.differences:
        set_gate_hold(
            row,
            [
                *gate_hold_pairs(row),
                *(
                    (CODE_DIFFERS_FROM_ORDER, differs_from_order_reason(*d))
                    for d in check.differences
                ),
            ],
        )
    return False
