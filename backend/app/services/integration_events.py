"""Zdarzenia API integracyjnego v1: katalog, listener ORM, publikacja, kanał.

Skąd biorą się zdarzenia
------------------------
Listener ``after_flush`` (rejestrowany przy imporcie modułu — ``main.py``
importuje go raz) patrzy na obiekty zapisane w danym flushu i dopisuje wiersze
do ``integration_event_outbox`` przez połączenie bieżącej transakcji. Bez
edycji ekranów: każda ścieżka, która zapisuje przez ORM, daje zdarzenie.

* ``candidates`` INSERT → ``candidate.created``
* ``candidate_stages`` INSERT (każdy ruch karty to nowy wiersz etapu, także
  dodanie do rekrutacji) → ``card.moved``
* ``notes`` INSERT → ``note.created``
* ``jobs`` INSERT → ``recruitment.created``; zmiana ``status`` na ``closed`` →
  ``recruitment.closed``, z ``closed`` na inny → ``recruitment.reopened``
* ``application.received`` — dwie drogi zgłoszenia z linku rekrutacji:
  znany e-mail = INSERT ``application_submissions``; nowy e-mail (od 22.09)
  = nowy kandydat i proces, któremu ``open_process`` stempluje
  ``recruitment_processes.entry_source = 'application'`` (UPDATE po INSERT-cie
  procesu). Proces nie daje zdarzenia, gdy w sesji jest zgłoszenie tej
  rekrutacji (to ono niesie zdarzenie — także przy rozpatrzeniu zgłoszenia);
  w jednym flushu jedno zdarzenie na parę (kandydat, rekrutacja)
* ``order_change_events`` INSERT (dziennik ``order_change_audit``) → ``order.changed``
* ``contracts`` zmiana ``status`` → ``contract.status_changed``
* ``md_consumption_imports`` INSERT → ``md_import.created``
* ``invoices`` INSERT → ``invoice.created``; zmiana pól → ``invoice.updated``
* ``leave.approved`` / ``leave.cancelled`` — z wiersza śladu
  ``hr_audit_events`` (INSERT), nie z ``leave_requests``: decyzje o wniosku
  idą warunkowym ``UPDATE … WHERE status = …`` (Core, flush ich nie widzi),
  a każda ma wiersz śladu zapisany przez ORM w tej samej transakcji — jak
  ``order.changed`` z dziennika. ``leave.approved`` = akceptacja, wniosek
  zatwierdzony od razu (L4) albo wpis za pracownika; ``leave.cancelled`` =
  anulowanie wniosku, który był zatwierdzony (oczekujący nie był
  nieobecnością). Import z Compassa śladu nie pisze, więc zdarzeń nie daje.
  Rodzaju nieobecności w ``refs`` nie ma NIGDY (D6), choć ślad go niesie
* ``equipment_assignments`` INSERT z protokołem wydania → ``equipment.issued``
  (import arkusza recepcji zakłada wydania bez protokołu — to stan
  początkowy, nie wydanie); ustawienie ``returned_at`` → ``equipment.returned``

Zmiany robione hurtowym ``UPDATE`` (Core, z pominięciem flusha — np. nocne
przejście kontraktów ``active`` → ``ending`` w ``contract_alerts``) zdarzeń
nie dają.

Bezpieczeństwo zapisu biznesowego
---------------------------------
* Błąd przy BUDOWIE zdarzenia (Python) jest logowany i pomijany per obiekt —
  zmiana biznesowa idzie dalej.
* Zapis do poczekalni idzie w SAVEPOINT-cie. Błąd bazy (np. brak tabeli, gdy
  migracja nie weszła) wycofuje tylko savepoint: transakcja zostaje zdrowa,
  zmiana biznesowa się zatwierdza, zdarzenia giną z logiem ERROR. Jeśli nie da
  się nawet wycofać savepointu (zerwane połączenie), wyjątek leci dalej — sesja
  i tak jest wtedy martwa, a połknięcie błędu dałoby mylący błąd przy commicie.

Kursor bez dziur
----------------
``publish_pending`` (pętla webhooków, co kilka sekund) przenosi zdarzenia
z poczekalni do ``integration_events`` pod blokadą doradczą, jedną transakcją
na partię. Kolejna partia startuje dopiero po zatwierdzeniu poprzedniej, więc
``id`` w kanale rośnie w kolejności widoczności — czytelnik, który widzi
``id = N``, widzi już każde mniejsze ``id``, które kiedykolwiek się pojawi.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Collection, Iterable, Optional

from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.integration_event import (
    EVENT_RETENTION_DAYS,
    IntegrationEvent,
    IntegrationEventOutbox,
)
from app.models.service_account import ServiceScope

logger = logging.getLogger(__name__)

# ── Katalog: typ zdarzenia → scope potrzebny, żeby je zobaczyć ────────────────

EVENT_TYPES: dict[str, str] = {
    "candidate.created": ServiceScope.candidates_read.value,
    "card.moved": ServiceScope.recruitments_read.value,
    "note.created": ServiceScope.notes_read.value,
    "recruitment.created": ServiceScope.recruitments_read.value,
    "recruitment.closed": ServiceScope.recruitments_read.value,
    "recruitment.reopened": ServiceScope.recruitments_read.value,
    "application.received": ServiceScope.applications_read.value,
    "order.changed": ServiceScope.orders_read.value,
    "contract.status_changed": ServiceScope.contracts_read.value,
    "md_import.created": ServiceScope.md_read.value,
    "invoice.created": ServiceScope.invoices_read.value,
    "invoice.updated": ServiceScope.invoices_read.value,
    "leave.approved": ServiceScope.absences_read.value,
    "leave.cancelled": ServiceScope.absences_read.value,
    "equipment.issued": ServiceScope.equipment_read.value,
    "equipment.returned": ServiceScope.equipment_read.value,
}

#: Zdarzenie próbne webhooka — nie trafia do kanału, ma ``id = 0``.
TEST_EVENT_TYPE = "webhook.test"

EVENT_SCOPES: frozenset[str] = frozenset(EVENT_TYPES.values())


def visible_types(scopes: Collection[str]) -> list[str]:
    """Typy zdarzeń, które widzi klucz o danych scope'ach (efektywnych)."""
    return [name for name, scope in EVENT_TYPES.items() if scope in scopes]


