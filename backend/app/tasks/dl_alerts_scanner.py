"""Dzienny skaner warunków, które generują powiadomienia Delivery Leada.

Cztery reguły w JEDNYM rejestrze ``ALERT_RULES``. Dołożenie piątej to dopisanie
funkcji i wpisu — nie przebudowa sekcji ani skanera (wymóg ticketu). Sama
mechanika cykliczności i wstrzymywania powtórek siedzi w
``app/services/dl_alerts.py``; tutaj są wyłącznie warunki.

Reguła #1 (wyczerpanie zamówienia kosztowego) świadomie NIE jest tutaj — jest
zdarzeniowa, emitowana w chwili, w której budżet spada do zera
(``services/cost_orders.settle_group`` + ścieżka importu). Skaner powtarzałby
ją co tydzień, a ona opisuje stan, który się już nie zmienia.

Tu jest natomiast jej BACKSTOP: gdy w chwili wyczerpania klient nie miał
przypisanego Delivery Leada, emisja szła do pustej listy i alert przepadał bez
śladu. ``reconcile_exhausted_group_budget_alerts`` (dobowo, poza rejestrem
``ALERT_RULES``, bo to nie reguła stanowa z powtórką) dostarcza go po
przypisaniu DL — dla zamówień kosztowych i wspólnej puli MD to jedyny sygnał
o końcu budżetu. Tak samo ``reconcile_mail_new_draft_alerts`` dostarcza
jednorazowy alert o pierwszym drafcie z maila (nowa osoba u klienta), którego
cotygodniowa reguła „bez zamówienia” świadomie nie obejmuje.

Trzy pozostałe są STANOWE: warunek trwa, dopóki ktoś czegoś nie uzupełni, więc
powtarzają się co ``DL_ALERT_REPEAT_DAYS`` dni — każda powtórka jako nowy wiersz
w logu, żeby raport pokazywał, ile tygodni sprawa czekała.

**Panel „Moi klienci" (09.2026).** Reguły datowe (zamówienie okresowe, umowa
ramowa, kontrakt) biegną cyklem T-30 → co 7 dni → T-14 (mail) → T-7 (wysoki
priorytet + mail). MD startuje przy 21 MD, kosztowe przy 10 000 zł, a wysoki
priorytet + mail przychodzi, gdy pozostałość wystarcza na ~7 dni roboczych
przy tempie TEGO zamówienia (``services/order_burn_rate.py``). Każda reguła
stanowa po przebiegu zamyka (``resolved``) sprawy, których warunek ustał —
karta nie wisi w panelu po przedłużeniu zamówienia.

Maile z progów wysyła ``send_pending_alert_emails`` PO commicie reguł.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    ClientOrderGroup,
    ClientOrderGroupMdConsumption,
)
from app.models.contract import Contract, ContractStatus
from app.models.dl_alert import (
    ALERT_CONTRACT_ENDING,
    ALERT_COST_BUDGET_LOW,
    ALERT_DRAFT_CONSULTANT_UNASSIGNED,
    ALERT_FRAMEWORK_CONTRACT_EXPIRING,
    ALERT_MD_BUDGET_LOW,
    ALERT_MISSING_REVENUE_RATE,
    ALERT_ORDER_MISSING_SUCCESSOR,
    ALERT_NEW_CONTRACTOR_DRAFT,
    ALERT_ORDER_MAIL_REVIEW,
    ALERT_PERIODIC_ORDER_ENDING,
    DL_ALERT_PRIORITY_HIGH,
    DL_ALERT_PRIORITY_STANDARD,
)
from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    ClientOrderMdConsumption,
)
from app.models.order_mail import OUTCOME_NEEDS_REVIEW, OrderMailDocument
from app.services.client_identity import client_display_name_expression
from app.services.client_order_lines import consultant_display_name
from app.services.delivery_alert_recipients import (
    DeliveryAlertRecipientScope,
    load_delivery_alert_recipient_scope,
)
from app.services.dl_alerts import (
    MAIL_NEW_DRAFT_ACTION,
    date_cycle_stage,
    dl_user_ids_for_client,
    emit,
    emit_new_contractor_draft,
    event_key_for,
    new_contractor_missing_fields,
    reconcile_exhausted_group_budget_alerts,
    reconcile_mail_new_draft_alerts,
    resolve_stale,
    send_pending_alert_emails,
)
from app.services.order_burn_rate import (
    cost_burn_rate,
    high_priority_threshold,
    md_burn_rate,
)
from app.services.shared_md_orders import uses_shared_md_pool
from app.services import loop_heartbeat

#: Activity szkicu zamówienia założonego po obustronnym podpisie umowy
#: w Generatorze B2B (``b2b_contract_automation._ensure_open_order``).
SIGNED_CONTRACT_DRAFT_ACTION = "auto_drafted_from_signed_contract"

logger = logging.getLogger(__name__)

Rule = Callable[[AsyncSession, DeliveryAlertRecipientScope | None], Awaitable[int]]


def _client_link(client_id: int) -> str:
    return f"/clients/{client_id}?tab=zamowienia"


def _order_link(client_id: int, order_id: int) -> str:
    """Deep link do KONKRETNEGO zamówienia (podświetlenie / okno edycji)."""
    return f"/clients/{client_id}?tab=zamowienia&order={order_id}"


def _group_link(client_id: int, group_id: int) -> str:
    return f"/clients/{client_id}?tab=zamowienia&group={group_id}"


def _live_keys(alert_type: str, entity_key: str, user_ids: list[int]) -> set[str]:
    return {event_key_for(alert_type, entity_key, uid) for uid in user_ids}


def _days_word(days: int) -> str:
    return "dzień" if days == 1 else "dni"


def _person(candidate: Candidate | None, fallback: str = "kontraktora") -> str:
    if candidate is None:
        return fallback
    full = f"{candidate.name or ''} {candidate.lastname or ''}".strip()
    return full or fallback


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
        .where(
            ClientOrder.status == ClientOrderStatus.draft,
            # Szkic z maila ma własny jednorazowy alert, a szkic z podpisu
            # umowy — kartę „Nowy kontraktor" (``rule_new_contractor_draft``).
            # Druga karta o tym samym szkicu byłaby szumem.
            ~select(Activity.id)
            .where(
                Activity.entity_type == "client_order",
                Activity.entity_id == ClientOrder.id,
                Activity.action.in_(
                    (MAIL_NEW_DRAFT_ACTION, SIGNED_CONTRACT_DRAFT_ACTION)
                ),
            )
            .exists(),
        )
    )
    orders = list(result.scalars())
    names = await _client_names(db, {o.client_id for o in orders})
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    created = 0
    live: set[str] = set()
    for order in orders:
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        live |= _live_keys(
            ALERT_DRAFT_CONSULTANT_UNASSIGNED, f"order:{order.id}", user_ids
        )
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
            link=_order_link(order.client_id, order.id),
            payload={"consultant": who, "candidate_name": who},
            order_id=order.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        )
        created += len(alerts)
    await resolve_stale(
        db,
        alert_type=ALERT_DRAFT_CONSULTANT_UNASSIGNED,
        live_event_keys=live,
        entity_prefix="order:",
    )
    await _resolve_mail_new_drafts(db)
    return created


async def _resolve_mail_new_drafts(db: AsyncSession) -> int:
    """Zamknij jednorazowe karty szkicu z maila, gdy szkic przestał być szkicem."""
    still_draft = (
        await db.execute(
            select(ClientOrder.id).where(ClientOrder.status == ClientOrderStatus.draft)
        )
    ).scalars()
    from app.models.dl_alert import DlAlert

    rows = (
        await db.execute(
            select(DlAlert.event_key, DlAlert.order_id).where(
                DlAlert.alert_type == ALERT_DRAFT_CONSULTANT_UNASSIGNED,
                DlAlert.status == "new",
                DlAlert.event_key.startswith(
                    f"{ALERT_DRAFT_CONSULTANT_UNASSIGNED}:mail-draft:", autoescape=True
                ),
            )
        )
    ).all()
    drafts = set(still_draft)
    live = {key for key, order_id in rows if key and order_id in drafts}
    if not rows:
        return 0
    return await resolve_stale(
        db,
        alert_type=ALERT_DRAFT_CONSULTANT_UNASSIGNED,
        live_event_keys=live,
        entity_prefix="mail-draft:",
    )


async def rule_md_budget_low(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Kończące się MD — osobno przy osobie i osobno we wspólnej puli.

    Próg jest GLOBALNY (``DL_ALERT_MD_THRESHOLD``, 21 MD), bez konfiguracji
    per klient — „mało MD" ma znaczyć to samo w każdym raporcie. Z tego samego
    powodu wspólna pula dostaje ten SAM próg bezwzględny, a nie procent budżetu.

    Wysoki priorytet (+ mail) NIE jest progiem stałym: pozostałość porównujemy
    z ~7 dniami roboczymi zużycia przy dotychczasowym tempie tego zamówienia.
    Zamówienie bez raportów dostaje szacunek 1 MD/dzień na osobę.
    """
    threshold = Decimal(str(settings.DL_ALERT_MD_THRESHOLD))
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    live: set[str] = set()
    created = await _md_low_per_consultant(db, threshold, recipient_scope, live)
    created += await _md_low_shared_pool(db, threshold, recipient_scope, live)
    await resolve_stale(db, alert_type=ALERT_MD_BUDGET_LOW, live_event_keys=live)
    return created


