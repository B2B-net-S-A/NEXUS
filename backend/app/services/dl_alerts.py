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
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
from app.models.dl_alert import (
    ALERT_COST_ORDER_EXHAUSTED,
    ALERT_MD_CONSULTANT_ENDED,
    DL_ALERT_STATUS_HANDLED,
    DL_ALERT_STATUS_NEW,
    DlAlert,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services.client_identity import client_display_name_expression
from app.services.multi_consultant_orders import EVENT_BUDGET_EXHAUSTED


async def dl_user_ids_for_client(db: AsyncSession, client_id: int) -> list[int]:
    """Delivery Leadzi przypisani do klienta — odbiorcy alertów.

    Jeden warunek daje tyle wierszy, ilu DL jest przypisanych. Raport ma
    odpowiadać na pytanie „ile spraw KTO zignorował", a nie „ile było
    zdarzeń", więc alert nie może być współdzielony.
    """
    res = await db.execute(
        select(DeliveryLeadClientAssignment.delivery_lead_user_id).where(
            DeliveryLeadClientAssignment.client_id == client_id
        )
    )
    return sorted({row[0] for row in res.all()})


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


async def _first_seen_and_handled(
    db: AsyncSession, *, alert_type: str, user_id: int, entity_key: str
) -> tuple[Optional[datetime], bool]:
    """(data pierwszego alertu tej sprawy, czy którykolwiek obsłużony)."""
    prefix = f"{alert_type}:{entity_key}:{user_id}:"
    res = await db.execute(
        select(DlAlert.created_at, DlAlert.status)
        # `autoescape` obowiązkowo: typy alertów zawierają `_`, który w LIKE
        # jest wieloznacznikiem „dowolny znak" — bez escapowania prefiks jednej
        # sprawy trafiałby w sąsiednie.
        .where(DlAlert.dedupe_key.startswith(prefix, autoescape=True))
        .order_by(DlAlert.created_at.asc())
    )
    rows = res.all()
    if not rows:
        return None, False
    handled = any(status == DL_ALERT_STATUS_HANDLED for _, status in rows)
    return rows[0][0], handled


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
    now: Optional[datetime] = None,
) -> list[DlAlert]:
    """Wystaw alert każdemu wskazanemu odbiorcy. Zwraca faktycznie utworzone.

    ``repeat_every_days=None`` = alert jednorazowy (klucz bez okna); tak działa
    wyczerpanie budżetu, bo samo zdarzenie jest jednorazowe.

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

    for user_id in user_ids:
        first_seen, handled = await _first_seen_and_handled(
            db, alert_type=alert_type, user_id=user_id, entity_key=entity_key
        )
        if handled:
            continue

        if repeat_every_days is None:
            window = "once"
        else:
            window = str(
                repeat_window(
                    first_seen or moment, moment, every_days=repeat_every_days
                )
            )
        dedupe_key = f"{alert_type}:{entity_key}:{user_id}:{window}"

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
                payload=payload,
                dedupe_key=dedupe_key[:255],
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
    """Alert o wyczerpaniu budżetu zamówienia kosztowego.

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
    przejście ``active → exhausted`` (obie ścieżki emisji zapisują je przed
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
            "wyczerpane i przeniesione do zakończonych. Sprawdź rozliczenie "
            "i zorganizuj nowe zamówienie."
        ),
        link=f"/clients/{group.client_id}?tab=zamowienia",
        payload={"order_number": group.order_number},
        order_group_id=group.id,
        repeat_every_days=None,
    )


def reaction_seconds(alert: DlAlert) -> Optional[int]:
    """Czas reakcji w sekundach albo ``None`` dla nieobsłużonych."""
    if alert.handled_at is None:
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