# ── Budowa zdarzeń z obiektów flusha ──────────────────────────────────────────

_CLOSED = "closed"
_APPLICATION_ENTRY = "application"
_UNKNOWN = object()


def _plain(value: Any) -> Any:
    """Enum → jego wartość; reszta bez zmian (refs to JSON)."""
    return getattr(value, "value", value)


def _row(event_type: str, refs: dict[str, Any]) -> dict[str, Any]:
    return {"type": event_type, "scope": EVENT_TYPES[event_type], "refs": refs}


def _values(obj: Any, *keys: str) -> dict[str, Any]:
    """Wartości kolumn wprost ze stanu obiektu — bez leniwego doczytywania.

    W ``after_flush`` klucz główny nowego wiersza i klucze obce (także
    ustawione relacją) są już w stanie obiektu; czego tam nie ma, dostaje
    ``None`` zamiast zapytania do bazy w środku flusha.
    """
    state = inspect(obj).dict
    return {key: _plain(state.get(key)) for key in keys}


def _change(obj: Any, key: str) -> Optional[tuple[Any, Any]]:
    """``(stara, nowa)`` wartość atrybutu z historii flusha albo ``None``.

    Stara wartość nieznana (atrybut ustawiony bez wcześniejszego odczytu) =
    ``_UNKNOWN``. Ustawienie tej samej wartości nie jest zmianą.
    """
    history = inspect(obj).attrs[key].history
    if not history.added:
        return None
    new = _plain(history.added[0])
    old = _plain(history.deleted[0]) if history.deleted else _UNKNOWN
    if old is not _UNKNOWN and old == new:
        return None
    return old, new


def _has_column_changes(obj: Any) -> bool:
    state = inspect(obj)
    return any(
        state.attrs[key].history.has_changes()
        for key in state.mapper.column_attrs.keys()
    )