async def _reports_by(
    db: AsyncSession, model, key_column, ids: set[int]
) -> dict[int, list[tuple[str, Decimal]]]:
    if not ids:
        return {}
    value = (
        model.invoice_amount
        if model is ClientOrderInvoiceConsumption
        else model.md_reported
    )
    rows = await db.execute(
        select(key_column, model.period_month, value).where(key_column.in_(ids))
    )
    out: dict[int, list[tuple[str, Decimal]]] = defaultdict(list)
    for key, month, amount in rows:
        out[key].append((month, amount))
    return out


def _md_stage(
    remaining: Decimal, high_threshold: Decimal | None
) -> tuple[str | None, str, bool]:
    if high_threshold is not None and remaining <= high_threshold:
        return "high", DL_ALERT_PRIORITY_HIGH, True
    return None, DL_ALERT_PRIORITY_STANDARD, False


def _fmt_md(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.1"))
    text = f"{quantized:f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") or "0"


async def _md_low_per_consultant(
    db: AsyncSession,
    threshold: Decimal,
    recipient_scope: DeliveryAlertRecipientScope,
    live: set[str],
) -> int:
    """Aktywna linia z własnym budżetem MD i pozostałością do progu."""
    result = await db.execute(
        select(ClientOrder)
        .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
        .options(
            selectinload(ClientOrder.order_group),
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
        )
        .where(
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrder.md_remaining.isnot(None),
            ClientOrder.md_remaining <= threshold,
            ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
        )
    )
    orders = list(result.scalars())
    names = await _client_names(db, {o.client_id for o in orders})
    reports = await _reports_by(
        db,
        ClientOrderMdConsumption,
        ClientOrderMdConsumption.order_id,
        {o.id for o in orders},
    )
    today = business_today()
    workdays = int(settings.DL_ALERT_HIGH_PRIORITY_WORKDAYS)
    created = 0
    for order in orders:
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        live |= _live_keys(ALERT_MD_BUDGET_LOW, f"order:{order.id}", user_ids)
        group = order.order_group
        number = group.order_number if group else "—"
        client_name = names.get(order.client_id, "Klient")
        who = consultant_display_name(order)
        rate = md_burn_rate(
            reports.get(order.id, ()),
            order_start=order.start_date or (group.start_date if group else None),
            today=today,
            consultants=1,
        )
        high = high_priority_threshold(rate, workdays)
        stage, priority, email = _md_stage(order.md_remaining, high)
        remaining = _fmt_md(order.md_remaining)
        if stage == "high":
            message = (
                f"Zamówieniu {number} dla {who} zostało {remaining} MD — przy "
                f"dotychczasowym tempie to ok. {workdays} dni roboczych pracy. "
                "Pilnie przygotuj nowe zamówienie lub przedłużenie."
            )
        else:
            message = (
                f"Zamówieniu {number} dla {who} zostało {remaining} MD. "
                "Zorganizuj nowe zamówienie lub przedłużenie."
            )
        alerts = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=user_ids,
            client_id=order.client_id,
            entity_key=f"order:{order.id}",
            title=f"{client_name} — mało MD na zamówieniu {number}",
            message=message,
            link=_order_link(order.client_id, order.id),
            payload={
                "order_number": number,
                "md_remaining": str(order.md_remaining),
                "candidate_name": who if who != "—" else None,
                "burn_rate_estimated": bool(rate and rate.estimated),
            },
            order_group_id=order.order_group_id,
            order_id=order.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
            stage=stage,
            priority=priority,
            email=email,
        )
        created += len(alerts)
    return created


