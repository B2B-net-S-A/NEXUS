"""Znacznik „Pracuje u nas" — jedna reguła dla każdego ekranu (12.10.2026).

Do tej zmiany informację, że osoba u nas pracuje, pokazywał tylko profil
i jedna kolumna listy kandydatów; okna dodawania do rekrutacji, Tablica
i panel osoby jej nie miały. Każdy z tych ekranów czyta teraz ten sam wynik
:func:`build_markers`.

Reguła:

* **pracuje** — żywa umowa (``status ∈ {active, ending}``) ze startem nie
  później niż dziś albo bez daty startu (``current_employment.is_live_contract``);
* **zaczyna** — żywa umowa ze startem w przyszłości. Podpis w Generatorze
  aktywuje umowę od razu i przesuwa kartę na „Zatrudniony";
* **kończy** — do końca łańcucha zamówień bez kontynuacji zostało najwyżej
  ``ENDING_WITHOUT_CONTINUATION_DAYS`` dni. To reguła alertów Delivery
  (``order_continuation``): linie zamówień MD „kończą się" tylko u klientów
  z listy rozszerzonej, a aktywna linia MD z budżetem nie ma daty końca.

**Źródłem jest wyłącznie umowa** (decyzja Artura 17.10.2026): z umowy czyta
się też stawkę i termin dostępności, więc zatrudniony to ktoś z umową
w Kontraktach. Etap „Zatrudniony” bez umowy (do 17.10 liczony 12 miesięcy)
i ręczny konflikt ``current_employment`` („Oznacz jako zatrudnionego”) nie
dają znacznika. Karta „Zatrudniony” bez umowy mówi o tym sama
(``hire_contract_reminder``). Znacznik istnieje dokładnie wtedy, gdy stare
pole ``employment.state`` to ``employed_at_client`` — pilnuje tego test.

Data w znaczniku to wcześniejsza z dat: koniec łańcucha zamówień i data
końca umowy (ustawiana tylko przy zakończeniu — umowa B2B jest
bezterminowa); łańcuch, którego wszystkie zamówienia już się skończyły,
kończy się w ostatnim dniu ostatniego z nich (audyt 13.10.2026).

Znacznik nie niesie kwot i niczego nie blokuje (decyzja o konfliktach
z 17.09.2026: ostrzeżenie, nie blokada).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Collection, Iterable, Mapping, Optional, Sequence

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.schemas.candidate import (
    EmploymentFreeFromBasis,
    EmploymentMarker,
    EmploymentMarkerClient,
    EmploymentPhase,
)
from app.services.client_identity import (
    client_display_name,
    client_display_name_expression,
)
from app.services.current_employment import LIVE_CONTRACT_STATUSES
from app.services.order_alert_policy import extended_order_alert_client_ids
from app.services.order_continuation import (
    ENDING_ORDER_STATUSES,
    ENDING_WITHOUT_CONTINUATION_DAYS,
    order_ending_without_continuation,
)

logger = logging.getLogger(__name__)

#: Horyzont filtra listy „Kończy u nas w ciągu 60 dni".
ENDING_SOON_FILTER_DAYS = 60

#: Wpis „Do przepięcia” niezamknięty (otwarty albo w toku) — razem
#: z przekazaniem do front office daje „Wraca na rynek” (22.10.2026).
RETURNING_REDEPLOY_STATUSES: tuple[str, ...] = ("open", "in_progress")
#: Ryzyko odejścia to sygnał opieki, nie decyzja o powrocie na rynek.
NEVER_RETURNING_REASONS = frozenset({"attrition_risk"})

_PHASE_RANK: dict[str, int] = {"working": 0, "ending": 1, "starting": 2}


@dataclass(frozen=True)
class ContractRow:
    """Żywa umowa osoby (``status ∈ LIVE_CONTRACT_STATUSES``)."""

    candidate_id: int
    contract_id: int
    client_id: Optional[int]
    client_name: Optional[str]
    start_date: Optional[date]
    # Data końca umowy. Umowa B2B ma ją tylko po ręcznym zakończeniu
    # (wypowiedzenie, `/terminate`); zlecenie i umowa o pracę — z umowy.
    end_date: Optional[date] = None


@dataclass(frozen=True)
class OrderRow:
    """Zamówienie żywej umowy w statusie, który może „kończyć się"."""

    contract_id: int
    end_date: Optional[date]
    # Kończy się bez kontynuacji wg reguły alertów (``order_continuation``).
    ending: bool
    # Aktywna linia MD z budżetem — pracuje do wyczerpania, nie do daty.
    md_open: bool
    # Już się skończyło: zamknięte albo z datą końca w przeszłości.
    finished: bool = False


