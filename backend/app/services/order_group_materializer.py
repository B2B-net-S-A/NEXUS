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
from app.models.contract import Contract, RateUnit
from app.models.order_type import OrderType
from app.services.client_order_lines import record_event, recompute_remaining
from app.services.cost_orders import skips_standard_order_group_materialization
from app.services.fx_service import rates_to_pln
from app.services.multi_consultant_orders import (
    EVENT_CONSULTANT_ADDED,
    format_md,
    is_multi_consultant_client,
)
from app.services.order_rate_snapshots import convert_order_rate
from app.services.order_types import effective_standalone_order_type

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


#: ``client_orders.rate_client`` / ``rate_candidate`` = Numeric(12, 3).
_ORDER_RATE_MAX = Decimal("999999999.999")


def _assert_fits_order_rate_column(value: Optional[Decimal], label: str) -> None:
    """Odmów PRZED zapisem, gdy stawka nie mieści się w kolumnie zamówienia.

    ``ValueError`` — jak każda inna odmowa w tym module. Wołający
    (``_materialize_group_after_activation``) zamienia go na 422 z tą treścią;
    gdyby poleciał dalej, wpadłby w ``UnhandledErrorMiddleware`` i użytkownik
    zobaczyłby ogólne „nieoczekiwany błąd serwera" zamiast nazwy pola do
    poprawienia. Serwis NIE rzuca ``HTTPException`` sam: nie importuje FastAPI
    i jest wołany także spoza warstwy HTTP.
    """

    if value is None:
        return
    if abs(Decimal(str(value))) > _ORDER_RATE_MAX:
        raise ValueError(
            f"Stawka {label} ({value}) przekracza zakres pola zamówienia — "
            "popraw kwotę przed aktywacją."
        )


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
    raw_order_type = getattr(order, "order_type", None)
    effective_type = effective_standalone_order_type(order.client_id, raw_order_type)
    if effective_type == OrderType.periodic:
        return None
    explicit_type = OrderType(raw_order_type) if raw_order_type is not None else None
    if explicit_type is None:
        # Pełna zgodność wsteczna: tylko stare, skonfigurowane klienty MD są
        # materializowane automatycznie i zachowują wszystkie dawne bramki.
        if not is_multi_consultant_client(order.client_id):
            return None
        if skips_standard_order_group_materialization(order.client_id):
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

    compatible_type = (
        ClientOrderGroup.order_type.is_(None)
        if explicit_type is None
        else ClientOrderGroup.order_type == explicit_type.value
    )
    group = await db.scalar(
        select(ClientOrderGroup)
        .where(
            ClientOrderGroup.client_id == order.client_id,
            ClientOrderGroup.order_number == number,
            compatible_type,
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
        cost_budget = (
            Decimal(str(order.total_value or 0))
            if explicit_type == OrderType.cost
            else None
        )
        md_budget = (
            Decimal(str(order.md_total or 0)) if explicit_type == OrderType.md else None
        )
        if explicit_type == OrderType.cost and cost_budget <= 0:
            raise ValueError("Zamówienie kosztowe wymaga budżetu całkowitego")
        if explicit_type == OrderType.md and md_budget <= 0:
            raise ValueError("Zamówienie na MD wymaga budżetu w MD")
        group = ClientOrderGroup(
            client_id=order.client_id,
            order_number=number,
            # start_date grupy jest NOT NULL; bramka aktywacji gwarantuje datę
            # startu na zamówieniu, więc fallback nie ma prawa się wykonać —
            # zostaje wyłącznie jako obrona przed wywołaniem poza ścieżką.
            start_date=start_date,
            end_date=end_date,
            status=GROUP_STATUS_ACTIVE,
            order_type=(explicit_type.value if explicit_type is not None else None),
            is_cost_based=explicit_type == OrderType.cost,
            budget_amount=cost_budget,
            budget_remaining=cost_budget,
            is_md_budget_based=explicit_type == OrderType.md,
            md_budget_total=md_budget,
            md_budget_remaining=md_budget,
            created_by_user_id=actor_id,
        )
        db.add(group)
        await db.flush()
    elif explicit_type == OrderType.cost:
        supplied = Decimal(str(order.total_value or 0))
        if supplied > 0 and supplied != Decimal(str(group.budget_amount or 0)):
            raise ValueError(
                "Budżet kosztowy różni się od istniejącego zamówienia o tym numerze"
            )
    elif explicit_type == OrderType.md:
        supplied = Decimal(str(order.md_total or 0))
        if supplied > 0 and supplied != Decimal(str(group.md_budget_total or 0)):
            raise ValueError(
                "Budżet MD różni się od istniejącego zamówienia o tym numerze"
            )

    who = await _consultant_name(db, order)
    order.order_group_id = group.id
    order.order_type = group.order_type
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
    unit = order.rate_unit or (
        order.contract.rate_unit if order.contract is not None else RateUnit.monthly
    )
    client_currency = (
        order.rate_client_currency
        or order.currency
        or (
            order.contract.resolved_rate_client_currency
            if order.contract is not None
            else "PLN"
        )
    ).upper()
    candidate_currency = (
        order.rate_candidate_currency
        or (
            order.contract.resolved_rate_candidate_currency
            if order.contract is not None
            else "PLN"
        )
    ).upper()
    fx = await rates_to_pln(
        db,
        {client_currency, candidate_currency},
        order.start_date or business_today(),
    )

    def canonical_pln_md(value: Optional[Decimal], currency: str) -> Optional[Decimal]:
        if value is None:
            return None
        rate_to_pln = fx.get(currency)
        if rate_to_pln is None:
            raise ValueError(
                f"Brak kursu {currency}/PLN potrzebnego do zapisania stawki linii"
            )
        per_md = convert_order_rate(
            value,
            unit,
            RateUnit.daily,
            order.billing_hours_per_month or 160,
        )
        if per_md is None:
            return None
        return md_rate_from_order_rate(per_md * rate_to_pln)

    if explicit_type in (OrderType.cost, OrderType.md):
        # Explicit drafts carry their true unit/currencies as an order
        # snapshot.  ``md_rate_revenue`` may already contain a temporary
        # mirror required by the standalone MD coherence check; that mirror is
        # still in the source unit/currency and must never be relabelled as
        # PLN/MD.  Materialization is the canonicalization boundary, so always
        # overwrite both mirrors here.
        order.md_rate_revenue = (
            canonical_pln_md(order.rate_client, client_currency)
            if order.rate_client is not None and order.rate_client > 0
            else None
        )
        order.md_rate_cost = (
            canonical_pln_md(candidate_rate, candidate_currency)
            if candidate_rate is not None
            else None
        )
    else:
        # Legacy client-specific lines were already maintained in canonical
        # PLN/MD. Preserve a populated historical mirror and fill only gaps.
        if (
            order.md_rate_revenue is None
            and order.rate_client is not None
            and order.rate_client > 0
        ):
            order.md_rate_revenue = canonical_pln_md(order.rate_client, client_currency)
        if order.md_rate_cost is None and candidate_rate is not None:
            order.md_rate_cost = canonical_pln_md(candidate_rate, candidate_currency)

    # Od tej chwili rekord jest linią grupową, której kanoniczną jednostką jest
    # PLN/MD. Zachowanie surowych warunków wejściowych należy do eventu/grupy;
    # relabeling bez konwersji był dotychczas źródłem błędu ×8 i EUR→PLN.
    #
    # Kolumny są WĘŻSZE po stronie zamówienia niż po stronie linii MD:
    # ``md_rate_*`` to Numeric(12,2) (10 cyfr całkowitych), a ``rate_*``
    # Numeric(12,3) (9 cyfr). Przepisanie bez sprawdzenia zakresu kończyło się
    # ``NumericValueOutOfRangeError`` przy commicie, czyli 500 bez nagłówków
    # CORS — u użytkownika „Network Error" w środku aktywacji zamówienia.
    _assert_fits_order_rate_column(order.md_rate_cost, "kosztowa")
    _assert_fits_order_rate_column(order.md_rate_revenue, "przychodowa")
    order.rate_candidate = order.md_rate_cost
    order.rate_client = order.md_rate_revenue
    order.rate_unit = RateUnit.daily
    order.billing_hours_per_month = 160
    order.currency = "PLN"
    order.rate_client_currency = "PLN"
    order.rate_candidate_currency = "PLN"
    if explicit_type in (OrderType.cost, OrderType.md):
        # Budżet jest wspólny na grupie; pozostawienie jego kopii na linii
        # stworzyłoby dwa niezależne liczniki i pozwoliło mieszać typy.
        order.total_value = None
        order.md_input_mode = None
        order.md_input_value = None
        order.md_total = None
        order.md_remaining = None
        order.md_manual_adjustment = Decimal("0")
    else:
        await recompute_remaining(db, order)

    if group.is_cost_based:
        budget_note = f", wspólny budżet {group.budget_amount} PLN"
    elif group.is_md_budget_based:
        budget_note = f", wspólny budżet {format_md(group.md_budget_total)} MD"
    else:
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
