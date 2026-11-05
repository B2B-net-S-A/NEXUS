"""Dokumenty do startu: kto, czego i na kiedy (etap 1, decyzje Artura 05.11.2026).

Klient ma listę (``ClientStartDocument``), a para (kandydat, rekrutacja) stan
pozycji (``PlacementStartDocument``). Reguły: ``docs/claude/kontrakty/dokumenty-do-startu.md``.

* **Lista klienta jest przełącznikiem.** Klient bez listy: nic się nie pojawia.
* **Pary w zakresie liczone przy odczycie**, bez hooków na etapach: do
  „Zatrudnionego” prowadzi kilka dróg (podpis, ręczny ruch, Traffit).
  W zakresie jest para, której najnowszy etap to akceptacja, negocjacje,
  onboarding albo „Zatrudniony”, od ``SINCE_GRACE_DAYS`` przed założeniem listy.
* **Etap 1 nie zmienia liczników.** Placement dalej nalicza „Zatrudniony”.
* **Odpowiada ta sama osoba, która dostaje placement** (reguła premii
  ``placement_bonuses.load_context``), bez rekrutera: Delivery Lead.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.start_document import ClientStartDocument, PlacementStartDocument
from app.models.user import User
from app.services.hr.calendar import WorkCalendar, load_calendar
from app.services.hr.lifecycle_dates import shift_working_days
from app.services.hr.placement_bonuses import load_context
from app.services.job_working_title import display_title

logger = logging.getLogger(__name__)

KIND_FILE = "file"
KIND_PESEL = "pesel"
KIND_AGREEMENT = "agreement"
STATUS_DELIVERED = "delivered"
STATUS_RETURNED = "returned"
STATUS_NOT_APPLICABLE = "not_applicable"
#: Stan pozycji w odpowiedzi: ``missing`` to brak wiersza pary.
STATE_MISSING = "missing"

ACTIVE_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.acceptance,
    PipelineStage.negotiation,
    PipelineStage.onboarding,
    PipelineStage.hired,
)
#: Świeże placementy sprzed założenia listy też wchodzą (decyzja 05.11.2026).
SINCE_GRACE_DAYS = 14
#: Mail z przypomnieniem dopiero tyle dni roboczych przed startem.
MAIL_FROM_WORKING_DAYS = 5
#: Delivery Lead dostaje listę tyle dni roboczych przed startem.
DL_FROM_WORKING_DAYS = 2
_DEAD_CONTRACT = (ContractStatus.void, ContractStatus.ended)
_LIVE_CONTRACT = (ContractStatus.active, ContractStatus.ending)
_TZ_UTC = timezone.utc

MSG_PESEL = "PESEL ma 11 cyfr i poprawną cyfrę kontrolną. Sprawdź numer."
_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def normalize_pesel(raw: str) -> Optional[str]:
    """PESEL bez spacji albo ``None``, gdy numer nie ma poprawnej sumy."""

    value = re.sub(r"\s+", "", raw or "")
    if not re.fullmatch(r"\d{11}", value):
        return None
    total = sum(w * int(d) for w, d in zip(_PESEL_WEIGHTS, value))
    return value if (10 - total % 10) % 10 == int(value[10]) else None


@dataclass(frozen=True)
class ItemState:
    document: ClientStartDocument
    row: Optional[PlacementStartDocument]
    state: str

    @property
    def done(self) -> bool:
        return self.state in (STATUS_DELIVERED, STATUS_NOT_APPLICABLE)


@dataclass(frozen=True)
class PairState:
    candidate_id: int
    job_id: int
    client_id: int
    candidate_name: str
    job_title: str
    client_name: str
    stage: str
    start_date: Optional[date]
    contract_id: Optional[int]
    agreement_number: Optional[str]
    recruiter_id: Optional[int]
    delivery_lead_id: Optional[int]
    items: tuple[ItemState, ...] = field(default_factory=tuple)
    deadline: Optional[date] = None
    tone: str = "calm"
    working: bool = False
    working_days_to_start: Optional[int] = None

    @property
    def required(self) -> tuple[ItemState, ...]:
        return tuple(i for i in self.items if i.document.required)

    @property
    def done_count(self) -> int:
        return sum(1 for i in self.required if i.done)

    @property
    def missing(self) -> tuple[ItemState, ...]:
        return tuple(i for i in self.required if not i.done)

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def owner_id(self) -> Optional[int]:
        return self.recruiter_id or self.delivery_lead_id


def item_state(
    document: ClientStartDocument,
    row: Optional[PlacementStartDocument],
    *,
    agreement_signed: bool,
) -> str:
    """Stan pozycji. Umowa odhacza się sama przy podpisie, chyba że DL ją wyłączył."""

    if row is not None:
        return row.status
    if document.kind == KIND_AGREEMENT and agreement_signed:
        return STATUS_DELIVERED
    return STATE_MISSING


def deadline_of(
    items: Iterable[ItemState], start_date: Optional[date], calendar: WorkCalendar
) -> Optional[date]:
    """Najwcześniejszy termin brakującej wymaganej pozycji."""

    if start_date is None:
        return None
    dates = [
        shift_working_days(calendar, start_date, item.document.offset_days)
        for item in items
        if item.document.required and not item.done
    ]
    return min(dates) if dates else None


def tone_of(deadline: Optional[date], today: date) -> str:
    if deadline is None:
        return "calm"
    if deadline < today:
        return "late"
    if deadline == today:
        return "today"
    return "calm"


def working_days_between(calendar: WorkCalendar, start: date, end: date) -> int:
    """Dni robocze od ``start`` (bez niego) do ``end`` (z nim); 0, gdy ``end`` minął."""

    days = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if calendar.is_working_day(current):
            days += 1
    return days


async def client_lists(
    db: AsyncSession, client_ids: Optional[Iterable[int]] = None
) -> dict[int, list[ClientStartDocument]]:
    """Żywe listy klientów, w kolejności pozycji."""

    query = select(ClientStartDocument).where(ClientStartDocument.archived_at.is_(None))
    if client_ids is not None:
        query = query.where(ClientStartDocument.client_id.in_(list(client_ids)))
    rows = await db.scalars(
        query.order_by(ClientStartDocument.position, ClientStartDocument.id)
    )
    found: dict[int, list[ClientStartDocument]] = {}
    for row in rows.all():
        found.setdefault(row.client_id, []).append(row)
    return found


async def _pairs_in_scope(
    db: AsyncSession, lists: dict[int, list[ClientStartDocument]]
) -> list[tuple[int, int]]:
    """Pary z aktywnym etapem, najpierw zawężone indeksem po dacie ruchu."""

    pairs: list[tuple[int, int]] = []
    for client_id, documents in lists.items():
        since = min(d.created_at for d in documents) - timedelta(days=SINCE_GRACE_DAYS)
        rows = await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.job_id)
            .join(Job, Job.id == CandidateStage.job_id)
            .where(
                Job.client_id == client_id,
                CandidateStage.stage.in_(ACTIVE_STAGES),
                CandidateStage.moved_at >= since,
            )
            .distinct()
        )
        pairs.extend((int(c), int(j)) for c, j in rows.all())
    return pairs


async def _latest_stages(
    db: AsyncSession, pairs: list[tuple[int, int]]
) -> dict[tuple[int, int], PipelineStage]:
    rows = await db.execute(
        select(CandidateStage.candidate_id, CandidateStage.job_id, CandidateStage.stage)
        .where(tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(pairs))
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
    )
    return {(int(c), int(j)): stage for c, j, stage in rows.all()}


async def build_states(
    db: AsyncSession,
    pairs: list[tuple[int, int]],
    lists: dict[int, list[ClientStartDocument]],
    *,
    today: Optional[date] = None,
    active_only: bool = True,
) -> list[PairState]:
    """Stan par. Stałą liczbą zapytań, niezależnie od liczby par."""

    if not pairs:
        return []
    today = today or business_today()
    latest = await _latest_stages(db, pairs)
    if active_only:
        pairs = [p for p in pairs if latest.get(p) in ACTIVE_STAGES]
    if not pairs:
        return []

    contracts: dict[tuple[int, int], Contract] = {}
    for contract in (
        await db.scalars(
            select(Contract)
            .where(tuple_(Contract.candidate_id, Contract.job_id).in_(pairs))
            .order_by(Contract.id)
        )
    ).all():
        key = (contract.candidate_id, contract.job_id)
        current = contracts.get(key)
        if current is None or current.status in _DEAD_CONTRACT:
            contracts[key] = contract
    if active_only:
        pairs = [
            p
            for p in pairs
            if p not in contracts or contracts[p].status not in _DEAD_CONTRACT
        ]
        if not pairs:
            return []

    signed: dict[tuple[int, int], str] = {}
    number: dict[tuple[int, int], str] = {}
    for candidate_id, job_id, contract_number, signature in (
        await db.execute(
            select(
                B2BGeneratedContract.candidate_id,
                B2BGeneratedContract.job_id,
                B2BGeneratedContract.contract_number,
                B2BGeneratedContract.signature_status,
            )
            .where(
                tuple_(
                    B2BGeneratedContract.candidate_id, B2BGeneratedContract.job_id
                ).in_(pairs),
                B2BGeneratedContract.contract_status.in_(("in_progress", "active")),
            )
            .order_by(B2BGeneratedContract.id)
        )
    ).all():
        number[(candidate_id, job_id)] = contract_number
        if signature == "signed_both":
            signed[(candidate_id, job_id)] = contract_number

    rows: dict[tuple[int, int, int], PlacementStartDocument] = {
        (r.candidate_id, r.job_id, r.document_id): r
        for r in (
            await db.scalars(
                select(PlacementStartDocument).where(
                    tuple_(
                        PlacementStartDocument.candidate_id,
                        PlacementStartDocument.job_id,
                    ).in_(pairs)
                )
            )
        ).all()
    }
    jobs = {
        j.id: j
        for j in (
            await db.scalars(select(Job).where(Job.id.in_({p[1] for p in pairs})))
        ).all()
    }
    names = {
        cid: " ".join(part for part in (first, last) if part).strip()
        for cid, first, last in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_({p[0] for p in pairs})
                )
            )
        ).all()
    }
    client_names = dict(
        (
            await db.execute(
                select(Client.id, Client.name).where(
                    Client.id.in_({j.client_id for j in jobs.values() if j.client_id})
                )
            )
        ).all()
    )
    probes = {
        (cid, jid): contracts.get((cid, jid))
        or Contract(candidate_id=cid, job_id=jid, client_id=jobs[jid].client_id)
        for cid, jid in pairs
    }
    context = await load_context(db, list(probes.values()))
    people = {pair: context.people(probe) for pair, probe in probes.items()}
    # Konto, które odeszło, nie dostanie dzwonka (``emit``): sprawa idzie do DL-a.
    active = set(
        (
            await db.scalars(
                select(User.id).where(
                    User.id.in_({p[1] for p in people.values() if p[1]}),
                    User.is_active.is_(True),
                )
            )
        ).all()
    )
    calendar = await load_calendar(
        db, today - timedelta(days=60), today + timedelta(days=400)
    )

    states: list[PairState] = []
    for candidate_id, job_id in pairs:
        job = jobs[job_id]
        documents = lists.get(job.client_id or 0) or []
        if not documents:
            continue
        pair = (candidate_id, job_id)
        contract = contracts.get(pair)
        dl_id, recruiter_id, _source = people[pair]
        if recruiter_id not in active:
            recruiter_id = None
        agreement_signed = pair in signed or (
            contract is not None and contract.status in _LIVE_CONTRACT
        )
        items = tuple(
            ItemState(
                document=document,
                row=rows.get((candidate_id, job_id, document.id)),
                state=item_state(
                    document,
                    rows.get((candidate_id, job_id, document.id)),
                    agreement_signed=agreement_signed,
                ),
            )
            for document in documents
        )
        start_date = contract.start_date if contract is not None else None
        deadline = deadline_of(items, start_date, calendar)
        states.append(
            PairState(
                candidate_id=candidate_id,
                job_id=job_id,
                client_id=job.client_id,
                candidate_name=names.get(candidate_id) or f"Kandydat #{candidate_id}",
                job_title=display_title(job),
                client_name=client_names.get(job.client_id) or "",
                stage=(latest[pair].value if pair in latest else ""),
                start_date=start_date,
                contract_id=contract.id if contract is not None else None,
                agreement_number=number.get(pair),
                recruiter_id=recruiter_id,
                delivery_lead_id=dl_id,
                items=items,
                deadline=deadline,
                tone=tone_of(deadline, today),
                working=(
                    start_date is not None
                    and start_date <= today
                    and contract is not None
                    and contract.status in _LIVE_CONTRACT
                ),
                working_days_to_start=(
                    working_days_between(calendar, today, start_date)
                    if start_date is not None
                    else None
                ),
            )
        )
    return states


async def open_states(
    db: AsyncSession, *, client_ids: Optional[Iterable[int]] = None
) -> list[PairState]:
    """Pary bez kompletu, od najpilniejszej."""

    lists = await client_lists(db, client_ids)
    if not lists:
        return []
    pairs = await _pairs_in_scope(db, lists)
    states = await build_states(db, pairs, lists)
    return sorted(
        (s for s in states if not s.complete),
        key=lambda s: (s.deadline or date.max, s.candidate_id),
    )


async def pair_state(
    db: AsyncSession, candidate_id: int, job: Job
) -> Optional[PairState]:
    """Stan jednej pary. Także poza zakresem, gdy ktoś wszedł z karty kontraktu."""

    if job.client_id is None:
        return None
    lists = await client_lists(db, [job.client_id])
    if not lists:
        return None
    states = await build_states(db, [(candidate_id, job.id)], lists, active_only=False)
    return states[0] if states else None


async def card_badges(
    db: AsyncSession, job: Job, candidate_ids: Iterable[int]
) -> dict[int, dict[str, object]]:
    """``{candidate_id: start_docs}`` karty Tablicy. Klient bez listy: jedno zapytanie."""

    if job.client_id is None:
        return {}
    lists = await client_lists(db, [job.client_id])
    if not lists:
        return {}
    since = min(d.created_at for d in lists[job.client_id]) - timedelta(
        days=SINCE_GRACE_DAYS
    )
    wanted = sorted({int(c) for c in candidate_ids})
    if not wanted:
        return {}
    rows = await db.execute(
        select(CandidateStage.candidate_id)
        .where(
            CandidateStage.job_id == job.id,
            CandidateStage.candidate_id.in_(wanted),
            CandidateStage.stage.in_(ACTIVE_STAGES),
            CandidateStage.moved_at >= since,
        )
        .distinct()
    )
    pairs = [(int(c), job.id) for (c,) in rows.all()]
    states = await build_states(db, pairs, lists)
    return {
        s.candidate_id: {
            "done": s.done_count,
            "total": len(s.required),
            "missing": [i.document.name for i in s.missing],
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "deadline": s.deadline.isoformat() if s.deadline else None,
            "tone": s.tone,
        }
        for s in states
        if s.required
    }


def utcnow() -> datetime:
    return datetime.now(_TZ_UTC)


async def next_position(db: AsyncSession, client_id: int) -> int:
    current = await db.scalar(
        select(func.max(ClientStartDocument.position)).where(
            ClientStartDocument.client_id == client_id,
            ClientStartDocument.archived_at.is_(None),
        )
    )
    return int(current or 0) + 1
