"""Router `/api/md-consumption` — import zużycia MD z arkusza Finansów.

Operator z Finansów wgrywa miesięczny raport (konsultant → zaraportowane MD),
a system odejmuje MD od budżetów aktywnych linii zamówień.

**Dopasowanie idzie WYŁĄCZNIE po imieniu i nazwisku**, bo arkusz nie zawiera
numeru zamówienia. Stąd trzy możliwe wyniki wiersza i tylko jeden z nich jest
automatyczny:

* dokładnie jedna aktywna linia → ``Zaktualizowano``,
* zero linii → ``Brak aktywnego zamówienia`` (wiersz zostaje, nie przerywa
  importu reszty),
* więcej niż jedna → ``Wymaga przypisania``; system NIE wybiera za człowieka.
  Trafienie w złe zamówienie odjęłoby MD nie temu klientowi i wyszło dopiero
  na fakturze, więc niejednoznaczność jest zostawiana do rozstrzygnięcia.

Import jest idempotentny per (linia, miesiąc): powtórka tego samego miesiąca
NADPISUJE wcześniejszy wpis konsumpcji i przelicza pozostałość od
``md_total``, zamiast odjąć MD po raz drugi.

Dostęp: ``FinanceManageUser`` (admin + rola Finanse). Projekcja wierszy jest
świadomie wąska — nazwisko przyszło z pliku, który ten użytkownik sam wgrał,
a poza nim widzi wyłącznie numer zamówienia i klienta, czyli minimum potrzebne
do rozstrzygnięcia i zafakturowania. Bez identyfikatorów kandydatów, kontraktów
i stawek: moduł Finanse nie jest powierzchnią kandydacką.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.financial_access import FinanceManageUser
from app.core.database import get_db
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract
from app.models.md_consumption import (
    IMPORT_ROW_APPLIED,
    IMPORT_ROW_NEEDS_ASSIGNMENT,
    IMPORT_ROW_STATUS_LABELS,
    IMPORT_ROW_UNMATCHED,
    MdConsumptionImport,
    MdConsumptionImportRow,
)
from app.schemas.md_consumption import (
    AssignRowRequest,
    ImportDetail,
    ImportListResponse,
    ImportRowRead,
    ImportSummary,
    LineOption,
)
from app.services.client_order_lines import (
    LineMatch,
    active_md_lines,
    describe_import,
    match_by_name,
    month_bounds,
    record_event,
    upsert_consumption,
)
from app.services.md_import_parser import MdSheetFormatError, parse_md_sheet
from app.services.multi_consultant_orders import EVENT_MD_IMPORT

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_ALLOWED_EXT = (".xlsx", ".xlsm")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _option_from_match(match: LineMatch, client_name: str) -> LineOption:
    return LineOption(
        order_id=match.order.id,
        order_number=match.group.order_number,
        client_id=match.group.client_id,
        client_name=client_name,
        consultant_name=match.consultant_name,
        md_remaining=match.order.md_remaining,
    )


async def _client_names(db: AsyncSession, client_ids: set[int]) -> dict[int, str]:
    if not client_ids:
        return {}
    rows = await db.execute(
        select(Client.id, Client.name).where(Client.id.in_(client_ids))
    )
    return {cid: name for cid, name in rows}


async def _row_to_read(db: AsyncSession, row: MdConsumptionImportRow) -> ImportRowRead:
    """Wiersz importu wraz z opcjami do wyboru (dla „wymaga przypisania")."""
    order_ids: set[int] = set()
    if row.matched_order_id:
        order_ids.add(row.matched_order_id)
    for oid in row.candidate_order_ids or []:
        try:
            order_ids.add(int(oid))
        except (TypeError, ValueError):
            continue

    options_by_id: dict[int, LineOption] = {}
    if order_ids:
        result = await db.execute(
            select(ClientOrder)
            .options(
                selectinload(ClientOrder.contract).selectinload(Contract.candidate),
                selectinload(ClientOrder.order_group),
            )
            .where(ClientOrder.id.in_(order_ids))
        )
        orders = list(result.scalars())
        names = await _client_names(db, {o.client_id for o in orders})
        for order in orders:
            group: Optional[ClientOrderGroup] = order.order_group
            candidate = order.contract.candidate if order.contract else None
            options_by_id[order.id] = LineOption(
                order_id=order.id,
                order_number=group.order_number if group else "—",
                client_id=order.client_id,
                client_name=names.get(order.client_id, "—"),
                consultant_name=(
                    f"{candidate.name or ''} {candidate.lastname or ''}".strip()
                    if candidate
                    else "—"
                ),
                md_remaining=order.md_remaining,
            )

    return ImportRowRead(
        id=row.id,
        row_number=row.row_number,
        consultant_name=row.consultant_name,
        md_reported=row.md_reported,
        status=row.status,
        status_label=IMPORT_ROW_STATUS_LABELS.get(row.status, row.status),
        matched_order_id=row.matched_order_id,
        matched=options_by_id.get(row.matched_order_id or -1),
        options=[
            options_by_id[int(oid)]
            for oid in (row.candidate_order_ids or [])
            if int(oid) in options_by_id
        ],
        resolved_at=row.resolved_at,
    )


def _summary(batch: MdConsumptionImport) -> ImportSummary:
    return ImportSummary(
        id=batch.id,
        period_month=batch.period_month,
        filename=batch.filename,
        rows_total=batch.rows_total,
        rows_applied=batch.rows_applied,
        rows_ambiguous=batch.rows_ambiguous,
        rows_unmatched=batch.rows_unmatched,
        uploaded_by_user_id=batch.uploaded_by_user_id,
        created_at=batch.created_at,
    )


async def _recount(db: AsyncSession, batch: MdConsumptionImport) -> None:
    """Przelicz liczniki partii z faktycznych statusów wierszy.

    Liczniki są przeliczane, a nie inkrementowane przy rozstrzyganiu: licznik
    modyfikowany krokowo rozjeżdża się przy każdym nieoczekiwanym przebiegu,
    a to on jest tym, co operator czyta jako „ile zostało do zrobienia".
    """
    result = await db.execute(
        select(MdConsumptionImportRow.status).where(
            MdConsumptionImportRow.import_id == batch.id
        )
    )
    statuses = [s for (s,) in result]
    batch.rows_total = len(statuses)
    batch.rows_applied = sum(1 for s in statuses if s == IMPORT_ROW_APPLIED)
    batch.rows_ambiguous = sum(1 for s in statuses if s == IMPORT_ROW_NEEDS_ASSIGNMENT)
    batch.rows_unmatched = sum(1 for s in statuses if s == IMPORT_ROW_UNMATCHED)


async def _apply_to_line(
    db: AsyncSession,
    *,
    match_order: ClientOrder,
    group_id: Optional[int],
    period_month: str,
    md_reported,
    import_id: int,
    user_id: int,
) -> None:
    _, previous, _ = await upsert_consumption(
        db,
        order=match_order,
        period_month=period_month,
        md_reported=md_reported,
        import_id=import_id,
        user_id=user_id,
    )
    if group_id:
        record_event(
            db,
            group_id=group_id,
            order_id=match_order.id,
            event_type=EVENT_MD_IMPORT,
            description=describe_import(
                match_order, period_month, md_reported, previous
            ),
            payload={
                "period_month": period_month,
                "md_reported": str(md_reported),
                "md_previous": str(previous),
                "md_remaining": str(match_order.md_remaining),
                "import_id": import_id,
            },
            user_id=user_id,
        )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post(
    "/imports", response_model=ImportDetail, status_code=status.HTTP_201_CREATED
)
async def create_import(
    user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    period_month: str = Form(...),
):
    """Wgraj miesięczny raport MD i zastosuj go do aktywnych linii."""
    try:
        month_bounds(period_month)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    filename = file.filename or "raport.xlsx"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(415, detail="Tylko pliki XLSX")

    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, detail=f"Plik przekracza {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
        )
    if not payload:
        raise HTTPException(400, detail="Pusty plik")

    try:
        parsed = parse_md_sheet(payload)
    except MdSheetFormatError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    candidates = await active_md_lines(db, period_month)

    batch = MdConsumptionImport(
        period_month=period_month,
        filename=filename[:255],
        uploaded_by_user_id=user.id,
    )
    db.add(batch)
    await db.flush()

    for parsed_row in parsed.rows:
        matches = match_by_name(candidates, parsed_row.consultant_name)
        row = MdConsumptionImportRow(
            import_id=batch.id,
            row_number=parsed_row.row_number,
            consultant_name=parsed_row.consultant_name[:255],
            md_reported=parsed_row.md_reported,
            status=IMPORT_ROW_UNMATCHED,
        )
        if len(matches) == 1:
            match = matches[0]
            row.status = IMPORT_ROW_APPLIED
            row.matched_order_id = match.order.id
            await _apply_to_line(
                db,
                match_order=match.order,
                group_id=match.group.id,
                period_month=period_month,
                md_reported=parsed_row.md_reported,
                import_id=batch.id,
                user_id=user.id,
            )
        elif len(matches) > 1:
            row.status = IMPORT_ROW_NEEDS_ASSIGNMENT
            row.candidate_order_ids = [m.order.id for m in matches]
        db.add(row)

    await db.flush()
    await _recount(db, batch)
    await db.commit()
    await db.refresh(batch)

    return await _detail(db, batch, parsed_sheet=parsed)