async def _md_low_shared_pool(
    db: AsyncSession,
    threshold: Decimal,
    recipient_scope: DeliveryAlertRecipientScope,
    live: set[str],
) -> int:
    """Wspólna pula MD (Lotte Wedel, Cyfrowy Polsat) do progu.

    Osobne zapytanie, bo budżet mieszka gdzie indziej: przy tych klientach
    linia konsultanta NIE MA ``md_remaining``, więc reguła oparta o linie
    mijała je w całości.

    ``uses_shared_md_pool`` sprawdzamy PONOWNIE w Pythonie, mimo filtra po
    ``is_md_budget_based`` w zapytaniu: sama flaga nie jest miarodajna, bo
    rewizja 0246 ustawiała ją każdemu jawnemu typowi ``md``.
    """
    result = await db.execute(
        select(ClientOrderGroup).where(
            ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
            ClientOrderGroup.is_md_budget_based.is_(True),
            ClientOrderGroup.md_budget_remaining.isnot(None),
            ClientOrderGroup.md_budget_remaining <= threshold,
        )
    )
    groups = [group for group in result.scalars() if uses_shared_md_pool(group)]
    names = await _client_names(db, {group.client_id for group in groups})
    group_ids = {g.id for g in groups}
    reports = await _reports_by(
        db,
        ClientOrderGroupMdConsumption,
        ClientOrderGroupMdConsumption.group_id,
        group_ids,
    )
    consultants = await _active_lines_per_group(db, group_ids)
    today = business_today()
    workdays = int(settings.DL_ALERT_HIGH_PRIORITY_WORKDAYS)
    created = 0
    for group in groups:
        user_ids = await dl_user_ids_for_client(
            db, group.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        live |= _live_keys(ALERT_MD_BUDGET_LOW, f"group:{group.id}", user_ids)
        client_name = names.get(group.client_id, "Klient")
        number = group.order_number or "—"
        rate = md_burn_rate(
            reports.get(group.id, ()),
            order_start=group.start_date,
            today=today,
            consultants=consultants.get(group.id, 0),
        )
        high = high_priority_threshold(rate, workdays)
        stage, priority, email = _md_stage(group.md_budget_remaining, high)
        remaining = _fmt_md(group.md_budget_remaining)
        suffix = (
            f" Przy dotychczasowym tempie to ok. {workdays} dni roboczych pracy — "
            "pilnie zwiększ pulę albo przygotuj nowe zamówienie."
            if stage == "high"
            else " Zwiększ pulę albo zorganizuj nowe zamówienie."
        )
        alerts = await emit(
            db,
            alert_type=ALERT_MD_BUDGET_LOW,
            user_ids=user_ids,
            client_id=group.client_id,
            # Inny prefiks niż `order:` — wspólna pula jest sprawą CAŁEGO
            # zamówienia, nie konkretnej linii.
            entity_key=f"group:{group.id}",
            title=f"{client_name} — mało MD na zamówieniu {number}",
            message=(
                f"We wspólnej puli zamówienia {number} zostało {remaining} MD." + suffix
            ),
            link=_group_link(group.client_id, group.id),
            payload={
                "order_number": number,
                "md_remaining": str(group.md_budget_remaining),
                "shared_pool": True,
                "burn_rate_estimated": bool(rate and rate.estimated),
            },
            order_group_id=group.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
            stage=stage,
            priority=priority,
            email=email,
        )
        created += len(alerts)
    return created


async def _active_lines_per_group(
    db: AsyncSession, group_ids: set[int]
) -> dict[int, int]:
    if not group_ids:
        return {}
    rows = await db.execute(
        select(ClientOrder.order_group_id, func.count(ClientOrder.id))
        .where(
            ClientOrder.order_group_id.in_(group_ids),
            ClientOrder.status == ClientOrderStatus.active,
        )
        .group_by(ClientOrder.order_group_id)
    )
    return {gid: int(count) for gid, count in rows}


async def rule_cost_budget_low(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Kończący się budżet zamówienia KOSZTOWEGO.

    Start przy ``DL_ALERT_COST_BUDGET_THRESHOLD`` (10 000 zł). Wysoki priorytet
    (+ mail), gdy reszta wystarcza na ~7 dni roboczych przy tempie faktur tego
    zamówienia. Bez żadnej faktury nie ma tempa i nie ma szacunku (stawki
    i skład pozycji są zbyt różne) — zostaje przypomnienie standardowe, a na
    koniec jednorazowy alert wyczerpania.

    Treść NIE podaje kwot: panel widzą także role, którym kwot klienta nie
    pokazujemy (hybryda HoR+DL). Próg 10 000 zł to reguła, nie dana klienta.
    """
    threshold = Decimal(str(settings.DL_ALERT_COST_BUDGET_THRESHOLD))
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    result = await db.execute(
        select(ClientOrderGroup).where(
            ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
            ClientOrderGroup.is_cost_based.is_(True),
            ClientOrderGroup.budget_remaining.isnot(None),
            ClientOrderGroup.budget_remaining <= threshold,
            ClientOrderGroup.budget_remaining > 0,
        )
    )
    groups = list(result.scalars())
    names = await _client_names(db, {g.client_id for g in groups})
    group_ids = {g.id for g in groups}
    line_rows = (
        await db.execute(
            select(ClientOrder.id, ClientOrder.order_group_id).where(
                ClientOrder.order_group_id.in_(group_ids)
            )
        )
        if group_ids
        else []
    )
    group_by_line = {line_id: gid for line_id, gid in line_rows}
    invoice_reports = await _reports_by(
        db,
        ClientOrderInvoiceConsumption,
        ClientOrderInvoiceConsumption.order_id,
        set(group_by_line),
    )
    per_group: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for line_id, entries in invoice_reports.items():
        bucket = per_group[group_by_line[line_id]]
        for month, amount in entries:
            bucket[month] = bucket.get(month, Decimal("0")) + Decimal(amount)
    today = business_today()
    workdays = int(settings.DL_ALERT_HIGH_PRIORITY_WORKDAYS)
    live: set[str] = set()
    created = 0
    for group in groups:
        user_ids = await dl_user_ids_for_client(
            db, group.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        live |= _live_keys(ALERT_COST_BUDGET_LOW, f"group:{group.id}", user_ids)
        client_name = names.get(group.client_id, "Klient")
        number = group.order_number or "—"
        rate = cost_burn_rate(
            per_group.get(group.id, {}).items(),
            order_start=group.start_date,
            today=today,
        )
        high = high_priority_threshold(rate, workdays)
        stage, priority, email = _md_stage(group.budget_remaining, high)
        if stage == "high":
            message = (
                f"Budżet zamówienia kosztowego {number} wystarczy na ok. "
                f"{workdays} dni roboczych przy dotychczasowym tempie. Pilnie "
                "przygotuj nowe zamówienie lub zwiększenie kwoty."
            )
        else:
            message = (
                f"W budżecie zamówienia kosztowego {number} zostało mniej niż "
                f"{int(threshold):,} zł.".replace(",", " ")
                + " Zorganizuj nowe zamówienie lub zwiększenie kwoty."
            )
        alerts = await emit(
            db,
            alert_type=ALERT_COST_BUDGET_LOW,
            user_ids=user_ids,
            client_id=group.client_id,
            entity_key=f"group:{group.id}",
            title=f"{client_name} — kończy się budżet zamówienia {number}",
            message=message,
            link=_group_link(group.client_id, group.id),
            payload={"order_number": number},
            order_group_id=group.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
            stage=stage,
            priority=priority,
            email=email,
        )
        created += len(alerts)
    await resolve_stale(db, alert_type=ALERT_COST_BUDGET_LOW, live_event_keys=live)
    return created


async def _emit_date_cycle(
    db: AsyncSession,
    *,
    alert_type: str,
    user_ids: list[int],
    client_id: int,
    entity_key: str,
    end_date: date,
    today: date,
    title: str,
    lead: str,
    standard_action: str,
    urgent_action: str,
    link: str,
    payload: dict,
    live: set[str],
    order_id: int | None = None,
) -> int:
    days_left = (end_date - today).days
    stage, priority, email = date_cycle_stage(days_left)
    live |= _live_keys(alert_type, entity_key, user_ids)
    action = urgent_action if priority == DL_ALERT_PRIORITY_HIGH else standard_action
    alerts = await emit(
        db,
        alert_type=alert_type,
        user_ids=user_ids,
        client_id=client_id,
        entity_key=entity_key,
        title=title,
        message=f"{lead} kończy się {end_date.isoformat()}. {action}",
        link=link,
        payload={**payload, "end_date": end_date.isoformat()},
        order_id=order_id,
        repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        stage=stage,
        priority=priority,
        email=email,
    )
    return len(alerts)


def _ending_window(today: date) -> tuple[date, date]:
    return today, today + timedelta(days=int(settings.DL_ALERT_ENDING_WINDOW_DAYS))


async def rule_periodic_order_ending(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Kończące się zamówienie OKRESOWE (samodzielne, poza grupami MD/kosztowymi).

    Klucz encji niesie datę końca: przedłużenie zamówienia (nowa data) to nowy
    cykl, a karta starej daty zamyka się przez ``resolve_stale``. Linie grup
    MD/kosztowych mają własne reguły budżetowe.
    """
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    today = business_today()
    start, stop = _ending_window(today)
    result = await db.execute(
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract).selectinload(Contract.candidate))
        .where(
            ClientOrder.order_group_id.is_(None),
            ClientOrder.status.in_(
                (ClientOrderStatus.active, ClientOrderStatus.paused)
            ),
            ClientOrder.end_date.isnot(None),
            ClientOrder.end_date >= start,
            ClientOrder.end_date <= stop,
        )
    )
    orders = list(result.scalars())
    names = await _client_names(db, {o.client_id for o in orders})
    live: set[str] = set()
    created = 0
    for order in orders:
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        who = consultant_display_name(order)
        client_name = names.get(order.client_id, "Klient")
        created += await _emit_date_cycle(
            db,
            alert_type=ALERT_PERIODIC_ORDER_ENDING,
            user_ids=user_ids,
            client_id=order.client_id,
            entity_key=f"order:{order.id}:end:{order.end_date.isoformat()}",
            end_date=order.end_date,
            today=today,
            title=f"{client_name} — zamówienie dla {who} kończy się",
            lead=f"Zamówienie dla {who}",
            standard_action=(
                "Skontaktuj się z klientem w sprawie przedłużenia i przygotuj "
                "nowe zamówienie."
            ),
            urgent_action="Przygotuj kolejne zamówienie lub przedłużenie.",
            link=_order_link(order.client_id, order.id),
            payload={
                "candidate_name": who if who != "—" else None,
                "contract_id": order.contract_id,
            },
            live=live,
            order_id=order.id,
        )
    await resolve_stale(
        db, alert_type=ALERT_PERIODIC_ORDER_ENDING, live_event_keys=live
    )
    return created


