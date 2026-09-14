"""Finanse → Zmiany w zamówieniach: odczyt czterech podzakładek i eksport.

Wszystkie cztery listy liczone są w jednym odczycie, żeby liczniki przy
podzakładkach zawsze zgadzały się z ich treścią.

* **Wejścia** — zamówienia z efektywnym startem w miesiącu (bez anulowanych);
  przedłużenie tej samej osoby u klienta jest oznaczone jako kontynuacja
  (decyzja Artura 14.09), a nie ukrywane — Finanse potrzebują nowego numeru
  zamówienia do faktury.
* **Zejścia** — zamówienia z efektywnym końcem w miesiącu, z werdyktem, czy
  osobę zdjąć z rozliczeń (ta sama reguła następcy co Braki).
* **Zmiany** — dziennik ``order_change_events`` z datą WPROWADZENIA w miesiącu
  (decyzja Artura 14.09) plus dodatkowe projekty: zamówienie zaczynające się
  w miesiącu, gdy osoba ma w tym dniu trwające zamówienie u INNEGO klienta.
* **Braki** — ``order_gaps`` z dniem wykrycia w miesiącu, także uzupełnione
  z opóźnieniem (wpis historyczny).

Odczyt niczego nie zapisuje — braki wykrywa pętla ``order_gaps``, a zamyka
zapis zamówienia.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract
from app.models.order_change_event import OrderChangeEvent
from app.models.order_gap import GAP_STATUS_OPEN, OrderGap
from app.models.user import User
from app.schemas.finance_order_changes import (
    OrderChangeItem,
    OrderChangesCounts,
    OrderChangesPeriod,
    OrderChangesResponse,
    OrderEntryItem,
    OrderExitItem,
    OrderGapItem,
)
from app.services.client_identity import client_display_name_expression
from app.services.order_excel_export import _safe_text
from app.services.order_facts import (
    INTENT_LABELS,
    OrderFact,
    effective_end_expr,
    effective_start_expr,
    load_ending_intents,
    load_facts,
    load_siblings,
    local_day_start,
    previous_of,
    siblings_of,
    successor_of,
)

MONTH_LABELS_PL = (
    "Styczeń",
    "Luty",
    "Marzec",
    "Kwiecień",
    "Maj",
    "Czerwiec",
    "Lipiec",
    "Sierpień",
    "Wrzesień",
    "Październik",
    "Listopad",
    "Grudzień",
)

ORDER_TYPE_LABELS = {"periodic": "B2B", "cost": "Kosztowe", "md": "MD"}
UNIT_LABELS = {"hourly": "h", "daily": "dzień", "monthly": "mc", "md": "MD"}


@dataclass(frozen=True)
class MonthWindow:
    year: int
    month: int
    first: date
    last: date

    @property
    def next_first(self) -> date:
        return date(self.year + (self.month // 12), self.month % 12 + 1, 1)

    @classmethod
    def of(cls, year: int, month: int) -> "MonthWindow":
        first = date(year, month, 1)
        following = date(year + (month // 12), month % 12 + 1, 1)
        return cls(
            year=year,
            month=month,
            first=first,
            last=date.fromordinal(following.toordinal() - 1),
        )


def period_label(year: int, month: int) -> str:
    return f"{MONTH_LABELS_PL[month - 1]} {year}"


def _fmt_date(value: Optional[date]) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def _ref(fact: OrderFact) -> dict:
    return {
        "order_id": fact.order_id,
        "order_group_id": fact.order_group_id,
        "contract_id": fact.contract_id,
        "client_id": fact.client_id,
        "client_name": fact.client_name,
        "consultant_name": fact.consultant_name,
        "order_number": fact.number,
    }


def _sort_key(item) -> tuple:
    return (item.consultant_name.lower(), item.client_name.lower(), item.order_number)


# ── Wejścia ──────────────────────────────────────────────────────────────────


async def _entries(
    db: AsyncSession, window: MonthWindow
) -> tuple[list[OrderEntryItem], list[OrderFact]]:
    start = effective_start_expr()
    facts = await load_facts(
        db,
        ClientOrder.status != ClientOrderStatus.cancelled,
        start.is_not(None),
        start >= window.first,
        start <= window.last,
    )
    siblings = await load_siblings(db, facts)
    items: list[OrderEntryItem] = []
    for fact in facts:
        previous = previous_of(fact, siblings_of(fact, siblings))
        items.append(
            OrderEntryItem(
                **_ref(fact),
                start_date=fact.start,
                end_date=fact.end,
                rate_cost=fact.rate_cost,
                rate_revenue=fact.rate_revenue,
                rate_unit=fact.rate_unit,
                currency=fact.currency,
                order_type=fact.order_type,
                status=fact.status,
                is_continuation=previous is not None,
                previous_order_number=previous.number if previous else None,
                previous_end_date=previous.end if previous else None,
            )
        )
    return items, facts


async def _additional_projects(
    db: AsyncSession, entry_facts: list[OrderFact]
) -> dict[int, list[OrderFact]]:
    """Zamówienie startujące, gdy osoba ma trwające zamówienie u innego klienta."""

    people = {fact.candidate_id for fact in entry_facts if fact.candidate_id}
    if not people:
        return {}
    others = await load_facts(
        db,
        Contract.candidate_id.in_(sorted(people)),
        ClientOrder.status.notin_(
            (ClientOrderStatus.cancelled, ClientOrderStatus.draft)
        ),
    )
    by_person: dict[int, list[OrderFact]] = {}
    for other in others:
        by_person.setdefault(other.candidate_id, []).append(other)
    result: dict[int, list[OrderFact]] = {}
    for fact in entry_facts:
        if fact.candidate_id is None or fact.start is None:
            continue
        running = [
            other
            for other in by_person.get(fact.candidate_id, [])
            if other.client_id != fact.client_id
            and (other.start is None or other.start <= fact.start)
            and (
                (
                    other.end is None
                    and other.status != ClientOrderStatus.completed.value
                )
                or (other.end is not None and other.end >= fact.start)
            )
        ]
        if running:
            result[fact.order_id] = running
    return result


# ── Zejścia ──────────────────────────────────────────────────────────────────


async def _exits(
    db: AsyncSession, window: MonthWindow, today: date
) -> list[OrderExitItem]:
    end = effective_end_expr()
    facts = await load_facts(
        db,
        ClientOrder.status.notin_(
            (ClientOrderStatus.cancelled, ClientOrderStatus.draft)
        ),
        end.is_not(None),
        end >= window.first,
        end <= window.last,
    )
    intents = await load_ending_intents(db, facts)
    siblings = await load_siblings(db, facts)
    # Zapisany brak rozstrzyga werdykt także wtedy, gdy zegar przeglądarki
    # i serwera mówi co innego niż dzień wykrycia — Zejścia i Braki nie mogą
    # sobie przeczyć.
    gap_orders = (
        set(
            (
                await db.scalars(
                    select(OrderGap.order_id).where(
                        OrderGap.order_id.in_([fact.order_id for fact in facts]),
                        OrderGap.status == GAP_STATUS_OPEN,
                    )
                )
            ).all()
        )
        if facts
        else set()
    )
    items: list[OrderExitItem] = []
    for fact in facts:
        if fact.end is None:
            continue
        intent = intents.get(fact.order_id)
        successor = successor_of(fact, siblings_of(fact, siblings))
        if intent is not None:
            verdict, label = "ended_intent", INTENT_LABELS[intent]
        elif fact.works_until_md_exhausted:
            # Linia MD pracuje po dacie końca, dopóki ma budżet — zdjęcie jej
            # z rozliczeń byłoby błędem (skaner wygasania też jej nie kończy).
            verdict = "continuation"
            remaining = (
                f"{fact.md_remaining.normalize():f}" if fact.md_remaining else "0"
            )
            label = f"Trwa do wyczerpania budżetu MD (zostało {remaining} MD)"
        elif successor is not None:
            draft = " (szkic)" if successor.is_draft else ""
            verdict = "continuation"
            label = (
                f"Kontynuacja: zam. {successor.number}{draft} "
                f"od {_fmt_date(successor.start)}"
            )
        elif fact.end >= today and fact.order_id not in gap_orders:
            verdict = "ending_pending"
            label = (
                f"Kończy się {_fmt_date(fact.end)} — na razie brak kolejnego zamówienia"
            )
        else:
            verdict = "no_successor"
            label = "Brak kolejnego zamówienia — do usunięcia z rozliczeń"
        items.append(
            OrderExitItem(
                **_ref(fact),
                end_date=fact.end,
                start_date=fact.start,
                rate_cost=fact.rate_cost,
                rate_revenue=fact.rate_revenue,
                rate_unit=fact.rate_unit,
                currency=fact.currency,
                order_type=fact.order_type,
                verdict=verdict,
                verdict_label=label,
                successor_order_number=successor.number if successor else None,
                successor_start_date=successor.start if successor else None,
                intent=intent,
            )
        )
    return sorted(items, key=_sort_key)


# ── Zmiany ───────────────────────────────────────────────────────────────────


async def _group_refs(db: AsyncSession, group_ids: Iterable[int]) -> dict[int, dict]:
    ids = sorted(set(group_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            ClientOrderGroup.id,
            ClientOrderGroup.client_id,
            ClientOrderGroup.order_number,
            client_display_name_expression().label("client_name"),
            func.count(ClientOrder.id).label("lines"),
        )
        .join(Client, Client.id == ClientOrderGroup.client_id)
        .outerjoin(
            ClientOrder,
            (ClientOrder.order_group_id == ClientOrderGroup.id)
            & (ClientOrder.status != ClientOrderStatus.cancelled),
        )
        .where(ClientOrderGroup.id.in_(ids))
        .group_by(ClientOrderGroup.id, Client.id)
    )
    return {
        row.id: {
            "order_id": None,
            "order_group_id": row.id,
            "contract_id": None,
            "client_id": row.client_id,
            "client_name": row.client_name or "—",
            "consultant_name": f"Całe zamówienie ({row.lines} os.)",
            "order_number": row.order_number or "—",
        }
        for row in rows.all()
    }


async def _changes(
    db: AsyncSession,
    window: MonthWindow,
    entry_facts: list[OrderFact],
    additional: dict[int, list[OrderFact]],
) -> list[OrderChangeItem]:
    zone = ZoneInfo(DEFAULT_TZ)
    events = list(
        (
            await db.scalars(
                select(OrderChangeEvent)
                .where(
                    OrderChangeEvent.created_at >= local_day_start(window.first),
                    OrderChangeEvent.created_at < local_day_start(window.next_first),
                )
                .order_by(
                    OrderChangeEvent.created_at.desc(), OrderChangeEvent.id.desc()
                )
            )
        ).all()
    )
    order_ids = sorted({e.order_id for e in events if e.order_id is not None})
    facts = (
        {
            fact.order_id: fact
            for fact in await load_facts(db, ClientOrder.id.in_(order_ids))
        }
        if order_ids
        else {}
    )
    groups = await _group_refs(
        db,
        (e.order_group_id for e in events if e.order_id is None and e.order_group_id),
    )
    author_ids = sorted({e.created_by_user_id for e in events if e.created_by_user_id})
    authors = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(author_ids))
                )
            ).all()
        )
        if author_ids
        else {}
    )

    items: list[OrderChangeItem] = []
    for event in events:
        if event.order_id is not None:
            fact = facts.get(event.order_id)
            if fact is None:
                continue  # zamówienie usunięte — nie ma już czego rozliczać
            ref = _ref(fact)
            whole = False
        else:
            ref = groups.get(event.order_group_id or 0)
            if ref is None:
                continue
            whole = True
        items.append(
            OrderChangeItem(
                **ref,
                kind=event.field,
                occurred_at=event.created_at,
                effective_date=event.created_at.astimezone(zone).date(),
                old_amount=event.old_amount,
                new_amount=event.new_amount,
                old_unit=event.old_unit,
                new_unit=event.new_unit,
                currency=event.currency,
                old_date=event.old_date,
                new_date=event.new_date,
                is_whole_order=whole,
                source=event.source,
                author_name=authors.get(event.created_by_user_id),
            )
        )

    for fact in entry_facts:
        running = additional.get(fact.order_id)
        if not running:
            continue
        items.append(
            OrderChangeItem(
                **_ref(fact),
                kind="additional_project",
                effective_date=fact.start,
                rate_cost=fact.rate_cost,
                rate_revenue=fact.rate_revenue,
                rate_unit=fact.rate_unit,
                currency=fact.currency,
                other_client_names=sorted({other.client_name for other in running}),
            )
        )
    return items


# ── Braki ────────────────────────────────────────────────────────────────────


async def _gaps(db: AsyncSession, window: MonthWindow) -> list[OrderGapItem]:
    zone = ZoneInfo(DEFAULT_TZ)
    rows = (
        await db.execute(
            select(
                OrderGap,
                client_display_name_expression().label("client_name"),
                Candidate.name,
                Candidate.lastname,
            )
            .outerjoin(Client, Client.id == OrderGap.client_id)
            .outerjoin(Contract, Contract.id == OrderGap.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                OrderGap.detected_on >= window.first,
                OrderGap.detected_on <= window.last,
            )
            # Otwarte braki (``open``) przed uzupełnionymi (``filled_late``).
            .order_by(OrderGap.status.desc(), OrderGap.detected_on.desc(), OrderGap.id)
        )
    ).all()
    items: list[OrderGapItem] = []
    for gap, client_name, first, last in rows:
        delay = None
        if gap.resolved_at is not None:
            delay = (gap.resolved_at.astimezone(zone).date() - gap.detected_on).days
        items.append(
            OrderGapItem(
                gap_id=gap.id,
                order_id=gap.order_id,
                order_group_id=gap.order_group_id,
                contract_id=gap.contract_id,
                client_id=gap.client_id,
                client_name=client_name or "—",
                consultant_name=f"{first or ''} {last or ''}".strip() or "—",
                order_number=gap.order_number or "—",
                ended_on=gap.ended_on,
                detected_on=gap.detected_on,
                status=gap.status,
                resolved_order_number=gap.resolved_order_number,
                resolved_at=gap.resolved_at,
                delay_days=max(delay, 0) if delay is not None else None,
            )
        )
    return items


async def build_order_changes(
    db: AsyncSession, year: int, month: int, *, today: Optional[date] = None
) -> OrderChangesResponse:
    window = MonthWindow.of(year, month)
    day = today or business_today()
    entries, entry_facts = await _entries(db, window)
    additional = await _additional_projects(db, entry_facts)
    entries = sorted(
        (
            entry.model_copy(
                update={"additional_project": entry.order_id in additional}
            )
            for entry in entries
        ),
        key=_sort_key,
    )
    exits = await _exits(db, window, day)
    changes = await _changes(db, window, entry_facts, additional)
    gaps = await _gaps(db, window)
    tracked_since = await db.scalar(select(func.min(OrderChangeEvent.created_at)))
    open_total = await db.scalar(
        select(func.count(OrderGap.id)).where(OrderGap.status == GAP_STATUS_OPEN)
    )
    return OrderChangesResponse(
        period=OrderChangesPeriod(
            year=year, month=month, label=period_label(year, month)
        ),
        counts=OrderChangesCounts(
            changes=len(changes), entries=len(entries), exits=len(exits), gaps=len(gaps)
        ),
        changes=changes,
        entries=entries,
        exits=exits,
        gaps=gaps,
        changes_tracked_since=tracked_since,
        gaps_tracked_since=settings.ORDER_GAP_TRACKING_START,
        open_gaps_total=open_total or 0,
    )


# ── Eksport ──────────────────────────────────────────────────────────────────


def _rate(
    amount: Optional[Decimal], unit: Optional[str], currency: Optional[str]
) -> str:
    if amount is None:
        return "—"
    unit_label = UNIT_LABELS.get(unit or "", unit or "")
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + (
        f" {currency or 'PLN'}/{unit_label}" if unit_label else f" {currency or 'PLN'}"
    )


def _change_description(item: OrderChangeItem) -> tuple[str, str, str]:
    if item.kind == "additional_project":
        return (
            "Dodatkowy projekt",
            "u: " + ", ".join(item.other_client_names),
            f"od {_fmt_date(item.effective_date)}; koszt "
            f"{_rate(item.rate_cost, item.rate_unit, item.currency)}, przychód "
            f"{_rate(item.rate_revenue, item.rate_unit, item.currency)}",
        )
    if item.kind == "end_date":
        return (
            "Zmiana daty końca",
            _fmt_date(item.old_date) if item.old_date else "bezterminowo",
            _fmt_date(item.new_date) if item.new_date else "bezterminowo",
        )
    label = (
        "Zmiana stawki kosztowej"
        if item.kind == "rate_cost"
        else "Zmiana stawki przychodowej"
    )
    return (
        label,
        _rate(item.old_amount, item.old_unit, item.currency),
        _rate(item.new_amount, item.new_unit, item.currency),
    )


def _sheet(
    workbook: Workbook,
    title: str,
    headers: list[str],
    rows: list[list[object]],
    widths: list[int],
) -> None:
    sheet = workbook.create_sheet(title)
    sheet.append(headers)
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = fill
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        sheet.append(
            [_safe_text(value) if isinstance(value, str) else value for value in row]
        )
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, bool):
                continue
            if isinstance(cell.value, (float, Decimal)):
                cell.number_format = "#,##0.00"
            elif isinstance(cell.value, int):
                cell.number_format = "0"
            elif isinstance(cell.value, date):
                cell.number_format = "DD.MM.YYYY"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False


def build_order_changes_workbook(data: OrderChangesResponse) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    zone = ZoneInfo(DEFAULT_TZ)

    _sheet(
        workbook,
        f"Zmiany ({data.counts.changes})",
        [
            "Konsultant",
            "Klient",
            "Numer zamówienia",
            "Zmiana",
            "Było",
            "Jest",
            "Data",
            "Autor",
        ],
        [
            [
                item.consultant_name,
                item.client_name,
                item.order_number,
                *_change_description(item),
                item.occurred_at.astimezone(zone).replace(tzinfo=None)
                if item.occurred_at
                else item.effective_date,
                item.author_name or ("System" if item.source == "system" else "—"),
            ]
            for item in data.changes
        ],
        [28, 28, 22, 26, 26, 40, 18, 22],
    )
    _sheet(
        workbook,
        f"Wejścia ({data.counts.entries})",
        [
            "Konsultant",
            "Klient",
            "Numer zamówienia",
            "Data rozpoczęcia",
            "Data zakończenia",
            "Stawka kosztowa",
            "Stawka przychodowa",
            "Jednostka",
            "Waluta",
            "Typ zamówienia",
            "Status",
            "Kontynuacja",
            "Dodatkowy projekt",
        ],
        [
            [
                item.consultant_name,
                item.client_name,
                item.order_number,
                item.start_date,
                item.end_date,
                item.rate_cost,
                item.rate_revenue,
                UNIT_LABELS.get(item.rate_unit or "", item.rate_unit or ""),
                item.currency or "PLN",
                ORDER_TYPE_LABELS.get(item.order_type, item.order_type),
                "Szkic" if item.status == ClientOrderStatus.draft.value else "",
                f"po zam. {item.previous_order_number}"
                if item.is_continuation
                else "Nowy konsultant",
                "Tak" if item.additional_project else "",
            ]
            for item in data.entries
        ],
        [28, 28, 22, 16, 16, 16, 18, 11, 9, 15, 10, 26, 18],
    )
    _sheet(
        workbook,
        f"Zejścia ({data.counts.exits})",
        [
            "Konsultant",
            "Klient",
            "Numer zamówienia",
            "Data zakończenia",
            "Typ zamówienia",
            "Decyzja dla rozliczeń",
        ],
        [
            [
                item.consultant_name,
                item.client_name,
                item.order_number,
                item.end_date,
                ORDER_TYPE_LABELS.get(item.order_type, item.order_type),
                item.verdict_label,
            ]
            for item in data.exits
        ],
        [28, 28, 22, 16, 15, 60],
    )
    _sheet(
        workbook,
        f"Braki ({data.counts.gaps})",
        [
            "Konsultant",
            "Klient",
            "Zakończone zamówienie",
            "Koniec zamówienia",
            "Brak od",
            "Status",
            "Uzupełnione zamówieniem",
            "Uzupełniono",
            "Opóźnienie (dni)",
        ],
        [
            [
                item.consultant_name,
                item.client_name,
                item.order_number,
                item.ended_on,
                item.detected_on,
                "Uzupełnione z opóźnieniem"
                if item.status == "filled_late"
                else "Brak zamówienia",
                item.resolved_order_number or "",
                item.resolved_at.astimezone(zone).date() if item.resolved_at else None,
                item.delay_days,
            ]
            for item in data.gaps
        ],
        [28, 28, 22, 18, 14, 26, 24, 14, 16],
    )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def order_changes_filename(year: int, month: int) -> str:
    return f"Zmiany_w_zamowieniach_{year}-{month:02d}.xlsx"
