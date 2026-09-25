"""Historia zamówienia MD — widok biznesowy dziennika ``client_order_group_events``.

Ticket 7 (25.09.2026): historia mieszała trzy rodzaje zapisów — zdarzenia
biznesowe, pojedyncze zejścia MD z importów i techniczne edycje pól
(``rate_candidate_currency``). Na zamówieniu 4500030197 było 23 wpisy, w tym
6 edycji Konrada Tepera w 3 minuty i dwukrotny „Zakończono zamówienie".

Dziennik zostaje nietknięty (czyta go ``/events``, dziesiątki testów i
raporty). Ten moduł SKŁADA z niego widok przy odczycie — czyste funkcje bez
bazy, żeby reguły grupowania dało się przetestować na liście zdarzeń:

* import MD → JEDEN wpis na import („Import MD za sierpień 2026 – 2 osoby,
  25 MD") z odsyłaczem do widoku „Importy MD", zamiast wpisu na każdą osobę;
* edycje tej samej osoby przez tego samego autora w odstępie do 15 minut →
  jeden wpis z wynikiem netto i listą zmian do rozwinięcia;
* ręczne zejścia MD („zejście MD") liczą się do serii edycji, ale seria
  złożona WYŁĄCZNIE z nich (albo z pól technicznych) nie trafia do historii —
  zejścia żyją w oknie „Zużycie MD" osoby, pola techniczne w Timeline
  kontraktu;
* zdublowane zapisy systemowe (to samo zdarzenie w tej samej minucie) → raz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

from app.services.client_order_lines import format_period_month
from app.services.multi_consultant_orders import (
    EVENT_BUDGET_EXHAUSTED,
    EVENT_CONSULTANT_ADDED,
    EVENT_CONSULTANT_ENDED,
    EVENT_CONSULTANT_SWAPPED,
    EVENT_INVOICE_IMPORT,
    EVENT_MANUAL_EDIT,
    EVENT_MD_IMPORT,
    EVENT_MD_OFFBOARDING_PENDING,
    EVENT_MD_OFFBOARDING_REMOVED,
    EVENT_MD_OFFBOARDING_RESTORED,
    EVENT_MD_OFFBOARDING_TRANSFERRED,
    EVENT_MD_TRANSFER,
    EVENT_ORDER_CANCELLED,
    EVENT_ORDER_CLOSED,
    EVENT_ORDER_CREATED,
    EVENT_ORDER_EXTENDED,
    EVENT_ORDER_REOPENED,
    EVENT_ORDER_RESTORED,
    EVENT_TYPE_LABELS,
    format_md,
)

# Kategorie filtra „typ zdarzenia" nad listą (Wszystko liczy front).
CATEGORY_ORDER = "order"
CATEGORY_CONSULTANTS = "consultants"
CATEGORY_CONSUMPTION = "consumption"
CATEGORY_EDITS = "edits"

EDIT_WINDOW = timedelta(minutes=15)

#: Etykieta ręcznego zejścia MD w ``payload.changed`` (``upsert_line_consumption``).
CONSUMPTION_EDIT_LABEL = "zejście MD"

#: Polskie nazwy pól technicznych. Klucze po lewej to SUROWE nazwy kolumn, które
#: ``update_line`` wpisywał do ``payload.changed`` do 25.09.2026 — historia ich
#: nie pokazuje, Timeline kontraktu tłumaczy je tą mapą.
TECHNICAL_FIELD_LABELS: dict[str, str] = {
    "rate_candidate_currency": "waluta stawki kosztowej",
    "rate_client_currency": "waluta stawki przychodowej",
    "rate_unit": "jednostka stawki",
    "billing_hours_per_month": "dzielnik godzin w miesiącu",
    "currency": "waluta",
}
TECHNICAL_LABELS: frozenset[str] = frozenset(
    set(TECHNICAL_FIELD_LABELS) | set(TECHNICAL_FIELD_LABELS.values())
)

#: Etykiety zmian z kwotą — rola bez finansów widzi, ŻE się zmieniły, ale nie ile.
FINANCE_CHANGE_LABELS: frozenset[str] = frozenset(
    {"stawka kosztowa", "stawka przychodowa"}
)

_ORDER_EVENTS = frozenset(
    {
        EVENT_ORDER_CREATED,
        EVENT_ORDER_CLOSED,
        EVENT_ORDER_REOPENED,
        EVENT_BUDGET_EXHAUSTED,
        EVENT_ORDER_EXTENDED,
        EVENT_ORDER_CANCELLED,
        EVENT_ORDER_RESTORED,
    }
)
_CONSULTANT_EVENTS = frozenset(
    {
        EVENT_CONSULTANT_ADDED,
        EVENT_CONSULTANT_SWAPPED,
        EVENT_CONSULTANT_ENDED,
        EVENT_MD_OFFBOARDING_PENDING,
        EVENT_MD_OFFBOARDING_REMOVED,
        EVENT_MD_OFFBOARDING_TRANSFERRED,
        EVENT_MD_OFFBOARDING_RESTORED,
    }
)
_CONSUMPTION_EVENTS = frozenset(
    {EVENT_MD_IMPORT, EVENT_INVOICE_IMPORT, EVENT_MD_TRANSFER}
)


@dataclass(frozen=True)
class RawEvent:
    """Wiersz dziennika — to, czego potrzebuje widok (bez sesji ORM)."""

    id: int
    event_type: str
    description: str
    order_id: Optional[int]
    payload: Optional[dict[str, Any]]
    created_at: datetime
    author_id: Optional[int]
    author_name: Optional[str]


@dataclass
class HistoryChange:
    label: str
    before: Optional[str] = None
    after: Optional[str] = None


@dataclass
class HistoryDetail:
    created_at: datetime
    author_name: Optional[str]
    author_id: Optional[int]
    text: str


@dataclass
class HistoryEntry:
    key: str
    category: str
    event_type: str
    type_label: str
    created_at: datetime
    author_id: Optional[int]
    author_name: Optional[str]
    summary: str
    order_id: Optional[int] = None
    person_name: Optional[str] = None
    person_names: list[str] = field(default_factory=list)
    changes: list[HistoryChange] = field(default_factory=list)
    balance_before: Optional[Decimal] = None
    balance_after: Optional[Decimal] = None
    details: list[HistoryDetail] = field(default_factory=list)
    import_id: Optional[int] = None
    import_period_month: Optional[str] = None
    import_people: Optional[int] = None
    import_md: Optional[Decimal] = None
    source_event_ids: list[int] = field(default_factory=list)


def _changed(payload: Optional[dict]) -> Optional[list[str]]:
    changed = (payload or {}).get("changed")
    return [str(c) for c in changed] if isinstance(changed, list) else None


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def is_technical_label(label: str) -> bool:
    return label in TECHNICAL_LABELS


def technical_labels_pl(labels: list[str]) -> list[str]:
    """Surowe nazwy pól → polskie; etykiety już polskie przechodzą bez zmian."""
    return [TECHNICAL_FIELD_LABELS.get(label, label) for label in labels]


def is_consumption_edit(ev: RawEvent) -> bool:
    return ev.event_type == EVENT_MANUAL_EDIT and _changed(ev.payload) == [
        CONSUMPTION_EDIT_LABEL
    ]


def is_technical_only_edit(ev: RawEvent) -> bool:
    """Edycja linii, która zmieniła WYŁĄCZNIE pola techniczne (waluta, jednostka)."""
    if ev.event_type != EVENT_MANUAL_EDIT or ev.order_id is None:
        return False
    payload = ev.payload or {}
    diff = payload.get("diff")
    changed = _changed(payload)
    if isinstance(diff, dict):
        return not diff and bool(payload.get("technical"))
    return bool(changed) and all(is_technical_label(c) for c in changed)


def technical_changes(ev: RawEvent) -> list[HistoryChange]:
    """Zmiany pól technicznych jednego wpisu — dla Timeline kontraktu."""
    payload = ev.payload or {}
    technical = payload.get("technical")
    if isinstance(technical, dict):
        out: list[HistoryChange] = []
        for label, pair in technical.items():
            before, after = _pair(pair)
            out.append(HistoryChange(label=str(label), before=before, after=after))
        return out
    return [
        HistoryChange(label=label)
        for label in technical_labels_pl(
            [c for c in (_changed(payload) or []) if is_technical_label(c)]
        )
    ]


def _pair(value: Any) -> tuple[Optional[str], Optional[str]]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        before, after = value
        return (
            None if before is None else str(before),
            None if after is None else str(after),
        )
    return None, None


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def dedupe_events(events: list[RawEvent]) -> list[RawEvent]:
    """Zdublowany zapis systemowy (to samo zdarzenie, ta sama minuta) — raz.

    Porównanie obejmuje opis i payload: dwa różne zdarzenia tego samego typu
    w jednej minucie (np. import dwóch osób) mają różne opisy i zostają.
    """
    seen: set[tuple] = set()
    out: list[RawEvent] = []
    for ev in events:
        key = (
            ev.event_type,
            ev.order_id,
            ev.author_id,
            ev.description,
            repr(sorted((ev.payload or {}).items())),
            _minute(ev.created_at),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def _category(ev: RawEvent) -> str:
    if ev.event_type in _CONSUMPTION_EVENTS:
        return CATEGORY_CONSUMPTION
    if ev.event_type in _CONSULTANT_EVENTS:
        return CATEGORY_CONSULTANTS
    if ev.event_type == EVENT_MANUAL_EDIT:
        return CATEGORY_EDITS if ev.order_id is not None else CATEGORY_ORDER
    if ev.event_type in _ORDER_EVENTS:
        return CATEGORY_ORDER
    return CATEGORY_ORDER


def _edit_detail_text(ev: RawEvent, person: Optional[str]) -> str:
    """Treść jednej edycji w rozwinięciu — z payloadu, bez surowych nazw pól."""
    payload = ev.payload or {}
    remaining = _decimal(payload.get("md_remaining"))
    tail = f" Pozostało {format_md(remaining)} MD." if remaining is not None else ""
    changed = _changed(payload)
    if changed == [CONSUMPTION_EDIT_LABEL]:
        month = payload.get("period_month")
        month_label = format_period_month(month) if isinstance(month, str) else "?"
        if "removed_md" in payload:
            return (
                f"Usunięto zejście MD za {month_label} "
                f"({format_md(_decimal(payload.get('removed_md')))} MD).{tail}"
            )
        previous = _decimal(payload.get("previous"))
        value = _decimal(payload.get("md_reported"))
        if previous is not None and previous != 0 and previous != value:
            return (
                f"Zejście MD za {month_label}: {format_md(previous)} → "
                f"{format_md(value)} MD.{tail}"
            )
        return f"Zejście MD za {month_label}: {format_md(value)} MD.{tail}"
    diff = payload.get("diff")
    if isinstance(diff, dict):
        parts = []
        for label, pair in diff.items():
            before, after = _pair(pair)
            parts.append(f"{label}: {before or '—'} → {after or '—'}")
        if parts:
            return "; ".join(parts) + "." + tail
        if payload.get("technical"):
            return "Zmiana pól technicznych (szczegóły w Timeline kontraktu)." + tail
    if changed is not None:
        business = [c for c in changed if not is_technical_label(c)]
        if business:
            return "Zmieniono: " + ", ".join(business) + "." + tail
        return "Zmiana pól technicznych (szczegóły w Timeline kontraktu)." + tail
    # Wpis bez listy pól (np. jednorazowa korekta danych) — opis dosłownie.
    return ev.description


def _net_changes(group: list[RawEvent]) -> list[HistoryChange]:
    """Wynik netto serii: pierwsza wartość „przed" i ostatnia „po" per pole.

    Wpisy sprzed 25.09.2026 nie niosą wartości — zostaje sama nazwa pola.
    """
    order: list[str] = []
    before: dict[str, Optional[str]] = {}
    after: dict[str, Optional[str]] = {}
    exact: set[str] = set()
    for ev in group:
        payload = ev.payload or {}
        diff = payload.get("diff")
        if isinstance(diff, dict):
            for label, pair in diff.items():
                label = str(label)
                b, a = _pair(pair)
                if label not in order:
                    order.append(label)
                    before[label] = b
                exact.add(label)
                after[label] = a
            continue
        for label in _changed(payload) or []:
            if label == CONSUMPTION_EDIT_LABEL or is_technical_label(label):
                continue
            if label not in order:
                order.append(label)
    out: list[HistoryChange] = []
    for label in order:
        if label in exact:
            if before.get(label) == after.get(label):
                continue  # zmiana cofnięta w tej samej serii
            out.append(HistoryChange(label, before.get(label), after.get(label)))
        else:
            out.append(HistoryChange(label))
    return out


def _balance(ev: RawEvent) -> Optional[Decimal]:
    return _decimal((ev.payload or {}).get("md_remaining"))


def build_history(
    events: list[RawEvent],
    *,
    person_name: Callable[[Optional[int]], Optional[str]],
) -> list[HistoryEntry]:
    """Widok historii: od najnowszego, pogrupowany i bez szumu technicznego.

    ``events`` przychodzą już bez wpisów technicznych na poziomie zamówienia
    (``_is_technical_event`` w API) — ten moduł odsiewa szum edycji LINII.
    """
    ordered = sorted(dedupe_events(events), key=lambda ev: (ev.created_at, ev.id))
    entries: list[HistoryEntry] = []

    # ── Importy: jeden wpis na import ──
    imports: dict[tuple[str, int], list[RawEvent]] = {}
    edits: list[RawEvent] = []
    for ev in ordered:
        payload = ev.payload or {}
        import_id = payload.get("import_id")
        if ev.event_type in (EVENT_MD_IMPORT, EVENT_INVOICE_IMPORT) and isinstance(
            import_id, int
        ):
            imports.setdefault((ev.event_type, import_id), []).append(ev)
            continue
        if ev.event_type == EVENT_MANUAL_EDIT and ev.order_id is not None:
            edits.append(ev)
            continue
        entries.append(_single_entry(ev, person_name))

    for (event_type, import_id), group in imports.items():
        entries.append(_import_entry(event_type, import_id, group, person_name))

    # ── Serie edycji linii ──
    chains: list[list[RawEvent]] = []
    open_chain: dict[tuple[int, Optional[int]], list[RawEvent]] = {}
    for ev in edits:
        key = (ev.order_id or 0, ev.author_id)
        chain = open_chain.get(key)
        if chain is not None and ev.created_at - chain[-1].created_at <= EDIT_WINDOW:
            chain.append(ev)
        else:
            chain = [ev]
            chains.append(chain)
            open_chain[key] = chain

    # Saldo PRZED serią: ostatnie znane saldo osoby z dowolnego wcześniejszego
    # wpisu (import, edycja, dodanie) — liczone po osi czasu.
    balance_points: dict[int, list[tuple[datetime, int, Decimal]]] = {}
    for ev in ordered:
        value = _balance(ev)
        if ev.order_id is not None and value is not None:
            balance_points.setdefault(ev.order_id, []).append(
                (ev.created_at, ev.id, value)
            )

    for chain in chains:
        if all(is_consumption_edit(ev) or is_technical_only_edit(ev) for ev in chain):
            continue
        first, last = chain[0], chain[-1]
        order_id = first.order_id
        # Saldo sprzed serii: od 25.09.2026 zapisane wprost na pierwszej edycji,
        # dla starszych wpisów — ostatnie saldo z wcześniejszego zdarzenia.
        before_balance = _decimal((first.payload or {}).get("md_remaining_before"))
        if before_balance is None:
            for ts, ev_id, value in balance_points.get(order_id or 0, []):
                if (ts, ev_id) < (first.created_at, first.id):
                    before_balance = value
        after_balance: Optional[Decimal] = None
        for ev in chain:
            value = _balance(ev)
            if value is not None:
                after_balance = value
        person = person_name(order_id)
        changes = _net_changes(chain)
        summary = _edit_summary(chain, changes)
        entries.append(
            HistoryEntry(
                key=f"edit-{first.id}",
                category=CATEGORY_EDITS,
                event_type=EVENT_MANUAL_EDIT,
                type_label="Edycja",
                created_at=last.created_at,
                author_id=first.author_id,
                author_name=first.author_name,
                summary=summary,
                order_id=order_id,
                person_name=person,
                person_names=[person] if person else [],
                changes=changes,
                balance_before=before_balance,
                balance_after=after_balance,
                details=(
                    [
                        HistoryDetail(
                            created_at=ev.created_at,
                            author_name=ev.author_name,
                            author_id=ev.author_id,
                            text=_edit_detail_text(ev, person),
                        )
                        for ev in chain
                    ]
                    if len(chain) > 1
                    else []
                ),
                source_event_ids=[ev.id for ev in chain],
            )
        )

    entries.sort(key=lambda e: (e.created_at, e.key), reverse=True)
    return entries


def _edit_summary(chain: list[RawEvent], changes: list[HistoryChange]) -> str:
    if len(chain) == 1:
        text = _edit_detail_text(chain[0], None)
        # Jedna edycja: opis jest treścią wpisu, zmiany niosą „przed → po".
        return text
    count = len(chain)
    return f"{count} zmian w serii edycji"


def _single_entry(
    ev: RawEvent, person_name: Callable[[Optional[int]], Optional[str]]
) -> HistoryEntry:
    person = person_name(ev.order_id) if ev.order_id is not None else None
    payload = ev.payload or {}
    return HistoryEntry(
        key=f"ev-{ev.id}",
        category=_category(ev),
        event_type=ev.event_type,
        type_label=EVENT_TYPE_LABELS.get(ev.event_type, ev.event_type),
        created_at=ev.created_at,
        author_id=ev.author_id,
        author_name=ev.author_name,
        summary=ev.description,
        order_id=ev.order_id,
        person_name=person,
        person_names=[person] if person else [],
        balance_after=_decimal(payload.get("md_remaining")),
        source_event_ids=[ev.id],
    )


def _import_entry(
    event_type: str,
    import_id: int,
    group: list[RawEvent],
    person_name: Callable[[Optional[int]], Optional[str]],
) -> HistoryEntry:
    first = group[0]
    payload = first.payload or {}
    month = (
        payload.get("period_month")
        if isinstance(payload.get("period_month"), str)
        else None
    )
    month_label = format_period_month(month) if month else "?"
    people: list[str] = []
    person_ids: set[int] = set()
    total = Decimal("0")
    for ev in group:
        p = ev.payload or {}
        if ev.order_id is not None:
            person_ids.add(ev.order_id)
            name = person_name(ev.order_id)
            if name and name not in people:
                people.append(name)
        if event_type == EVENT_MD_IMPORT:
            if "md_reverted" in p:
                total -= _decimal(p.get("md_reverted")) or Decimal("0")
            elif ev.order_id is None:
                total += _decimal(p.get("md_reported")) or Decimal("0")
            else:
                total += _decimal(p.get("md_applied")) or Decimal("0")
    if event_type == EVENT_INVOICE_IMPORT:
        summary = f"Import faktur za {month_label}"
        type_label = EVENT_TYPE_LABELS[EVENT_INVOICE_IMPORT]
    else:
        count = len(person_ids)
        who = "wspólna pula" if not person_ids else f"{count} {_osob(count)}"
        summary = f"Import MD za {month_label} – {who}, {format_md(total)} MD"
        type_label = EVENT_TYPE_LABELS[EVENT_MD_IMPORT]
    return HistoryEntry(
        key=f"import-{event_type}-{import_id}",
        category=CATEGORY_CONSUMPTION,
        event_type=event_type,
        type_label=type_label,
        created_at=min(ev.created_at for ev in group),
        author_id=first.author_id,
        author_name=first.author_name,
        summary=summary,
        person_names=people,
        import_id=import_id,
        import_period_month=month,
        import_people=len(person_ids),
        import_md=total if event_type == EVENT_MD_IMPORT else None,
        source_event_ids=[ev.id for ev in group],
    )


def _osob(count: int) -> str:
    if count == 1:
        return "osoba"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "osoby"
    return "osób"
