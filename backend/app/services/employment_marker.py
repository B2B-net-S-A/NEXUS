"""Znacznik „Pracuje u nas" — jedna reguła dla każdego ekranu (12.10.2026).

Do tej zmiany informację, że osoba u nas pracuje, pokazywał tylko profil
i jedna kolumna listy kandydatów; okna dodawania do rekrutacji, Tablica
i panel osoby jej nie miały. Każdy z tych ekranów czyta teraz ten sam wynik
:func:`build_markers`.

Reguła:

* **pracuje** — żywa umowa (``status ∈ {active, ending}``) ze startem nie
  później niż dziś albo bez daty startu (``current_employment.is_live_contract``);
* **zaczyna** — żywa umowa ze startem w przyszłości. Podpis w Generatorze
  aktywuje umowę od razu i przesuwa kartę na „Zatrudniony", więc ta sama
  umowa wygrywa z sygnałem ``hired`` i z ręcznym konfliktem;
* **kończy** — do końca łańcucha zamówień bez kontynuacji zostało najwyżej
  ``ENDING_WITHOUT_CONTINUATION_DAYS`` dni. To reguła alertów Delivery
  (``order_continuation``): linie zamówień MD „kończą się" tylko u klientów
  z listy rozszerzonej, a aktywna linia MD z budżetem nie ma daty końca.

Bez żywej umowy zostają dwa starsze sygnały, w tej samej kolejności co
``candidates._derive_employment``: ręczny konflikt ``current_employment``
i bieżący etap ``hired``. Znacznik istnieje dokładnie wtedy, gdy stare pole
``employment.state`` to ``employed_at_client`` — pilnuje tego test.

Znacznik nie niesie kwot i niczego nie blokuje (decyzja o konfliktach
z 17.09.2026: ostrzeżenie, nie blokada).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Collection, Iterable, Literal, Mapping, Optional, Sequence

from sqlalchemy import (
    Date,
    Integer,
    and_,
    cast,
    func,
    literal_column,
    null,
    or_,
    select,
)
from sqlalchemy import union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.schemas.candidate import (
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
from app.services.pipeline_latest import current_hired_stage_clause

#: Horyzont filtra listy „Kończy u nas w ciągu 60 dni".
ENDING_SOON_FILTER_DAYS = 60

SignalSource = Literal["conflict", "pipeline"]

_PHASE_RANK: dict[str, int] = {"working": 0, "ending": 1, "starting": 2}


@dataclass(frozen=True)
class ContractRow:
    """Żywa umowa osoby (``status ∈ LIVE_CONTRACT_STATUSES``)."""

    candidate_id: int
    contract_id: int
    client_id: Optional[int]
    client_name: Optional[str]
    start_date: Optional[date]


@dataclass(frozen=True)
class SignalRow:
    """Sygnał zatrudnienia spoza umów: ręczny konflikt albo etap ``hired``."""

    candidate_id: int
    source: SignalSource
    client_id: Optional[int]
    client_name: Optional[str]


@dataclass(frozen=True)
class OrderRow:
    """Zamówienie żywej umowy w statusie, który może „kończyć się"."""

    contract_id: int
    end_date: Optional[date]
    # Kończy się bez kontynuacji wg reguły alertów (``order_continuation``).
    ending: bool
    # Aktywna linia MD z budżetem — pracuje do wyczerpania, nie do daty.
    md_open: bool


# ── Reguła (czysta) ─────────────────────────────────────────────────────────


def order_end_by_contract(rows: Iterable[OrderRow]) -> dict[int, date]:
    """Koniec łańcucha zamówień bez kontynuacji, per umowa.

    Umowy bez wpisu nie mają daty końca: zamówienie bezterminowe, zaplanowana
    kontynuacja, brak zamówień albo aktywna linia MD z budżetem. Z kilku
    kończących się zamówień liczy się najwcześniejsze — tak samo jak na
    liście kontraktorów (``ending_without_successor(days=None)``).
    """
    rows = list(rows)
    open_md = {row.contract_id for row in rows if row.md_open}
    out: dict[int, date] = {}
    for row in rows:
        if not row.ending or row.end_date is None or row.contract_id in open_md:
            continue
        current = out.get(row.contract_id)
        if current is None or row.end_date < current:
            out[row.contract_id] = row.end_date
    return out


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
    end = order_ends.get(row.contract_id)
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


def _marker(
    source: Literal["contract", "conflict", "pipeline"],
    clients: list[EmploymentMarkerClient],
    job_client_ids: Optional[Collection[int]],
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
        phase=phase, source=source, elsewhere=elsewhere, clients=clients
    )


