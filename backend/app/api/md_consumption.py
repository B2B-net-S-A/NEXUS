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
from app.models.client_order_group import GROUP_STATUS_EXHAUSTED, ClientOrderGroup
from app.models.contract import Contract
from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    COST_ROW_APPLIED,
    COST_ROW_STATUS_LABELS,
    COST_ROW_UNMATCHED_CONSULTANT,
    COST_ROW_UNMATCHED_NUMBER,
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
from app.services.client_identity import client_display_name_expression
from app.services.client_order_lines import (
    LineMatch,
    active_cost_lines,
    active_md_lines,
    active_shared_md_lines,
    apply_md_consumption,
    describe_import,
    match_by_name,
    month_bounds,
    record_event,
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
) -> None:
    """Zapisz MD na linii i dopisz jeden wpis do historii jej zamówienia.

    Grupa, a nie samo ``group_id``: treść wpisu niesie numer zamówienia, a
    podział nadwyżki na następcę potrzebuje numerów obu stron. Obie ścieżki
    importu — wsadowa i ręczne rozstrzygnięcie — wołają tę funkcję, więc
    podział nie zależy od tego, którą z nich operator akurat wybrał.
    """
    outcome = await apply_md_consumption(
        db,
        order=match_order,
        group=group,
        period_month=period_month,
        md_reported=md_reported,
        import_id=import_id,
        user_id=user_id,
    )
    if group is not None:
        record_event(
            db,
            group_id=group.id,
            order_id=match_order.id,
            event_type=EVENT_MD_IMPORT,
            description=describe_import(
                match_order,
                period_month,
                outcome.applied,
                outcome.previous,
                order_number=group.order_number,
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
    pending_shared_md: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    shared_md_groups: dict[int, ClientOrderGroup] = {}

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
        )
        if not consultant_in_shared_md:
            matches = match_by_name(candidates, parsed_row.consultant_name)
            if len(matches) == 1:
                match = matches[0]
                row.status = IMPORT_ROW_APPLIED
                row.matched_order_id = match.order.id
                pending_md[match.order.id] += parsed_row.md_reported
                md_orders[match.order.id] = (match.order, match.group)
            elif len(matches) > 1:
                row.status = IMPORT_ROW_NEEDS_ASSIGNMENT
                row.candidate_order_ids = [m.order.id for m in matches]

        # ── Ścieżka kosztowa: NIEZALEŻNA od dopasowania MD po nazwisku ──
        # Prawidłowo dopasowany numer wspólnej puli MD nie może jednocześnie
        # zgłaszać „brak zamówienia kosztowego o tym numerze". Typy grup są
        # rozłączne, więc taki wiersz kończy routing na ścieżce shared-MD.
        shared_md_applied = consultant_in_shared_md and row.status == IMPORT_ROW_APPLIED
        if not shared_md_applied:
            _match_cost_row(
                row,
                parsed_row=parsed_row,
                cost_candidates=cost_candidates,
                pending_invoices=pending_invoices,
                invoice_orders=invoice_orders,
                touched_groups=touched_groups,
            )
        db.add(row)

    for order_id, md_total in pending_md.items():
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

    # Stała kolejność blokad grup — dwa równoległe raporty obejmujące te same
    # zamówienia w innej kolejności wierszy nie mogą zakleszczyć transakcji.
    for group_id in sorted(pending_shared_md):
        await _settle_shared_md_and_record(
            db,
            group=shared_md_groups[group_id],
            period_month=period_month,
            md_reported=pending_shared_md[group_id],
            import_id=batch.id,
            user_id=user.id,
        )

    for order_id, amount in pending_invoices.items():
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


def _match_shared_md_row(
    row: MdConsumptionImportRow,
    *,
    parsed_row,
    shared_md_candidates: list[LineMatch],
    pending_shared_md: dict[int, Decimal],
    shared_md_groups: dict[int, ClientOrderGroup],
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
    numbered = [match for match in named if match.group.order_number.strip() in hints]
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
    return True


def _match_cost_row(
    row: MdConsumptionImportRow,
    *,
    parsed_row,
    cost_candidates: list[LineMatch],
    pending_invoices: dict[int, Decimal],
    invoice_orders: dict[int, ClientOrder],
    touched_groups: dict[int, ClientOrderGroup],
) -> None:
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
        return

    # Numer zamówienia nie jest globalnie unikalny (ani w bazie, ani między
    # klientami), więc nie wolno zwijać kandydatów do słownika po samym
    # numerze. Najpierw konfrontujemy WSZYSTKIE numery z uwag, potem nazwisko,
    # i akceptujemy wyłącznie dokładnie jedną linię. Dzięki temu dwa zamówienia
    # „445" u Polkomtela, Cyfrowego Polsatu i Lotte Wedel nie nadpisują się zależnie od
    # kolejności wyniku zapytania.
    numbered = [
        match for match in cost_candidates if match.group.order_number.strip() in hints
    ]
    if not numbered:
        row.cost_status = COST_ROW_UNMATCHED_NUMBER
        return

    named = match_by_name(numbered, parsed_row.consultant_name)
    if len(named) != 1:
        # Zero trafień albo niejednoznaczność — w obu przypadkach system NIE
        # zgaduje. Kwota trafiłaby wtedy na cudzą linię, a „Zafakturowano"
        # przy konsultancie przestałoby zgadzać się z jego fakturami.
        row.cost_status = COST_ROW_UNMATCHED_CONSULTANT
        return

    match = named[0]
    group = match.group
    order = match.order
    row.matched_group_id = group.id
    row.order_number_hint = group.order_number.strip()
    row.cost_status = COST_ROW_APPLIED
    pending_invoices[order.id] += quantize_money(amount)
    invoice_orders[order.id] = order
    touched_groups[group.id] = group


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
