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
from app.services.client_identity import client_display_name_expression
from app.services.client_order_lines import consultant_display_name
from app.services.delivery_alert_recipients import (
    DeliveryAlertRecipientScope,
    load_delivery_alert_recipient_scope,
)
from app.services.dl_alerts import dl_user_ids_for_client, emit
from app.services.shared_md_orders import uses_shared_md_pool

logger = logging.getLogger(__name__)

Rule = Callable[[AsyncSession, DeliveryAlertRecipientScope | None], Awaitable[int]]


def _client_link(client_id: int) -> str:
    return f"/clients/{client_id}?tab=zamowienia"


async def _client_names(db: AsyncSession, client_ids: set[int]) -> dict[int, str]:
    if not client_ids:
        return {}
    rows = await db.execute(
        select(
            Client.id,
            client_display_name_expression().label("client_name"),
        ).where(Client.id.in_(client_ids))
    )
    return {cid: name for cid, name in rows}


async def rule_draft_consultant_unassigned(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
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
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    created = 0
    for order in orders:
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
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


async def rule_md_budget_low(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Kończące się MD — osobno przy osobie i osobno we wspólnej puli.

    Próg jest GLOBALNY (``DL_ALERT_MD_THRESHOLD``), bez konfiguracji per klient
    — ticket wprost tego wymaga, żeby „poniżej progu" znaczyło to samo
    w każdym raporcie. Z tego samego powodu wspólna pula dostaje ten SAM próg
    bezwzględny, a nie procent budżetu: „mało MD" ma znaczyć tyle samo dni
    niezależnie od tego, czy budżet wisi przy osobie, czy na zamówieniu.
    """
    threshold = Decimal(str(settings.DL_ALERT_MD_THRESHOLD))
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    created = await _md_low_per_consultant(db, threshold, recipient_scope)
    created += await _md_low_shared_pool(db, threshold, recipient_scope)
    return created


async def _md_low_per_consultant(
    db: AsyncSession,
    threshold: Decimal,
    recipient_scope: DeliveryAlertRecipientScope,
) -> int:
    """Aktywna linia z własnym budżetem MD i pozostałością poniżej progu."""
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
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
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


async def _md_low_shared_pool(
    db: AsyncSession,
    threshold: Decimal,
    recipient_scope: DeliveryAlertRecipientScope,
) -> int:
    """Wspólna pula MD (Lotte Wedel, Cyfrowy Polsat) poniżej progu.

    Osobne zapytanie, bo budżet mieszka gdzie indziej: przy tych dwóch
    klientach linia konsultanta NIE MA ``md_remaining``, więc reguła oparta
    o linie mijała je w całości. Skutek był taki, że jedyny alert budżetowy,
    jaki te zamówienia w ogóle dostawały, przychodził dopiero po zejściu puli
    do zera — czyli wtedy, gdy zamówienie już przestało przyjmować ludzi.

    ``uses_shared_md_pool`` sprawdzamy PONOWNIE w Pythonie, mimo filtra po
    ``is_md_budget_based`` w zapytaniu: sama flaga nie jest miarodajna, bo
    rewizja 0246 ustawiała ją każdemu jawnemu typowi ``md``, a historyczne
    wiersze innych klientów wciąż ją niosą. Alert wysłany takiemu wierszowi
    mówiłby o puli, której na jego karcie nie ma.
    """
    result = await db.execute(
        select(ClientOrderGroup).where(
            ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
            ClientOrderGroup.is_md_budget_based.is_(True),
            ClientOrderGroup.md_budget_remaining.isnot(None),
            ClientOrderGroup.md_budget_remaining < threshold,
        )
    )
    groups = [group for group in result.scalars() if uses_shared_md_pool(group)]
    names = await _client_names(db, {group.client_id for group in groups})
    created = 0
    for group in groups:
        user_ids = await dl_user_ids_for_client(
            db, group.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        client_name = names.get(group.client_id, "Klient")
        number = group.order_number or "—"
        alerts = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=user_ids,
            client_id=group.client_id,
            # Inny prefiks niż `order:` — wspólna pula jest sprawą CAŁEGO
            # zamówienia, nie konkretnej linii, a klucze obu wariantów muszą
            # żyć w rozłącznych przestrzeniach.
            entity_key=f"group:{group.id}",
            title=f"{client_name} — mało MD na zamówieniu {number}",
            message=(
                f"⏳ {client_name} — we wspólnej puli zamówienia {number} "
                f"pozostało mniej niż {int(threshold)} MD. Zwiększ pulę albo "
                "zorganizuj nowe zamówienie."
            ),
            link=_client_link(group.client_id),
            payload={
                "order_number": number,
                "md_remaining": str(group.md_budget_remaining),
                "shared_pool": True,
            },
            order_group_id=group.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        )
        created += len(alerts)
    return created


async def rule_missing_revenue_rate(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
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
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    created = 0
    for order in orders:
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
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
    recipient_scope = await load_delivery_alert_recipient_scope(db)
    for name, rule in ALERT_RULES.items():
        try:
            # SAVEPOINT, nie wspólna transakcja z `db.rollback()` w except.
            # Rollback SESJI cofa też wstawienia reguł, które już się udały —
            # commit na końcu zapisywałby wtedy pustkę, a `created[...]`
            # raportowałoby liczby wierszy, których w bazie nie ma. To ten sam
            # tryb awarii co przy fazie `workflows` importu Traffita.
            async with db.begin_nested():
                created[name] = await rule(db, recipient_scope)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # Padnięta reguła nie może zabrać pozostałych: to cztery niezależne
            # warunki. Savepoint cofa wyłącznie jej własną pracę.
            logger.exception("dl_alerts rule %s failed", name)
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