def build_markers(
    contracts: Iterable[ContractRow],
    signals: Iterable[SignalRow],
    *,
    today: date,
    order_ends: Optional[Mapping[int, date]] = None,
    leads: Optional[Mapping[int, str]] = None,
    job_client_ids: Optional[Collection[int]] = None,
) -> dict[int, EmploymentMarker]:
    """Znaczniki osób, które mają jakikolwiek sygnał zatrudnienia u nas.

    Osoba bez sygnału nie ma wpisu. Kolejność źródeł jest ta sama co
    w ``candidates._derive_employment``: umowa → ręczny konflikt → etap
    ``hired``; niższe źródło nie dokleja klientów do wyższego.
    """
    order_ends = order_ends or {}
    leads = leads or {}

    by_candidate: dict[int, list[EmploymentMarkerClient]] = defaultdict(list)
    for row in contracts:
        by_candidate[row.candidate_id].append(
            _contract_client(row, today=today, order_ends=order_ends, leads=leads)
        )
    out: dict[int, EmploymentMarker] = {
        candidate_id: _marker("contract", _one_per_client(clients), job_client_ids)
        for candidate_id, clients in by_candidate.items()
    }

    signals = list(signals)
    for source in ("conflict", "pipeline"):
        grouped: dict[int, list[EmploymentMarkerClient]] = defaultdict(list)
        for signal in signals:
            if signal.source != source or signal.candidate_id in out:
                continue
            grouped[signal.candidate_id].append(
                EmploymentMarkerClient(
                    client_id=signal.client_id,
                    client_name=signal.client_name,
                    phase="working",
                    delivery_lead_name=(
                        leads.get(signal.client_id)
                        if signal.client_id is not None
                        else None
                    ),
                )
            )
        for candidate_id, clients in grouped.items():
            out[candidate_id] = _marker(
                source, _one_per_client(clients), job_client_ids
            )
    return out


def marker_client_ids(
    contracts: Iterable[ContractRow], signals: Iterable[SignalRow]
) -> set[int]:
    """Klienci, których Delivery Leada trzeba doczytać dla tych wierszy."""
    return {
        row.client_id for row in (*contracts, *signals) if row.client_id is not None
    }


# ── Wiersze z relacji już wczytanych (lista kandydatów) ─────────────────────


def rows_from_candidate(candidate: Any) -> tuple[list[ContractRow], list[SignalRow]]:
    """Wiersze reguły z relacji wczytanych przez ``_candidate_list_options``.

    Lista kandydatów ma umowy, konflikty i etapy w pamięci — znacznik nie
    dokłada tam zapytań o źródła. Wymaga ``contracts → client``,
    ``conflicts → client`` i ``pipeline_stages → job → client``.
    """
    contracts = [
        ContractRow(
            candidate_id=candidate.id,
            contract_id=contract.id,
            client_id=contract.client_id,
            client_name=(
                client_display_name(contract.client) if contract.client else None
            ),
            start_date=contract.start_date,
        )
        for contract in (candidate.contracts or [])
        if contract.status in LIVE_CONTRACT_STATUSES
    ]
    signals = [
        SignalRow(
            candidate_id=candidate.id,
            source="conflict",
            client_id=conflict.client_id,
            client_name=(
                client_display_name(conflict.client) if conflict.client else None
            ),
        )
        for conflict in (candidate.conflicts or [])
        if conflict.active and conflict.type == ConflictType.current_employment
    ]
    latest_by_job: dict[int, Any] = {}
    for stage in candidate.pipeline_stages or []:
        current = latest_by_job.get(stage.job_id)
        if current is None or (stage.moved_at, stage.id) > (
            current.moved_at,
            current.id,
        ):
            latest_by_job[stage.job_id] = stage
    for stage in latest_by_job.values():
        if stage.stage != PipelineStage.hired:
            continue
        client = stage.job.client if stage.job else None
        signals.append(
            SignalRow(
                candidate_id=candidate.id,
                source="pipeline",
                client_id=client.id if client else None,
                client_name=client_display_name(client) if client else None,
            )
        )
    return contracts, signals


# ── Ładowanie ───────────────────────────────────────────────────────────────


def _md_budget_line_open(order: Any = ClientOrder) -> Any:
    """Lustro ``OrderFact.works_until_md_exhausted`` — wyłącznie linia grupy."""
    return and_(
        order.status == ClientOrderStatus.active,
        order.order_group_id.isnot(None),
        order.md_total.isnot(None),
        func.coalesce(order.md_remaining, 0) > 0,
    )


