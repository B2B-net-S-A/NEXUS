"""MD czekające na kolejne zamówienie (import MD, 21.10.2026).

Arkusz Finansów bywa dzielony na dwa wiersze tej samej osoby: jeden z numerem
zamówienia, drugi bez (kolejne zamówienie jeszcze nie wpłynęło). Do 21.10
import sumował oba na zamówienie z numerem i oznaczał całość jako
przekroczenie puli. Teraz wiersz bez numeru dostaje status
``awaiting_order``: nie schodzi z żadnej puli, a jego MD (``md_pending``)
czekają przy zamówieniu z numerem („Pozostało do zafakturowania za …”).

Gdy w NEXUSIE pojawi się kolejne zamówienie tej osoby u tego samego klienta,
:func:`settle_awaiting_md_for_client` zdejmuje z niego oczekujące MD jako
zużycie za miesiąc, którego dotyczą — tyle, ile mieści pula, reszta czeka
dalej. Wołają ją: import MD, nowe zamówienie, przedłużenie, dodanie osoby
do zamówienia i aktywacja szkicu z poczty.

„Kolejne zamówienie” = linia tej samej osoby (kandydat kontraktu) u tego
samego klienta na zamówieniu MD per osoba założonym PO zamówieniu z numerem
(wyższe id grupy) i nie wcześniejszym (data startu), aktywnym albo
zaplanowanym. Kilka takich → od najwcześniejszego, kolejne biorą resztę.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_SCHEDULED,
    ClientOrderGroup,
    ClientOrderGroupEvent,
)
from app.models.contract import Contract
from app.models.md_consumption import (
    COST_ROW_APPLIED,
    ClientOrderMdConsumption,
    IMPORT_ROW_APPLIED,
    IMPORT_ROW_AWAITING_ORDER,
    IMPORT_ROW_NEEDS_ASSIGNMENT,
    IMPORT_ROW_OVERFLOW,
    IMPORT_ROW_SUPERSEDED,
    IMPORT_ROW_UNMATCHED,
    MdConsumptionImport,
    MdConsumptionImportRow,
)
from app.services.client_order_lines import (
    format_period_month,
    name_tokens,
    recompute_remaining,
    record_event,
    upsert_consumption,
)
from app.services.contract_lifecycle import lock_contract_then_orders
from app.services.multi_consultant_orders import (
    EVENT_MD_IMPORT,
    format_md,
    quantize_md,
)
from app.services.shared_md_orders import uses_shared_md_pool

ZERO = Decimal("0")


@dataclass(frozen=True)
class AwaitingSettlement:
    """Jedno zejście oczekujących MD na kolejne zamówienie."""

    row_id: int
    order_id: int
    group_id: int
    period_month: str
    md: Decimal


async def recount_import_batch(db: AsyncSession, batch: MdConsumptionImport) -> None:
    """Przelicz liczniki partii z faktycznych statusów wierszy.

    Liczniki są przeliczane, a nie inkrementowane przy rozstrzyganiu: licznik
    modyfikowany krokowo rozjeżdża się przy każdym nieoczekiwanym przebiegu,
    a to on jest tym, co operator czyta jako „ile zostało do zrobienia".
    „Oczekuje na zamówienie” nie wymaga człowieka — liczy się tylko do sumy.
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


def _origin_options():
    return (
        selectinload(MdConsumptionImportRow.import_batch),
        selectinload(MdConsumptionImportRow.awaiting_origin_order).selectinload(
            ClientOrder.contract
        ),
        selectinload(MdConsumptionImportRow.awaiting_origin_order).selectinload(
            ClientOrder.order_group
        ),
    )


