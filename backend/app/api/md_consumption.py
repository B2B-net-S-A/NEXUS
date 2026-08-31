"""Router `/api/md-consumption` — import zużycia MD z arkusza Finansów.

Operator z Finansów wgrywa miesięczny raport (konsultant → zaraportowane MD),
a system odejmuje MD od budżetów aktywnych linii zamówień.

Historyczne zamówienia MD są dopasowywane wyłącznie po imieniu i nazwisku.
Wspólna pula MD Cyfrowego Polsatu/Lotte Wedel oraz zamówienia kosztowe wymagają
dodatkowo
numeru zamówienia wyciągniętego z kolumny „Uwagi" — numer nie jest zgadywany
ani wybierany jako „pierwszy pasujący". Dla ścieżki historycznej zostają trzy
możliwe wyniki wiersza i tylko jeden z nich jest automatyczny:

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
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.financial_access import FinanceManageUser
from app.core.database import get_db
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_EXHAUSTED,
    ClientOrderGroup,
    ClientOrderGroupMdConsumption,
)
from app.models.contract import Contract, ContractStatus
from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    ClientOrderMdConsumption,
    COST_ROW_APPLIED,
    COST_ROW_STATUS_LABELS,
    COST_ROW_UNMATCHED_CONSULTANT,
    COST_ROW_UNMATCHED_NUMBER,
    CONSUMPTION_SOURCE_MANUAL,
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
    PolkomtelReprocessRequest,
    PolkomtelReprocessResponse,
    PolkomtelReprocessTarget,
)
from app.services import finance_order_matching
from app.services.client_identity import client_display_name_expression
from app.services.client_order_lines import (
    LineMatch,
    active_cost_lines,
    active_md_lines,
    active_shared_md_lines,
    apply_md_consumption,
    describe_import,
    historical_cost_lines,
    historical_md_lines,
    historical_shared_md_lines,
    match_by_name,
    month_bounds,
    record_event,
    successor_line_for,
)
from app.services.cost_orders import (
    describe_invoice_import,
    lock_group_for_settlement,
    quantize_money,
    settle_group,
    upsert_invoice,
)
from app.services.md_import_parser import (
    MdSheetFormatError,
    extract_order_number_candidates,
    parse_md_sheet,
)
from app.services.dl_alerts import emit_cost_order_exhausted
from app.services.multi_consultant_orders import (
    EVENT_BUDGET_EXHAUSTED,
    EVENT_INVOICE_IMPORT,
    EVENT_MD_IMPORT,
    format_md,
    quantize_md,
)
from app.services.shared_md_orders import (
    shared_md_used_total,
    upsert_shared_md_consumption,
    uses_shared_md_pool,
)

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
        select(
            Client.id,
            client_display_name_expression().label("client_name"),
        ).where(Client.id.in_(client_ids))
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
        notes_raw=row.notes_raw,
        order_number_hint=row.order_number_hint,
        invoice_amount=row.invoice_amount,
        cost_status=row.cost_status,
        cost_status_label=(
            COST_ROW_STATUS_LABELS.get(row.cost_status, row.cost_status)
            if row.cost_status
            else None
        ),
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
        rows_cost_applied=batch.rows_cost_applied,
        rows_cost_unmatched=batch.rows_cost_unmatched,
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

    cost_result = await db.execute(
        select(MdConsumptionImportRow.cost_status).where(
            MdConsumptionImportRow.import_id == batch.id
        )
    )
    cost_statuses = [c for (c,) in cost_result if c is not None]
    batch.rows_cost_applied = sum(1 for c in cost_statuses if c == COST_ROW_APPLIED)
    batch.rows_cost_unmatched = len(cost_statuses) - batch.rows_cost_applied


async def _apply_to_line(
    db: AsyncSession,
    *,
    match_order: ClientOrder,
    group: Optional[ClientOrderGroup],
    period_month: str,
    md_reported,
    import_id: int,
    user_id: int,
    historical_reprocess: bool = False,
) -> None:
    """Zapisz MD na linii i dopisz jeden wpis do historii jej zamówienia.

    Grupa, a nie samo ``group_id``: treść wpisu niesie numer zamówienia, a
    podział nadwyżki na następcę potrzebuje numerów obu stron. Obie ścieżki
    importu — wsadowa i ręczne rozstrzygnięcie — wołają tę funkcję, więc
    podział nie zależy od tego, którą z nich operator akurat wybrał.
    """
    expected_group_id = group.id if group is not None else match_order.order_group_id
    locked_order = await db.scalar(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.order_group),
        )
        .where(ClientOrder.id == match_order.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    first, last = month_bounds(period_month)
    historical_target_is_valid = (
        historical_reprocess
        and locked_order is not None
        and locked_order.status
        in (ClientOrderStatus.active, ClientOrderStatus.completed)
        and locked_order.contract is not None
        and locked_order.contract.status != ContractStatus.void
        and locked_order.order_group is not None
        and locked_order.order_group.status
        in (GROUP_STATUS_ACTIVE, GROUP_STATUS_COMPLETED, GROUP_STATUS_EXHAUSTED)
        and locked_order.order_group.start_date <= last
        and (
            locked_order.order_group.end_date is None
            or locked_order.order_group.end_date >= first
        )
        and (locked_order.start_date is None or locked_order.start_date <= last)
        and (locked_order.end_date is None or locked_order.end_date >= first)
    )
    target_is_valid = historical_target_is_valid or (
        not historical_reprocess
        and locked_order is not None
        and locked_order.status == ClientOrderStatus.active
    )
    if (
        locked_order is None
        or not target_is_valid
        or locked_order.order_group_id != expected_group_id
    ):
        # The match was computed before this transaction acquired the line.
        # Contract offboarding (or another lifecycle action) may have changed
        # the staffing in between; applying the spreadsheet to the stale row
        # would make its remaining-MD snapshot financially incorrect.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Obsada zamówienia zmieniła się podczas importu. "
                "Odśwież dane i ponów import."
            ),
        )

    locked_group = locked_order.order_group
    outcome = await apply_md_consumption(
        db,
        order=locked_order,
        group=locked_group,
        period_month=period_month,
        md_reported=md_reported,
        import_id=import_id,
        user_id=user_id,
        allow_successor_transfer=not historical_reprocess,
    )
    if locked_group is not None:
        record_event(
            db,
            group_id=locked_group.id,
            order_id=locked_order.id,
            event_type=EVENT_MD_IMPORT,
            description=describe_import(
                locked_order,
                period_month,
                outcome.applied,
                outcome.previous,
                order_number=locked_group.order_number,
            ),
            payload={
                # `md_reported` zostaje liczbą Z ARKUSZA, a `md_applied` mówi,
                # ile z niej przyjęło TO zamówienie — po rozdzieleniu obie
                # wartości są potrzebne do rozliczenia faktury za ten miesiąc.
                "period_month": period_month,
                "md_reported": str(md_reported),
                "md_applied": str(outcome.applied),
                "md_transferred": str(outcome.transferred),
                "md_previous": str(outcome.previous),
                "md_remaining": str(locked_order.md_remaining),
                "import_id": import_id,
            },
            user_id=user_id,
        )


async def _lock_finance_target_orders(
    db: AsyncSession, order_ids: set[int]
) -> dict[int, ClientOrder]:
    """Lock every target line once, globally ordered by primary key."""

    if not order_ids:
        return {}
    ordered_ids = sorted(order_ids)
    result = await db.execute(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.order_group),
        )
        .where(ClientOrder.id.in_(ordered_ids))
        .order_by(ClientOrder.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    locked = {order.id: order for order in result.scalars()}
    if set(locked) != set(ordered_ids):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Jedna z linii zmieniła się podczas rozliczania importu.",
        )
    return locked


async def _lock_finance_target_groups(
    db: AsyncSession, groups: dict[int, ClientOrderGroup]
) -> dict[int, ClientOrderGroup]:
    """Lock every target group after lines, globally ordered by primary key."""

    locked: dict[int, ClientOrderGroup] = {}
    for group_id in sorted(groups):
        locked[group_id] = await lock_group_for_settlement(
            db,
            groups[group_id],
            flush_local_changes=False,
        )
    return locked


def _ordinary_locked_target_is_valid(
    *,
    kind: str,
    order: ClientOrder,
    group: ClientOrderGroup,
    rows: list[MdConsumptionImportRow],
    expected_client_id: int,
    period_month: str,
) -> bool:
    """Re-match persisted spreadsheet evidence after line/group lock waits.

    Candidate selection happens before the importer can acquire its locks.  A
    concurrent group PATCH may therefore rename or move the period of an order
    while this transaction is waiting.  Rechecking only status/type would then
    apply the old spreadsheet row to the newly named order.  Keep the original
    row evidence and prove the same name, client, period and (where routing
    requires it) order number against the refreshed ORM objects.
    """

    contract = order.contract
    candidate = contract.candidate if contract else None
    consultant_name = (
        f"{candidate.name or ''} {candidate.lastname or ''}".strip()
        if candidate
        else ""
    )
    current_match = LineMatch(order, group, consultant_name)
    first, last = month_bounds(period_month)
    if (
        not rows
        or order.order_group_id != group.id
        or order.client_id != expected_client_id
        or group.client_id != expected_client_id
        or contract is None
        or contract.client_id != expected_client_id
        or contract.status == ContractStatus.void
        or (order.start_date is not None and order.start_date > last)
        or (order.end_date is not None and order.end_date < first)
    ):
        return False

    if kind == "md_line":
        if order.status != ClientOrderStatus.active or order.md_total is None:
            return False
    elif kind == "shared_md":
        if (
            order.status != ClientOrderStatus.active
            or group.status != GROUP_STATUS_ACTIVE
            or not uses_shared_md_pool(group)
        ):
            return False
    elif kind == "cost":
        if (
            order.status not in (ClientOrderStatus.active, ClientOrderStatus.draft)
            or group.status != GROUP_STATUS_ACTIVE
            or not group.is_cost_based
        ):
            return False
    else:
        return False

    for row in rows:
        if match_by_name([current_match], row.consultant_name) != [current_match]:
            return False
        hints = extract_order_number_candidates(row.notes_raw)
        number_is_evidence = kind in ("shared_md", "cost") or (
            expected_client_id == finance_order_matching.POLKOMTEL_CLIENT_ID
            and bool(hints)
        )
        if (
            number_is_evidence
            and not finance_order_matching.finance_order_number_matches(
                client_id=group.client_id,
                order_number=group.order_number,
                numeric_hints=hints,
            )
        ):
            return False
    return True


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
    """Wgraj raport MD i zastosuj go do aktywnych linii lub wspólnych pul."""
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
    shared_md_candidates = await active_shared_md_lines(db, period_month)
    cost_candidates = await active_cost_lines(db, period_month)

    batch = MdConsumptionImport(
        period_month=period_month,
        filename=filename[:255],
        uploaded_by_user_id=user.id,
    )
    db.add(batch)
    await db.flush()

    # Faktury tej samej osoby na tym samym zamówieniu są SUMOWANE przed
    # zapisem, a nie zapisywane po kolei: klucz idempotencji to (linia,
    # miesiąc), więc drugi wiersz nadpisałby pierwszy i kwota po cichu
    # zniknęłaby z rozliczenia zamiast się do niego dodać.
    pending_invoices: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    invoice_orders: dict[int, ClientOrder] = {}
    touched_groups: dict[int, ClientOrderGroup] = {}

    # MD idą tą samą drogą co faktury i z DOKŁADNIE tego samego powodu.
    # Wcześniej ``_apply_to_line`` szło wewnątrz pętli po wierszach, więc
    # ``ON CONFLICT DO UPDATE`` na kluczu (linia, miesiąc) zostawiał MD z
    # OSTATNIEGO wiersza, a wcześniejsze znikały — przy „Kowalski Jan | 15 MD"
    # i „Kowalski Jan | 5 MD" budżet tracił 15 dni, a oba wiersze i tak były
    # w podsumowaniu oznaczone jako „Zaktualizowano", więc operator nie miał
    # żadnego sygnału.
    pending_md: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    md_orders: dict[int, tuple[ClientOrder, ClientOrderGroup]] = {}
    md_rows: dict[int, list[MdConsumptionImportRow]] = defaultdict(list)
    pending_shared_md: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    shared_md_groups: dict[int, ClientOrderGroup] = {}
    shared_md_orders: dict[int, ClientOrder] = {}
    shared_md_rows: dict[int, list[MdConsumptionImportRow]] = defaultdict(list)
    cost_rows: dict[int, list[MdConsumptionImportRow]] = defaultdict(list)

    for parsed_row in parsed.rows:
        row = MdConsumptionImportRow(
            import_id=batch.id,
            row_number=parsed_row.row_number,
            consultant_name=parsed_row.consultant_name[:255],
            md_reported=parsed_row.md_reported,
            status=IMPORT_ROW_UNMATCHED,
            notes_raw=parsed_row.notes_raw,
            order_number_hint=parsed_row.order_number_hint,
            invoice_amount=parsed_row.invoice_amount,
        )

        # Parser dochodzi tutaj wyłącznie po znalezieniu jawnie rozpoznanej
        # kolumny MD. Wspólna pula nie próbuje wyliczać dni z faktury, godzin
        # ani innej kolumny zastępczej, dopóki Finanse nie ustalą formatu.
        consultant_in_shared_md = _match_shared_md_row(
            row,
            parsed_row=parsed_row,
            shared_md_candidates=shared_md_candidates,
            pending_shared_md=pending_shared_md,
            shared_md_groups=shared_md_groups,
            shared_md_orders=shared_md_orders,
        )
        if (
            consultant_in_shared_md
            and row.status == IMPORT_ROW_APPLIED
            and row.matched_order_id is not None
        ):
            shared_md_rows[row.matched_order_id].append(row)
        if not consultant_in_shared_md:
            matches = _match_per_consultant_md_row(
                parsed_row=parsed_row,
                candidates=candidates,
            )
            if len(matches) == 1:
                match = matches[0]
                row.status = IMPORT_ROW_APPLIED
                row.matched_order_id = match.order.id
                pending_md[match.order.id] += parsed_row.md_reported
                md_orders[match.order.id] = (match.order, match.group)
                md_rows[match.order.id].append(row)
            elif len(matches) > 1:
                row.status = IMPORT_ROW_NEEDS_ASSIGNMENT
                row.candidate_order_ids = [m.order.id for m in matches]

        # ── Ścieżka kosztowa: NIEZALEŻNA od dopasowania MD po nazwisku ──
        # Prawidłowo dopasowany numer wspólnej puli MD nie może jednocześnie
        # zgłaszać „brak zamówienia kosztowego o tym numerze". Typy grup są
        # rozłączne, więc taki wiersz kończy routing na ścieżce shared-MD.
        shared_md_applied = consultant_in_shared_md and row.status == IMPORT_ROW_APPLIED
        if not shared_md_applied:
            cost_match = _match_cost_row(
                row,
                parsed_row=parsed_row,
                cost_candidates=cost_candidates,
                pending_invoices=pending_invoices,
                invoice_orders=invoice_orders,
                touched_groups=touched_groups,
            )
            if cost_match is not None:
                cost_rows[cost_match.order.id].append(row)
        db.add(row)

    # One lock protocol for every Finance writer: all lines (ascending), then
    # all groups (ascending), only then monthly rows/upserts.  Offboarding and
    # group edits already use line -> group; reversing that order here could
    # deadlock when an invoice FK waits on a line held by those workflows.
    expected_group_by_order: dict[int, int] = {
        order_id: group.id for order_id, (_, group) in md_orders.items()
    }
    expected_group_by_order.update(
        {
            order_id: order.order_group_id
            for order_id, order in shared_md_orders.items()
            if order.order_group_id is not None
        }
    )
    expected_client_by_order: dict[int, int] = {
        order_id: group.client_id for order_id, (_, group) in md_orders.items()
    }
    expected_client_by_order.update(
        {order_id: order.client_id for order_id, order in shared_md_orders.items()}
    )
    expected_client_by_order.update(
        {order_id: order.client_id for order_id, order in invoice_orders.items()}
    )
    expected_group_by_order.update(
        {
            order_id: order.order_group_id
            for order_id, order in invoice_orders.items()
            if order.order_group_id is not None
        }
    )
    locked_orders = await _lock_finance_target_orders(db, set(expected_group_by_order))
    for order_id, expected_group_id in expected_group_by_order.items():
        if locked_orders[order_id].order_group_id != expected_group_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    "Obsada zamówienia zmieniła się podczas importu. "
                    "Odśwież dane i ponów import."
                ),
            )

    target_groups = (
        {group.id: group for _, group in md_orders.values()}
        | shared_md_groups
        | touched_groups
    )
    locked_groups = await _lock_finance_target_groups(db, target_groups)

    for order_id, (_, group) in list(md_orders.items()):
        md_orders[order_id] = (locked_orders[order_id], locked_groups[group.id])
    for group_id in list(shared_md_groups):
        shared_md_groups[group_id] = locked_groups[group_id]
    for order_id in list(invoice_orders):
        invoice_orders[order_id] = locked_orders[order_id]
    for group_id in list(touched_groups):
        touched_groups[group_id] = locked_groups[group_id]

    for order_id, rows in md_rows.items():
        order = locked_orders[order_id]
        group = locked_groups[expected_group_by_order[order_id]]
        if not _ordinary_locked_target_is_valid(
            kind="md_line",
            order=order,
            group=group,
            rows=rows,
            expected_client_id=expected_client_by_order[order_id],
            period_month=period_month,
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Linia MD zmieniła się podczas importu.",
            )
    for order_id, rows in shared_md_rows.items():
        order = locked_orders[order_id]
        group = locked_groups[expected_group_by_order[order_id]]
        if not _ordinary_locked_target_is_valid(
            kind="shared_md",
            order=order,
            group=group,
            rows=rows,
            expected_client_id=expected_client_by_order[order_id],
            period_month=period_month,
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Wspólna pula MD zmieniła się podczas importu.",
            )
    for order_id, rows in cost_rows.items():
        order = locked_orders[order_id]
        group = locked_groups[expected_group_by_order[order_id]]
        if not _ordinary_locked_target_is_valid(
            kind="cost",
            order=order,
            group=group,
            rows=rows,
            expected_client_id=expected_client_by_order[order_id],
            period_month=period_month,
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Zamówienie kosztowe zmieniło się podczas importu.",
            )

    for order_id in sorted(pending_md):
        md_total = pending_md[order_id]
        order_obj, order_group = md_orders[order_id]
        await _apply_to_line(
            db,
            match_order=order_obj,
            group=order_group,
            period_month=period_month,
            md_reported=md_total,
            import_id=batch.id,
            user_id=user.id,
        )

    for group_id in sorted(pending_shared_md):
        await _settle_shared_md_and_record(
            db,
            group=shared_md_groups[group_id],
            period_month=period_month,
            md_reported=pending_shared_md[group_id],
            import_id=batch.id,
            user_id=user.id,
        )

    for order_id in sorted(pending_invoices):
        amount = pending_invoices[order_id]
        await upsert_invoice(
            db,
            order=invoice_orders[order_id],
            period_month=period_month,
            invoice_amount=amount,
            import_id=batch.id,
            user_id=user.id,
        )

    await db.flush()
    for group_id in sorted(touched_groups):
        await _settle_and_record(
            db,
            group=touched_groups[group_id],
            period_month=period_month,
            import_id=batch.id,
            user_id=user.id,
        )

    await db.flush()
    await _recount(db, batch)
    await db.commit()
    await db.refresh(batch)

    return await _detail(db, batch, parsed_sheet=parsed)


def _match_per_consultant_md_row(*, parsed_row, candidates: list[LineMatch]):
    """Preserve name matching, but use Polkomtel's explicit SAP number.

    Historical MD imports are name-only.  When a row carries a number that
    matches a Polkomtel ``SAP`` order, using it resolves the reported bug and
    prevents a same-name row from landing on another order.  Once an explicit
    hint is present beside a Polkomtel candidate, a mismatch is authoritative
    and returns no Polkomtel line instead of falling back to name-only.

    Rows without a Polkomtel candidate (or without a numeric hint) retain the
    old BIK/BNP name-only behavior.  Exact numbered matches from neighbouring
    clients remain in the narrowed set, so a genuine cross-client collision is
    still ambiguous and never guessed.
    """

    named = match_by_name(candidates, parsed_row.consultant_name)
    if not named:
        return []
    hints = extract_order_number_candidates(parsed_row.notes_raw)
    has_polkomtel_candidate = any(
        match.group.client_id == finance_order_matching.POLKOMTEL_CLIENT_ID
        for match in named
    )
    if not has_polkomtel_candidate or not hints:
        return named
    return [
        match
        for match in named
        if finance_order_matching.finance_order_number_matches(
            client_id=match.group.client_id,
            order_number=match.group.order_number,
            numeric_hints=hints,
        )
    ]


def _match_shared_md_row(
    row: MdConsumptionImportRow,
    *,
    parsed_row,
    shared_md_candidates: list[LineMatch],
    pending_shared_md: dict[int, Decimal],
    shared_md_groups: dict[int, ClientOrderGroup],
    shared_md_orders: dict[int, ClientOrder],
) -> bool:
    """Dopasuj wspólną pulę MD po konsultancie ORAZ numerze zamówienia.

    Zwraca ``True``, gdy konsultant ma aktywną linię shared-MD — także jeśli
    numer jest pusty lub niejednoznaczny. To rozróżnienie jest kluczowe:
    nierozpoznanego wiersza wspólnej puli nie wolno przepuścić do starego
    matchera po samym nazwisku, bo mógłby zdjąć MD z innego klienta.
    """
    named = match_by_name(shared_md_candidates, parsed_row.consultant_name)
    if not named:
        return False

    hints = extract_order_number_candidates(parsed_row.notes_raw)
    numbered = [
        match
        for match in named
        if finance_order_matching.finance_order_number_matches(
            client_id=match.group.client_id,
            order_number=match.group.order_number,
            numeric_hints=hints,
        )
    ]
    if len(numbered) != 1:
        # Status pozostaje `unmatched`; ręczne przypisanie historycznej linii
        # zapisuje budżet per konsultant, więc nie jest bezpieczną ścieżką dla
        # wspólnej puli. Zero lub wiele trafień oznacza brak zapisu.
        return True

    match = numbered[0]
    row.status = IMPORT_ROW_APPLIED
    row.matched_order_id = match.order.id
    row.matched_group_id = match.group.id
    row.order_number_hint = match.group.order_number.strip()
    pending_shared_md[match.group.id] += parsed_row.md_reported
    shared_md_groups[match.group.id] = match.group
    shared_md_orders[match.order.id] = match.order
    return True


def _match_cost_row(
    row: MdConsumptionImportRow,
    *,
    parsed_row,
    cost_candidates: list[LineMatch],
    pending_invoices: dict[int, Decimal],
    invoice_orders: dict[int, ClientOrder],
    touched_groups: dict[int, ClientOrderGroup],
) -> Optional[LineMatch]:
    """Dopasuj wiersz do zamówienia kosztowego po numerze z „Uwag".

    Wiersz wchodzi na tę ścieżkę tylko wtedy, gdy ma OBIE rzeczy: numer
    w „Uwagach" i kwotę w „Fakturze". Bez kwoty nie ma czego odjąć, więc
    oznaczanie takiego wiersza na czerwono byłoby fałszywym alarmem — a to on
    ma kierować uwagę operatora tam, gdzie faktycznie zginęły pieniądze.

    Numer wybieramy przez KONFRONTACJĘ z istniejącymi zamówieniami, a nie
    heurystyką „najdłuższy ciąg cyfr": w komórce obok numeru zamówienia stoi
    często rok albo numer transzy, a zgadywanie odjęłoby kwotę z cudzego
    budżetu i wyszło dopiero na fakturze.
    """
    hints = extract_order_number_candidates(parsed_row.notes_raw)
    amount = parsed_row.invoice_amount
    if not hints or amount is None or quantize_money(amount) <= Decimal("0"):
        return None

    # Numer zamówienia nie jest globalnie unikalny (ani w bazie, ani między
    # klientami), więc nie wolno zwijać kandydatów do słownika po samym
    # numerze. Najpierw konfrontujemy WSZYSTKIE numery z uwag, potem nazwisko,
    # i akceptujemy wyłącznie dokładnie jedną linię. Dzięki temu dwa zamówienia
    # „445" u Polkomtela, Cyfrowego Polsatu i Lotte Wedel nie nadpisują się zależnie od
    # kolejności wyniku zapytania.
    numbered = [
        match
        for match in cost_candidates
        if finance_order_matching.finance_order_number_matches(
            client_id=match.group.client_id,
            order_number=match.group.order_number,
            numeric_hints=hints,
        )
    ]
    if not numbered:
        row.cost_status = COST_ROW_UNMATCHED_NUMBER
        return None

    named = match_by_name(numbered, parsed_row.consultant_name)
    if len(named) != 1:
        # Zero trafień albo niejednoznaczność — w obu przypadkach system NIE
        # zgaduje. Kwota trafiłaby wtedy na cudzą linię, a „Zafakturowano"
        # przy konsultancie przestałoby zgadzać się z jego fakturami.
        row.cost_status = COST_ROW_UNMATCHED_CONSULTANT
        return None

    match = named[0]
    group = match.group
    order = match.order
    row.matched_group_id = group.id
    row.order_number_hint = group.order_number.strip()
    row.cost_status = COST_ROW_APPLIED
    pending_invoices[order.id] += quantize_money(amount)
    invoice_orders[order.id] = order
    touched_groups[group.id] = group
    return match


# ── Safe reprocessing of an already uploaded Polkomtel batch ───────────────

_REPROCESS_MD_LINE = "md_line"
_REPROCESS_SHARED_MD = "shared_md"
_REPROCESS_COST = "cost"


@dataclass
class _PolkomtelReprocessPlan:
    kind: str
    match: LineMatch
    rows: list[MdConsumptionImportRow]
    rows_to_update: list[MdConsumptionImportRow]
    expected_value: Decimal
    current_value: Optional[Decimal] = None
    write_required: bool = True


def _single_polkomtel_numbered_match(
    candidates: list[LineMatch], row: MdConsumptionImportRow
) -> tuple[Optional[LineMatch], bool]:
    """Return one Polkomtel match only when it is unique across clients."""

    named = match_by_name(candidates, row.consultant_name)
    hints = extract_order_number_candidates(row.notes_raw)
    numbered = [
        match
        for match in named
        if finance_order_matching.finance_order_number_matches(
            client_id=match.group.client_id,
            order_number=match.group.order_number,
            numeric_hints=hints,
        )
    ]
    polkomtel = [
        match
        for match in numbered
        if match.group.client_id == finance_order_matching.POLKOMTEL_CLIENT_ID
    ]
    if not polkomtel:
        return None, False
    if len(numbered) == 1:
        return polkomtel[0], False
    return None, True


def _build_polkomtel_reprocess_plan(
    rows: list[MdConsumptionImportRow],
    *,
    md_candidates: list[LineMatch],
    shared_md_candidates: list[LineMatch],
    cost_candidates: list[LineMatch],
) -> tuple[list[_PolkomtelReprocessPlan], list[str]]:
    """Plan only newly provable Polkomtel matches; never rewrite a decision.

    Every target aggregates *all* matching rows from the batch, not only rows
    whose status changes.  The monthly consumption has a single upsert key, so
    writing only the newly matched row would overwrite and lose an amount that
    was already applied from the same spreadsheet.
    """

    buckets: dict[tuple[str, int], _PolkomtelReprocessPlan] = {}
    conflicts: list[str] = []

    def add_md(*, kind: str, match: LineMatch, row: MdConsumptionImportRow) -> None:
        key_id = match.group.id if kind == _REPROCESS_SHARED_MD else match.order.id
        key = (kind, key_id)
        plan = buckets.setdefault(
            key,
            _PolkomtelReprocessPlan(
                kind=kind,
                match=match,
                rows=[],
                rows_to_update=[],
                expected_value=Decimal("0"),
            ),
        )
        plan.rows.append(row)
        plan.expected_value += Decimal(str(row.md_reported))

        already_different = row.matched_order_id not in (None, match.order.id) or (
            kind == _REPROCESS_SHARED_MD
            and row.matched_group_id not in (None, match.group.id)
        )
        if row.status == IMPORT_ROW_APPLIED and already_different:
            conflicts.append(
                f"Wiersz {row.id}: MD jest już przypisane do innego zamówienia."
            )
            return
        if (
            row.status != IMPORT_ROW_APPLIED
            or row.matched_order_id != match.order.id
            or (kind == _REPROCESS_SHARED_MD and row.matched_group_id != match.group.id)
        ):
            plan.rows_to_update.append(row)

    def add_cost(match: LineMatch, row: MdConsumptionImportRow) -> None:
        key = (_REPROCESS_COST, match.order.id)
        plan = buckets.setdefault(
            key,
            _PolkomtelReprocessPlan(
                kind=_REPROCESS_COST,
                match=match,
                rows=[],
                rows_to_update=[],
                expected_value=Decimal("0"),
            ),
        )
        plan.rows.append(row)
        plan.expected_value += Decimal(str(row.invoice_amount or 0))
        if row.cost_status == COST_ROW_APPLIED and row.matched_group_id not in (
            None,
            match.group.id,
        ):
            conflicts.append(
                f"Wiersz {row.id}: kwota jest już przypisana do innego zamówienia."
            )
            return
        if (
            row.cost_status != COST_ROW_APPLIED
            or row.matched_group_id != match.group.id
        ):
            plan.rows_to_update.append(row)

    for row in rows:
        shared_match, shared_ambiguous = _single_polkomtel_numbered_match(
            shared_md_candidates, row
        )
        if shared_ambiguous:
            conflicts.append(
                f"Wiersz {row.id}: numer i konsultant pasują do więcej niż "
                "jednej wspólnej puli MD."
            )
        if shared_match is not None:
            add_md(kind=_REPROCESS_SHARED_MD, match=shared_match, row=row)
        else:
            line_match, line_ambiguous = _single_polkomtel_numbered_match(
                md_candidates, row
            )
            if line_ambiguous:
                conflicts.append(
                    f"Wiersz {row.id}: numer i konsultant pasują do więcej "
                    "niż jednej linii MD."
                )
            if line_match is not None:
                add_md(kind=_REPROCESS_MD_LINE, match=line_match, row=row)

        # Shared-MD is a terminal route in the ordinary importer too.  A row
        # applied to that pool must not additionally subtract an invoice.
        amount = row.invoice_amount
        if (
            shared_match is None
            and amount is not None
            and quantize_money(amount) > Decimal("0")
        ):
            cost_match, cost_ambiguous = _single_polkomtel_numbered_match(
                cost_candidates, row
            )
            if cost_ambiguous:
                conflicts.append(
                    f"Wiersz {row.id}: numer i konsultant pasują do więcej "
                    "niż jednej linii kosztowej."
                )
            if cost_match is not None:
                add_cost(cost_match, row)

    plans: list[_PolkomtelReprocessPlan] = []
    for plan in buckets.values():
        if not plan.rows_to_update:
            continue
        if plan.kind == _REPROCESS_COST:
            plan.expected_value = quantize_money(plan.expected_value)
        else:
            plan.expected_value = quantize_md(plan.expected_value)
        plans.append(plan)
    # Mirror the ordinary importer: a shared pool is terminal; otherwise MD is
    # resolved first and the cost route may then own ``matched_group_id``.
    kind_order = {
        _REPROCESS_SHARED_MD: 0,
        _REPROCESS_MD_LINE: 1,
        _REPROCESS_COST: 2,
    }
    plans.sort(
        key=lambda plan: (
            kind_order[plan.kind],
            plan.match.group.id,
            plan.match.order.id,
        )
    )
    return plans, list(dict.fromkeys(conflicts))


async def _protect_newer_or_manual_consumption(
    db: AsyncSession,
    *,
    batch: MdConsumptionImport,
    plan: _PolkomtelReprocessPlan,
    lock: bool,
) -> Optional[str]:
    """Prevent a July correction from overwriting newer/manual truth."""

    if plan.kind == _REPROCESS_SHARED_MD:
        current_query = select(ClientOrderGroupMdConsumption).where(
            ClientOrderGroupMdConsumption.group_id == plan.match.group.id,
            ClientOrderGroupMdConsumption.period_month == batch.period_month,
        )
        if lock:
            current_query = current_query.with_for_update()
        current = await db.scalar(
            current_query.execution_options(populate_existing=True)
        )
        if current is None:
            return None
        current_value = quantize_md(current.md_reported)
        plan.current_value = current_value
        if current.source == CONSUMPTION_SOURCE_MANUAL:
            return (
                f"Zamówienie {plan.match.group.order_number}: istnieje ręczna "
                "korekta wspólnej puli MD za ten miesiąc."
            )
        if current_value == plan.expected_value:
            plan.write_required = False
            return None
        # Shared-MD rows predate an import_id column, so ownership cannot be
        # proven.  Refuse to replace a different imported value.
        return (
            f"Zamówienie {plan.match.group.order_number}: istnieje inne "
            "rozliczenie wspólnej puli MD za ten miesiąc."
        )

    model = (
        ClientOrderInvoiceConsumption
        if plan.kind == _REPROCESS_COST
        else ClientOrderMdConsumption
    )
    value_column = (
        model.invoice_amount if plan.kind == _REPROCESS_COST else model.md_reported
    )
    current_query = select(model).where(
        model.order_id == plan.match.order.id,
        model.period_month == batch.period_month,
    )
    if lock:
        current_query = current_query.with_for_update()
    current = await db.scalar(current_query.execution_options(populate_existing=True))
    if current is None:
        return None
    current_value = (
        quantize_money(getattr(current, value_column.key))
        if plan.kind == _REPROCESS_COST
        else quantize_md(getattr(current, value_column.key))
    )
    plan.current_value = current_value
    if current.source == CONSUMPTION_SOURCE_MANUAL:
        return (
            f"Zamówienie {plan.match.group.order_number}: istnieje ręczne "
            "rozliczenie za ten miesiąc."
        )
    if current_value == plan.expected_value:
        plan.write_required = False
        return None
    if current.import_id == batch.id:
        return None
    if current.import_id is None:
        return (
            f"Zamówienie {plan.match.group.order_number}: istnieje inne "
            "rozliczenie bez możliwej do potwierdzenia partii źródłowej."
        )
    other_batch = await db.get(MdConsumptionImport, current.import_id)
    if other_batch is None or other_batch.created_at >= batch.created_at:
        return (
            f"Zamówienie {plan.match.group.order_number}: istnieje rozliczenie "
            "z nowszego importu; starsza partia nie może go nadpisać."
        )
    return None


async def _lock_polkomtel_reprocess_targets(
    db: AsyncSession,
    plans: list[_PolkomtelReprocessPlan],
    *,
    period_month: str,
) -> None:
    """Serialize replay with every ordinary writer before protection checks.

    An existing monthly row is locked separately in
    ``_protect_newer_or_manual_consumption``.  For an absent row there is
    nothing PostgreSQL can row-lock, so replay first locks every target line,
    then every target group.  This mirrors group edits/offboarding and the
    ordinary Finance importer, preventing an order -> group / group -> order
    cycle.
    """

    expected_group_by_order = {
        plan.match.order.id: plan.match.group.id for plan in plans
    }
    locked_orders = await _lock_finance_target_orders(db, set(expected_group_by_order))
    for order_id, group_id in expected_group_by_order.items():
        if locked_orders[order_id].order_group_id != group_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Obsada zamówienia zmieniła się podczas przeliczenia.",
            )

    target_groups = {plan.match.group.id: plan.match.group for plan in plans}
    locked_groups = await _lock_finance_target_groups(db, target_groups)
    for plan in plans:
        locked_order = locked_orders[plan.match.order.id]
        locked_group = locked_groups[plan.match.group.id]
        plan.match = LineMatch(
            order=locked_order,
            group=locked_group,
            consultant_name=(
                f"{locked_order.contract.candidate.name or ''} "
                f"{locked_order.contract.candidate.lastname or ''}"
            ).strip()
            if locked_order.contract and locked_order.contract.candidate
            else "",
        )

    for plan in plans:
        if not _historical_reprocess_match_is_valid(plan, period_month=period_month):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    "Cel zmienił się podczas ponownego przeliczenia; wykonaj "
                    "ponownie dry-run."
                ),
            )


def _historical_reprocess_match_is_valid(
    plan: _PolkomtelReprocessPlan, *, period_month: str
) -> bool:
    """Revalidate the exact Polkomtel target after action-time locks."""

    order = plan.match.order
    group = plan.match.group
    first, last = month_bounds(period_month)
    contract = order.contract
    if (
        order.client_id != finance_order_matching.POLKOMTEL_CLIENT_ID
        or group.client_id != finance_order_matching.POLKOMTEL_CLIENT_ID
        or order.order_group_id != group.id
        or order.status not in (ClientOrderStatus.active, ClientOrderStatus.completed)
        or contract is None
        or contract.status == ContractStatus.void
        or contract.client_id != order.client_id
        or group.status
        not in (GROUP_STATUS_ACTIVE, GROUP_STATUS_COMPLETED, GROUP_STATUS_EXHAUSTED)
        or group.start_date > last
        or (group.end_date is not None and group.end_date < first)
        or (order.start_date is not None and order.start_date > last)
        or (order.end_date is not None and order.end_date < first)
    ):
        return False
    if plan.kind == _REPROCESS_MD_LINE and order.md_total is None:
        return False
    if plan.kind == _REPROCESS_SHARED_MD and not uses_shared_md_pool(group):
        return False
    if plan.kind == _REPROCESS_COST and not group.is_cost_based:
        return False
    return all(
        _single_polkomtel_numbered_match([plan.match], row) == (plan.match, False)
        for row in plan.rows
    )


async def _polkomtel_reprocess_successor_conflicts(
    db: AsyncSession, plans: list[_PolkomtelReprocessPlan]
) -> list[str]:
    """Fail closed when replay could split/clear MD on a successor line."""

    conflicts: list[str] = []
    for plan in plans:
        if plan.kind != _REPROCESS_MD_LINE:
            continue
        successor, successor_group = await successor_line_for(db, plan.match.order)
        if successor is None or successor_group is None:
            continue
        conflicts.append(
            f"Zamówienie {plan.match.group.order_number}: linia MD ma kontynuację "
            f"{successor_group.order_number}; ponowne przeliczenie wymaga "
            "ręcznej weryfikacji podziału MD."
        )
    return conflicts


def _reprocess_target_read(plan: _PolkomtelReprocessPlan) -> PolkomtelReprocessTarget:
    return PolkomtelReprocessTarget(
        kind=plan.kind,
        order_id=(None if plan.kind == _REPROCESS_SHARED_MD else plan.match.order.id),
        group_id=plan.match.group.id,
        order_number=plan.match.group.order_number,
        row_ids=sorted(row.id for row in plan.rows),
        row_ids_to_update=sorted(row.id for row in plan.rows_to_update),
        current_value=plan.current_value,
        expected_value=plan.expected_value,
        write_required=plan.write_required,
    )


async def _settle_shared_md_and_record(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    period_month: str,
    md_reported: Decimal,
    import_id: int,
    user_id: int,
) -> None:
    """Nadpisz miesiąc wspólnej puli, przelicz ją i zapisz historię."""
    # Lock before capturing ``before`` and before the monthly upsert. Two
    # concurrent imports must produce two truthful, serialized transitions,
    # while a budget PATCH must not overwrite a result computed from a newer
    # consumption row.
    group = await lock_group_for_settlement(db, group, flush_local_changes=False)
    before = group.md_budget_remaining
    was_exhausted = group.status == GROUP_STATUS_EXHAUSTED
    _, remaining = await upsert_shared_md_consumption(
        db,
        group=group,
        period_month=period_month,
        md_reported=md_reported,
        user_id=user_id,
    )
    used = await shared_md_used_total(db, group.id)
    available = quantize_md(
        (group.md_budget_total or Decimal("0"))
        + (group.md_budget_manual_adjustment or Decimal("0"))
    )
    if available < Decimal("0"):
        available = Decimal("0")
    over_budget = quantize_md(max(Decimal("0"), used - available))
    warning = (
        f" Raport przekracza dostępny budżet o {format_md(over_budget)} MD."
        if over_budget > Decimal("0")
        else ""
    )

    record_event(
        db,
        group_id=group.id,
        order_id=None,
        event_type=EVENT_MD_IMPORT,
        description=(
            f"Import MD za {period_month}: wspólna pula zamówienia "
            f"{group.order_number} pomniejszona o {format_md(md_reported)} MD."
            f"{warning}"
        ),
        payload={
            "period_month": period_month,
            "md_reported": str(quantize_md(md_reported)),
            "md_used_total": str(used),
            "md_over_budget": str(over_budget),
            "md_budget_remaining_before": str(before) if before is not None else None,
            "md_budget_remaining_after": str(remaining),
            "import_id": import_id,
        },
        user_id=user_id,
    )
    if not was_exhausted and group.status == GROUP_STATUS_EXHAUSTED:
        record_event(
            db,
            group_id=group.id,
            order_id=None,
            event_type=EVENT_BUDGET_EXHAUSTED,
            description=(
                f"Budżet MD zamówienia {group.order_number} został wyczerpany "
                f"(import za {period_month}). Zamówienie przeniesione "
                "do zakończonych."
            ),
            payload={"period_month": period_month, "import_id": import_id},
            user_id=user_id,
        )


async def _settle_and_record(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    period_month: str,
    import_id: int,
    user_id: int,
) -> None:
    """Przelicz budżet zamówienia i dopisz jeden wpis do jego historii.

    Jeden wpis na zamówienie, a nie na wiersz: historia ma odpowiadać na
    pytanie „co zrobił import z tym zamówieniem", a nie odtwarzać arkusz.
    """
    group = await lock_group_for_settlement(db, group, flush_local_changes=False)
    before = group.budget_remaining
    was_exhausted = group.status == GROUP_STATUS_EXHAUSTED
    remaining = await settle_group(db, group)
    total = await db.scalar(
        select(func.coalesce(func.sum(ClientOrderInvoiceConsumption.invoice_amount), 0))
        .join(ClientOrder, ClientOrder.id == ClientOrderInvoiceConsumption.order_id)
        .where(
            ClientOrder.order_group_id == group.id,
            ClientOrderInvoiceConsumption.period_month == period_month,
        )
    )
    record_event(
        db,
        group_id=group.id,
        order_id=None,
        event_type=EVENT_INVOICE_IMPORT,
        description=describe_invoice_import(
            group_number=group.order_number,
            period_month=period_month,
            total=Decimal(str(total or 0)),
        ),
        payload={
            "period_month": period_month,
            "invoiced_total": str(quantize_money(total or 0)),
            "budget_remaining_before": str(before) if before is not None else None,
            "budget_remaining_after": str(remaining),
            "import_id": import_id,
        },
        user_id=user_id,
    )
    if not was_exhausted and group.status == GROUP_STATUS_EXHAUSTED:
        record_event(
            db,
            group_id=group.id,
            order_id=None,
            event_type=EVENT_BUDGET_EXHAUSTED,
            description=(
                f"Budżet zamówienia {group.order_number} został wyczerpany "
                f"(import za {period_month}). Zamówienie przeniesione "
                "do zakończonych."
            ),
            payload={"period_month": period_month, "import_id": import_id},
            user_id=user_id,
        )
        await emit_cost_order_exhausted(db, group)


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


@router.post(
    "/imports/{import_id}/reprocess-polkomtel",
    response_model=PolkomtelReprocessResponse,
)
async def reprocess_polkomtel_import(
    import_id: int,
    payload: PolkomtelReprocessRequest,
    user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    """Re-match one stored batch after the Polkomtel SAP-prefix fix.

    The endpoint consumes the persisted import rows, so the original workbook
    is not needed.  It is a dry-run unless the caller explicitly sends
    ``{"apply": true}``.  Scope is hard-pinned to canonical Polkomtel and
    existing manual/newer monthly consumptions are protected from overwrite.
    """

    batch_query = select(MdConsumptionImport).where(MdConsumptionImport.id == import_id)
    if payload.apply:
        batch_query = batch_query.with_for_update()
    batch = await db.scalar(batch_query)
    if batch is None:
        raise HTTPException(404, detail="Import nie istnieje")

    rows_query = (
        select(MdConsumptionImportRow)
        .where(MdConsumptionImportRow.import_id == batch.id)
        .order_by(MdConsumptionImportRow.row_number.asc())
    )
    if payload.apply:
        rows_query = rows_query.with_for_update()
    rows = list((await db.execute(rows_query)).scalars())

    # A July order can be completed or exhausted today.  Replays therefore
    # select by the batch month, while ordinary uploads above deliberately keep
    # using today's active-only candidates.
    md_candidates = await historical_md_lines(db, batch.period_month)
    shared_md_candidates = await historical_shared_md_lines(db, batch.period_month)
    cost_candidates = await historical_cost_lines(db, batch.period_month)
    plans, conflicts = _build_polkomtel_reprocess_plan(
        rows,
        md_candidates=md_candidates,
        shared_md_candidates=shared_md_candidates,
        cost_candidates=cost_candidates,
    )
    if payload.apply:
        await _lock_polkomtel_reprocess_targets(
            db,
            plans,
            period_month=batch.period_month,
        )
    conflicts.extend(await _polkomtel_reprocess_successor_conflicts(db, plans))
    cost_groups_to_settle: dict[int, ClientOrderGroup] = {}
    for plan in plans:
        conflict = await _protect_newer_or_manual_consumption(
            db,
            batch=batch,
            plan=plan,
            lock=payload.apply,
        )
        if conflict is not None:
            conflicts.append(conflict)
    conflicts = list(dict.fromkeys(conflicts))

    row_ids_to_update = {row.id for plan in plans for row in plan.rows_to_update}
    response = PolkomtelReprocessResponse(
        import_id=batch.id,
        period_month=batch.period_month,
        client_id=finance_order_matching.POLKOMTEL_CLIENT_ID,
        applied=False,
        rows_scanned=len(rows),
        rows_to_update=len(row_ids_to_update),
        targets_to_recalculate=sum(plan.write_required for plan in plans),
        conflicts=conflicts,
        targets=[_reprocess_target_read(plan) for plan in plans],
    )
    if not payload.apply:
        return response
    if conflicts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "polkomtel_reprocess_conflict",
                "conflicts": conflicts,
            },
        )

    # Data writes use the same idempotent upsert/settlement functions as a new
    # upload.  One event is produced per changed target; a second APPLY sees no
    # rows to update and produces neither writes nor duplicate history.
    for plan in plans:
        if not plan.write_required:
            continue
        if plan.kind == _REPROCESS_MD_LINE:
            await _apply_to_line(
                db,
                match_order=plan.match.order,
                group=plan.match.group,
                period_month=batch.period_month,
                md_reported=plan.expected_value,
                import_id=batch.id,
                user_id=user.id,
                historical_reprocess=True,
            )
        elif plan.kind == _REPROCESS_SHARED_MD:
            await _settle_shared_md_and_record(
                db,
                group=plan.match.group,
                period_month=batch.period_month,
                md_reported=plan.expected_value,
                import_id=batch.id,
                user_id=user.id,
            )
        else:
            await upsert_invoice(
                db,
                order=plan.match.order,
                period_month=batch.period_month,
                invoice_amount=plan.expected_value,
                import_id=batch.id,
                user_id=user.id,
            )
            cost_groups_to_settle[plan.match.group.id] = plan.match.group

    for group_id in sorted(cost_groups_to_settle):
        group = cost_groups_to_settle[group_id]
        await _settle_and_record(
            db,
            group=group,
            period_month=batch.period_month,
            import_id=batch.id,
            user_id=user.id,
        )

    for plan in plans:
        for row in plan.rows_to_update:
            row.order_number_hint = plan.match.group.order_number.strip()
            if plan.kind == _REPROCESS_COST:
                row.matched_group_id = plan.match.group.id
                row.cost_status = COST_ROW_APPLIED
            else:
                row.status = IMPORT_ROW_APPLIED
                row.matched_order_id = plan.match.order.id
                row.candidate_order_ids = None
                if plan.kind == _REPROCESS_SHARED_MD:
                    row.matched_group_id = plan.match.group.id

    await db.flush()
    await _recount(db, batch)
    await db.commit()
    response.applied = True
    return response


@router.post("/imports/{import_id}/rows/{row_id}/assign", response_model=ImportRowRead)
async def assign_row(
    import_id: int,
    row_id: int,
    payload: AssignRowRequest,
    user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    """Ręczne rozstrzygnięcie wiersza „Wymaga przypisania"."""
    # The reprocessor uses the same batch -> row -> order lock order.  Reading
    # status before those locks allowed a concurrent assignment to resume on a
    # stale ``needs_assignment`` snapshot and overwrite replay's decision.
    batch = await db.scalar(
        select(MdConsumptionImport)
        .where(MdConsumptionImport.id == import_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if batch is None:
        raise HTTPException(404, detail="Import nie istnieje")

    row = await db.scalar(
        select(MdConsumptionImportRow)
        .where(
            MdConsumptionImportRow.id == row_id,
            MdConsumptionImportRow.import_id == import_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
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

    # Zapis idzie po kluczu (linia, miesiąc) i NADPISUJE, więc rozstrzygnięcie
    # nie może wysłać samego ``row.md_reported``: gdyby na tę samą linię trafił
    # już inny wiersz tego importu (automatycznie albo wcześniejszym
    # przypisaniem), jego MD zostałyby skasowane. Wysyłamy sumę wszystkich
    # zastosowanych wierszy tej paczki dla tej linii — to daje ten sam wynik co
    # ścieżka wsadowa i jest odporne na kolejność rozstrzygania.
    already_applied = await db.scalar(
        select(func.coalesce(func.sum(MdConsumptionImportRow.md_reported), 0)).where(
            MdConsumptionImportRow.import_id == batch.id,
            MdConsumptionImportRow.matched_order_id == order.id,
            MdConsumptionImportRow.status == IMPORT_ROW_APPLIED,
            MdConsumptionImportRow.id != row.id,
        )
    )
    await _apply_to_line(
        db,
        match_order=order,
        group=order.order_group,
        period_month=batch.period_month,
        md_reported=Decimal(str(already_applied or 0)) + row.md_reported,
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