async def _load_source_rows(
    db: AsyncSession, candidate_ids: Sequence[int]
) -> tuple[list[ContractRow], list[SignalRow]]:
    name = client_display_name_expression()
    contracts_q = (
        select(
            literal_column("'contract'").label("kind"),
            Contract.candidate_id.label("candidate_id"),
            Contract.client_id.label("client_id"),
            name.label("client_name"),
            Contract.id.label("contract_id"),
            Contract.start_date.label("start_date"),
        )
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(
            Contract.candidate_id.in_(candidate_ids),
            Contract.status.in_(LIVE_CONTRACT_STATUSES),
        )
    )
    conflicts_q = (
        select(
            literal_column("'conflict'"),
            CandidateConflict.candidate_id,
            CandidateConflict.client_id,
            name,
            cast(null(), Integer),
            cast(null(), Date),
        )
        .outerjoin(Client, Client.id == CandidateConflict.client_id)
        .where(
            CandidateConflict.candidate_id.in_(candidate_ids),
            CandidateConflict.type == ConflictType.current_employment,
            CandidateConflict.active.is_(True),
        )
    )
    hired_q = (
        select(
            literal_column("'pipeline'"),
            CandidateStage.candidate_id,
            Job.client_id,
            name,
            cast(null(), Integer),
            cast(null(), Date),
        )
        .join(Job, Job.id == CandidateStage.job_id)
        .outerjoin(Client, Client.id == Job.client_id)
        .where(
            CandidateStage.candidate_id.in_(candidate_ids),
            current_hired_stage_clause(),
        )
    )
    rows = (await db.execute(union_all(contracts_q, conflicts_q, hired_q))).all()
    contracts: list[ContractRow] = []
    signals: list[SignalRow] = []
    for row in rows:
        if row.kind == "contract":
            contracts.append(
                ContractRow(
                    candidate_id=row.candidate_id,
                    contract_id=row.contract_id,
                    client_id=row.client_id,
                    client_name=row.client_name,
                    start_date=row.start_date,
                )
            )
        else:
            signals.append(
                SignalRow(
                    candidate_id=row.candidate_id,
                    source=row.kind,
                    client_id=row.client_id,
                    client_name=row.client_name,
                )
            )
    return contracts, signals


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
    rows = (
        await db.execute(
            select(
                ClientOrder.contract_id,
                ClientOrder.end_date,
                ending.label("ending"),
                _md_budget_line_open().label("md_open"),
            ).where(
                ClientOrder.contract_id.in_(ids),
                ClientOrder.status.in_(ENDING_ORDER_STATUSES),
            )
        )
    ).all()
    return order_end_by_contract(
        OrderRow(
            contract_id=row.contract_id,
            end_date=row.end_date,
            ending=bool(row.ending),
            md_open=bool(row.md_open),
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
    signals: Sequence[SignalRow],
    *,
    today: date,
    job_client_ids: Optional[Collection[int]] = None,
) -> dict[int, EmploymentMarker]:
    """Doczytuje zamówienia i Delivery Leadów tylko, gdy jest po co."""
    if not contracts and not signals:
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
    leads = await client_delivery_leads(db, marker_client_ids(contracts, signals))
    return build_markers(
        contracts,
        signals,
        today=today,
        order_ends=order_ends,
        leads=leads,
        job_client_ids=job_client_ids,
    )


async def load_employment_markers(
    db: AsyncSession,
    candidate_ids: Iterable[int],
    *,
    today: date,
    job_client_id: Optional[int] = None,
) -> dict[int, Optional[EmploymentMarker]]:
    """``{candidate_id: znacznik | None}`` — każdy przekazany id jest w wyniku.

    Jedno zapytanie o źródła; zamówienia i Delivery Leadzi dochodzą tylko
    wtedy, gdy na stronie jest ktoś z sygnałem. ``job_client_id`` włącza
    ``elsewhere`` (klient spoza rodziny klienta rekrutacji).
    """
    ids = sorted({int(cid) for cid in candidate_ids if cid is not None})
    out: dict[int, Optional[EmploymentMarker]] = {cid: None for cid in ids}
    if not ids:
        return out
    contracts, signals = await _load_source_rows(db, ids)
    family = await job_client_family(db, job_client_id)
    out.update(
        await markers_from_rows(
            db, contracts, signals, today=today, job_client_ids=family
        )
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


def ending_soon_exists(
    candidate_id: Any, *, today: date, days: int = ENDING_SOON_FILTER_DAYS
) -> Any:
    """``EXISTS``: osoba pracuje u nas, a jej zamówienie kończy się w ``days``
    dni bez kontynuacji. Ta sama reguła co faza „kończy" znacznika, z dłuższym
    horyzontem; korelacja po przekazanym wyrażeniu (``Candidate.id``).
    """
    budget_line = aliased(ClientOrder)
    md_open = (
        select(1)
        .where(
            budget_line.contract_id == Contract.id,
            _md_budget_line_open(budget_line),
        )
        .exists()
    )
    return (
        select(1)
        .select_from(Contract)
        .join(ClientOrder, ClientOrder.contract_id == Contract.id)
        .where(
            Contract.candidate_id == candidate_id,
            Contract.status.in_(LIVE_CONTRACT_STATUSES),
            or_(Contract.start_date.is_(None), Contract.start_date <= today),
            order_ending_without_continuation(
                today,
                today + timedelta(days=days),
                extended_client_ids=extended_order_alert_client_ids(),
                today=today,
            ),
            ~md_open,
        )
        .exists()
    )


__all__ = [
    "ENDING_SOON_FILTER_DAYS",
    "ContractRow",
    "OrderRow",
    "SignalRow",
    "build_markers",
    "client_delivery_leads",
    "ending_soon_exists",
    "job_client_family",
    "load_employment_markers",
    "load_order_ends",
    "marker_client_ids",
    "markers_from_rows",
    "order_end_by_contract",
    "rows_from_candidate",
]
