"""Materializacja grupy dla aktywowanego szkicu u klienta wielo-konsultantowego.

U klientów z ``MULTI_CONSULTANT_ORDER_CLIENT_IDS`` zakładka „Zamówienia"
renderuje wyłącznie GRUPY (``client_order_groups``) z liniami konsultantów —
samodzielny ``ClientOrder`` bez ``order_group_id`` jest tam niewidzialny.
Szkice z hooka zatrudnienia („Oznacz jako podpisane" / pipeline „hired")
powstają właśnie jako samodzielne wiersze, więc uzupełniony i aktywowany szkic
znikałby z Draftu i NIE pojawiał się w Aktywnych — dokładnie ta sama klasa
awarii, którą naprawiał ticket („uzupełnienie czterech pól nie daje żadnego
widocznego skutku").

Stąd materializacja: w chwili aktywacji szkic staje się linią grupy o numerze
z pola „numer zamówienia". Grupa o tym numerze już istnieje (aktywna lub
zaplanowana) → dołączamy linię do niej (BIK prowadzi grupy wieloosobowe);
nie istnieje → powstaje nowa. Dzięki temu import zużycia MD
(``active_md_lines`` wymaga ``order_group_id``), alert ``ALERT_MD_BUDGET_LOW``
(JOIN po aktywnej grupie), eksport XLSX i cały cykl życia grup działają na tych
zamówieniach bez żadnych zmian po swojej stronie.

Grupa z materializacji jest ZAWSZE ``active``, świadomie inaczej niż
``_initial_group_status`` przy ręcznym tworzeniu (przyszły start → scheduled):
aktywacja szkicu realizuje semantykę Ticketu 1 — „komplet pól = Aktywne",
niezależnie od daty startu (widok jednoosobowy też nie odracza aktywacji).
Grupa ``scheduled`` chowałaby świeżo uzupełnione zamówienie przed pigułką
„Aktywne" i trzymała aktywną linię w zaplanowanej grupie, czego model grup
zabrania w każdym innym miejscu (``add_line`` w scheduled tworzy linie draft).

Zamówień KOSZTOWYCH ta ścieżka nie dotyczy: u klientów z
``COST_ORDER_CLIENT_IDS`` (Polkomtel) hook zatrudnienia w ogóle nie tworzy
szkicu (`should_auto_create_order`), a zamówienie — z wyborem typu — zakłada
Delivery Lead ręcznie przez „Nowy kontraktor / zamówienie".
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
from app.models.contract import Contract
from app.services.client_order_lines import record_event, recompute_remaining
from app.services.cost_orders import is_cost_order_client
from app.services.multi_consultant_orders import (
    EVENT_CONSULTANT_ADDED,
    format_md,
    is_multi_consultant_client,
)

_PLACEHOLDER_TITLE = "(bez numeru)"


def md_rate_from_order_rate(rate: Optional[Decimal]) -> Optional[Decimal]:
    """Stawka zamówienia (Numeric 12,3) → stawka linii MD (Numeric 12,2).

    Kolumny ``md_rate_*`` mają 2 miejsca po przecinku, a ``rate_client``
    trzy (Alior 164.375 — migracja 0149). Kwantyzacja jest tu JAWNA, żeby
    ewentualna utrata trzeciego miejsca była decyzją tego modułu, a nie cichym
    przycięciem w bazie. U klientów MD stawki są całkowitozłotowe, więc w
    praktyce różnica nie występuje.
    """
    if rate is None:
        return None
    return Decimal(str(rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def group_number_from_order(order: ClientOrder) -> Optional[str]:
    """Numer grupy z pola „numer zamówienia" szkicu; ``None`` gdy placeholder.

    Bramka aktywacji (`_order_has_required_activation_data`) gwarantuje
    niepusty, nie-placeholderowy tytuł, więc ``None`` zdarza się wyłącznie przy
    wywołaniu poza ścieżką aktywacji — wtedy materializacja jest po prostu
    pomijana, zamiast zakładać grupę o numerze „(bez numeru)".
    """
    number = (order.title or "").strip()
    if not number or number == _PLACEHOLDER_TITLE:
        return None
    return number[:64]


async def materialize_group_for_activated_order(
    db: AsyncSession,
    order: ClientOrder,
    *,
    actor_id: Optional[int],
    candidate_rate: Optional[Decimal],
) -> Optional[ClientOrderGroup]:
    """Przypnij świeżo aktywowany, samodzielny szkic do grupy zamówień.

    Zwraca grupę (istniejącą albo nową) lub ``None``, gdy zamówienie nie
    podlega materializacji. ``candidate_rate`` przychodzi parametrem, bo
    efektywną stawkę kosztową liczy warstwa API (`_activation_candidate_rate`
    zna regułę „harmonogram jest prawdą"), a serwis nie może importować z API.

    Wołający odpowiada za ``db.commit()``.
    """
    if order.status != ClientOrderStatus.active:
        return None
    if order.order_group_id is not None:
        return None
    if not is_multi_consultant_client(order.client_id):
        return None
    if is_cost_order_client(order.client_id):
        return None
    number = group_number_from_order(order)
    if number is None:
        return None

    # Advisory lock per (klient, numer) na czas transakcji: dwa równoległe
    # PATCHe kompletujące szkice z tym samym numerem widziałyby oba
    # ``group is None`` i każdy założyłby własną grupę — numer jest celowo
    # bez UNIQUE, więc baza by tego nie zatrzymała, a w rejestrze zostałaby
    # pusta, aktywna grupa-dubel. Lock zwalnia się przy commit/rollback;
    # drugi wątek po odblokowaniu widzi już grupę pierwszego.
    await db.scalar(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"order-group:{order.client_id}:{number}", 0)
            )
        )
    )

    group = await db.scalar(
        select(ClientOrderGroup)
        .where(
            ClientOrderGroup.client_id == order.client_id,
            ClientOrderGroup.order_number == number,
            # WYŁĄCZNIE grupy aktywne: dołączenie aktywnej linii do grupy
            # ``scheduled`` łamałoby kontrakt modułu (add_line w scheduled
            # tworzy linie draft), chowało zamówienie przed pigułką „Aktywne"
            # i przed alertem progu MD (JOIN po aktywnej grupie). Gdy pod tym
            # numerem istnieje tylko grupa zaplanowana, powstaje osobna grupa
            # aktywna — numer i tak jest celowo bez UNIQUE.
            ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
        )
        # Numer bywa reużywany w kolejnych latach (celowo bez UNIQUE w bazie);
        # przy dublach wybieramy najświeższą otwartą grupę.
        .order_by(ClientOrderGroup.id.desc())
        .limit(1)
    )
    group_created = group is None
    if group is None:
        start_date = order.start_date or business_today()
        end_date = order.end_date
        # `ck_client_order_groups_dates` wymaga end >= start, a zamówienie
        # takiej walidacji nigdy nie miało (InlinePeriod pozwala zapisać
        # do < od). Niespójną datę końcową grupa dostaje jako „bezterminowo"
        # zamiast IntegrityError w środku aktywacji — daty zamówienia zostają
        # nietknięte i są do poprawienia w wierszu.
        if end_date is not None and end_date < start_date:
            end_date = None
        group = ClientOrderGroup(
            client_id=order.client_id,
            order_number=number,
            # start_date grupy jest NOT NULL; bramka aktywacji gwarantuje datę
            # startu na zamówieniu, więc fallback nie ma prawa się wykonać —
            # zostaje wyłącznie jako obrona przed wywołaniem poza ścieżką.
            start_date=start_date,
            end_date=end_date,
            status=GROUP_STATUS_ACTIVE,
            is_cost_based=False,
            created_by_user_id=actor_id,
        )
        db.add(group)
        await db.flush()

    who = await _consultant_name(db, order)
    order.order_group_id = group.id
    # Tytuł linii przechodzi na konwencję grup („Zamówienie NR — osoba"):
    # numer mieszka odtąd na grupie, a osierocona kiedyś linia (usunięcie
    # grupy odpina, nie kasuje) zachowuje czytelny ślad numeru w tytule.
    order.title = f"Zamówienie {number} — {who or 'konsultant'}"[:255]
    # Lustro stawek do kolumn linii MD: odczyty grup (`rate_cost`/`rate_revenue`),
    # alert „brak stawki przychodowej" i zamiana kontraktora czytają md_rate_*,
    # nie rate_client/kontrakt. Bez lustra aktywna linia z wypełnioną stawką
    # dostawałaby cotygodniowy alert o jej braku. Stawka zerowa NIE wchodzi
    # do lustra: `ck_client_orders_md_coherence` żąda md_rate_revenue > 0
    # także bez budżetu, więc zero dałoby IntegrityError w środku aktywacji.
    if (
        order.md_rate_revenue is None
        and order.rate_client is not None
        and order.rate_client > 0
    ):
        order.md_rate_revenue = md_rate_from_order_rate(order.rate_client)
    if order.md_rate_cost is None and candidate_rate is not None:
        order.md_rate_cost = md_rate_from_order_rate(candidate_rate)
    await recompute_remaining(db, order)

    budget_note = (
        f", budżet {format_md(order.md_total)} MD"
        if order.md_total is not None
        else ", budżet MD do uzupełnienia"
    )
    record_event(
        db,
        group_id=group.id,
        order_id=order.id,
        event_type=EVENT_CONSULTANT_ADDED,
        description=(
            f"{who or 'Konsultant'} — przypisano automatycznie po uzupełnieniu "
            f"szkicu zamówienia{budget_note}"
            + (" (utworzono nowe zamówienie)" if group_created else "")
        ),
        payload={
            "consultant": who,
            "source": "draft_completion",
            "rate_cost": (
                str(order.md_rate_cost) if order.md_rate_cost is not None else None
            ),
            "rate_revenue": (
                str(order.md_rate_revenue)
                if order.md_rate_revenue is not None
                else None
            ),
            "md_total": str(order.md_total) if order.md_total is not None else None,
            "group_created": group_created,
        },
        user_id=actor_id,
    )
    return group


async def _consultant_name(db: AsyncSession, order: ClientOrder) -> str:
    """Imię i nazwisko przez JAWNE zapytanie, nie relację.

    Ścieżki wołające materializer ładują kontrakt z harmonogramem stawek, ale
    bez kandydata — ``order.contract.candidate`` byłby w sesji async leniwym
    doczytaniem, czyli ``MissingGreenlet`` (HTTP 500 bez nagłówków CORS).
    """
    row = await db.scalar(
        select(Candidate)
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(Contract.id == order.contract_id)
    )
    if row is None:
        return ""
    return f"{row.name or ''} {row.lastname or ''}".strip()
