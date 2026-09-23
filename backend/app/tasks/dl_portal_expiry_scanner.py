"""Daily scanner — flippuje statusy + emituje notyfikacje expiry dla framework
contracts i client orders.

Lifecycle:
1. ``ClientFrameworkContract``: status=active, expiry_date<today → status=expired
2. ``ClientOrder``: status=active, end_date<today → status=completed
   (POZA liniami MD — te kończy budżet, nie kalendarz; patrz ``_promote_statuses``)
2a. ``ClientOrderGroup`` klientów z ``closes_on_md_exhaustion`` (BIK): wszystkie
   osoby wyczerpały limit MD → completed (``order_md_exhaustion``)
3. ``Contract``: ended/ending + aktywny Order obejmujący dziś → active
4. Dispatch notyfikacji expiry:
   - 30/14/7 dni przed ``ClientFrameworkContract.expiry_date`` (status=active)
   - 30/14/7 dni przed ``ClientOrder.end_date`` (status=active)

Progi liczone z ZAKRESU dni do końca (``_threshold_bucket``), nie z równości
z konkretną datą. Równość gubiła próg bezpowrotnie: dzień bez biegu skanera
albo zamówienie wpisane/przedłużone na mniej niż 30 dni i uprzedzenie
30-dniowe nie przychodziło nigdy — pierwszy dzwonek wypadał dopiero na 14 dni.
Ten sam powód, dla którego ``dl_alerts.date_cycle_stage`` liczy z zakresu.

Odbiorcy: aktywni admini globalnie oraz aktywni Delivery Leadzi wyłącznie dla
przypisanych klientów i tylko z effective ``delivery >= read``.

Dedup: ``Notification.related_entity_*`` + ``notification_type`` + DATA KOŃCA
per próg — jeden alert 30d + jeden 14d + jeden 7d na encję na KAŻDĄ datę
końca, więc przedłużenie zamówienia/umowy ramowej uzbraja progi od nowa.

Wzorzec: `app/tasks/contract_alerts.py` — daily loop z 24h sleep.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import and_, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import GROUP_STATUS_COMPLETED, ClientOrderGroup
from app.models.contract import Contract
from app.models.notification import Notification, NotificationType
from app.services.contract_lifecycle import (
    reconcile_contracts_to_live_orders,
)
from app.services.client_identity import client_display_name_expression
from app.services.delivery_alert_recipients import (
    DeliveryAlertRecipientScope,
    load_delivery_alert_recipient_scope,
)
from app.services.order_continuation import order_has_continuation
from app.services.order_group_lifecycle import materialize_scheduled_order_groups
from app.services.order_md_exhaustion import reconcile_md_exhausted_groups

logger = logging.getLogger(__name__)


_INTERVAL_HOURS = 24.0
_THRESHOLDS_DAYS = (30, 14, 7)

_FC_NTYPE_BY_DAY = {
    30: NotificationType.framework_contract_expiring_30d,
    14: NotificationType.framework_contract_expiring_14d,
    7: NotificationType.framework_contract_expiring_7d,
}
_ORDER_NTYPE_BY_DAY = {
    30: NotificationType.client_order_ending_30d,
    14: NotificationType.client_order_ending_14d,
    7: NotificationType.client_order_ending_7d,
}

#: Progi rosnąco — najciaśniejszy pasujący wygrywa.
_THRESHOLDS_ASC = tuple(sorted(_THRESHOLDS_DAYS))
#: Najdalszy próg = horyzont zapytania.
_HORIZON_DAYS = max(_THRESHOLDS_DAYS)


def _threshold_bucket(days_left: int) -> int | None:
    """Najciaśniejszy próg, w który wpada ``days_left`` — albo ``None``.

    Jeden bieg wysyła DOKŁADNIE JEDEN próg na encję: zamówienie przy 22 dniach
    dostaje próg 30, przy 13 próg 14, przy 6 próg 7 — trzy dzwonki w całym
    cyklu, tak jak przy równości, tylko bez gubienia ich przy pominiętym dniu.
    Powtórzeniu w kolejnych biegach tego samego pasma zapobiega
    :func:`_already_notified` (epizod = odbiorca, encja, próg, data końca).
    """
    for threshold in _THRESHOLDS_ASC:
        if days_left <= threshold:
            return threshold
    return None


def _lead_phrase(days_left: int) -> str:
    """„dzisiaj" / „za 1 dzień" / „za 22 dni" — do tytułu powiadomienia.

    Tytuł niesie FAKTYCZNĄ liczbę dni, nie numer progu: przy zakresach próg 30
    bywa wysłany przy 22 dniach i „za 30 dni" byłoby wtedy nieprawdą. Treść
    (``message``) zostaje nietknięta — niesie ``_end_phrase``, czyli klucz
    dedupu.
    """
    if days_left <= 0:
        return "dzisiaj"
    return f"za {days_left} {'dzień' if days_left == 1 else 'dni'}"


def _end_phrase(verb: str, end: date) -> str:
    """Fragment treści niosący datę końca — i zarazem klucz epizodu w dedupie.

    Jedno źródło dla treści i dla ``_already_notified``: rozjazd tych dwóch
    (np. zmiana formatu daty tylko w treści) zamieniłby dedup w no-op, a drugi
    wpis tego samego dnia rozbiłby się o ``ix_notif_dedup_daily`` i wycofał cały
    przebieg skanera, łącznie z przejściami statusów.
    """
    return f"{verb} {end.isoformat()}"


async def _already_notified(
    db: AsyncSession,
    *,
    user_id: int,
    related_entity_type: str,
    related_entity_id: int,
    ntype: NotificationType,
    end_phrase: str,
) -> bool:
    """Czy ten próg dla TEJ daty końca poszedł już do tej osoby.

    Epizod = (odbiorca, encja, próg, data końca). Klucz bez daty (do 09.2026)
    wyciszał próg na zawsze: zamówienie albo umowa ramowa przedłużone na nowy
    okres nie dostawały już ostrzeżeń 30/14/7 — dokładnie wtedy, gdy zbliżał
    się kolejny koniec. Data stoi w treści powiadomienia („… kończy się
    RRRR-MM-DD.” / „… wygasa RRRR-MM-DD.”) od pierwszej wersji skanera, więc
    wpisy sprzed tej zmiany dalej deduplikują swój epizod — bez migracji i bez
    jednorazowego zalewu powtórek. Ten sam wzorzec „epizod w kluczu” co
    ``[Nd|<data>]`` w ``contract_alerts``; tytuł zostaje czytelny.

    Drugi warunek to bezpiecznik ``ix_notif_dedup_daily`` i jest DOKŁADNIE
    jego kluczem: odbiorca, typ, numer encji, dzień w Warszawie — BEZ typu
    encji, bo indeks go nie zna. ``contract_alerts`` pisze
    ``client_order_ending_30d`` z ``related_entity_type='contract'``, więc
    kontrakt #N i zamówienie #N u tego samego odbiorcy w jednej warszawskiej
    dobie to dla indeksu ten sam wpis. To samo przy przesunięciu daty o dzień
    między biegami — od 09.2026 próg liczy ``business_today()`` (ten sam zegar
    co ``_promote_statuses``, koniec rozjazdu UTC/Warszawa), a że progi idą
    z zakresu, przesunięcie o dzień i tak trafia w to samo pasmo. Taki próg
    tego dnia odpuszczamy; ostatnia linia obrony to ``ON CONFLICT DO NOTHING``
    przy zapisie (:func:`_insert_notification`) — kolizja nie może wycofać
    całego przebiegu razem z przejściami statusów.
    """
    warsaw_day = func.date_trunc(
        "day", func.timezone("Europe/Warsaw", Notification.created_at)
    ) == func.date_trunc("day", func.timezone("Europe/Warsaw", func.now()))
    res = await db.execute(
        select(Notification.id)
        .where(
            Notification.user_id == user_id,
            Notification.related_entity_id == related_entity_id,
            Notification.notification_type == ntype,
            or_(
                and_(
                    Notification.related_entity_type == related_entity_type,
                    Notification.message.contains(end_phrase, autoescape=True),
                ),
                warsaw_day,
            ),
        )
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


async def _insert_notification(db: AsyncSession, **values: object) -> bool:
    """Wstaw powiadomienie; kolizja z ``ix_notif_dedup_daily`` = pominięcie.

    ``INSERT … ON CONFLICT DO NOTHING`` na tym właśnie indeksie (te same
    kolumny i wyrażenie dnia, ten sam warunek częściowy), więc inny błąd
    integralności nadal wychodzi na wierzch. Zwraca ``True``, gdy wiersz powstał.
    """
    statement = (
        pg_insert(Notification)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[
                Notification.user_id,
                Notification.notification_type,
                Notification.related_entity_id,
                literal_column(
                    "(date_trunc('day', created_at AT TIME ZONE 'Europe/Warsaw'))"
                ),
            ],
            index_where=Notification.related_entity_id.is_not(None),
        )
        .returning(Notification.id)
    )
    return (await db.execute(statement)).scalar_one_or_none() is not None


async def _promote_statuses(
    db: AsyncSession, *, business_day: date | None = None
) -> tuple[int, int, int, int]:
    """Materializuj dzienne przejścia FC, Order i przyszłych grup."""
    today = business_day or business_today()

    fc_expired = await db.execute(
        update(ClientFrameworkContract)
        .where(
            ClientFrameworkContract.status == FrameworkContractStatus.active,
            ClientFrameworkContract.expiry_date.is_not(None),
            ClientFrameworkContract.expiry_date < today,
        )
        .values(status=FrameworkContractStatus.expired)
    )
    order_completed = await db.execute(
        update(ClientOrder)
        .where(
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrder.end_date.is_not(None),
            ClientOrder.end_date < today,
            # Zamówienie rozliczane w MD kończy BUDŻET, nie kalendarz. Data
            # nadal opisuje okres obowiązywania i steruje alertami wygasania
            # niżej, ale nie domyka linii: konsultant z niewykorzystanymi MD
            # pracuje dalej, a zamknięty przez skaner wypadał z importu
            # zużycia (`md_lines_settling_in_month` pyta o linie aktywne), czyli MD
            # przestawały się odejmować i budżet zamierał na ostatniej
            # wartości. Statusem linii MD steruje wyłącznie
            # `client_order_lines.sync_md_line_status`.
            ClientOrder.md_total.is_(None),
        )
        .values(status=ClientOrderStatus.completed)
    )
    # Linia MD zamknięta W PRZÓD (zamiana kontraktora z datą w przyszłości,
    # zamknięcie grupy z przyszłą datą) dostaje datę końca od razu, a status
    # ``completed`` „gdy dzień nadejdzie" — tylko że nikt go potem nie stawiał,
    # bo warunek wyżej celowo pomija linie MD. Linia zostawała ``active`` na
    # zawsze: nie trafiała do Zejść, Kończących się ani Braków (audyt 22.09,
    # FIN-CHG-1). Zamykamy WYŁĄCZNIE linie, których koniec jest świadomą
    # decyzją: mają następcę (zamiana) albo ich grupa jest zakończona datą
    # nie późniejszą niż koniec linii. Linia MD z samą datą nadal pracuje
    # do wyczerpania budżetu.
    successor = aliased(ClientOrder)
    md_closed = await db.execute(
        update(ClientOrder)
        .where(
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrder.md_total.is_not(None),
            ClientOrder.end_date.is_not(None),
            ClientOrder.end_date < today,
            or_(
                select(successor.id)
                .where(
                    successor.predecessor_order_id == ClientOrder.id,
                    successor.status != ClientOrderStatus.cancelled,
                )
                .exists(),
                select(ClientOrderGroup.id)
                .where(
                    ClientOrderGroup.id == ClientOrder.order_group_id,
                    ClientOrderGroup.status == GROUP_STATUS_COMPLETED,
                    ClientOrderGroup.closure_date.is_not(None),
                    ClientOrderGroup.closure_date <= ClientOrder.end_date,
                )
                .exists(),
            ),
        )
        .values(status=ClientOrderStatus.completed)
        .execution_options(synchronize_session=False)
    )
    groups_promoted = await materialize_scheduled_order_groups(db, today=today)
    contracts_reconciled = await reconcile_contracts_to_live_orders(
        db,
        today=today,
    )
    return (
        fc_expired.rowcount or 0,
        (order_completed.rowcount or 0) + (md_closed.rowcount or 0),
        groups_promoted,
        contracts_reconciled,
    )


async def _scan_framework_contracts(
    db: AsyncSession, recipient_scope: DeliveryAlertRecipientScope
) -> int:
    """Zwraca # nowych notyfikacji."""
    today = business_today()
    rows = list(
        (
            await db.execute(
                select(ClientFrameworkContract).where(
                    ClientFrameworkContract.status == FrameworkContractStatus.active,
                    ClientFrameworkContract.expiry_date >= today,
                    ClientFrameworkContract.expiry_date
                    <= today + timedelta(days=_HORIZON_DAYS),
                )
            )
        ).scalars()
    )
    sent = 0
    for fc in rows:
        days_left = (fc.expiry_date - today).days
        days = _threshold_bucket(days_left)
        if days is None:
            continue
        ntype = _FC_NTYPE_BY_DAY[days]
        end_phrase = _end_phrase("wygasa", fc.expiry_date)
        for user_id in recipient_scope.for_client(fc.client_id):
            if await _already_notified(
                db,
                user_id=user_id,
                related_entity_type="client_framework_contract",
                related_entity_id=fc.id,
                ntype=ntype,
                end_phrase=end_phrase,
            ):
                continue
            if await _insert_notification(
                db,
                user_id=user_id,
                title=f"Umowa ramowa wygasa {_lead_phrase(days_left)}",
                message=(
                    f"'{fc.name}' {end_phrase}. "
                    "Skontaktuj się z klientem, aby przedyskutować przedłużenie."
                ),
                notification_type=ntype,
                related_entity_type="client_framework_contract",
                related_entity_id=fc.id,
                # Klucz z `frontend/src/lib/client-tab.ts`.
                link=f"/clients/{fc.client_id}?tab=umowy-ramowe",
            ):
                sent += 1
    return sent


