"""Zapis zamówień w API integracyjnym v1 (``orders:write``, kwoty ``amounts:write``).

Te same ciała co ekran — ``apply_group_close|cancel|extend``
(``client_order_groups``) i ``apply_order_close|update|file``
(``client_orders``) — z ``IntegrationWritePolicy`` (``api/write_policy.py``):
uprawnienia ze scope'ów, zakres całej firmy, autor = konto serwisowe. Reguły,
kody i komunikaty są te same co na ekranie (blokady, sprawy po zakończeniu
współpracy, przedłużenie dziedziczy typ rozliczenia, synchronizacja kontraktu
i dzwonki Delivery Leada w ``commit_order_write``).

Świadomie węziej niż ekran:

* bez zakładania i usuwania zamówień; przedłużenie zakłada wyłącznie
  kontynuację istniejącego zamówienia MD/kosztowego, a jego osoby wskazuje się
  kontraktem u klienta (``contract_id``) — API nie zakłada szkiców kontraktów;
* ``PATCH /orders/{id}`` zmienia tylko ``end_date`` i ``notes``, a z
  ``amounts:write`` także stawki i ich waluty; inne pole = 422. Linia
  zamówienia MD/kosztowego zmienia się przez swoje zamówienie (409);
* bez ``dry_run``: ciała zatwierdzają zapis same (``commit_order_write``),
  a PDF ląduje na dysku przed commitem.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api import client_order_groups as group_routes
from app.api import client_orders as order_routes
from app.api.integrations_v1.common import (
    INT4_MAX,
    AmountLevel,
    IdPath,
    IntegrationRoute,
    OrdersWrite,
    amount_level,
    idempotent_write,
    principal_rate_key,
    write_policy,
    write_rate_limit,
)
from app.api.integrations_v1.orders import (
    OrderGroupOut,
    OrderOut,
    _group_out,
    _order_out,
    _orders_select,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.schemas.client_order import ClientOrderClose, ClientOrderUpdate
from app.schemas.client_order_group import (
    OrderGroupCancel,
    OrderGroupClose,
    OrderGroupExtend,
)

router = APIRouter(route_class=IntegrationRoute)


# ── Wejście ──────────────────────────────────────────────────────────────────


class _StrictIn(BaseModel):
    # Literówka w nazwie pola zapisu nie może przejść po cichu jako „bez zmian”.
    model_config = ConfigDict(extra="forbid")


class GroupCloseIn(_StrictIn):
    closure_date: date
    closure_reason: Optional[str] = Field(None, max_length=1000)


class GroupCancelIn(_StrictIn):
    reason: Optional[str] = Field(None, max_length=1000)


class ExtendLineIn(_StrictIn):
    """Osoba w przedłużeniu — wskazana kontraktem u tego klienta.

    ``input_mode`` + ``input_value`` (budżet MD osoby: liczba MD albo kwota)
    przychodzą razem albo wcale; zamówienie kosztowe i wspólna pula MD nie
    mają budżetu per osoba.
    """

    contract_id: int = Field(..., ge=1, le=INT4_MAX)
    rate_cost: Decimal = Field(..., ge=0, max_digits=12, decimal_places=3)
    rate_revenue: Decimal = Field(..., gt=0, max_digits=12, decimal_places=3)
    rate_candidate_currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$")
    rate_client_currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$")
    input_mode: Optional[Literal["md", "amount"]] = None
    input_value: Optional[Decimal] = Field(None, ge=0, max_digits=16, decimal_places=6)
    optional_md: Optional[Decimal] = Field(None, ge=0, max_digits=16, decimal_places=6)
    start_date: date
    end_date: Optional[date] = None


class GroupExtendIn(_StrictIn):
    order_number: str = Field(..., min_length=1, max_length=64)
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=5000)
    budget_amount: Optional[Decimal] = Field(
        None, gt=0, max_digits=17, decimal_places=3
    )
    md_budget_total: Optional[Decimal] = Field(
        None, gt=0, max_digits=16, decimal_places=6
    )
    lines: list[ExtendLineIn] = Field(default_factory=list, max_length=200)


class OrderCloseIn(_StrictIn):
    closure_date: date
    closure_reason: Optional[str] = Field(None, max_length=500)


class OrderPatchIn(_StrictIn):
    """Pola zmieniane przez API. Pominięte pole zostaje bez zmian, ``null``
    czyści (``end_date: null`` = bezterminowo). Stawki i waluty to kwoty —
    wymagają ``amounts:write``."""

    end_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=5000)
    rate_client: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=3)
    rate_candidate: Optional[Decimal] = Field(
        None, ge=0, max_digits=12, decimal_places=3
    )
    rate_client_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    rate_candidate_currency: Optional[str] = Field(None, min_length=3, max_length=3)


def _screen_model(model_cls: type[BaseModel], data: dict[str, Any]) -> Any:
    """Model ekranu z danych v1 — jego walidatory (np. komplet budżetu linii)
    jako 422 v1, nie 500."""
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(
            422,
            detail={
                "error": "validation_error",
                "message": "Nieprawidłowe dane żądania.",
                "errors": [
                    {
                        "loc": list(err.get("loc", ())),
                        "msg": err.get("msg"),
                        "type": err.get("type"),
                    }
                    for err in exc.errors()
                ],
            },
        ) from None


# ── Odczyt po zapisie ────────────────────────────────────────────────────────


async def _group_client_id(db: AsyncSession, group_id: int) -> int:
    # Sama kolumna, nie encja: ciało czyta grupę świeżo, pod swoimi blokadami.
    client_id = await db.scalar(
        select(ClientOrderGroup.client_id).where(ClientOrderGroup.id == group_id)
    )
    if client_id is None:
        raise HTTPException(404, detail="Zamówienie nie istnieje.")
    return client_id


async def _order_row(db: AsyncSession, order_id: int):
    # Kolumny, nie encja — encja w sesji przed `SELECT … FOR UPDATE` ciała
    # zostałaby z wartościami sprzed blokady.
    row = (
        await db.execute(
            select(ClientOrder.client_id, ClientOrder.order_group_id).where(
                ClientOrder.id == order_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(404, detail="Zamówienie nie istnieje.")
    return row


async def _group_response(
    db: AsyncSession, group_id: int, *, level: AmountLevel
) -> OrderGroupOut:
    group = await db.scalar(
        select(ClientOrderGroup)
        .options(selectinload(ClientOrderGroup.client))
        .where(ClientOrderGroup.id == group_id)
        .execution_options(populate_existing=True)
    )
    return (await _group_out(db, [group], level=level))[0]


async def _order_response(
    db: AsyncSession, order_id: int, *, level: AmountLevel
) -> OrderOut:
    row = (await db.execute(_orders_select().where(ClientOrder.id == order_id))).first()
    return _order_out(row, level=level)


def _json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_unset=True)


# ── Zamówienia MD i kosztowe ────────────────────────────────────────────────


@router.post(
    "/order-groups/{group_id}/close",
    response_model=OrderGroupOut,
    summary="Zakończ zamówienie MD / kosztowe",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def close_order_group(
    request: Request,
    group_id: IdPath,
    body: GroupCloseIn,
    caller: OrdersWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Jak „Zakończ” na ekranie: data końca zapisuje się zamówieniu i otwartym
    liniom od razu, status ``completed`` linie dostają, gdy dzień nadejdzie.
    Data wstecz jest dozwolona (nie wcześniejsza niż start zamówienia)."""

    async def run():
        client_id = await _group_client_id(db, group_id)
        group = await group_routes.apply_group_close(
            db,
            client_id,
            group_id,
            OrderGroupClose(
                closure_date=body.closure_date, closure_reason=body.closure_reason
            ),
            policy=write_policy(caller, db),
        )
        return 200, await _group_response(db, group.id, level=amount_level(caller))

    return await idempotent_write(
        request, db, caller, payload={"group_id": group_id, **_json(body)}, run=run
    )


