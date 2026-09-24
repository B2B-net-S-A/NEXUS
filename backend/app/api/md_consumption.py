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
* zero linii → ``Brak pasującego zamówienia`` (wiersz zostaje, nie przerywa
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
from datetime import date as date_type, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

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
    COST_ROW_NON_POSITIVE,
    COST_ROW_STATUS_LABELS,
    COST_ROW_UNMATCHED_CONSULTANT,
    COST_ROW_UNMATCHED_NUMBER,
    CONSUMPTION_SOURCE_MANUAL,
    IMPORT_ROW_APPLIED,
    IMPORT_ROW_COST_ONLY,
    IMPORT_ROW_NEEDS_ASSIGNMENT,
    IMPORT_ROW_OVERFLOW,
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
from app.services.contract_lifecycle import lock_contract_then_orders
from app.services.client_identity import client_display_name_expression
from app.services.client_order_lines import (
    LineMatch,
    apply_md_consumption,
    candidate_name_tokens,
    exhausted_groups_with_month_entry,
    cost_lines_settling_in_month,
    describe_import,
    format_period_month,
    group_settles_in_month,
    historical_cost_lines,
    historical_md_lines,
    historical_shared_md_lines,
    line_settles_in_month,
    match_by_name,
    prefer_active_line,
    md_lines_for_numbered_rows,
    md_lines_settling_in_month,
    month_bounds,
    name_tokens,
    record_event,
    shared_md_lines_settling_in_month,
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
from app.services.dl_alerts import (
    emit_cost_order_exhausted,
    emit_shared_md_pool_exhausted,
)
from app.services.multi_consultant_orders import (
    EVENT_BUDGET_EXHAUSTED,
    EVENT_INVOICE_IMPORT,
    EVENT_MD_IMPORT,
    format_md,
    quantize_md,
)
from app.services.order_policies import md_exhaustion_client_ids
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


async def _order_number_index(
    db: AsyncSession,
) -> finance_order_matching.OrderNumberIndex:
    """Numery wszystkich zamówień grupowych — do rozpoznania numeru w „Uwagach"."""
    rows = await db.execute(
        select(ClientOrderGroup.client_id, ClientOrderGroup.order_number)
    )
    return finance_order_matching.build_order_number_index(rows.all())


def _fmt_day(value) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


@dataclass
class _ReasonContext:
    """Dane do opisu niedopasowanych wierszy — ładowane raz na odczyt paczki."""

    index: finance_order_matching.OrderNumberIndex
    groups: dict[int, object]
    lines_by_person: dict[frozenset[str], list[ClientOrder]]


async def _reason_context(db: AsyncSession) -> _ReasonContext:
    groups = {
        g.id: g
        for g in (
            await db.execute(
                select(
                    ClientOrderGroup.id,
                    ClientOrderGroup.client_id,
                    ClientOrderGroup.order_number,
                    ClientOrderGroup.is_cost_based,
                )
            )
        ).all()
    }
    lines = (
        await db.execute(
            select(ClientOrder)
            .options(
                selectinload(ClientOrder.contract).selectinload(Contract.candidate)
            )
            .where(
                ClientOrder.order_group_id.isnot(None),
                ClientOrder.status != ClientOrderStatus.cancelled,
            )
            .order_by(ClientOrder.id.asc())
        )
    ).scalars()
    by_person: dict[frozenset[str], list[ClientOrder]] = defaultdict(list)
    for line in lines:
        tokens = candidate_name_tokens(
            line.contract.candidate if line.contract else None
        )
        if tokens:
            by_person[tokens].append(line)
    return _ReasonContext(
        index=finance_order_matching.build_order_number_index(
            (g.client_id, g.order_number) for g in groups.values()
        ),
        groups=groups,
        lines_by_person=by_person,
    )


def _unmatched_reason(
    row: MdConsumptionImportRow,
    period_month: Optional[str],
    context: Optional[_ReasonContext],
) -> Optional[str]:
    """Dlaczego wiersz z wiążącym numerem zamówienia nie trafił na żadną linię.

    Liczone przy odczycie (bez kolumny w bazie), więc opis mówi o dzisiejszym
    stanie zamówień — tym, który operator ma poprawić. Numer wiąże się tą samą
    regułą co przy imporcie (klienci tej osoby, ``_authoritative_md_hints``).
    ``None`` = wiersz bez wiążącego numeru; tam wystarcza sam status.
    """
    if (
        context is None
        or row.status != IMPORT_ROW_UNMATCHED
        or not period_month
        or row.cost_status == COST_ROW_APPLIED
    ):
        return None
    hints = extract_order_number_candidates(row.notes_raw)
    wanted = name_tokens(row.consultant_name)
    person_lines = context.lines_by_person.get(wanted, []) if wanted else []
    if not hints or not person_lines:
        return None
    clients = {line.client_id for line in person_lines}
    if finance_order_matching.POLKOMTEL_CLIENT_ID in clients:
        authoritative = list(hints)
    else:
        authoritative = finance_order_matching.explicit_order_hints(
            hints, context.index, clients
        )
    if not authoritative:
        return None
    number = authoritative[0]
    not_elsewhere = "Zużycie nie trafiło na żadne inne zamówienie tej osoby"
    matching_ids = {
        g.id
        for g in context.groups.values()
        if g.client_id in clients
        and finance_order_matching.finance_order_number_matches(
            client_id=g.client_id,
            order_number=g.order_number,
            numeric_hints=authoritative,
        )
    }
    if not matching_ids:
        return (
            f"Zamówienia nr {number} nie ma w NEXUSIE. {not_elsewhere} — "
            "dodaj zamówienie albo popraw numer w arkuszu."
        )
    on_order = [line for line in person_lines if line.order_group_id in matching_ids]
    if not on_order:
        return (
            f"Na zamówieniu nr {number} nie ma osoby z arkusza. {not_elsewhere} — "
            "sprawdź numer w arkuszu albo obsadę zamówienia."
        )
    line = on_order[0]
    group = context.groups[line.order_group_id]
    label = format_period_month(period_month)
    if group.is_cost_based:
        return (
            f"Zamówienie nr {number} jest kosztowe — rozlicza fakturę, nie liczbę MD. "
            f"{not_elsewhere}."
        )
    if not line_settles_in_month(line, period_month, contract=line.contract):
        return (
            f"Okres tej osoby na zamówieniu nr {number} "
            f"({_fmt_day(line.start_date)} – "
            f"{_fmt_day(line.end_date) if line.end_date else 'bezterminowo'}) "
            f"nie obejmuje miesiąca raportu ({label}). {not_elsewhere} — "
            "sprawdź okres albo numer zamówienia."
        )
    return (
        f"Zamówienie nr {number} nie rozlicza miesiąca raportu ({label}). "
        f"{not_elsewhere} — sprawdź okres i status zamówienia."
    )


def _overflow_label(md: Optional[Decimal]) -> str:
    label = IMPORT_ROW_STATUS_LABELS[IMPORT_ROW_OVERFLOW]
    return f"{label} o {format_md(md)} MD" if md is not None else label


async def _row_to_read(
    db: AsyncSession,
    row: MdConsumptionImportRow,
    period_month: Optional[str] = None,
    reason_context: Optional[_ReasonContext] = None,
    merged_rows: int = 1,
) -> ImportRowRead:
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

    status_reason = _unmatched_reason(row, period_month, reason_context)
    if row.status == IMPORT_ROW_OVERFLOW:
        status_label = _overflow_label(row.overflow_md)
    elif status_reason:
        # Wiersz wskazał numer zamówienia, którego nie da się rozliczyć —
        # ticket 1.1: „Do weryfikacji” z opisem przyczyny.
        status_label = "Do weryfikacji"
    else:
        status_label = IMPORT_ROW_STATUS_LABELS.get(row.status, row.status)
    return ImportRowRead(
        id=row.id,
        row_number=row.row_number,
        consultant_name=row.consultant_name,
        md_reported=row.md_reported,
        status=row.status,
        status_label=status_label,
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
        status_reason=status_reason,
        overflow_md=row.overflow_md,
        merged_rows=merged_rows,
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
    # „Do weryfikacji – przekroczenie puli” też czeka na człowieka.
    batch.rows_ambiguous = sum(
        1 for s in statuses if s in (IMPORT_ROW_NEEDS_ASSIGNMENT, IMPORT_ROW_OVERFLOW)
    )
    batch.rows_unmatched = sum(1 for s in statuses if s == IMPORT_ROW_UNMATCHED)

    cost_result = await db.execute(
        select(MdConsumptionImportRow.cost_status).where(
            MdConsumptionImportRow.import_id == batch.id
        )
    )
    cost_statuses = [c for (c,) in cost_result if c is not None]
    batch.rows_cost_applied = sum(1 for c in cost_statuses if c == COST_ROW_APPLIED)
    batch.rows_cost_unmatched = len(cost_statuses) - batch.rows_cost_applied


async def _rollback_trial(db: AsyncSession, savepoint) -> None:
    """Cofnij próbny zapis i doczytaj obiekty, które savepoint wygasił.

    SQLAlchemy wygasza przy wycofaniu savepointu obiekty zmienione w nim
    (grupa, linia) — następny dostęp do atrybutu w sesji async to
    ``MissingGreenlet``. Blokady wierszy z transakcji głównej zostają.
    """
    await savepoint.rollback()
    for obj in list(db.identity_map.values()):
        state = sa_inspect(obj)
        if state.persistent and state.expired_attributes:
            await db.refresh(obj)


def _negative_delta(before, after) -> Decimal:
    """O ile zapis zepchnął saldo poniżej zera (0 = nie zepchnął)."""
    if after is None:
        return Decimal("0")
    after = Decimal(str(after))
    if after >= 0:
        return Decimal("0")
    if before is not None:
        before = Decimal(str(before))
        if after >= before:
            return Decimal("0")  # ten zapis salda nie pogorszył
        if before < 0:
            return quantize_md(before - after)
    return quantize_md(-after)


def _booking_overflow(outcome, before_remaining: dict) -> Decimal:
    """Przekroczenie puli po zapisie zejścia (linia docelowa i następca)."""
    if outcome is None:
        return Decimal("0")
    landed = outcome.order
    worst = Decimal("0")
    if landed is not None:
        worst = max(
            worst,
            _negative_delta(before_remaining.get(landed.id), landed.md_remaining),
        )
    successor = outcome.successor_order
    if successor is not None and outcome.transferred:
        worst = max(
            worst,
            _negative_delta(before_remaining.get(successor.id), successor.md_remaining),
        )
    return worst


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
    explicit_order: bool = False,
    ignore_period: bool = False,
    overflow_approved: Optional[Decimal] = None,
):
    """Zapisz MD na linii i dopisz jeden wpis do historii jej zamówienia.

    Zwraca wynik ``apply_md_consumption`` (linia, na której zapis wylądował,
    i jej pozostałość) — import sprawdza po nim, czy saldo nie zeszło poniżej
    zera (ticket 1.1). ``ignore_period``: wiersz z numerem zamówienia BIK
    (data zamówienia = data wystawienia, ``md_lines_for_numbered_rows``).
    ``overflow_approved``: człowiek zatwierdził przekroczenie o tyle MD —
    wpis w historii mówi to wprost.

    ``explicit_order``: wiersz wskazał TO zamówienie numerem z „Uwag" — zużycie
    zostaje wyłącznie na nim (bez przekierowania na poprzednika i bez
    przeniesienia nadwyżki na następcę, ticket 23.09.2026).

    Grupa, a nie samo ``group_id``: treść wpisu niesie numer zamówienia, a
    podział nadwyżki na następcę potrzebuje numerów obu stron. Obie ścieżki
    importu — wsadowa i ręczne rozstrzygnięcie — wołają tę funkcję, więc
    podział nie zależy od tego, którą z nich operator akurat wybrał.
    """
    expected_group_id = group.id if group is not None else match_order.order_group_id
    # Kolejność blokad writerów zamówień: kontrakt → zamówienie.
    await lock_contract_then_orders(db, order_ids=[match_order.id])
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
    # Jedna reguła dla obu ścieżek: linia rozlicza miesiąc, jeżeli go OBSADZAŁA
    # (`line_settles_in_month`) — status „zakończona" nie jest przeszkodą, bo
    # raport za sierpień wpływa do systemu długo po zejściu konsultanta.
    # Anulowana linia nie rozlicza nigdy, a ostatnim sitem jest niezmienność
    # grupy pod blokadą: to ona chroni przed nadpisaniem przez równoległą
    # zmianę obsady.
    line_is_valid = locked_order is not None and line_settles_in_month(
        locked_order,
        period_month,
        contract=locked_order.contract,
        ignore_period=ignore_period,
    )
    target_is_valid = line_is_valid
    if target_is_valid and historical_reprocess:
        # Replay starej paczki dokłada do tego okres samej GRUPY — zwykły
        # import sprawdza go wcześniej (`_ordinary_locked_target_is_valid`),
        # więc tutaj nie sięgamy po atrybuty grupy poza tą ścieżką.
        group_now = locked_order.order_group
        target_is_valid = (
            group_now is not None
            and group_now.status
            in (GROUP_STATUS_ACTIVE, GROUP_STATUS_COMPLETED, GROUP_STATUS_EXHAUSTED)
            and group_now.start_date <= last
            and (group_now.end_date is None or group_now.end_date >= first)
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
        explicit_order=explicit_order,
    )
    # FIN-MD-01: miesiąc już raz podzielony rozlicza się od poprzednika — wpis
    # historii ląduje na linii, na której rozliczenie faktycznie się zaczęło.
    if getattr(outcome, "order", None) is not None:
        locked_order = outcome.order
        locked_group = outcome.group
    if locked_group is not None:
        description = describe_import(
            locked_order,
            period_month,
            outcome.applied,
            outcome.previous,
            order_number=locked_group.order_number,
        )
        if overflow_approved is not None:
            description += (
                f" Przekroczenie puli o {format_md(overflow_approved)} MD "
                "zatwierdzone ręcznie."
            )
        record_event(
            db,
            group_id=locked_group.id,
            order_id=locked_order.id,
            event_type=EVENT_MD_IMPORT,
            description=description,
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
                **(
                    {"overflow_approved_md": str(overflow_approved)}
                    if overflow_approved is not None
                    else {}
                ),
            },
            user_id=user_id,
        )
    return outcome


async def _lock_finance_target_orders(
    db: AsyncSession, order_ids: set[int]
) -> dict[int, ClientOrder]:
    """Lock every target line once, globally ordered by primary key."""

    if not order_ids:
        return {}
    ordered_ids = sorted(order_ids)
    await lock_contract_then_orders(db, order_ids=ordered_ids)
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


async def _md_family_line_ids(db: AsyncSession, group_ids: set[int]) -> set[int]:
    """Linie zamówień MD celów importu wraz z ich poprzednikami i następcami."""

    if not group_ids:
        return set()
    predecessors = set(
        (
            await db.scalars(
                select(ClientOrderGroup.predecessor_group_id).where(
                    ClientOrderGroup.id.in_(group_ids),
                    ClientOrderGroup.predecessor_group_id.is_not(None),
                )
            )
        ).all()
    )
    successors = set(
        (
            await db.scalars(
                select(ClientOrderGroup.id).where(
                    ClientOrderGroup.predecessor_group_id.in_(group_ids)
                )
            )
        ).all()
    )
    family = group_ids | predecessors | successors
    return set(
        (
            await db.scalars(
                select(ClientOrder.id).where(ClientOrder.order_group_id.in_(family))
            )
        ).all()
    )


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
    correctable_exhausted_group_ids: frozenset[int] = frozenset(),
    order_numbers: Optional[finance_order_matching.OrderNumberIndex] = None,
    ignore_period: bool = False,
) -> bool:
    """Re-match persisted spreadsheet evidence after line/group lock waits.

    ``ignore_period`` — linia wskazana numerem u klienta, którego data
    zamówienia nie jest okresem usługi (BIK, ticket 1.1): okres linii nie
    jest wtedy warunkiem, numer z arkusza nadal jest.

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
        or (
            not ignore_period
            and (
                (order.start_date is not None and order.start_date > last)
                or (order.end_date is not None and order.end_date < first)
            )
        )
    ):
        return False

    # Stan linii: OKRES, nie status — lustro `line_settles_in_month`, którym
    # wybrano kandydatów. Linia zakończona po miesiącu, którego dotyczy
    # raport, nadal go rozlicza; `cancelled` nie rozlicza nigdy.
    #
    # Stan grupy: ta sama reguła co przy wyborze kandydatów
    # (`shared_md_lines_settling_in_month` / `cost_lines_settling_in_month`).
    # Zamówienie zakończone z datą nie wcześniejszą niż ten miesiąc nadal się
    # w nim rozlicza — bez lustra import wybierał je, a po blokadach odrzucał
    # całą partię 409.
    if kind == "md_line":
        if (
            not line_settles_in_month(
                order, period_month, contract=contract, ignore_period=ignore_period
            )
            or order.md_total is None
        ):
            return False
    elif kind == "shared_md":
        if (
            not line_settles_in_month(order, period_month, contract=contract)
            or not (
                group_settles_in_month(group, first)
                or group.id in correctable_exhausted_group_ids
            )
            or not uses_shared_md_pool(group)
        ):
            return False
    elif kind == "cost":
        if (
            not line_settles_in_month(
                order, period_month, contract=contract, include_draft=True
            )
            or not (
                group_settles_in_month(group, first)
                or group.id in correctable_exhausted_group_ids
            )
            or not group.is_cost_based
        ):
            return False
    else:
        return False

    for row in rows:
        if match_by_name([current_match], row.consultant_name) != [current_match]:
            return False
        hints = extract_order_number_candidates(row.notes_raw)
        # Wiersz MD z jawnym numerem zamówienia (u każdego klienta, ticket
        # 23.09.2026; u Polkomtela — każdy numer) musi nadal wskazywać TO
        # zamówienie po zdjęciu blokad.
        number_is_evidence = (
            kind in ("shared_md", "cost")
            or ignore_period
            or bool(
                _authoritative_md_hints(
                    hints,
                    named=[current_match],
                    order_numbers=order_numbers,
                )
            )
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
        # N6: openpyxl parsuje synchronicznie — duży arkusz blokowałby pętlę
        # zdarzeń całego procesu (backend to jeden uvicorn).
        parsed = await run_in_threadpool(parse_md_sheet, payload)
    except MdSheetFormatError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    candidates = await md_lines_settling_in_month(db, period_month)
    # BIK (ticket 1.1): wiersz z numerem trafia na to zamówienie niezależnie
    # od jego daty — data zamówienia SAP to data wystawienia, nie okres usługi.
    numbered_candidates = await md_lines_for_numbered_rows(
        db, md_exhaustion_client_ids()
    )
    in_period_line_ids = {match.order.id for match in candidates}
    shared_md_candidates = await shared_md_lines_settling_in_month(db, period_month)
    cost_candidates = await cost_lines_settling_in_month(db, period_month)
    order_numbers = await _order_number_index(db)

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
    # Linie wskazane NUMEREM zamówienia z „Uwag" — zużycie zostaje wyłącznie
    # na nich (bez przekierowania na poprzednika i przeniesienia na następcę).
    explicit_md_orders: set[int] = set()
    # …i te z nich, których okres nie obejmuje miesiąca raportu (BIK).
    period_exempt_orders: set[int] = set()
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
            status=(
                IMPORT_ROW_COST_ONLY
                if getattr(parsed_row, "cost_only", False)
                else IMPORT_ROW_UNMATCHED
            ),
            notes_raw=parsed_row.notes_raw,
            order_number_hint=parsed_row.order_number_hint,
            invoice_amount=parsed_row.invoice_amount,
        )
        if getattr(parsed_row, "cost_only", False):
            # FIN-MD-06: wiersz z samą fakturą rozlicza wyłącznie pulę
            # kosztową — do budżetów MD (per osoba i wspólnej puli) nie idzie.
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
            continue

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
        md_explicit_applied = False
        if not consultant_in_shared_md:
            matches = _match_per_consultant_md_row(
                parsed_row=parsed_row,
                candidates=candidates,
                order_numbers=order_numbers,
                numbered_candidates=numbered_candidates,
            )
            authoritative = _authoritative_md_hints(
                extract_order_number_candidates(parsed_row.notes_raw),
                named=match_by_name(
                    candidates + numbered_candidates, parsed_row.consultant_name
                ),
                order_numbers=order_numbers,
            )
            if len(matches) == 1:
                match = matches[0]
                row.status = IMPORT_ROW_APPLIED
                row.matched_order_id = match.order.id
                pending_md[match.order.id] += parsed_row.md_reported
                md_orders[match.order.id] = (match.order, match.group)
                md_rows[match.order.id].append(row)
                if authoritative:
                    md_explicit_applied = True
                    explicit_md_orders.add(match.order.id)
                    row.order_number_hint = match.group.order_number.strip()[:64]
                    if match.order.id not in in_period_line_ids:
                        period_exempt_orders.add(match.order.id)
            elif len(matches) > 1:
                row.status = IMPORT_ROW_NEEDS_ASSIGNMENT
                row.candidate_order_ids = [m.order.id for m in matches]
            elif authoritative:
                # Wiersz wskazał zamówienie, którego ta osoba nie rozlicza w tym
                # miesiącu — zostaje do weryfikacji z numerem z arkusza, a powód
                # składa `_unmatched_reason` przy odczycie.
                row.order_number_hint = authoritative[0][:64]

        # ── Ścieżka kosztowa: NIEZALEŻNA od dopasowania MD po nazwisku ──
        # Prawidłowo dopasowany numer wspólnej puli MD nie może jednocześnie
        # zgłaszać „brak zamówienia kosztowego o tym numerze". Typy grup są
        # rozłączne, więc taki wiersz kończy routing na ścieżce shared-MD.
        shared_md_applied = consultant_in_shared_md and row.status == IMPORT_ROW_APPLIED
        # Numer, który wskazał zamówienie MD tej osoby, jest rozliczony — ścieżka
        # kosztowa (typy grup są rozłączne) zgłaszałaby przy nim fałszywe
        # „Brak zamówienia o tym numerze".
        if not shared_md_applied and not md_explicit_applied:
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
    # S8 (audyt 24.09.2026): zapis MD per osoba dotyka też linii poza celami
    # z arkusza — poprzednika (FIN-MD-01), następcy (nadwyżka), następcy
    # zamiany i celu przeniesienia puli (korekty FIN-MD-02). Ich kontrakty
    # i wiersze blokujemy RAZEM z celami, w jednej kolejności kontrakt →
    # linia → grupa; blokada kontraktu wzięta później szłaby po blokadach
    # linii i grup i zamykała cykl z anulowaniem/zakończeniem zamówienia.
    family_line_ids = await _md_family_line_ids(
        db, {group.id for _, group in md_orders.values()}
    )
    locked_orders = await _lock_finance_target_orders(
        db, set(expected_group_by_order) | family_line_ids
    )
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

    # FIN-MD-08: grupy wyczerpane, które już mają wpis za ten miesiąc, są
    # celem korekty (patrz `_exhausted_with_month_entry_clause`).
    correctable_exhausted = await exhausted_groups_with_month_entry(
        db, locked_groups.keys(), period_month
    )
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
            order_numbers=order_numbers,
            ignore_period=order_id in period_exempt_orders,
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
            correctable_exhausted_group_ids=correctable_exhausted,
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
            correctable_exhausted_group_ids=correctable_exhausted,
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Zamówienie kosztowe zmieniło się podczas importu.",
            )

    # Ticket 1.1: zejście, po którym saldo spadłoby poniżej zera, nie jest
    # księgowane automatycznie. Zapis idzie próbnie w savepoincie (ta sama
    # ścieżka co zwykły zapis — podział na następcę, przekierowanie na
    # poprzednika), a przy przekroczeniu jest cofany razem ze skutkami
    # (automatyczne zakończenie zamówienia na błędnym saldzie).
    before_remaining = {
        oid: locked.md_remaining for oid, locked in locked_orders.items()
    }
    await db.flush()
    for order_id in sorted(pending_md):
        md_total = pending_md[order_id]
        order_obj, order_group = md_orders[order_id]
        savepoint = await db.begin_nested()
        outcome = await _apply_to_line(
            db,
            match_order=order_obj,
            group=order_group,
            period_month=period_month,
            md_reported=md_total,
            import_id=batch.id,
            user_id=user.id,
            explicit_order=order_id in explicit_md_orders,
            ignore_period=order_id in period_exempt_orders,
        )
        overflow = _booking_overflow(outcome, before_remaining)
        if overflow > Decimal("0"):
            await _rollback_trial(db, savepoint)
            for held in md_rows[order_id]:
                held.status = IMPORT_ROW_OVERFLOW
                held.overflow_md = overflow
                held.candidate_order_ids = [order_id]
        else:
            await savepoint.commit()
            # Następny zapis porównuje się ze stanem PO tym (rodzina linii
            # bywa wspólna: przeniesienie nadwyżki na następcę).
            for touched in (outcome.order, outcome.successor_order):
                if touched is not None:
                    before_remaining[touched.id] = touched.md_remaining

    for group_id in sorted(pending_shared_md):
        before_used = await shared_md_used_total(db, group_id)
        # S5: plik korygujący za ten sam miesiąc niesie zwykle tylko część osób.
        # Miesiąc puli to JEDNA suma, więc bez tego nadpisałby ją samymi
        # osobami z pliku, a wkład pozostałych przepadłby bez śladu.
        present = {
            order_id
            for order_id, order in shared_md_orders.items()
            if order.order_group_id == group_id
        }
        carried, carried_names = await _shared_md_carry_over(
            db,
            group_id=group_id,
            period_month=period_month,
            import_id=batch.id,
            present_order_ids=present,
        )
        await db.flush()
        savepoint = await db.begin_nested()
        overflow = await _settle_shared_md_and_record(
            db,
            group=shared_md_groups[group_id],
            period_month=period_month,
            md_reported=pending_shared_md[group_id] + carried,
            import_id=batch.id,
            user_id=user.id,
            carried_md=carried,
            carried_names=carried_names,
            before_used=before_used,
        )
        if overflow > Decimal("0"):
            # Pula wspólna: cały miesiąc grupy czeka na zatwierdzenie — suma
            # miesiąca jest jedna, więc nie da się zaksięgować części osób.
            await _rollback_trial(db, savepoint)
            for held_order_id in present:
                for held in shared_md_rows.get(held_order_id, []):
                    held.status = IMPORT_ROW_OVERFLOW
                    held.overflow_md = overflow
                    held.candidate_order_ids = [held_order_id]
        else:
            await savepoint.commit()

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


def _authoritative_md_hints(
    hints: list[str],
    *,
    named: list[LineMatch],
    order_numbers: Optional[finance_order_matching.OrderNumberIndex],
) -> list[str]:
    """Numery z „Uwag", które wiążą wiersz MD z konkretnym zamówieniem.

    Polkomtel zachowuje dotychczasową, szerszą regułę: przy jego kandydacie
    każdy ciąg cyfr jest dowodem (numer SAP). U pozostałych klientów wiąże
    numer ZNANY jako numer zamówienia klienta tej osoby, a u klienta z numerami
    z samych cyfr także dostatecznie długi
    (``finance_order_matching.explicit_order_hints``).
    """
    if not hints:
        return []
    has_polkomtel_candidate = any(
        match.group.client_id == finance_order_matching.POLKOMTEL_CLIENT_ID
        for match in named
    )
    if has_polkomtel_candidate:
        return list(hints)
    return finance_order_matching.explicit_order_hints(
        hints, order_numbers, {match.group.client_id for match in named}
    )


def _match_per_consultant_md_row(
    *,
    parsed_row,
    candidates: list[LineMatch],
    order_numbers: Optional[finance_order_matching.OrderNumberIndex] = None,
    numbered_candidates: Optional[list[LineMatch]] = None,
):
    """Dopasuj wiersz MD per konsultant: nazwisko, a numer zamówienia wiąże.

    Wiersz z jawnym numerem zamówienia (ticket 23.09.2026, BIK: dwa wiersze
    tej samej osoby, stare i nowe zamówienie w jednym miesiącu) trafia
    WYŁĄCZNIE na linię tej osoby w zamówieniu o tym numerze. Brak takiej linii
    = pusta lista — wiersz idzie do weryfikacji, nigdy na inne zamówienie tej
    osoby. Numer wskazujący kilka różnych zamówień naraz (dwa numery w jednej
    komórce) zostaje niejednoznaczny — system nie wybiera za człowieka.

    Wiersz bez jawnego numeru zachowuje dopasowanie po samym nazwisku
    (BNP i inni klienci, których arkusz nie niesie numeru).

    ``numbered_candidates`` (ticket 1.1, 24.09.2026): linie klientów, których
    data zamówienia jest datą wystawienia (BIK). Służą WYŁĄCZNIE wierszom
    z numerem — zamówienie 4500030845 wystawione 3.09 rozlicza MD za sierpień,
    choć okres linii sierpnia nie obejmuje. Bez tego wiersz z tym numerem
    trafiał na inne zamówienie tej osoby (do #1745) albo do weryfikacji.
    """

    named = match_by_name(candidates, parsed_row.consultant_name)
    named_extra = (
        match_by_name(numbered_candidates, parsed_row.consultant_name)
        if numbered_candidates
        else []
    )
    if not named and not named_extra:
        return []
    hints = extract_order_number_candidates(parsed_row.notes_raw)
    in_period_ids = {match.order.id for match in named}
    pool = named + [m for m in named_extra if m.order.id not in in_period_ids]
    authoritative = _authoritative_md_hints(
        hints, named=pool, order_numbers=order_numbers
    )
    # Preferencja linii aktywnej dopiero PO zawężeniu numerem — wpięta
    # wcześniej wycinałaby linię, którą numer właśnie miał wskazać.
    if not authoritative:
        return prefer_active_line(named)
    numbered = [
        match
        for match in pool
        if finance_order_matching.finance_order_number_matches(
            client_id=match.group.client_id,
            order_number=match.group.order_number,
            numeric_hints=authoritative,
        )
    ]
    distinct_orders = {
        (match.group.client_id, str(match.group.order_number).strip())
        for match in numbered
    }
    if len(distinct_orders) > 1:
        return numbered
    return prefer_active_line(numbered)


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
    numbered = prefer_active_line(
        [
            match
            for match in named
            if finance_order_matching.finance_order_number_matches(
                client_id=match.group.client_id,
                order_number=match.group.order_number,
                numeric_hints=hints,
            )
        ]
    )
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
    if hints and amount is not None and quantize_money(amount) <= Decimal("0"):
        # FIN-MD-06: korekta faktury (kwota ≤ 0) nie znika po cichu — operator
        # dostaje status do ręcznego rozliczenia.
        row.cost_status = COST_ROW_NON_POSITIVE
        return None
    if not hints or amount is None:
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

    named = prefer_active_line(match_by_name(numbered, parsed_row.consultant_name))
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

    is_cost = plan.kind == _REPROCESS_COST
    message, current_value, write_required = await _newer_or_manual_conflict(
        db,
        model=ClientOrderInvoiceConsumption if is_cost else ClientOrderMdConsumption,
        order_id=plan.match.order.id,
        order_number=plan.match.group.order_number,
        batch=batch,
        expected_value=plan.expected_value,
        is_cost=is_cost,
        lock=lock,
    )
    if current_value is not None:
        plan.current_value = current_value
    if not write_required:
        plan.write_required = False
    return message


async def _newer_or_manual_conflict(
    db: AsyncSession,
    *,
    model,
    order_id: int,
    order_number: str,
    batch: MdConsumptionImport,
    expected_value: Decimal,
    is_cost: bool,
    lock: bool,
) -> tuple[Optional[str], Optional[Decimal], bool]:
    """Czy wpis za ten miesiąc na linii jest ręczny albo z NOWSZEJ partii.

    Zwraca ``(komunikat konfliktu | None, bieżąca wartość | None,
    czy zapis jest potrzebny)``. Wspólne dla replayu Polkomtela i ręcznego
    przypisania wiersza (audyt 22.09 r2, FIN-MD-07): ``assign_row`` ze starszej
    paczki nadpisywał nowszy albo ręczny wpis za ten sam miesiąc.
    """
    value_column = model.invoice_amount if is_cost else model.md_reported
    current_query = select(model).where(
        model.order_id == order_id,
        model.period_month == batch.period_month,
    )
    if lock:
        current_query = current_query.with_for_update()
    current = await db.scalar(current_query.execution_options(populate_existing=True))
    if current is None:
        return None, None, True
    raw = getattr(current, value_column.key)
    current_value = quantize_money(raw) if is_cost else quantize_md(raw)
    if current.source == CONSUMPTION_SOURCE_MANUAL:
        return (
            f"Zamówienie {order_number}: istnieje ręczne rozliczenie za ten miesiąc.",
            current_value,
            True,
        )
    if current_value == expected_value:
        return None, current_value, False
    if current.import_id == batch.id:
        return None, current_value, True
    if current.import_id is None:
        return (
            f"Zamówienie {order_number}: istnieje inne "
            "rozliczenie bez możliwej do potwierdzenia partii źródłowej.",
            current_value,
            True,
        )
    other_batch = await db.get(MdConsumptionImport, current.import_id)
    if other_batch is None or other_batch.created_at >= batch.created_at:
        return (
            f"Zamówienie {order_number}: istnieje rozliczenie "
            "z nowszego importu; starsza partia nie może go nadpisać.",
            current_value,
            True,
        )
    return None, current_value, True


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


async def _shared_md_carry_over(
    db: AsyncSession,
    *,
    group_id: int,
    period_month: str,
    import_id: int,
    present_order_ids: set[int],
) -> tuple[Decimal, list[str]]:
    """Wkład osób z WCZEŚNIEJSZYCH importów tego miesiąca, których nie ma w pliku.

    Audyt 24.09.2026 (S5). Wspólna pula trzyma jedną sumę za miesiąc, a plik
    korygujący przychodzi zwykle z samymi poprawionymi osobami — dotąd jego
    suma nadpisywała cały miesiąc. Wkład osoby to jej wiersze z NAJNOWSZEJ
    wcześniejszej paczki, w której była (linia = osoba); osoba obecna w nowym
    pliku jest liczona wyłącznie z niego.

    Nic nie przenosimy, gdy miesiąc puli zapisał ostatnio człowiek (``source
    = manual``) — ręczna suma nie ma podziału na osoby, a nadpisanie jej
    importem to dotychczasowa, opisana w instrukcji reguła.
    """
    source = await db.scalar(
        select(ClientOrderGroupMdConsumption.source).where(
            ClientOrderGroupMdConsumption.group_id == group_id,
            ClientOrderGroupMdConsumption.period_month == period_month,
        )
    )
    if source != "import":
        return Decimal("0"), []
    rows = (
        await db.execute(
            select(
                MdConsumptionImportRow.import_id,
                MdConsumptionImportRow.matched_order_id,
                MdConsumptionImportRow.md_reported,
                MdConsumptionImportRow.consultant_name,
            )
            .join(
                MdConsumptionImport,
                MdConsumptionImport.id == MdConsumptionImportRow.import_id,
            )
            .where(
                MdConsumptionImportRow.matched_group_id == group_id,
                MdConsumptionImportRow.matched_order_id.is_not(None),
                MdConsumptionImportRow.status == IMPORT_ROW_APPLIED,
                MdConsumptionImport.period_month == period_month,
                MdConsumptionImportRow.import_id != import_id,
            )
        )
    ).all()
    latest: dict[int, int] = {}
    sums: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0"))
    names: dict[int, str] = {}
    for batch_id, order_id, md, name in rows:
        if order_id in present_order_ids:
            continue
        latest[order_id] = max(latest.get(order_id, batch_id), batch_id)
        sums[(order_id, batch_id)] += Decimal(str(md))
        names[order_id] = name
    carried = quantize_md(
        sum(
            (sums[(order_id, batch_id)] for order_id, batch_id in latest.items()),
            Decimal("0"),
        )
    )
    return carried, sorted({names[order_id] for order_id in latest})


async def _settle_shared_md_and_record(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    period_month: str,
    md_reported: Decimal,
    import_id: int,
    user_id: int,
    carried_md: Decimal = Decimal("0"),
    carried_names: Optional[list[str]] = None,
    before_used: Optional[Decimal] = None,
    overflow_approved: bool = False,
) -> Decimal:
    """Nadpisz miesiąc wspólnej puli, przelicz ją i zapisz historię.

    Zwraca, o ile MD ten zapis zepchnął pulę ponad dostępny budżet
    (``before_used`` = wykorzystanie przed zapisem; ticket 1.1) — import cofa
    wtedy zapis i zostawia wiersze do zatwierdzenia.
    """
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
    new_overflow = Decimal("0")
    if over_budget > Decimal("0") and (before_used is None or used > before_used):
        floor = available if before_used is None else max(available, before_used)
        new_overflow = quantize_md(used - floor)
    warning = (
        f" Raport przekracza dostępny budżet o {format_md(over_budget)} MD."
        if over_budget > Decimal("0")
        else ""
    )
    if overflow_approved and over_budget > Decimal("0"):
        warning += " Przekroczenie puli zatwierdzone ręcznie."
    if carried_md > Decimal("0"):
        # S5: plik nie zawierał tych osób — ich MD z wcześniejszego importu
        # tego miesiąca zostają w sumie, a historia mówi to wprost.
        warning += (
            f" W sumie zostało {format_md(carried_md)} MD z wcześniejszego "
            "importu tego miesiąca dla osób nieobecnych w tym pliku: "
            + ", ".join(carried_names or [])
            + "."
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
            "md_carried_over": str(quantize_md(carried_md)),
            **({"overflow_approved": True} if overflow_approved else {}),
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
        # Zdarzenie w historii widzi tylko ten, kto otworzy kartę zamówienia.
        # Bez tej emisji wyczerpanie wspólnej puli nie docierało do NIKOGO:
        # próg „mało MD" liczy budżet PRZYPISANY OSOBIE, więc dla Lotte Wedel
        # i Cyfrowego Polsatu ten alert jest jedynym sygnałem o końcu budżetu.
        await emit_shared_md_pool_exhausted(db, group)
    return new_overflow


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
    stored = list(result.scalars())
    context = (
        await _reason_context(db)
        if any(r.status == IMPORT_ROW_UNMATCHED and r.notes_raw for r in stored)
        else None
    )
    per_target: dict[int, int] = defaultdict(int)
    for r in stored:
        if r.matched_order_id is not None and r.status in (
            IMPORT_ROW_APPLIED,
            IMPORT_ROW_OVERFLOW,
        ):
            per_target[r.matched_order_id] += 1
    rows = [
        await _row_to_read(
            db,
            r,
            batch.period_month,
            context,
            merged_rows=(
                per_target.get(r.matched_order_id, 1)
                if r.matched_order_id is not None
                and r.status in (IMPORT_ROW_APPLIED, IMPORT_ROW_OVERFLOW)
                else 1
            ),
        )
        for r in stored
    ]
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
    if row.status not in (IMPORT_ROW_NEEDS_ASSIGNMENT, IMPORT_ROW_OVERFLOW):
        raise HTTPException(
            409,
            detail="Ten wiersz nie czeka na przypisanie — został już rozstrzygnięty.",
        )

    allowed = {int(o) for o in (row.candidate_order_ids or [])}
    if payload.order_id not in allowed:
        # Wybór spoza listy kandydatów oznacza, że linia nie pasowała do
        # nazwiska ALBO nie obsadzała zamówienia w tym miesiącu. Przyjęcie go
        # tutaj obeszłoby oba filtry naraz.
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

    if order.order_group is not None and uses_shared_md_pool(order.order_group):
        return await _approve_shared_md_overflow(
            db, batch=batch, row=row, order=order, user=user, payload=payload
        )

    # Numer zamówienia wskazany w wierszu wiąże także ręczne rozstrzygnięcie
    # (ticket 23.09.2026): wiersz „4500029903" nie może trafić na 4500030067.
    group_number = order.order_group.order_number if order.order_group else None
    authoritative = _authoritative_md_hints(
        extract_order_number_candidates(row.notes_raw),
        named=[LineMatch(order, order.order_group, row.consultant_name)]
        if order.order_group is not None
        else [],
        order_numbers=await _order_number_index(db),
    )
    if authoritative and not finance_order_matching.finance_order_number_matches(
        client_id=order.client_id,
        order_number=group_number,
        numeric_hints=authoritative,
    ):
        raise HTTPException(
            422,
            detail=(
                f"Wiersz wskazuje zamówienie nr {authoritative[0]} — nie można "
                f"przypisać go do zamówienia nr {group_number or '—'}."
            ),
        )
    # BIK (ticket 1.1): wiersz z numerem rozlicza zamówienie o tym numerze
    # niezależnie od jego daty — data zamówienia to data wystawienia.
    ignore_period = bool(authoritative) and order.client_id in (
        md_exhaustion_client_ids()
    )

    # Lista kandydatów powstała przy wgraniu pliku, a rozstrzygnięcie następuje
    # później — w międzyczasie linia mogła zostać anulowana albo skrócona poza
    # importowany miesiąc. Zakończenie współpracy przeszkodą NIE jest: to
    # właśnie po nim przychodzi zaległy raport za miesiąc, w którym konsultant
    # jeszcze pracował, i człowiek musi mieć jak go przypisać bez odblokowywania
    # statusu linii.
    if not line_settles_in_month(
        order,
        batch.period_month,
        contract=order.contract,
        ignore_period=ignore_period,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Ta linia nie rozlicza tego miesiąca — została anulowana albo "
                "jej okres go nie obejmuje. Wybierz inne zamówienie."
            ),
        )

    # Zapis idzie po kluczu (linia, miesiąc) i NADPISUJE, więc rozstrzygnięcie
    # nie może wysłać samego ``row.md_reported``: gdyby na tę samą linię trafił
    # już inny wiersz tego importu (automatycznie albo wcześniejszym
    # przypisaniem), jego MD zostałyby skasowane. Wysyłamy sumę wszystkich
    # zastosowanych wierszy tej paczki dla tej linii — to daje ten sam wynik co
    # ścieżka wsadowa i jest odporne na kolejność rozstrzygania. Wiersze tej
    # linii wstrzymane przez przekroczenie puli idą razem z tym (były
    # zsumowane w jedno zejście).
    already_applied = await db.scalar(
        select(func.coalesce(func.sum(MdConsumptionImportRow.md_reported), 0)).where(
            MdConsumptionImportRow.import_id == batch.id,
            MdConsumptionImportRow.matched_order_id == order.id,
            MdConsumptionImportRow.status == IMPORT_ROW_APPLIED,
            MdConsumptionImportRow.id != row.id,
        )
    )
    held_rows = list(
        (
            await db.execute(
                select(MdConsumptionImportRow)
                .where(
                    MdConsumptionImportRow.import_id == batch.id,
                    MdConsumptionImportRow.matched_order_id == order.id,
                    MdConsumptionImportRow.status == IMPORT_ROW_OVERFLOW,
                    MdConsumptionImportRow.id != row.id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    md_total = (
        Decimal(str(already_applied or 0))
        + row.md_reported
        + sum((held.md_reported for held in held_rows), Decimal("0"))
    )
    # Audyt 22.09 r2 (FIN-MD-07): starsza paczka nie nadpisuje nowszego ani
    # ręcznego wpisu za ten miesiąc (ta sama reguła co replay Polkomtela).
    conflict, _current, _write = await _newer_or_manual_conflict(
        db,
        model=ClientOrderMdConsumption,
        order_id=order.id,
        order_number=(
            order.order_group.order_number if order.order_group else str(order.id)
        ),
        batch=batch,
        expected_value=quantize_md(md_total),
        is_cost=False,
        lock=True,
    )
    if conflict is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=conflict)

    # Ticket 1.1: najpierw próbny zapis — zejście, po którym saldo spadłoby
    # poniżej zera, wymaga świadomego zatwierdzenia (``confirm_overflow``).
    await lock_contract_then_orders(db, order_ids=[order.id])
    before_remaining = {
        order.id: await db.scalar(
            select(ClientOrder.md_remaining).where(ClientOrder.id == order.id)
        )
    }
    await db.flush()
    savepoint = await db.begin_nested()
    outcome = await _apply_to_line(
        db,
        match_order=order,
        group=order.order_group,
        period_month=batch.period_month,
        md_reported=md_total,
        import_id=batch.id,
        user_id=user.id,
        explicit_order=bool(authoritative),
        ignore_period=ignore_period,
    )
    successor = getattr(outcome, "successor_order", None)
    if successor is not None:
        before_remaining.setdefault(successor.id, None)
    overflow = _booking_overflow(outcome, before_remaining)
    now = datetime.now(timezone.utc)
    if overflow > Decimal("0"):
        await _rollback_trial(db, savepoint)
        if not payload.confirm_overflow:
            for held in [row, *held_rows]:
                held.status = IMPORT_ROW_OVERFLOW
                held.overflow_md = overflow
                held.matched_order_id = order.id
                held.candidate_order_ids = [order.id]
            await db.flush()
            await _recount(db, batch)
            await db.commit()
            await db.refresh(row)
            return await _row_to_read(db, row, batch.period_month)
        await _apply_to_line(
            db,
            match_order=order,
            group=order.order_group,
            period_month=batch.period_month,
            md_reported=md_total,
            import_id=batch.id,
            user_id=user.id,
            explicit_order=bool(authoritative),
            ignore_period=ignore_period,
            overflow_approved=overflow,
        )
    else:
        await savepoint.commit()
    for booked in [row, *held_rows]:
        booked.status = IMPORT_ROW_APPLIED
        booked.matched_order_id = order.id
        booked.resolved_by_user_id = user.id
        booked.resolved_at = now

    await db.flush()
    await _recount(db, batch)
    await db.commit()
    await db.refresh(row)
    return await _row_to_read(db, row, batch.period_month)


async def _approve_shared_md_overflow(
    db: AsyncSession,
    *,
    batch: MdConsumptionImport,
    row: MdConsumptionImportRow,
    order: ClientOrder,
    user,
    payload: AssignRowRequest,
) -> ImportRowRead:
    """Zatwierdzenie miesiąca wspólnej puli wstrzymanego przez przekroczenie.

    Suma miesiąca puli jest jedna, więc zatwierdza się ją całą: wszystkie
    wstrzymane wiersze tej grupy w tej paczce + wiersze już zastosowane
    + wkład osób z wcześniejszych importów tego miesiąca (S5).
    """
    if row.status != IMPORT_ROW_OVERFLOW or not payload.confirm_overflow:
        raise HTTPException(
            409,
            detail=(
                "Wiersz wspólnej puli MD rozlicza się razem z całym miesiącem "
                "zamówienia — zatwierdź przekroczenie puli."
            ),
        )
    group = order.order_group
    group_rows = list(
        (
            await db.execute(
                select(MdConsumptionImportRow)
                .where(
                    MdConsumptionImportRow.import_id == batch.id,
                    MdConsumptionImportRow.matched_group_id == group.id,
                    MdConsumptionImportRow.status.in_(
                        (IMPORT_ROW_APPLIED, IMPORT_ROW_OVERFLOW)
                    ),
                )
                .with_for_update()
            )
        ).scalars()
    )
    present = {r.matched_order_id for r in group_rows if r.matched_order_id}
    carried, carried_names = await _shared_md_carry_over(
        db,
        group_id=group.id,
        period_month=batch.period_month,
        import_id=batch.id,
        present_order_ids=present,
    )
    await _settle_shared_md_and_record(
        db,
        group=group,
        period_month=batch.period_month,
        md_reported=sum((r.md_reported for r in group_rows), Decimal("0")) + carried,
        import_id=batch.id,
        user_id=user.id,
        carried_md=carried,
        carried_names=carried_names,
        overflow_approved=True,
    )
    now = datetime.now(timezone.utc)
    for booked in group_rows:
        if booked.status == IMPORT_ROW_OVERFLOW:
            booked.status = IMPORT_ROW_APPLIED
            booked.resolved_by_user_id = user.id
            booked.resolved_at = now
    await db.flush()
    await _recount(db, batch)
    await db.commit()
    await db.refresh(row)
    return await _row_to_read(db, row, batch.period_month)


# ── Cofnięcie zakończenia kontraktu (0368) ──────────────────────────────────


@dataclass(frozen=True)
class RestoredLineImportRow:
    """Wiersz importu, który trafi (albo trafił) na przywróconą linię."""

    import_id: int
    row_id: int
    period_month: str
    filename: Optional[str]
    md_reported: Decimal
    order_id: int
    skipped: Optional[str] = None


def _period_within(
    start: Optional[date_type], end: Optional[date_type], period_month: str
) -> bool:
    first, last = month_bounds(period_month)
    if start is not None and start > last:
        return False
    return end is None or end >= first


async def reapply_rows_for_restored_line(
    db: AsyncSession,
    *,
    line: ClientOrder,
    since: datetime,
    ended_on: Optional[date_type],
    target_end_date: Optional[date_type],
    user_id: Optional[int],
    dry_run: bool,
) -> list[RestoredLineImportRow]:
    """Importy MD wgrane, gdy linia była zakończona — przelicz je dla osoby.

    Zakończona linia przyjmuje raport za miesiąc, w którym osoba jeszcze
    pracowała (``line_settles_in_month`` pyta o okres), więc bez dopasowania
    zostały wyłącznie wiersze za miesiące PO dacie zakończenia. Po cofnięciu
    zakończenia linia znowu obsadza te miesiące — wiersz ``unmatched`` z tym
    samym nazwiskiem idzie tą samą ścieżką co ręczne przypisanie (``assign_row``):
    suma wierszy partii dla linii, ochrona nowszego i ręcznego wpisu,
    ``_apply_to_line`` z wpisem w historii zamówienia.

    Wyłącznie linie z budżetem MD per osoba. Wspólna pula i zamówienie
    kosztowe dopasowują wiersz po numerze zamówienia, nie po osobie, więc tu
    nie ma czego zgadywać — takie wiersze rozstrzyga Finanse w imporcie.

    ``dry_run`` liczy podgląd do okna potwierdzenia: linia ma jeszcze stan po
    zakończeniu, więc okres ocenia się z ``target_end_date``.
    """

    group = line.order_group
    contract = line.contract
    if group is None or contract is None:
        return []
    if group.is_cost_based or uses_shared_md_pool(group):
        return []
    wanted = candidate_name_tokens(contract.candidate)
    if not wanted:
        return []

    candidates = (
        await db.execute(
            select(MdConsumptionImportRow, MdConsumptionImport)
            .join(
                MdConsumptionImport,
                MdConsumptionImport.id == MdConsumptionImportRow.import_id,
            )
            .where(
                MdConsumptionImportRow.status == IMPORT_ROW_UNMATCHED,
                MdConsumptionImport.created_at >= since,
            )
            .order_by(MdConsumptionImport.created_at.asc(), MdConsumptionImportRow.id)
        )
    ).all()

    results: list[RestoredLineImportRow] = []
    order_numbers: Optional[finance_order_matching.OrderNumberIndex] = None
    for row, batch in candidates:
        if name_tokens(row.consultant_name) != wanted:
            continue
        # Numer zamówienia z „Uwag" wiąże wiersz (ticket 23.09.2026, ta sama
        # reguła co ręczne przypisanie): wiersz wskazujący INNE zamówienie nie
        # trafia na przywróconą linię.
        hints = extract_order_number_candidates(row.notes_raw)
        if hints:
            if order_numbers is None:
                order_numbers = await _order_number_index(db)
            authoritative = _authoritative_md_hints(
                hints,
                named=[LineMatch(line, group, row.consultant_name)],
                order_numbers=order_numbers,
            )
            if (
                authoritative
                and not finance_order_matching.finance_order_number_matches(
                    client_id=line.client_id,
                    order_number=group.order_number,
                    numeric_hints=authoritative,
                )
            ):
                continue
        first, _last = month_bounds(batch.period_month)
        if ended_on is not None and ended_on >= first:
            # Ten miesiąc zakończona linia i tak rozliczała — wiersz bez
            # dopasowania ma inny powód niż zakończenie.
            continue
        if not _period_within(line.start_date, target_end_date, batch.period_month):
            continue
        item = RestoredLineImportRow(
            import_id=batch.id,
            row_id=row.id,
            period_month=batch.period_month,
            filename=batch.filename,
            md_reported=Decimal(str(row.md_reported)),
            order_id=line.id,
        )
        if dry_run:
            results.append(item)
            continue

        locked_batch = await db.scalar(
            select(MdConsumptionImport)
            .where(MdConsumptionImport.id == batch.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        locked_row = await db.scalar(
            select(MdConsumptionImportRow)
            .where(MdConsumptionImportRow.id == row.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            locked_batch is None
            or locked_row is None
            or locked_row.status != IMPORT_ROW_UNMATCHED
        ):
            continue
        if not line_settles_in_month(
            line, locked_batch.period_month, contract=contract
        ):
            results.append(
                RestoredLineImportRow(**{**item.__dict__, "skipped": "period"})
            )
            continue
        already_applied = await db.scalar(
            select(
                func.coalesce(func.sum(MdConsumptionImportRow.md_reported), 0)
            ).where(
                MdConsumptionImportRow.import_id == locked_batch.id,
                MdConsumptionImportRow.matched_order_id == line.id,
                MdConsumptionImportRow.status == IMPORT_ROW_APPLIED,
            )
        )
        total = quantize_md(Decimal(str(already_applied or 0)) + locked_row.md_reported)
        conflict, _current, _write = await _newer_or_manual_conflict(
            db,
            model=ClientOrderMdConsumption,
            order_id=line.id,
            order_number=group.order_number,
            batch=locked_batch,
            expected_value=total,
            is_cost=False,
            lock=True,
        )
        if conflict is not None:
            results.append(
                RestoredLineImportRow(**{**item.__dict__, "skipped": conflict})
            )
            continue
        await _apply_to_line(
            db,
            match_order=line,
            group=group,
            period_month=locked_batch.period_month,
            md_reported=total,
            import_id=locked_batch.id,
            user_id=user_id,
        )
        locked_row.status = IMPORT_ROW_APPLIED
        locked_row.matched_order_id = line.id
        locked_row.resolved_by_user_id = user_id
        locked_row.resolved_at = datetime.now(timezone.utc)
        await db.flush()
        await _recount(db, locked_batch)
        results.append(item)
    return results