# ── Reguła (czysta) ─────────────────────────────────────────────────────────


def order_end_by_contract(rows: Iterable[OrderRow]) -> dict[int, date]:
    """Koniec łańcucha zamówień bez kontynuacji, per umowa.

    Umowy bez wpisu nie mają daty końca: zamówienie bezterminowe, zaplanowana
    kontynuacja, brak zamówień albo aktywna linia MD z budżetem. Z kilku
    kończących się zamówień liczy się najwcześniejsze — tak samo jak na
    liście kontraktorów (``ending_without_successor(days=None)``).

    Umowa, której wszystkie zamówienia już się skończyły, dostaje ostatni
    dzień ostatniego z nich: łańcuch skończył się bez kontynuacji, a umowa
    trwa, bo nikt jej nie zakończył. Do 14.10.2026 nie miała daty, więc
    znacznik mówił „Zamówienie bez daty końca”, choć zamówienia nie było.
    """
    rows = list(rows)
    open_md = {row.contract_id for row in rows if row.md_open}
    current_orders = {row.contract_id for row in rows if not row.finished}
    out: dict[int, date] = {}
    for row in rows:
        if not row.ending or row.end_date is None or row.contract_id in open_md:
            continue
        current = out.get(row.contract_id)
        if current is None or row.end_date < current:
            out[row.contract_id] = row.end_date
    for row in rows:
        if (
            not row.finished
            or row.end_date is None
            or row.contract_id in current_orders
        ):
            continue
        last = out.get(row.contract_id)
        if last is None or row.end_date > last:
            out[row.contract_id] = row.end_date
    return out


def _earliest(*days: Optional[date]) -> Optional[date]:
    known = [day for day in days if day is not None]
    return min(known) if known else None


def _contract_client(
    row: ContractRow,
    *,
    today: date,
    order_ends: Mapping[int, date],
    leads: Mapping[int, str],
) -> EmploymentMarkerClient:
    lead = leads.get(row.client_id) if row.client_id is not None else None
    if row.start_date is not None and row.start_date > today:
        return EmploymentMarkerClient(
            client_id=row.client_id,
            client_name=row.client_name,
            contract_id=row.contract_id,
            phase="starting",
            starts_on=row.start_date,
            delivery_lead_name=lead,
        )
    # Wypowiedziana umowa kończy pracę w swojej dacie także przy linii MD
    # z budżetem (audyt 13.10.2026: znacznik mówił „bez daty końca”).
    end = _earliest(order_ends.get(row.contract_id), row.end_date)
    ending = end is not None and (end - today).days <= ENDING_WITHOUT_CONTINUATION_DAYS
    return EmploymentMarkerClient(
        client_id=row.client_id,
        client_name=row.client_name,
        contract_id=row.contract_id,
        phase="ending" if ending else "working",
        order_end_date=end,
        delivery_lead_name=lead,
    )


def _client_sort_key(client: EmploymentMarkerClient) -> tuple[int, str, int]:
    return (
        _PHASE_RANK[client.phase],
        (client.client_name or "").casefold(),
        client.contract_id or 0,
    )


