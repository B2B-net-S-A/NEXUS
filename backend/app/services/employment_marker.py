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

Po audycie 13.10.2026 (14.10.2026):

* etap ``hired`` nie jest sygnałem, gdy umowa u klienta tej rekrutacji
  skończyła się albo została anulowana po zatrudnieniu, a żadna inna umowa
  u niego nie trwa ani nie czeka na podpis (:func:`hire_closed_by_contract`) —
  inaczej były konsultant „pracował u nas” na zawsze, a Delivery Lead
  dawnego klienta dostawał dzwonek;
* data w znaczniku to wcześniejsza z dat: koniec łańcucha zamówień i data
  końca umowy (ustawiana tylko przy zakończeniu — umowa B2B jest
  bezterminowa); łańcuch, którego wszystkie zamówienia już się skończyły,
  kończy się w ostatnim dniu ostatniego z nich.

Znacznik nie niesie kwot i niczego nie blokuje (decyzja o konfliktach
z 17.09.2026: ostrzeżenie, nie blokada).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Collection, Iterable, Literal, Mapping, Optional, Sequence

from sqlalchemy import (
    Date,
    Integer,
    and_,
    case,
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

from app.core.scheduling import business_today
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus
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

#: Umowa, która się skończyła: zakończona albo anulowana.
CLOSED_CONTRACT_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.ended,
    ContractStatus.void,
)
#: Umowa, przy której zatrudnienie u klienta trwa albo czeka na podpis.
_OPEN_CONTRACT_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    *LIVE_CONTRACT_STATUSES,
)


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


def _closed_on(contract: Any) -> Optional[date]:
    """Dzień końca umowy zakończonej albo anulowanej; ``None`` = nie wiadomo."""
    for value in (
        getattr(contract, "end_date", None),
        getattr(contract, "terminated_at", None),
    ):
        if value is not None:
            return value
    voided_at = getattr(contract, "voided_at", None)
    return voided_at.date() if voided_at is not None else None


# „Zatrudniony” bez żadnej umowy u klienta liczy się najwyżej tyle dni
# (decyzja Artura 14.10.2026: 12 miesięcy). Umowa nowej osoby powstaje
# w tygodniach, a starsze etapy bez umowy to głównie zatrudnienia z czasów
# Traffita — 85 osób na produkcji 14.10.2026, 65 ponad rok temu.
STALE_HIRE_DAYS = 365


def hire_closed_by_contract(
    *,
    client_id: Optional[int],
    hired_at: Optional[datetime],
    contracts: Iterable[Any],
    today: Optional[date] = None,
) -> bool:
    """Etap „Zatrudniony” u klienta jest już historią.

    Tak jest, gdy umowa osoby u tego klienta skończyła się albo została
    anulowana (``ended`` / ``void``) w dniu zatrudnienia lub później, a żadna
    inna umowa u niego nie trwa ani nie czeka na podpis. Umowa bez żadnej daty
    końca też zamyka — wiemy, że się skończyła. Umowa zakończona PRZED
    zatrudnieniem nie zamyka: to ponowne zatrudnienie u tego samego klienta.

    Bez żadnej umowy u tego klienta etap jest historią, gdy minęło ponad
    ``STALE_HIRE_DAYS`` dni od zatrudnienia (14.10.2026) — inaczej osoba
    zatrudniona lata temu w Traffit „pracowała u nas” na zawsze.

    Lustro SQL: :func:`hire_closed_by_contract_clause`. Czyta je znacznik
    i stare pole ``employment`` (niezmiennik znacznika).
    """
    if client_id is None:
        return False
    at_client = [
        contract
        for contract in contracts
        if getattr(contract, "client_id", None) == client_id
    ]
    if not at_client:
        if hired_at is None:
            return False
        today = today or business_today()
        return hired_at.date() < today - timedelta(days=STALE_HIRE_DAYS)
    if any(contract.status in _OPEN_CONTRACT_STATUSES for contract in at_client):
        return False
    hired_on = hired_at.date() if hired_at is not None else None
    for contract in at_client:
        if contract.status not in CLOSED_CONTRACT_STATUSES:
            continue
        closed_on = _closed_on(contract)
        if closed_on is None or (hired_on is not None and closed_on >= hired_on):
            return True
    return False


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