@router.post(
    "/order-groups/{group_id}/cancel",
    response_model=OrderGroupOut,
    summary="Anuluj zamówienie MD / kosztowe",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def cancel_order_group(
    request: Request,
    group_id: IdPath,
    body: GroupCancelIn,
    caller: OrdersWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Zamówienie, które nie doszło do skutku. Tylko bez rozliczeń (zejścia
    MD, faktury) — takie się kończy, nie anuluje (409
    ``order_group_has_settlements``). Przywrócenie — na ekranie."""

    async def run():
        client_id = await _group_client_id(db, group_id)
        group = await group_routes.apply_group_cancel(
            db,
            client_id,
            group_id,
            OrderGroupCancel(reason=body.reason),
            policy=write_policy(caller, db),
        )
        return 200, await _group_response(db, group.id, level=amount_level(caller))

    return await idempotent_write(
        request, db, caller, payload={"group_id": group_id, **_json(body)}, run=run
    )


@router.post(
    "/order-groups/{group_id}/extend",
    response_model=OrderGroupOut,
    status_code=201,
    summary="Przedłuż zamówienie MD / kosztowe (nowe zamówienie)",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def extend_order_group(
    request: Request,
    group_id: IdPath,
    body: GroupExtendIn,
    caller: OrdersWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Nowe zamówienie kontynuujące wskazane (nowy numer, okres i budżety);
    poprzednie zostaje w rejestrze bez zmian. Typ rozliczenia dziedziczy się
    po poprzedniku: kosztowe wymaga ``budget_amount``, wspólna pula MD —
    ``md_budget_total``. Osoby (``lines``), kwota i pula to kwoty —
    wymagają ``amounts:write``."""

    async def run():
        client_id = await _group_client_id(db, group_id)
        payload = _screen_model(
            OrderGroupExtend,
            {
                **body.model_dump(exclude={"lines"}),
                "lines": [line.model_dump(exclude_unset=True) for line in body.lines],
            },
        )
        group = await group_routes.apply_group_extend(
            db, client_id, group_id, payload, policy=write_policy(caller, db)
        )
        return 201, await _group_response(db, group.id, level=amount_level(caller))

    return await idempotent_write(
        request,
        db,
        caller,
        payload={"group_id": group_id, **body.model_dump(mode="json")},
        run=run,
    )


# ── Zamówienia okresowe ─────────────────────────────────────────────────────


def _reject_group_line(order_group_id: Optional[int]) -> None:
    if order_group_id is not None:
        raise HTTPException(
            409,
            detail={
                "code": "order_belongs_to_group",
                "message": (
                    "To jest linia zamówienia MD/kosztowego — zmieniaj ją przez "
                    "zamówienie, do którego należy (/order-groups/{id})."
                ),
                "order_group_id": order_group_id,
            },
        )


@router.post(
    "/orders/{order_id}/close",
    response_model=OrderOut,
    summary="Zakończ zamówienie okresowe",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def close_order(
    request: Request,
    order_id: IdPath,
    body: OrderCloseIn,
    caller: OrdersWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Kończy JEDNO zamówienie, bez dotykania umowy. Data zapisuje się od razu,
    status ``completed`` — gdy dzień nadejdzie. Szkic (409 ``order_is_draft``)
    i linia zamówienia MD (409 ``order_belongs_to_group``) się nie kończą."""

    async def run():
        row = await _order_row(db, order_id)
        order = await order_routes.apply_order_close(
            db,
            row.client_id,
            order_id,
            ClientOrderClose(
                closure_date=body.closure_date, closure_reason=body.closure_reason
            ),
            policy=write_policy(caller, db),
        )
        return 200, await _order_response(db, order.id, level=amount_level(caller))

    return await idempotent_write(
        request, db, caller, payload={"order_id": order_id, **_json(body)}, run=run
    )


@router.patch(
    "/orders/{order_id}",
    response_model=OrderOut,
    summary="Zmień zamówienie okresowe (data końca, notatka, stawki)",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def update_order(
    request: Request,
    order_id: IdPath,
    body: OrderPatchIn,
    caller: OrdersWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Te same reguły co edycja na ekranie: okres nie nachodzi na inne
    zamówienie tej osoby, nowy okres przelicza status, zamówienie trwające
    wskrzesza zakończony kontrakt. Inne pole niż wymienione = 422."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            422,
            detail={
                "error": "validation_error",
                "message": "Podaj co najmniej jedno pole do zmiany.",
            },
        )

    async def run():
        row = await _order_row(db, order_id)
        _reject_group_line(row.order_group_id)
        order = await order_routes.apply_order_update(
            db,
            row.client_id,
            order_id,
            _screen_model(ClientOrderUpdate, changes),
            policy=write_policy(caller, db),
        )
        return 200, await _order_response(db, order.id, level=amount_level(caller))

    return await idempotent_write(
        request, db, caller, payload={"order_id": order_id, **_json(body)}, run=run
    )


@router.put(
    "/orders/{order_id}/file",
    response_model=OrderOut,
    summary="Wgraj albo podmień PDF zamówienia",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def put_order_file(
    request: Request,
    order_id: IdPath,
    caller: OrdersWrite,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="PDF zamówienia (do 25 MB)."),
) -> Response:
    """Jeden PDF na zamówienie — nowy zastępuje poprzedni (tylko PDF, 415 dla
    innych). Bez ``dry_run``: plik zapisuje się przed zatwierdzeniem."""
    content = await file.read(order_routes.MAX_UPLOAD_BYTES + 1)
    digest = hashlib.sha256(content).hexdigest()
    await file.seek(0)

    async def run():
        row = await _order_row(db, order_id)
        order = await order_routes.apply_order_file(
            db, row.client_id, order_id, file, policy=write_policy(caller, db)
        )
        return 200, await _order_response(db, order.id, level=amount_level(caller))

    return await idempotent_write(
        request,
        db,
        caller,
        payload={
            "order_id": order_id,
            "file_sha256": digest,
            "filename": file.filename,
        },
        run=run,
    )