def _preference_key(client: EmploymentMarkerClient) -> tuple[int, int, int]:
    """Dwie umowy u tego samego klienta: wygrywa ta, która trwa dłużej."""
    end = client.order_end_date
    return (
        _PHASE_RANK[client.phase],
        0 if end is None else 1,
        -end.toordinal() if end is not None else 0,
    )


def _one_per_client(
    clients: Iterable[EmploymentMarkerClient],
) -> list[EmploymentMarkerClient]:
    best: dict[Any, EmploymentMarkerClient] = {}
    for client in clients:
        key: Any = (
            client.client_id
            if client.client_id is not None
            else ("contract", client.contract_id, client.client_name)
        )
        current = best.get(key)
        if current is None or _preference_key(client) < _preference_key(current):
            best[key] = client
    return sorted(best.values(), key=_client_sort_key)


def contract_free_from(
    clients: Iterable[EmploymentMarkerClient],
) -> tuple[Optional[date], Optional[EmploymentFreeFromBasis]]:
    """Od kiedy osoba z żywą umową jest wolna (15.10.2026).

    Czyta WSZYSTKIE umowy osoby, przed :func:`_one_per_client` — wybór jednej
    umowy na klienta woli tę, która trwa, i gubi kolejną umowę u tego samego
    klienta, a z nią to, że osoba zostaje u nas.

    * ``starting`` — żadna umowa jeszcze się nie zaczęła;
    * ``no_end_date`` — któraś trwająca umowa nie ma końca pracy albo po
      bieżącej czeka kolejna umowa;
    * ``work_end`` — dzień po najpóźniejszym końcu pracy (także miniony:
      zamówienia się skończyły, a umowy nikt nie zamknął).

    Lustro SQL: ``contract_availability.contract_free_by_clause``.
    """
    clients = list(clients)
    if not clients:
        return None, None
    started = [client for client in clients if client.phase != "starting"]
    if not started:
        return None, "starting"
    if len(started) != len(clients) or any(
        client.order_end_date is None for client in started
    ):
        return None, "no_end_date"
    last = max(client.order_end_date for client in started if client.order_end_date)
    return last + timedelta(days=1), "work_end"


def _marker(
    clients: list[EmploymentMarkerClient],
    job_client_ids: Optional[Collection[int]],
    *,
    free_from: Optional[date] = None,
    free_from_basis: Optional[EmploymentFreeFromBasis] = None,
) -> EmploymentMarker:
    phases = {client.phase for client in clients}
    phase: EmploymentPhase = (
        "working"
        if "working" in phases
        else "ending"
        if "ending" in phases
        else "starting"
    )
    elsewhere: Optional[bool] = None
    if job_client_ids is not None:
        elsewhere = any(
            client.client_id is not None and client.client_id not in job_client_ids
            for client in clients
        )
    return EmploymentMarker(
        phase=phase,
        source="contract",
        elsewhere=elsewhere,
        clients=clients,
        free_from=free_from,
        free_from_basis=free_from_basis,
    )


def build_markers(
    contracts: Iterable[ContractRow],
    *,
    today: date,
    order_ends: Optional[Mapping[int, date]] = None,
    leads: Optional[Mapping[int, str]] = None,
    job_client_ids: Optional[Collection[int]] = None,
) -> dict[int, EmploymentMarker]:
    """Znaczniki osób z żywą umową u nas; osoba bez umowy nie ma wpisu."""
    order_ends = order_ends or {}
    leads = leads or {}

    by_candidate: dict[int, list[EmploymentMarkerClient]] = defaultdict(list)
    for row in contracts:
        by_candidate[row.candidate_id].append(
            _contract_client(row, today=today, order_ends=order_ends, leads=leads)
        )
    out: dict[int, EmploymentMarker] = {}
    for candidate_id, clients in by_candidate.items():
        free_from, basis = contract_free_from(clients)
        out[candidate_id] = _marker(
            _one_per_client(clients),
            job_client_ids,
            free_from=free_from,
            free_from_basis=basis,
        )
    return out


