"""Rozliczenie, które czeka na zamówienie: ponad pulę albo na zamówieniu zakończonym.

Próba IX–X 2026: w 5 przypadkach MD były dobre, a rozliczenie czekało na
Finanse, bo zamówienie w NEXUS-ie się nie domykało (ponad pulę o 2–16,5 MD,
dwa razy mail klienta wskazał zamówienie zakończone w NEXUS-ie). Delivery Lead
dostawał wcześniej najwyżej „mało MD na zamówieniu” (próg 21 MD), które po
odhaczeniu albo po zakończeniu zamówienia milknie, a po uzupełnieniu zamówienia
rozliczenie zostawało „Z uwagami”, dopóki Finanse czegoś nie kliknęły.

* **Problem czytamy z zapisanego przeliczenia** (``service.meta_of``):
  ``md_over`` przy jednym zamówieniu, a przy podziale z maila klienta część
  na zamówieniu zakończonym albo ponad jego pulę. Bez drugiego liczenia puli.
* **Alert** (``rule_settlement_over_order`` w ``dl_alerts_scanner``) dostaje
  Delivery Lead klienta z linkiem do zamówienia, dla rozliczeń jeszcze nie
  przyjętych i nie odesłanych do poprawy, z ostatnich ``MONTHS_BACK`` miesięcy.
* **Przeliczenie po zmianie zamówienia** (``refresh_client``): utworzenie,
  przedłużenie, dopisanie osoby, aktywacja szkicu (``settle_awaiting_md_for_client``),
  edycja linii albo zamówienia. Przeliczamy tylko otwarte rozliczenia klienta,
  które mają problem z zamówieniem albo stawką linii, każde w osobnym punkcie
  zapisu: awaria przeliczenia nie cofa zapisu zamówienia. Wiersz zajęty przez
  przyjęcie Finansów pomijamy (``skip_locked``), żeby nie nadpisać przyjęcia.
* **Zapas** (``refresh_stale``, raz na bieg skanera): rozliczenia z problemem,
  których kontrakt, linia albo zamówienie zmieniły się po ostatnim przeliczeniu,
  też przez ścieżkę bez haka.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.models.client_order_revenue_step import ClientOrderRevenueStep
from app.models.client_settlement import ClientSettlement
from app.models.contract import Contract
from app.services.client_settlements import line_rate
from app.services.client_settlements import settings as module_settings

logger = logging.getLogger(__name__)

#: Rozliczenia jeszcze przed decyzją Finansów (bez przyjętych i „Do poprawy”).
OPEN_STATUSES = ("checking", "ok", "warnings", "no_md")
#: Miesiąc rozliczenia i tyle wcześniejszych (jak automat przyjęć).
MONTHS_BACK = 3
OVER, CLOSED = "over", "closed"


@dataclass(frozen=True)
class OrderIssue:
    kind: str
    order_id: int
    number: Optional[str]
    #: MD ponad pulę (``over``) albo MD rozliczane na zakończonym (``closed``).
    md: Decimal


def _meta(s: ClientSettlement) -> dict[str, Any]:
    for item in s.checks or []:
        if isinstance(item, dict) and "remaining_after" in item:
            return item
    return {}


def _dec(value: Any) -> Optional[Decimal]:
    try:
        return None if value in (None, "") else Decimal(str(value))
    except ArithmeticError:
        return None


def issues_of(s: ClientSettlement) -> list[OrderIssue]:
    """Problemy z zamówieniem zapisane przy ostatnim przeliczeniu. Bez bazy."""

    meta = _meta(s)
    out: list[OrderIssue] = []
    for part in meta.get("orders") or []:
        if not isinstance(part, dict) or not part.get("order_id"):
            continue
        order_id, number = int(part["order_id"]), part.get("number")
        remaining = _dec(part.get("remaining_after"))
        if part.get("closed"):
            out.append(OrderIssue(CLOSED, order_id, number, _dec(part.get("md")) or 0))
        elif remaining is not None and remaining < 0:
            out.append(OrderIssue(OVER, order_id, number, -remaining))
    if out or meta.get("orders"):
        return out
    over = _dec(meta.get("md_over"))
    if over and over > 0 and s.order_id:
        out.append(OrderIssue(OVER, s.order_id, None, over))
    return out


def needs_refresh(s: ClientSettlement) -> bool:
    """Rozliczenie, które może się zmienić po zmianie zamówienia albo stawki."""

    if s.md_regular is None:
        return False
    return (
        bool(issues_of(s))
        or bool(line_rate.mismatches_of(_meta(s)))
        or s.status == "no_md"
        or s.order_id is None
    )


def month_floor(today: date) -> str:
    index = today.year * 12 + today.month - 1 - MONTHS_BACK
    return f"{index // 12}-{index % 12 + 1:02d}"


def _open(today: date):
    return (
        select(ClientSettlement)
        .where(
            ClientSettlement.kind == "actual",
            ClientSettlement.status.in_(OPEN_STATUSES),
            ClientSettlement.period_month >= month_floor(today),
            ClientSettlement.md_regular.is_not(None),
        )
        .order_by(ClientSettlement.period_month, ClientSettlement.id)
    )


async def open_settlements(
    db: AsyncSession, today: date, *, client_id: Optional[int] = None
) -> list[ClientSettlement]:
    query = _open(today)
    if client_id is not None:
        query = query.where(ClientSettlement.client_id == client_id)
    return list(await db.scalars(query))


async def _recompute_each(db: AsyncSession, rows: Iterable[ClientSettlement]) -> int:
    from app.services.client_settlements import service

    done = 0
    for row in rows:
        try:
            async with db.begin_nested():
                # Blokada wiersza na czas przeliczenia; zajęty (przyjęcie Finansów
                # w toku) pomijamy, a przyjęty w międzyczasie już nie jest otwarty.
                s = await db.scalar(
                    select(ClientSettlement)
                    .where(
                        ClientSettlement.id == row.id,
                        ClientSettlement.status.in_(OPEN_STATUSES),
                    )
                    .with_for_update(skip_locked=True)
                    .execution_options(populate_existing=True)
                )
                if s is None:
                    continue
                await service.recompute_and_store(db, s)
                # Przeliczenie bez zmiany wyniku też jest przeliczeniem: zapas
                # w skanerze porównuje zmiany zamówień z tą chwilą.
                s.updated_at = func.now()
            done += 1
        except Exception:  # noqa: BLE001 — zapis zamówienia nie może przez to paść
            logger.exception(
                "settlement %s: przeliczenie po zmianie zamówienia", row.id
            )
    return done


async def refresh_client(
    db: AsyncSession, *, client_id: int, today: Optional[date] = None
) -> int:
    """Po zmianie zamówienia klienta: przelicz jego otwarte rozliczenia z problemem.

    Zwraca liczbę przeliczonych. Wołający commituje."""

    from app.core.scheduling import business_today

    if not await module_settings.is_enabled(db):
        return 0
    await db.flush()
    rows = list(
        await db.scalars(
            _open(today or business_today()).where(
                ClientSettlement.client_id == client_id,
                # Już przeliczone w tej transakcji (drugi hak tego samego zapisu).
                ClientSettlement.updated_at < func.now(),
            )
        )
    )
    return await _recompute_each(db, [s for s in rows if needs_refresh(s)])


async def _changed_since(db: AsyncSession, s: ClientSettlement) -> bool:
    """Kontrakt, jego linie, ich zamówienia albo stawki zmienione po przeliczeniu."""

    since = s.updated_at
    order = await db.scalar(
        select(ClientOrder.id)
        .outerjoin(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .outerjoin(
            ClientOrderRevenueStep, ClientOrderRevenueStep.order_id == ClientOrder.id
        )
        .where(
            ClientOrder.contract_id == s.contract_id,
            or_(
                ClientOrder.updated_at > since,
                ClientOrderGroup.updated_at > since,
                ClientOrderRevenueStep.created_at > since,
            ),
        )
        .limit(1)
    )
    if order is not None:
        return True
    contract = await db.scalar(
        select(Contract.updated_at).where(Contract.id == s.contract_id)
    )
    return contract is not None and contract > since


async def refresh_stale(db: AsyncSession, today: date) -> int:
    """Zapas dla ścieżek bez haka: przelicz rozliczenia z problemem zamówienia,
    których zamówienie albo kontrakt zmieniły się po ostatnim przeliczeniu."""

    if not await module_settings.is_enabled(db):
        return 0
    rows = await open_settlements(db, today)
    stale = [s for s in rows if needs_refresh(s) and await _changed_since(db, s)]
    return await _recompute_each(db, stale)
