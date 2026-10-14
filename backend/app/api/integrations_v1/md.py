"""Zużycie MD w API integracyjnym v1 (``md:read`` / ``md:write``).

* Import raportu MD (XLSX) — ta sama droga co ekran Finansów
  (``api/md_consumption.run_md_import``), z ``dry_run`` (przeliczenie bez
  zapisu) i ochroną przed powtórnym importem tego samego pliku za ten sam
  miesiąc (409 ``duplicate_import``, świadomie ``force=true``).
* Przypisanie wiersza „Wymaga przypisania” — bez zatwierdzania przekroczeń
  salda i bez wspólnych pul MD: tam decyduje człowiek na ekranie (ticket 1.1).
* Ręczna korekta MD linii za miesiąc — nadpisuje miesiąc jak na ekranie
  (klucz ``(linia, miesiąc)``), nigdy nie dokłada.

Każdy zapis wymaga ``Idempotency-Key``; autor = konto serwisowe (dziennik
zamówienia, Historia zdarzeń, „Importy MD”).

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import hashlib
from decimal import Decimal
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api import client_order_groups as group_routes
from app.api import md_consumption as md_routes
from app.api.integrations_v1.common import (
    IdPath,
    IntegrationRoute,
    MdRead,
    MdWrite,
    Page,
    PageQuery,
    dry_run_response,
    idempotent_write,
    integration_actor,
    page_of,
    principal_of,
    principal_rate_key,
    read_rate_limit,
    write_rate_limit,
)
from app.api.integrations_v1.orders import OrderOut, _order_out, _orders_select
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.client_order import ClientOrder
from app.models.md_consumption import (
    CONSUMPTION_SOURCE_MANUAL,
    IMPORT_ROW_NEEDS_ASSIGNMENT,
    MdConsumptionImport,
    MdConsumptionImportRow,
)
from app.schemas.client_order_group import LineConsumptionUpsert
from app.schemas.md_consumption import (
    AssignRowRequest,
    ImportDetail,
    ImportRowRead,
    ImportSummary,
)
from app.services.client_order_lines import (
    consultant_display_name,
    format_period_month,
    record_event,
    upsert_consumption,
)
from app.services.multi_consultant_orders import (
    CONSUMPTION_STATUS_LABELS,
    EVENT_MANUAL_EDIT,
    format_md,
    quantize_md,
)
from app.services.order_write_errors import commit_order_write
from app.services.shared_md_orders import uses_shared_md_pool

router = APIRouter(route_class=IntegrationRoute)


def _requires_screen(message: str) -> HTTPException:
    return HTTPException(
        409, detail={"error": "requires_screen_approval", "message": message}
    )


# ── Odczyt ───────────────────────────────────────────────────────────────────


@router.get("/md/imports", response_model=Page[ImportSummary], summary="Importy MD")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_md_imports(
    request: Request,
    _caller: MdRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: int = Query(50, ge=1, le=200),
    period_month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
) -> dict:
    """Partie importu raportów MD — od najnowszej."""
    query = select(MdConsumptionImport)
    if period_month:
        query = query.where(MdConsumptionImport.period_month == period_month)
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    batches = (
        (
            await db.execute(
                query.order_by(
                    MdConsumptionImport.created_at.desc(), MdConsumptionImport.id.desc()
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = [md_routes._summary(b) for b in batches]
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get(
    "/md/imports/{import_id}",
    response_model=ImportDetail,
    summary="Import MD z wierszami",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_md_import(
    request: Request,
    import_id: IdPath,
    _caller: MdRead,
    db: AsyncSession = Depends(get_db),
) -> ImportDetail:
    batch = await db.get(MdConsumptionImport, import_id)
    if batch is None:
        raise HTTPException(404, detail="Import nie istnieje.")
    return await md_routes._detail(db, batch)


# ── Import raportu ───────────────────────────────────────────────────────────


@router.post(
    "/md/imports",
    response_model=ImportDetail,
    status_code=201,
    summary="Import raportu MD (XLSX)",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def create_md_import(
    request: Request,
    caller: MdWrite,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="Raport MD w formacie XLSX."),
    period_month: str = Form(..., pattern=r"^\d{4}-\d{2}$"),
    dry_run: bool = Query(False, description="Przelicz bez zapisu."),
    force: bool = Query(
        False, description="Zaimportuj mimo identycznego pliku za ten miesiąc."
    ),
) -> Response:
    """Zaksięguj raport MD na linie zamówień (jak „Importy MD” w Finansach).

    Wiersze bez jednoznacznego dopasowania i przekroczenia salda czekają na
    człowieka (``needs_assignment`` / ``overflow``) — automat ich nie zatwierdza.
    """
    principal = principal_of(caller)
    payload = await file.read(md_routes.MAX_UPLOAD_BYTES + 1)
    digest = hashlib.sha256(payload).hexdigest()
    filename = file.filename or "raport.xlsx"

    async def run():
        if not force:
            existing = await db.scalar(
                select(MdConsumptionImport.id).where(
                    MdConsumptionImport.period_month == period_month,
                    MdConsumptionImport.file_sha256 == digest,
                )
            )
            if existing is not None:
                raise HTTPException(
                    409,
                    detail={
                        "error": "duplicate_import",
                        "message": "Ten sam plik za ten miesiąc został już "
                        "zaimportowany. Powtórka podwoiłaby zużycie; świadomie: "
                        "force=true.",
                        "import_id": existing,
                    },
                )
        batch, parsed = await md_routes.run_md_import(
            db,
            payload=payload,
            filename=filename,
            period_month=period_month,
            user_id=None,
            service_account_id=principal.account_id,
        )
        return 201, await md_routes._detail(db, batch, parsed_sheet=parsed)

    if dry_run:
        return await dry_run_response(db, run)
    return await idempotent_write(
        request,
        db,
        caller,
        payload={"period_month": period_month, "file_sha256": digest, "force": force},
        run=run,
    )


# ── Przypisanie wiersza ──────────────────────────────────────────────────────


class AssignIn(BaseModel):
    """Linia z listy dopasowań wiersza. Bez ``confirm_overflow`` z ekranu —
    przekroczenie salda zatwierdza człowiek."""

    order_id: int = Field(..., ge=1, le=2_147_483_647)


@router.post(
    "/md/imports/{import_id}/rows/{row_id}/assign",
    response_model=ImportRowRead,
    summary="Przypisz wiersz importu do linii zamówienia",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def assign_md_import_row(
    request: Request,
    import_id: IdPath,
    row_id: IdPath,
    body: AssignIn,
    caller: MdWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Rozstrzygnij wiersz „Wymaga przypisania” wybraną linią z jego listy."""

    async def run():
        row = await db.scalar(
            select(MdConsumptionImportRow).where(
                MdConsumptionImportRow.id == row_id,
                MdConsumptionImportRow.import_id == import_id,
            )
        )
        if row is None:
            raise HTTPException(404, detail="Wiersz importu nie istnieje.")
        if row.status != IMPORT_ROW_NEEDS_ASSIGNMENT:
            raise _requires_screen(
                "Wiersz nie czeka na przypisanie (przekroczenie salda albo już "
                "rozstrzygnięty) — decyzja na ekranie."
            )
        order = await db.scalar(
            select(ClientOrder)
            .options(selectinload(ClientOrder.order_group))
            .where(ClientOrder.id == body.order_id)
        )
        if (
            order is not None
            and order.order_group is not None
            and uses_shared_md_pool(order.order_group)
        ):
            raise _requires_screen(
                "Przypisanie do wspólnej puli MD jest tylko na ekranie."
            )
        # Handler ekranu czyta z „osoby” wyłącznie `.id` (autor = None, ślad
        # konta przez stempel sesji). Sam commituje — paragon `pending` wchodzi
        # razem ze zmianą (patrz `integration_receipts`).
        result = await md_routes.assign_row(
            import_id=import_id,
            row_id=row_id,
            payload=AssignRowRequest(order_id=body.order_id, confirm_overflow=False),
            user=integration_actor(caller),
            db=db,
        )
        return 200, result

    return await idempotent_write(
        request,
        db,
        caller,
        payload={"import_id": import_id, "row_id": row_id, "order_id": body.order_id},
        run=run,
    )