def mark_returning(
    markers: Mapping[int, EmploymentMarker], returning_contract_ids: Collection[int]
) -> dict[int, EmploymentMarker]:
    """„Wraca na rynek DD.MM” przy znaczniku (22.10.2026, czysta).

    Osoba wraca na rynek, gdy KAŻDA jej trwająca umowa (bez tych z przyszłym
    startem) ma przekazanie do front office z niezamkniętym wpisem „Do
    przepięcia” (``returning_contract_ids``). Druga umowa bez takiej decyzji = osoba
    zostaje u nas. Data = najpóźniejszy koniec pracy na tych umowach; brak
    daty na którejś = data nieznana (plakietka bez daty).
    """
    returning = set(returning_contract_ids)
    out: dict[int, EmploymentMarker] = dict(markers)
    if not returning:
        return out
    for candidate_id, marker in markers.items():
        started = [client for client in marker.clients if client.phase != "starting"]
        if not started or any(
            client.contract_id not in returning for client in started
        ):
            continue
        known = [c.order_end_date for c in started if c.order_end_date is not None]
        out[candidate_id] = marker.model_copy(
            update={
                "returns_to_market": True,
                "returns_to_market_on": max(known)
                if len(known) == len(started)
                else None,
            }
        )
    return out


def returning_contract_ids(
    handed_over: Collection[int], redeploy_items: Iterable[tuple[int, str, str]]
) -> set[int]:
    """Umowy, które „wracają na rynek” (czysta reguła, przegląd 22.10.2026).

    Tak = umowa przekazana do front office (ślad ``care.front_office_handoff``)
    i z niezamkniętym wpisem „Do przepięcia” (``redeploy_items`` = (umowa,
    status, powód)). Sam wpis w toku — np. ryzyko odejścia albo „chce zmiany”
    bez przekazania — nie wystarcza; wpis „ryzyko odejścia” nie liczy się nigdy.
    """

    handed = set(handed_over)
    return {
        contract_id
        for contract_id, status, reason in redeploy_items
        if contract_id in handed
        and status in RETURNING_REDEPLOY_STATUSES
        and reason not in NEVER_RETURNING_REASONS
    }


async def load_returning_contract_ids(
    db: AsyncSession, contract_ids: Iterable[int]
) -> set[int]:
    """Umowy przekazane do front office z niezamkniętym wpisem „Do przepięcia”.

    Liczy ``returning_contract_ids``; tylko przy włączonym module opieki.

    Wyłączony program albo moduł = nikt nie „wraca na rynek” (dane opieki nie
    wychodzą poza moduł). Awaria odczytu (np. brak tabel modułu) nie kładzie
    ekranu z osobami: savepoint, log i pusty wynik.
    """
    ids = sorted({int(cid) for cid in contract_ids})
    if not ids:
        return set()
    from app.models.contract_care import RedeployQueueItem
    from app.models.hr_ops import HrAuditEvent
    from app.services.care.front_office import HANDOFF_ACTION
    from app.services.hr.modules import load_modules

    try:
        async with db.begin_nested():
            modules = await load_modules(db)
            if not modules.get("care"):
                return set()
            handed = {
                int(entity_id)
                for entity_id in await db.scalars(
                    select(HrAuditEvent.entity_id)
                    .where(
                        HrAuditEvent.entity_type == "contract",
                        HrAuditEvent.entity_id.in_([str(cid) for cid in ids]),
                        HrAuditEvent.action == HANDOFF_ACTION,
                    )
                    .distinct()
                )
            }
            if not handed:
                return set()
            rows = await db.execute(
                select(
                    RedeployQueueItem.contract_id,
                    RedeployQueueItem.status,
                    RedeployQueueItem.reason,
                ).where(
                    RedeployQueueItem.contract_id.in_(sorted(handed)),
                    RedeployQueueItem.status.in_(RETURNING_REDEPLOY_STATUSES),
                )
            )
            return returning_contract_ids(handed, rows.all())
    except Exception:  # noqa: BLE001 — znacznik ma się pokazać bez dopisku
        logger.warning(
            "employment_marker: returning contracts unavailable", exc_info=True
        )
        return set()