async def rule_framework_contract_expiring(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Wygasająca umowa ramowa klienta — ten sam cykl co zamówienie okresowe."""
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    today = business_today()
    start, stop = _ending_window(today)
    result = await db.execute(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.status == FrameworkContractStatus.active,
            ClientFrameworkContract.expiry_date.isnot(None),
            ClientFrameworkContract.expiry_date >= start,
            ClientFrameworkContract.expiry_date <= stop,
        )
    )
    contracts = list(result.scalars())
    names = await _client_names(db, {fc.client_id for fc in contracts})
    live: set[str] = set()
    created = 0
    for fc in contracts:
        user_ids = await dl_user_ids_for_client(db, fc.client_id, scope=recipient_scope)
        if not user_ids:
            continue
        client_name = names.get(fc.client_id, "Klient")
        created += await _emit_date_cycle(
            db,
            alert_type=ALERT_FRAMEWORK_CONTRACT_EXPIRING,
            user_ids=user_ids,
            client_id=fc.client_id,
            entity_key=f"framework:{fc.id}:end:{fc.expiry_date.isoformat()}",
            end_date=fc.expiry_date,
            today=today,
            title=f"{client_name} — umowa ramowa wygasa",
            lead=f"Umowa ramowa „{fc.name}”",
            standard_action="Skontaktuj się z klientem w sprawie przedłużenia umowy.",
            urgent_action="Pilnie ustal z klientem przedłużenie lub nową umowę.",
            link=(f"/clients/{fc.client_id}?tab=umowy-ramowe&framework={fc.id}"),
            payload={"framework_contract_id": fc.id},
            live=live,
        )
    await resolve_stale(
        db, alert_type=ALERT_FRAMEWORK_CONTRACT_EXPIRING, live_event_keys=live
    )
    return created


async def rule_contract_ending(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Kończący się kontrakt kontraktora (data końca umowy w oknie 30 dni).

    Umowa B2B ma datę końca WYŁĄCZNIE po ręcznym zakończeniu (``/terminate``),
    więc karta dotyczy realnie kończącej się współpracy, a nie daty
    przepisanej z zamówienia.
    """
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    today = business_today()
    start, stop = _ending_window(today)
    result = await db.execute(
        select(Contract)
        .options(selectinload(Contract.candidate))
        .where(
            Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
            Contract.end_date.isnot(None),
            Contract.end_date >= start,
            Contract.end_date <= stop,
        )
    )
    contracts = list(result.scalars())
    names = await _client_names(db, {c.client_id for c in contracts if c.client_id})
    # Kontrakt, którego zamówienie okresowe kończy się TEGO SAMEGO dnia, ma już
    # kartę zamówienia — druga karta (i drugi mail) o tej samej osobie i dacie
    # byłaby szumem.
    covered = set()
    if contracts:
        covered = {
            (contract_id, end)
            for contract_id, end in await db.execute(
                select(ClientOrder.contract_id, ClientOrder.end_date).where(
                    ClientOrder.contract_id.in_([c.id for c in contracts]),
                    ClientOrder.order_group_id.is_(None),
                    ClientOrder.status.in_(
                        (ClientOrderStatus.active, ClientOrderStatus.paused)
                    ),
                )
            )
        }
    live: set[str] = set()
    created = 0
    for contract in contracts:
        if contract.client_id is None or (contract.id, contract.end_date) in covered:
            continue
        user_ids = await dl_user_ids_for_client(
            db, contract.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        who = _person(contract.candidate)
        client_name = names.get(contract.client_id, "Klient")
        created += await _emit_date_cycle(
            db,
            alert_type=ALERT_CONTRACT_ENDING,
            user_ids=user_ids,
            client_id=contract.client_id,
            entity_key=f"contract:{contract.id}:end:{contract.end_date.isoformat()}",
            end_date=contract.end_date,
            today=today,
            title=f"{client_name} — kontrakt {who} kończy się",
            lead=f"Kontrakt {who}",
            standard_action=(
                "Sprawdź, czy współpraca ma trwać dalej, i uzgodnij to z klientem."
            ),
            urgent_action="Pilnie potwierdź zakończenie albo przedłużenie współpracy.",
            link=f"/contracts/{contract.id}",
            payload={
                "candidate_name": who if contract.candidate else None,
                "contract_id": contract.id,
            },
            live=live,
        )
    await resolve_stale(db, alert_type=ALERT_CONTRACT_ENDING, live_event_keys=live)
    return created


async def rule_new_contractor_draft(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Szkic zamówienia z obustronnie podpisanej umowy, któremu czegoś brakuje.

    Pierwszą kartę wystawia ścieżka podpisu w chwili zapisu; skaner powtarza
    ją co 7 dni i zamyka, gdy szkic przestał być szkicem albo braki zniknęły.
    """
    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    result = await db.execute(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.job),
        )
        .where(
            ClientOrder.status == ClientOrderStatus.draft,
            select(Activity.id)
            .where(
                Activity.entity_type == "client_order",
                Activity.entity_id == ClientOrder.id,
                Activity.action == SIGNED_CONTRACT_DRAFT_ACTION,
            )
            .exists(),
        )
    )
    live: set[str] = set()
    created = 0
    for order in result.scalars():
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        candidate = order.contract.candidate if order.contract else None
        name = _person(candidate, "Kontraktor")
        job_title = order.job.title if order.job else None
        if not new_contractor_missing_fields(
            order, candidate_name=name, job_title=job_title
        ):
            continue
        live |= _live_keys(ALERT_NEW_CONTRACTOR_DRAFT, f"order:{order.id}", user_ids)
        created += len(
            await emit_new_contractor_draft(
                db,
                order=order,
                candidate_name=name,
                job_title=job_title,
                user_ids=user_ids,
            )
        )
    await resolve_stale(db, alert_type=ALERT_NEW_CONTRACTOR_DRAFT, live_event_keys=live)
    return created


async def rule_order_mail_review(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Zamówienie z maila utknęło w weryfikacji — powtórka co 7 dni.

    Pierwszą kartę wystawia ``order_mail_ingest.notify_review`` w chwili
    odczytu. Skaner ponawia ją dopóki dokument jest w kolejce i zamyka, gdy
    ktoś go zastosował albo odrzucił.
    """
    from app.services.order_mail_ingest import notify_review

    rows = (
        await db.execute(
            select(OrderMailDocument).where(
                OrderMailDocument.outcome == OUTCOME_NEEDS_REVIEW,
                OrderMailDocument.client_id.isnot(None),
            )
        )
    ).scalars()
    live: set[str] = set()
    created = 0
    for doc in rows:
        created += await notify_review(
            db, doc, recipient_scope=recipient_scope, live_event_keys=live
        )
    await resolve_stale(db, alert_type=ALERT_ORDER_MAIL_REVIEW, live_event_keys=live)
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
    live: set[str] = set()
    for order in orders:
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
        if not user_ids:
            continue
        live |= _live_keys(ALERT_MISSING_REVENUE_RATE, f"order:{order.id}", user_ids)
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
            link=_order_link(order.client_id, order.id),
            payload={"order_number": number, "consultant": who, "candidate_name": who},
            order_group_id=order.order_group_id,
            order_id=order.id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        )
        created += len(alerts)
    await resolve_stale(db, alert_type=ALERT_MISSING_REVENUE_RATE, live_event_keys=live)
    return created


async def rule_order_missing_successor(
    db: AsyncSession, recipient_scope: DeliveryAlertRecipientScope | None = None
) -> int:
    """Brak kolejnego zamówienia (Finanse → Braki): powtórka co N dni.

    Wykrycie braku robi pętla ``order_gaps``; tu tylko przypominamy o brakach,
    które wciąż są otwarte.
    """
    from app.services.order_gaps import remind_open_gaps

    return await remind_open_gaps(db, recipient_scope)


#: Rejestr reguł. Dołożenie typu alertu = dopisanie funkcji i wpisu.
ALERT_RULES: dict[str, Rule] = {
    ALERT_DRAFT_CONSULTANT_UNASSIGNED: rule_draft_consultant_unassigned,
    ALERT_MD_BUDGET_LOW: rule_md_budget_low,
    ALERT_MISSING_REVENUE_RATE: rule_missing_revenue_rate,
    ALERT_ORDER_MISSING_SUCCESSOR: rule_order_missing_successor,
    ALERT_PERIODIC_ORDER_ENDING: rule_periodic_order_ending,
    ALERT_FRAMEWORK_CONTRACT_EXPIRING: rule_framework_contract_expiring,
    ALERT_CONTRACT_ENDING: rule_contract_ending,
    ALERT_COST_BUDGET_LOW: rule_cost_budget_low,
    ALERT_NEW_CONTRACTOR_DRAFT: rule_new_contractor_draft,
    ALERT_ORDER_MAIL_REVIEW: rule_order_mail_review,
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
    # Backstop dla JEDNORAZOWEGO alertu wyczerpania budżetu: dostarcza go, gdy
    # w chwili wyczerpania klient nie miał przypisanego DL (emisja w próżnię).
    # Osobno od ALERT_RULES — to nie reguła stanowa z powtórką co N dni.
    try:
        async with db.begin_nested():
            created[
                "exhausted_budget_backstop"
            ] = await reconcile_exhausted_group_budget_alerts(db)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("dl_alerts exhausted-budget backstop failed")
        created["exhausted_budget_backstop"] = 0
    # Ten sam backstop dla JEDNORAZOWEGO alertu o pierwszym drafcie z maila:
    # klient bez DL w chwili zapisu draftu dostaje go po przypisaniu DL.
    try:
        async with db.begin_nested():
            created["mail_new_draft_backstop"] = await reconcile_mail_new_draft_alerts(
                db, recipient_scope
            )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("dl_alerts mail-new-draft backstop failed")
        created["mail_new_draft_backstop"] = 0
    await db.commit()
    # Maile PO commicie reguł: claim każdego wiersza commituje osobno, więc
    # wysyłka nie może dzielić transakcji z emisją (padnięty mail cofałby karty).
    try:
        created["emails_sent"] = await send_pending_alert_emails(db)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("dl_alerts email dispatch failed")
        await db.rollback()
        created["emails_sent"] = 0
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
    # MON-04: tick na początku iteracji; cisza dłuższa niż próg = „stalled”.
    beat = loop_heartbeat.register("dl_alerts", max_silence_seconds=interval + 2 * 3600)
    while True:
        beat.tick()
        try:
            summary = await run_once()
            if summary:
                logger.info("dl_alerts scan created %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("dl_alerts_loop iteration failed")
        await asyncio.sleep(interval)
