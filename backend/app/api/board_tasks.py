"""Router `/api/board-tasks` — kolejka „Czeka na Ciebie" (0348, Rekrutacja v5).

Odczyt listy (do wysłania do Cpro, wysłane do Cpro, przegląd DL przed
wysłaniem CV do klienta), kolejka Cpro całej firmy i osoba, która wysyła do
Cpro — JEDNA na firmę (`services/cpro_sender.py`, decyzja Artura 23.09.2026).
Przegląd DZ (0353) zniknął 24.09.2026 — zastąpiło go QC CV
(`/api/pipeline/stages/{id}/qc`).

Samo wrzucenie do Cpro i zwrot do rekrutera to zwykły ruch w pipeline
(`POST /api/pipeline/move`) — ta trasa nie ma własnej ścieżki zapisu etapu,
żeby reguły ruchu (wersja procesu, ostrzeżenia dopuszczalności, QC CV)
obowiązywały bez kopii.
"""

from datetime import date, datetime, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_followups import FollowupRow, serialize_rows
from app.api.deps import OperationalUser
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services import board_tasks as svc
from app.services import (
    candidate_followups,
    cpro_sender,
    move_requirements,
    prep_attention,
)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class BoardTaskRow(BaseModel):
    kind: Literal["cpro_to_send", "cpro_sent", "dl_review"]
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    since: datetime
    process_state_version: int
    target_stage_def_id: Optional[int] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    # Tylko przegląd DL (`dl_review`); przy pozostałych rodzajach puste.
    rejected_stage_def_id: Optional[int] = None
    verified_by_id: Optional[int] = None
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None
    expected_rate_value: Optional[float] = None
    expected_rate_unit: Optional[str] = None
    expected_rate_currency: Optional[str] = None
    screening_stage_id: Optional[int] = None
    job_sender_id: Optional[int] = None
    job_sender_name: Optional[str] = None
    # Kolejka Cpro: etap QC CV szablonu — cel „Zwróć do rekrutera".
    return_stage_def_id: Optional[int] = None
    # Przegląd DL i kolejka Cpro: wynik QC CV pary.
    qc_status: Optional[Literal["passed", "failed", "overridden", "unchecked"]] = None
    qc_blocking_failed: int = 0


class PrepAttentionRow(BaseModel):
    """Prep przed rozmową u klienta wymagający uwagi (0370)."""

    reason: Literal["missing", "weak", "unrecorded"]
    prep_no: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    interview_event_id: int
    interview_start: datetime
    prep_event_id: Optional[int] = None
    owner_id: Optional[int] = None
    urgent: bool = False


class BoardTasksResponse(BaseModel):
    cpro_to_send: list[BoardTaskRow]
    cpro_sent: list[BoardTaskRow]
    dl_review: list[BoardTaskRow]
    window_days: int
    dl_review_window_days: int
    # Ruch na „CV wysłane" ze stawką do klienta (u klientów spoza Nordei)
    # wykonuje wyłącznie admin albo Delivery Lead — Head of Recruitment widzi
    # kolejkę, ale serwer odmówiłby mu wysyłki.
    can_send_to_client: bool
    # 0370: brak prepu, prep słaby albo bez nagrania — organizator i HoR.
    prep_attention: list[PrepAttentionRow] = []
    # 0372: follow-up z kandydatem, gdy klient milczy — telefony tej osoby
    # (termin do końca jutra) i kandydaci, u których prowadzi proces, a dzwoni
    # ktoś inny.
    followups: list[FollowupRow] = []
    followups_by_others: list[FollowupRow] = []


class CproSenderRead(BaseModel):
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    until: Optional[date] = None
    fallback_user_id: Optional[int] = None
    fallback_user_name: Optional[str] = None
    set_by_name: Optional[str] = None
    set_at: Optional[datetime] = None


class CproSenderUpdate(BaseModel):
    # `null` = nikt nie wysyła (kolejka wraca do DL / Head of Recruitment).
    user_id: Optional[int] = None
    # Ostatni dzień zastępstwa; potem wraca poprzednia osoba.
    until: Optional[date] = None


class CproQueueCv(BaseModel):
    generated_document_id: Optional[int] = None
    document_id: Optional[int] = None


class CproQueueItem(BaseModel):
    stage_id: int
    candidate_id: int
    candidate_name: str
    since: datetime
    process_state_version: int
    target_stage_def_id: Optional[int] = None
    return_stage_def_id: Optional[int] = None
    client_rate_value: Optional[float] = None
    client_rate_unit: Optional[str] = None
    client_rate_currency: Optional[str] = None
    availability: Optional[date] = None
    qc_status: Literal["passed", "failed", "overridden", "unchecked"] = "unchecked"
    cv: Optional[CproQueueCv] = None


