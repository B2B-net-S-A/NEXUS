"""Router `/api/clients/{client_id}/order-groups` — zamówienia wielo-konsultantowe.

Grupa to „Zamówienie nr 445" od klienta; linia to konkretny konsultant pod tym
numerem, ze swoją stawką kosztową, przychodową i budżetem MD. Linia jest
zwykłym ``ClientOrder`` wpiętym w grupę, więc zachowuje kontrakt, kandydata i
całą dotychczasową obsługę (skaner wygasania, sync terminacji, MRR).

Cały router stoi za bramką klientów (``MULTI_CONSULTANT_ORDER_CLIENT_IDS``).
Bramka jest przy KAŻDEJ operacji, nie tylko przy renderowaniu widoku: ukryty
przycisk nie jest zabezpieczeniem, a wywołane wprost API założyłoby zamówienie
u klienta, którego zakładka nigdy go nie pokaże — czyli dane nie do zobaczenia
i nie do poprawienia z interfejsu.

Uprawnienia dzielą się dokładnie tam, gdzie w module zamówień: **pieniądze
pisze wyłącznie admin** (stawki, kwota budżetu), operacyjne rzeczy — DL
przypisany do klienta. Nowa powierzchnia nie może rozluźnić bramki finansowej,
bo obchodziłaby regułę, którą reszta modułu już egzekwuje.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.deps import DlAssignedOrAdmin, TacPlus
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
from app.models.contract import Contract
from app.models.job import Job
from app.models.user import User, UserRole
from app.schemas.client_order_group import (
    OrderGroupCreate,
    OrderGroupEventRead,
    OrderGroupEventsResponse,
    OrderGroupListResponse,
    OrderGroupRead,
    OrderGroupUpdate,
    OrderLineCreate,
    OrderLineRead,
    OrderLineSwapRequest,
    OrderLineUpdate,
)
from app.services.client_order_lines import (
    consultant_display_name,
    lines_for_group,
    record_event,
    recompute_remaining,
)
from app.services.client_access import deny, resolve_client_access
from app.services.multi_consultant_orders import (
    EVENT_CONSULTANT_ADDED,
    EVENT_CONSULTANT_SWAPPED,
    EVENT_MANUAL_EDIT,
    EVENT_ORDER_CREATED,
    EVENT_TYPE_LABELS,
    INPUT_MODE_AMOUNT,
    INPUT_MODE_MD,
    compute_md_total,
    format_md,
    is_multi_consultant_client,
    quantize_md,
    remaining_value_pln,
    swap_md_total,
)

router = APIRouter()


# Pola pieniężne linii. Nazwy są WŁASNE, nie z `_ORDER_FINANCE_WRITE_FIELDS`
# w `client_orders.py` — tamten zbiór opisuje `rate_client`/`rate_candidate`,
# czyli stawki interpretowane przez `Contract.rate_unit`. Tutaj stawki są
# per MD i mają osobne kolumny, więc muszą mieć też własną bramkę; użycie
# tamtego zbioru przepuściłoby te pola bez żadnej kontroli.
_LINE_FINANCE_FIELDS = frozenset({"rate_cost", "rate_revenue"})


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _assert_client(db: AsyncSession, client_id: int) -> Client:
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(404, detail="Client not found")
    return client


async def _require_group_read(db: AsyncSession, user: User, client_id: int) -> None:
    """Ta sama decyzja dostępu co przy zamówieniach jednoosobowych.

    Lustro ``client_orders._require_client_order_read``: linia niesie kandydata
    i stawki, więc wymaga jawnego przypisania DL/TAC, a nie samej roli.
    """
    await _assert_client(db, client_id)
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_legal_documents:
        raise deny("zamówienia klienta wymagają jawnego przypisania DL/TAC")


def _assert_multi_client(client_id: int) -> None:
    if not is_multi_consultant_client(client_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Ten klient nie jest rozliczany w modelu wielo-konsultantowym. "
                "Użyj zwykłego zamówienia albo dopisz klienta do "
                "MULTI_CONSULTANT_ORDER_CLIENT_IDS."
            ),
        )


def _assert_line_finance_write_allowed(user: User, supplied: set[str]) -> None:
    """Stawki linii pisze wyłącznie admin — jak każde pole pieniężne zamówienia."""
    forbidden = sorted(supplied & _LINE_FINANCE_FIELDS)
    if forbidden and not user.has_role(UserRole.admin):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "finance_fields_forbidden", "fields": forbidden},
        )


def _can_see_finance(user: User) -> bool:
    return user_has_capability(user, AnalyticsCapability.VIEW_FINANCE)


async def _load_group(
    db: AsyncSession, client_id: int, group_id: int
) -> ClientOrderGroup:
    group = await db.scalar(
        select(ClientOrderGroup).where(
            ClientOrderGroup.id == group_id,
            ClientOrderGroup.client_id == client_id,
        )
    )
    if group is None:
        raise HTTPException(404, detail="Zamówienie nie istnieje")
    return group


def _line_to_read(order: ClientOrder, *, with_finance: bool) -> OrderLineRead:
    contract = order.contract
    predecessor_name: Optional[str] = None
    if order.predecessor is not None:
        predecessor_name = consultant_display_name(order.predecessor)

    # Kwota widziana przez rolę bez VIEW_FINANCE musi zniknąć, ale liczba MD
    # zostaje — pasek zużycia jest informacją operacyjną, nie finansową.
    input_value: Optional[Decimal] = order.md_input_value
    if not with_finance and order.md_input_mode == INPUT_MODE_AMOUNT:
        input_value = None

    return OrderLineRead(
        id=order.id,
        group_id=order.order_group_id,
        contract_id=order.contract_id,
        candidate_id=contract.candidate_id if contract else None,
        consultant_name=consultant_display_name(order),
        job_id=order.job_id,
        job_title=None,
        status=order.status.value,
        is_active=order.status == ClientOrderStatus.active,
        start_date=order.start_date,
        end_date=order.end_date,
        rate_cost=order.md_rate_cost if with_finance else None,
        rate_revenue=order.md_rate_revenue if with_finance else None,
        input_value=input_value,
        input_mode=order.md_input_mode,
        md_total=order.md_total,
        md_remaining=order.md_remaining,
        md_manual_adjustment=order.md_manual_adjustment,
        predecessor_order_id=order.predecessor_order_id,
        predecessor_consultant_name=predecessor_name,
    )


async def _group_to_read(
    db: AsyncSession, group: ClientOrderGroup, *, with_finance: bool
) -> OrderGroupRead:
    lines = await lines_for_group(db, group.id)
    job_titles: dict[int, str] = {}
    job_ids = [line.job_id for line in lines if line.job_id]
    if job_ids:
        rows = await db.execute(
            select(Job.id, Job.title).where(Job.id.in_(set(job_ids)))
        )
        job_titles = {jid: title for jid, title in rows}

    reads: list[OrderLineRead] = []
    for line in lines:
        item = _line_to_read(line, with_finance=with_finance)
        if item.job_id:
            item.job_title = job_titles.get(item.job_id)
        reads.append(item)

    event_count = await db.scalar(
        select(func.count(ClientOrderGroupEvent.id)).where(
            ClientOrderGroupEvent.group_id == group.id
        )
    )
    return OrderGroupRead(
        id=group.id,
        client_id=group.client_id,
        order_number=group.order_number,
        start_date=group.start_date,
        end_date=group.end_date,
        notes=group.notes,
        created_at=group.created_at,
        lines=reads,
        active_consultants=sum(1 for r in reads if r.is_active),
        event_count=int(event_count or 0),
    )


async def _resolve_contract(
    db: AsyncSession, client_id: int, contract_id: int
) -> Contract:
    contract = await db.scalar(
        select(Contract)
        .options(selectinload(Contract.candidate))
        .where(Contract.id == contract_id, Contract.client_id == client_id)
    )
    if contract is None:
        raise HTTPException(
            400, detail="Wybrany konsultant nie ma kontraktu u tego klienta"
        )
    return contract


async def _build_line(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    payload: OrderLineCreate,
    user: User,
) -> tuple[ClientOrder, str]:
    contract = await _resolve_contract(db, group.client_id, payload.contract_id)
    if payload.job_id is not None:
        owns_job = await db.scalar(
            select(Job.id).where(
                Job.id == payload.job_id, Job.client_id == group.client_id
            )
        )
        if owns_job is None:
            raise HTTPException(400, detail="Rekrutacja nie należy do tego klienta")

    try:
        md_total = compute_md_total(
            input_mode=payload.input_mode,
            input_value=payload.input_value,
            rate_revenue=payload.rate_revenue,
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    candidate = contract.candidate
    who = (
        f"{candidate.name or ''} {candidate.lastname or ''}".strip()
        if candidate
        else ""
    )
    now = datetime.now(timezone.utc)
    line = ClientOrder(
        client_id=group.client_id,
        contract_id=contract.id,
        job_id=payload.job_id,
        order_group_id=group.id,
        title=f"Zamówienie {group.order_number} — {who or 'konsultant'}"[:255],
        status=ClientOrderStatus.active,
        start_date=payload.start_date,
        end_date=payload.end_date or group.end_date,
        filled_at=now,
        md_rate_cost=payload.rate_cost,
        md_rate_revenue=payload.rate_revenue,
        md_input_mode=payload.input_mode,
        md_input_value=payload.input_value,
        md_total=md_total,
        md_remaining=md_total,
        md_manual_adjustment=Decimal("0"),
        created_by_user_id=user.id,
    )
    db.add(line)
    # Zwracamy nazwisko RAZEM z linią, zamiast odczytywać je później przez
    # `line.contract.candidate`: świeżo skonstruowany obiekt nie ma załadowanej
    # relacji, więc sięgnięcie po nią odpaliłoby leniwe doczytanie — w async
    # SQLAlchemy kończy się to `MissingGreenlet`, czyli 500 bez CORS
    # (w przeglądarce „Network Error" bez żadnej wskazówki).
    return line, who or "konsultant"


def _describe_line(order: ClientOrder, who: str) -> str:
    return (
        f"{who} — stawka kosztowa {format_md(order.md_rate_cost)} zł/MD, "
        f"przychodowa {format_md(order.md_rate_revenue)} zł/MD, "
        f"budżet {format_md(order.md_total)} MD"
    )


# ── Odczyt ──────────────────────────────────────────────────────────────────


@router.get("/{client_id}/order-groups", response_model=OrderGroupListResponse)
async def list_order_groups(
    client_id: int,
    user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Zamówienia klienta wraz z liniami konsultantów.

    Klient spoza listy dostaje PUSTĄ listę, nie 403 — front pyta o ten zasób
    dopiero po sprawdzeniu flagi, a odmowa renderowałaby się jako awaria tam,
    gdzie faktycznie po prostu nie ma czego pokazać.
    """
    await _require_group_read(db, user, client_id)
    if not is_multi_consultant_client(client_id):
        return OrderGroupListResponse(groups=[], total_groups=0, total_consultants=0)

    result = await db.execute(
        select(ClientOrderGroup)
        .where(ClientOrderGroup.client_id == client_id)
        .order_by(ClientOrderGroup.start_date.desc(), ClientOrderGroup.id.desc())
    )
    with_finance = _can_see_finance(user)
    groups = [
        await _group_to_read(db, g, with_finance=with_finance) for g in result.scalars()
    ]
    return OrderGroupListResponse(
        groups=groups,
        total_groups=len(groups),
        total_consultants=sum(g.active_consultants for g in groups),
    )