def rows_from_candidate(
    candidate: Any, today: Optional[date] = None
) -> tuple[list[ContractRow], list[SignalRow]]:
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
            end_date=getattr(contract, "end_date", None),
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
        if hire_closed_by_contract(
            client_id=client.id if client else None,
            hired_at=stage.moved_at,
            contracts=candidate.contracts or [],
            today=today,
        ):
            continue
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


def hire_closed_by_contract_clause(today: Optional[date] = None) -> Any:
    """Lustro SQL :func:`hire_closed_by_contract` dla zapytania po
    ``CandidateStage`` złączonym z ``Job`` (korelacja po obu)."""
    closed = aliased(Contract)
    still_open = aliased(Contract)
    any_contract = aliased(Contract)
    stale_before = (today or business_today()) - timedelta(days=STALE_HIRE_DAYS)
    closed_on = func.coalesce(
        closed.end_date, closed.terminated_at, cast(closed.voided_at, Date)
    )
    closed_after_hire = (
        select(1)
        .where(
            closed.candidate_id == CandidateStage.candidate_id,
            closed.client_id == Job.client_id,
            closed.status.in_(CLOSED_CONTRACT_STATUSES),
            or_(
                closed_on.is_(None),
                closed_on >= cast(CandidateStage.moved_at, Date),
            ),
        )
        .exists()
    )
    open_at_client = (
        select(1)
        .where(
            still_open.candidate_id == CandidateStage.candidate_id,
            still_open.client_id == Job.client_id,
            still_open.status.in_(_OPEN_CONTRACT_STATUSES),
        )
        .exists()
    )
    contract_at_client = (
        select(1)
        .where(
            any_contract.candidate_id == CandidateStage.candidate_id,
            any_contract.client_id == Job.client_id,
        )
        .exists()
    )
    return or_(
        and_(closed_after_hire, ~open_at_client),
        and_(
            ~contract_at_client,
            cast(CandidateStage.moved_at, Date) < stale_before,
        ),
    )


def current_hired_signal_exists(candidate_id: Any, today: Optional[date] = None) -> Any:
    """``EXISTS``: osoba stoi dziś na „Zatrudniony”, a umowa u klienta tej
    rekrutacji tego nie zamknęła — sygnał ``pipeline`` znacznika.

    Dla filtra listy (``candidates._at_client_predicate``), żeby
    ``employment=at_client`` / ``available`` mówiły to samo co znacznik.
    """
    return (
        select(1)
        .select_from(CandidateStage)
        .join(Job, Job.id == CandidateStage.job_id)
        .where(
            CandidateStage.candidate_id == candidate_id,
            current_hired_stage_clause(),
            ~hire_closed_by_contract_clause(today),
        )
        .exists()
    )


async def _load_source_rows(
    db: AsyncSession, candidate_ids: Sequence[int], today: Optional[date] = None
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
            Contract.end_date.label("end_date"),
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
            cast(null(), Date),
        )
        .join(Job, Job.id == CandidateStage.job_id)
        .outerjoin(Client, Client.id == Job.client_id)
        .where(
            CandidateStage.candidate_id.in_(candidate_ids),
            current_hired_stage_clause(),
            ~hire_closed_by_contract_clause(today),
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
                    end_date=row.end_date,
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
    contracts, signals = await _load_source_rows(db, ids, today)
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


def _work_end_sql(*, today: date) -> Any:
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
            func.coalesce(_work_end_sql(today=today), date.max) > stop,
        )
        .exists()
    )
    return and_(works, ~stays_longer)


__all__ = [
    "CLOSED_CONTRACT_STATUSES",
    "ENDING_SOON_FILTER_DAYS",
    "ContractRow",
    "OrderRow",
    "SignalRow",
    "build_markers",
    "client_delivery_leads",
    "current_hired_signal_exists",
    "ending_soon_exists",
    "hire_closed_by_contract",
    "hire_closed_by_contract_clause",
    "job_client_family",
    "load_employment_markers",
    "load_order_ends",
    "marker_client_ids",
    "markers_from_rows",
    "order_end_by_contract",
    "rows_from_candidate",
]
