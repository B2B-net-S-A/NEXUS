"""Braki: zamówienie zakończone, a osoba nie ma u klienta następnego.

Reguła (ticket Finansów, decyzje Artura 14.09):

* wpis powstaje DZIEŃ PO dacie końca zamówienia (``detected_on = koniec + 1``),
  gdy ta sama osoba nie ma u tego klienta zamówienia trwającego po tej dacie
  — aktywnego, przyszłego ani szkicu (``order_facts.successor_of``);
* następca dodany do końca dnia wykrycia jest NA CZAS (decyzja 15.09.2026) —
  taki wpis nie powstaje, a uzupełniony tego samego dnia nie trafia do raportu;
* świadomy koniec nie jest brakiem: wypowiedziana umowa, zamiana kontraktora,
  decyzja offboardingu MD, „usuń z zamówienia" / „zostaw jako historię"
  (``order_facts.load_ending_intents``);
* wpis NIGDY nie znika. Uzupełnienie po fakcie zmienia status na
  ``filled_late`` z numerem i datą uzupełnienia;
* następca dodany PO dniu wykrycia, zanim detektor zdążył przebiec (np. deploy
  w środku miesiąca), też jest spóźnieniem — wpis powstaje od razu jako
  ``filled_late``. Inaczej to, czy spóźnienie DL w ogóle trafi do raportu,
  zależałoby od godziny przebiegu pętli.

Delivery Lead dostaje alert w sekcji alertów (powtórka co
``DL_ALERT_REPEAT_DAYS``) i powiadomienie w dzwonku; uzupełnienie oznacza
alerty jako obsłużone.

Historia śledzona od ``ORDER_GAP_TRACKING_START`` — bez tej granicy pierwszy
bieg zamieniłby w „braki" lata normalnych odejść sprzed tej funkcji.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, func, not_, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract
from app.models.dl_alert import (
    ALERT_ORDER_MISSING_SUCCESSOR,
    DL_ALERT_STATUS_HANDLED,
    DL_ALERT_STATUS_NEW,
    DlAlert,
)
from app.models.notification import NotificationType
from app.models.order_gap import GAP_STATUS_FILLED_LATE, GAP_STATUS_OPEN, OrderGap
from app.services import dl_alerts
from app.services.delivery_alert_recipients import DeliveryAlertRecipientScope
from app.services.order_facts import (
    OrderFact,
    effective_end_expr,
    load_ending_intents,
    load_facts,
    load_siblings,
    local_day_start,
    siblings_of,
    successor_of,
)

logger = logging.getLogger(__name__)

GAP_ENTITY_TYPE = "order_gap"


@dataclass(frozen=True)
class GapRunResult:
    detected: int
    detected_late: int
    resolved: int


def tracking_start() -> date:
    return settings.ORDER_GAP_TRACKING_START


def _link(client_id: int, order_id: int | None = None) -> str:
    # `?order=` — panel „Moi klienci" prowadzi do KONKRETNEGO zamówienia.
    base = f"/clients/{client_id}?tab=zamowienia"
    return f"{base}&order={order_id}" if order_id else base


def _message(fact: OrderFact) -> str:
    return (
        f"Zamówienie {fact.number} ({fact.consultant_name}) zakończyło się "
        f"{fact.end.strftime('%d.%m.%Y') if fact.end else '—'}, a osoba nie ma "
        "u klienta kolejnego zamówienia. Dodaj zamówienie albo zakończ "
        "współpracę — dział finansowy widzi ten brak w rozliczeniach."
    )


async def _notify(
    db: AsyncSession, gap: OrderGap, fact: OrderFact, *, bell: bool = True
) -> None:
    """Alert DL (z powtórką) + jedno powiadomienie w dzwonku na brak."""

    from app.tasks.dl_portal_expiry_scanner import _insert_notification

    user_ids = await dl_alerts.dl_user_ids_for_client(db, gap.client_id)
    if not user_ids:
        return
    title = f"{fact.client_name} — brak kolejnego zamówienia"
    message = _message(fact)
    await dl_alerts.emit(
        db,
        alert_type=ALERT_ORDER_MISSING_SUCCESSOR,
        user_ids=user_ids,
        client_id=gap.client_id,
        entity_key=f"gap:{gap.id}",
        title=title,
        message=message,
        link=_link(gap.client_id, gap.order_id),
        payload={
            "order_gap_id": gap.id,
            "order_number": fact.number,
            "consultant_name": fact.consultant_name,
            "ended_on": gap.ended_on.isoformat(),
        },
        order_group_id=gap.order_group_id,
        order_id=gap.order_id,
        repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
    )
    if not bell:
        return
    # Wołane wyłącznie dla świeżo wstawionego braku, więc jedno powiadomienie
    # na brak na osobę; dobowy indeks dedupu jest tu tylko bezpiecznikiem.
    for user_id in user_ids:
        await _insert_notification(
            db,
            user_id=user_id,
            title=title[:255],
            message=message,
            link=_link(gap.client_id, gap.order_id),
            notification_type=NotificationType.order_missing_successor,
            is_read=False,
            related_entity_type=GAP_ENTITY_TYPE,
            related_entity_id=gap.id,
        )


def detection_window_start(today: date) -> date:
    """Najstarsza data końca, dla której jeszcze wykrywamy brak.

    Granica z ``ORDER_GAP_TRACKING_START`` odcina historię sprzed funkcji,
    a okno ``ORDER_GAP_LOOKBACK_DAYS`` pilnuje, żeby zamknięty już miesiąc nie
    dostawał po czasie nowych braków — np. gdy szkic następcy, który był na
    czas, zostanie po tygodniach usunięty.
    """
    return max(
        tracking_start(), today - timedelta(days=settings.ORDER_GAP_LOOKBACK_DAYS)
    )


async def _ended_candidates(db: AsyncSession, today: date) -> list[OrderFact]:
    end = effective_end_expr()
    already = select(OrderGap.order_id)
    still_billing_md = and_(
        ClientOrder.status == ClientOrderStatus.active,
        ClientOrder.md_total.is_not(None),
        func.coalesce(ClientOrder.md_remaining, 0) > 0,
    )
    return await load_facts(
        db,
        ClientOrder.status.notin_(
            (ClientOrderStatus.draft, ClientOrderStatus.cancelled)
        ),
        end.is_not(None),
        end < today,
        end >= detection_window_start(today),
        ClientOrder.id.notin_(already),
        not_(still_billing_md),
    )


async def detect_order_gaps(
    db: AsyncSession, *, today: Optional[date] = None, notify: bool = True
) -> tuple[int, int]:
    """Zapisz nowe braki. Zwraca (otwarte, od razu uzupełnione z opóźnieniem).

    Każdy brak idzie w osobnym savepoincie: awaria powiadomienia dla jednego
    klienta nie może cofnąć braków zapisanych w tym przebiegu — inaczej ten sam
    błąd codziennie zatrzymywałby wykrywanie w całości.
    """

    day = today or business_today()
    facts = await _ended_candidates(db, day)
    if not facts:
        return 0, 0
    intents = await load_ending_intents(db, facts)
    siblings = await load_siblings(db, facts)

    opened = late = 0
    for fact in facts:
        if fact.order_id in intents or fact.end is None:
            continue
        detected_on = fact.end + timedelta(days=1)
        successor = successor_of(fact, siblings_of(fact, siblings))
        # Następca dodany do końca dnia wykrycia jest na czas (decyzja
        # 15.09.2026, UAT B69): „0 dni po terminie” nie jest opóźnieniem.
        if successor is not None and successor.created_at < local_day_start(
            detected_on + timedelta(days=1)
        ):
            continue  # następca był na czas — to nie jest brak
        values = {
            "order_id": fact.order_id,
            "order_group_id": fact.order_group_id,
            "contract_id": fact.contract_id,
            "client_id": fact.client_id,
            "order_number": fact.number[:255],
            "ended_on": fact.end,
            "detected_on": detected_on,
        }
        if successor is not None:
            values.update(
                status=GAP_STATUS_FILLED_LATE,
                resolved_order_id=successor.order_id,
                resolved_order_number=successor.number[:255],
                resolved_at=successor.created_at,
            )
        else:
            values["status"] = GAP_STATUS_OPEN
        try:
            async with db.begin_nested():
                gap_id = await db.scalar(
                    pg_insert(OrderGap)
                    .values(**values)
                    .on_conflict_do_nothing(constraint="uq_order_gaps_order_id")
                    .returning(OrderGap.id)
                )
                if gap_id is None:
                    continue
                if successor is None and notify:
                    gap = await db.get(OrderGap, gap_id)
                    if gap is not None:
                        # Dzwonek tylko dla świeżych braków: pierwszy przebieg
                        # po wdrożeniu nie zasypie DL powiadomieniami o
                        # tygodniach historii (alert w sekcji DL i tak powstaje).
                        await _notify(
                            db, gap, fact, bell=detected_on >= day - timedelta(days=2)
                        )
        except Exception:  # noqa: BLE001
            logger.exception("order gap detection failed for order %s", fact.order_id)
            continue
        if successor is not None:
            late += 1
        else:
            opened += 1
    return opened, late


async def _scoped_open_gaps(
    db: AsyncSession, contract_ids: Optional[set[int]]
) -> list[OrderGap]:
    query = select(OrderGap).where(OrderGap.status == GAP_STATUS_OPEN)
    if contract_ids is not None:
        # Brak tej samej współpracy mógł powstać na innym kontrakcie tej osoby
        # u tego klienta — zawężamy w SQL, zamiast ładować wszystkie braki.
        touched = (
            select(Contract.candidate_id, Contract.client_id)
            .where(
                Contract.id.in_(sorted(contract_ids)),
                Contract.candidate_id.is_not(None),
            )
            .subquery()
        )
        gap_contract = aliased(Contract)
        query = query.join(gap_contract, gap_contract.id == OrderGap.contract_id).where(
            or_(
                OrderGap.contract_id.in_(sorted(contract_ids)),
                tuple_(gap_contract.candidate_id, OrderGap.client_id).in_(
                    select(touched.c.candidate_id, touched.c.client_id)
                ),
            )
        )
    return list((await db.scalars(query)).all())


async def resolve_order_gaps(
    db: AsyncSession,
    *,
    contract_ids: Optional[Iterable[int]] = None,
    actor_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> int:
    """Oznacz braki, dla których pojawiło się zamówienie, jako uzupełnione.

    Wpis zostaje na liście (``filled_late``). Następca może być innym
    zamówieniem tej osoby u klienta albo tym samym zamówieniem, któremu DL
    przesunął datę końca po fakcie.
    """

    scoped = set(contract_ids) if contract_ids is not None else None
    if scoped is not None and not scoped:
        return 0
    gaps = await _scoped_open_gaps(db, scoped)
    if not gaps:
        return 0
    gap_facts = await load_facts(db, ClientOrder.id.in_([gap.order_id for gap in gaps]))
    by_order = {fact.order_id: fact for fact in gap_facts}
    siblings = await load_siblings(db, by_order.values())
    moment = now or datetime.now(timezone.utc)

    resolved = 0
    for gap in gaps:
        fact = by_order.get(gap.order_id)
        if fact is None:
            continue
        pinned = replace(fact, end=gap.ended_on)
        successor = successor_of(
            pinned, siblings_of(fact, siblings) or [fact], include_self=True
        )
        if successor is None:
            continue
        gap.status = GAP_STATUS_FILLED_LATE
        gap.resolved_order_id = successor.order_id
        gap.resolved_order_number = successor.number[:255]
        gap.resolved_at = moment
        await db.execute(
            update(DlAlert)
            .where(
                DlAlert.alert_type == ALERT_ORDER_MISSING_SUCCESSOR,
                DlAlert.order_id == gap.order_id,
                DlAlert.status == DL_ALERT_STATUS_NEW,
            )
            .values(
                status=DL_ALERT_STATUS_HANDLED,
                handled_at=moment,
                handled_by_user_id=actor_id,
            )
            .execution_options(synchronize_session=False)
        )
        resolved += 1
    if resolved:
        await db.flush()
    return resolved


async def remind_open_gaps(
    db: AsyncSession, scope: Optional[DeliveryAlertRecipientScope] = None
) -> int:
    """Powtórka alertu DL dla otwartych braków (skaner alertów DL).

    Działa też jako backstop: brak wykryty, gdy klient nie miał DL, dostaje
    alert po przypisaniu DL (``emit`` jest idempotentny w oknie powtórki).
    """

    if not settings.ORDER_GAPS_ENABLED:
        return 0

    gaps = list(
        (
            await db.scalars(select(OrderGap).where(OrderGap.status == GAP_STATUS_OPEN))
        ).all()
    )
    if not gaps:
        return 0
    facts = {
        fact.order_id: fact
        for fact in await load_facts(
            db, ClientOrder.id.in_([gap.order_id for gap in gaps])
        )
    }
    created = 0
    for gap in gaps:
        fact = facts.get(gap.order_id)
        if fact is None:
            continue
        user_ids = await dl_alerts.dl_user_ids_for_client(
            db, gap.client_id, scope=scope
        )
        rows = await dl_alerts.emit(
            db,
            alert_type=ALERT_ORDER_MISSING_SUCCESSOR,
            user_ids=user_ids,
            client_id=gap.client_id,
            entity_key=f"gap:{gap.id}",
            title=f"{fact.client_name} — brak kolejnego zamówienia",
            message=_message(fact),
            link=_link(gap.client_id, gap.order_id),
            payload={
                "order_gap_id": gap.id,
                "order_number": fact.number,
                "consultant_name": fact.consultant_name,
                "ended_on": gap.ended_on.isoformat(),
            },
            order_group_id=gap.order_group_id,
            order_id=gap.order_id,
            repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        )
        created += len(rows)
    return created


async def run_order_gaps(
    db: AsyncSession, *, today: Optional[date] = None
) -> GapRunResult:
    opened, late = await detect_order_gaps(db, today=today)
    resolved = await resolve_order_gaps(db)
    return GapRunResult(detected=opened, detected_late=late, resolved=resolved)


async def refresh_order_gaps_safely(
    db: AsyncSession,
    *,
    contract_ids: Optional[Sequence[int]] = None,
    detect: bool = False,
    actor_id: Optional[int] = None,
) -> None:
    """Braki odświeżane przy okazji innego zapisu/odczytu — nigdy go nie wywracają."""

    if not settings.ORDER_GAPS_ENABLED:
        return
    try:
        async with db.begin_nested():
            if detect:
                await detect_order_gaps(db)
            await resolve_order_gaps(db, contract_ids=contract_ids, actor_id=actor_id)
    except Exception:  # noqa: BLE001
        logger.exception("order gaps refresh failed")