async def _detail(
    db: AsyncSession, batch: MdConsumptionImport, *, parsed_sheet=None
) -> ImportDetail:
    result = await db.execute(
        select(MdConsumptionImportRow)
        .where(MdConsumptionImportRow.import_id == batch.id)
        .order_by(MdConsumptionImportRow.row_number.asc())
    )
    rows = [await _row_to_read(db, r) for r in result.scalars()]
    base = _summary(batch)
    return ImportDetail(
        **base.model_dump(),
        rows=rows,
        skipped_rows=list(parsed_sheet.skipped_rows) if parsed_sheet else [],
        sheet_name=parsed_sheet.sheet_name if parsed_sheet else None,
    )


@router.get("/imports", response_model=ImportListResponse)
async def list_imports(
    user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    """Ostatnie partie importu — od najnowszej."""
    result = await db.execute(
        select(MdConsumptionImport)
        .order_by(MdConsumptionImport.created_at.desc(), MdConsumptionImport.id.desc())
        .limit(max(1, min(limit, 100)))
    )
    return ImportListResponse(imports=[_summary(b) for b in result.scalars()])


@router.get("/imports/{import_id}", response_model=ImportDetail)
async def get_import(
    import_id: int,
    user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    batch = await db.scalar(
        select(MdConsumptionImport).where(MdConsumptionImport.id == import_id)
    )
    if batch is None:
        raise HTTPException(404, detail="Import nie istnieje")
    return await _detail(db, batch)


@router.post("/imports/{import_id}/rows/{row_id}/assign", response_model=ImportRowRead)
async def assign_row(
    import_id: int,
    row_id: int,
    payload: AssignRowRequest,
    user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    """Ręczne rozstrzygnięcie wiersza „Wymaga przypisania"."""
    row = await db.scalar(
        select(MdConsumptionImportRow).where(
            MdConsumptionImportRow.id == row_id,
            MdConsumptionImportRow.import_id == import_id,
        )
    )
    if row is None:
        raise HTTPException(404, detail="Wiersz importu nie istnieje")
    if row.status != IMPORT_ROW_NEEDS_ASSIGNMENT:
        raise HTTPException(
            409,
            detail="Ten wiersz nie czeka na przypisanie — został już rozstrzygnięty.",
        )

    allowed = {int(o) for o in (row.candidate_order_ids or [])}
    if payload.order_id not in allowed:
        # Wybór spoza listy kandydatów oznacza, że linia nie pasowała do
        # nazwiska ALBO nie była aktywna w tym miesiącu. Przyjęcie go tutaj
        # obeszłoby oba filtry naraz.
        raise HTTPException(
            422,
            detail="To zamówienie nie jest jednym z dopasowań tego wiersza.",
        )

    batch = await db.scalar(
        select(MdConsumptionImport).where(MdConsumptionImport.id == import_id)
    )
    if batch is None:
        raise HTTPException(404, detail="Import nie istnieje")

    order = await db.scalar(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.order_group),
        )
        .where(ClientOrder.id == payload.order_id)
    )
    if order is None:
        raise HTTPException(404, detail="Linia zamówienia nie istnieje")
    # Lista kandydatów powstała przy wgraniu pliku, a rozstrzygnięcie następuje
    # później — w międzyczasie linia mogła zostać domknięta (np. zamianą
    # kontraktora). Zapis MD na nieaktywną linię tworzy zużycie, którego
    # `active_md_lines` już nigdy nie pokaże: nie da się go zobaczyć ani cofnąć
    # z interfejsu, a policzy się do faktury.
    if order.status != ClientOrderStatus.active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Ta linia nie jest już aktywna — w międzyczasie została "
                "zakończona lub zamieniona. Wybierz inne zamówienie."
            ),
        )

    await _apply_to_line(
        db,
        match_order=order,
        group_id=order.order_group_id,
        period_month=batch.period_month,
        md_reported=row.md_reported,
        import_id=batch.id,
        user_id=user.id,
    )
    row.status = IMPORT_ROW_APPLIED
    row.matched_order_id = order.id
    row.resolved_by_user_id = user.id
    row.resolved_at = datetime.now(timezone.utc)

    await db.flush()
    await _recount(db, batch)
    await db.commit()
    await db.refresh(row)
    return await _row_to_read(db, row)