def marker_client_ids(contracts: Iterable[ContractRow]) -> set[int]:
    """Klienci, których Delivery Leada trzeba doczytać dla tych wierszy."""
    return {row.client_id for row in contracts if row.client_id is not None}


# ── Wiersze z relacji już wczytanych (lista kandydatów) ─────────────────────


def rows_from_candidate(candidate: Any) -> list[ContractRow]:
    """Wiersze reguły z umów wczytanych przez ``_candidate_list_options``.

    Lista kandydatów ma umowy w pamięci — znacznik nie dokłada tam zapytań
    o źródła. Wymaga ``contracts → client``.
    """
    return [
        ContractRow(
            candidate_id=candidate.id,
            contract_id=contract.id,
            client_id=contract.client_id,
            client_name=(
                client_display_name(contract.client) if contract.client else None
            ),
            start_date=contract.start_date,
            end_date=getattr(contract, "end_date", None),
        )
        for contract in (candidate.contracts or [])
        if contract.status in LIVE_CONTRACT_STATUSES
    ]


# ── Ładowanie ───────────────────────────────────────────────────────────────


def _md_budget_line_open(order: Any = ClientOrder) -> Any:
    """Lustro ``OrderFact.works_until_md_exhausted`` — wyłącznie linia grupy."""
    return and_(
        order.status == ClientOrderStatus.active,
        order.order_group_id.isnot(None),
        order.md_total.isnot(None),
        func.coalesce(order.md_remaining, 0) > 0,
    )


def _empty_draft(order: Any = ClientOrder) -> Any:
    """Porzucony szkic (bez daty końca i stawki przychodowej, np. z podpisu
    umowy) — nie jest zamówieniem; lustro ``order_continuation``."""
    return and_(
        order.status == ClientOrderStatus.draft,
        order.end_date.is_(None),
        func.coalesce(order.rate_client, order.md_rate_revenue, 0) <= 0,
    )


def _order_finished(order: Any = ClientOrder, *, today: date) -> Any:
    """Zamówienie już się skończyło: zamknięte albo aktywne/wstrzymane z datą
    końca w przeszłości (nocny cron jeszcze go nie domknął). Linia MD
    z budżetem pracuje po dacie — nie jest skończona. Nigdy ``NULL``."""
    return or_(
        order.status == ClientOrderStatus.completed,
        and_(
            order.status.in_(ENDING_ORDER_STATUSES),
            order.end_date.isnot(None),
            order.end_date < today,
            ~_md_budget_line_open(order),
        ),
    )


async def _load_contract_rows(
    db: AsyncSession, candidate_ids: Sequence[int]
) -> list[ContractRow]:
    rows = (
        await db.execute(
            select(
                Contract.candidate_id,
                Contract.client_id,
                client_display_name_expression().label("client_name"),
                Contract.id.label("contract_id"),
                Contract.start_date,
                Contract.end_date,
            )
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(
                Contract.candidate_id.in_(candidate_ids),
                Contract.status.in_(LIVE_CONTRACT_STATUSES),
            )
        )
    ).all()
    return [
        ContractRow(
            candidate_id=row.candidate_id,
            contract_id=row.contract_id,
            client_id=row.client_id,
            client_name=row.client_name,
            start_date=row.start_date,
            end_date=row.end_date,
        )
        for row in rows
    ]


