"""Dzienny skaner warunków, które generują powiadomienia Delivery Leada.

Cztery reguły w JEDNYM rejestrze ``ALERT_RULES``. Dołożenie piątej to dopisanie
funkcji i wpisu — nie przebudowa sekcji ani skanera (wymóg ticketu). Sama
mechanika cykliczności i wstrzymywania powtórek siedzi w
``app/services/dl_alerts.py``; tutaj są wyłącznie warunki.

Reguła #1 (wyczerpanie zamówienia kosztowego) świadomie NIE jest tutaj — jest
zdarzeniowa, emitowana w chwili, w której budżet spada do zera
(``services/cost_orders.settle_group`` + ścieżka importu). Skaner powtarzałby
ją co tydzień, a ona opisuje stan, który się już nie zmienia.

Trzy pozostałe są STANOWE: warunek trwa, dopóki ktoś czegoś nie uzupełni, więc
powtarzają się co ``DL_ALERT_REPEAT_DAYS`` dni — każda powtórka jako nowy wiersz
w logu, żeby raport pokazywał, ile tygodni sprawa czekała.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
from app.models.contract import Contract
from app.models.dl_alert import (
    ALERT_DRAFT_CONSULTANT_UNASSIGNED,
    ALERT_MD_BUDGET_LOW,
    ALERT_MISSING_REVENUE_RATE,
)
from app.services.client_order_lines import consultant_display_name
from app.services.dl_alerts import dl_user_ids_for_client, emit

logger = logging.getLogger(__name__)

Rule = Callable[[AsyncSession], Awaitable[int]]


def _client_link(client_id: int) -> str:
    return f"/clients/{client_id}?tab=zamowienia"


async def _client_names(db: AsyncSession, client_ids: set[int]) -> dict[int, str]:
    if not client_ids:
        return {}
    rows = await db.execute(
        select(Client.id, Client.name).where(Client.id.in_(client_ids))
    )
    return {cid: name for cid, name in rows}


async def rule_draft_consultant_unassigned(db: AsyncSession) -> int:
    """Konsultant z zamówieniem w statusie Draft — czeka na uzupełnienie.

    To ta sama populacja, którą zakładka „Zamówienia" pokazuje pod pigułką
    „Draft (do uzupełnienia)". Alert istnieje dlatego, że draft powstaje
    automatycznie z hooka „hired" i nikt go nie widzi, dopóki sam nie wejdzie
    na profil klienta.
    """
    result = await db.execute(
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract).selectinload(Contract.candidate))
        .where(ClientOrder.status == ClientOrderStatus.draft)
    )
    orders = list(result.scalars())
    names = await _client_names(db, {o.client_id for o in orders})
    created = 0
    for order in orders:
        user_ids = await dl_user_ids_for_client(db, order.client_id)
        if not user_ids:
            continue
        who = consultant_display_name(order) or "Konsultant"
        client_name = names.get(order.client_id, "Klient")
        alerts = await emit(
            db,
            alert_type=ALERT_DRAFT_CONSULTANT_UNASSIGNED,
            user_ids=user_ids,
            client_id=order.client_id,
            entity_key=f"order:{order.id}",
            title=f"{client_name} — {who} bez zamówienia",
            message=(
                f"🆕 {client_name} — {who} czeka na przypisanie do zamówienia "
                "(status: Draft). Potrzebne jest zamówienie dla tej osoby."
            ),
            link=_client_link(order.client_id),
            payload={"consultant": who},
            order_id=order.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        )
        created += len(alerts)
    return created


async def rule_md_budget_low(db: AsyncSession) -> int:
    """Aktywna linia MD z pozostałością poniżej progu.

    Próg jest GLOBALNY (``DL_ALERT_MD_THRESHOLD``), bez konfiguracji per klient
    — ticket wprost tego wymaga, żeby „poniżej progu" znaczyło to samo
    w każdym raporcie.
    """
    threshold = Decimal(str(settings.DL_ALERT_MD_THRESHOLD))
    result = await db.execute(
        select(ClientOrder)
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrder.md_remaining.isnot(None),
            ClientOrder.md_remaining < threshold,
            ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
        )
    )
    orders = list(result.scalars())
    names = await _client_names(db, {o.client_id for o in orders})
    created = 0
    for order in orders:
        user_ids = await dl_user_ids_for_client(db, order.client_id)
        if not user_ids:
            continue
        group = order.order_group
        number = group.order_number if group else "—"
        client_name = names.get(order.client_id, "Klient")
        alerts = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=user_ids,
            client_id=order.client_id,
            entity_key=f"order:{order.id}",
            title=f"{client_name} — mało MD na zamówieniu {number}",
            message=(
                f"⏳ {client_name} — zamówieniu {number} pozostało mniej niż "
                f"{int(threshold)} MD. Zorganizuj nowe zamówienie/przedłużenie."
            ),
            link=_client_link(order.client_id),
            payload={
                "order_number": number,
                "md_remaining": str(order.md_remaining),
            },
            order_group_id=order.order_group_id,
            order_id=order.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        )
        created += len(alerts)
    return created


async def rule_missing_revenue_rate(db: AsyncSession) -> int:
    """Aktywne zamówienie bez uzupełnionej stawki przychodowej.

    Dwa źródła, bo stawka przychodowa mieszka w dwóch kolumnach: linia
    wielo-konsultantowa trzyma ją w ``md_rate_revenue`` (zł/MD), a zwykłe
    zamówienie w ``rate_client``. Pytanie o jedną z nich pomijałoby połowę
    zamówień w systemie.
    """
    result = await db.execute(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.order_group),
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
        )
        .where(
            ClientOrder.status == ClientOrderStatus.active,
            (
                (
                    ClientOrder.order_group_id.isnot(None)
                    & ClientOrder.md_rate_revenue.is_(None)
                )
                | (
                    ClientOrder.order_group_id.is_(None)
                    & ClientOrder.rate_client.is_(None)
                )
            ),
        )
    )
    orders = list(result.scalars())
    names = await _client_names(db, {o.client_id for o in orders})
    created = 0
    for order in orders:
        user_ids = await dl_user_ids_for_client(db, order.client_id)
        if not user_ids:
            continue
        group = order.order_group
        number = group.order_number if group else order.title
        who = consultant_display_name(order) or "konsultanta"
        client_name = names.get(order.client_id, "Klient")
        alerts = await emit(
            db,
            alert_type=ALERT_MISSING_REVENUE_RATE,
            user_ids=user_ids,
            client_id=order.client_id,
            entity_key=f"order:{order.id}",
            title=f"{client_name} — brak stawki przychodowej",
            message=(
                f"✏️ {client_name} — uzupełnij stawkę przychodową dla {who} "
                f"w zamówieniu {number}."
            ),
            link=_client_link(order.client_id),
            payload={"order_number": number, "consultant": who},
            order_group_id=order.order_group_id,
            order_id=order.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        )
        created += len(alerts)
    return created


#: Rejestr reguł. Dołożenie piątego typu alertu = dopisanie funkcji i wpisu.
ALERT_RULES: dict[str, Rule] = {
    ALERT_DRAFT_CONSULTANT_UNASSIGNED: rule_draft_consultant_unassigned,
    ALERT_MD_BUDGET_LOW: rule_md_budget_low,
    ALERT_MISSING_REVENUE_RATE: rule_missing_revenue_rate,
}


async def run_once(db: AsyncSession | None = None) -> dict[str, int]:
    """Jeden przebieg wszystkich reguł. Zwraca liczbę nowych wpisów per reguła."""
    if not settings.DL_ALERTS_ENABLED:
        return {}
    if db is not None:
        return await _run_rules(db)
    async with AsyncSessionLocal() as session:
        return await _run_rules(session)


async def _run_rules(db: AsyncSession) -> dict[str, int]:
    created: dict[str, int] = {}
    for name, rule in ALERT_RULES.items():
        try:
            created[name] = await rule(db)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # Padnięta reguła nie może zabrać pozostałych: to cztery niezależne
            # warunki, a wspólny rollback zamieniłby jeden błąd w ciszę na
            # całej sekcji.
            logger.exception("dl_alerts rule %s failed", name)
            await db.rollback()
            created[name] = 0
    await db.commit()
    return created


async def dl_alerts_loop() -> None:
    """Dzienna pętla. Kill-switch sprawdzany PRZED pętlą, nie w środku.

    Wyłączona funkcja ma nie budzić procesu co 24 h tylko po to, żeby sprawdzić
    tę samą flagę (ten sam błąd naprawiano w pętli CloudTalka).
    """
    if not settings.DL_ALERTS_ENABLED:
        logger.info("dl_alerts_loop disabled (DL_ALERTS_ENABLED=false)")
        return
    interval = max(1.0, float(settings.DL_ALERTS_INTERVAL_HOURS)) * 3600
    while True:
        try:
            summary = await run_once()
            if summary:
                logger.info("dl_alerts scan created %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("dl_alerts_loop iteration failed")
        await asyncio.sleep(interval)
