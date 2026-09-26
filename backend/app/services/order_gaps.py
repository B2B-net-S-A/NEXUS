"""Braki: zamówienie zakończone, a osoba nie ma u klienta następnego.

Reguła (ticket Finansów, decyzje Artura 14.09):

* wpis powstaje DZIEŃ PO dacie końca zamówienia (``detected_on = koniec + 1``),
  gdy ta sama osoba nie ma u tego klienta zamówienia trwającego po tej dacie
  — aktywnego, przyszłego ani szkicu (``order_facts.successor_of``);
* następca dodany do końca dnia wykrycia jest NA CZAS (decyzja 15.09.2026) —
  taki wpis nie powstaje, a uzupełniony tego samego dnia nie trafia do raportu;
* świadomy koniec nie jest brakiem: wypowiedziana umowa, zamiana kontraktora,
  decyzja offboardingu MD, „usuń z zamówienia" / „zostaw jako historię"
  (``order_facts.load_ending_intents``). Świadomy koniec zapisany PO wykryciu
  (DL wypowiada umowę dopiero, gdy zobaczy brak) nie kasuje wpisu, ale zdejmuje
  go z raportu Finansów i z przypomnień DL (``gap_orders_with_ending_intent``)
  — osoba stoi wtedy w Zejściach, a nie w Brakach;
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
    participation_end_expr,
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
    # Koniec udziału (``participation_end_expr``): linia MD zakończona
    # wyczerpaniem budżetu nie ma własnej daty, a grupa bywa bez daty końca —
    # bez tego taka osoba nigdy nie trafiała do Braków (runda 6 audytu).
    end = participation_end_expr()
    already = select(OrderGap.order_id)
    # Lustro `OrderFact.works_until_md_exhausted`: tylko linia zamówienia
    # MD/kosztowego pracuje po dacie końca (M10, audyt 25.09.2026).
    still_billing_md = and_(
        ClientOrder.status == ClientOrderStatus.active,
        ClientOrder.order_group_id.is_not(None),
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


async def gap_orders_with_ending_intent(
    db: AsyncSession, order_ids: Iterable[Optional[int]]
) -> set[int]:
    """Zamówienia braków, których koniec jest DZIŚ świadomą decyzją.

    Ta sama funkcja (``load_ending_intents``) stawia wiersz w Zejściach, więc
    osoba nie może stać jednocześnie tam i w Brakach. Wpis braku zostaje
    w bazie (nigdy nie znika) — reguła działa przy odczycie.
    """

    ids = sorted({order_id for order_id in order_ids if order_id is not None})
    if not ids:
        return set()
    facts = await load_facts(db, ClientOrder.id.in_(ids))
    return set(await load_ending_intents(db, facts))


async def _scoped_open_gaps(
    db: AsyncSession, contract_ids: Optional[set[int]], *, status: str = GAP_STATUS_OPEN
) -> list[OrderGap]:
    query = select(OrderGap).where(OrderGap.status == status)
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


async def close_gap_alerts(
    db: AsyncSession,
    order_id: int,
    moment: datetime,
    *,
    actor_id: Optional[int] = None,
) -> None:
    """Oznacz karty DL braku zamówienia ``order_id`` jako obsłużone."""
    await _close_gap_alerts(db, order_id, moment, actor_id=actor_id)


async def close_gaps_of_deleted_orders(
    db: AsyncSession, order_ids: Iterable[int], *, actor_id: Optional[int] = None
) -> None:
    """Usunięte zamówienie nie zostawia otwartej karty DL (FIN-CHG-5).

    Wołane PRZED ``db.delete(order)``: karta DL ma ``order_id`` z
    ``ON DELETE SET NULL``, więc po usunięciu nie da się jej już znaleźć po
    zamówieniu. Wiersz braku zostaje w bazie (nigdy nie znika), ale raport
    Finansów i przypomnienia pomijają braki bez zamówienia.
    """
    ids = sorted({order_id for order_id in order_ids if order_id is not None})
    if not ids or not settings.ORDER_GAPS_ENABLED:
        return
    moment = datetime.now(timezone.utc)
    for order_id in ids:
        await _close_gap_alerts(db, order_id, moment, actor_id=actor_id)
    # Usuwane zamówienie bywa NASTĘPCĄ, który uzupełnił czyjś brak — ten brak
    # wraca, jeśli osoba nie ma innego następcy (runda 6 audytu). Liczone
    # teraz, bo zamówienie jeszcze istnieje: po ``db.delete`` nikt już nie
    # wiąże braku z usuniętym numerem. Savepoint: awaria alertu nie może
    # wywrócić samego usunięcia.
    try:
        async with db.begin_nested():
            await reopen_orphaned_gaps(db, excluded_order_ids=ids)
    except Exception:  # noqa: BLE001
        logger.exception("reopening gaps of deleted orders failed")


async def _close_gap_alerts(
    db: AsyncSession,
    order_id: int,
    moment: datetime,
    *,
    actor_id: Optional[int] = None,
) -> None:
    await db.execute(
        update(DlAlert)
        .where(
            DlAlert.alert_type == ALERT_ORDER_MISSING_SUCCESSOR,
            DlAlert.order_id == order_id,
            DlAlert.status == DL_ALERT_STATUS_NEW,
        )
        .values(
            status=DL_ALERT_STATUS_HANDLED,
            handled_at=moment,
            handled_by_user_id=actor_id,
        )
        .execution_options(synchronize_session=False)
    )


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
        # Moment uzupełnienia to chwila ZAŁOŻENIA następcy, nie przebiegu, który
        # go zauważył — ścieżka bez odświeżenia braków (podpis B2B, projekt
        # z rejestru) przesuwała go na noc i zamówienie na czas wyglądało na
        # spóźnione (audyt 22.09, FIN-CHG-2). To samo zamówienie przedłużone
        # po fakcie ma stary ``created_at`` — tam liczy się chwila przebiegu.
        gap.resolved_at = (
            min(moment, successor.created_at)
            if successor.order_id != gap.order_id and successor.created_at
            else moment
        )
        await _close_gap_alerts(db, gap.order_id, moment, actor_id=actor_id)
        resolved += 1
    if resolved:
        await db.flush()
    return resolved


async def reopen_orphaned_gaps(
    db: AsyncSession,
    *,
    contract_ids: Optional[Iterable[int]] = None,
    excluded_order_ids: Iterable[int] = (),
    notify: bool = True,
    bell: bool = True,
) -> int:
    """Brak ``filled_late``, którego następca zniknął, wraca jako ``open``.

    Runda 6 audytu: odświeżanie widziało wyłącznie braki otwarte, a detektor
    pomija zamówienia, które mają już wiersz braku — więc brak uzupełniony
    zamówieniem, które potem USUNIĘTO albo ANULOWANO, zostawał „uzupełniony”
    na zawsze: osoba bez zamówienia i bez alertu DL. Wraca tylko wtedy, gdy
    następca zniknął/anulowano go i osoba nie ma INNEGO następcy (ta sama
    reguła co przy uzupełnianiu, ``successor_of``); gdy inny jest — brak
    zostaje uzupełniony, tylko wskazuje tego innego. Świadomy koniec
    współpracy zapisany po drodze (``load_ending_intents``) braku nie
    przywraca — osoba stoi wtedy w Zejściach.

    ``excluded_order_ids`` = zamówienia usuwane w tej transakcji (jeszcze
    widoczne w bazie). Wiersz braku nie znika i nie zmienia daty wykrycia;
    kasujemy tylko dane uzupełnienia, bo uzupełnienia nie ma. ``bell=False``
    (dobowy przebieg) zostawia samą kartę DL — pierwszy przebieg po wdrożeniu
    nie dzwoni o historycznych przypadkach.
    """

    excluded = {order_id for order_id in excluded_order_ids if order_id is not None}
    if excluded:
        # Usuwanie: wyłącznie braki uzupełnione właśnie tymi zamówieniami.
        gaps = list(
            (
                await db.scalars(
                    select(OrderGap).where(
                        OrderGap.status == GAP_STATUS_FILLED_LATE,
                        OrderGap.resolved_order_id.in_(sorted(excluded)),
                    )
                )
            ).all()
        )
    else:
        scoped = set(contract_ids) if contract_ids is not None else None
        if scoped is not None and not scoped:
            return 0
        gaps = await _scoped_open_gaps(db, scoped, status=GAP_STATUS_FILLED_LATE)
    gaps = [gap for gap in gaps if gap.resolved_order_id is not None]
    if not gaps:
        return 0

    resolving_ids = sorted({gap.resolved_order_id for gap in gaps})
    live_resolving = {
        order_id
        for order_id, status in (
            await db.execute(
                select(ClientOrder.id, ClientOrder.status).where(
                    ClientOrder.id.in_(resolving_ids)
                )
            )
        ).all()
        if order_id not in excluded and status != ClientOrderStatus.cancelled
    }
    orphaned = [gap for gap in gaps if gap.resolved_order_id not in live_resolving]
    if not orphaned:
        return 0

    gap_facts = await load_facts(
        db, ClientOrder.id.in_(sorted({gap.order_id for gap in orphaned}))
    )
    by_order = {
        fact.order_id: fact for fact in gap_facts if fact.order_id not in excluded
    }
    intents = await load_ending_intents(db, list(by_order.values()))
    siblings = await load_siblings(db, by_order.values())
    moment = datetime.now(timezone.utc)

    reopened = 0
    for gap in orphaned:
        fact = by_order.get(gap.order_id)
        if fact is None or fact.is_cancelled or gap.order_id in intents:
            # Samo zamówienie braku usunięte/anulowane albo współpraca
            # świadomie zakończona — nie ma czego przywracać.
            continue
        pinned = replace(fact, end=gap.ended_on)
        candidates = [
            other
            for other in (siblings_of(fact, siblings) or [fact])
            if other.order_id not in excluded
        ]
        successor = successor_of(pinned, candidates, include_self=True)
        if successor is not None:
            gap.resolved_order_id = successor.order_id
            gap.resolved_order_number = successor.number[:255]
            continue
        gap.status = GAP_STATUS_OPEN
        gap.resolved_order_id = None
        gap.resolved_order_number = None
        gap.resolved_at = None
        reopened += 1
        if notify:
            # Karta DL braku była odhaczona przy uzupełnieniu — zamykamy ten
            # epizod, żeby ``emit`` wystawił nową kartę zamiast uznać sprawę
            # za załatwioną.
            await dl_alerts.resolve_entity_alerts(
                db,
                alert_type=ALERT_ORDER_MISSING_SUCCESSOR,
                entity_key=f"gap:{gap.id}",
                now=moment,
            )
            await _notify(db, gap, fact, bell=bell)
    await db.flush()
    return reopened


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
    fact_list = await load_facts(db, ClientOrder.id.in_([gap.order_id for gap in gaps]))
    facts = {fact.order_id: fact for fact in fact_list}
    ended = set(await load_ending_intents(db, fact_list))
    created = 0
    for gap in gaps:
        fact = facts.get(gap.order_id)
        if fact is None:
            # Zamówienie usunięte — brak nie jest już sprawą do załatwienia
            # (FIN-CHG-5). Karta miała ``order_id`` wyzerowany przez FK, więc
            # zamykamy ją po kluczu sprawy.
            await dl_alerts.resolve_entity_alerts(
                db, alert_type=ALERT_ORDER_MISSING_SUCCESSOR, entity_key=f"gap:{gap.id}"
            )
            continue
        if gap.order_id in ended:
            # Współpraca zakończona po wykryciu braku: nie przypominamy DL
            # o zamówieniu, którego świadomie nie będzie, i zdejmujemy kartę.
            await _close_gap_alerts(db, gap.order_id, datetime.now(timezone.utc))
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
    await reopen_orphaned_gaps(db, bell=False)
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
            await reopen_orphaned_gaps(db, contract_ids=contract_ids)
            await resolve_order_gaps(db, contract_ids=contract_ids, actor_id=actor_id)
    except Exception:  # noqa: BLE001
        logger.exception("order gaps refresh failed")
