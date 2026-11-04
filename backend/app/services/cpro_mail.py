"""Zmiany z maili CPro (Nordea) wchodzą do NEXUSA same (decyzje Artura 02.11.2026).

Pomiar 12.10–02.11 w skrzynkach obu Delivery Leadów Nordei: 24 rekrutacje
zamknięte ręcznie po mailu (16 w ciągu 15 minut), dwie otwarte dalej mimo
zamknięcia w CPro, 40 ze 115 odrzuconych przez klienta nadal „w toku”.

* zamknięty request → NEXUS zamyka rekrutacje z tym numerem i pisze (dzwonek
  i mail) do każdego rekrutera z kartą w toku; osoba w umowie albo zatrudniona
  zatrzymuje zamknięcie i pyta Delivery Leada;
* odrzucenie → karta do „Zamknięci” jako „przez klienta”; kandydat nie dostaje
  nic, prowadzący dostaje dzwonek;
* rozmowa zamówiona, wycofana, zmienione terminy → tylko dzwonek, bo terminy
  są wyłącznie w CPro;
* każdy mail daje jeden wiersz dziennika, a przed działaniem sprawdzamy nadawcę
  w nagłówkach Exchange. Domena nadawcy ma DMARC ``p=none``, więc nikt inny nie
  odrzuci podszytego maila.

Reguła: ``docs/claude/integracje/cpro-maile-nordei.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, Sequence
from urllib.parse import quote

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.cpro_mail import CproMailEvent
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.m365 import Email, EmailDirection, M365Connection
from app.models.notification import NotificationType
from app.models.pipeline_template import (
    PipelineStageDef,
    RejectionReason,
    TerminalType,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import cpro_mail_parse as parsing
from app.services.board_stage_badges import board_column_for, cpro_enabled_for_client
from app.services.cpro_mail_parse import CproEvent

logger = logging.getLogger(__name__)

RULES_KEY = "cpro_mail:rules"
RULE_CLOSED = "closed"
RULE_REJECTED = "rejected"
RULE_INTERVIEW = "interview"
DEFAULT_RULES = {RULE_CLOSED: True, RULE_REJECTED: True, RULE_INTERVIEW: True}

OUTCOME_DONE = "done"
OUTCOME_ALREADY = "already"
OUTCOME_NOTIFIED = "notified"
OUTCOME_MANUAL = "manual"

SUBJECT_FILTER = (
    r"was closed|^Rejected:|^I would like to interview"
    r"|^Interview has been withdrawn|^Interview slots have changed"
)
BATCH_LIMIT = 300
INTERVIEW_MAX_AGE = timedelta(days=2)
MAILBOX_WAIT = timedelta(days=14)
OUTCOME_TEXT_MAX = 300
_LOCK_ID = 7_302_111
# Zakleszczenie, konflikt serializacji, blokada, restart bazy.
TRANSIENT_SQLSTATES = frozenset({"40P01", "40001", "55P03", "57P01", "57P03"})

CLOSE_REASONS = {
    "consultant contracted": JobCloseReason.competitor,
    "demand change": JobCloseReason.budget,
}
# Karta tu oznacza, że wygrała nasza osoba albo właśnie podpisuje: automat pyta.
HOLD_CLOSE_COLUMNS = frozenset({"contract", "hired"})


@dataclass(frozen=True)
class VerifiedMail:
    found: bool
    authenticated: bool = False
    body_text: str = ""
    body_html: str = ""


# ``None`` = chwilowa awaria (spróbujemy w następnym przebiegu).
Verifier = Callable[[AsyncSession, Email], Awaitable[Optional[VerifiedMail]]]


@dataclass(frozen=True)
class Outcome:
    outcome: str
    text: str
    job_id: Optional[int] = None
    candidate_id: Optional[int] = None
    notified: int = 0


async def verify_with_graph(db: AsyncSession, email: Email) -> Optional[VerifiedMail]:
    """Treść i nagłówki prosto ze skrzynki właściciela wiersza."""
    from app.services.admin_cases.contract_links import (  # noqa: PLC0415
        sender_authenticated,
    )
    from app.services.m365.graph_client import (  # noqa: PLC0415
        GraphClient,
        GraphRequestError,
    )
    from app.services.m365.html_sanitize import html_to_text  # noqa: PLC0415

    conn = await db.scalar(
        select(M365Connection).where(
            M365Connection.user_id == email.user_id,
            M365Connection.is_active.is_(True),
        )
    )
    if conn is None:
        # Wygasły token wyłącza połączenie: mail czeka, aż ktoś je odnowi. Dopiero
        # po czasie uznajemy, że tej skrzynki już nie będzie.
        age = datetime.now(timezone.utc) - email.received_at
        return VerifiedMail(found=False) if age > MAILBOX_WAIT else None
    try:
        async with GraphClient(conn, db) as graph:
            message = await graph.get(
                f"/me/messages/{quote(email.m365_message_id, safe='')}",
                params={"$select": "from,body,internetMessageHeaders"},
            )
    except GraphRequestError as exc:
        if exc.status == 404:
            return VerifiedMail(found=False)
        logger.warning("cpro_mail: Graph %s przy odczycie maila", exc.status)
        return None
    except Exception as exc:  # noqa: BLE001 — awaria sieci/tokenu: następny przebieg
        logger.warning("cpro_mail: odczyt maila nieudany: %s", type(exc).__name__)
        return None
    sender = ((message.get("from") or {}).get("emailAddress") or {}).get("address")
    html = (message.get("body") or {}).get("content") or ""
    return VerifiedMail(
        found=True,
        authenticated=(sender or "").strip().lower() == parsing.SENDER
        and sender_authenticated(message.get("internetMessageHeaders"), parsing.SENDER),
        body_text=html_to_text(html),
        body_html=html,
    )


async def load_rules(db: AsyncSession) -> dict[str, bool]:
    row = await db.get(AppSetting, RULES_KEY)
    stored = row.value if row is not None and isinstance(row.value, dict) else {}
    return {key: bool(stored.get(key, on)) for key, on in DEFAULT_RULES.items()}


async def save_rules(
    db: AsyncSession, changes: dict[str, bool], *, actor_id: int
) -> dict[str, bool]:
    rules = {**await load_rules(db), **changes}
    row = await db.get(AppSetting, RULES_KEY)
    if row is None:
        db.add(AppSetting(key=RULES_KEY, value=rules))
    else:
        row.value = rules
    db.add(
        Activity(
            entity_type="settings",
            entity_id=0,
            action="cpro_rules_changed",
            user_id=actor_id,
            details=changes,
        )
    )
    return rules


def since_moment() -> datetime:
    day = date.fromisoformat(settings.CPRO_MAIL_SINCE)
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def message_key(email: Email) -> str:
    return email.m365_internet_message_id or f"email:{email.id}"


def close_reason_for(cpro_reason: Optional[str]) -> JobCloseReason:
    """Bez znanego powodu ``other``: zostaje w przeglądzie zamknięć i hit ratio."""
    key = " ".join((cpro_reason or "").lower().split())
    return CLOSE_REASONS.get(key, JobCloseReason.other)


def close_note(cpro_reason: Optional[str]) -> str:
    if cpro_reason:
        return f"Zamknięte z CPro, powód w CPro: {cpro_reason}"
    return "Zamknięte z CPro, mail bez powodu"


async def _jobs_with_number(
    db: AsyncSession, request: Optional[str], *, lock: bool = False
) -> list[Job]:
    if not request:
        return []
    query = select(Job).where(Job.client_reference == request).order_by(Job.id)
    if lock:
        query = query.with_for_update()
    rows = (await db.scalars(query)).all()
    return [job for job in rows if cpro_enabled_for_client(job.client_id)]


async def _reopened_after(db: AsyncSession, job_id: int, moment: datetime) -> bool:
    """Ktoś świadomie otworzył rekrutację po tym mailu: stary mail jej nie zamknie."""
    found = await db.scalar(
        select(Activity.id)
        .where(
            Activity.entity_type == "job",
            Activity.entity_id == job_id,
            Activity.action == "published",
            Activity.created_at > moment,
        )
        .limit(1)
    )
    return found is not None


async def _current_columns(db: AsyncSession, job_id: int) -> dict[int, str]:
    rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.stage,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(CandidateStage.job_id == job_id)
            .order_by(CandidateStage.moved_at, CandidateStage.id)
        )
    ).all()
    columns: dict[int, str] = {}
    for candidate_id, stage, name, category, terminal in rows:
        columns[candidate_id] = board_column_for(
            name,
            getattr(stage, "value", stage),
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal, "value", terminal),
        )
    return columns


def _lead_ids(job: Job) -> list[int]:
    return [job.delivery_lead_id] if job.delivery_lead_id else []


async def _emit(db: AsyncSession, user_ids: Sequence[int], **kwargs: Any) -> int:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    sent = 0
    for user_id in dict.fromkeys(user_ids):
        try:
            async with db.begin_nested():
                row = await emit(db, user_id=user_id, **kwargs)
            sent += int(row is not None)
        except Exception:  # noqa: BLE001 — dzwonek nie cofa zdarzenia
            logger.exception("cpro_mail: dzwonek dla user_id=%s nie powstał", user_id)
    return sent


async def _apply_closed(
    db: AsyncSession,
    event: CproEvent,
    received_at: datetime,
    rules: dict[str, bool],
    effects: Any,
) -> Outcome:
    from app.services.job_closed_notices import (  # noqa: PLC0415
        notify_closed_from_cpro,
    )
    from app.services.job_lifecycle import close_job_core  # noqa: PLC0415

    jobs = await _jobs_with_number(db, event.request, lock=True)
    if not jobs:
        return Outcome(OUTCOME_MANUAL, f"Numeru {event.request} nie ma w NEXUSIE.")
    first_id = jobs[0].id
    open_jobs = [job for job in jobs if job.status == JobStatus.published]
    if not open_jobs:
        return Outcome(OUTCOME_ALREADY, "Rekrutacja była już zamknięta.", first_id)
    if not rules[RULE_CLOSED]:
        return Outcome(OUTCOME_MANUAL, "Reguła jest wyłączona.", open_jobs[0].id)

    closed = held = reopened = notified = 0
    for job in open_jobs:
        if await _reopened_after(db, job.id, received_at):
            reopened += 1
            continue
        columns = await _current_columns(db, job.id)
        if HOLD_CLOSE_COLUMNS & set(columns.values()):
            held += 1
            notified += await _emit(
                db,
                _lead_ids(job),
                title="CPro zamknęło request, a masz osobę w umowie",
                message=(
                    f"Nordea zamknęła request {event.request} w CPro"
                    + (f" ({event.reason})" if event.reason else "")
                    + ". W rekrutacji jest osoba w umowie albo zatrudniona, więc NEXUS "
                    "jej nie zamknął. Zdecyduj na rekrutacji."
                ),
                ntype=NotificationType.cpro_close_needs_decision,
                related_entity_type="job",
                related_entity_id=job.id,
                link=f"/jobs/{job.id}",
            )
            continue
        await close_job_core(
            db,
            job,
            reason=close_reason_for(event.reason),
            notes=close_note(event.reason),
            actor_id=None,
            effects=effects,
        )
        closed += 1
        notified += len(
            await notify_closed_from_cpro(
                db, job, request=event.request, cpro_reason=event.reason
            )
        )
    job_id = open_jobs[0].id
    if held:
        return Outcome(
            OUTCOME_MANUAL,
            "Osoba w umowie albo zatrudniona: decyzja Delivery Leada.",
            job_id,
            notified=notified,
        )
    if closed:
        return Outcome(
            OUTCOME_DONE,
            "Zamknięto rekrutację i powiadomiono rekruterów.",
            job_id,
            notified=notified,
        )
    if reopened:
        return Outcome(
            OUTCOME_ALREADY, "Otwarta ponownie po tym mailu: bez zmian.", job_id
        )
    return Outcome(OUTCOME_ALREADY, "Rekrutacja była już zamknięta.", job_id)


async def _find_cards(
    db: AsyncSession,
    jobs: Sequence[Job],
    person: Optional[str],
    linked_candidate_id: Optional[int],
) -> tuple[list[tuple[Job, int]], bool]:
    """Karty tej osoby w rekrutacjach z numerem; drugi element = niejednoznaczne."""
    if not jobs or not person:
        return [], False
    rows = (
        await db.execute(
            select(
                CandidateStage.job_id, Candidate.id, Candidate.name, Candidate.lastname
            )
            .join(Candidate, Candidate.id == CandidateStage.candidate_id)
            .where(CandidateStage.job_id.in_([job.id for job in jobs]))
            .distinct()
        )
    ).all()
    wanted = parsing.normalized_name(person)
    matches = [
        (job_id, candidate_id)
        for job_id, candidate_id, name, lastname in rows
        if parsing.normalized_name(f"{name} {lastname}") == wanted
    ]
    candidates = {candidate_id for _job_id, candidate_id in matches}
    if len(candidates) > 1:
        if linked_candidate_id not in candidates:
            return [], True
        matches = [m for m in matches if m[1] == linked_candidate_id]
    by_id = {job.id: job for job in jobs}
    return [(by_id[job_id], candidate_id) for job_id, candidate_id in matches], False


async def _card_owner(
    db: AsyncSession, job_id: int, candidate_id: int
) -> Optional[int]:
    """Osoba karty jak w „Daj znać”: przypisana, weryfikujący, dodający."""
    from app.services.job_closed_notices import waiting_cards  # noqa: PLC0415
    from app.services.pair_owner import owners_for_job  # noqa: PLC0415

    rows = (
        await db.execute(
            select(
                CandidateStage.id,
                CandidateStage.candidate_id,
                CandidateStage.stage,
                CandidateStage.moved_by,
                CandidateStage.moved_at,
                CandidateStage.approved_at,
                PipelineStageDef.name.label("stage_name"),
                PipelineStageDef.category.label("stage_category"),
                PipelineStageDef.terminal_type.label("stage_terminal_type"),
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(
                CandidateStage.job_id == job_id,
                CandidateStage.candidate_id == candidate_id,
            )
        )
    ).all()
    assigned = await owners_for_job(db, job_id)
    owner = assigned.get(candidate_id)
    if owner is not None and owner.owner_user_id:
        return owner.owner_user_id
    cards = waiting_cards(rows, {}, columns=None)
    if cards:
        return cards[0].user_id
    # Karta już zamknięta: kto ją dodał.
    earliest = min(rows, key=lambda r: (r.moved_at, r.id), default=None)
    return earliest.moved_by if earliest is not None else None


async def _reason_id(
    db: AsyncSession, template_id: Optional[int], *, withdrawn: bool
) -> Optional[int]:
    if template_id is None:
        return None
    wanted = "Kandydat się wycofał" if withdrawn else "Inne (rejected)"
    category = TerminalType.withdrawn if withdrawn else TerminalType.rejected
    return await db.scalar(
        select(RejectionReason.id)
        .where(
            RejectionReason.template_id == template_id,
            RejectionReason.name == wanted,
            RejectionReason.category == category,
        )
        .limit(1)
    )


async def _reject_card(
    db: AsyncSession,
    job: Job,
    candidate_id: int,
    event: CproEvent,
    received_at: datetime,
    effects: Any,
) -> tuple[Optional[CandidateStage], str]:
    """Karta do „Zamknięci”. Zwraca wiersz albo ``(None, dlaczego nie)``."""
    from app.services.candidate_contact_hooks import (  # noqa: PLC0415
        maybe_close_contact_opportunity,
    )
    from app.services.pipeline_auto_move import (  # noqa: PLC0415
        _target_stage_def,
        _template_id,
        is_closed,
        run_after_commit,
    )
    from app.services.pipeline_realtime import (  # noqa: PLC0415
        broadcast_pipeline_changed,
    )
    from app.services.priority_work_policy import PriorityWorkLocked  # noqa: PLC0415
    from app.services.recruitment_process_commands import (  # noqa: PLC0415
        transition_process,
    )
    from app.services.stage_handoff_recipients import (  # noqa: PLC0415
        close_cpro_queue_bells,
    )

    await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job.id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if latest is None:
        return None, "manual"
    latest_def = (
        await db.get(PipelineStageDef, latest.stage_def_id)
        if latest.stage_def_id is not None
        else None
    )
    if is_closed(latest.stage, latest_def):
        return None, "closed"
    if latest.moved_at > received_at:
        return None, "moved"

    withdrawal = parsing.is_withdrawal(event.reason)
    target = PipelineStage.withdrawn if withdrawal else PipelineStage.rejected
    template_id = await _template_id(db, job)
    target_def = await _target_stage_def(db, template_id, target)
    reason_id = await _reason_id(db, template_id, withdrawn=withdrawal)
    if withdrawal and reason_id is None:
        return None, "manual"
    try:
        stage = await transition_process(
            db,
            candidate_id=candidate_id,
            job_id=job.id,
            stage=target,
            stage_def_id=target_def.id if target_def is not None else None,
            rejection_reason_id=reason_id,
            moved_at=datetime.now(timezone.utc),
            actor_user_id=None,
            require_existing=True,
            notes=f"Z CPro: {event.reason}" if event.reason else "Z CPro",
            ended_by="candidate" if withdrawal else "client",
        )
    except PriorityWorkLocked:
        return None, "manual"
    await close_cpro_queue_bells(
        db,
        previous=latest,
        target_name=target_def.name if target_def is not None else None,
    )
    await maybe_close_contact_opportunity(
        db,
        candidate_id=candidate_id,
        job_id=job.id,
        actor_user_id=None,
        reason=f"pipeline_terminal:{target.value}",
        occurred_at=stage.moved_at,
    )
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=None,
            details={
                "candidate_id": candidate_id,
                "job_id": job.id,
                "from_stage": getattr(latest.stage, "value", latest.stage),
                "from_stage_def_id": latest.stage_def_id,
                "stage": target.value,
                "stage_def_id": stage.stage_def_id,
                "source": "cpro_mail",
            },
        )
    )
    stage_id, job_id = stage.id, job.id

    async def _after_commit() -> None:
        from app.core.database import AsyncSessionLocal  # noqa: PLC0415

        async with AsyncSessionLocal() as session:
            await run_after_commit(session, stage_id=stage_id, mover=None)
            await broadcast_pipeline_changed(session, job_id, None)
            await session.commit()

    effects.add(f"cpro_card_{stage_id}", _after_commit)
    return stage, target.value


async def _apply_rejected(
    db: AsyncSession,
    event: CproEvent,
    email: Email,
    received_at: datetime,
    rules: dict[str, bool],
    effects: Any,
) -> Outcome:
    # Bez blokady rekrutacji: `transition_process` bierze kandydata i rekrutację
    # w kolejności całego repo, a odwrotna daje zakleszczenie z ręcznym ruchem.
    jobs = await _jobs_with_number(db, event.request)
    if not jobs:
        return Outcome(OUTCOME_MANUAL, f"Numeru {event.request} nie ma w NEXUSIE.")
    cards, ambiguous = await _find_cards(db, jobs, event.person, email.candidate_id)
    if ambiguous:
        return Outcome(
            OUTCOME_MANUAL, "Dwie osoby o tym nazwisku w rekrutacji.", jobs[0].id
        )
    if not cards:
        return Outcome(OUTCOME_MANUAL, "Nie ma tej osoby w rekrutacji.", jobs[0].id)
    job, candidate_id = cards[0]
    if not rules[RULE_REJECTED]:
        return Outcome(OUTCOME_MANUAL, "Reguła jest wyłączona.", job.id, candidate_id)

    moved_any = False
    last_reason = "closed"
    notified = 0
    for card_job, card_candidate in cards:
        # Przed ruchem: zamknięta karta nie ma już osoby karty.
        owner = await _card_owner(db, card_job.id, card_candidate)
        stage, why = await _reject_card(
            db, card_job, card_candidate, event, received_at, effects
        )
        if stage is None:
            last_reason = why
            continue
        moved_any = True
        job, candidate_id = card_job, card_candidate
        withdrew = why == PipelineStage.withdrawn.value
        bell = dict(
            title=(
                f"Rezygnacja w CPro: {event.person}"
                if withdrew
                else f"Klient odrzucił: {event.person}, napisz do kandydata"
            ),
            message=(
                f"Request {event.request}"
                + (f". Powód w CPro: {event.reason}" if event.reason else "")
                + ". Karta jest już w „Zamknięci”. NEXUS nie wysłał kandydatowi "
                "żadnego maila."
            ),
            ntype=NotificationType.cpro_candidate_rejected,
            related_entity_type="pipeline",
            related_entity_id=stage.id,
            link=f"/jobs/{card_job.id}?candidate={card_candidate}",
        )
        sent = await _emit(db, [owner] if owner else [], **bell)
        # Prowadzący odszedł z firmy albo karty nikt nie prowadzi: wie Delivery Lead.
        notified += sent or await _emit(db, _lead_ids(card_job), **bell)
    if moved_any:
        return Outcome(
            OUTCOME_DONE,
            "Przeniesiono do „Zamknięci” i powiadomiono prowadzącego.",
            job.id,
            candidate_id,
            notified,
        )
    texts = {
        "moved": "Karta przesunięta po mailu: bez zmian.",
        "manual": "Nie udało się przenieść karty: zrób to ręcznie.",
    }
    return Outcome(
        OUTCOME_MANUAL if last_reason == "manual" else OUTCOME_ALREADY,
        texts.get(last_reason, "Karta była już w „Zamknięci”."),
        job.id,
        candidate_id,
    )


INTERVIEW_TEXT = {
    parsing.KIND_INTERVIEW: (
        "Klient chce rozmowy: {who}",
        "Request {request}. Terminy są w CPro: potwierdź tam termin i wpisz go w NEXUSIE.",
    ),
    parsing.KIND_INTERVIEW_WITHDRAWN: (
        "Klient wycofał rozmowę: {who}",
        "Request {request}. CPro da znać, gdy prośba o rozmowę wróci.",
    ),
    parsing.KIND_SLOTS_CHANGED: (
        "Klient zmienił terminy rozmowy: {who}",
        "Request {request}. Potwierdź nowy termin w CPro i popraw go w NEXUSIE.",
    ),
}


async def _apply_interview(
    db: AsyncSession,
    event: CproEvent,
    email: Email,
    received_at: datetime,
    rules: dict[str, bool],
    now: datetime,
    event_id: int,
) -> Outcome:
    jobs = await _jobs_with_number(db, event.request)
    if not jobs:
        return Outcome(OUTCOME_MANUAL, "Nie ma tego numeru w NEXUSIE.")
    cards, _ambiguous = await _find_cards(db, jobs, event.person, email.candidate_id)
    job, candidate_id = cards[0] if cards else (jobs[0], None)
    if not rules[RULE_INTERVIEW]:
        return Outcome(OUTCOME_MANUAL, "Reguła jest wyłączona.", job.id, candidate_id)
    if now - received_at > INTERVIEW_MAX_AGE:
        return Outcome(
            OUTCOME_ALREADY,
            "Mail starszy niż 2 dni: bez dzwonka.",
            job.id,
            candidate_id,
        )
    recipients = list(_lead_ids(job))
    if candidate_id is not None:
        owner = await _card_owner(db, job.id, candidate_id)
        if owner:
            recipients.append(owner)
    title, message = INTERVIEW_TEXT[event.kind]
    sent = await _emit(
        db,
        recipients,
        title=title.format(who=event.person or "osoba z CPro"),
        message=message.format(request=event.request),
        ntype=NotificationType.cpro_interview_change,
        related_entity_type="cpro_mail_event",
        related_entity_id=event_id,
        link=(
            f"/jobs/{job.id}?candidate={candidate_id}"
            if candidate_id is not None
            else f"/jobs/{job.id}"
        ),
    )
    if candidate_id is None:
        return Outcome(
            OUTCOME_MANUAL,
            "Nie ma tej osoby w rekrutacji. Powiadomiono Delivery Leada.",
            job.id,
            notified=sent,
        )
    return Outcome(
        OUTCOME_NOTIFIED,
        "Powiadomiono Delivery Leada i prowadzącego: wpisz termin z CPro.",
        job.id,
        candidate_id,
        sent,
    )


def _store(row: CproMailEvent, result: Outcome) -> None:
    row.outcome = result.outcome
    row.outcome_text = result.text[:OUTCOME_TEXT_MAX]
    row.job_id = result.job_id
    row.candidate_id = result.candidate_id
    row.notified = result.notified


async def _process_one(
    db: AsyncSession,
    email: Email,
    verified: VerifiedMail,
    rules: dict[str, bool],
    effects: Any,
    now: datetime,
) -> str:
    event = parsing.parse(email.subject, verified.body_text or email.body_text)
    row = CproMailEvent(
        message_key=message_key(email),
        email_id=email.id,
        kind=event.kind if event else "unknown",
        request_number=event.request if event else None,
        person=event.person[:255] if event and event.person else None,
        reason=event.reason if event else None,
        received_at=email.received_at,
        outcome=OUTCOME_MANUAL,
        outcome_text="",
    )
    db.add(row)
    await db.flush()

    if event is None or not event.request:
        result = Outcome(OUTCOME_MANUAL, "Nie udało się odczytać tego maila.")
    elif not verified.found:
        result = Outcome(
            OUTCOME_MANUAL,
            "Nie da się odczytać tego maila ze skrzynki: nie potwierdzono nadawcy.",
        )
    elif not verified.authenticated or not parsing.has_cpro_link(verified.body_html):
        logger.warning("cpro_mail: nie potwierdzono nadawcy, zdarzenie %s", row.id)
        result = Outcome(
            OUTCOME_MANUAL, "Nie potwierdzono nadawcy: NEXUS nic nie zmienił."
        )
    elif event.kind == parsing.KIND_CLOSED:
        result = await _apply_closed(db, event, email.received_at, rules, effects)
    elif event.kind == parsing.KIND_REJECTED:
        result = await _apply_rejected(
            db, event, email, email.received_at, rules, effects
        )
    else:
        result = await _apply_interview(
            db, event, email, email.received_at, rules, now, row.id
        )
    _store(row, result)
    return result.outcome


def is_transient(exc: BaseException) -> bool:
    """Zakleszczenie, konflikt albo utrata połączenia: mail spróbuje jeszcze raz."""
    if isinstance(exc, (OperationalError, ConnectionError, TimeoutError)):
        return True
    if not isinstance(exc, DBAPIError):
        return False
    if exc.connection_invalidated:
        return True
    return getattr(exc.orig, "sqlstate", None) in TRANSIENT_SQLSTATES


async def run_sweep(
    db: AsyncSession,
    *,
    verifier: Verifier = verify_with_graph,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Jeden przebieg po nowych mailach; commit po każdym zdarzeniu."""
    from app.services.job_lifecycle import PostCommit, run_post_commit  # noqa: PLC0415

    moment = now or datetime.now(timezone.utc)
    known = select(CproMailEvent.message_key)
    key = func.coalesce(Email.m365_internet_message_id, func.concat("email:", Email.id))
    emails = (
        await db.scalars(
            select(Email)
            .where(
                func.lower(Email.from_address) == parsing.SENDER,
                Email.direction == EmailDirection.received,
                Email.received_at >= since_moment(),
                Email.subject.op("~*")(SUBJECT_FILTER),
                key.not_in(known),
            )
            .order_by(Email.received_at, Email.id)
            .limit(BATCH_LIMIT)
        )
    ).all()
    # Ten sam mail w dwóch skrzynkach: wystarczy potwierdzić go w jednej.
    by_key: dict[str, list[int]] = {}
    for email in emails:
        by_key.setdefault(message_key(email), []).append(email.id)

    counts: dict[str, int] = {}
    for mail_key, email_ids in by_key.items():
        effects = PostCommit()
        try:
            acquired = await db.scalar(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": _LOCK_ID},
            )
            if not acquired:
                counts["skipped"] = 1
                await db.rollback()
                break
            if await db.scalar(
                select(CproMailEvent.id).where(CproMailEvent.message_key == mail_key)
            ):
                await db.rollback()
                continue
            chosen: Optional[Email] = None
            verified: Optional[VerifiedMail] = None
            retry = False
            for email_id in email_ids:
                candidate = await db.get(Email, email_id)
                if candidate is None:
                    continue
                check = await verifier(db, candidate)
                if check is None:
                    retry = True
                    continue
                if chosen is None or (
                    check.found and not (verified and verified.found)
                ):
                    chosen, verified = candidate, check
                if check.found:
                    break
            if verified is None or chosen is None or (retry and not verified.found):
                await db.rollback()
                counts["retry"] = counts.get("retry", 0) + 1
                continue
            rules = await load_rules(db)
            outcome = await _process_one(db, chosen, verified, rules, effects, moment)
            await db.commit()
            counts[outcome] = counts.get(outcome, 0) + 1
        except Exception as exc:  # noqa: BLE001 — jeden mail nie zatrzymuje reszty
            await db.rollback()
            if is_transient(exc):
                logger.warning("cpro_mail: błąd chwilowy: %s", type(exc).__name__)
                counts["retry"] = counts.get("retry", 0) + 1
                continue
            logger.exception("cpro_mail: zdarzenie nie przeszło")
            if await db.scalar(
                select(CproMailEvent.id).where(CproMailEvent.message_key == mail_key)
            ):
                continue
            db.add(
                CproMailEvent(
                    message_key=mail_key,
                    email_id=email_ids[0],
                    kind="unknown",
                    received_at=moment,
                    outcome=OUTCOME_MANUAL,
                    outcome_text="Błąd przetwarzania: zrób to ręcznie.",
                )
            )
            await db.commit()
            counts["error"] = counts.get("error", 0) + 1
            continue
        await run_post_commit(effects)
    return counts


async def run_once_safely() -> Optional[dict[str, int]]:
    """Własna sesja; nigdy nie rzuca."""
    from app.core.database import AsyncSessionLocal  # noqa: PLC0415

    try:
        async with AsyncSessionLocal() as db:
            counts = await run_sweep(db)
    except Exception:  # noqa: BLE001 — pętla nie może przez to stanąć
        logger.exception("cpro_mail: przebieg nie powiódł się")
        return None
    if counts:
        logger.info("cpro_mail: %s", counts)
    return counts