@router.get(
    "/{client_id}/order-groups/{group_id}/events",
    response_model=OrderGroupEventsResponse,
)
async def list_group_events(
    client_id: int,
    group_id: int,
    user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Historia zamówienia — chronologicznie, od najnowszego."""
    await _require_group_read(db, user, client_id)
    _assert_multi_client(client_id)
    await _load_group(db, client_id, group_id)

    result = await db.execute(
        select(ClientOrderGroupEvent)
        .where(ClientOrderGroupEvent.group_id == group_id)
        .order_by(
            ClientOrderGroupEvent.created_at.desc(), ClientOrderGroupEvent.id.desc()
        )
    )
    with_finance = _can_see_finance(user)
    events: list[OrderGroupEventRead] = []
    for ev in result.scalars():
        # `payload` niesie stawki (rozliczenie faktury w miesiącu zamiany),
        # więc dla ról bez VIEW_FINANCE znika w całości — opis po polsku
        # zostaje, bo mówi KTO i KIEDY, a nie ZA ILE.
        events.append(
            OrderGroupEventRead(
                id=ev.id,
                event_type=ev.event_type,
                event_label=EVENT_TYPE_LABELS.get(ev.event_type, ev.event_type),
                description=ev.description,
                order_id=ev.order_id,
                payload=ev.payload if with_finance else None,
                created_by_user_id=ev.created_by_user_id,
                created_at=ev.created_at,
            )
        )
    return OrderGroupEventsResponse(events=events)


# ── Zapis ───────────────────────────────────────────────────────────────────


@router.post(
    "/{client_id}/order-groups",
    response_model=OrderGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_group(
    client_id: int,
    payload: OrderGroupCreate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Nowe zamówienie klienta wraz z jedną lub wieloma liniami konsultantów."""
    if payload.lines:
        _assert_line_finance_write_allowed(user, {"rate_cost", "rate_revenue"})
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    if payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(422, detail="Data zakończenia jest wcześniejsza niż start")

    group = ClientOrderGroup(
        client_id=client_id,
        order_number=payload.order_number.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        notes=payload.notes,
        created_by_user_id=user.id,
    )
    db.add(group)
    await db.flush()

    record_event(
        db,
        group_id=group.id,
        event_type=EVENT_ORDER_CREATED,
        description=(
            f"Utworzono zamówienie nr {group.order_number} "
            f"({group.start_date.isoformat()} → "
            f"{group.end_date.isoformat() if group.end_date else 'bezterminowo'})"
        ),
        user_id=user.id,
    )

    for line_payload in payload.lines:
        line, who = await _build_line(db, group=group, payload=line_payload, user=user)
        await db.flush()
        record_event(
            db,
            group_id=group.id,
            order_id=line.id,
            event_type=EVENT_CONSULTANT_ADDED,
            description=_describe_line(line, who),
            payload={
                "consultant": who,
                "rate_cost": str(line.md_rate_cost),
                "rate_revenue": str(line.md_rate_revenue),
                "md_total": str(line.md_total),
                "input_mode": line.md_input_mode,
                "input_value": str(line.md_input_value),
            },
            user_id=user.id,
        )

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_group_created",
            details={"group_id": group.id, "lines": len(payload.lines)},
        )
    )
    await db.commit()
    await db.refresh(group)
    return await _group_to_read(db, group, with_finance=_can_see_finance(user))


