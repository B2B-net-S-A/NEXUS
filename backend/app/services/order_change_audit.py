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
    # Waluta stawki: sama zmiana waluty (1000 PLN → 1000 EUR) to zmiana
    # pieniędzy, której dziennik do 24.09.2026 nie widział (N1).
    "currency",
    "rate_client_currency",
    "rate_candidate_currency",
)
_GROUP_FIELDS = ("status", "end_date")
#: Pola czytane przy budowie zdarzenia (poza śledzonymi) — zapamiętywane po
#: flushu, bo wycofany savepoint wygasza obiekt (FIN-CHG-3).
_CONTEXT_FIELDS = (
    *_ORDER_FIELDS,
    "order_group_id",
    "contract_id",
    "client_id",
    "currency",
    "rate_client_currency",
    "rate_candidate_currency",
)

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

    __slots__ = ("obj", "old", "flushed")

    def __init__(self, obj: object) -> None:
        self.obj = obj
        self.old: dict[str, Any] = {}
        #: Wartość po ostatnim flushu. Wycofany SAVEPOINT wygasza obiekty
        #: zmienione w jego trakcie — wtedy bieżąca wartość jest nieznana, a ta
        #: (odtworzona sprzed savepointu) nadal mówi, co zapisano wcześniej.
        self.flushed: dict[str, Any] = {}

    def copy(self) -> "_Snapshot":
        clone = _Snapshot(self.obj)
        clone.old = dict(self.old)
        clone.flushed = dict(self.flushed)
        return clone

    def current(self, key: str) -> Any:
        value = inspect(self.obj).dict.get(key, NO_VALUE)
        if value is NO_VALUE:
            return self.flushed.get(key, NO_VALUE)
        return value

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
        # ``md_rate_*`` to kanoniczne PLN/MD. Linia w walucie obcej zapisuje
        # zmianę stawki ŹRÓDŁOWEJ (``rate_*`` w walucie i jednostce linii) —
        # „PLN" przy kwocie przeliczonej z EUR mylił Finanse (S14).
        foreign_line = in_group and _currency(snap.current, currency_key) != "PLN"
        if in_group and not foreign_line:
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
        currency = _currency(snap.current, currency_key)
        old_currency = _currency(snap.initial, currency_key)
        if old == new and initial_unit == current_unit and old_currency == currency:
            continue
        events.append(
            {
                "field": field,
                "old_amount": old,
                "new_amount": new,
                "old_unit": initial_unit,
                "new_unit": current_unit,
                "currency": currency,
                "old_currency": old_currency,
            }
        )
    return events


def _currency(read: Any, key: str) -> str:
    """Waluta strony stawki (``rate_*_currency``, zapasowo ``currency``, PLN).

    Brak waluty to PLN — jak wszędzie w module zamówień. Bez tego
    uzupełnienie pustej waluty wartością „PLN" (normalizacja w PATCH) dawało
    fałszywą „zmianę stawki" o tej samej kwocie."""
    value = read(key)
    if value in (None, NO_VALUE):
        value = read("currency")
    if value in (None, NO_VALUE):
        return "PLN"
    return str(value).strip().upper() or "PLN"


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


@event.listens_for(Session, "after_flush")
def _remember_flushed_values(session: Session, _flush_context: object) -> None:
    for snap in (session.info.get(_PENDING_KEY) or {}).values():
        state = inspect(snap.obj).dict
        for key in (*snap.old, *_CONTEXT_FIELDS):
            if key in state:
                snap.flushed[key] = state[key]


# ── SAVEPOINT-y (audyt 22.09, FIN-CHG-3) ─────────────────────────────────────
# ``before_commit``/``after_commit``/``after_rollback`` odpalają się także dla
# transakcji ZAGNIEŻDŻONEJ. Dawniej wycofanie savepointu czyściło zapamiętane
# zmiany CAŁEJ transakcji (zmiana sprzed savepointu znikała z dziennika),
# a zatwierdzenie savepointu zapisywało stan pośredni. Teraz: savepoint
# zapamiętuje stan dziennika na starcie, wycofanie go odtwarza, a zapis
# i czyszczenie dzieją się wyłącznie w transakcji głównej.
_SAVEPOINTS_KEY = "order_change_audit.savepoints"


@event.listens_for(Session, "after_transaction_create")
def _remember_state_at_savepoint(session: Session, transaction: Any) -> None:
    if not getattr(transaction, "nested", False):
        return
    pending: dict = session.info.get(_PENDING_KEY) or {}
    session.info.setdefault(_SAVEPOINTS_KEY, {})[id(transaction)] = {
        key: snap.copy() for key, snap in pending.items()
    }


@event.listens_for(Session, "after_soft_rollback")
def _forget_after_rollback(session: Session, previous_transaction: Any) -> None:
    # Uwaga: ``after_transaction_end`` odpala się PRZED tym zdarzeniem, więc
    # zapamiętany stan savepointu zdejmujemy dopiero tutaj.
    if getattr(previous_transaction, "nested", False):
        saved = (session.info.get(_SAVEPOINTS_KEY) or {}).pop(
            id(previous_transaction), None
        )
        if saved is not None:
            session.info[_PENDING_KEY] = saved
        return
    session.info.pop(_PENDING_KEY, None)
    session.info.pop(_SAVEPOINTS_KEY, None)


@event.listens_for(Session, "before_commit")
def _record_order_changes(session: Session) -> None:
    # Zmiany, które nie przeszły jeszcze przez flush, też należą do tej
    # transakcji — commit sflushuje je dopiero po tym zdarzeniu.
    _capture(session)
    if session.in_nested_transaction():
        # Zatwierdzenie SAVEPOINT-u nie kończy transakcji — zmiany zapisze
        # commit główny (jedna zmiana na transakcję, nie na savepoint).
        return
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


@event.listens_for(Session, "after_commit")
def _forget_after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return
    # Flush wewnątrz commitu łapie te same obiekty jeszcze raz — już zapisane.
    session.info.pop(_PENDING_KEY, None)
    session.info.pop(_SAVEPOINTS_KEY, None)