def _created_events(obj: Any, table: str) -> list[dict[str, Any]]:
    if table == "candidates":
        return [_row("candidate.created", {"candidate_id": _values(obj, "id")["id"]})]
    if table == "candidate_stages":
        v = _values(obj, "id", "candidate_id", "job_id", "stage")
        return [
            _row(
                "card.moved",
                {
                    "candidate_id": v["candidate_id"],
                    "job_id": v["job_id"],
                    "stage": v["stage"],
                    "stage_entry_id": v["id"],
                },
            )
        ]
    if table == "notes":
        v = _values(obj, "id", "candidate_id", "job_id", "contract_id")
        return [
            _row(
                "note.created",
                {
                    "note_id": v["id"],
                    "candidate_id": v["candidate_id"],
                    "job_id": v["job_id"],
                    "contract_id": v["contract_id"],
                },
            )
        ]
    if table == "jobs":
        return [_row("recruitment.created", {"job_id": _values(obj, "id")["id"]})]
    if table == "application_submissions":
        v = _values(obj, "id", "job_id", "matched_candidate_id")
        return [
            _row(
                "application.received",
                {
                    "application_id": v["id"],
                    "candidate_id": v["matched_candidate_id"],
                    "job_id": v["job_id"],
                    "stage_id": None,
                },
            )
        ]
    if table == "recruitment_processes":
        if _values(obj, "entry_source")["entry_source"] != _APPLICATION_ENTRY:
            return []
        return _process_application(obj)
    if table == "order_change_events":
        v = _values(
            obj, "id", "order_id", "order_group_id", "contract_id", "client_id", "field"
        )
        return [
            _row(
                "order.changed",
                {
                    "order_change_id": v["id"],
                    "order_id": v["order_id"],
                    "order_group_id": v["order_group_id"],
                    "contract_id": v["contract_id"],
                    "client_id": v["client_id"],
                    "field": v["field"],
                },
            )
        ]
    if table == "md_consumption_imports":
        v = _values(obj, "id", "period_month")
        return [
            _row(
                "md_import.created",
                {"md_import_id": v["id"], "period_month": v["period_month"]},
            )
        ]
    if table == "invoices":
        v = _values(obj, "id", "contract_id", "status")
        return [
            _row(
                "invoice.created",
                {
                    "invoice_id": v["id"],
                    "contract_id": v["contract_id"],
                    "status": v["status"],
                },
            )
        ]
    if table == "hr_audit_events":
        return _leave_events(obj)
    if table == "equipment_assignments":
        if _values(obj, "issue_protocol_id")["issue_protocol_id"] is None:
            return []
        return [_row("equipment.issued", _assignment_refs(obj))]
    return []


#: Wpisy śladu, po których wniosek jest zatwierdzony: akceptacja, nieobecność
#: zatwierdzona od razu (``absence_reported``) i wpis za pracownika.
_LEAVE_APPROVED_ACTIONS = frozenset(
    {"leave_approved", "absence_reported", "leave_entered_on_behalf"}
)
_APPROVED = "approved"


def _leave_events(obj: Any) -> list[dict[str, Any]]:
    """Zdarzenie nieobecności z wiersza śladu HR — daty i osoba, bez rodzaju."""
    v = _values(obj, "entity_type", "entity_id", "action", "subject_user_id")
    if v["entity_type"] != "leave_request":
        return []
    details = _values(obj, "details")["details"]
    details = details if isinstance(details, dict) else {}
    if v["action"] in _LEAVE_APPROVED_ACTIONS and details.get("status") == _APPROVED:
        event_type = "leave.approved"
    elif (
        v["action"] == "leave_cancelled" and details.get("previous_status") == _APPROVED
    ):
        event_type = "leave.cancelled"
    else:
        return []
    return [
        _row(
            event_type,
            {
                "leave_request_id": v["entity_id"],
                "user_id": v["subject_user_id"],
                "start_date": details.get("start_date"),
                "end_date": details.get("end_date"),
            },
        )
    ]


#: Kolumna posiadacza wydania → rodzaj w ``refs`` (CHECK: dokładnie jedna).
_HOLDER_COLUMNS = (
    ("user_id", "user"),
    ("contract_id", "contract"),
    ("external_person_id", "external"),
    ("academy_application_id", "academy_application"),
)


def _assignment_refs(obj: Any) -> dict[str, Any]:
    v = _values(obj, "id", "item_id", *(column for column, _ in _HOLDER_COLUMNS))
    kind, holder_id = next(
        (
            (kind, v[column])
            for column, kind in _HOLDER_COLUMNS
            if v[column] is not None
        ),
        (None, None),
    )
    return {
        "assignment_id": v["id"],
        "item_id": v["item_id"],
        "holder_kind": kind,
        "holder_id": holder_id,
    }


def _process_application(obj: Any) -> list[dict[str, Any]]:
    v = _values(obj, "candidate_id", "job_id", "legacy_current_candidate_stage_id")
    return [
        _row(
            "application.received",
            {
                "application_id": None,
                "candidate_id": v["candidate_id"],
                "job_id": v["job_id"],
                "stage_id": v["legacy_current_candidate_stage_id"],
            },
        )
    ]


