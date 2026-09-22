"""Emisja i cykliczność powiadomień Delivery Leada.

Cała wiedza o tym, KIEDY alert się powtarza i KIEDY przestaje, siedzi tutaj —
skaner (``app/tasks/dl_alerts_scanner.py``) tylko wylicza warunki i woła
``emit``. Dzięki temu dołożenie piątego typu alertu jest dopisaniem reguły,
a nie przebudową mechanizmu (wymóg ticketu).

**Powtórka co 7 dni jest NOWYM wierszem, nie aktualizacją.** Ticket wymaga, by
każde ponowienie było widoczne osobno w historii i w eksporcie — inaczej raport
pokazywałby jeden alert zamiast sześciu tygodni ignorowania sprawy. Dlatego
numer okna wchodzi w skład ``dedupe_key``.

**Powtórki ustają w dwóch przypadkach i tylko w tych dwóch:**

* którykolwiek wcześniejszy wiersz tej samej sprawy ma ``status='handled'`` —
  człowiek powiedział „zajęte", więc system przestaje o tym mówić, nawet gdy
  warunek trwa. To świadome: alert, który wraca po obsłużeniu, uczy ignorować
  całą sekcję;
* warunek ustał — wtedy skaner po prostu nie wywoła ``emit``.

Nowa SPRAWA (inne zamówienie, inna linia) ma inny klucz encji, więc alarmuje
od nowa niezależnie od tego, co obsłużono wcześniej.

**Panel „Moi klienci" (09.2026) — sprawa, etap, epizod.**

* ``event_key = {typ}:{encja}:{odbiorca}`` identyfikuje SPRAWĘ, czyli jedną
  kartę panelu. Wszystkie wiersze powtórek niosą ten sam klucz, więc lista
  składa je w jedną kartę, a odhaczenie zamyka je naraz.
* ``stage`` zastępuje numer okna tam, gdzie próg ma nazwę: ``t14`` (mail),
  ``t7`` i ``high`` (wysoki priorytet + mail). Bez ``stage`` klucz dostaje
  numer tygodnia jak dotąd — istniejące klucze się nie zmieniają.
* Przyczyna ustąpiła bez odhaczenia → ``resolve_stale`` stawia wierszom
  ``status='resolved'``. To NIE jest odhaczenie DL (``handled_by`` pusty).
  Każde takie zamknięcie kończy EPIZOD: jeśli warunek wróci, sprawa alarmuje
  od nowa z prefiksem ``e{n}`` w kluczu (inaczej ``ON CONFLICT`` zdusiłby
  pierwsze przypomnienie nowego epizodu, bo klucz ``…:0`` już istnieje).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_EXHAUSTED,
    ClientOrderGroup,
    ClientOrderGroupEvent,
)
from app.models.contract import Contract
from app.models.dl_alert import (
    ALERT_COST_ORDER_EXHAUSTED,
    ALERT_DRAFT_CONSULTANT_UNASSIGNED,
    ALERT_MD_CONSULTANT_ENDED,
    ALERT_NEW_CONTRACTOR_DRAFT,
    DL_ALERT_PRIORITY_HIGH,
    DL_ALERT_PRIORITY_STANDARD,
    DL_ALERT_STATUS_HANDLED,
    DL_ALERT_STATUS_NEW,
    DL_ALERT_STATUS_RESOLVED,
    DlAlert,
)
from app.models.user import User
from app.services.client_identity import client_display_name_expression
from app.services.delivery_alert_recipients import (
    DeliveryAlertRecipientScope,
    load_delivery_alert_recipient_scope,
)
from app.services.multi_consultant_orders import EVENT_BUDGET_EXHAUSTED

logger = logging.getLogger(__name__)


async def dl_user_ids_for_client(
    db: AsyncSession,
    client_id: int,
    *,
    scope: DeliveryAlertRecipientScope | None = None,
) -> list[int]:
    """Active, authorised Delivery Leads assigned to this client.

    Jeden warunek daje tyle wierszy, ilu DL jest przypisanych. Raport ma
    odpowiadać na pytanie „ile spraw KTO zignorował", a nie „ile było
    zdarzeń", więc alert nie może być współdzielony. Sam historyczny wpis w
    tabeli przypisań nie jest grantem: odbiorca musi nadal mieć rolę Delivery
    Leada i effective ``delivery >= read``.
    """
    resolved_scope = scope
    if resolved_scope is None:
        resolved_scope = await load_delivery_alert_recipient_scope(db)
    return sorted(
        resolved_scope.delivery_lead_ids_by_client.get(client_id, frozenset())
    )


def repeat_window(first_seen: datetime, now: datetime, *, every_days: int) -> int:
    """Numer okna powtórki, licząc od daty PIERWSZEGO alertu tej sprawy.

    Ticket mówi wprost: „nie w ustalony dzień tygodnia — cykl liczony
    indywidualnie dla każdego alertu, od jego własnej daty powstania". Okno
    liczone od poniedziałku zsynchronizowałoby wszystkie alerty w jeden dzień
    i zamieniło sekcję w cotygodniową ścianę wpisów.
    """
    if every_days <= 0:
        return 0
    delta = now - first_seen
    return max(0, delta.days // every_days)


def event_key_for(alert_type: str, entity_key: str, user_id: int) -> str:
    """Klucz SPRAWY (jednej karty panelu) — ``dedupe_key`` bez etapu."""
    return f"{alert_type}:{entity_key}:{user_id}"


async def _episode_state(
    db: AsyncSession, *, event_key: str
) -> tuple[Optional[datetime], bool, int]:
    """(pierwszy alert bieżącego epizodu, czy obsłużony w nim, numer epizodu).

    Epizod kończy ``resolve_stale`` / ``resolve_entity_alerts`` — gdy przyczyna
    ustąpiła, WSZYSTKIE wiersze sprawy (otwarte i odhaczone) dostają wspólny
    stempel ``episode_closed_at``. Liczba różnych stempli to numer epizodu,
    a bieżący epizod to wiersze bez stempla. Bez zamykania odhaczonych wierszy
    sprawa odhaczona raz nie alarmowałaby już nigdy — nawet gdy problem minął
    i po miesiącach wrócił (np. pula MD uzupełniona i znów niska).

    Porównujemy stemple, nie znaczniki czasu wierszy: ``created_at`` i moment
    zamknięcia pochodzą z różnych zegarów (baza vs proces).
    """
    res = await db.execute(
        select(DlAlert.created_at, DlAlert.status, DlAlert.episode_closed_at)
        .where(DlAlert.event_key == event_key)
        .order_by(DlAlert.created_at.asc(), DlAlert.id.asc())
    )
    rows = res.all()
    if not rows:
        return None, False, 0
    episode = len({closed for _, _, closed in rows if closed is not None})
    current = [
        (created_at, status)
        for created_at, status, closed in rows
        if closed is None and status != DL_ALERT_STATUS_RESOLVED
    ]
    if not current:
        return None, False, episode
    handled = any(status == DL_ALERT_STATUS_HANDLED for _, status in current)
    return current[0][0], handled, episode


async def emit(
    db: AsyncSession,
    *,
    alert_type: str,
    user_ids: Sequence[int],
    client_id: int,
    entity_key: str,
    title: str,
    message: str,
    link: Optional[str] = None,
    payload: Optional[dict] = None,
    order_group_id: Optional[int] = None,
    order_id: Optional[int] = None,
    offboarding_case_id: Optional[int] = None,
    repeat_every_days: Optional[int] = None,
    stage: Optional[str] = None,
    priority: str = DL_ALERT_PRIORITY_STANDARD,
    email: bool = False,
    email_on_first: bool = False,
    now: Optional[datetime] = None,
) -> list[DlAlert]:
    """Wystaw alert każdemu wskazanemu odbiorcy. Zwraca faktycznie utworzone.

    ``repeat_every_days=None`` = alert jednorazowy (klucz bez okna); tak działa
    wyczerpanie budżetu, bo samo zdarzenie jest jednorazowe.

    ``stage`` (``t14``/``t7``/``high``) = nazwany próg: jeden wiersz na próg,
    niezależnie od okna tygodniowego. ``email=True`` zapisuje w payloadzie
    prośbę o mail — wysyła go ``send_pending_alert_emails`` po skanie.

    ``email_on_first=True`` prosi o mail także przy PIERWSZYM wierszu sprawy,
    niezależnie od etapu. Tak działa miesięczne uprzedzenie o kończącym się
    zamówieniu: sprawa wchodzi w okno ``DL_ALERT_ENDING_WINDOW_DAYS`` (30 dni)
    i od razu idzie mail, zamiast czekać na ``t14``. Świadomie liczone
    z ``first_seen``, a nie z nowego etapu ``t30``: etap wykluczyłby powtórki
    tygodniowe w paśmie 30→15 dni (etap i numer okna to ta sama pozycja
    ``dedupe_key``) i wysłałby zaraz po wdrożeniu mail każdej sprawie już
    wiszącej w oknie. Sprawa z otwartym wierszem ma ``first_seen`` ustawione,
    więc maila nie dostaje.

    Zapis idzie przez ``INSERT … ON CONFLICT DO NOTHING`` na ``dedupe_key``,
    a nie przez „SELECT, potem INSERT": ta druga wersja ma okno wyścigu, w
    którym dwa równoległe przebiegi skanera widzą brak wiersza, oba wstawiają
    i drugie dostaje ``IntegrityError`` — czyli padnięty przebieg zamiast
    no-opu.
    """
    if not settings.DL_ALERTS_ENABLED or not user_ids:
        return []
    moment = now or datetime.now(timezone.utc)
    created: list[DlAlert] = []

    base_payload = dict(payload or {})

    for user_id in user_ids:
        event_key = event_key_for(alert_type, entity_key, user_id)
        first_seen, handled, episode = await _episode_state(db, event_key=event_key)
        if handled:
            continue

        # Payload liczony PER ODBIORCA, bo `email_on_first` zależy od tego, czy
        # TEN odbiorca ma już otwarty wiersz sprawy: nowy Delivery Lead
        # przypisany do klienta w połowie okna dostaje swój pierwszy mail, a
        # pozostali nie dostają drugiego.
        row_payload = dict(base_payload)
        if email or (email_on_first and first_seen is None):
            row_payload["email"] = True

        if stage is not None:
            window = stage
        elif repeat_every_days is None:
            window = "once"
        else:
            window = str(
                repeat_window(
                    first_seen or moment, moment, every_days=repeat_every_days
                )
            )
        if episode:
            window = f"e{episode}:{window}"
        dedupe_key = f"{event_key}:{window}"

        stmt = (
            pg_insert(DlAlert)
            .values(
                alert_type=alert_type,
                user_id=user_id,
                client_id=client_id,
                order_group_id=order_group_id,
                order_id=order_id,
                offboarding_case_id=offboarding_case_id,
                title=title[:255],
                message=message,
                link=link,
                payload=row_payload or None,
                dedupe_key=dedupe_key[:255],
                # Ten sam zegar co okno powtórki (`moment`), nie `now()` bazy.
                created_at=moment,
                event_key=event_key[:255],
                priority=(
                    DL_ALERT_PRIORITY_HIGH
                    if priority == DL_ALERT_PRIORITY_HIGH
                    else DL_ALERT_PRIORITY_STANDARD
                ),
            )
            .on_conflict_do_nothing(constraint="uq_dl_alerts_dedupe_key")
            .returning(DlAlert.id)
        )
        alert_id = await db.scalar(stmt)
        if alert_id is None:
            continue
        alert = await db.get(DlAlert, alert_id)
        if alert is not None:
            created.append(alert)
    return created


async def resolve_stale(
    db: AsyncSession,
    *,
    alert_type: str,
    live_event_keys: set[str],
    entity_prefix: Optional[str] = None,
    now: Optional[datetime] = None,
) -> int:
    """Zamknij sprawy typu, których warunek już nie zachodzi. Zwraca liczbę
    zamkniętych OTWARTYCH wierszy (karty zdjęte z panelu).

    ``live_event_keys`` to klucze spraw, które reguła w TYM przebiegu uznała za
    aktualne (także te, dla których ``emit`` nic nie dopisał, bo wiersz już
    był). Sprawa odbiorcy, który przestał być DL klienta, też wypada z tego
    zbioru — i poprawnie się zamyka.

    ``entity_prefix`` zawęża zamykanie do przestrzeni kluczy jednej reguły,
    gdy ten sam typ emituje kilka ścieżek (``draft_consultant_unassigned``:
    ``order:`` ze skanera i ``mail-draft:`` z writera maila).

    Dwa kroki, jeden stempel ``episode_closed_at`` na przebieg:
    otwarte wiersze → ``resolved`` (karta znika, to nie odhaczenie DL);
    odhaczone wiersze → tylko stempel epizodu, żeby powrót warunku znów
    alarmował (``_episode_state``).
    """
    moment = now or datetime.now(timezone.utc)
    prefix = f"{alert_type}:{entity_prefix or ''}"

    def _scoped(stmt):
        stmt = stmt.where(
            DlAlert.alert_type == alert_type,
            DlAlert.episode_closed_at.is_(None),
            # `autoescape`: typy mają `_`, który w LIKE jest wieloznacznikiem.
            DlAlert.event_key.startswith(prefix, autoescape=True),
        )
        if live_event_keys:
            stmt = stmt.where(DlAlert.event_key.not_in(sorted(live_event_keys)))
        return stmt.execution_options(synchronize_session=False)

    result = await db.execute(
        _scoped(
            update(DlAlert)
            .where(DlAlert.status == DL_ALERT_STATUS_NEW)
            .values(
                status=DL_ALERT_STATUS_RESOLVED,
                handled_at=moment,
                episode_closed_at=moment,
            )
        )
    )
    await db.execute(
        _scoped(
            update(DlAlert)
            .where(
                DlAlert.status.in_((DL_ALERT_STATUS_HANDLED, DL_ALERT_STATUS_RESOLVED))
            )
            .values(episode_closed_at=moment)
        )
    )
    return result.rowcount or 0


async def resolve_entity_alerts(
    db: AsyncSession,
    *,
    alert_type: str,
    entity_key: str,
    now: Optional[datetime] = None,
) -> int:
    """Zamknij natychmiast sprawy JEDNEJ encji (wszyscy odbiorcy).

    Ścieżki zdarzeniowe (zastosowany mail, uzupełniony szkic) nie czekają na
    dobowy skaner — karta ma zniknąć w chwili, w której przyczyna ustąpiła.
    """
    return await resolve_stale(
        db,
        alert_type=alert_type,
        live_event_keys=set(),
        entity_prefix=f"{entity_key}:",
        now=now,
    )


def date_cycle_stage(
    days_left: int,
) -> tuple[Optional[str], str, bool]:
    """(etap, priorytet, mail) cyklu „kończy się w dniu X".

    * więcej niż 14 dni → tydzień okna (``None`` = numer tygodnia), standard;
    * 14…8 dni → ``t14``, standard + mail;
    * 7…0 dni → ``t7``, wysoki priorytet + mail.

    Mail miesiąc przed końcem NIE jest tutaj — daje go ``email_on_first``
    w :func:`emit` (pierwszy wiersz sprawy). Osobny etap ``t30`` zabrałby
    powtórki tygodniowe z pasma 30→15 dni, bo etap i numer okna zajmują tę samą
    pozycję w ``dedupe_key``.

    Liczone z ZAKRESU dni do końca, nie z równości z konkretną datą — dzień
    bez biegu skanera nie gubi progu (stary skaner dzwonka tak go gubił).
    """
    if days_left <= 7:
        return "t7", DL_ALERT_PRIORITY_HIGH, True
    if days_left <= 14:
        return "t14", DL_ALERT_PRIORITY_STANDARD, True
    return None, DL_ALERT_PRIORITY_STANDARD, False


async def emit_md_consultant_ended(
    db: AsyncSession,
    *,
    case_id: int,
    client_id: int,
    order_id: int,
    order_group_id: Optional[int],
    order_number: Optional[str],
    consultant_name: str,
    effective_date: date,
    remaining_md: Decimal,
    uses_shared_md_pool: bool,
) -> list[DlAlert]:
    """Emit the one-off DL decision alert for an effective MD offboarding.

    The case id is the episode discriminator.  Re-running contract termination
    therefore repairs a missing alert but cannot duplicate an existing one.
    Rates deliberately stay out of the alert payload: dashboard visibility is
    wider than financial visibility, while the decision endpoint can enforce
    ``VIEW_FINANCE`` before returning the snapshots.
    """

    user_ids = await dl_user_ids_for_client(db, client_id)
    client_name = (
        await db.scalar(
            select(client_display_name_expression()).where(Client.id == client_id)
        )
    ) or "Klient"
    number = order_number or "—"
    if uses_shared_md_pool:
        pool_detail = (
            "Zamówienie ma wspólną pulę MD — zakończenie jednej osoby nie "
            "zmieniło jej wartości."
        )
    else:
        pool_detail = f"Do rozstrzygnięcia pozostało {remaining_md} MD."

    return await emit(
        db,
        alert_type=ALERT_MD_CONSULTANT_ENDED,
        user_ids=user_ids,
        client_id=client_id,
        entity_key=f"case:{case_id}",
        title=f"{client_name} — decyzja MD po zakończeniu współpracy",
        message=(
            f"{consultant_name} zakończył(a) współpracę {effective_date.isoformat()} "
            f"na zamówieniu {number}. {pool_detail} Otwórz zamówienie i wybierz "
            "usunięcie, przeniesienie albo przywrócenie konsultanta."
        ),
        link=(f"/clients/{client_id}?tab=zamowienia&offboardingCase={case_id}"),
        payload={
            "offboarding_case_id": case_id,
            "order_number": order_number,
            "consultant_name": consultant_name,
            "effective_date": effective_date.isoformat(),
            "remaining_md": str(remaining_md),
            "uses_shared_md_pool": uses_shared_md_pool,
        },
        order_group_id=order_group_id,
        order_id=order_id,
        offboarding_case_id=case_id,
        repeat_every_days=None,
    )


async def handle_offboarding_case_alerts(
    db: AsyncSession,
    *,
    case_id: int,
    handled_by_user_id: int,
    now: Optional[datetime] = None,
) -> int:
    """Resolve every recipient row for one decision without deleting history."""

    moment = now or datetime.now(timezone.utc)
    result = await db.execute(
        update(DlAlert)
        .where(
            DlAlert.offboarding_case_id == case_id,
            DlAlert.status == DL_ALERT_STATUS_NEW,
        )
        .values(
            status=DL_ALERT_STATUS_HANDLED,
            handled_by_user_id=handled_by_user_id,
            handled_at=moment,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def emit_cost_order_exhausted(
    db: AsyncSession, group: ClientOrderGroup
) -> list[DlAlert]:
    """Alert o wyczerpaniu budżetu zamówienia KOSZTOWEGO (pula w złotych)."""

    return await _emit_budget_exhausted(
        db,
        group,
        detail="Sprawdź rozliczenie i zorganizuj nowe zamówienie.",
    )


async def emit_shared_md_pool_exhausted(
    db: AsyncSession, group: ClientOrderGroup
) -> list[DlAlert]:
    """Alert o wyczerpaniu WSPÓLNEJ PULI MD (Lotte Wedel, Cyfrowy Polsat).

    Ten sam typ alertu co przy zamówieniu kosztowym, bo dla odbiorcy to ta sama
    sprawa: pula się skończyła, zamówienie przestało przyjmować konsultantów
    i trzeba coś z tym zrobić. Osobny typ oznaczałby osobną kolumnę w raporcie
    i osobną pozycję do odklikania, mimo że decyzja jest identyczna.

    Różni się treść, bo różni się jednostka: tam brakło pieniędzy, tu dni.
    Wspólna pula NIE MA odpowiednika progu „mało MD" — ten działa na budżecie
    przypisanym osobie — więc dla tych dwóch klientów jest to jedyny sygnał
    o końcu budżetu, jaki w ogóle przychodzi.
    """

    return await _emit_budget_exhausted(
        db,
        group,
        detail="Zwiększ pulę MD albo zorganizuj nowe zamówienie.",
    )


async def _emit_budget_exhausted(
    db: AsyncSession, group: ClientOrderGroup, *, detail: str
) -> list[DlAlert]:
    """Wspólna mechanika alertu „zamówienie wyczerpane".

    Nie powtarza się co tydzień — samo zdarzenie jest jednorazowe (zamówienie
    trafia do zakończonych), więc ponawianie mówiłoby o czymś, co już się nie
    zmienia.

    Ale „jednorazowy" znaczy „raz na EPIZOD", nie „raz w życiu zamówienia":
    operator może podnieść kwotę (``settle_group`` odsłania wtedy budżet
    i wraca na ``active``), a kolejny import albo korekta znów ją wyczerpać.
    Przy kluczu opartym wyłącznie na ``group.id`` drugie wyczerpanie wpadłoby
    w ``ON CONFLICT DO NOTHING`` i **nikt by się o nim nie dowiedział** —
    a to moment, w którym kończą się pieniądze na projekcie.

    Epizod liczymy LICZBĄ PRZEJŚĆ zapisanych w historii zamówienia, nie kwotą
    budżetu: kwota podniesiona i wróconą do poprzedniej wartości dałaby ten sam
    klucz co pierwszy raz. Zdarzenie ``wyczerpanie`` powstaje dokładnie raz na
    przejście ``active → exhausted`` (każda ścieżka emisji zapisuje je przed
    wywołaniem tej funkcji), więc licznik jest deterministyczny i stały
    w obrębie jednej transakcji — ponowienie tego samego przejścia nadal
    trafia w ten sam klucz. Ten sam wzorzec „epizod w kluczu" co
    w ``ContractAlertDedup``, gdzie klucz niesie datę końca umowy.
    """
    episode = await db.scalar(
        select(func.count(ClientOrderGroupEvent.id)).where(
            ClientOrderGroupEvent.group_id == group.id,
            ClientOrderGroupEvent.event_type == EVENT_BUDGET_EXHAUSTED,
        )
    )
    user_ids = await dl_user_ids_for_client(db, group.client_id)
    # Nazwa klienta JAWNYM zapytaniem, nie przez `group.client`: ta grupa
    # przychodzi ze ścieżki importu, gdzie eager-loadowana jest wyłącznie
    # relacja z linii do grupy. Sięgnięcie po relację bez eager-loadu w async
    # SQLAlchemy to `MissingGreenlet` — czyli 500 w środku importu, po
    # zapisaniu części rozliczeń.
    client_name = (
        await db.scalar(
            select(client_display_name_expression()).where(Client.id == group.client_id)
        )
    ) or "Klient"
    return await emit(
        db,
        alert_type=ALERT_COST_ORDER_EXHAUSTED,
        user_ids=user_ids,
        client_id=group.client_id,
        entity_key=f"group:{group.id}:ep:{int(episode or 0)}",
        title=f"{client_name} — zamówienie {group.order_number} wyczerpane",
        message=(
            f"⚠ {client_name} — zamówienie {group.order_number} zostało "
            f"wyczerpane i przeniesione do zakończonych. {detail}"
        ),
        link=f"/clients/{group.client_id}?tab=zamowienia",
        payload={"order_number": group.order_number},
        order_group_id=group.id,
        repeat_every_days=None,
    )


async def reconcile_exhausted_group_budget_alerts(db: AsyncSession) -> int:
    """Backstop: dostarcz alert wyczerpania, który przepadł przy braku DL.

    Alert wyczerpania budżetu (kosztowego albo wspólnej puli MD) jest
    JEDNORAZOWY i emitowany w chwili przejścia ``active → exhausted``. Jeśli
    w tym momencie klient nie miał przypisanego Delivery Leada, ``emit`` szedł do
    PUSTEJ listy odbiorców i alert przepadał bez śladu — a dla zamówień
    kosztowych i wspólnej puli MD to JEDYNY sygnał o końcu budżetu. Ta funkcja
    (dobowa) dostarcza go po przypisaniu DL.

    Zbiór jest naturalnie ograniczony: bierzemy WYŁĄCZNIE grupy ``exhausted``,
    dla których NIE istnieje ani jeden wiersz alertu wyczerpania — czyli takie,
    gdzie emisja poszła w próżnię. Gdy tylko powstanie pierwszy wiersz (po
    przypisaniu DL), grupa wypada ze zbioru, więc pętla nie rośnie w
    nieskończoność ani nie ponawia dostarczonego alertu.
    ``with_for_update(skip_locked=True)`` rozdziela współbieżne skany, a sama
    emisja jest idempotentna (klucz per epizod + ``ON CONFLICT DO NOTHING``).

    Świadome ograniczenie: filtr „brak JAKIEGOKOLWIEK alertu wyczerpania" jest
    per grupa, nie per epizod. Re-wyczerpanie (nowy epizod) grupy, która ma już
    historyczny wiersz, obsługuje ścieżka emisji w chwili przejścia — a ta ma
    wtedy odbiorcę (inaczej pierwszego wiersza by nie było). Backstop celuje
    w klienta, który przy wyczerpaniu nie miał DL w ogóle.
    """
    if not settings.DL_ALERTS_ENABLED:
        return 0
    stmt = (
        select(ClientOrderGroup)
        .where(
            ClientOrderGroup.status == GROUP_STATUS_EXHAUSTED,
            ~select(DlAlert.id)
            .where(
                DlAlert.order_group_id == ClientOrderGroup.id,
                DlAlert.alert_type == ALERT_COST_ORDER_EXHAUSTED,
            )
            .exists(),
        )
        .order_by(ClientOrderGroup.id.asc())
        .with_for_update(skip_locked=True)
    )
    created = 0
    for group in (await db.execute(stmt)).scalars().all():
        # Savepoint PER GRUPA: awaria emisji jednej grupy (brakujący FK,
        # nieoczekiwany constraint) nie może wycofać alertów już wystawionych
        # grupom wcześniejszym w tym przebiegu. Lustro wzorca z `_run_rules`,
        # gdzie każda reguła ma własny `begin_nested()`.
        try:
            async with db.begin_nested():
                if group.is_cost_based:
                    alerts = await emit_cost_order_exhausted(db, group)
                else:
                    alerts = await emit_shared_md_pool_exhausted(db, group)
                created += len(alerts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "backstop wyczerpania: emisja padła dla grupy %d", group.id
            )
    return created


#: Activity, którą writer zamówień z maila zostawia na PIERWSZYM drafcie nowej
#: osoby u klienta. Tego draftu nie obejmuje cotygodniowa reguła „bez
#: zamówienia” (``rule_draft_consultant_unassigned``) — ma jednorazowy alert.
MAIL_NEW_DRAFT_ACTION = "order_mail_new_draft"


async def emit_mail_new_draft(
    db: AsyncSession,
    *,
    client_id: int,
    order_id: int,
    consultant: str,
    user_ids: Optional[Sequence[int]] = None,
) -> list[DlAlert]:
    """Jednorazowy alert o pierwszym drafcie z maila (nowa osoba u klienta).

    Jedno źródło treści dla writera (w chwili zapisu) i dla backstopu
    (po przypisaniu Delivery Leada). Klucz ``mail-draft:<id>`` bez okna —
    ``ON CONFLICT`` w ``emit`` gwarantuje, że obie ścieżki razem dadzą jeden
    wiersz na odbiorcę.
    """
    client = await db.get(Client, client_id)
    client_name = (client.display_name or client.name) if client else "Klient"
    if user_ids is None:
        user_ids = await dl_user_ids_for_client(db, client_id)
    return await emit(
        db,
        alert_type=ALERT_DRAFT_CONSULTANT_UNASSIGNED,
        user_ids=user_ids,
        client_id=client_id,
        entity_key=f"mail-draft:{order_id}",
        order_id=order_id,
        repeat_every_days=None,
        title=f"Nowy kontraktor {consultant} w {client_name}",
        message=(
            f"Nowy kontraktor {consultant} w {client_name} — uzupełnij dane: "
            "stawka kosztowa."
        ),
        # Klucz zakładki z `frontend/src/lib/client-tab.ts` — nieznany klucz
        # (dawniej „orders") otwierał profil zamiast zakładki ze sprawą.
        link=f"/clients/{client_id}?tab=zamowienia",
    )


async def reconcile_mail_new_draft_alerts(
    db: AsyncSession,
    recipient_scope: DeliveryAlertRecipientScope | None = None,
) -> int:
    """Backstop: dostarcz alert o pierwszym drafcie z maila, który przepadł.

    Lustro ``reconcile_exhausted_group_budget_alerts`` (#1394), ci sami
    odbiorcy: Delivery Leadzi przypisani do klienta. Writer wystawia alert
    w chwili zapisu draftu; gdy klient nie miał wtedy DL, ``emit`` szedł do
    PUSTEJ listy, a cotygodniowa reguła „bez zamówienia” takiego draftu
    świadomie nie obejmuje — więc sprawa nie docierała do nikogo, także po
    przypisaniu DL. Tu dostarczamy ją raz, po przypisaniu.

    Zbiór jest naturalnie ograniczony: drafty z Activity
    ``order_mail_new_draft`` bez ANI JEDNEGO wiersza tego alertu. Po
    dostarczeniu (albo gdy draft przestanie być draftem) zamówienie wypada ze
    zbioru. Bez ``FOR UPDATE`` na zamówieniach — to drafty, które DL właśnie
    uzupełnia, a emisja i tak jest idempotentna (klucz + ``ON CONFLICT``).
    """
    if not settings.DL_ALERTS_ENABLED:
        return 0
    from app.services.client_order_lines import consultant_display_name
    from sqlalchemy.orm import selectinload

    if recipient_scope is None:
        recipient_scope = await load_delivery_alert_recipient_scope(db)
    stmt = (
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract).selectinload(Contract.candidate))
        .where(
            ClientOrder.status == ClientOrderStatus.draft,
            select(Activity.id)
            .where(
                Activity.entity_type == "client_order",
                Activity.entity_id == ClientOrder.id,
                Activity.action == MAIL_NEW_DRAFT_ACTION,
            )
            .exists(),
            ~select(DlAlert.id)
            .where(
                DlAlert.order_id == ClientOrder.id,
                DlAlert.alert_type == ALERT_DRAFT_CONSULTANT_UNASSIGNED,
            )
            .exists(),
        )
        .order_by(ClientOrder.id.asc())
    )
    created = 0
    for order in (await db.execute(stmt)).scalars().all():
        user_ids = await dl_user_ids_for_client(
            db, order.client_id, scope=recipient_scope
        )
        if not user_ids:
            # Nadal brak DL — spróbujemy przy następnym przebiegu.
            continue
        name = consultant_display_name(order)
        try:
            async with db.begin_nested():
                alerts = await emit_mail_new_draft(
                    db,
                    client_id=order.client_id,
                    order_id=order.id,
                    consultant=name if name and name != "—" else "Konsultant",
                    user_ids=user_ids,
                )
                created += len(alerts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "backstop draftu z maila: emisja padła dla zamówienia %d", order.id
            )
    return created


def reaction_seconds(alert: DlAlert) -> Optional[int]:
    """Czas reakcji w sekundach albo ``None`` dla nieobsłużonych.

    Wiersz zamknięty automatycznie (``resolved``) nie ma czasu reakcji — nikt
    nie zareagował, przyczyna ustąpiła sama.
    """
    if alert.handled_at is None or alert.status != DL_ALERT_STATUS_HANDLED:
        return None
    delta: timedelta = alert.handled_at - alert.created_at
    return max(0, int(delta.total_seconds()))


def format_reaction(alert: DlAlert) -> str:
    """Czas reakcji po ludzku („2 dni 3 h", „—" dla nieobsłużonych)."""
    seconds = reaction_seconds(alert)
    if seconds is None:
        return "—"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    if minutes or not parts:
        parts.append(f"{minutes} min")
    return " ".join(parts)


# ── Nowy kontraktor z Generatora umów ───────────────────────────────────────

#: Tytuł-zaślepka szkicu u klienta wielo-konsultantowego / MD / kosztowego.
ORDER_NUMBER_PLACEHOLDER = "(bez numeru)"


def new_contractor_missing_fields(
    order: ClientOrder, *, candidate_name: Optional[str], job_title: Optional[str]
) -> list[str]:
    """Czego brakuje w szkicu zamówienia, żeby DL mógł go aktywować.

    Numer zamówienia NIE ma osobnej kolumny: w widoku jednoosobowym tytuł
    zamówienia JEST jego numerem. Szkic z podpisu dostaje tytuł-etykietę
    „Imię Nazwisko — Rekrutacja" albo zaślepkę „(bez numeru)"; dopóki tytuł
    jest jednym z nich, numeru nikt nie wpisał.
    """
    missing: list[str] = []
    has_revenue_rate = (
        order.md_rate_revenue is not None
        if order.order_group_id is not None
        else order.rate_client is not None
    )
    if not has_revenue_rate:
        missing.append("stawkę przychodową")
    if order.start_date is None or order.end_date is None:
        missing.append("okres zamówienia")
    title = (order.title or "").strip()
    # Tytuł-etykieta szkicu z podpisu to „Imię Nazwisko — Rekrutacja". Porównanie
    # po KOŃCÓWCE (tytule rekrutacji), nie po imieniu: korekta nazwiska
    # kandydata nie może udawać wpisanego numeru.
    auto_label = bool(
        title
        and (
            title == ORDER_NUMBER_PLACEHOLDER
            or (job_title and title.endswith(f" — {job_title}"))
            or (
                candidate_name
                and title in {candidate_name, f"{candidate_name} — {job_title}"}
            )
        )
    )
    if not title or auto_label:
        missing.append("numer zamówienia")
    return missing


async def emit_new_contractor_draft(
    db: AsyncSession,
    *,
    order: ClientOrder,
    candidate_name: str,
    job_title: Optional[str],
    user_ids: Optional[Sequence[int]] = None,
    now: Optional[datetime] = None,
) -> list[DlAlert]:
    """Karta „Nowy kontraktor u klienta — uzupełnij zamówienie".

    Jedno źródło treści dla ścieżki podpisu (natychmiast) i dla skanera
    (powtórka co 7 dni, dopóki czegoś brakuje). Link otwiera TEN szkic
    (``?order=``), nie samą zakładkę.
    """
    missing = new_contractor_missing_fields(
        order, candidate_name=candidate_name, job_title=job_title
    )
    if not missing:
        return []
    client_name = (
        await db.scalar(
            select(client_display_name_expression()).where(Client.id == order.client_id)
        )
    ) or "Klient"
    if user_ids is None:
        user_ids = await dl_user_ids_for_client(db, order.client_id)
    return await emit(
        db,
        alert_type=ALERT_NEW_CONTRACTOR_DRAFT,
        user_ids=user_ids,
        client_id=order.client_id,
        entity_key=f"order:{order.id}",
        title=f"Nowy kontraktor u {client_name} — uzupełnij zamówienie",
        message=(
            f"Nowy kontraktor {candidate_name} — umowa podpisana obustronnie. "
            f"Uzupełnij: {', '.join(missing)}."
        ),
        link=f"/clients/{order.client_id}?tab=zamowienia&order={order.id}",
        payload={
            "candidate_name": candidate_name,
            "missing_fields": missing,
            "source": "b2b_generator",
        },
        order_id=order.id,
        repeat_every_days=settings.DL_ALERT_REPEAT_DAYS,
        now=now,
    )


# ── Mail z progów ───────────────────────────────────────────────────────────

_EMAIL_CLAIM_STALE_MIN = 30
_EMAIL_BATCH = 200


async def send_pending_alert_emails(db: AsyncSession) -> int:
    """Wyślij maile dla wierszy z ``payload.email=true``. Zwraca liczbę wysłanych.

    Claim → wysyłka → stempel, jak w ``job_deadline_alerts``: dwa równoległe
    przebiegi (deploy) nie wyślą tego samego maila dwa razy. Odbiorca jest
    sprawdzany PONOWNIE (aktywne konto, nadal odbiorca spraw klienta) — mail
    niesie nazwisko kontraktora, a przypisanie mogło zniknąć od emisji.
    Wiersz już zamknięty (odhaczony / rozwiązany) nie dostaje maila.
    """
    if not (settings.DL_ALERTS_ENABLED and settings.DL_ALERT_EMAIL_ENABLED):
        return 0
    from sqlalchemy import or_

    from app.services.email import email_channel_enabled, send_email
    from app.services.notification_delivery import guarded_send, load_policy
    from app.services.m365.system_mail import (
        get_system_sender_connection,
        send_system_email,
    )

    policy = await load_policy(db)
    if not policy.kind_enabled("delivery_alert"):
        return 0
    connection = await get_system_sender_connection(db)
    if connection is None and not email_channel_enabled():
        return 0

    stale_cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=_EMAIL_CLAIM_STALE_MIN
    )
    rows = (
        await db.execute(
            select(DlAlert, User)
            .join(User, User.id == DlAlert.user_id)
            .where(
                DlAlert.status == DL_ALERT_STATUS_NEW,
                DlAlert.email_sent_at.is_(None),
                DlAlert.created_at >= policy.cutoff_for("delivery_alert"),
                DlAlert.payload["email"].as_boolean().is_(True),
                or_(
                    DlAlert.email_send_started_at.is_(None),
                    DlAlert.email_send_started_at <= stale_cutoff,
                ),
                User.is_active.is_(True),
                # Bez adresu nie ma czego wysłać — takie wiersze nie mogą
                # zająć paczki i zagłodzić kolejki.
                User.email.isnot(None),
                User.email != "",
            )
            .order_by(DlAlert.created_at.asc())
            .limit(_EMAIL_BATCH)
        )
    ).all()
    if not rows:
        return 0

    scope = await load_delivery_alert_recipient_scope(db)
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    sent = 0
    for alert, user in rows:
        alert_id = alert.id
        if not user.email or alert.user_id not in scope.for_client(alert.client_id):
            continue
        claimed = await db.execute(
            update(DlAlert)
            .where(
                DlAlert.id == alert_id,
                # Odhaczona albo zamknięta w międzyczasie — bez maila.
                DlAlert.status == DL_ALERT_STATUS_NEW,
                DlAlert.email_sent_at.is_(None),
                or_(
                    DlAlert.email_send_started_at.is_(None),
                    DlAlert.email_send_started_at <= stale_cutoff,
                ),
            )
            .values(email_send_started_at=func.now())
            .returning(DlAlert.id)
        )
        won = claimed.scalar_one_or_none() is not None
        await db.commit()
        if not won:
            continue

        link = f"{base}{alert.link}" if base and alert.link else (alert.link or "/")
        subject = f"[Nexus] {alert.title}"
        text_body = (
            f"Cześć {user.name or user.email},\n\n"
            f"{alert.message}\n\n"
            f"Otwórz w Nexusie: {link}\n\n"
            "Powiadomienie z panelu „Moi klienci”. Odhacz je w panelu, gdy "
            "sprawa jest załatwiona — przypomnienia przestaną przychodzić.\n\n"
            "— Nexus ATS"
        )
        ok = False
        try:
            if not (await load_policy(db)).allows("delivery_alert", alert.created_at):
                await db.execute(
                    update(DlAlert)
                    .where(DlAlert.id == alert_id)
                    .values(email_send_started_at=None)
                )
                await db.commit()
                continue
            if connection is not None:
                ok = await send_system_email(
                    db,
                    connection,
                    to=user.email,
                    subject=subject,
                    text_body=text_body,
                    delivery_kind="delivery_alert",
                    event_at=alert.created_at,
                )
            else:
                ok = await asyncio.to_thread(
                    guarded_send,
                    "delivery_alert",
                    alert.created_at,
                    send_email,
                    user.email,
                    subject,
                    text_body,
                    None,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "dl_alerts email failed alert=%d: %s", alert_id, type(exc).__name__
            )
        await db.execute(
            update(DlAlert)
            .where(DlAlert.id == alert_id)
            .values(
                email_sent_at=func.now() if ok else None,
                email_send_started_at=func.now() if ok else None,
            )
        )
        await db.commit()
        if ok:
            sent += 1
    return sent
