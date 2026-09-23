"""Przejęcie pozostałych MD przy zastępstwie (ticket 09.2026, wszyscy klienci MD).

Jedna reguła dla trzech wejść: „Wejdź za konsultanta" z karty szkicu (CeZ),
modal „Zakończenie współpracy — decyzja o MD" z nową osobą i „Zastąp kimś
innym" na linii osoby, która odeszła.

Sposób przeniesienia zależy od tego, w czym zapisano pulę odchodzącego:

* pula w MD — pozostałe MD przechodzą 1:1; przelicznika nie ma, bo liczba
  dni jest tu faktem umowy, a nie kwotą do podzielenia;
* pula w kwocie — ``pozostało X MD × stawka odchodzącego = kwota``, a DL
  wybiera, czy nowa osoba dostaje X MD (po stawce odchodzącego), czy
  ``kwota ÷ stawka przychodzącego`` (po stawce przychodzącego, zaokrąglone do
  0,1 MD). Żadnej opcji nie wybieramy za niego — to decyzja o pieniądzach.

Przeniesienie jest zapisywane jako ROZSTRZYGNIĘTA sprawa offboardingu
(``transfer`` na linię nowej osoby). Dzięki temu korekta po spóźnionym
raporcie Finansów (``_rebalance_offboarding_transfer``, FIN-MD-02) działa tu
tak samo jak przy zwykłym przeniesieniu puli, a odchodzący przestaje pokazywać
„pozostało" — jego budżet jest zdejmowany o przekazaną pulę (B2).

Zastępstwo za osobę, która jeszcze pracuje (przyszła data zakończenia), jest
ZAPLANOWANE: nowa linia czeka jako szkic, a w dniu wejścia — gdy kontrakt
odchodzącego już się zakończył — ``activate_due_takeovers`` przenosi pulę
z tego dnia i aktywuje linię.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    ClientOrderGroup,
    ClientOrderGroupEvent,
)
from app.models.client_order_offboarding import (
    OFFBOARDING_RATE_BASIS_DEPARTING,
    OFFBOARDING_RATE_BASIS_RECIPIENT,
    OFFBOARDING_RESOLUTION_TRANSFER,
    OFFBOARDING_STATUS_PENDING,
    OFFBOARDING_STATUS_RESOLVED,
    ClientOrderOffboardingCase,
)
from app.models.contract import Contract, ContractStatus
from app.services.client_order_lines import (
    _swap_split_remaining,
    consultant_display_name,
    recompute_remaining,
    record_event,
)
from app.services.multi_consultant_orders import (
    EVENT_CONSULTANT_ADDED,
    EVENT_MANUAL_EDIT,
    EVENT_MD_OFFBOARDING_TRANSFERRED,
    INPUT_MODE_AMOUNT,
    INPUT_MODE_MD,
    format_md,
    quantize_md,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
TENTH = Decimal("0.1")

TRANSFER_ONE_TO_ONE = "one_to_one"
TRANSFER_DEPARTING_RATE = "departing_rate"
TRANSFER_INCOMING_RATE = "incoming_rate"
TRANSFER_METHODS: tuple[str, ...] = (
    TRANSFER_ONE_TO_ONE,
    TRANSFER_DEPARTING_RATE,
    TRANSFER_INCOMING_RATE,
)
TRANSFER_METHOD_LABELS: dict[str, str] = {
    TRANSFER_ONE_TO_ONE: "1:1",
    TRANSFER_DEPARTING_RATE: "po stawce osoby odchodzącej",
    TRANSFER_INCOMING_RATE: "po stawce osoby przychodzącej",
}

POOL_UNIT_MD = "md"
POOL_UNIT_AMOUNT = "amount"

#: Stan osoby, za którą można wejść.
SOURCE_ENDED = "ended"
SOURCE_LEAVING = "leaving"

#: Znacznik w payloadzie zdarzenia „dodanie konsultanta".
ASSIGNMENT_JOIN = "join"
ASSIGNMENT_TAKEOVER = "takeover"


class TakeoverError(ValueError):
    """Odmowa z komunikatem po polsku; ``status`` mówi, jaki kod HTTP oddać."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