@router.patch("/{client_id}/order-groups/{group_id}", response_model=OrderGroupRead)
async def update_order_group(
    client_id: int,
    group_id: int,
    payload: OrderGroupUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Edycja numeru i okresu zamówienia (bez dotykania linii)."""
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    data = payload.model_dump(exclude_unset=True)
    if not data:
        return await _group_to_read(db, group, with_finance=_can_see_finance(user))

    new_start = data.get("start_date", group.start_date)
    new_end = data.get("end_date", group.end_date)
    if new_end and new_start and new_end < new_start:
        raise HTTPException(422, detail="Data zakończenia jest wcześniejsza niż start")

    for field, value in data.items():
        setattr(group, field, value.strip() if field == "order_number" else value)

    record_event(
        db,
        group_id=group.id,
        event_type=EVENT_MANUAL_EDIT,
        description="Edycja zamówienia: " + ", ".join(sorted(data.keys())),
        payload={"changed": sorted(data.keys())},
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(group)
    return await _group_to_read(db, group, with_finance=_can_see_finance(user))


@router.delete(
    "/{client_id}/order-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_order_group(
    client_id: int,
    group_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Usuwa PUSTE zamówienie.

    Zamówienie z liniami jest odrzucane (409), a nie kasowane kaskadowo: linia
    to realne zaangażowanie z kontraktem, plikiem PO i historią zużycia MD.
    Kaskada skasowałaby dane, które powstały poza tym ekranem.
    """
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    line_count = await db.scalar(
        select(func.count(ClientOrder.id)).where(ClientOrder.order_group_id == group.id)
    )
    if line_count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"Zamówienie ma {line_count} linii konsultantów. "
                "Usuń albo przenieś linie, zanim skasujesz zamówienie."
            ),
        )
    await db.delete(group)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_group_deleted",
            details={"group_id": group_id},
        )
    )
    await db.commit()


