"""Zapis starej → nowej wartości przy każdej rozliczeniowej zmianie zamówienia.

Źródło podzakładki „Zmiany" (Finanse → Zmiany w zamówieniach). Listenery na
``Session`` łapią KAŻDY zapis zamówienia — endpoint, mail zamówień,
synchronizację kosztu z umowy, materializację przedłużeń — bez wymogu, żeby
nowy writer o tym pamiętał.

**Jedna zmiana na transakcję, nie na flush.** ``before_flush`` zapamiętuje
PIERWSZĄ starą wartość każdego pola (``committed_state`` — po flushu jest już
pusty), a wiersze powstają dopiero w ``before_commit`` jako różnica między
stanem z początku transakcji a stanem końcowym. Zapis per flush rejestrował
stan POŚREDNI: PATCH stawki kosztowej 100 → 120, po którym synchronizacja
z umową przywraca 100, dawał dwie „zmiany" autora zamiast żadnej.

**Filtr szumu** — Finanse chcą zmian ISTNIEJĄCYCH zamówień, nie wypełniania
formularzy:

* zamówienie, które na początku transakcji było szkicem albo anulowane, jest
  pomijane (uzupełnienie szkicu pokazują „Wejścia");
* pierwsze wpisanie stawki (stara ``None``) nie jest zmianą stawki;
* ta sama liczba w innej skali (``150`` vs ``150.000``) nie jest zmianą;
* data końca ``None`` → data JEST zmianą: zamówienie bezterminowe dostało
  koniec, a to wprost zmienia rozliczenia.

Świadomie poza zakresem: masowe ``update(ClientOrder)`` w skanerze
wygasania — zmienia wyłącznie status, a zakończenie pokazują „Zejścia".
Atrybut wygaszony w trakcie transakcji (``refresh``) nie ma wartości końcowej
w pamięci — takiej zmiany nie zapisujemy zamiast doczytywać w środku commitu
(``MissingGreenlet``).

Autora stempluje ``deps.get_authenticated_user`` w ``session.info`` (sesja
żądania jest współdzielona przez zależności FastAPI). Zapis bez zalogowanej
osoby — pętle w tle, poczta — ma źródło ``system``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.orm.base import NO_VALUE

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.order_change_event import (
    FIELD_END_DATE,
    FIELD_RATE_COST,
    FIELD_RATE_REVENUE,
    SOURCE_SYSTEM,
    SOURCE_USER,
    OrderChangeEvent,
)

ACTOR_INFO_KEY = "order_change_audit.actor_id"
_PENDING_KEY = "order_change_audit.pending"
MD_UNIT = "md"

_ORDER_FIELDS = (
    "status",
    "rate_candidate",
    "rate_client",
    "md_rate_cost",
    "md_rate_revenue",
    "rate_unit",
    "end_date",
)
_GROUP_FIELDS = ("status", "end_date")

# Grupy, których zmiana daty nie jest jeszcze zmianą obowiązującego
# zamówienia (odpowiednik szkicu zamówienia samodzielnego).
_INACTIVE_GROUP_STATUSES = frozenset({"draft"})


def stamp_actor(session_info: dict, user_id: Optional[int]) -> None:
    """Zapamiętaj zalogowaną osobę dla zdarzeń zapisanych w tej sesji."""

    if user_id is not None:
        session_info[ACTOR_INFO_KEY] = user_id


def _value(raw: Any) -> Any:
    return getattr(raw, "value", raw)


def _amount(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


class _Snapshot:
    """Obiekt z pierwszymi starymi wartościami pól z tej transakcji."""

    __slots__ = ("obj", "old")

    def __init__(self, obj: object) -> None:
        self.obj = obj
        self.old: dict[str, Any] = {}

    def current(self, key: str) -> Any:
        return inspect(self.obj).dict.get(key, NO_VALUE)

    def initial(self, key: str) -> Any:
        """Wartość z początku transakcji (bieżąca, gdy pole się nie zmieniło)."""
        return self.old[key] if key in self.old else self.current(key)

    def change(self, key: str) -> Optional[tuple[Any, Any]]:
        if key not in self.old:
            return None
        old, new = self.old[key], self.current(key)
        if old is NO_VALUE or new is NO_VALUE or old == new:
            return None
        return old, new


def _capture(session: Session) -> None:
    """Dopisz pierwsze stare wartości zmienionych pól zamówień i grup."""

    pending: Optional[dict] = None
    for obj in list(session.dirty):
        if isinstance(obj, ClientOrder):
            fields = _ORDER_FIELDS
        elif isinstance(obj, ClientOrderGroup):
            fields = _GROUP_FIELDS
        else:
            continue
        state = inspect(obj)
        if not state.identity:
            continue
        changed = [key for key in fields if key in state.committed_state]
        if not changed:
            continue
        if pending is None:
            pending = session.info.setdefault(_PENDING_KEY, {})
        snapshot = pending.get((type(obj), state.identity))
        if snapshot is None:
            snapshot = pending[(type(obj), state.identity)] = _Snapshot(obj)
        for key in changed:
            snapshot.old.setdefault(key, state.committed_state[key])


def _rate_events(snap: _Snapshot) -> list[dict[str, Any]]:
    """Zmiany stawek jednego zamówienia.

    Linia zamówienia MD/kosztowego rozlicza się w ``md_rate_*`` (za MD);
    zamówienie samodzielne w ``rate_candidate``/``rate_client`` z jednostką
    ``rate_unit``. Na samodzielnym ``md_rate_revenue`` jest wyłącznie
    lustrem ``rate_client`` — liczenie obu dałoby tę samą zmianę dwa razy.
    """

    events: list[dict[str, Any]] = []
    in_group = snap.current("order_group_id") not in (None, NO_VALUE)
    current_unit = _value(snap.current("rate_unit"))
    initial_unit = _value(snap.initial("rate_unit"))
    if current_unit is NO_VALUE or initial_unit is NO_VALUE:
        current_unit = initial_unit = None

    pairs = (
        (FIELD_RATE_COST, "rate_candidate", "md_rate_cost", "rate_candidate_currency"),
        (FIELD_RATE_REVENUE, "rate_client", "md_rate_revenue", "rate_client_currency"),
    )
    for field, legacy_key, md_key, currency_key in pairs:
        if in_group:
            md_change = snap.change(md_key)
            if md_change is not None:
                old, new = _amount(md_change[0]), _amount(md_change[1])
                if old is not None and new is not None and old != new:
                    events.append(
                        {
                            "field": field,
                            "old_amount": old,
                            "new_amount": new,
                            "old_unit": MD_UNIT,
                            "new_unit": MD_UNIT,
                            "currency": "PLN",
                        }
                    )
                continue
            # Linia bez stawek MD (starsze linie) rozlicza się stawką zwykłą.
            if snap.current(md_key) not in (None, NO_VALUE):
                continue

        old_raw, new_raw = snap.initial(legacy_key), snap.current(legacy_key)
        if old_raw is NO_VALUE or new_raw is NO_VALUE:
            continue
        old, new = _amount(old_raw), _amount(new_raw)
        if old is None or new is None:
            continue
        if old == new and initial_unit == current_unit:
            continue
        currency = snap.current(currency_key)
        if currency in (None, NO_VALUE):
            currency = snap.current("currency")
        events.append(
            {
                "field": field,
                "old_amount": old,
                "new_amount": new,
                "old_unit": initial_unit,
                "new_unit": current_unit,
                "currency": None if currency is NO_VALUE else currency,
            }
        )
    return events


def _end_date_event(snap: _Snapshot) -> list[dict[str, Any]]:
    change = snap.change("end_date")
    if change is None:
        return []
    return [{"field": FIELD_END_DATE, "old_date": change[0], "new_date": change[1]}]


def _events_for(snap: _Snapshot) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    obj = snap.obj
    identity = inspect(obj).identity[0]
    status = _value(snap.initial("status"))
    if isinstance(obj, ClientOrder):
        if status in (ClientOrderStatus.draft.value, ClientOrderStatus.cancelled.value):
            return {}, []
        base = {
            "order_id": identity,
            "order_group_id": snap.current("order_group_id"),
            "contract_id": snap.current("contract_id"),
            "client_id": snap.current("client_id"),
        }
        return base, _rate_events(snap) + _end_date_event(snap)
    if status in _INACTIVE_GROUP_STATUSES:
        return {}, []
    base = {
        "order_id": None,
        "order_group_id": identity,
        "contract_id": None,
        "client_id": snap.current("client_id"),
    }
    return base, _end_date_event(snap)


@event.listens_for(Session, "before_flush")
def _capture_before_flush(
    session: Session, _flush_context: object, _instances: object
) -> None:
    _capture(session)


@event.listens_for(Session, "before_commit")
def _record_order_changes(session: Session) -> None:
    # Zmiany, które nie przeszły jeszcze przez flush, też należą do tej
    # transakcji — commit sflushuje je dopiero po tym zdarzeniu.
    _capture(session)
    pending: dict = session.info.pop(_PENDING_KEY, None) or {}
    if not pending:
        return
    actor_id = session.info.get(ACTOR_INFO_KEY)
    source = SOURCE_USER if isinstance(actor_id, int) else SOURCE_SYSTEM
    for snap in pending.values():
        base, changes = _events_for(snap)
        for change in changes:
            base_values = {
                key: (None if value is NO_VALUE else value)
                for key, value in base.items()
            }
            session.add(
                OrderChangeEvent(
                    **base_values,
                    **change,
                    source=source,
                    created_by_user_id=actor_id if source == SOURCE_USER else None,
                )
            )


@event.listens_for(Session, "after_rollback")
def _forget_after_rollback(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)


@event.listens_for(Session, "after_commit")
def _forget_after_commit(session: Session) -> None:
    # Flush wewnątrz commitu łapie te same obiekty jeszcze raz — już zapisane.
    session.info.pop(_PENDING_KEY, None)