# ── Arytmetyka (czysta) ─────────────────────────────────────────────────────


def line_pool_unit(line: ClientOrder) -> Optional[str]:
    """W czym zapisano pulę osoby: ``md``, ``amount`` albo ``None`` (brak puli).

    Linia kosztowa i linia wspólnej puli nie mają budżetu per osoba
    (``md_total IS NULL``) — nie ma czego przenosić.
    """
    if line.md_total is None:
        return None
    return POOL_UNIT_AMOUNT if line.md_input_mode == INPUT_MODE_AMOUNT else POOL_UNIT_MD


def resolve_transfer_method(unit: Optional[str], method: Optional[str]) -> str:
    """Sposób przeniesienia dozwolony dla tej puli.

    Pula w MD ma jedną odpowiedź (1:1), więc brak wyboru jest poprawny.
    Pula w kwocie wymaga JAWNEGO wyboru — domyślna opcja rozstrzygałaby za DL,
    ile dni dostaje nowa osoba.
    """
    if unit == POOL_UNIT_MD:
        if method not in (None, TRANSFER_ONE_TO_ONE):
            raise TakeoverError(
                "Zamówienie ma pulę w MD — pozostałe MD przechodzą 1:1, "
                "bez przeliczania po stawce."
            )
        return TRANSFER_ONE_TO_ONE
    if unit == POOL_UNIT_AMOUNT:
        if method not in (TRANSFER_DEPARTING_RATE, TRANSFER_INCOMING_RATE):
            raise TakeoverError(
                "Zamówienie ma pulę w kwocie — wybierz, po czyjej stawce "
                "przeliczyć pozostałe MD."
            )
        return method
    raise TakeoverError("Ta osoba nie ma własnej puli MD do przeniesienia.")


def round_to_tenth(value: Decimal) -> Decimal:
    return quantize_md(Decimal(str(value)).quantize(TENTH, rounding=ROUND_HALF_UP))


def transferred_md(
    method: str,
    remaining: Decimal,
    departing_rate: Optional[Decimal],
    incoming_rate: Optional[Decimal],
) -> Decimal:
    """Ile MD dostaje nowa osoba z ``remaining`` MD odchodzącego.

    1:1 i „po stawce odchodzącego" dają tę samą liczbę dni; „po stawce
    przychodzącego" dzieli kwotę (X × stawka odchodzącego) przez stawkę
    przychodzącego i zaokrągla do 0,1 MD.
    """
    remaining = quantize_md(remaining)
    if method in (TRANSFER_ONE_TO_ONE, TRANSFER_DEPARTING_RATE):
        return remaining
    if method != TRANSFER_INCOMING_RATE:
        raise TakeoverError("Nieznany sposób przeniesienia MD.")
    if departing_rate is None or Decimal(str(departing_rate)) <= 0:
        raise TakeoverError("Osoba odchodząca nie ma stawki przychodowej.")
    if incoming_rate is None or Decimal(str(incoming_rate)) <= 0:
        raise TakeoverError("Podaj stawkę przychodową nowej osoby.")
    amount = remaining * Decimal(str(departing_rate))
    return round_to_tenth(amount / Decimal(str(incoming_rate)))


def basis_rate_for(
    method: str, departing_rate: Decimal, incoming_rate: Decimal
) -> Decimal:
    """Stawka, przez którą ``_rebalance_offboarding_transfer`` mnoży pulę.

    Korekta liczy ``pozostało × podstawa ÷ stawka_celu`` — dla 1:1 podstawą
    jest stawka celu (wynik = pozostało), dla przeliczenia po stawce
    przychodzącego — stawka odchodzącego (wynik = kwota ÷ stawka celu).
    """
    if method == TRANSFER_INCOMING_RATE:
        return Decimal(str(departing_rate))
    return Decimal(str(incoming_rate))


