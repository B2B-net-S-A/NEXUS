"""Ikona „CV” w górnym pasku (16.10.2026, bez dzwonka) — kubełki ze STANU.

Dzwonek pokazywał zdarzenia CV („CV gotowe”, „QC do poprawy”, „CV do
przeglądu”), które nie gasły po zrobieniu sprawy. Ikona „CV” liczy stan:
wiersz znika, gdy karta pójdzie dalej. Źródła są już w aplikacji — ta sama
reguła co pulpit:

* rekruter — „Twoje CV w drodze” (`cv_in_transit`: wróciło, w przeglądzie,
  wysłane) i auto-CV czekające na przegląd (`cv_auto_review`); liczba =
  „do sprawdzenia” + „do poprawy”;
* Delivery Lead — „Do wysłania do klienta” (`dl_send_queue`, ta sama lista
  co pigułka sprzed tej zmiany i poranny mail) oraz CV wysłane dziś
  w jego rekrutacjach; liczba = gotowe do wysłania.

Reguła: `docs/claude/powiadomienia/pasek-tematy-bez-dzwonka.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job, JobStatus
from app.models.pipeline_template import PipelineTemplate
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import cv_in_transit as transit
from app.services.board_tasks import _catalog
from app.services.cv_auto_review import needs_review_clause
from app.services.dl_send_queue import local_date, reviewer_scope_clause

# Auto-CV starsze niż to nie czeka już na nikogo — karta dawno poszła dalej
# albo nikt jej nie ruszy; lista ma mówić o sprawach z ostatnich dni.
TO_CHECK_WINDOW_DAYS = 14
MAX_ROWS = 30

_FIX_KINDS = transit.RETURNED_TO_FIX_KINDS


@dataclass(frozen=True)
class CvCheck:
    """Auto-CV gotowe, którego osoba przesuwająca kartę jeszcze nie przejrzała."""

    document_id: int
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str]
    client_name: Optional[str]
    since: datetime


@dataclass(frozen=True)
class RecruiterCv:
    to_check: tuple[CvCheck, ...] = ()
    to_fix: tuple[transit.TransitRow, ...] = ()
    with_dl: tuple[transit.TransitRow, ...] = ()
    sent: tuple[transit.TransitRow, ...] = ()


def recruiter_buckets(
    moving: transit.CvInTransit, to_check: list[CvCheck]
) -> RecruiterCv:
    """Kubełki rekrutera z „Twoje CV w drodze” i auto-CV do przejrzenia.

    Do poprawy: karta cofnięta z „QC CV” albo z kolejki Cpro i karta w „QC CV”
    z niezdanym QC (ruch ma rekruter). U Delivery Leada: „QC CV” z QC zdanym,
    przepuszczonym albo jeszcze liczonym oraz kolejka Cpro. Odrzucenie przez
    DL nie jest CV do poprawy — to ruch w rekrutacji (ikona „Rekrutacje”).
    """
    fix = [r for r in moving.returned if r.kind in _FIX_KINDS]
    fix += [
        r
        for r in moving.in_review
        if r.kind == transit.KIND_IN_REVIEW and r.qc_status == "failed"
    ]
    with_dl = [
        r
        for r in moving.in_review
        if not (r.kind == transit.KIND_IN_REVIEW and r.qc_status == "failed")
    ]
    return RecruiterCv(
        to_check=tuple(to_check),
        to_fix=tuple(fix),
        with_dl=tuple(with_dl),
        sent=tuple(moving.sent),
    )


def badge_for(*, recruiter: Optional[RecruiterCv], dl_to_send: int) -> int:
    """Liczba na ikonie: CV, na które czekamy na tę osobę."""
    mine = len(recruiter.to_check) + len(recruiter.to_fix) if recruiter else 0
    return mine + dl_to_send


def _day_start(now: datetime) -> datetime:
    """Północ dnia firmy (Europe/Warsaw), w którym wypada ``now``."""
    return datetime.combine(
        local_date(now), time.min, tzinfo=ZoneInfo(settings.BUSINESS_TZ)
    )


async def load_to_check(
    db: AsyncSession, user: User, *, now: Optional[datetime] = None
) -> list[CvCheck]:
    """Auto-CV z `cv_auto_review.needs_review_clause`, które zrobił automat po
    ruchu tej osoby, a karta wciąż stoi na etapie, który je zamówił."""
    now = now or datetime.now(timezone.utc)
    newer = aliased(CandidateStage)
    stage = aliased(CandidateStage)
    rows = (
        await db.execute(
            select(
                CvGeneratedDocument.id,
                CvGeneratedDocument.created_at,
                stage.id.label("stage_id"),
                stage.candidate_id,
                stage.job_id,
                Candidate.name,
                Candidate.lastname,
                Job.title,
                Job.working_title,
                Client.name.label("client_name"),
            )
            .join(stage, stage.id == CvGeneratedDocument.stage_id)
            .join(Candidate, Candidate.id == stage.candidate_id)
            .join(Job, Job.id == stage.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(
                CvGeneratedDocument.created_by == user.id,
                CvGeneratedDocument.status == "ready",
                CvGeneratedDocument.created_at
                >= now - timedelta(days=TO_CHECK_WINDOW_DAYS),
                Job.status == JobStatus.published,
                needs_review_clause(),
                ~exists(
                    select(newer.id).where(
                        newer.candidate_id == stage.candidate_id,
                        newer.job_id == stage.job_id,
                        tuple_(newer.moved_at, newer.id)
                        > tuple_(stage.moved_at, stage.id),
                    )
                ),
            )
            .order_by(CvGeneratedDocument.created_at.desc())
            .limit(MAX_ROWS)
        )
    ).all()
    seen: set[int] = set()
    out: list[CvCheck] = []
    for r in rows:
        # Kilka generacji tej samej karty — jedna pozycja (najnowsza).
        if r.stage_id in seen:
            continue
        seen.add(r.stage_id)
        out.append(
            CvCheck(
                document_id=r.id,
                stage_id=r.stage_id,
                candidate_id=r.candidate_id,
                candidate_name=" ".join(p for p in (r.name, r.lastname) if p)
                or "Kandydat",
                job_id=r.job_id,
                job_title=r.title,
                job_working_title=r.working_title,
                client_name=r.client_name,
                since=r.created_at,
            )
        )
    return out


async def load_recruiter(
    db: AsyncSession,
    user: User,
    *,
    portfolio: frozenset[int],
    now: Optional[datetime] = None,
) -> RecruiterCv:
    now = now or datetime.now(timezone.utc)
    moving = await transit.load_for_user(db, user, portfolio=portfolio, now=now)
    return recruiter_buckets(moving, await load_to_check(db, user, now=now))


async def load_sent_today(
    db: AsyncSession,
    user: User,
    *,
    portfolio: frozenset[int],
    now: Optional[datetime] = None,
) -> list[transit.TransitRow]:
    """CV wysłane do klienta dziś (kalendarz firmy) w rekrutacjach, które
    Delivery Lead przegląda — ten sam zakres co kolejka „Do wysłania”."""
    now = now or datetime.now(timezone.utc)
    catalog = await _catalog(db)
    default_template_id = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )
    lead = aliased(User)
    mover = aliased(User)
    rows = (
        await db.execute(
            select(
                CandidateStage.id,
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.stage,
                CandidateStage.stage_def_id,
                CandidateStage.moved_at,
                func.coalesce(Job.pipeline_template_id, default_template_id).label(
                    "template_id"
                ),
                Job.title,
                Job.working_title,
                Client.name.label("client_name"),
                Candidate.name,
                Candidate.lastname,
                func.coalesce(mover.name, mover.email).label("mover_name"),
            )
            .join(Job, Job.id == CandidateStage.job_id)
            .join(Candidate, Candidate.id == CandidateStage.candidate_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(lead, lead.id == Job.delivery_lead_id)
            .outerjoin(mover, mover.id == CandidateStage.moved_by)
            .where(
                and_(
                    CandidateStage.moved_at >= _day_start(now),
                    Job.status == JobStatus.published,
                    reviewer_scope_clause(user.id, portfolio, lead),
                )
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(200)
        )
    ).all()
    out: list[transit.TransitRow] = []
    for r in rows:
        column, _badge = transit._place(catalog, r.template_id, r.stage_def_id, r.stage)
        if column != transit.CV_SENT_COLUMN:
            continue
        out.append(
            transit.TransitRow(
                kind=transit.KIND_SENT,
                stage_id=r.id,
                candidate_id=r.candidate_id,
                candidate_name=" ".join(p for p in (r.name, r.lastname) if p)
                or "Kandydat",
                job_id=r.job_id,
                job_title=r.title,
                job_working_title=r.working_title,
                client_name=r.client_name,
                since=r.moved_at,
                actor_name=r.mover_name,
            )
        )
        if len(out) >= MAX_ROWS:
            break
    return out


__all__ = [
    "MAX_ROWS",
    "TO_CHECK_WINDOW_DAYS",
    "CvCheck",
    "RecruiterCv",
    "badge_for",
    "load_recruiter",
    "load_sent_today",
    "load_to_check",
    "recruiter_buckets",
]