async def next_order_lines(db: AsyncSession, origin: ClientOrder) -> list[ClientOrder]:
    """Linie kolejnych zamówień tej osoby u tego klienta — od najwcześniejszej."""
    group = origin.order_group
    contract = origin.contract
    if group is None or contract is None or contract.candidate_id is None:
        return []
    lines = (
        await db.execute(
            select(ClientOrder)
            .join(Contract, ClientOrder.contract_id == Contract.id)
            .join(ClientOrderGroup, ClientOrder.order_group_id == ClientOrderGroup.id)
            .options(
                selectinload(ClientOrder.order_group),
                selectinload(ClientOrder.contract),
            )
            .where(
                ClientOrder.client_id == origin.client_id,
                ClientOrder.id != origin.id,
                Contract.candidate_id == contract.candidate_id,
                ClientOrderGroup.id > group.id,
                ClientOrderGroup.start_date >= group.start_date,
                ClientOrderGroup.status.in_(
                    (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED)
                ),
                ClientOrderGroup.is_cost_based.is_(False),
                ClientOrder.status.notin_(
                    (ClientOrderStatus.cancelled, ClientOrderStatus.completed)
                ),
                ClientOrder.md_total.isnot(None),
            )
            .order_by(
                ClientOrderGroup.start_date.asc(),
                ClientOrderGroup.id.asc(),
                ClientOrder.id.asc(),
            )
        )
    ).scalars()
    return [line for line in lines if not uses_shared_md_pool(line.order_group)]


async def next_order_line_ids(
    db: AsyncSession, origins: Iterable[ClientOrder]
) -> set[int]:
    """Linie, które może dotknąć rozliczenie — import blokuje je z góry."""
    ids: set[int] = set()
    for origin in origins:
        ids |= {line.id for line in await next_order_lines(db, origin)}
    return ids


async def _month_md(db: AsyncSession, order_id: int, period_month: str) -> Decimal:
    value = await db.scalar(
        select(ClientOrderMdConsumption.md_reported).where(
            ClientOrderMdConsumption.order_id == order_id,
            ClientOrderMdConsumption.period_month == period_month,
        )
    )
    return Decimal(str(value)) if value is not None else ZERO