async def load_order_ends(
    db: AsyncSession, contract_ids: Iterable[int], *, today: date
) -> dict[int, date]:
    """Koniec łańcucha zamówień dla umów — jedno wąskie zapytanie, bez stawek."""
    ids = sorted({int(cid) for cid in contract_ids})
    if not ids:
        return {}
    ending = order_ending_without_continuation(
        today,
        date.max,
        extended_client_ids=extended_order_alert_client_ids(),
        today=today,
    )
    # Zamknięte i zaplanowane też: bez nich umowa po końcu ostatniego
    # zamówienia wyglądała jak umowa z zamówieniem bez daty końca. Linia
    # zamówienia MD bez własnej daty kończy się z grupą (jak w
    # ``order_continuation``); kończące się zamówienie ma własną datę.
    group = aliased(ClientOrderGroup)
    rows = (
        await db.execute(
            select(
                ClientOrder.contract_id,
                func.coalesce(ClientOrder.end_date, group.end_date).label("end_date"),
                ending.label("ending"),
                _md_budget_line_open().label("md_open"),
                _order_finished(today=today).label("finished"),
            )
            .outerjoin(group, group.id == ClientOrder.order_group_id)
            .where(
                ClientOrder.contract_id.in_(ids),
                ClientOrder.status != ClientOrderStatus.cancelled,
                ~_empty_draft(),
            )
        )
    ).all()
    return order_end_by_contract(
        OrderRow(
            contract_id=row.contract_id,
            end_date=row.end_date,
            ending=bool(row.ending),
            md_open=bool(row.md_open),
            finished=bool(row.finished),
        )
        for row in rows
    )


async def client_delivery_leads(
    db: AsyncSession, client_ids: Iterable[int]
) -> dict[int, str]:
    """Delivery Lead klienta do pokazania przy znaczniku: ``{client_id: imię}``.

    Główny opiekun, a bez niego dowolny przypisany. Sam wiersz przypisania nie
    jest grantem — liczy się aktywne konto z rolą Delivery Leada (ten sam
    warunek co ``job_delivery_lead_fill._HEADS``).
    """
    ids = sorted({int(cid) for cid in client_ids})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(DeliveryLeadClientAssignment.client_id, User)
            .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
            .where(
                DeliveryLeadClientAssignment.client_id.in_(ids),
                User.is_active.is_(True),
            )
            .order_by(
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.is_head.desc(),
                DeliveryLeadClientAssignment.id,
            )
        )
    ).all()
    out: dict[int, str] = {}
    for client_id, user in rows:
        if client_id in out or not user.has_role(UserRole.delivery_lead):
            continue
        out[client_id] = user.name
    return out


async def markers_from_rows(
    db: AsyncSession,
    contracts: Sequence[ContractRow],
    *,
    today: date,
    job_client_ids: Optional[Collection[int]] = None,
) -> dict[int, EmploymentMarker]:
    """Doczytuje zamówienia i Delivery Leadów tylko, gdy jest po co."""
    if not contracts:
        return {}
    order_ends = await load_order_ends(
        db,
        (
            row.contract_id
            for row in contracts
            if row.start_date is None or row.start_date <= today
        ),
        today=today,
    )
    leads = await client_delivery_leads(db, marker_client_ids(contracts))
    markers = build_markers(
        contracts,
        today=today,
        order_ends=order_ends,
        leads=leads,
        job_client_ids=job_client_ids,
    )
    returning = await load_returning_contract_ids(
        db, (row.contract_id for row in contracts)
    )
    return mark_returning(markers, returning)


async def load_employment_markers(
    db: AsyncSession,
    candidate_ids: Iterable[int],
    *,
    today: date,
    job_client_id: Optional[int] = None,
) -> dict[int, Optional[EmploymentMarker]]:
    """``{candidate_id: znacznik | None}`` — każdy przekazany id jest w wyniku.

    Jedno zapytanie o umowy; zamówienia i Delivery Leadzi dochodzą tylko
    wtedy, gdy na stronie jest ktoś z umową. ``job_client_id`` włącza
    ``elsewhere`` (klient spoza rodziny klienta rekrutacji).
    """
    ids = sorted({int(cid) for cid in candidate_ids if cid is not None})
    out: dict[int, Optional[EmploymentMarker]] = {cid: None for cid in ids}
    if not ids:
        return out
    contracts = await _load_contract_rows(db, ids)
    family = await job_client_family(db, job_client_id)
    out.update(
        await markers_from_rows(db, contracts, today=today, job_client_ids=family)
    )
    return out