@router.post(
    "/{client_id}/order-groups/{group_id}/lines",
    response_model=OrderLineRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_line(
    client_id: int,
    group_id: int,
    payload: OrderLineCreate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Dodaje konsultanta do istniejącego zamówienia."""
    _assert_line_finance_write_allowed(user, {"rate_cost", "rate_revenue"})
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    line, who = await _build_line(db, group=group, payload=payload, user=user)
    await db.flush()
    record_event(
        db,
        group_id=group.id,
        order_id=line.id,
        event_type=EVENT_CONSULTANT_ADDED,
        description=_describe_line(line, who),
        payload={
            "consultant": who,
            "rate_cost": str(line.md_rate_cost),
            "rate_revenue": str(line.md_rate_revenue),
            "md_total": str(line.md_total),
        },
        user_id=user.id,
    )
    await db.commit()

    refreshed = await db.scalar(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.predecessor),
        )
        .where(ClientOrder.id == line.id)
    )
    return _line_to_read(refreshed, with_finance=_can_see_finance(user))


@router.patch(
    "/{client_id}/order-groups/{group_id}/lines/{line_id}",
    response_model=OrderLineRead,
)
async def update_line(
    client_id: int,
    group_id: int,
    line_id: int,
    payload: OrderLineUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Edycja linii: stawki, budżet albo ręczna korekta pozostałych MD."""
    supplied = payload.model_fields_set
    _assert_line_finance_write_allowed(user, set(supplied))
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    await _load_group(db, client_id, group_id)

    line = await db.scalar(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.predecessor),
        )
        .where(
            ClientOrder.id == line_id,
            ClientOrder.order_group_id == group_id,
            ClientOrder.client_id == client_id,
        )
    )
    if line is None:
        raise HTTPException(404, detail="Linia nie istnieje w tym zamówieniu")

    data = payload.model_dump(exclude_unset=True)
    changed: list[str] = []

    if "rate_cost" in data:
        line.md_rate_cost = data["rate_cost"]
        changed.append("stawka kosztowa")
    if "end_date" in data:
        line.end_date = data["end_date"]
        changed.append("data zakończenia")

    # Stawka przychodowa i budżet przeliczają md_total razem — zmiana samej
    # stawki przy trybie „kwota" musi zmienić liczbę MD, inaczej zamówienie
    # zaczęłoby opiewać na inną kwotę, niż podpisano.
    recompute_total = (
        "rate_revenue" in data or "input_mode" in data or "input_value" in data
    )
    if recompute_total:
        rate_revenue = data.get("rate_revenue", line.md_rate_revenue)
        input_mode = data.get("input_mode", line.md_input_mode) or INPUT_MODE_MD
        input_value = data.get("input_value", line.md_input_value)
        if rate_revenue is None or input_value is None:
            raise HTTPException(
                422, detail="Do przeliczenia budżetu potrzebna jest stawka i wartość"
            )
        try:
            line.md_total = compute_md_total(
                input_mode=input_mode,
                input_value=input_value,
                rate_revenue=rate_revenue,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        line.md_rate_revenue = rate_revenue
        line.md_input_mode = input_mode
        line.md_input_value = input_value
        changed.append("budżet MD")

    if "md_remaining" in data and data["md_remaining"] is not None:
        # Korekta zapisywana jako RÓŻNICA, nie nadpisanie. Nadpisanie
        # `md_remaining` przeżyłoby dokładnie do najbliższego importu, który
        # przelicza pozostałość od `md_total` — i skasowałoby poprawkę bez
        # śladu.
        await recompute_remaining(db, line)
        natural = Decimal(str(line.md_remaining or 0)) - Decimal(
            str(line.md_manual_adjustment or 0)
        )
        line.md_manual_adjustment = quantize_md(
            Decimal(str(data["md_remaining"])) - natural
        )
        changed.append("ręczna korekta MD")

    await recompute_remaining(db, line)
    await db.flush()

    if changed:
        record_event(
            db,
            group_id=group_id,
            order_id=line.id,
            event_type=EVENT_MANUAL_EDIT,
            description=(
                f"{consultant_display_name(line)} — zmieniono: "
                + ", ".join(changed)
                + f". Pozostało {format_md(line.md_remaining)} MD."
            ),
            payload={"changed": changed, "md_remaining": str(line.md_remaining)},
            user_id=user.id,
        )
    await db.commit()
    await db.refresh(line)
    return _line_to_read(line, with_finance=_can_see_finance(user))


@router.post(
    "/{client_id}/order-groups/{group_id}/lines/{line_id}/swap",
    response_model=OrderLineRead,
    status_code=status.HTTP_201_CREATED,
)
async def swap_consultant(
    client_id: int,
    group_id: int,
    line_id: int,
    payload: OrderLineSwapRequest,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Zamiana kontraktora — nowa linia z MD przeliczonymi na nową stawkę.

    Przeliczenie zachowuje wartość zamówienia w PLN:
    ``md_nowe × stawka_nowa == md_pozostałe × stawka_stara``.

    Zamiana działa OD DNIA ZAMIANY W PRZÓD. MD zaraportowane wcześniej
    rozlicza się stawką poprzednika, więc wpisy konsumpcji sprzed tej daty
    zostają nietknięte, a obie stawki i obie liczby MD lądują w historii —
    bez nich nie da się rozliczyć faktury za miesiąc zamiany.
    """
    _assert_line_finance_write_allowed(user, {"rate_cost", "rate_revenue"})
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    old = await db.scalar(
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract).selectinload(Contract.candidate))
        .where(
            ClientOrder.id == line_id,
            ClientOrder.order_group_id == group_id,
            ClientOrder.client_id == client_id,
        )
    )
    if old is None:
        raise HTTPException(404, detail="Linia nie istnieje w tym zamówieniu")
    if old.md_total is None or old.md_rate_revenue is None:
        raise HTTPException(422, detail="Linia nie ma budżetu MD do przeniesienia")
    if old.status != ClientOrderStatus.active:
        raise HTTPException(
            422, detail="Zamienić można tylko aktywną linię konsultanta"
        )
    if old.start_date and payload.swap_date < old.start_date:
        raise HTTPException(
            422, detail="Data zamiany jest wcześniejsza niż start linii"
        )

    await recompute_remaining(db, old)
    md_remaining_old = Decimal(str(old.md_remaining or 0))
    try:
        md_total_new = swap_md_total(
            md_remaining_old=md_remaining_old,
            rate_revenue_old=old.md_rate_revenue,
            rate_revenue_new=payload.rate_revenue,
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    new_contract = await _resolve_contract(db, client_id, payload.contract_id)

    # Domknięcie starej linii lustrzane wobec syncu terminacji kontraktu
    # (`contracts.py`): data zawsze, status `completed` dopiero gdy dzień
    # zamiany nadszedł. Zamiana zaplanowana na przyszłość nie może wyłączyć
    # konsultanta, który jeszcze pracuje.
    today = date.today()
    old.end_date = payload.swap_date
    if payload.swap_date <= today:
        old.status = ClientOrderStatus.completed

    old_who = consultant_display_name(old)
    new_candidate = new_contract.candidate
    new_who = (
        f"{new_candidate.name or ''} {new_candidate.lastname or ''}".strip()
        if new_candidate
        else "konsultant"
    )

    new_line = ClientOrder(
        client_id=client_id,
        contract_id=new_contract.id,
        job_id=old.job_id,
        order_group_id=group.id,
        title=f"Zamówienie {group.order_number} — {new_who}"[:255],
        status=ClientOrderStatus.active,
        start_date=payload.swap_date,
        end_date=old.end_date if old.end_date != payload.swap_date else group.end_date,
        filled_at=datetime.now(timezone.utc),
        md_rate_cost=payload.rate_cost,
        md_rate_revenue=payload.rate_revenue,
        # Tryb „md": budżet nowej linii POWSTAŁ z przeliczenia, a nie z kwoty
        # wpisanej przez operatora. Zapisanie go jako „amount" sugerowałoby
        # kwotę, której nikt nie podał.
        md_input_mode=INPUT_MODE_MD,
        md_input_value=md_total_new,
        md_total=md_total_new,
        md_remaining=md_total_new,
        md_manual_adjustment=Decimal("0"),
        predecessor_order_id=old.id,
        created_by_user_id=user.id,
    )
    db.add(new_line)
    await db.flush()

    value_pln = remaining_value_pln(
        md_remaining=md_remaining_old, rate_revenue=old.md_rate_revenue
    )
    record_event(
        db,
        group_id=group.id,
        order_id=new_line.id,
        event_type=EVENT_CONSULTANT_SWAPPED,
        description=(
            f"Zamiana kontraktora {payload.swap_date.isoformat()}: "
            f"{old_who} ({format_md(old.md_rate_revenue)} zł/MD, "
            f"pozostało {format_md(md_remaining_old)} MD) → "
            f"{new_who} ({format_md(payload.rate_revenue)} zł/MD, "
            f"{format_md(md_total_new)} MD). "
            f"Wartość pozostała bez zmian: {format_md(value_pln)} zł."
        ),
        payload={
            "swap_date": payload.swap_date.isoformat(),
            "old_order_id": old.id,
            "old_consultant": old_who,
            "old_rate_cost": str(old.md_rate_cost),
            "old_rate_revenue": str(old.md_rate_revenue),
            "old_md_remaining": str(md_remaining_old),
            "new_order_id": new_line.id,
            "new_consultant": new_who,
            "new_rate_cost": str(payload.rate_cost),
            "new_rate_revenue": str(payload.rate_revenue),
            "new_md_total": str(md_total_new),
            "remaining_value_pln": str(value_pln),
        },
        user_id=user.id,
    )
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_line_swapped",
            details={"group_id": group.id, "from": old.id, "to": new_line.id},
        )
    )
    await db.commit()

    refreshed = await db.scalar(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.predecessor)
            .selectinload(ClientOrder.contract)
            .selectinload(Contract.candidate),
        )
        .where(ClientOrder.id == new_line.id)
    )
    return _line_to_read(refreshed, with_finance=_can_see_finance(user))
