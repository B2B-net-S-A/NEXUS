"""„Importy MD" na profilu klienta (ticket 7, 25.09.2026).

Import zużycia MD z Finansów był widoczny wyłącznie jako wpisy historii
poszczególnych zamówień, a pełny podgląd importu (``/api/md-consumption``)
jest za bramką Finansów. Delivery Lead nie miał gdzie zobaczyć, co jeden
arkusz zrobił z zamówieniami JEGO klienta.

Ten router pokazuje importy, które dotknęły klienta, i WYŁĄCZNIE wiersze tego
klienta: zaksięgowane na jego zamówienia, czekające na wybór między jego
liniami albo niosące w „Uwagach" numer jego zamówienia. Wiersze innych
klientów (nazwiska, kwoty) nie wychodzą — ta sama bramka co karta zamówień
(``_require_safe_group_read``), kwoty tylko z dostępem do finansów klienta.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.client_order_groups import (
    OrderGroupSafeReadUser,
    _assert_multi_client,
    _can_see_finance,
    _require_safe_group_read,
)
from app.api.md_consumption import (
    _reason_context,
    _row_status_label,
    _unmatched_reason,
)
from app.api.delivery_client_scope import DELIVERY_CLIENT_SCOPE_DEPENDENCIES
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.models.md_consumption import (
    COST_ROW_APPLIED,
    IMPORT_ROW_APPLIED,
    IMPORT_ROW_COST_ONLY,
    IMPORT_ROW_NEEDS_ASSIGNMENT,
    IMPORT_ROW_OVERFLOW,
    IMPORT_ROW_UNMATCHED,
    MdConsumptionImport,
    MdConsumptionImportRow,
)
from app.models.user import User
from app.schemas.client_order_group import MdValue, MoneyPLN
from app.services import finance_order_matching
from app.services.md_consumption_view import is_foreign_number, same_order_number

router = APIRouter(
    dependencies=[*DELIVERY_SECTION_DEPENDENCIES, *DELIVERY_CLIENT_SCOPE_DEPENDENCIES]
)

RowState = Literal["booked", "to_verify", "error", "neutral"]

ROW_STATE_LABELS: dict[str, str] = {
    "booked": "Zaksięgowano",
    "to_verify": "Do weryfikacji",
    "error": "Błąd",
    "neutral": "Bez zamówienia MD",
}


class ClientMdImportSummary(BaseModel):
    id: int
    period_month: str
    filename: Optional[str] = None
    created_at: datetime
    uploaded_by_name: Optional[str] = None
    rows_total: int = 0
    rows_booked: int = 0
    rows_to_verify: int = 0
    rows_error: int = 0
    md_booked: MdValue = Decimal("0")


class ClientMdImportRow(BaseModel):
    id: int
    row_number: int
    consultant_name: str
    order_number_hint: Optional[str] = None
    target_order_number: Optional[str] = None
    target_group_id: Optional[int] = None
    md_reported: MdValue
    invoice_amount: Optional[MoneyPLN] = None
    state: RowState
    state_label: str
    status_label: str
    status_reason: Optional[str] = None
    number_mismatch: bool = False
    """Numer z „Uwag" różni się od zamówienia, na które trafił wiersz."""


class ClientMdImportDetail(ClientMdImportSummary):
    rows: list[ClientMdImportRow] = Field(default_factory=list)


class ClientMdImportListResponse(BaseModel):
    imports: list[ClientMdImportSummary] = Field(default_factory=list)


def row_state(row: MdConsumptionImportRow, has_reason: bool) -> RowState:
    """Lustro ``importRowTone`` (``lib/md-import-row-tone.ts``) w trzech stanach."""
    if row.status == IMPORT_ROW_APPLIED:
        return "booked"
    if row.status in (IMPORT_ROW_NEEDS_ASSIGNMENT, IMPORT_ROW_OVERFLOW):
        return "to_verify"
    if row.cost_status == COST_ROW_APPLIED:
        return "booked"
    if has_reason or row.cost_status is not None:
        return "error"
    if row.status == IMPORT_ROW_COST_ONLY:
        return "error"
    return "neutral"