async def settle_awaiting_rows(
    db: AsyncSession,
    rows: Iterable[MdConsumptionImportRow],
    *,
    user_id: Optional[int],
) -> list[AwaitingSettlement]:
    """Zdejmij oczekujące MD wierszy z kolejnych zamówień, ile mieszczą pule.

    Wiersze muszą mieć załadowane ``import_batch`` i ``awaiting_origin_order``
    (z kontraktem i grupą). Zejście DOKŁADA się do wpisu linii za ten miesiąc
    (klucz idempotencji to linia + miesiąc), więc nie nadpisuje innego
    rozliczenia tego miesiąca na nowym zamówieniu.
    """
    ordered = sorted(
        rows, key=lambda r: (r.import_batch.period_month, r.import_id, r.row_number)
    )
    settlements: list[AwaitingSettlement] = []
    touched: dict[int, MdConsumptionImport] = {}
    for row in ordered:
        origin = row.awaiting_origin_order
        pending = quantize_md(row.md_pending or ZERO)
        if row.status != IMPORT_ROW_AWAITING_ORDER or origin is None or pending <= 0:
            continue
        period = row.import_batch.period_month
        origin_number = (
            origin.order_group.order_number if origin.order_group is not None else "—"
        )
        for candidate in await next_order_lines(db, origin):
            await lock_contract_then_orders(db, order_ids=[candidate.id])
            await db.flush()
            target = await db.scalar(
                select(ClientOrder)
                .options(
                    selectinload(ClientOrder.order_group),
                    selectinload(ClientOrder.contract),
                )
                .where(ClientOrder.id == candidate.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if target.md_remaining is None:
                await recompute_remaining(db, target)
            remaining = Decimal(str(target.md_remaining or ZERO))
            if remaining <= 0:
                continue
            take = quantize_md(min(pending, remaining))
            month_before = await _month_md(db, target.id, period)
            _, _, left = await upsert_consumption(
                db,
                order=target,
                period_month=period,
                md_reported=month_before + take,
                import_id=row.import_id,
                user_id=user_id,
            )
            pending = quantize_md(pending - take)
            record_event(
                db,
                group_id=target.order_group_id,
                order_id=target.id,
                event_type=EVENT_MD_IMPORT,
                description=(
                    f"Zdjęto {format_md(take)} MD za {format_period_month(period)} "
                    f"— {row.consultant_name}, oczekiwały na kolejne zamówienie "
                    f"po zamówieniu nr {origin_number}. Pozostało "
                    f"{format_md(left)} MD."
                ),
                payload={
                    "period_month": period,
                    "md_reported": str(row.md_reported),
                    "md_applied": str(take),
                    "md_previous": str(month_before),
                    "md_remaining": str(left),
                    "import_id": row.import_id,
                    "awaiting_row_id": row.id,
                    "awaiting_origin_order_id": origin.id,
                    "md_still_awaiting": str(pending),
                },
                user_id=user_id,
            )
            row.matched_order_id = target.id
            row.matched_group_id = target.order_group_id
            settlements.append(
                AwaitingSettlement(
                    row_id=row.id,
                    order_id=target.id,
                    group_id=target.order_group_id,
                    period_month=period,
                    md=take,
                )
            )
            if pending <= 0:
                break
        if pending != quantize_md(row.md_pending or ZERO):
            row.md_pending = pending
            if pending <= 0:
                row.status = IMPORT_ROW_APPLIED
                row.resolved_at = datetime.now(timezone.utc)
                row.resolved_by_user_id = user_id
            touched[row.import_id] = row.import_batch
    if touched:
        await db.flush()
        for batch_id in sorted(touched):
            await recount_import_batch(db, touched[batch_id])
    return settlements


async def settle_awaiting_md_for_client(
    db: AsyncSession, *, client_id: int, user_id: Optional[int]
) -> list[AwaitingSettlement]:
    """Nowe zamówienie u klienta — zdejmij z niego MD, które na nie czekały.

    Kolejność blokad jak w imporcie: kontrakty i linie kolejnych zamówień,
    dopiero potem wiersze importu (import trzyma linie, gdy sięga po wiersze
    starszej paczki).
    """
    await db.flush()
    query = (
        select(MdConsumptionImportRow)
        .join(
            ClientOrder,
            MdConsumptionImportRow.awaiting_origin_order_id == ClientOrder.id,
        )
        .options(*_origin_options())
        .where(
            MdConsumptionImportRow.status == IMPORT_ROW_AWAITING_ORDER,
            MdConsumptionImportRow.md_pending > 0,
            ClientOrder.client_id == client_id,
        )
    )
    rows = list((await db.execute(query)).scalars())
    if not rows:
        return []
    targets = await next_order_line_ids(
        db, {row.awaiting_origin_order for row in rows if row.awaiting_origin_order}
    )
    if not targets:
        return []
    await lock_contract_then_orders(db, order_ids=sorted(targets))
    rows = list(
        (
            await db.execute(
                query.with_for_update(of=MdConsumptionImportRow).execution_options(
                    populate_existing=True
                )
            )
        ).scalars()
    )
    return await settle_awaiting_rows(db, rows, user_id=user_id)


PersonKey = tuple[frozenset[str], int]
"""(tokeny imienia i nazwiska, klient zamówienia z numerem)."""


@dataclass
class ReimportPlan:
    """Wcześniejsze wiersze oczekujące za ten miesiąc osób z nowej paczki."""

    earlier: dict[PersonKey, list[MdConsumptionImportRow]]
    targets: set[int]


async def _earlier_awaiting_rows(
    db: AsyncSession,
    *,
    import_id: int,
    period_month: str,
    persons: set[PersonKey],
    lock: bool = False,
) -> dict[PersonKey, list[MdConsumptionImportRow]]:
    if not persons:
        return {}
    query = (
        select(MdConsumptionImportRow, ClientOrder.client_id)
        .join(
            MdConsumptionImport,
            MdConsumptionImportRow.import_id == MdConsumptionImport.id,
        )
        .join(
            ClientOrder,
            MdConsumptionImportRow.awaiting_origin_order_id == ClientOrder.id,
        )
        .where(
            MdConsumptionImportRow.import_id != import_id,
            MdConsumptionImport.period_month == period_month,
            MdConsumptionImportRow.status.in_(
                (IMPORT_ROW_AWAITING_ORDER, IMPORT_ROW_APPLIED, IMPORT_ROW_SUPERSEDED)
            ),
        )
        .order_by(MdConsumptionImportRow.import_id, MdConsumptionImportRow.row_number)
    )
    if lock:
        query = query.with_for_update(of=MdConsumptionImportRow).execution_options(
            populate_existing=True
        )
    grouped: dict[PersonKey, list[MdConsumptionImportRow]] = defaultdict(list)
    for row, client_id in (await db.execute(query)).all():
        key = (name_tokens(row.consultant_name), client_id)
        if key in persons:
            grouped[key].append(row)
    return dict(grouped)


async def _settled_by_target(
    db: AsyncSession, row_ids: Iterable[int]
) -> dict[int, Decimal]:
    """Netto MD zdjęte z kolejnych zamówień za te wiersze — z dziennika zamówień.

    Każde zejście i każda korekta zostawia wpis z ``awaiting_row_id``, więc
    suma wpisów mówi, ile tych MD jest dziś na którym zamówieniu — niezależnie
    od tego, przez ile paczek przeszły.
    """
    ids = {str(i) for i in row_ids}
    if not ids:
        return {}
    await db.flush()
    events = await db.execute(
        select(ClientOrderGroupEvent.order_id, ClientOrderGroupEvent.payload).where(
            ClientOrderGroupEvent.event_type == EVENT_MD_IMPORT,
            ClientOrderGroupEvent.payload["awaiting_row_id"].astext.in_(ids),
        )
    )
    settled: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for order_id, payload in events.all():
        if order_id is None:
            continue
        settled[int(order_id)] += Decimal(str(payload.get("md_applied") or "0"))
    return {oid: quantize_md(md) for oid, md in settled.items() if md != 0}


async def plan_reimport(
    db: AsyncSession,
    *,
    import_id: int,
    period_month: str,
    persons: Iterable[tuple[str, int]],
) -> ReimportPlan:
    """Przed blokadami importu: kogo dotyczy powtórka miesiąca i które linie
    kolejnych zamówień może poprawić (import blokuje je z góry).

    ``persons``: pary (nazwisko z wiersza MD paczki, klient jego zamówienia).
    Klient należy do klucza (audyt 22.10.2026, F70): wiersz tej osoby u innego
    klienta albo imiennika nie rusza jej wcześniejszych wierszy oczekujących.
    """
    keys = {
        (tokens, client_id)
        for name, client_id in persons
        if (tokens := name_tokens(name))
    }
    earlier = await _earlier_awaiting_rows(
        db, import_id=import_id, period_month=period_month, persons=keys
    )
    targets: set[int] = set()
    for rows in earlier.values():
        targets |= set(await _settled_by_target(db, (r.id for r in rows)))
    return ReimportPlan(earlier=earlier, targets=targets)


async def apply_reimport(
    db: AsyncSession,
    plan: ReimportPlan,
    *,
    import_id: int,
    period_month: str,
    new_awaiting: list[tuple[MdConsumptionImportRow, int]],
    user_id: Optional[int],
) -> None:
    """Powtórka miesiąca: nowa paczka jest prawdą o MD oczekujących tej osoby.

    Woła się PO blokadach linii i PRZED zapisem zejść paczki. Dla każdej osoby
    z nowej paczki (klucz: osoba + klient zamówienia z numerem):

    * jej wcześniejsze wiersze oczekujące dostają ``superseded`` — niezależnie
      od tego, czy nowa paczka ma dla niej wiersz oczekujący (plik korygujący
      mógł przenieść te MD na wiersz z numerem),
    * to, co już zeszło z kolejnych zamówień, pokrywa nowe wiersze oczekujące
      (bez drugiego zejścia), a nadwyżka ponad nową wartość wraca z tych
      zamówień — lustro nadpisania (linia, miesiąc) przy zwykłym imporcie.

    ``new_awaiting``: nowe wiersze oczekujące z klientem ich zamówienia z numerem.
    """
    earlier = await _earlier_awaiting_rows(
        db,
        import_id=import_id,
        period_month=period_month,
        persons=set(plan.earlier),
        lock=True,
    )
    fresh: dict[PersonKey, list[MdConsumptionImportRow]] = defaultdict(list)
    for row, client_id in new_awaiting:
        fresh[(name_tokens(row.consultant_name), client_id)].append(row)

    for key, old_rows in earlier.items():
        for old in old_rows:
            if old.status == IMPORT_ROW_AWAITING_ORDER:
                old.status = IMPORT_ROW_SUPERSEDED
                old.md_pending = ZERO
        settled = await _settled_by_target(db, (r.id for r in old_rows))
        new_rows = sorted(fresh.get(key, []), key=lambda r: r.row_number)
        wanted = quantize_md(sum((Decimal(str(r.md_reported)) for r in new_rows), ZERO))
        excess = quantize_md(sum(settled.values(), ZERO) - wanted)
        anchor = new_rows[0] if new_rows else old_rows[-1]
        # Nadwyżka wraca od zamówienia, które przyjęło MD najpóźniej.
        for target_id in sorted(settled, reverse=True):
            if excess <= 0:
                break
            back = min(excess, settled[target_id])
            if back <= 0:
                continue
            await _revert_settlement(
                db,
                target_id=target_id,
                period_month=period_month,
                md=back,
                anchor=anchor,
                user_id=user_id,
            )
            settled[target_id] = quantize_md(settled[target_id] - back)
            excess = quantize_md(excess - back)
        covered_total = quantize_md(sum(settled.values(), ZERO))
        last_target = max((oid for oid, md in settled.items() if md > 0), default=None)
        for row in new_rows:
            if covered_total <= 0:
                break
            covered = min(covered_total, Decimal(str(row.md_reported)))
            covered_total = quantize_md(covered_total - covered)
            row.md_pending = quantize_md(Decimal(str(row.md_reported)) - covered)
            row.matched_order_id = last_target
            if row.md_pending <= 0:
                row.status = IMPORT_ROW_APPLIED


async def _revert_settlement(
    db: AsyncSession,
    *,
    target_id: int,
    period_month: str,
    md: Decimal,
    anchor: MdConsumptionImportRow,
    user_id: Optional[int],
) -> None:
    await lock_contract_then_orders(db, order_ids=[target_id])
    await db.flush()
    target = await db.scalar(
        select(ClientOrder)
        .where(ClientOrder.id == target_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if target is None or target.order_group_id is None:
        return
    month_before = await _month_md(db, target.id, period_month)
    _, _, left = await upsert_consumption(
        db,
        order=target,
        period_month=period_month,
        md_reported=max(month_before - md, ZERO),
        import_id=anchor.import_id,
        user_id=user_id,
    )
    record_event(
        db,
        group_id=target.order_group_id,
        order_id=target.id,
        event_type=EVENT_MD_IMPORT,
        description=(
            f"Cofnięto {format_md(md)} MD za {format_period_month(period_month)} "
            f"— {anchor.consultant_name}: ponowny import miesiąca zmienił MD, "
            f"które czekały na kolejne zamówienie. Pozostało {format_md(left)} MD."
        ),
        payload={
            "period_month": period_month,
            "md_applied": str(-md),
            "md_previous": str(month_before),
            "md_remaining": str(left),
            "import_id": anchor.import_id,
            "awaiting_row_id": anchor.id,
        },
        user_id=user_id,
    )


async def awaiting_md_by_origin_line(
    db: AsyncSession, line_ids: Iterable[int]
) -> dict[int, list[tuple[str, Decimal]]]:
    """``{linia: [(miesiąc, MD oczekujące)]}`` — informacja przy zamówieniu."""
    ids = sorted({int(i) for i in line_ids})
    if not ids:
        return {}
    rows = await db.execute(
        select(
            MdConsumptionImportRow.awaiting_origin_order_id,
            MdConsumptionImport.period_month,
            func.sum(MdConsumptionImportRow.md_pending),
        )
        .join(
            MdConsumptionImport,
            MdConsumptionImportRow.import_id == MdConsumptionImport.id,
        )
        .where(
            MdConsumptionImportRow.status == IMPORT_ROW_AWAITING_ORDER,
            MdConsumptionImportRow.md_pending > 0,
            MdConsumptionImportRow.awaiting_origin_order_id.in_(ids),
        )
        .group_by(
            MdConsumptionImportRow.awaiting_origin_order_id,
            MdConsumptionImport.period_month,
        )
        .order_by(MdConsumptionImport.period_month.asc())
    )
    result: dict[int, list[tuple[str, Decimal]]] = defaultdict(list)
    for origin_id, period, md in rows:
        result[int(origin_id)].append((period, quantize_md(Decimal(str(md)))))
    return dict(result)
