"""Finanse → Zmiany w zamówieniach: odhaczenia „Zrobione", karta zamówienia i historia.

Audyt miesiąca liczy ``finance_order_changes.build_order_changes``; ten moduł
dokłada do każdej pozycji to, czego potrzebuje karta zamówienia:

* **klucz pozycji** (``item_key``) — stabilny identyfikator, pod którym
  zapisuje się odhaczenie. Wpis dziennika zmian ma własne id; pozycje liczone
  z bieżącego stanu (wejście, zejście, kończące się zamówienie, brak) niosą
  w kluczu to, co je wyróżnia — ponowna zmiana zamówienia (inna data końca,
  inny status braku) daje nowy klucz, czyli nową pozycję „Do zrobienia";
* **stan odhaczenia** — ostatni wpis klucza w ``order_change_checks``
  (dopisywany audyt: odhaczenie i cofnięcie zostają w historii);
* **okres zamówienia i PDF** — do nagłówka karty (format z „Zamówień PDF")
  i do podglądu;
* **kto i kiedy wprowadził** pozycję (autor wpisu albo zamówienia, mail
  ``zamowienia@b2bnetwork.pl``).

Odhaczenia zapisuje wyłącznie ``set_check``; odczyt niczego nie zapisuje.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.models.order_change_check import (
    ACTION_CHECKED,
    ACTION_UNCHECKED,
    OrderChangeCheck,
)
from app.models.order_change_event import OrderChangeEvent
from app.models.order_mail import OrderMailDocument
from app.models.user import User
from app.schemas.finance_order_changes import (
    OrderChangeItem,
    OrderChangesResponse,
    OrderChangesTabSummary,
    OrderHistoryEntry,
    OrderItemCheck,
    OrderPdfRef,
    SupersededCheck,
)
from app.services import finance_order_pdfs
from app.services.finance_order_changes import (
    ORDER_CHANGES_TABS,
    OrderChangesTab,
    _change_description,
    _fmt_date,
    _rate,
)
from app.services.order_facts import effective_end_expr, effective_start_expr

# Lista pól odpowiedzi z pozycjami każdej podzakładki.
_TAB_FIELDS: dict[str, str] = {
    "changes": "changes",
    "entries": "entries",
    "exits": "exits",
    "ending": "ending_orders",
    "gaps": "gaps",
}

# Zmiana wprowadzona przez automat maila zamówień zapisuje się w dzienniku
# bez osoby. Wpis dziennika i zastosowanie dokumentu z maila dzieli zwykle
# kilka sekund — okno 10 minut wiąże je bez łapania późniejszych edycji.
_MAIL_MATCH_WINDOW = timedelta(minutes=10)
ORDER_MAIL_LABEL = "zamowienia@b2bnetwork.pl"


def _order_state(status: Optional[str], start, cost, revenue) -> str:
    """Stan nowego zamówienia w kluczu pozycji.

    Dziennik zmian celowo pomija szkice (``order_change_audit``) i pierwsze
    wpisanie stawki, więc uzupełnienie i aktywacja szkicu nie dają żadnego
    wpisu. Bez stanu w kluczu pozycja odhaczona na pustym szkicu zostałaby
    „Zrobione" z kwotami, których Finanse nie widziały. Zamówienie żywe niesie
    tylko start — jego zmiany stawek mają własne pozycje z dziennika, a odcisk
    stawek policzyłby tę samą zmianę dwa razy.
    """

    begin = start.isoformat() if start is not None else "-"
    if status == "draft":
        return f"draft:{begin}:{cost if cost is not None else '-'}:{revenue if revenue is not None else '-'}"
    return f"live:{begin}"


def item_key(tab: str, item) -> str:
    """Klucz pozycji — ten sam w odczycie, odhaczeniu i historii."""

    if tab == "changes":
        if item.event_id is not None:
            return f"chg:ev:{item.event_id}"
        state = _order_state(
            item.order_status, item.start_date, item.rate_cost, item.rate_revenue
        )
        return f"chg:{item.kind}:{item.order_id}:{state}"
    if tab == "entries":
        state = _order_state(
            item.status, item.start_date, item.rate_cost, item.rate_revenue
        )
        return f"entry:{item.order_id}:{state}"
    if tab == "exits":
        return f"exit:{item.order_id}:{item.end_date.isoformat()}"
    if tab == "ending":
        # Bez werdyktu: „kończy się" przechodzi w „brak kolejnego" samym
        # upływem daty — to nie jest nowa zmiana do rozliczenia.
        return f"ending:{item.order_id}:{item.end_date.isoformat()}"
    return f"gap:{item.gap_id}:{item.status}"


def item_summary(tab: str, item) -> str:
    """Opis pozycji zapisywany przy odhaczeniu (historia bez bieżącego stanu)."""

    if tab == "changes":
        title, before, after = _change_description(item)
        text = f"{title}: {before} → {after}"
    elif tab == "entries":
        text = f"Nowe zamówienie od {_fmt_date(item.start_date)}"
    elif tab == "exits":
        text = f"Zejście: koniec {_fmt_date(item.end_date)} — {item.verdict_label}"
    elif tab == "ending":
        text = f"Koniec zamówienia {_fmt_date(item.end_date)} — {item.verdict_label}"
    else:
        text = (
            f"Brak kolejnego zamówienia po {_fmt_date(item.ended_on)} "
            f"(wykryto {_fmt_date(item.detected_on)})"
        )
    return text[:400]


def iter_items(response: OrderChangesResponse) -> Iterable[tuple[str, object]]:
    for tab in ORDER_CHANGES_TABS:
        for item in getattr(response, _TAB_FIELDS[tab]):
            yield tab, item


@dataclass(frozen=True)
class CheckState:
    action: str
    by_name: str
    at: datetime

    def as_done(self) -> Optional[OrderItemCheck]:
        if self.action != ACTION_CHECKED:
            return None
        return OrderItemCheck(by_name=self.by_name, at=self.at)


async def _latest_by_key(db: AsyncSession, *where) -> dict[str, CheckState]:
    rows = (
        await db.execute(
            select(
                OrderChangeCheck.item_key,
                OrderChangeCheck.action,
                OrderChangeCheck.user_name,
                OrderChangeCheck.created_at,
            )
            .where(*where)
            .distinct(OrderChangeCheck.item_key)
            .order_by(OrderChangeCheck.item_key, OrderChangeCheck.id.desc())
        )
    ).all()
    return {
        row.item_key: CheckState(row.action, row.user_name or "—", row.created_at)
        for row in rows
    }


async def latest_states(db: AsyncSession, keys: Iterable[str]) -> dict[str, CheckState]:
    wanted = sorted(set(keys))
    if not wanted:
        return {}
    return await _latest_by_key(db, OrderChangeCheck.item_key.in_(wanted))


async def _superseded(
    db: AsyncSession, year: int, month: int, current_keys: set[str]
) -> list[SupersededCheck]:
    """Odhaczone pozycje miesiąca, których nie ma już w bieżącym widoku."""

    rows = (
        await db.execute(
            select(OrderChangeCheck)
            .where(
                OrderChangeCheck.period_year == year,
                OrderChangeCheck.period_month == month,
            )
            .distinct(OrderChangeCheck.item_key)
            .order_by(OrderChangeCheck.item_key, OrderChangeCheck.id.desc())
        )
    ).scalars()
    result = [
        SupersededCheck(
            item_key=row.item_key,
            tab=row.tab,
            order_id=row.order_id,
            order_group_id=row.order_group_id,
            summary=row.summary,
            done=OrderItemCheck(by_name=row.user_name or "—", at=row.created_at),
        )
        for row in rows
        if row.action == ACTION_CHECKED and row.item_key not in current_keys
    ]
    return sorted(result, key=lambda item: item.done.at)


async def _order_meta(db: AsyncSession, order_ids: set[int]) -> dict[int, tuple]:
    """Okres, autor i chwila założenia zamówień: ``id → (created_at, autor, start, koniec)``."""

    if not order_ids:
        return {}
    start = effective_start_expr()
    end = effective_end_expr()
    rows = (
        await db.execute(
            select(
                ClientOrder.id,
                ClientOrder.created_at,
                User.name,
                start.label("start"),
                end.label("end"),
            )
            .select_from(ClientOrder)
            .outerjoin(
                ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id
            )
            .outerjoin(User, User.id == ClientOrder.created_by_user_id)
            .where(ClientOrder.id.in_(sorted(order_ids)))
        )
    ).all()
    return {row.id: (row.created_at, row.name, row.start, row.end) for row in rows}


async def _group_periods(db: AsyncSession, group_ids: set[int]) -> dict[int, tuple]:
    if not group_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ClientOrderGroup.id,
                ClientOrderGroup.start_date,
                ClientOrderGroup.end_date,
            ).where(ClientOrderGroup.id.in_(sorted(group_ids)))
        )
    ).all()
    return {row.id: (row.start_date, row.end_date) for row in rows}


async def _mail_applications(
    db: AsyncSession, order_ids: set[int], group_ids: set[int]
) -> tuple[dict[int, list[datetime]], dict[int, list[datetime]]]:
    """Kiedy dokumenty z maila zamówień zostały zastosowane do zamówień i grup."""

    if not order_ids and not group_ids:
        return {}, {}
    conditions = []
    if order_ids:
        conditions.append(OrderMailDocument.applied_order_id.in_(sorted(order_ids)))
    if group_ids:
        conditions.append(OrderMailDocument.applied_group_id.in_(sorted(group_ids)))
    rows = (
        await db.execute(
            select(
                OrderMailDocument.applied_order_id,
                OrderMailDocument.applied_group_id,
                OrderMailDocument.applied_at,
            ).where(or_(*conditions), OrderMailDocument.applied_at.is_not(None))
        )
    ).all()
    by_order: dict[int, list[datetime]] = {}
    by_group: dict[int, list[datetime]] = {}
    for row in rows:
        if row.applied_order_id is not None:
            by_order.setdefault(row.applied_order_id, []).append(row.applied_at)
        if row.applied_group_id is not None:
            by_group.setdefault(row.applied_group_id, []).append(row.applied_at)
    return by_order, by_group


def _near(moments: list[datetime], at: Optional[datetime]) -> bool:
    if at is None:
        return False
    return any(abs(moment - at) <= _MAIL_MATCH_WINDOW for moment in moments)


def _pdf_ref(entry: finance_order_pdfs.OrderPdfEntry) -> OrderPdfRef:
    return OrderPdfRef(
        kind=entry.kind,
        id=entry.id,
        month=entry.start.strftime("%Y-%m"),
        client_id=entry.client_id,
        download_name=entry.download_name,
    )


async def decorate(
    db: AsyncSession,
    response: OrderChangesResponse,
    *,
    can_check: bool,
) -> OrderChangesResponse:
    """Klucze, stany odhaczeń, okres zamówienia, PDF i autor każdej pozycji.

    Wołać na PEŁNYM audycie (przed filtrami widoku) — inaczej pozycje
    ukryte filtrem wyglądałyby jak odhaczenia, które zniknęły.
    """

    items = list(iter_items(response))
    keys = {id(item): item_key(tab, item) for tab, item in items}
    states = await latest_states(db, keys.values())
    superseded = await _superseded(
        db, response.period.year, response.period.month, set(keys.values())
    )

    order_ids = {item.order_id for _, item in items if item.order_id is not None}
    group_ids = {
        item.order_group_id for _, item in items if item.order_group_id is not None
    }
    order_meta = await _order_meta(db, order_ids)
    group_periods = await _group_periods(db, group_ids)
    order_pdfs, group_pdfs = await finance_order_pdfs.entries_for(
        db, order_ids=order_ids, group_ids=group_ids
    )
    mail_orders, mail_groups = await _mail_applications(db, order_ids, group_ids)

    def decorated(tab: str, item):
        key = keys[id(item)]
        state = states.get(key)
        update: dict = {"item_key": key, "done": state.as_done() if state else None}

        meta = order_meta.get(item.order_id) if item.order_id is not None else None
        if meta is not None:
            update["order_start"], update["order_end"] = meta[2], meta[3]
        elif item.order_group_id is not None:
            period = group_periods.get(item.order_group_id)
            if period is not None:
                update["order_start"], update["order_end"] = period

        entry = (
            order_pdfs.get(item.order_id) if item.order_id is not None else None
        ) or (
            group_pdfs.get(item.order_group_id)
            if item.order_group_id is not None
            else None
        )
        update["pdf"] = _pdf_ref(entry) if entry is not None else None

        mail_moments = [
            *mail_orders.get(item.order_id or 0, ()),
            *mail_groups.get(item.order_group_id or 0, ()),
        ]
        if isinstance(item, OrderChangeItem) and item.event_id is not None:
            from_mail = item.source == "system" and _near(
                mail_moments, item.occurred_at
            )
            update.update(
                entered_at=item.occurred_at,
                entered_by=item.author_name,
                entered_automatically=item.source == "system",
                from_order_mail=from_mail,
            )
        elif tab in ("changes", "entries") and meta is not None:
            # Nowe zamówienie: autor i chwila założenia zamówienia.
            created_at, creator = meta[0], meta[1]
            from_mail = bool(mail_moments) and creator is None
            update.update(
                entered_at=created_at,
                entered_by=creator,
                entered_automatically=creator is None,
                from_order_mail=from_mail,
            )
        return item.model_copy(update=update)

    lists = {
        field: [decorated(tab, item) for item in getattr(response, field)]
        for tab, field in _TAB_FIELDS.items()
    }
    return response.model_copy(
        update={**lists, "can_check": can_check, "superseded": superseded}
    )


def find_item(response: OrderChangesResponse, key: str):
    """``(zakładka, pozycja)`` o danym kluczu albo ``None``."""

    for tab, item in iter_items(response):
        if item_key(tab, item) == key:
            return tab, item
    return None


async def set_check(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    tab: str,
    item,
    done: bool,
    user: User,
) -> Optional[OrderItemCheck]:
    """Zapisuje odhaczenie albo cofnięcie. Ten sam stan = brak nowego wpisu.

    Blokada doradcza na kluczu szereguje dwa równoczesne kliknięcia — bez niej
    obie osoby odczytałyby „nie odhaczone" i dopisały dwa odhaczenia.
    """

    key = item_key(tab, item)
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
    current = (await latest_states(db, (key,))).get(key)
    currently_done = current is not None and current.action == ACTION_CHECKED
    if currently_done == done:
        return current.as_done() if current else None
    row = OrderChangeCheck(
        item_key=key,
        tab=tab,
        period_year=year,
        period_month=month,
        order_id=item.order_id,
        order_group_id=item.order_group_id,
        client_id=item.client_id,
        summary=item_summary(tab, item),
        action=ACTION_CHECKED if done else ACTION_UNCHECKED,
        user_id=user.id,
        user_name=user.name or user.email or "—",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row, attribute_names=["created_at"])
    return OrderItemCheck(by_name=row.user_name, at=row.created_at) if done else None


async def tab_summary(
    db: AsyncSession, response: OrderChangesResponse
) -> dict[str, OrderChangesTabSummary]:
    items = list(iter_items(response))
    states = await latest_states(db, (item_key(tab, item) for tab, item in items))
    summary = {tab: [0, 0] for tab in ORDER_CHANGES_TABS}
    for tab, item in items:
        state = states.get(item_key(tab, item))
        summary[tab][0] += 1
        if state is None or state.action != ACTION_CHECKED:
            summary[tab][1] += 1
    return {
        tab: OrderChangesTabSummary(total=total, todo=todo)
        for tab, (total, todo) in summary.items()
    }


def todo_orders(
    response: OrderChangesResponse, states: dict[str, CheckState]
) -> tuple[set[int], set[int]]:
    """Zamówienia i grupy z co najmniej jedną pozycją „Do zrobienia"."""

    orders: set[int] = set()
    groups: set[int] = set()
    for tab, item in iter_items(response):
        state = states.get(item_key(tab, item))
        if state is not None and state.action == ACTION_CHECKED:
            continue
        if item.order_id is not None:
            orders.add(item.order_id)
        if item.order_group_id is not None:
            groups.add(item.order_group_id)
    return orders, groups