class _ClientScope:
    """Zamówienia klienta: linie, grupy i numery — do zawężenia wierszy."""

    def __init__(self, line_group: dict[int, int], groups: dict[int, str]) -> None:
        self.line_group = line_group
        self.groups = groups

    def target_group(self, row: MdConsumptionImportRow) -> Optional[int]:
        if row.matched_order_id is not None and row.matched_order_id in self.line_group:
            return self.line_group[row.matched_order_id]
        if row.matched_group_id is not None and row.matched_group_id in self.groups:
            return row.matched_group_id
        return None

    def touches(self, row: MdConsumptionImportRow) -> bool:
        if self.target_group(row) is not None:
            return True
        # Wiersz zaksięgowany u INNEGO klienta nigdy nie jest wierszem tego
        # klienta — niezależnie od numeru w „Uwagach" (przegląd 25.09.2026:
        # luźne porównanie numerów pokazywało cudze faktury).
        if row.matched_order_id is not None or row.matched_group_id is not None:
            return False
        for oid in row.candidate_order_ids or []:
            try:
                if int(oid) in self.line_group:
                    return True
            except (TypeError, ValueError):
                continue
        if row.status in (IMPORT_ROW_UNMATCHED, IMPORT_ROW_COST_ONLY) and (
            row.order_number_hint
        ):
            return any(
                same_order_number(row.order_number_hint, number)
                for number in self.groups.values()
            )
        return False


async def _client_scope(db: AsyncSession, client_id: int) -> _ClientScope:
    groups = {
        gid: number
        for gid, number in (
            await db.execute(
                select(ClientOrderGroup.id, ClientOrderGroup.order_number).where(
                    ClientOrderGroup.client_id == client_id
                )
            )
        ).all()
    }
    line_group = {
        oid: gid
        for oid, gid in (
            await db.execute(
                select(ClientOrder.id, ClientOrder.order_group_id).where(
                    ClientOrder.client_id == client_id,
                    ClientOrder.order_group_id.isnot(None),
                )
            )
        ).all()
    }
    return _ClientScope(line_group, groups)


def _summary(
    batch: MdConsumptionImport,
    uploader: Optional[str],
    rows: list[tuple[MdConsumptionImportRow, RowState]],
) -> ClientMdImportSummary:
    return ClientMdImportSummary(
        id=batch.id,
        period_month=batch.period_month,
        filename=batch.filename,
        created_at=batch.created_at,
        uploaded_by_name=uploader,
        rows_total=len(rows),
        rows_booked=sum(1 for _, state in rows if state == "booked"),
        rows_to_verify=sum(1 for _, state in rows if state == "to_verify"),
        rows_error=sum(1 for _, state in rows if state == "error"),
        md_booked=sum(
            (
                Decimal(str(row.md_reported))
                for row, state in rows
                if state == "booked" and row.status == IMPORT_ROW_APPLIED
            ),
            Decimal("0"),
        ),
    )