def _updated_events(obj: Any, table: str) -> list[dict[str, Any]]:
    if table == "recruitment_processes":
        # ``transition_process`` zakłada proces, flushuje, a źródło wejścia
        # stempluje dopiero potem — zgłoszenie z nowym e-mailem to UPDATE.
        change = _change(obj, "entry_source")
        if change is None or change[1] != _APPLICATION_ENTRY:
            return []
        return _process_application(obj)
    if table == "jobs":
        change = _change(obj, "status")
        if change is None:
            return []
        old, new = change
        job_id = _values(obj, "id")["id"]
        if new == _CLOSED:
            return [_row("recruitment.closed", {"job_id": job_id})]
        # Wznowienie tylko przy pewnym „było zamknięte” — nieznany stan
        # poprzedni nie wystarcza, żeby ogłosić ponowne otwarcie.
        if old == _CLOSED:
            return [_row("recruitment.reopened", {"job_id": job_id})]
        return []
    if table == "contracts":
        change = _change(obj, "status")
        if change is None:
            return []
        old, new = change
        return [
            _row(
                "contract.status_changed",
                {
                    "contract_id": _values(obj, "id")["id"],
                    "status": new,
                    "previous_status": None if old is _UNKNOWN else old,
                },
            )
        ]
    if table == "invoices":
        if not _has_column_changes(obj):
            return []
        v = _values(obj, "id", "contract_id", "status")
        return [
            _row(
                "invoice.updated",
                {
                    "invoice_id": v["id"],
                    "contract_id": v["contract_id"],
                    "status": v["status"],
                },
            )
        ]
    if table == "equipment_assignments":
        # Zwrot = ``returned_at`` ustawione na wydaniu, które było otwarte;
        # poprawka daty już zwróconego wydania zwrotem nie jest.
        change = _change(obj, "returned_at")
        if change is None or change[1] is None:
            return []
        if change[0] is not _UNKNOWN and change[0] is not None:
            return []
        return [_row("equipment.returned", _assignment_refs(obj))]
    return []


_CREATED_TABLES = frozenset(
    {
        "candidates",
        "candidate_stages",
        "notes",
        "jobs",
        "application_submissions",
        "order_change_events",
        "md_consumption_imports",
        "invoices",
        "recruitment_processes",
        "hr_audit_events",
        "equipment_assignments",
    }
)
_UPDATED_TABLES = frozenset(
    {"jobs", "contracts", "invoices", "recruitment_processes", "equipment_assignments"}
)


def _submission_jobs(objects: Iterable[Any]) -> set[tuple[Any, Any]]:
    """``(job_id, kandydat)`` zgłoszeń z linku obecnych w sesji.

    Także przegląd AI (0404) zgłoszenia znanego e-maila: pętla otwiera proces
    z wierszem ``application_screenings`` w sesji, a zdarzenie poszło już przy
    zapisie zgłoszenia.
    """
    pairs: set[tuple[Any, Any]] = set()
    for obj in objects:
        table = getattr(type(obj), "__tablename__", None)
        if table == "application_submissions":
            v = _values(obj, "job_id", "matched_candidate_id")
            pairs.add((v["job_id"], v["matched_candidate_id"]))
        elif table == "application_screenings":
            v = _values(obj, "job_id", "candidate_id", "submission_id")
            if v["submission_id"] is not None:
                pairs.add((v["job_id"], v["candidate_id"]))
    return pairs