# ── Korekta MD za miesiąc ────────────────────────────────────────────────────


@router.put(
    "/orders/{order_id}/md-consumptions/{period_month}",
    response_model=OrderOut,
    summary="Zużycie MD linii za miesiąc (wpis albo nadpisanie)",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def put_order_md_consumption(
    request: Request,
    order_id: IdPath,
    period_month: str,
    body: LineConsumptionUpsert,
    caller: MdWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Ręczny wpis zejścia MD linii za miesiąc ``RRRR-MM``.

    Powtórzenie NADPISUJE miesiąc i przelicza saldo od zera — nigdy nie
    dokłada (ten sam klucz co import).
    """
    principal = principal_of(caller)
    month = group_routes._validated_period_month(period_month)

    async def run():
        order = await db.get(ClientOrder, order_id)
        if order is None or order.order_group_id is None:
            raise HTTPException(
                404,
                detail="Linia zamówienia MD nie istnieje (samodzielne zamówienie nie ma zejść MD).",
            )
        group = await group_routes._load_group(
            db, order.client_id, order.order_group_id
        )
        group_routes._assert_group_not_cancelled(group)
        line = await group_routes._md_line_for_consumptions(
            db, group=group, line_id=order.id, for_update=True
        )
        await group_routes._assert_no_pending_offboarding_case(
            db, group_id=group.id, order_id=line.id
        )
        _row, previous, remaining = await upsert_consumption(
            db,
            order=line,
            period_month=month,
            md_reported=body.md_reported,
            source=CONSUMPTION_SOURCE_MANUAL,
            user_id=None,
            status=body.status,
            note=body.note,
        )
        value = quantize_md(body.md_reported)
        status_label = (
            CONSUMPTION_STATUS_LABELS.get(body.status, body.status)
            if body.status
            else "bez statusu"
        )
        overwritten = (
            f", nadpisano wcześniejsze {format_md(previous)} MD"
            if previous and previous != value
            else ""
        )
        record_event(
            db,
            group_id=group.id,
            order_id=line.id,
            event_type=EVENT_MANUAL_EDIT,
            description=(
                f"{consultant_display_name(line)} — zejście MD za "
                f"{format_period_month(month)}: {format_md(value)} MD "
                f"({status_label}{overwritten}). Pozostało {format_md(remaining)} MD. "
                f"Zapisała {principal.display_label}."
            ),
            payload={
                "changed": ["zejście MD"],
                "period_month": month,
                "md_reported": str(value),
                "previous": str(previous),
                "status": body.status,
                "note": body.note,
                "md_remaining": str(remaining),
                "actor": principal.display_label,
            },
            user_id=None,
        )
        await commit_order_write(db)
        row = (
            await db.execute(_orders_select().where(ClientOrder.id == line.id))
        ).first()
        return 200, _order_out(row, with_amounts=False)

    return await idempotent_write(
        request,
        db,
        caller,
        payload={
            "order_id": order_id,
            "period_month": month,
            "md_reported": str(Decimal(str(body.md_reported))),
            "status": body.status,
            "note": body.note,
        },
        run=run,
    )
