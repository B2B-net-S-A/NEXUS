"""„Do wysłania do klienta” — jedna reguła kolejki Delivery Leada (13.10.2026).

Przed tą datą każda para w kolumnie „QC CV” poza Nordeą była „przeglądem DL”
(`board_tasks.KIND_DL_REVIEW`), z oknem 30 dni. Pomiar na produkcji z
13.10.2026: 15 par u 4 Delivery Leadów, z czego 8 z QC do poprawy — ruch miał
rekruter, a lista i dzwonek mówiły Delivery Leadowi „sprawdź i wyślij”.

Ten moduł jest jedynym miejscem, które liczy te wiersze. Czytają go pulpit
(`board_tasks.load_snapshot`), górny pasek i menu (`GET /api/board-tasks/dl-send`),
poranny dzwonek i mail, lista rekrutacji, przypomnienie rekrutera i sygnał
dla Head of Recruitment:

* **wiersz** = najnowszy wiersz pary na etapie QC opublikowanej rekrutacji
  klienta bez kolejki Cpro, BEZ okna czasu (karta stojąca ponad 30 dni
  znikała z pulpitu, choć na Tablicy stała dalej);
* **gotowe** (``ready``) = QC zdane albo przepuszczone — ta sama reguła,
  którą karta na Tablicy stosuje od v5 (`board-card-badges.ts`); reszta
  kolumny jest jeszcze u rekrutera;
* **czeka od** (``ready_since``) = wejście do kolumny albo zaliczenie QC, co
  później; dni robocze i pilność liczą się od tej chwili, żeby czas poprawek
  rekrutera nie obciążał Delivery Leada;
* **z importu** (``imported``) = bieżący etap ustawił import Traffita i nikt
  nie ruszył karty w NEXUSIE — nie wchodzi do liczników ani przypomnień
  (decyzja Artura 11.10.2026, `notification_triggers._set_in_nexus`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.pipeline_template import PipelineTemplate
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services.board_stage_badges import cpro_enabled_for_client
from app.services.board_tasks import KIND_DL_REVIEW, BoardTask, _catalog, _Catalog
from app.services.move_requirements import QC_OK_STATUSES, qc_statuses
from app.services.order_burn_rate import workdays_between

logger = logging.getLogger(__name__)

TRAFFIT_SOURCE = "traffit"

URGENCY_FRESH = "fresh"
URGENCY_DUE = "due"
URGENCY_LATE = "late"
_URGENCY_RANK = {URGENCY_FRESH: 0, URGENCY_DUE: 1, URGENCY_LATE: 2}

# Progi w dniach roboczych od ``ready_since`` (decyzja Artura 13.10.2026):
# 1 — bursztyn, 2 — czerwień i „Przypomnij” u rekrutera, 3 — sygnał dla
# Head of Recruitment.
DUE_WORKDAYS = 1
LATE_WORKDAYS = 2
STALE_WORKDAYS = 3


@dataclass(frozen=True)
class Scope:
    """Czyje wiersze czytać. Bez pól — cała firma.

    ``viewer_id`` z ``portfolio`` zawęża w SQL do rekrutacji, w których
    przegląd należy do tej osoby (`reviewer_scope_clause`); górny pasek pyta
    o to na każdej stronie, więc nie ładuje kolejki całej firmy.
    """

    viewer_id: Optional[int] = None
    portfolio: frozenset[int] = frozenset()
    job_id: Optional[int] = None
    pair: Optional[tuple[int, int]] = None


def local_date(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(settings.BUSINESS_TZ)).date()


def waiting_workdays(ready_since: datetime, today: date) -> int:
    """Ile dni roboczych minęło od dnia gotowości (dzień gotowości = 0)."""

    return workdays_between(local_date(ready_since) + timedelta(days=1), today)


def urgency_for(workdays: int) -> str:
    if workdays >= LATE_WORKDAYS:
        return URGENCY_LATE
    if workdays >= DUE_WORKDAYS:
        return URGENCY_DUE
    return URGENCY_FRESH


def worst_urgency(tasks: Iterable[BoardTask]) -> Optional[str]:
    ranked = [t.urgency for t in tasks if t.urgency in _URGENCY_RANK]
    return max(ranked, key=_URGENCY_RANK.__getitem__) if ranked else None


def counts_for_reviewer(task: BoardTask) -> bool:
    """Czy wiersz budzi licznik, dzwonek i przypomnienia Delivery Leada."""

    return task.ready and not task.imported


@dataclass(frozen=True)
class Readiness:
    ready: bool
    ready_since: Optional[datetime] = None
    waiting_workdays: int = 0
    urgency: Optional[str] = None


def readiness_of(
    *,
    since: datetime,
    qc_status: Optional[str],
    ok_at: Optional[datetime],
    today: date,
) -> Readiness:
    """Gotowość pary ze stanu QC — jedna reguła dla kolejki Delivery Leada
    i dla „Twoje CV w drodze” rekrutera (`cv_in_transit`)."""

    if qc_status not in QC_OK_STATUSES:
        return Readiness(ready=False)
    ready_since = max(since, ok_at) if ok_at is not None else since
    workdays = waiting_workdays(ready_since, today)
    return Readiness(
        ready=True,
        ready_since=ready_since,
        waiting_workdays=workdays,
        urgency=urgency_for(workdays),
    )


def apply_readiness(task: BoardTask, *, ok_at: Optional[datetime], today: date) -> None:
    """``ready`` / ``ready_since`` / dni robocze / pilność ze stanu QC wiersza."""

    state = readiness_of(
        since=task.since, qc_status=task.qc_status, ok_at=ok_at, today=today
    )
    task.ready = state.ready
    task.ready_since = state.ready_since
    task.waiting_workdays = state.waiting_workdays
    task.urgency = state.urgency


def _active_lead_id(lead):
    # Nieaktywny DL rekrutacji = jak brak DL-a: przegląd idzie do portfela
    # klienta, zamiast do konta, którego nikt nie czyta.
    return case((lead.is_active.is_(True), Job.delivery_lead_id))


def reviewer_scope_clause(viewer_id: int, portfolio: frozenset[int], lead):
    """Lustro `board_tasks.reviews_as_dl` w SQL (``lead`` = alias konta DL-a).

    Rolę Delivery Leada sprawdza wołający — tu jest tylko „która rekrutacja”.
    """

    lead_id = _active_lead_id(lead)
    return or_(
        lead_id == viewer_id,
        and_(lead_id.is_(None), Job.client_id.in_(sorted(portfolio))),
    )


def _qc_def_ids(catalog: _Catalog) -> list[int]:
    """Etapy, które w KTÓRYMKOLWIEK szablonie stają na etapie QC (także etap
    szablonu Traffita rysowany na domyślnej tablicy)."""

    out: set[int] = set()
    for def_id in catalog.defs:
        for template_id, stages in catalog.stages.items():
            if catalog.effective_def_id(template_id, def_id) in stages.qc_ids:
                out.add(def_id)
                break
    return sorted(out)


async def load_rows(
    db: AsyncSession,
    *,
    scope: Optional[Scope] = None,
    now: Optional[datetime] = None,
    catalog: Optional[_Catalog] = None,
    default_template_id: Optional[int] = None,
) -> list[BoardTask]:
    """Wiersze kolejki ze stanem QC i gotowością — najdłużej stojące pierwsze.

    Lekka część: jedno zapytanie o wiersze i jedno o stan QC. Historię pary,
    stan karty, imiona i budżet dokłada `board_tasks.load_snapshot` (pulpit).
    """

    scope = scope or Scope()
    now = now or datetime.now(timezone.utc)
    catalog = catalog or await _catalog(db)
    qc_def_ids = _qc_def_ids(catalog)
    if not qc_def_ids:
        return []
    if default_template_id is None:
        default_template_id = await db.scalar(
            select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
        )

    later = aliased(CandidateStage)
    moved_on = (
        select(later.id)
        .where(
            later.candidate_id == CandidateStage.candidate_id,
            later.job_id == CandidateStage.job_id,
            tuple_(later.moved_at, later.id)
            > tuple_(CandidateStage.moved_at, CandidateStage.id),
        )
        .exists()
    )
    lead = aliased(User)
    query = (
        select(
            CandidateStage.id,
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage_def_id,
            CandidateStage.moved_at,
            CandidateStage.moved_by,
            CandidateStage.external_source,
            func.coalesce(Job.pipeline_template_id, default_template_id).label(
                "template_id"
            ),
            Job.title,
            Job.working_title,
            Job.client_reference,
            Job.client_id,
            Job.deadline,
            _active_lead_id(lead).label("delivery_lead_id"),
            Client.name.label("client_name"),
            Candidate.name.label("cname"),
            Candidate.lastname.label("clastname"),
        )
        .join(Job, Job.id == CandidateStage.job_id)
        .join(Candidate, Candidate.id == CandidateStage.candidate_id)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(lead, lead.id == Job.delivery_lead_id)
        .where(
            Job.status == JobStatus.published,
            CandidateStage.stage_def_id.in_(qc_def_ids),
            ~moved_on,
        )
        .order_by(CandidateStage.moved_at, CandidateStage.id)
    )
    if scope.pair is not None:
        query = query.where(
            CandidateStage.candidate_id == scope.pair[0],
            CandidateStage.job_id == scope.pair[1],
        )
    if scope.job_id is not None:
        query = query.where(CandidateStage.job_id == scope.job_id)
    if scope.viewer_id is not None:
        query = query.where(
            reviewer_scope_clause(scope.viewer_id, scope.portfolio, lead)
        )

    tasks: list[BoardTask] = []
    for r in (await db.execute(query)).all():
        stages = catalog.stages.get(r.template_id)
        if stages is None:
            continue
        effective = catalog.effective_def_id(r.template_id, r.stage_def_id)
        if effective is None or effective not in stages.qc_ids:
            continue
        if cpro_enabled_for_client(r.client_id):
            # U Nordei po QC CV idzie kolejka Cpro, nie przegląd DL.
            continue
        name = " ".join(p for p in (r.cname, r.clastname) if p) or "Kandydat"
        tasks.append(
            BoardTask(
                kind=KIND_DL_REVIEW,
                stage_id=r.id,
                candidate_id=r.candidate_id,
                candidate_name=name,
                job_id=r.job_id,
                job_title=r.title,
                job_working_title=r.working_title,
                client_reference=r.client_reference,
                client_id=r.client_id,
                client_name=r.client_name,
                since=r.moved_at,
                process_state_version=0,
                target_stage_def_id=stages.cv_sent_id,
                rejected_stage_def_id=stages.rejected_id,
                return_stage_def_id=stages.verified_id,
                moved_by=r.moved_by,
                delivery_lead_id=r.delivery_lead_id,
                template_id=r.template_id,
                imported=r.external_source == TRAFFIT_SOURCE,
                deadline=r.deadline,
            )
        )
    await attach_readiness(db, tasks, now=now)
    return tasks


async def attach_readiness(
    db: AsyncSession, tasks: list[BoardTask], *, now: datetime
) -> None:
    if not tasks:
        return
    statuses = await qc_statuses(db, ((t.candidate_id, t.job_id) for t in tasks))
    today = local_date(now)
    for t in tasks:
        status = statuses.get((t.candidate_id, t.job_id)) or {}
        t.qc_status = status.get("status") or "unchecked"
        t.qc_blocking_failed = int(status.get("blocking_failed") or 0)
        apply_readiness(t, ok_at=status.get("ok_at"), today=today)


async def attach_handed_over_names(db: AsyncSession, tasks: list[BoardTask]) -> None:
    """Kto przekazał kartę do „QC CV” (autor bieżącego wiersza etapu)."""

    user_ids = {t.moved_by for t in tasks if t.moved_by is not None}
    if not user_ids:
        return
    rows = await db.execute(
        select(User.id, User.name, User.email).where(User.id.in_(user_ids))
    )
    names = {uid: name or email for uid, name, email in rows.all()}
    for t in tasks:
        if t.moved_by is not None:
            t.handed_over_by_name = names.get(t.moved_by)


async def attach_budget(db: AsyncSession, tasks: list[BoardTask]) -> None:
    """Budżet rekrutacji „od–do” — ta sama para co w przeglądzie DL."""

    job_ids = sorted({t.job_id for t in tasks})
    if not job_ids:
        return
    from app.services.dealbreaker_filters import resolve_job_budget_hourly  # noqa: PLC0415
    from app.services.job_budget_range import effective_min  # noqa: PLC0415

    # Budżet jest dodatkiem do wiersza — awaria jego odczytu nie może położyć
    # całej kolejki. Savepoint, bo sesja żądania jedzie dalej.
    try:
        async with db.begin_nested():
            jobs = (await db.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
            budgets = {
                job.id: (effective_min(job), resolve_job_budget_hourly(job))
                for job in jobs
            }
    except Exception:  # noqa: BLE001
        logger.exception("dl_send_queue: nie udało się odczytać budżetu rekrutacji")
        return
    for t in tasks:
        low, high = budgets.get(t.job_id, (None, None))
        t.budget_min_hourly = low
        t.budget_max_hourly = high


async def load_for_viewer(
    db: AsyncSession,
    user: User,
    *,
    portfolio: frozenset[int],
    now: Optional[datetime] = None,
) -> list[BoardTask]:
    """Kolejka jednej osoby — puste bez roli Delivery Leada, bez zapytań."""

    if not user.has_role(UserRole.delivery_lead):
        return []
    return await load_rows(
        db, scope=Scope(viewer_id=user.id, portfolio=portfolio), now=now
    )


def ready_job_counts(
    tasks: Iterable[BoardTask], *, min_workdays: int = 0
) -> dict[int, int]:
    """``{rekrutacja: ile osób gotowych czeka}`` — tylko wiersze, które budzą
    licznik (`counts_for_reviewer`), opcjonalnie czekające co najmniej
    ``min_workdays`` dni roboczych.

    Lista rekrutacji i sygnał dla Head of Recruitment liczą z tych samych
    wierszy co pas na pulpicie — bez osobnej definicji „gotowe” w SQL
    (reguła obejścia QC ma mieć jednego czytelnika, `cv_qc._override_applies`).
    """

    out: dict[int, int] = {}
    for t in tasks:
        if counts_for_reviewer(t) and t.waiting_workdays >= min_workdays:
            out[t.job_id] = out.get(t.job_id, 0) + 1
    return out


__all__ = [
    "DUE_WORKDAYS",
    "LATE_WORKDAYS",
    "STALE_WORKDAYS",
    "Scope",
    "URGENCY_DUE",
    "URGENCY_FRESH",
    "URGENCY_LATE",
    "apply_readiness",
    "attach_budget",
    "attach_handed_over_names",
    "attach_readiness",
    "counts_for_reviewer",
    "load_for_viewer",
    "load_rows",
    "local_date",
    "Readiness",
    "readiness_of",
    "ready_job_counts",
    "reviewer_scope_clause",
    "urgency_for",
    "waiting_workdays",
    "worst_urgency",
]