async def job_client_family(
    db: AsyncSession, job_client_id: Optional[int]
) -> Optional[set[int]]:
    """Klient rekrutacji ze scalonymi rekordami; ``None`` = bez rekrutacji."""
    if job_client_id is None:
        return None
    from app.services.recruitment_rates import client_family_ids

    return await client_family_ids(db, job_client_id)


# ── Filtr listy kandydatów ──────────────────────────────────────────────────


def work_end_sql(*, today: date) -> Any:
    """Koniec pracy na umowie ``Contract`` z zewnętrznego zapytania — lustro
    SQL daty znacznika (:func:`order_end_by_contract` + :func:`_contract_client`):
    wcześniejsza z dat końca umowy i końca łańcucha zamówień; ``NULL`` = bez
    daty końca."""
    line = aliased(ClientOrder)
    counted = and_(
        line.contract_id == Contract.id,
        line.status != ClientOrderStatus.cancelled,
        ~_empty_draft(line),
    )
    ending_end = (
        select(func.min(ClientOrder.end_date))
        .where(
            ClientOrder.contract_id == Contract.id,
            order_ending_without_continuation(
                today,
                date.max,
                extended_client_ids=extended_order_alert_client_ids(),
                today=today,
            ),
        )
        .scalar_subquery()
    )
    md_open = (
        select(1)
        .where(line.contract_id == Contract.id, _md_budget_line_open(line))
        .exists()
    )
    current_order = (
        select(1).where(counted, ~_order_finished(line, today=today)).exists()
    )
    line_group = aliased(ClientOrderGroup)
    finished_end = (
        select(func.max(func.coalesce(line.end_date, line_group.end_date)))
        .select_from(line)
        .outerjoin(line_group, line_group.id == line.order_group_id)
        .where(counted, _order_finished(line, today=today))
        .scalar_subquery()
    )
    # Kończące się zamówienie jest bieżące, więc obie gałęzie się wykluczają.
    chain_end = func.coalesce(
        case((~md_open, ending_end)), case((~current_order, finished_end))
    )
    # LEAST w Postgresie pomija NULL-e: brak jednej z dat = druga.
    return func.least(Contract.end_date, chain_end)


def ending_soon_exists(
    candidate_id: Any, *, today: date, days: int = ENDING_SOON_FILTER_DAYS
) -> Any:
    """Osoba pracuje u nas, a KAŻDA jej trwająca umowa kończy się najpóźniej
    za ``days`` dni — ta sama data co w znaczniku (koniec zamówień bez
    kontynuacji albo data końca umowy), z dłuższym horyzontem; korelacja po
    przekazanym wyrażeniu (``Candidate.id``).

    Do 14.10.2026 wystarczała jedna kończąca się umowa: osoba z drugą umową
    bez końca była na liście „Kończy u nas”, a znacznik mówił „Pracuje u nas”.
    """
    stop = today + timedelta(days=days)
    started_live = and_(
        Contract.candidate_id == candidate_id,
        Contract.status.in_(LIVE_CONTRACT_STATUSES),
        or_(Contract.start_date.is_(None), Contract.start_date <= today),
    )
    works = select(1).select_from(Contract).where(started_live).exists()
    stays_longer = (
        select(1)
        .select_from(Contract)
        .where(
            started_live,
            func.coalesce(work_end_sql(today=today), date.max) > stop,
        )
        .exists()
    )
    return and_(works, ~stays_longer)


__all__ = [
    "ENDING_SOON_FILTER_DAYS",
    "ContractRow",
    "OrderRow",
    "build_markers",
    "client_delivery_leads",
    "contract_free_from",
    "ending_soon_exists",
    "job_client_family",
    "load_employment_markers",
    "load_order_ends",
    "load_returning_contract_ids",
    "returning_contract_ids",
    "mark_returning",
    "marker_client_ids",
    "markers_from_rows",
    "order_end_by_contract",
    "rows_from_candidate",
    "work_end_sql",
]