class CproQueueJob(BaseModel):
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    oldest_since: datetime
    items: list[CproQueueItem]


class CproQueueResponse(BaseModel):
    sender: CproSenderRead
    jobs: list[CproQueueJob]
    sent_today: int


@router.get("", response_model=BoardTasksResponse)
async def list_board_tasks(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> BoardTasksResponse:
    snapshot = await svc.load_snapshot(db)
    portfolio = await svc.dl_portfolio_client_ids(db, current_user.id)
    mine = svc.tasks_for_user(snapshot, current_user, portfolio=portfolio)
    preps = prep_attention.for_user(
        await prep_attention.load_prep_attention(db, datetime.now(timezone.utc)),
        current_user,
    )
    names, titles = await prep_attention.labels(db, preps)
    now = datetime.now(timezone.utc)
    today = candidate_followups.local_date(now)
    all_followups = await candidate_followups.load_followups_safely(db, now=now)
    followups = await serialize_rows(
        db,
        candidate_followups.for_user(all_followups, current_user, today=today),
        today=today,
    )
    followups_by_others = await serialize_rows(
        db,
        candidate_followups.others_for_user(all_followups, current_user),
        today=today,
    )
    return BoardTasksResponse(
        followups=followups,
        followups_by_others=followups_by_others,
        cpro_to_send=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_CPRO_TO_SEND]],
        # Najdłużej czekające na Nordeę na górze — wysłane rośnie w czasie.
        cpro_sent=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_CPRO_SENT]],
        dl_review=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_DL_REVIEW]],
        window_days=svc.WINDOW_DAYS,
        dl_review_window_days=svc.DL_REVIEW_WINDOW_DAYS,
        can_send_to_client=current_user.has_any_role(
            UserRole.admin, UserRole.delivery_lead
        ),
        prep_attention=[
            PrepAttentionRow(
                reason=a.reason,
                prep_no=a.prep_no,
                candidate_id=a.candidate_id,
                candidate_name=names.get(a.candidate_id, f"Kandydat #{a.candidate_id}"),
                job_id=a.job_id,
                job_title=titles.get(a.job_id, f"Rekrutacja #{a.job_id}"),
                interview_event_id=a.interview_event_id,
                interview_start=a.interview_start,
                prep_event_id=a.prep_event_id,
                owner_id=a.owner_id,
                urgent=a.urgent,
            )
            for a in preps
        ],
    )