@router.get(
    "/{client_id}/md-imports",
    response_model=ClientMdImportListResponse,
)
async def list_client_md_imports(
    client_id: int,
    user: OrderGroupSafeReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Importy MD, które dotknęły zamówień klienta — od najnowszego."""
    await _require_safe_group_read(db, user, client_id)
    _assert_multi_client(client_id)
    scope = await _client_scope(db, client_id)
    if not scope.groups:
        return ClientMdImportListResponse()
    batches = (
        await db.execute(
            select(MdConsumptionImport, User.name)
            .outerjoin(User, User.id == MdConsumptionImport.uploaded_by_user_id)
            .order_by(
                MdConsumptionImport.created_at.desc(), MdConsumptionImport.id.desc()
            )
            .limit(200)
        )
    ).all()
    if not batches:
        return ClientMdImportListResponse()
    rows = (
        await db.scalars(
            select(MdConsumptionImportRow).where(
                MdConsumptionImportRow.import_id.in_([b.id for b, _ in batches])
            )
        )
    ).all()
    touched = [row for row in rows if scope.touches(row)]
    # Stan wiersza liczy TA SAMA reguła co widok szczegółów (z opisem
    # przyczyny) — inaczej lista i szczegóły podawałyby różne liczby błędów.
    context = (
        await _reason_context(db)
        if any(r.status == IMPORT_ROW_UNMATCHED and r.notes_raw for r in touched)
        else None
    )
    period = {batch.id: batch.period_month for batch, _ in batches}
    by_import: dict[int, list[tuple[MdConsumptionImportRow, RowState]]] = defaultdict(
        list
    )
    for row in touched:
        reason = _unmatched_reason(row, period.get(row.import_id), context)
        by_import[row.import_id].append((row, row_state(row, reason is not None)))
    return ClientMdImportListResponse(
        imports=[
            _summary(batch, uploader, by_import[batch.id])
            for batch, uploader in batches
            if by_import.get(batch.id)
        ]
    )


@router.get(
    "/{client_id}/md-imports/{import_id}",
    response_model=ClientMdImportDetail,
)
async def get_client_md_import(
    client_id: int,
    import_id: int,
    user: OrderGroupSafeReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Wiersze jednego importu — wyłącznie te, które dotyczą klienta."""
    await _require_safe_group_read(db, user, client_id)
    _assert_multi_client(client_id)
    found = (
        await db.execute(
            select(MdConsumptionImport, User.name)
            .outerjoin(User, User.id == MdConsumptionImport.uploaded_by_user_id)
            .where(MdConsumptionImport.id == import_id)
        )
    ).first()
    if found is None:
        raise HTTPException(404, detail="Import nie istnieje")
    batch, uploader = found
    scope = await _client_scope(db, client_id)
    order_numbers = finance_order_matching.build_order_number_index(
        (client_id, number) for number in scope.groups.values()
    )
    stored = [
        row
        for row in (
            await db.scalars(
                select(MdConsumptionImportRow)
                .where(MdConsumptionImportRow.import_id == import_id)
                .order_by(MdConsumptionImportRow.row_number.asc())
            )
        ).all()
        if scope.touches(row)
    ]
    if not stored:
        # Import istnieje, ale nie dotyczy tego klienta — dla tego widoku
        # to brak importu, nie pusta tabela.
        raise HTTPException(404, detail="Ten import nie dotyczy zamówień klienta")
    with_finance = await _can_see_finance(db, user, client_id)
    context = (
        await _reason_context(db)
        if any(r.status == IMPORT_ROW_UNMATCHED and r.notes_raw for r in stored)
        else None
    )
    states: list[tuple[MdConsumptionImportRow, RowState]] = []
    reads: list[ClientMdImportRow] = []
    for row in stored:
        reason = _unmatched_reason(row, batch.period_month, context)
        state = row_state(row, reason is not None)
        states.append((row, state))
        target_group = scope.target_group(row)
        target_number = scope.groups.get(target_group) if target_group else None
        reads.append(
            ClientMdImportRow(
                id=row.id,
                row_number=row.row_number,
                consultant_name=row.consultant_name,
                order_number_hint=row.order_number_hint,
                target_order_number=target_number,
                target_group_id=target_group,
                md_reported=row.md_reported,
                invoice_amount=row.invoice_amount if with_finance else None,
                state=state,
                state_label=ROW_STATE_LABELS[state],
                status_label=_row_status_label(row, reason[0] if reason else None),
                status_reason=reason[1] if reason else None,
                number_mismatch=bool(
                    target_number
                    and is_foreign_number(
                        row.order_number_hint,
                        target_number,
                        client_id=client_id,
                        order_numbers=order_numbers,
                    )
                ),
            )
        )
    summary = _summary(batch, uploader, states)
    return ClientMdImportDetail(**summary.model_dump(), rows=reads)