def _dedupe_applications(
    rows: list[dict[str, Any]], submissions: set[tuple[Any, Any]]
) -> list[dict[str, Any]]:
    """Jedno ``application.received`` na zgłoszenie.

    Zdarzenie z procesu (``application_id`` puste) odpada, gdy w sesji jest
    zgłoszenie tej rekrutacji dla tej osoby albo jeszcze bez dopasowanej
    osoby; w jednym flushu zostaje pierwsze zdarzenie pary (kandydat, rekrutacja).
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for row in rows:
        if row["type"] != "application.received":
            out.append(row)
            continue
        refs = row["refs"]
        pair = (refs.get("candidate_id"), refs.get("job_id"))
        if refs.get("application_id") is None and (
            (pair[1], pair[0]) in submissions or (pair[1], None) in submissions
        ):
            continue
        if pair[0] is not None:
            if pair in seen:
                continue
            seen.add(pair)
        out.append(row)
    return out


def collect_flush_events(
    new: Iterable[Any],
    dirty: Iterable[Any],
    *,
    session_objects: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    """Wiersze poczekalni dla obiektów nowych i zmienionych w jednym flushu.

    ``session_objects`` — pozostałe obiekty sesji (mapa tożsamości); służą
    wyłącznie do rozpoznania, że proces otwiera rozpatrywane zgłoszenie.
    Błąd przy jednym obiekcie nie zabiera zdarzeń pozostałym ani zmiany
    biznesowej — log bez wartości (same nazwy), obiekt pominięty.
    """
    new = list(new)
    dirty = list(dirty)
    rows: list[dict[str, Any]] = []
    for objects, tables, build in (
        (new, _CREATED_TABLES, _created_events),
        (dirty, _UPDATED_TABLES, _updated_events),
    ):
        for obj in objects:
            table = getattr(type(obj), "__tablename__", None)
            if table not in tables:
                continue
            try:
                rows.extend(build(obj, table))
            except Exception as exc:  # noqa: BLE001 — zdarzenie nie blokuje zmiany
                logger.error(
                    "integration_events: pominięte zdarzenie dla %s (%s)",
                    table,
                    type(exc).__name__,
                )
    if any(row["type"] == "application.received" for row in rows):
        try:
            rows = _dedupe_applications(
                rows, _submission_jobs([*new, *dirty, *session_objects])
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "integration_events: pominięte deduplikowanie zgłoszeń (%s)",
                type(exc).__name__,
            )
    return rows


def write_outbox(connection: Connection, rows: list[dict[str, Any]]) -> bool:
    """Dopisz wiersze do poczekalni w SAVEPOINT-cie bieżącej transakcji.

    Zwraca, czy zapis wszedł. Błąd bazy przy samym INSERT-cie wycofuje tylko
    savepoint (zmiana biznesowa zostaje); błąd wycofania leci dalej.
    """
    savepoint = connection.begin_nested()
    try:
        connection.execute(IntegrationEventOutbox.__table__.insert(), rows)
    except SQLAlchemyError as exc:
        savepoint.rollback()
        logger.error(
            "integration_events: zapis %d zdarzeń do poczekalni nieudany (%s) — "
            "zmiana biznesowa zostaje, zdarzenia pominięte",
            len(rows),
            type(exc).__name__,
        )
        return False
    savepoint.commit()
    return True


class _LazyIdentityMap:
    """Obiekty mapy tożsamości czytane dopiero, gdy flush ma zgłoszenie do
    sprawdzenia — zwykły flush nie płaci za przejście po całej sesji."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def __iter__(self):
        return iter(list(self._session.identity_map.values()))


@event.listens_for(Session, "after_flush")
def _emit_integration_events(session: Session, _flush_context: Any) -> None:
    # W ``after_flush`` listy new/dirty i historia atrybutów są jeszcze sprzed
    # flusha, a klucze główne nowych wierszy już nadane.
    rows = collect_flush_events(
        session.new, session.dirty, session_objects=_LazyIdentityMap(session)
    )
    if rows:
        write_outbox(session.connection(), rows)


# ── Publikacja do kanału (pętla w tle) ────────────────────────────────────────

_PUBLISH_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"integration_events:publish").digest()[:8], "big", signed=True
)
PUBLISH_BATCH = 1000
_PUBLISH_MAX_BATCHES = 20

_MOVE_SQL = text(
    """
    WITH moved AS (
        DELETE FROM integration_event_outbox
        WHERE id IN (
            SELECT id FROM integration_event_outbox ORDER BY id LIMIT :batch
        )
        RETURNING id, type, scope, refs, occurred_at
    )
    INSERT INTO integration_events (type, scope, refs, occurred_at)
    SELECT type, scope, refs, occurred_at FROM moved ORDER BY id
    RETURNING id
    """
)


async def publish_pending(db: AsyncSession, *, batch: int = PUBLISH_BATCH) -> int:
    """Przenieś zatwierdzone zdarzenia z poczekalni do kanału. Zwraca liczbę.

    Każda partia = osobna transakcja pod ``pg_try_advisory_xact_lock``: gdy
    publikuje inny proces (np. stary kontener w trakcie wdrożenia), ten bieg
    nic nie robi. Blokada zwalnia się dopiero PO tym, jak zatwierdzona partia
    jest widoczna, więc kolejna partia dostaje większe ``id`` i widać ją później.
    """
    published = 0
    for _ in range(_PUBLISH_MAX_BATCHES):
        locked = await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": _PUBLISH_LOCK_KEY},
        )
        if not locked:
            await db.rollback()
            break
        moved = len((await db.execute(_MOVE_SQL, {"batch": batch})).fetchall())
        await db.commit()
        published += moved
        if moved < batch:
            break
    return published