@router.get("/cpro/sender", response_model=CproSenderRead)
async def get_cpro_sender(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproSenderRead:
    """Kto dziś wysyła kandydatów Nordei do Cpro (po wygaśnięciu zastępstwa)."""

    del current_user
    state = await cpro_sender.effective_sender(db)
    return CproSenderRead(**await cpro_sender.describe(db, state))


@router.put("/cpro/sender", response_model=CproSenderRead)
async def set_cpro_sender(
    body: CproSenderUpdate,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproSenderRead:
    """Ustawia JEDNĄ osobę na całą firmę (decyzja Artura 23.09.2026).

    Zmienia KAŻDY z zespołu — to informacja „kto dziś wrzuca", nie
    uprawnienie; wrzucenie i tak przechodzi przez zwykły ruch w pipeline.
    `until` = zastępstwo: po tej dacie wraca osoba, która wysyłała wcześniej.
    """

    if body.user_id is not None:
        await svc.load_assignee(db, body.user_id)
    before, after = await cpro_sender.set_sender(
        db, user_id=body.user_id, until=body.until, actor=current_user
    )
    db.add(
        Activity(
            entity_type="user",
            entity_id=current_user.id,
            action="cpro_sender_changed",
            user_id=current_user.id,
            details={
                "from": before.user_id,
                "to": after.user_id,
                "until": after.until.isoformat() if after.until else None,
                "fallback_user_id": after.fallback_user_id,
            },
        )
    )
    if after.user_id is not None and after.user_id != before.user_id:
        snapshot = await svc.load_snapshot(db)
        waiting = sum(1 for t in snapshot.tasks if t.kind == svc.KIND_CPRO_TO_SEND)
        await cpro_sender.notify_new_sender(
            db,
            sender_id=after.user_id,
            until=after.until,
            waiting=waiting,
            actor=current_user,
        )
    await db.commit()
    return CproSenderRead(**await cpro_sender.describe(db, after))


@router.get("/cpro/queue", response_model=CproQueueResponse)
async def get_cpro_queue(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproQueueResponse:
    """Kolejka Cpro całej firmy, pogrupowana po rekrutacji.

    Widzi ją każdy z dostępem do kolejki — osoba od Cpro zmienia się często
    (zastępstwa), a zastępca musi widzieć, co czeka, zanim go ustawią.
    „✓ Wrzucone" i „Zwróć do rekrutera" to zwykłe `POST /api/pipeline/move`.
    """

    now = datetime.now(timezone.utc)
    # Stawkę do klienta widzą role z `CLIENT_RATE_VIEW_ROLES` (decyzja
    # 23.09.2026, #1742) oraz osoba od Cpro — to ona wpisuje ją do Cpro.
    from app.api.candidate_access import user_can_view_client_rate

    show_rate = user_can_view_client_rate(current_user) or (
        (await cpro_sender.effective_sender(db, now)).user_id == current_user.id
    )
    snapshot = await svc.load_snapshot(db, now=now)
    to_send = [t for t in snapshot.tasks if t.kind == svc.KIND_CPRO_TO_SEND]
    pairs = [(t.candidate_id, t.job_id) for t in to_send]
    rates = await _latest_client_rates(db, pairs)
    cvs = await move_requirements.company_cv_refs(db, pairs)
    availability = await _availability(db, {t.candidate_id for t in to_send})

    jobs: dict[int, CproQueueJob] = {}
    for t in to_send:
        pair = (t.candidate_id, t.job_id)
        rate = rates.get(pair) if show_rate else None
        cv = cvs.get(pair)
        item = CproQueueItem(
            stage_id=t.stage_id,
            candidate_id=t.candidate_id,
            candidate_name=t.candidate_name,
            since=t.since,
            process_state_version=t.process_state_version,
            target_stage_def_id=t.target_stage_def_id,
            return_stage_def_id=t.return_stage_def_id,
            client_rate_value=rate[0] if rate else None,
            client_rate_unit=rate[1] if rate else None,
            client_rate_currency=rate[2] if rate else None,
            availability=availability.get(t.candidate_id),
            qc_status=t.qc_status or "unchecked",
            cv=(
                CproQueueCv(
                    generated_document_id=cv["generated_document_id"],
                    document_id=cv["document_id"],
                )
                if cv
                else None
            ),
        )
        group = jobs.get(t.job_id)
        if group is None:
            group = CproQueueJob(
                job_id=t.job_id,
                job_title=t.job_title,
                client_name=t.client_name,
                oldest_since=t.since,
                items=[],
            )
            jobs[t.job_id] = group
        group.items.append(item)
        group.oldest_since = min(group.oldest_since, t.since)

    # „Wysłane dziś" liczy dzień w kalendarzu firmy, nie UTC.
    tz = ZoneInfo(settings.BUSINESS_TZ)
    today = now.astimezone(tz).date()
    sent_today = sum(
        1
        for t in snapshot.tasks
        if t.kind == svc.KIND_CPRO_SENT and t.since.astimezone(tz).date() == today
    )
    sender = await cpro_sender.effective_sender(db, now)
    return CproQueueResponse(
        sender=CproSenderRead(**await cpro_sender.describe(db, sender)),
        jobs=sorted(jobs.values(), key=lambda g: g.oldest_since),
        sent_today=sent_today,
    )


async def _latest_client_rates(
    db: AsyncSession, pairs: list[tuple[int, int]]
) -> dict[tuple[int, int], tuple[float, Optional[str], Optional[str]]]:
    """Najnowsza stawka do klienta pary — ta, za którą osobę wysyłamy."""

    if not pairs:
        return {}
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.client_rate_value,
            CandidateStage.client_rate_unit,
            CandidateStage.client_rate_currency,
        )
        .where(
            tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(
                sorted(set(pairs))
            ),
            CandidateStage.client_rate_value.is_not(None),
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )
    out: dict[tuple[int, int], tuple[float, Optional[str], Optional[str]]] = {}
    for cand, job, value, unit, currency in rows.all():
        out.setdefault((cand, job), (float(value), unit, currency))
    return out


async def _availability(db: AsyncSession, candidate_ids: set[int]) -> dict[int, date]:
    if not candidate_ids:
        return {}
    rows = await db.execute(
        select(Candidate.id, Candidate.availability_date).where(
            Candidate.id.in_(sorted(candidate_ids)),
            Candidate.availability_date.is_not(None),
        )
    )
    return dict(rows.all())