def stored_rate_basis(method: str) -> str:
    """Wartość kolumny ``rate_basis`` sprawy (CHECK zna tylko dwie)."""
    return (
        OFFBOARDING_RATE_BASIS_DEPARTING
        if method == TRANSFER_INCOMING_RATE
        else OFFBOARDING_RATE_BASIS_RECIPIENT
    )


def split_transferred(
    *,
    method: str,
    base_remaining: Decimal,
    optional_remaining: Decimal,
    has_optional: bool,
    departing_rate: Optional[Decimal],
    incoming_rate: Optional[Decimal],
) -> tuple[Decimal, Optional[Decimal]]:
    """(podstawa, opcja) budżetu nowej osoby — zakres opcjonalny zostaje opcją."""
    total = transferred_md(
        method, base_remaining + optional_remaining, departing_rate, incoming_rate
    )
    if not has_optional:
        return total, None
    if method == TRANSFER_INCOMING_RATE:
        optional_new = min(
            total,
            round_to_tenth(
                optional_remaining
                * Decimal(str(departing_rate))
                / Decimal(str(incoming_rate))
            ),
        )
    else:
        optional_new = quantize_md(optional_remaining)
    return quantize_md(total - optional_new), quantize_md(optional_new)


def describe_transfer(
    *,
    source_name: str,
    target_name: str,
    entry_date: date,
    transferred: Decimal,
    remaining: Decimal,
    method: str,
    departing_rate: Optional[Decimal],
    automatic: bool = False,
) -> str:
    """Wpis „Historii zamówienia" (B3): z kogo, na kogo, od kiedy, ile, jak."""
    how = TRANSFER_METHOD_LABELS.get(method, method)
    text = (
        f"Przeniesienie MD: {source_name} → {target_name} od "
        f"{entry_date.strftime('%d.%m.%Y')}: {format_md(transferred)} MD ({how})."
    )
    if method != TRANSFER_ONE_TO_ONE and departing_rate is not None:
        text += (
            f" Pozostało {format_md(remaining)} MD × "
            f"{format_md(departing_rate)} zł/MD osoby odchodzącej."
        )
    if automatic:
        text += " Zastępstwo weszło automatycznie w dniu wejścia."
    return text


# ── Stan osoby odchodzącej ──────────────────────────────────────────────────


@dataclass(frozen=True)
class TakeoverSource:
    state: str
    departure_date: Optional[date]
    case: Optional[ClientOrderOffboardingCase]


async def _cases_for_line(
    db: AsyncSession, line_id: int
) -> list[ClientOrderOffboardingCase]:
    return list(
        (
            await db.scalars(
                select(ClientOrderOffboardingCase)
                .where(ClientOrderOffboardingCase.order_id == line_id)
                .order_by(ClientOrderOffboardingCase.id.desc())
            )
        ).all()
    )