async def _scan_orders(
    db: AsyncSession, recipient_scope: DeliveryAlertRecipientScope
) -> int:
    today = business_today()
    # Join Order → Contract → Candidate + Client dla candidate_name + client_name w treści
    rows = list(
        await db.execute(
            select(
                ClientOrder,
                Candidate.name.label("candidate_name"),
                client_display_name_expression().label("client_name"),
            )
            .join(Contract, Contract.id == ClientOrder.contract_id)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .join(Client, Client.id == ClientOrder.client_id)
            .where(
                ClientOrder.status == ClientOrderStatus.active,
                ClientOrder.end_date >= today,
                ClientOrder.end_date <= today + timedelta(days=_HORIZON_DAYS),
                # Dodana kontynuacja (także szkic) = nic do zrobienia; ta sama
                # reguła co zakładka „Kończące się 30d" i karta w panelu DL.
                ~order_has_continuation(),
            )
        )
    )
    sent = 0
    for row in rows:
        o: ClientOrder = row[0]
        days_left = (o.end_date - today).days
        days = _threshold_bucket(days_left)
        if days is None:
            continue
        ntype = _ORDER_NTYPE_BY_DAY[days]
        cand_name: str = row.candidate_name or "kontraktor"
        cli_name: str = row.client_name or "klient"
        end_phrase = _end_phrase("kończy się", o.end_date)

        for user_id in recipient_scope.for_client(o.client_id):
            if await _already_notified(
                db,
                user_id=user_id,
                related_entity_type="client_order",
                related_entity_id=o.id,
                ntype=ntype,
                end_phrase=end_phrase,
            ):
                continue
            if await _insert_notification(
                db,
                user_id=user_id,
                title=f"Zamówienie {cand_name} kończy się {_lead_phrase(days_left)}",
                message=(
                    f"Zamówienie dla {cand_name} u {cli_name} {end_phrase}. "
                    "Skontaktuj się z klientem, aby przedyskutować przedłużenie."
                ),
                notification_type=ntype,
                related_entity_type="client_order",
                related_entity_id=o.id,
                link=f"/clients/{o.client_id}?tab=zamowienia",
            ):
                sent += 1
    return sent