def _event_summary(event: OrderChangeEvent) -> str:
    if event.field == "end_date":
        before = _fmt_date(event.old_date) if event.old_date else "bezterminowo"
        after = _fmt_date(event.new_date) if event.new_date else "bezterminowo"
        return f"Zmiana daty końca: {before} → {after}"
    label = (
        "Zmiana stawki kosztowej"
        if event.field == "rate_cost"
        else "Zmiana stawki przychodowej"
    )
    return (
        f"{label}: {_rate(event.old_amount, event.old_unit, event.currency)} → "
        f"{_rate(event.new_amount, event.new_unit, event.currency)}"
    )


async def order_history(
    db: AsyncSession,
    *,
    order_id: Optional[int],
    order_group_id: Optional[int],
) -> list[OrderHistoryEntry]:
    """Zmiany zamówienia (dziennik) i odhaczenia jego pozycji — najnowsze pierwsze.

    Linia zamówienia zbiorczego dostaje też zmiany CAŁEJ grupy (data końca
    zamówienia MD/kosztowego dotyczy każdej osoby na nim).
    """

    event_scope = []
    check_scope = []
    if order_id is not None:
        event_scope.append(OrderChangeEvent.order_id == order_id)
        check_scope.append(OrderChangeCheck.order_id == order_id)
    if order_group_id is not None:
        event_scope.append(
            and_(
                OrderChangeEvent.order_id.is_(None),
                OrderChangeEvent.order_group_id == order_group_id,
            )
        )
        check_scope.append(
            and_(
                OrderChangeCheck.order_id.is_(None),
                OrderChangeCheck.order_group_id == order_group_id,
            )
        )
    if not event_scope:
        return []
    events = (await db.scalars(select(OrderChangeEvent).where(or_(*event_scope)))).all()
    authors_ids = {e.created_by_user_id for e in events if e.created_by_user_id}
    authors = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(sorted(authors_ids)))
                )
            ).all()
        )
        if authors_ids
        else {}
    )
    checks = (await db.scalars(select(OrderChangeCheck).where(or_(*check_scope)))).all()
    history = [
        OrderHistoryEntry(
            at=event.created_at,
            kind="change",
            summary=_event_summary(event),
            by_name=authors.get(event.created_by_user_id),
            automatic=event.source == "system",
        )
        for event in events
    ] + [
        OrderHistoryEntry(
            at=check.created_at,
            kind=check.action,
            summary=check.summary,
            by_name=check.user_name or None,
        )
        for check in checks
    ]
    return sorted(history, key=lambda entry: entry.at, reverse=True)


__all__ = [
    "ORDER_MAIL_LABEL",
    "OrderChangesTab",
    "decorate",
    "find_item",
    "item_key",
    "item_summary",
    "latest_states",
    "order_history",
    "set_check",
    "tab_summary",
    "todo_orders",
]