def takeover_source_state(
    line: ClientOrder,
    *,
    contract: Optional[Contract],
    cases: list[ClientOrderOffboardingCase],
    has_successor: bool,
    history_decided: bool,
    today: date,
) -> Optional[TakeoverSource]:
    """Czy za tę osobę można wejść — i od kiedy jej nie ma.

    * ``ended`` — współpraca zakończona, a pula czeka: otwarta sprawa
      offboardingu albo linia zakończona bez sprawy, z pozostałymi MD;
    * ``leaving`` — osoba jeszcze pracuje, ale jej kontrakt ma przyszłą datę
      zakończenia (wypowiedzenie z datą).

    Osoba z następcą, z podjętą decyzją o puli albo bez własnej puli MD nie
    jest źródłem — jej pozostałe MD już ktoś rozdysponował albo ich nie ma.
    """
    if line.md_total is None or line.order_group_id is None:
        return None
    if has_successor or history_decided:
        return None
    pending = next((c for c in cases if c.status == OFFBOARDING_STATUS_PENDING), None)
    if pending is not None:
        if pending.uses_shared_md_pool:
            return None
        return TakeoverSource(SOURCE_ENDED, pending.effective_date, pending)
    if any(c.status == OFFBOARDING_STATUS_RESOLVED for c in cases):
        return None
    contract_status = (
        getattr(contract.status, "value", contract.status) if contract else None
    )
    if line.status == ClientOrderStatus.active:
        if (
            contract is not None
            and contract.end_date is not None
            and contract.end_date >= today
            and contract_status
            in (ContractStatus.active.value, ContractStatus.ending.value)
        ):
            return TakeoverSource(SOURCE_LEAVING, contract.end_date, None)
        return None
    if (
        line.status == ClientOrderStatus.completed
        and contract_status == ContractStatus.ended.value
        and Decimal(str(line.md_remaining or 0)) > 0
    ):
        departure = contract.end_date or line.end_date
        return TakeoverSource(SOURCE_ENDED, departure, None)
    return None


async def load_takeover_source(
    db: AsyncSession, line: ClientOrder, *, today: Optional[date] = None
) -> Optional[TakeoverSource]:
    """Ta sama reguła co ``takeover_source_state``, z doczytaniem stanu z bazy."""
    from app.services.multi_consultant_orders import (
        EVENT_CONSULTANT_ENDED,
        LINE_DECISION_KEEP_HISTORY,
        LINE_DECISION_REMOVED,
    )

    successor = await db.scalar(
        select(ClientOrder.id).where(
            ClientOrder.predecessor_order_id == line.id,
            ClientOrder.order_group_id == line.order_group_id,
            ClientOrder.status != ClientOrderStatus.cancelled,
        )
    )
    decided = await db.scalar(
        select(ClientOrderGroupEvent.id).where(
            ClientOrderGroupEvent.order_id == line.id,
            ClientOrderGroupEvent.event_type == EVENT_CONSULTANT_ENDED,
            ClientOrderGroupEvent.payload["reason"].astext.in_(
                (LINE_DECISION_REMOVED, LINE_DECISION_KEEP_HISTORY)
            ),
        )
    )
    contract = await db.get(Contract, line.contract_id)
    return takeover_source_state(
        line,
        contract=contract,
        cases=await _cases_for_line(db, line.id),
        has_successor=successor is not None,
        history_decided=decided is not None,
        today=today or business_today(),
    )


# ── Przeniesienie ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TransferResult:
    case: ClientOrderOffboardingCase
    transferred: Decimal
    remaining: Decimal
    method: str


