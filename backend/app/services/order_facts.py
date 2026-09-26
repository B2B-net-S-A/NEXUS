"""Wspólny odczyt zamówień dla Finanse → Zmiany w zamówieniach i Braków.

Jedno miejsce odpowiada na trzy pytania, które zadają obie powierzchnie:

* jaki jest EFEKTYWNY okres zamówienia — linia zamówienia MD/kosztowego zwykle
  nie niesie własnych dat, więc okres to ``COALESCE(linia, grupa)`` (ta sama
  reguła co eksport Excela zamówień);
* czy osoba ma u tego klienta NASTĘPNE zamówienie po końcu danego;
* czy koniec był ŚWIADOMY (wypowiedziana umowa, decyzja offboardingu MD,
  zamiana kontraktora, „zostaw jako historię") — wtedy brak następcy nie jest
  zaniedbaniem Delivery Leada.

Podzakładka „Zejścia" i detektor Braków czytają tę samą regułę następcy: dwie
kopie rozjechałyby się tak, że Zejście mówi „brak następcy", a Braki milczą.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Date,
    Select,
    and_,
    case,
    cast,
    func,
    literal_column,
    or_,
    select,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
from app.models.client_order_offboarding import (
    OFFBOARDING_RESOLUTION_REMOVE,
    OFFBOARDING_RESOLUTION_TRANSFER,
    ClientOrderOffboardingCase,
)
from app.models.contract import Contract, ContractStatus
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.md_consumption import ClientOrderMdConsumption
from app.services.client_identity import client_display_name_expression
from app.services.multi_consultant_orders import (
    EVENT_CONSULTANT_ENDED,
    LINE_DECISION_KEEP_HISTORY,
    LINE_DECISION_REMOVED,
)
from app.services.order_types import legacy_null_order_type

MD_UNIT = "md"

INTENT_CONTRACT_ENDED = "contract_ended"
INTENT_REPLACED = "replaced"
INTENT_MD_OFFBOARDING = "md_offboarding"
INTENT_REMOVED_FROM_ORDER = "removed_from_order"
INTENT_KEEP_HISTORY = "keep_history"

INTENT_LABELS: dict[str, str] = {
    INTENT_CONTRACT_ENDED: "Współpraca zakończona (umowa wypowiedziana)",
    INTENT_REPLACED: "Zastąpiony innym konsultantem na zamówieniu",
    INTENT_MD_OFFBOARDING: "Decyzja DL po zakończeniu współpracy (MD)",
    INTENT_REMOVED_FROM_ORDER: "Usunięty z zamówienia",
    INTENT_KEEP_HISTORY: "Zostawiony na zamówieniu jako historia",
}


@dataclass(frozen=True)
class OrderFact:
    order_id: int
    order_group_id: Optional[int]
    contract_id: int
    candidate_id: Optional[int]
    client_id: int
    client_name: str
    consultant_name: str
    status: str
    start: Optional[date]
    end: Optional[date]
    number: str
    order_type: str
    rate_cost: Optional[Decimal]
    rate_revenue: Optional[Decimal]
    rate_unit: Optional[str]
    currency: Optional[str]
    created_at: datetime
    md_total: Optional[Decimal] = None
    md_remaining: Optional[Decimal] = None

    @property
    def is_cancelled(self) -> bool:
        return self.status == ClientOrderStatus.cancelled.value

    @property
    def is_draft(self) -> bool:
        return self.status == ClientOrderStatus.draft.value

    @property
    def works_until_md_exhausted(self) -> bool:
        """Aktywna linia MD z budżetem — pracuje po dacie końca, do wyczerpania.

        Skaner wygasania celowo NIE kończy takich linii po dacie
        (``_promote_statuses``), a następna grupa czeka, aż poprzednia zużyje
        MD. Traktowanie daty jako końca dawałoby fałszywe braki i „do usunięcia
        z rozliczeń" przy kimś, kto nadal rozlicza dni.

        WYŁĄCZNIE linia zamówienia MD/kosztowego (``order_group_id``) — lustro
        poprawki M10 w ``order_continuation``. Samodzielne zamówienie okresowe
        z ``md_total`` kończy się datą (skaner je domyka), a jego „pozostałe
        MD” nie maleją, bo nie rozlicza go import MD (audyt 25.09.2026).
        """
        return (
            self.status == ClientOrderStatus.active.value
            and self.order_group_id is not None
            and self.md_total is not None
            and (self.md_remaining or Decimal("0")) > 0
        )


def _value(raw: object) -> object:
    return getattr(raw, "value", raw)


def effective_start_expr():
    return func.coalesce(ClientOrder.start_date, ClientOrderGroup.start_date)


def effective_end_expr():
    return func.coalesce(ClientOrder.end_date, ClientOrderGroup.end_date)


def exhaustion_end_expr():
    """Ostatni dzień miesiąca ostatniego zejścia MD linii (``NULL`` bez zejść).

    Linię MD kończy budżet, nie kalendarz: ``sync_md_line_status`` stawia
    ``completed`` przy wyczerpaniu i NIE zapisuje daty końca — zapis daty
    zablokowałby wskrzeszenie linii po korekcie budżetu. Dzień wyczerpania
    wynika więc z dziennika zużycia: udział kończy się w miesiącu, którego
    raport zjadł ostatnie MD.
    """

    last_month = (
        select(func.max(ClientOrderMdConsumption.period_month))
        .where(
            ClientOrderMdConsumption.order_id == ClientOrder.id,
            ClientOrderMdConsumption.md_reported > 0,
        )
        .correlate(ClientOrder)
        .scalar_subquery()
    )
    return cast(
        func.to_date(last_month, "YYYY-MM")
        + literal_column("INTERVAL '1 month'")
        - literal_column("INTERVAL '1 day'"),
        Date,
    )


def participation_end_expr():
    """Koniec UDZIAŁU osoby w zamówieniu — okres dla Zejść, Kończących i Braków.

    Zwykle to ``effective_end_expr`` (``COALESCE(linia, grupa)``). Wyjątek:
    linia MD zakończona WYCZERPANIEM budżetu (``completed``, bez własnej daty,
    ``md_remaining`` ≤ 0) kończy się w miesiącu ostatniego zejścia MD, a nie
    z datą grupy. Bez tego taka linia nie trafiała do Braków (grupa bez daty
    końca) albo lądowała w Zejściach w złym miesiącu (data grupy) — runda 6
    audytu. Aktywna linia z niewyczerpanym budżetem nie jest tu ruszana: ona
    nadal pracuje po dacie (``works_until_md_exhausted``). Okres DOKUMENTU
    (Zamówienia PDF, nagłówek karty) zostaje przy ``effective_end_expr``.
    """

    exhausted = and_(
        ClientOrder.end_date.is_(None),
        ClientOrder.order_group_id.is_not(None),
        ClientOrder.md_total.is_not(None),
        ClientOrder.status == ClientOrderStatus.completed,
        func.coalesce(ClientOrder.md_remaining, 0) <= 0,
    )
    return case(
        (exhausted, func.coalesce(exhaustion_end_expr(), effective_end_expr())),
        else_=effective_end_expr(),
    )


def order_facts_select() -> Select:
    """Kolumny jednego zamówienia z okresem, osobą, klientem i stawkami."""

    return (
        select(
            ClientOrder.id,
            ClientOrder.order_group_id,
            ClientOrder.contract_id,
            Contract.candidate_id,
            ClientOrder.client_id,
            client_display_name_expression().label("client_name"),
            Candidate.name.label("candidate_first"),
            Candidate.lastname.label("candidate_last"),
            ClientOrder.status,
            effective_start_expr().label("eff_start"),
            participation_end_expr().label("eff_end"),
            ClientOrder.title,
            ClientOrderGroup.order_number,
            ClientOrder.order_type,
            ClientOrderGroup.order_type.label("group_order_type"),
            ClientOrderGroup.is_cost_based,
            ClientOrder.rate_candidate,
            ClientOrder.rate_client,
            ClientOrder.md_rate_cost,
            ClientOrder.md_rate_revenue,
            ClientOrder.rate_unit,
            ClientOrder.rate_candidate_currency,
            ClientOrder.rate_client_currency,
            ClientOrder.currency,
            ClientOrder.created_at,
            ClientOrder.md_total,
            ClientOrder.md_remaining,
        )
        .select_from(ClientOrder)
        .join(Contract, Contract.id == ClientOrder.contract_id)
        .join(Client, Client.id == ClientOrder.client_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
    )


def fact_from_row(row) -> OrderFact:
    in_group = row.order_group_id is not None
    if in_group:
        if row.group_order_type is not None:
            order_type = str(row.group_order_type)
        else:
            order_type = "cost" if row.is_cost_based else "md"
        number = row.order_number or row.title or "—"
    else:
        raw_type = _value(row.order_type)
        order_type = (
            str(raw_type)
            if raw_type is not None
            else legacy_null_order_type(row.client_id).value
        )
        number = row.title or "—"

    line_currency = (
        row.rate_client_currency or row.rate_candidate_currency or row.currency or "PLN"
    )
    # ``md_rate_*`` to kanoniczne PLN/MD. Linia w walucie obcej ma stawki
    # źródłowe w ``rate_*`` (waluta i jednostka linii) — tak pokazuje je karta
    # zamówienia; „PLN" przy kwocie przeliczonej z EUR mylił Finanse (S14).
    if (
        in_group
        and str(line_currency).strip().upper() == "PLN"
        and (row.md_rate_cost is not None or row.md_rate_revenue is not None)
    ):
        rate_cost, rate_revenue, unit, currency = (
            row.md_rate_cost,
            row.md_rate_revenue,
            MD_UNIT,
            "PLN",
        )
    else:
        rate_cost, rate_revenue = row.rate_candidate, row.rate_client
        unit = _value(row.rate_unit)
        currency = (
            row.rate_client_currency or row.rate_candidate_currency or row.currency
        )
    name = f"{row.candidate_first or ''} {row.candidate_last or ''}".strip() or "—"
    return OrderFact(
        order_id=row.id,
        order_group_id=row.order_group_id,
        contract_id=row.contract_id,
        candidate_id=row.candidate_id,
        client_id=row.client_id,
        client_name=row.client_name or "—",
        consultant_name=name,
        status=str(_value(row.status)),
        start=row.eff_start,
        end=row.eff_end,
        number=number,
        order_type=order_type,
        rate_cost=rate_cost,
        rate_revenue=rate_revenue,
        rate_unit=str(unit) if unit is not None else None,
        currency=currency,
        created_at=row.created_at,
        md_total=row.md_total,
        md_remaining=row.md_remaining,
    )


async def load_facts(db: AsyncSession, *where) -> list[OrderFact]:
    rows = (await db.execute(order_facts_select().where(*where))).all()
    return [fact_from_row(row) for row in rows]


SiblingKey = tuple[str, int, int]


def sibling_key(fact: OrderFact) -> SiblingKey:
    """Klucz współpracy: (osoba, klient), a bez osoby — kontrakt.

    Osoba potrafi dostać nowy kontrakt u tego samego klienta, a to nadal jest
    kontynuacja współpracy. Kontrakt bez osoby nie może łączyć obcych ludzi,
    więc tam współpracą jest sam kontrakt.
    """
    if fact.candidate_id is None:
        return ("contract", fact.contract_id, fact.client_id)
    return ("person", fact.candidate_id, fact.client_id)


async def load_siblings(
    db: AsyncSession, facts: Iterable[OrderFact]
) -> dict[SiblingKey, list[OrderFact]]:
    """Wszystkie zamówienia tych samych współprac (patrz ``sibling_key``)."""

    facts = list(facts)
    people = sorted(
        {(f.candidate_id, f.client_id) for f in facts if f.candidate_id is not None}
    )
    orphan_contracts = sorted({f.contract_id for f in facts if f.candidate_id is None})
    rows: list[OrderFact] = []
    if people:
        rows.extend(
            await load_facts(
                db, tuple_(Contract.candidate_id, ClientOrder.client_id).in_(people)
            )
        )
    if orphan_contracts:
        rows.extend(
            await load_facts(
                db,
                Contract.candidate_id.is_(None),
                ClientOrder.contract_id.in_(orphan_contracts),
            )
        )
    grouped: dict[SiblingKey, list[OrderFact]] = {}
    for fact in rows:
        grouped.setdefault(sibling_key(fact), []).append(fact)
    return grouped


def siblings_of(
    fact: OrderFact, siblings: dict[SiblingKey, list[OrderFact]]
) -> list[OrderFact]:
    return siblings.get(sibling_key(fact), [])


def is_empty_open_draft(candidate: OrderFact) -> bool:
    """Porzucony szkic: bez daty końca i bez stawki przychodowej.

    Szkic z podpisu umowy (``b2b_contract_automation``) ma start umowy, pusty
    koniec i pustą stawkę klienta — do audytu 24.09.2026 (W2) liczył się jako
    następca KAŻDEGO zamówienia tej osoby, więc kończące się zamówienie nigdy
    nie trafiało do „Kończących się" ani alertów. Szkic uzupełniony (ze stawką
    albo datą końca) to nadal zaplanowana kontynuacja.
    """

    return (
        candidate.is_draft
        and candidate.end is None
        and (candidate.rate_revenue is None or candidate.rate_revenue <= 0)
    )


def covers_after(
    candidate: OrderFact, ended_on: date, *, today: Optional[date] = None
) -> bool:
    """Czy zamówienie trwa (albo zacznie się) po ``ended_on``.

    Zamówienie bez daty końca liczy się tylko, gdy nie jest zakończone —
    zakończony wiersz bez daty to historia, nie następca. Szkic się liczy
    (decyzja Artura 14.09: szkic następnego zamówienia = zaplanowane) — poza
    porzuconym szkicem (``is_empty_open_draft``). Zakończone zamówienie z datą
    końca PO dzisiejszym dniu też nie jest następcą: nikt go już nie wykona
    (N2, audyt 24.09.2026).
    """

    if candidate.is_cancelled:
        return False
    if candidate.works_until_md_exhausted:
        return True
    if is_empty_open_draft(candidate):
        return False
    if candidate.end is None:
        return candidate.status != ClientOrderStatus.completed.value
    if candidate.status == ClientOrderStatus.completed.value and candidate.end > (
        today or business_today()
    ):
        return False
    return candidate.end > ended_on


def successor_of(
    fact: OrderFact,
    siblings: Sequence[OrderFact],
    *,
    include_self: bool = False,
) -> Optional[OrderFact]:
    """Najwcześniej zaczynające się zamówienie tej osoby po końcu ``fact``."""

    if fact.end is None:
        return None
    found = [
        other
        for other in siblings
        if (include_self or other.order_id != fact.order_id)
        and covers_after(other, fact.end)
    ]
    if not found:
        return None
    return min(
        found,
        key=lambda other: (other.start or date.min, other.created_at, other.order_id),
    )


def previous_of(fact: OrderFact, siblings: Sequence[OrderFact]) -> Optional[OrderFact]:
    """Zamówienie tej osoby u klienta, które skończyło się tuż przed startem.

    „Kontynuacja" w Wejściach: poprzednie zamówienie skończyło się najwyżej
    31 dni przed startem tego (przerwa między zamówieniami bywa kilkudniowa,
    a miesiąc to granica, za którą wraca się „po przerwie").
    """

    if fact.start is None:
        return None
    window_start = fact.start - timedelta(days=31)
    found = [
        other
        for other in siblings
        if other.order_id != fact.order_id
        and not other.is_cancelled
        and other.end is not None
        and window_start <= other.end < fact.start
    ]
    if not found:
        return None
    return max(found, key=lambda other: (other.end, other.order_id))


def local_day_start(day: date) -> datetime:
    """Początek doby w Warszawie jako chwila UTC."""

    local = datetime.combine(day, time.min, tzinfo=ZoneInfo(DEFAULT_TZ))
    return local.astimezone(timezone.utc)


async def load_ending_intents(
    db: AsyncSession, facts: Sequence[OrderFact]
) -> dict[int, str]:
    """Zamówienia, których koniec był świadomą decyzją — z powodem."""

    if not facts:
        return {}
    by_id = {fact.order_id: fact for fact in facts}
    order_ids = sorted(by_id)
    contract_ids = sorted({fact.contract_id for fact in facts})
    intents: dict[int, str] = {}

    # Lustro warunku następcy w skanerze wygasania (``_promote_statuses``):
    # anulowana linia i szkic zaplanowanego „Wejdź za konsultanta” wskazują
    # poprzednika, ale nikogo nie zastąpiły — odchodzący pracuje do swojej
    # daty, a zastępstwo mogło zostać odwołane. Bez tych filtrów anulowane
    # zastępstwo robiło z osoby „zastąpioną” w Zejściach i gasiło jej Brak
    # (runda 6 audytu). Import leniwy, bo moduł zastępstw ciągnie za sobą
    # ścieżkę zapisu zamówień, która importuje Braki (a te — ten moduł).
    from app.services.order_line_takeover import scheduled_takeover_draft_clause

    successor = aliased(ClientOrder)
    replaced = await db.scalars(
        select(successor.predecessor_order_id).where(
            successor.predecessor_order_id.in_(order_ids),
            successor.status != ClientOrderStatus.cancelled,
            ~scheduled_takeover_draft_clause(successor),
        )
    )
    for order_id in replaced:
        intents.setdefault(order_id, INTENT_REPLACED)

    offboarding = await db.scalars(
        select(ClientOrderOffboardingCase.order_id).where(
            ClientOrderOffboardingCase.order_id.in_(order_ids),
            ClientOrderOffboardingCase.resolution.in_(
                (OFFBOARDING_RESOLUTION_REMOVE, OFFBOARDING_RESOLUTION_TRANSFER)
            ),
        )
    )
    for order_id in offboarding:
        intents.setdefault(order_id, INTENT_MD_OFFBOARDING)

    decisions = await db.execute(
        select(
            ClientOrderGroupEvent.order_id,
            ClientOrderGroupEvent.payload["reason"].astext,
        ).where(
            ClientOrderGroupEvent.order_id.in_(order_ids),
            ClientOrderGroupEvent.event_type == EVENT_CONSULTANT_ENDED,
            ClientOrderGroupEvent.payload["reason"].astext.in_(
                (LINE_DECISION_REMOVED, LINE_DECISION_KEEP_HISTORY)
            ),
        )
    )
    for order_id, reason in decisions.all():
        intents.setdefault(
            order_id,
            INTENT_REMOVED_FROM_ORDER
            if reason == LINE_DECISION_REMOVED
            else INTENT_KEEP_HISTORY,
        )

    contracts = await db.execute(
        select(
            Contract.id,
            Contract.status,
            Contract.end_date,
            Contract.terminated_at,
            Contract.termination_reason,
        ).where(Contract.id.in_(contract_ids))
    )
    early = set(
        await db.scalars(
            select(ContractAmendment.contract_id).where(
                ContractAmendment.contract_id.in_(contract_ids),
                ContractAmendment.amendment_type
                == ContractAmendmentType.early_termination,
            )
        )
    )
    # Kontrakt ``ended``/``void`` to SAM w sobie zamiar zakończenia (decyzja
    # D2, audyt 24.09.2026): współpraca się skończyła, więc żadne jej
    # zamówienie nie czeka na następcę — niezależnie od tego, czy data końca
    # umowy wypada przed, czy po końcu zamówienia (zamówienie do 30.08,
    # umowa zakończona 31.08). Wypowiedzenie umowy, która jeszcze trwa, liczy
    # się jak dotąd tylko dla zamówień kończących się nie wcześniej niż umowa.
    terminal_contracts: set[int] = set()
    terminated_contracts: dict[int, date] = {}
    for contract_id, status, end_date, terminated_at, reason in contracts.all():
        status_value = _value(status)
        if status_value in (ContractStatus.ended.value, ContractStatus.void.value):
            terminal_contracts.add(contract_id)
            continue
        # `terminated_at` przeżywa wznowienie umowy, ale wznowienie czyści
        # datę końca — więc wypowiedzenie liczy się tylko z datą końca.
        if end_date is not None and (
            terminated_at is not None or reason is not None or contract_id in early
        ):
            terminated_contracts[contract_id] = end_date

    for fact in facts:
        if fact.end is None:
            continue
        if fact.contract_id in terminal_contracts:
            intents.setdefault(fact.order_id, INTENT_CONTRACT_ENDED)
            continue
        contract_end = terminated_contracts.get(fact.contract_id)
        if contract_end is not None and contract_end <= fact.end:
            intents.setdefault(fact.order_id, INTENT_CONTRACT_ENDED)
    return intents


def live_order_filter():
    """Zamówienie istnieje rozliczeniowo: nie anulowane."""

    return ClientOrder.status != ClientOrderStatus.cancelled


def period_overlaps(start: date, end: date):
    eff_start = effective_start_expr()
    eff_end = effective_end_expr()
    return and_(
        or_(eff_start.is_(None), eff_start <= end),
        or_(eff_end.is_(None), eff_end >= start),
    )