async def run_once() -> dict:
    """Uruchom scan + status promotions raz; zwraca summary dict."""
    async with AsyncSessionLocal() as db:
        try:
            (
                fc_expired,
                order_completed,
                groups_promoted,
                contracts_reconciled,
            ) = await _promote_statuses(db)
            # BIK: zamówienie kończy wyczerpanie limitów MD wszystkich osób —
            # siatka dla przejść, których nie wywołał import zużycia.
            md_groups_synced = await reconcile_md_exhausted_groups(db)
            recipient_scope = await load_delivery_alert_recipient_scope(db)
            fc_alerts = await _scan_framework_contracts(db, recipient_scope)
            order_alerts = await _scan_orders(db, recipient_scope)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            raise

    summary = {
        "fc_expired": fc_expired,
        "orders_completed": order_completed,
        "order_groups_promoted": groups_promoted,
        "md_exhaustion_groups_synced": md_groups_synced,
        "contracts_reconciled": contracts_reconciled,
        "fc_alerts_dispatched": fc_alerts,
        "order_alerts_dispatched": order_alerts,
    }
    logger.info("DL portal expiry scan: %s", summary)
    return summary


async def dl_portal_expiry_loop() -> None:
    """Daily loop — first run on startup, potem co 24h."""
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("dl_portal_expiry_loop iteration failed")
        try:
            await asyncio.sleep(_INTERVAL_HOURS * 3600)
        except asyncio.CancelledError:
            raise