async def apply_takeover_transfer(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    source: ClientOrder,
    target: ClientOrder,
    departure_date: date,
    entry_date: date,
    method: str,
    case: Optional[ClientOrderOffboardingCase],
    actor_id: Optional[int],
    automatic: bool = False,
) -> TransferResult:
    """Przenieś pozostałą pulę ``source`` na NOWĄ linię ``target``.

    Budżet celu jest ustawiany od zera (linia powstała na to zastępstwo),
    budżet źródła zdejmowany o przeniesioną pulę — obie strony liczą te MD
    dokładnie raz. Sprawa offboardingu (istniejąca albo założona tutaj) staje
    się rozstrzygniętym ``transfer`` z dowodami dla korekty FIN-MD-02.
    Bez commitu.
    """
    # Import leniwy: helper żyje w module tras i woła `HTTPException`; tu
    # przechwytujemy jego odmowę i oddajemy ją jako `TakeoverError`.
    from fastapi import HTTPException

    from app.api.client_order_groups import _reduce_legacy_md_budget
    from app.services.dl_alerts import handle_offboarding_case_alerts

    await recompute_remaining(db, source, rebalance=False)
    remaining = max(ZERO, quantize_md(source.md_remaining or 0))
    if case is not None:
        remaining = max(ZERO, quantize_md(case.remaining_md_snapshot))
    if remaining <= 0:
        raise TakeoverError(
            "Osoba odchodząca nie ma pozostałych MD do przejęcia — dodaj nową "
            "osobę do zamówienia z własną pulą."
        )
    departing_rate = (
        case.rate_revenue_snapshot if case is not None else None
    ) or source.md_rate_revenue
    incoming_rate = target.md_rate_revenue
    base_rem, opt_rem = await _swap_split_remaining(db, source, remaining)
    base_new, opt_new = split_transferred(
        method=method,
        base_remaining=base_rem,
        optional_remaining=opt_rem,
        has_optional=source.md_optional_total is not None,
        departing_rate=departing_rate,
        incoming_rate=incoming_rate,
    )
    transferred = quantize_md(base_new + (opt_new or ZERO))
    if transferred <= 0:
        raise TakeoverError("Przeliczenie dało zero MD — sprawdź stawki.")

    source_before = {
        "md_total": None if source.md_total is None else str(source.md_total),
        "md_optional_total": (
            None if source.md_optional_total is None else str(source.md_optional_total)
        ),
        "md_manual_adjustment": str(source.md_manual_adjustment or 0),
        "md_input_mode": source.md_input_mode,
        "md_input_value": (
            None if source.md_input_value is None else str(source.md_input_value)
        ),
    }

    target.md_input_mode = INPUT_MODE_MD
    target.md_input_value = base_new
    target.md_total = base_new
    target.md_optional_total = opt_new
    target.md_manual_adjustment = ZERO
    target.md_remaining = transferred

    try:
        _reduce_legacy_md_budget(source, remaining)
    except HTTPException as exc:
        detail = exc.detail
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        raise TakeoverError(message, status=exc.status_code) from exc
    await recompute_remaining(db, source, rebalance=False)
    await db.flush()
    await recompute_remaining(db, target, rebalance=False)

    now = datetime.now(timezone.utc)
    if case is None:
        # Linia zakończona bez sprawy albo zastępstwo zaplanowane, którego
        # sprawę nocna terminacja jeszcze nie założyła: zapisujemy decyzję jako
        # sprawę rozstrzygniętą, żeby korekta FIN-MD-02 widziała przeniesienie.
        existing = await db.scalar(
            select(ClientOrderOffboardingCase)
            .where(
                ClientOrderOffboardingCase.order_id == source.id,
                ClientOrderOffboardingCase.effective_date == departure_date,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.status != OFFBOARDING_STATUS_PENDING:
                raise TakeoverError(
                    "Decyzja o pozostałych MD tej osoby została już podjęta.",
                    status=409,
                )
            case = existing
        else:
            case = ClientOrderOffboardingCase(
                contract_id=source.contract_id,
                order_id=source.id,
                order_group_id=group.id,
                client_id=source.client_id,
                effective_date=departure_date,
                status=OFFBOARDING_STATUS_PENDING,
                version=1,
                uses_shared_md_pool=False,
                remaining_md_snapshot=remaining,
                rate_cost_snapshot=source.md_rate_cost,
                rate_revenue_snapshot=source.md_rate_revenue,
                currency_snapshot="PLN",
                order_number_snapshot=group.order_number,
                created_by_user_id=actor_id,
            )
            db.add(case)
            await db.flush()

    target_name = consultant_display_name(target)
    source_name = consultant_display_name(source)
    was_pending = case.status == OFFBOARDING_STATUS_PENDING
    case.status = OFFBOARDING_STATUS_RESOLVED
    case.resolution = OFFBOARDING_RESOLUTION_TRANSFER
    case.target_order_id = target.id
    case.rate_basis = stored_rate_basis(method)
    case.resolved_at = now
    case.resolved_by_user_id = actor_id
    case.version += 1
    case.resolution_payload = {
        "remaining_md_snapshot": str(remaining),
        "transferred_md": str(transferred),
        "uses_shared_md_pool": False,
        "source_rate_revenue": None if departing_rate is None else str(departing_rate),
        "target_rate_revenue": None if incoming_rate is None else str(incoming_rate),
        "target_order_id": target.id,
        "target_consultant": target_name,
        "md_transfer_method": method,
        "takeover": True,
        "entry_date": entry_date.isoformat(),
        "basis_rate": str(basis_rate_for(method, departing_rate, incoming_rate)),
        "source_before": source_before,
        "source_md_total_after": str(source.md_total),
        "source_md_optional_after": (
            None if source.md_optional_total is None else str(source.md_optional_total)
        ),
        "target_md_total_after": str(target.md_total),
        "restored_end_date": None,
        "contract_reopened": False,
    }
    record_event(
        db,
        group_id=group.id,
        order_id=source.id,
        event_type=EVENT_MD_OFFBOARDING_TRANSFERRED,
        description=describe_transfer(
            source_name=source_name,
            target_name=target_name,
            entry_date=entry_date,
            transferred=transferred,
            remaining=remaining,
            method=method,
            departing_rate=departing_rate,
            automatic=automatic,
        ),
        payload={
            "offboarding_case_id": case.id,
            "source_order_id": source.id,
            "target_order_id": target.id,
            "rate_basis": case.rate_basis,
            **case.resolution_payload,
        },
        user_id=actor_id,
    )
    if was_pending:
        await handle_offboarding_case_alerts(
            db, case_id=case.id, handled_by_user_id=actor_id, now=now
        )
    return TransferResult(
        case=case, transferred=transferred, remaining=remaining, method=method
    )


def projected_budget(
    *,
    source: ClientOrder,
    method: str,
    incoming_rate: Decimal,
    base_remaining: Decimal,
    optional_remaining: Decimal,
) -> tuple[Decimal, Optional[Decimal]]:
    """Budżet zaplanowanego zastępstwa „na dziś" — przeliczany w dniu wejścia."""
    return split_transferred(
        method=method,
        base_remaining=max(ZERO, base_remaining),
        optional_remaining=max(ZERO, optional_remaining),
        has_optional=source.md_optional_total is not None,
        departing_rate=source.md_rate_revenue,
        incoming_rate=incoming_rate,
    )


async def scheduled_takeover_event(
    db: AsyncSession, line: ClientOrder
) -> Optional[ClientOrderGroupEvent]:
    """Zdarzenie dodania linii z planem zastępstwa, jeśli linia go niesie."""
    event = await db.scalar(
        select(ClientOrderGroupEvent)
        .where(
            ClientOrderGroupEvent.order_id == line.id,
            ClientOrderGroupEvent.event_type == EVENT_CONSULTANT_ADDED,
        )
        .order_by(ClientOrderGroupEvent.id.asc())
        .limit(1)
    )
    payload = (event.payload or {}) if event is not None else {}
    if payload.get("assignment") == ASSIGNMENT_TAKEOVER and payload.get("scheduled"):
        return event
    return None


async def scheduled_successor_of(
    db: AsyncSession, source_id: int
) -> Optional[ClientOrder]:
    """Zaplanowane (jeszcze nieaktywne) zastępstwo za tę linię."""
    candidates = list(
        (
            await db.scalars(
                select(ClientOrder).where(
                    ClientOrder.predecessor_order_id == source_id,
                    ClientOrder.status == ClientOrderStatus.draft,
                )
            )
        ).all()
    )
    for line in candidates:
        if await scheduled_takeover_event(db, line) is not None:
            return line
    return None


async def activate_due_takeovers(
    db: AsyncSession, *, today: Optional[date] = None
) -> int:
    """Wejście zaplanowanych zastępstw, których dzień nadszedł.

    Warunek: data wejścia minęła albo jest dziś, a odchodzący NIE pracuje już
    na zamówieniu (nocna terminacja domknęła jego linię i założyła sprawę).
    Pula jest liczona z tego dnia — MD zużyte do końca współpracy zostają
    przy odchodzącym. Każde zastępstwo w osobnym savepoincie: jedno zepsute
    nie zatrzymuje pozostałych. Bez commitu.
    """
    from app.services.contract_lifecycle import sync_contract_to_live_order

    day = today or business_today()
    due = list(
        (
            await db.scalars(
                select(ClientOrder)
                .options(
                    selectinload(ClientOrder.contract).selectinload(Contract.candidate)
                )
                .join(
                    ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id
                )
                .where(
                    ClientOrder.status == ClientOrderStatus.draft,
                    ClientOrder.predecessor_order_id.is_not(None),
                    ClientOrder.start_date <= day,
                    ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
                )
                .order_by(ClientOrder.id.asc())
            )
        ).all()
    )
    activated = 0
    for target in due:
        event = await scheduled_takeover_event(db, target)
        if event is None:
            continue
        payload = dict(event.payload or {})
        try:
            async with db.begin_nested():
                group = await db.scalar(
                    select(ClientOrderGroup)
                    .where(ClientOrderGroup.id == target.order_group_id)
                    .with_for_update()
                )
                source = await db.scalar(
                    select(ClientOrder)
                    .options(
                        selectinload(ClientOrder.contract).selectinload(
                            Contract.candidate
                        )
                    )
                    .where(ClientOrder.id == target.predecessor_order_id)
                    .with_for_update()
                )
                if group is None or source is None:
                    continue
                if source.status == ClientOrderStatus.active:
                    # Odchodzący jeszcze pracuje (terminacja nie weszła) —
                    # zastępstwo czeka na jego koniec.
                    continue
                cases = await _cases_for_line(db, source.id)
                pending = next(
                    (c for c in cases if c.status == OFFBOARDING_STATUS_PENDING), None
                )
                if pending is None and any(
                    c.status == OFFBOARDING_STATUS_RESOLVED for c in cases
                ):
                    target.status = ClientOrderStatus.cancelled
                    record_event(
                        db,
                        group_id=group.id,
                        order_id=target.id,
                        event_type=EVENT_MANUAL_EDIT,
                        description=(
                            f"Zaplanowane zastępstwo {consultant_display_name(target)} "
                            f"za {consultant_display_name(source)} nie weszło — "
                            "decyzję o pozostałych MD podjęto wcześniej ręcznie."
                        ),
                        payload={
                            "assignment": ASSIGNMENT_TAKEOVER,
                            "scheduled_cancelled": True,
                            "takeover_from_order_id": source.id,
                        },
                    )
                    continue
                departure = (
                    pending.effective_date
                    if pending is not None
                    else (source.end_date or target.start_date)
                )
                await apply_takeover_transfer(
                    db,
                    group=group,
                    source=source,
                    target=target,
                    departure_date=departure,
                    entry_date=target.start_date or day,
                    method=str(
                        payload.get("md_transfer_method") or TRANSFER_ONE_TO_ONE
                    ),
                    case=pending,
                    actor_id=None,
                    automatic=True,
                )
                target.status = ClientOrderStatus.active
                if target.filled_at is None:
                    target.filled_at = datetime.now(timezone.utc)
                payload["scheduled"] = False
                payload["activated_on"] = day.isoformat()
                event.payload = payload
                contract = await db.get(Contract, target.contract_id)
                if contract is not None:
                    await sync_contract_to_live_order(
                        db,
                        contract,
                        order_start=target.start_date,
                        order_end=target.end_date,
                        actor_id=None,
                        today=day,
                    )
                activated += 1
        except TakeoverError as exc:
            logger.warning(
                "order_line_takeover: zastępstwo linii %s nie weszło: %s",
                target.id,
                exc,
            )
    return activated