async def purge_expired(db: AsyncSession, *, now: Optional[datetime] = None) -> int:
    """Retencja kanału: zdarzenia opublikowane ponad 30 dni temu znikają.

    ``published_at`` rośnie razem z ``id``, więc cięcie idzie zakresem kursora
    (indeks klucza głównego) — od pierwszego „młodego” zdarzenia w dół.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=EVENT_RETENTION_DAYS)
    result = await db.execute(
        text(
            """
            DELETE FROM integration_events
            WHERE id < COALESCE(
                (SELECT id FROM integration_events
                 WHERE published_at >= :cutoff ORDER BY id LIMIT 1),
                (SELECT max(id) + 1 FROM integration_events)
            )
            """
        ),
        {"cutoff": cutoff},
    )
    await db.commit()
    return int(result.rowcount or 0)


# ── Odczyt kanału (trasa ``GET /events`` i webhooki) ──────────────────────────


def listed_jobs_clause():
    """Zdarzenie rekrutacji ukrytego albo usuniętego klienta nie istnieje dla
    klucza — tak jak ``GET /recruitments/{id}`` (404) i reszta tras v1
    (``jobs_register_base_clause``). Zdarzenia bez ``job_id`` przechodzą.
    Wspólne dla kanału (``read_feed``) i wysyłki webhooków; sprawdzane przy
    ODCZYCIE, więc klient ukryty później znika też z zaległości."""
    from sqlalchemy import Integer, cast, or_

    from app.api.jobs import jobs_register_base_clause
    from app.models.job import Job

    job_ref = IntegrationEvent.refs["job_id"].astext
    return or_(
        job_ref.is_(None),
        cast(job_ref, Integer).in_(select(Job.id).where(jobs_register_base_clause())),
    )


async def read_feed(
    db: AsyncSession,
    *,
    after: int,
    scopes: Collection[str],
    types: Optional[Collection[str]] = None,
    limit: int,
) -> tuple[list[IntegrationEvent], int, bool]:
    """Zdarzenia po kursorze, które widzi klucz: ``(zdarzenia, next_after, has_more)``.

    Górna granica (``max(id)``) jest czytana PRZED zdarzeniami — wszystko do
    niej jest już widoczne (patrz ``publish_pending``). Gdy strona nie jest
    pełna, ``next_after`` przeskakuje do tej granicy także przez zdarzenia
    niewidoczne dla klucza, żeby następne odpytanie nie skanowało ich znowu.
    """
    upper = await db.scalar(select(func.max(IntegrationEvent.id)))
    allowed = sorted(set(scopes) & EVENT_SCOPES)
    if upper is None or upper <= after or not allowed:
        return [], max(after, upper or 0), False
    query = select(IntegrationEvent).where(
        IntegrationEvent.id > after,
        IntegrationEvent.id <= upper,
        IntegrationEvent.scope.in_(allowed),
        listed_jobs_clause(),
    )
    if types:
        query = query.where(IntegrationEvent.type.in_(sorted(set(types))))
    rows = list(
        (
            await db.execute(query.order_by(IntegrationEvent.id).limit(limit + 1))
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_after = rows[-1].id if has_more else upper
    return rows, next_after, has_more


async def current_cursor(db: AsyncSession) -> int:
    """Najnowszy kursor kanału (0 = pusty) — start nowego webhooka."""
    return int(await db.scalar(select(func.max(IntegrationEvent.id))) or 0)


def event_payload(row: IntegrationEvent) -> dict[str, Any]:
    """Zdarzenie w kształcie kanału — ten sam w ``GET /events`` i w webhooku."""
    occurred = row.occurred_at
    return {
        "id": row.id,
        "type": row.type,
        "occurred_at": occurred.isoformat() if occurred is not None else None,
        "refs": dict(row.refs or {}),
    }


__all__ = [
    "EVENT_SCOPES",
    "EVENT_TYPES",
    "PUBLISH_BATCH",
    "TEST_EVENT_TYPE",
    "collect_flush_events",
    "current_cursor",
    "event_payload",
    "listed_jobs_clause",
    "publish_pending",
    "purge_expired",
    "read_feed",
    "visible_types",
    "write_outbox",
]
