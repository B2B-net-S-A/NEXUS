"""Karty bez śladu nie wiszą w „Screeningu” ani w „Biorę” (decyzja Artura
z 23.11.2026, reguła `docs/claude/rekrutacja-tablica/karty-bez-sladu-wracaja-do-nowych.md`).

Artur: „wraca do nowych po 2 dniach roboczych i jest dostępna znowu dla
wszystkich albo cofane jest biorę i też dostępna dla wszystkich”.

- Karta w „Screeningu” bez śladu pracy przez ``RETURN_WORKDAYS`` pełne dni
  robocze wraca do „Nowych” (``transition_process``, ta sama ścieżka co każdy
  ruch na serwerze) bez „Biorę” i bez blokady.
- Karta w „Nowych” wzięta przez „Biorę”/„Dzwonię”/„Przejmij” (wpis
  ``candidate_claimed``) bez śladu przez tyle samo dni traci „Biorę”.
- Osoba, która kartę trzymała, dostaje jeden dzwonek na rekrutację.

Ślad = ruch karty, „Biorę”, notatka człowieka do osoby (przy tej rekrutacji
albo bez rekrutacji, także „Nie odebrał”), zapis arkusza screeningu i umówiony
telefon (trzyma kartę do terminu + 30 min, jak blokada w ``screening_calls``).
Dni liczą się kalendarzem firmy: dzień śladu = 0, potem dwa pełne dni robocze,
karta wraca trzeciego dnia roboczego (lustro terminu porcji,
``review_batch.close_window_start``).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_date, is_business_day
from app.models.activity import Activity
from app.models.calendar_event import (
    BOOKED_CALL_LOCATION,
    CalendarEvent,
    EventStatus,
    EventType,
)
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User
from app.services import candidate_claim
from app.services.board_stage_badges import (
    NEW_COLUMN,
    SCREENING_COLUMN,
    board_column_for,
)
from app.services.pipeline_latest import latest_stage_ids

if TYPE_CHECKING:
    from app.models.notification import NotificationType

logger = logging.getLogger(__name__)

RETURN_WORKDAYS = 2
# Ile dni roboczych Tablica pokazuje powrót („Wróciły od Ciebie”, 26.11.2026).
# Pięć dni obejmuje też pierwszą falę z 24.11.2026 przez tydzień po wdrożeniu.
RETURNED_VISIBLE_WORKDAYS = 5
KIND_SCREENING = "screening"
KIND_CLAIM = "claim"
SOURCE = "screening_stale_return"
ACTION_RETURNED = "stale_card_returned"
# Znacznik w ``entry_meta`` osoby od systemu: porcja nie oddaje jej
# z powrotem jako nowej (``review_batch.in_batch``), decyzja „Do screeningu”
# sprzed powrotu przestaje być zaległością (``review_batch._decisions``),
# a termin decyzji w „Nowych” liczy się od powrotu (``autofill_decisions``).
META_RETURNED_AT = "returned_to_pool_at"
NOTE = "NEXUS: 2 dni robocze bez śladu — karta wróciła do „Nowych” dla wszystkich."
# Bezpiecznik jednego przebiegu (pierwszy przebieg na produkcji ma setki kart).
MAX_PER_RUN = 200
# Oddanie osoby z blokadą (25.11.2026) to „Biorę” osoby, która ją dostała
# (``details.to_user_id``), nie tej, która kliknęła.
_HANDED_OVER = "candidate_claim_handed_over"
_CLAIM_ACTIONS = ("candidate_claimed", _HANDED_OVER)
_SHEET_ACTION = "screening_answered"
_BOOKED_HOLD = timedelta(minutes=30)
# Klucze decyzji „Dzwonię” i porcji, które karta wracająca do puli traci.
_RELEASED_META_KEYS = ("decided_at", "decided_by", "decision", "review_owner_id")


@dataclass(frozen=True)
class StaleCard:
    """Karta, której dotyczy reguła: w „Screeningu” albo w „Nowych” z „Biorę”."""

    job_id: int
    candidate_id: int
    process_id: int
    stage_id: int
    kind: str
    # Od kiedy liczymy (wejście na etap albo „Biorę”); ślady są późniejsze.
    since: datetime
    # Kto dostaje dzwonek: osoba z „Biorę”, a w „Screeningu” bez niej osoba,
    # która kartę tam przesunęła.
    holder_id: Optional[int]
    claimed_by: Optional[int] = None
    stage_ids: tuple[int, ...] = field(default=())

    @property
    def pair(self) -> tuple[int, int]:
        return (self.job_id, self.candidate_id)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _is_workday(day: date) -> bool:
    return is_business_day(datetime.combine(day, time(12), tzinfo=ZoneInfo(DEFAULT_TZ)))


def return_day(last_trace: datetime) -> date:
    """Dzień roboczy, w którym karta wraca: dzień śladu, dwa pełne dni robocze
    ciszy, potem trzeci. Ślad we wtorek przed świętem w środę → wraca w poniedziałek."""
    day = business_date(_aware(last_trace))
    left = RETURN_WORKDAYS + 1
    while left:
        day += timedelta(days=1)
        if _is_workday(day):
            left -= 1
    return day


def is_due(last_trace: datetime, today: date) -> bool:
    return return_day(last_trace) <= today


async def _new_column_defs(
    db: AsyncSession, template_ids: Iterable[int]
) -> dict[int, int]:
    """Etap „Nowi” każdego szablonu: pierwszy etap z kodem ``new``, który
    Tablica pokazuje w kolumnie „Nowi” (etapy „new” bywają innymi kolumnami,
    np. „Wysłać do Cpro”)."""
    ids = sorted({int(t) for t in template_ids if t is not None})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                PipelineStageDef.id,
                PipelineStageDef.template_id,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .where(
                PipelineStageDef.template_id.in_(ids),
                PipelineStageDef.legacy_enum_value == PipelineStage.new.value,
                PipelineStageDef.is_terminal.is_(False),
            )
            .order_by(PipelineStageDef.order, PipelineStageDef.id)
        )
    ).all()
    out: dict[int, int] = {}
    for def_id, template_id, name, category, terminal_type in rows:
        if template_id in out:
            continue
        column = board_column_for(
            name,
            PipelineStage.new.value,
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal_type, "value", terminal_type),
        )
        if column == NEW_COLUMN:
            out[int(template_id)] = int(def_id)
    return out


async def published_job_ids(
    db: AsyncSession, job_ids: Optional[Iterable[int]] = None
) -> list[int]:
    """Rekrutacje, w których działa reguła: opublikowane (bez zamkniętych
    i szkiców). Zamknięcie zostawia osoby tam, gdzie stały."""
    stmt = select(Job.id).where(Job.status == JobStatus.published)
    if job_ids is not None:
        ids = sorted({int(j) for j in job_ids})
        if not ids:
            return []
        stmt = stmt.where(Job.id.in_(ids))
    return [int(j) for j in (await db.scalars(stmt)).all()]


async def cards_for_jobs(
    db: AsyncSession, job_ids: Optional[Iterable[int]] = None
) -> list[StaleCard]:
    """Karty w „Screeningu” i karty w „Nowych” z „Biorę” w opublikowanych
    rekrutacjach. ``None`` = wszystkie opublikowane."""
    jobs = await published_job_ids(db, job_ids)
    if not jobs:
        return []
    latest = latest_stage_ids(job_ids=jobs)
    rows = (
        await db.execute(
            select(
                CandidateStage.id,
                CandidateStage.job_id,
                CandidateStage.candidate_id,
                CandidateStage.stage,
                CandidateStage.moved_at,
                CandidateStage.moved_by,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(CandidateStage.id.in_(select(latest.c.latest_id)))
        )
    ).all()
    columns: dict[tuple[int, int], tuple[str, int, datetime, Optional[int]]] = {}
    for sid, job_id, cid, stage, moved_at, moved_by, name, category, ttype in rows:
        column = board_column_for(
            name,
            getattr(stage, "value", stage),
            category=getattr(category, "value", category),
            terminal_type=getattr(ttype, "value", ttype),
        )
        if column in (NEW_COLUMN, SCREENING_COLUMN):
            columns[(int(job_id), int(cid))] = (column, int(sid), moved_at, moved_by)
    if not columns:
        return []
    pair_jobs = sorted({j for j, _ in columns})
    pair_cands = sorted({c for _, c in columns})
    processes: dict[tuple[int, int], RecruitmentProcess] = {}
    for process in (
        await db.scalars(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.job_id.in_(pair_jobs),
                RecruitmentProcess.candidate_id.in_(pair_cands),
            )
            .order_by(
                RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc()
            )
        )
    ).all():
        processes.setdefault((process.job_id, process.candidate_id), process)
    stage_ids: dict[tuple[int, int], list[int]] = defaultdict(list)
    for sid, job_id, cid in (
        await db.execute(
            select(
                CandidateStage.id, CandidateStage.job_id, CandidateStage.candidate_id
            ).where(
                CandidateStage.job_id.in_(pair_jobs),
                CandidateStage.candidate_id.in_(pair_cands),
            )
        )
    ).all():
        if (job_id, cid) in columns:
            stage_ids[(int(job_id), int(cid))].append(int(sid))
    # „Biorę” na karcie w „Nowych”: ostatni wpis ``candidate_claimed`` osoby,
    # która trzyma kartę. Ręczne dodanie też zakłada blokadę, ale bez wpisu —
    # taka karta zostaje u dodającego (``biore-zmienia-osobe-karty.md``).
    claim_at: dict[tuple[int, int], tuple[int, datetime]] = {}
    new_stage_owner = {
        sid: pair
        for pair, (column, _sid, _at, _by) in columns.items()
        if column == NEW_COLUMN
        and (p := processes.get(pair)) is not None
        and p.claimed_by_user_id is not None
        for sid in stage_ids.get(pair, ())
    }
    if new_stage_owner:
        for entity_id, action, actor_id, details, created_at in (
            await db.execute(
                select(
                    Activity.entity_id,
                    Activity.action,
                    Activity.user_id,
                    Activity.details,
                    Activity.created_at,
                ).where(
                    Activity.entity_type == "pipeline",
                    Activity.action.in_(_CLAIM_ACTIONS),
                    Activity.entity_id.in_(sorted(new_stage_owner)),
                )
            )
        ).all():
            pair = new_stage_owner[entity_id]
            user_id = (
                (details or {}).get("to_user_id")
                if action == _HANDED_OVER
                else actor_id
            )
            if user_id is None:
                continue
            prev = claim_at.get(pair)
            if prev is None or created_at > prev[1]:
                claim_at[pair] = (int(user_id), created_at)
    out: list[StaleCard] = []
    for pair, (column, sid, moved_at, moved_by) in columns.items():
        process = processes.get(pair)
        if (
            process is None
            or process.status != ProcessStatus.open
            or process.voided_at is not None
        ):
            continue
        claimer = process.claimed_by_user_id
        if column == SCREENING_COLUMN:
            out.append(
                StaleCard(
                    job_id=pair[0],
                    candidate_id=pair[1],
                    process_id=process.id,
                    stage_id=sid,
                    kind=KIND_SCREENING,
                    since=moved_at,
                    holder_id=claimer if claimer is not None else moved_by,
                    claimed_by=claimer,
                    stage_ids=tuple(stage_ids.get(pair, ())),
                )
            )
            continue
        claim = claim_at.get(pair)
        if claimer is None or claim is None or claim[0] != claimer:
            continue
        if process.opened_at is not None and claim[1] < process.opened_at:
            continue
        out.append(
            StaleCard(
                job_id=pair[0],
                candidate_id=pair[1],
                process_id=process.id,
                stage_id=sid,
                kind=KIND_CLAIM,
                since=max(claim[1], moved_at),
                holder_id=claimer,
                claimed_by=claimer,
                stage_ids=tuple(stage_ids.get(pair, ())),
            )
        )
    return out


async def last_traces(
    db: AsyncSession, cards: Sequence[StaleCard]
) -> dict[tuple[int, int], datetime]:
    """Ostatni ślad pracy każdej karty (co najmniej ``since``)."""
    out: dict[tuple[int, int], datetime] = {c.pair: _aware(c.since) for c in cards}
    if not cards:
        return out

    def bump(pair: tuple[int, int], moment: Optional[datetime]) -> None:
        if moment is None or pair not in out:
            return
        moment = _aware(moment)
        if moment > out[pair]:
            out[pair] = moment

    jobs = sorted({c.job_id for c in cards})
    cands = sorted({c.candidate_id for c in cards})
    by_candidate: dict[int, list[int]] = defaultdict(list)
    for c in cards:
        by_candidate[c.candidate_id].append(c.job_id)
    # Notatki człowieka (także „Nie odebrał” i odpowiedzi w wątku). Notatka
    # z importu liczy się datą źródła, nie datą importu.
    noted = func.coalesce(Note.source_created_at, Note.created_at)
    for cid, note_job, at in (
        await db.execute(
            select(Note.candidate_id, Note.job_id, func.max(noted))
            .where(
                Note.candidate_id.in_(cands),
                Note.author_id.is_not(None),
                or_(Note.job_id.in_(jobs), Note.job_id.is_(None)),
            )
            .group_by(Note.candidate_id, Note.job_id)
        )
    ).all():
        targets = by_candidate.get(cid, []) if note_job is None else [note_job]
        for job_id in targets:
            bump((job_id, cid), at)
    # Ruch karty, „Biorę” i zapis arkusza — po wierszach etapów pary.
    pair_of_stage = {sid: c.pair for c in cards for sid in c.stage_ids}
    if pair_of_stage:
        stage_list = sorted(pair_of_stage)
        for sid, at in (
            await db.execute(
                select(CandidateStage.id, CandidateStage.moved_at).where(
                    CandidateStage.id.in_(stage_list)
                )
            )
        ).all():
            bump(pair_of_stage[sid], at)
        for entity_type, entity_id, at in (
            await db.execute(
                select(
                    Activity.entity_type,
                    Activity.entity_id,
                    func.max(Activity.created_at),
                )
                .where(
                    or_(
                        (Activity.entity_type == "pipeline")
                        & Activity.action.in_(_CLAIM_ACTIONS),
                        (Activity.entity_type == "candidate_stage")
                        & (Activity.action == _SHEET_ACTION),
                    ),
                    Activity.entity_id.in_(stage_list),
                    Activity.user_id.is_not(None) | (Activity.action == _SHEET_ACTION),
                )
                .group_by(Activity.entity_type, Activity.entity_id)
            )
        ).all():
            bump(pair_of_stage[entity_id], at)
    # Umówiony telefon: zapis terminu to ślad, a otwarty termin trzyma kartę
    # do startu + 30 min (``screening_calls.hold_until``).
    for job_id, cid, created_at, start, status in (
        await db.execute(
            select(
                CalendarEvent.job_id,
                CalendarEvent.candidate_id,
                CalendarEvent.created_at,
                CalendarEvent.start_time,
                CalendarEvent.status,
            ).where(
                CalendarEvent.event_type == EventType.screening,
                CalendarEvent.location == BOOKED_CALL_LOCATION,
                CalendarEvent.job_id.in_(jobs),
                CalendarEvent.candidate_id.in_(cands),
            )
        )
    ).all():
        bump((job_id, cid), created_at)
        if status == EventStatus.scheduled and start is not None:
            bump((job_id, cid), _aware(start) + _BOOKED_HOLD)
    return out


async def return_days_for_jobs(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, dict[int, date]]:
    """Dzień powrotu kart Tablic: ``{job_id: {candidate_id: dzień}}``.
    Ta sama reguła co automat, więc karta mówi prawdę o swoim powrocie."""
    ids = sorted({int(j) for j in job_ids})
    out: dict[int, dict[int, date]] = {j: {} for j in ids}
    cards = await cards_for_jobs(db, ids)
    traces = await last_traces(db, cards)
    for card in cards:
        out[card.job_id][card.candidate_id] = return_day(traces[card.pair])
    return out


@dataclass(frozen=True)
class ReturnedCard:
    """Karta, którą automat oddał ze „Screeningu” i która dalej stoi w „Nowych”
    (26.11.2026): grupa „Wróciły od Ciebie” u osoby, która ją trzymała, i
    znacznik „wróciła ze Screeningu” u pozostałych."""

    returned_at: datetime
    holder_id: Optional[int]
    # Wejście do „Screeningu” przed powrotem (poprzedni wiersz etapu pary).
    screening_since: Optional[datetime]


def returned_window_start(now: datetime) -> date:
    """Pierwszy dzień, z którego powroty jeszcze widać: ``RETURNED_VISIBLE_WORKDAYS``
    dni roboczych wstecz od dziś (dziś się liczy)."""
    day = business_date(_aware(now))
    left = RETURNED_VISIBLE_WORKDAYS - 1
    while left:
        day -= timedelta(days=1)
        if _is_workday(day):
            left -= 1
    return day


async def returned_cards_for_jobs(
    db: AsyncSession, job_ids: Iterable[int], *, now: Optional[datetime] = None
) -> dict[int, dict[int, ReturnedCard]]:
    """Powroty ze „Screeningu” z ostatnich dni roboczych, których nikt jeszcze
    nie ruszył: wpis ``stale_card_returned`` wskazuje wiersz etapu, który jest
    dziś ostatnim wierszem pary. ``{job_id: {candidate_id: ReturnedCard}}``."""
    ids = sorted({int(j) for j in job_ids})
    out: dict[int, dict[int, ReturnedCard]] = {j: {} for j in ids}
    if not ids:
        return out
    moment = now or datetime.now(timezone.utc)
    start = returned_window_start(moment)
    since = datetime.combine(start, time(0), tzinfo=ZoneInfo(DEFAULT_TZ))
    latest = latest_stage_ids(job_ids=ids)
    rows = (
        await db.execute(
            select(Activity.entity_id, Activity.details, Activity.created_at)
            .where(
                Activity.entity_type == "pipeline",
                Activity.action == ACTION_RETURNED,
                Activity.created_at >= since,
                Activity.entity_id.in_(select(latest.c.latest_id)),
            )
            .order_by(Activity.created_at)
        )
    ).all()
    found: dict[tuple[int, int], tuple[int, Optional[int], datetime]] = {}
    for stage_id, details, created_at in rows:
        details = details or {}
        if details.get("kind") != KIND_SCREENING:
            continue
        try:
            pair = (int(details["job_id"]), int(details["candidate_id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if pair[0] not in out:
            continue
        holder = details.get("holder_user_id")
        found[pair] = (
            int(stage_id),
            int(holder) if holder is not None else None,
            _aware(created_at),
        )
    if not found:
        return out
    # Wejście do „Screeningu”: ostatni wcześniejszy wiersz etapu pary.
    before: dict[tuple[int, int], datetime] = {}
    for job_id, cid, sid, moved_at in (
        await db.execute(
            select(
                CandidateStage.job_id,
                CandidateStage.candidate_id,
                CandidateStage.id,
                CandidateStage.moved_at,
            ).where(
                CandidateStage.job_id.in_(sorted({j for j, _ in found})),
                CandidateStage.candidate_id.in_(sorted({c for _, c in found})),
            )
        )
    ).all():
        pair = (int(job_id), int(cid))
        hit = found.get(pair)
        if hit is None or sid == hit[0] or moved_at is None:
            continue
        moved = _aware(moved_at)
        if moved < hit[2] and (pair not in before or moved > before[pair]):
            before[pair] = moved
    for pair, (_sid, holder, at) in found.items():
        out[pair[0]][pair[1]] = ReturnedCard(
            returned_at=at, holder_id=holder, screening_since=before.get(pair)
        )
    return out


def _released_meta(
    meta: object, *, now: datetime, kind: str, holder: Optional[int]
) -> dict:
    base = dict(meta) if isinstance(meta, dict) else {}
    for key in _RELEASED_META_KEYS:
        base.pop(key, None)
    base[META_RETURNED_AT] = now.isoformat()
    base["returned_from"] = kind
    if holder is not None:
        base["returned_holder"] = holder
    return base


def returned_after(meta: object, moment: datetime) -> bool:
    """Karta wróciła do puli po ``moment`` (np. po decyzji „Do screeningu”)."""
    if not isinstance(meta, dict) or not meta.get(META_RETURNED_AT):
        return False
    try:
        at = datetime.fromisoformat(str(meta[META_RETURNED_AT]))
    except ValueError:
        return False
    return _aware(at) >= _aware(moment)


def returned_at(meta: object) -> Optional[datetime]:
    if not isinstance(meta, dict) or not meta.get(META_RETURNED_AT):
        return None
    try:
        return _aware(datetime.fromisoformat(str(meta[META_RETURNED_AT])))
    except ValueError:
        return None


@dataclass
class SweepResult:
    returned: int = 0
    released: int = 0
    skipped: int = 0
    # (osoba, rekrutacja) → kandydaci, do dzwonka po commicie przebiegu.
    bells: dict[tuple[int, int], list[int]] = field(default_factory=dict)
    jobs: set[int] = field(default_factory=set)

    def as_dict(self) -> dict[str, int]:
        return {
            "returned": self.returned,
            "released": self.released,
            "skipped": self.skipped,
            "bells": len(self.bells),
        }


async def due_cards(
    db: AsyncSession, *, now: datetime, job_ids: Optional[Iterable[int]] = None
) -> list[tuple[StaleCard, datetime]]:
    """Karty, którym minęły dwa pełne dni robocze bez śladu, od najstarszego śladu."""
    cards = await cards_for_jobs(db, job_ids)
    traces = await last_traces(db, cards)
    today = business_date(now)
    due = [(c, traces[c.pair]) for c in cards if is_due(traces[c.pair], today)]
    return sorted(due, key=lambda item: (item[1], item[0].job_id, item[0].candidate_id))


async def _apply(
    db: AsyncSession,
    card: StaleCard,
    *,
    now: datetime,
    new_defs: Mapping[int, int],
    template_of: Mapping[int, Optional[int]],
) -> bool:
    """Oddaje jedną kartę. ``False`` = karta się zmieniła od odczytu (pomijamy)."""
    from app.services.priority_work_policy import PriorityWorkLocked
    from app.services.recruitment_process_commands import transition_process

    locked = await db.scalar(
        select(Candidate.id).where(Candidate.id == card.candidate_id).with_for_update()
    )
    if locked is None:
        return False
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == card.candidate_id,
            CandidateStage.job_id == card.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    process = await db.scalar(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == card.candidate_id,
            RecruitmentProcess.job_id == card.job_id,
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
        .with_for_update()
    )
    if (
        latest is None
        or latest.id != card.stage_id
        or process is None
        or process.id != card.process_id
        or process.status != ProcessStatus.open
        or process.claimed_by_user_id != card.claimed_by
    ):
        return False
    moved_stage_id = latest.id
    if card.kind == KIND_SCREENING:
        template_id = template_of.get(card.job_id)
        try:
            stage = await transition_process(
                db,
                candidate_id=card.candidate_id,
                job_id=card.job_id,
                stage=PipelineStage.new,
                stage_def_id=new_defs.get(template_id) if template_id else None,
                actor_user_id=None,
                moved_at=now,
                require_existing=True,
                notes=NOTE,
            )
        except PriorityWorkLocked:
            return False
        moved_stage_id = stage.id
        db.add(
            Activity(
                entity_type="pipeline",
                entity_id=stage.id,
                action="stage_changed",
                user_id=None,
                details={
                    "candidate_id": card.candidate_id,
                    "job_id": card.job_id,
                    "from_stage": getattr(latest.stage, "value", latest.stage),
                    "from_stage_def_id": latest.stage_def_id,
                    "stage": PipelineStage.new.value,
                    "stage_def_id": stage.stage_def_id,
                    "source": SOURCE,
                },
            )
        )
    candidate_claim.clear_claim(process)
    if process.entry_source == candidate_claim.ENTRY_SYSTEM:
        # Nowy słownik: JSONB bez MutableDict nie widzi zmiany w miejscu.
        process.entry_meta = _released_meta(
            process.entry_meta, now=now, kind=card.kind, holder=card.holder_id
        )
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=moved_stage_id,
            action=ACTION_RETURNED,
            user_id=None,
            details={
                "candidate_id": card.candidate_id,
                "job_id": card.job_id,
                "kind": card.kind,
                "holder_user_id": card.holder_id,
            },
        )
    )
    return True


async def run_sweep(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    limit: int = MAX_PER_RUN,
    job_ids: Optional[Iterable[int]] = None,
) -> SweepResult:
    """Jeden przebieg: oddaje zaległe karty. Nie commituje; dzwonki po commicie
    (``send_bells``). Działa tylko w dzień roboczy, więc weekend i święto
    niczego nie oddają, a dzień powrotu z ``return_day`` jest zawsze roboczy."""
    moment = now or datetime.now(timezone.utc)
    result = SweepResult()
    if not is_business_day(moment):
        return result
    due = (await due_cards(db, now=moment, job_ids=job_ids))[:limit]
    if not due:
        return result
    template_of = {
        int(job_id): template_id
        for job_id, template_id in (
            await db.execute(
                select(Job.id, Job.pipeline_template_id).where(
                    Job.id.in_(sorted({c.job_id for c, _ in due}))
                )
            )
        ).all()
    }
    from app.models.pipeline_template import PipelineTemplate

    default_template = await db.scalar(
        select(PipelineTemplate.id)
        .where(PipelineTemplate.is_default.is_(True))
        .order_by(PipelineTemplate.id)
        .limit(1)
    )
    template_of = {j: t or default_template for j, t in template_of.items()}
    new_defs = await _new_column_defs(db, template_of.values())
    for card, _trace in due:
        try:
            async with db.begin_nested():
                applied = await _apply(
                    db, card, now=moment, new_defs=new_defs, template_of=template_of
                )
        except Exception:  # noqa: BLE001 — jedna karta nie zatrzymuje przebiegu
            logger.exception(
                "screening_stale: karta %s/%s nie wróciła",
                card.job_id,
                card.candidate_id,
            )
            applied = False
        if not applied:
            result.skipped += 1
            continue
        if card.kind == KIND_SCREENING:
            result.returned += 1
        else:
            result.released += 1
        result.jobs.add(card.job_id)
        if card.holder_id is not None:
            result.bells.setdefault((card.holder_id, card.job_id), []).append(
                card.candidate_id
            )
    return result


def people(count: int) -> str:
    """„1 osoba”, „3 osoby”, „5 osób”, „22 osoby” — odmiana po polsku."""
    if count == 1:
        return "1 osoba"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} osoby"
    return f"{count} osób"


_WEEKDAY_ACC = (
    "poniedziałek",
    "wtorek",
    "środę",
    "czwartek",
    "piątek",
    "sobotę",
    "niedzielę",
)
# Ostrzeżenie dzień wcześniej (26.11.2026): w dzień roboczy od 8:00 do 20:00.
WARN_FROM_HOUR = 8
WARN_UNTIL_HOUR = 20
STOP_HINT = "Notatka, „Nie odebrał” albo umówiony telefon zatrzyma kartę u Ciebie."


def _day_start(moment: datetime) -> datetime:
    """Północ dnia kalendarzowego w Warszawie (granica dziennego dzwonka)."""
    local = _aware(moment).astimezone(ZoneInfo(DEFAULT_TZ))
    return datetime.combine(local.date(), time(0), tzinfo=ZoneInfo(DEFAULT_TZ))


def next_workday(day: date) -> date:
    day += timedelta(days=1)
    while not _is_workday(day):
        day += timedelta(days=1)
    return day


def returned_bell_title(returned: int, released: int) -> str:
    if returned:
        return f"Wróciło do „Nowych”: {people(returned)}"
    return f"„Biorę” wygasło: {people(released)}"


def soon_bell_title(count: int, today: date, day: date) -> str:
    when = (
        "Jutro"
        if day == today + timedelta(days=1)
        else f"W {_WEEKDAY_ACC[day.weekday()]}"
    )
    return f"{when} wrócą do „Nowych”: {people(count)}"


def _job_lines(
    by_job: Mapping[int, Sequence[int]],
    titles: Mapping[int, str],
    names: Mapping[int, str],
) -> list[str]:
    """„Tytuł rekrutacji: Jan K., Ola M.” — od rekrutacji z największą liczbą kart."""
    lines = []
    for job_id, cids in sorted(by_job.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        shown = ", ".join(names.get(c, "Kandydat") for c in cids)
        lines.append(f"{titles.get(job_id, 'Rekrutacja')} ({len(cids)}): {shown}")
    return lines


async def _names(db: AsyncSession, candidate_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted(set(candidate_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname).where(
                Candidate.id.in_(ids)
            )
        )
    ).all()
    return {cid: f"{n or ''} {ln or ''}".strip() or "Kandydat" for cid, n, ln in rows}


async def _titles(db: AsyncSession, job_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted(set(job_ids))
    if not ids:
        return {}
    return dict(
        (await db.execute(select(Job.id, Job.title).where(Job.id.in_(ids)))).all()
    )


async def _upsert_daily(
    db: AsyncSession,
    *,
    user_id: int,
    ntype: NotificationType,
    title: str,
    message: str,
    link: str,
    refresh: bool = True,
) -> bool:
    """Jeden dzwonek dziennie na osobę: dzisiejszy aktualizuje treść i wraca
    jako nieprzeczytany (``refresh=False``: zostaje, jaki był), a gdy go nie ma
    — ``emit`` (bramka odbiorcy, dedup). „Dziś” z zegara, nie z ``--as-of``:
    dzwonek ma czas zapisu. Szukamy po osobie, której dzwonek dotyczy
    (``related_entity``), nie po odbiorcy: przy zastępstwie ``emit`` zapisuje
    wiersz na zastępcę."""
    from app.models.notification import Notification
    from app.services.notification_triggers import emit

    existing = await db.scalar(
        select(Notification)
        .where(
            Notification.notification_type == ntype,
            Notification.related_entity_type == "user",
            Notification.related_entity_id == user_id,
            Notification.created_at >= _day_start(datetime.now(timezone.utc)),
        )
        .order_by(Notification.id.desc())
        .limit(1)
    )
    if existing is not None:
        if not refresh or (existing.title == title and existing.message == message):
            return False
        existing.title = title
        existing.message = message
        existing.link = link
        existing.is_read = False
        # „Przed chwilą” w okienku zamiast czasu pierwszego przebiegu.
        existing.created_at = datetime.now(timezone.utc)
        return True
    notification = await emit(
        db,
        user_id=user_id,
        title=title,
        message=message,
        ntype=ntype,
        related_entity_type="user",
        related_entity_id=user_id,
        link=link,
    )
    return notification is not None


async def send_bells(db: AsyncSession, result: SweepResult) -> int:
    """Dzwonek „wróciło do Nowych” (26.11.2026): jeden na osobę dziennie, liczony
    ze WSZYSTKICH dzisiejszych powrotów (wpisy ``stale_card_returned``), a nie
    z jednego przebiegu. Przebieg oddaje najwyżej 200 kart, więc pierwsza fala
    szła w kilku przebiegach, a dzienny dedup puszczał tylko dzwonek z pierwszego
    (24.11: 593 z 1 632 kart bez dzwonka). „Dziś” z zegara, bo wpisy powrotu
    mają czas zapisu (także przy ``--as-of`` na stagingu). Nigdy nie rzuca."""
    from app.models.notification import NotificationType

    holders = sorted({user_id for user_id, _job in result.bells})
    if not holders:
        return 0
    moment = datetime.now(timezone.utc)
    sent = 0
    try:
        rows = (
            await db.execute(
                select(Activity.details).where(
                    Activity.entity_type == "pipeline",
                    Activity.action == ACTION_RETURNED,
                    Activity.created_at >= _day_start(moment),
                )
            )
        ).all()
    except Exception:  # noqa: BLE001
        logger.exception(
            "screening_stale: odczyt dzisiejszych powrotów nie powiódł się"
        )
        return 0
    # osoba → rodzaj → rekrutacja → kandydaci (bez powtórzeń, w kolejności powrotu)
    today: dict[int, dict[str, dict[int, list[int]]]] = {}
    wanted = set(holders)
    for (details,) in rows:
        details = details or {}
        try:
            holder = int(details["holder_user_id"])
            job_id = int(details["job_id"])
            cid = int(details["candidate_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if holder not in wanted:
            continue
        kind = details.get("kind") or KIND_SCREENING
        bucket = (
            today.setdefault(holder, {}).setdefault(kind, {}).setdefault(job_id, [])
        )
        if cid not in bucket:
            bucket.append(cid)
    all_jobs = {j for kinds in today.values() for jobs in kinds.values() for j in jobs}
    all_cands = {
        c
        for kinds in today.values()
        for jobs in kinds.values()
        for cids in jobs.values()
        for c in cids
    }
    titles = await _titles(db, all_jobs)
    names = await _names(db, all_cands)
    for user_id in holders:
        kinds = today.get(user_id)
        if not kinds:
            continue
        try:
            user = await db.get(User, user_id)
            if user is None or not user.is_active:
                continue
            returned = kinds.get(KIND_SCREENING, {})
            released = kinds.get(KIND_CLAIM, {})
            n_returned = sum(len(c) for c in returned.values())
            n_released = sum(len(c) for c in released.values())
            parts: list[str] = []
            if returned:
                parts.append(
                    "2 dni robocze bez śladu w „Screeningu”. Stoją w „Nowych” "
                    "i bierze je każdy; chcesz dalej dzwonić, weź ponownie:"
                )
                parts += _job_lines(returned, titles, names)
            if released:
                parts.append("„Biorę” wygasło (2 dni robocze bez śladu):")
                parts += _job_lines(released, titles, names)
            main = returned or released
            top_job = sorted(main.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0][0]
            async with db.begin_nested():
                changed = await _upsert_daily(
                    db,
                    user_id=user_id,
                    ntype=NotificationType.screening_cards_returned,
                    title=returned_bell_title(n_returned, n_released),
                    message="\n".join(parts),
                    link=f"/jobs/{top_job}",
                )
            if changed:
                sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("screening_stale: dzwonek do %s nie poszedł", user_id)
    return sent


async def soon_cards(
    db: AsyncSession, *, now: datetime, job_ids: Optional[Iterable[int]] = None
) -> tuple[date, dict[int, list[StaleCard]]]:
    """Karty w „Screeningu”, które wrócą następnego dnia roboczego, po osobie,
    która je trzyma (``holder_id``) — ta sama reguła co automat."""
    day = next_workday(business_date(now))
    cards = [c for c in await cards_for_jobs(db, job_ids) if c.kind == KIND_SCREENING]
    traces = await last_traces(db, cards)
    out: dict[int, list[StaleCard]] = defaultdict(list)
    for card in cards:
        if card.holder_id is not None and return_day(traces[card.pair]) == day:
            out[card.holder_id].append(card)
    return day, dict(out)


async def send_soon_bells(
    db: AsyncSession, *, now: datetime, job_ids: Optional[Iterable[int]] = None
) -> int:
    """Poranne ostrzeżenie (26.11.2026): „Jutro wrócą do „Nowych”: N osób” —
    jeden dzwonek na osobę dziennie. Tylko w dzień roboczy. Nigdy nie rzuca."""
    from app.models.notification import NotificationType

    if not is_business_day(now):
        return 0
    try:
        day, by_holder = await soon_cards(db, now=now, job_ids=job_ids)
    except Exception:  # noqa: BLE001
        logger.exception("screening_stale: ostrzeżenie — odczyt kart nie powiódł się")
        return 0
    if not by_holder:
        return 0
    titles = await _titles(db, {c.job_id for cs in by_holder.values() for c in cs})
    names = await _names(db, {c.candidate_id for cs in by_holder.values() for c in cs})
    today = business_date(now)
    sent = 0
    for user_id, cards in sorted(by_holder.items()):
        try:
            user = await db.get(User, user_id)
            if user is None or not user.is_active:
                continue
            by_job: dict[int, list[int]] = defaultdict(list)
            for card in sorted(cards, key=lambda c: (c.job_id, c.candidate_id)):
                by_job[card.job_id].append(card.candidate_id)
            top_job = sorted(by_job.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0][0]
            async with db.begin_nested():
                changed = await _upsert_daily(
                    db,
                    user_id=user_id,
                    ntype=NotificationType.screening_cards_return_soon,
                    title=soon_bell_title(len(cards), today, day),
                    message="\n".join([STOP_HINT, *_job_lines(by_job, titles, names)]),
                    link=f"/jobs/{top_job}",
                    # Po restarcie wieczorem (wdrożenia od 18:00) poranne
                    # ostrzeżenie zostaje, jakie było — bez drugiego dzwonka.
                    refresh=False,
                )
            if changed:
                sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("screening_stale: ostrzeżenie do %s nie poszło", user_id)
    return sent


def warn_due(now: datetime) -> bool:
    """Pora na poranne ostrzeżenie: dzień roboczy, 8:00–20:00 w Warszawie."""
    local = _aware(now).astimezone(ZoneInfo(DEFAULT_TZ))
    return is_business_day(now) and WARN_FROM_HOUR <= local.hour < WARN_UNTIL_HOUR


async def warn_once_safely(now: Optional[datetime] = None) -> Optional[int]:
    """Własna sesja i commit; nigdy nie rzuca. ``None`` = błąd."""
    from app.core.database import AsyncSessionLocal

    moment = now or datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as db:
            sent = await send_soon_bells(db, now=moment)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("screening_stale: ostrzeżenie nie powiodło się")
        return None
    if sent:
        logger.info("screening_stale: ostrzeżenia %s", sent)
    return sent


async def run_once_safely(now: Optional[datetime] = None) -> Optional[dict[str, int]]:
    """Własna sesja, commit, dzwonki i odświeżenie Tablic po commicie; nigdy nie rzuca."""
    from app.core.database import AsyncSessionLocal
    from app.services.pipeline_realtime import broadcast_pipeline_changed

    try:
        async with AsyncSessionLocal() as db:
            result = await run_sweep(db, now=now)
            await db.commit()
            if result.bells:
                await send_bells(db, result)
                await db.commit()
            for job_id in sorted(result.jobs):
                await broadcast_pipeline_changed(db, job_id, None)
    except Exception:  # noqa: BLE001 — pętla nie może przez to stanąć
        logger.exception("screening_stale: przebieg nie powiódł się")
        return None
    counts = result.as_dict()
    if result.returned or result.released:
        logger.info("screening_stale: %s", counts)
    return counts
