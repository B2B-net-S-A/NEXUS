"""„Match” — Delivery Lead wysyła osobę od razu do innych swoich rekrutacji.

Zgłoszenie Artura 22.10.2026 (makiety https://claude.ai/artifact/HTjysWg2TjaDvxvCtjd1RV,
warianty rekomendowane): DL w przeglądzie przed wysyłką widzi, że osoba pasuje
też do innych rekrutacji z jego portfela, i jednym kliknięciem wysyła ją
wszędzie. Pomiar z produkcji: od 12.10 osoby wysłane do klienta trafiały do
drugiej rekrutacji tego klienta średnio po 11–15 dniach, a 108 ze 150 nie
doszło tam do „CV wysłane”.

Tu jest lista rekrutacji („Pasuje też do Twoich rekrutacji”) i reguły bez
bazy. Wysyłkę składa ``api/dl_match.py`` ze ścieżek, które już istnieją:
dodanie z kopią CV (jak przepięcie), „Zweryfikowany” przez DL-a (bez bramek
pól, ``dl-przesuwa-bez-blokad.md``) i zwykły ruch na „CV wysłane” albo do
kolejki Cpro ze stawką do klienta.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services.also_fits import AlsoFitsJob, also_fits_for_candidate
from app.services.board_stage_badges import board_column_for, cpro_enabled_for_client
from app.services.board_tasks import (
    TemplateStages,
    classify_template,
    dl_portfolio_client_ids,
)
from app.services.client_identity import client_display_name_expression
from app.services.job_similarity import linked_job_ids
from app.services.job_working_title import display_title
from app.services.polish_ilike import polish_folded_ilike
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

#: Ile rekrutacji pokazujemy w „Pasuje też do Twoich rekrutacji” (makieta: 5).
MATCH_LIMIT = 5
#: Ślad Match na procesie (``recruitment_processes.entry_meta.via``) — źródło
#: wejścia zostaje ``reassign``, bo to przepięcie, tylko wskazane przez DL-a.
MATCH_VIA = "dl_match"
#: Najwyżej tyle rekrutacji w jednej wysyłce.
MAX_TARGETS = 10
#: „+ Dodaj inną rekrutację”: tyle wyników, od tylu znaków.
SEARCH_LIMIT = 8
SEARCH_MIN_CHARS = 2

DESTINATION_CV_SENT = "cv_sent"
DESTINATION_CPRO = "cpro"

_CLOSED_COLUMNS = frozenset({"closed"})


@dataclass(frozen=True)
class MatchJob:
    job_id: int
    title: str
    client_name: Optional[str]
    client_reference: Optional[str]
    #: ``None`` — rekrutacja połączona z A, której ocena nie weszła do top 5.
    score: Optional[int]
    matching_must: tuple[str, ...] = ()
    gap_must: tuple[str, ...] = ()
    linked: bool = False
    destination: str = DESTINATION_CV_SENT
    #: Szablon ma etap „Zweryfikowany” i etap docelowy (CV wysłane / Cpro).
    sendable: bool = True
    budget_min_hourly: Optional[Decimal] = None
    budget_max_hourly: Optional[Decimal] = None
    #: ``False`` — rekrutacja spoza portfela DL-a (tylko z wyszukiwania).
    in_portfolio: bool = True
    #: DL tamtej rekrutacji, gdy jest spoza portfela — żeby wysyłający wiedział, czyja.
    delivery_lead_name: Optional[str] = None


@dataclass(frozen=True)
class AlreadyIn:
    job_id: int
    title: str
    client_reference: Optional[str]
    column: str


@dataclass(frozen=True)
class Suggestions:
    status: str  # "ok" | "unavailable"
    jobs: tuple[MatchJob, ...] = field(default_factory=tuple)
    already_in: tuple[AlreadyIn, ...] = field(default_factory=tuple)


def portfolio_clause(user: User, portfolio: Iterable[int]) -> Optional[ColumnElement]:
    """Które rekrutacje to „Twoje” (decyzja D: portfel DL-a, nie wszystkie).

    Delivery Lead: rekrutacje, w których jest DL-em, i rekrutacje klientów
    z jego portfela. Konto z uprawnieniem wysyłki bez roli DL (admin) —
    bez zawężenia (``None``).
    """
    if not user.has_any_role(UserRole.delivery_lead):
        return None
    clients = sorted({int(c) for c in portfolio})
    if not clients:
        return Job.delivery_lead_id == user.id
    return or_(Job.delivery_lead_id == user.id, Job.client_id.in_(clients))


def order_jobs(jobs: Iterable[MatchJob]) -> list[MatchJob]:
    """Połączone z A najpierw, potem po wyniku; remis — niższe id."""
    return sorted(
        jobs,
        key=lambda j: (
            not j.linked,
            -(j.score if j.score is not None else -1),
            j.job_id,
        ),
    )


def destination_for(client_id: Optional[int]) -> str:
    return (
        DESTINATION_CPRO if cpro_enabled_for_client(client_id) else DESTINATION_CV_SENT
    )


def target_stage_id(
    stages: Optional[TemplateStages], destination: str
) -> Optional[int]:
    if stages is None:
        return None
    return stages.cpro_id if destination == DESTINATION_CPRO else stages.cv_sent_id


async def template_stages(db: AsyncSession, job: Job) -> Optional[TemplateStages]:
    """Etapy kolejki z szablonu rekrutacji (bez szablonu — domyślny)."""
    template_id = job.pipeline_template_id or await db.scalar(
        select(PipelineTemplate.id)
        .where(PipelineTemplate.is_default.is_(True))
        .order_by(PipelineTemplate.id)
        .limit(1)
    )
    if template_id is None:
        return None
    defs = (
        await db.scalars(
            select(PipelineStageDef).where(PipelineStageDef.template_id == template_id)
        )
    ).all()
    return classify_template(defs)


async def scope_for(db: AsyncSession, user: User) -> Optional[ColumnElement]:
    portfolio = (
        await dl_portfolio_client_ids(db, user.id)
        if user.has_any_role(UserRole.delivery_lead)
        else frozenset()
    )
    return portfolio_clause(user, portfolio)


async def open_target_ids(
    db: AsyncSession,
    *,
    candidate_id: int,
    from_job_id: int,
    job_ids: Iterable[int],
    scope: Optional[ColumnElement],
) -> set[int]:
    """Z ``job_ids`` te, do których Match może wysłać: otwarte, w zakresie,
    bez żadnego wiersza tej osoby (ta sama pula co „Pasuje też do”)."""
    ids = sorted({int(j) for j in job_ids} - {int(from_job_id)})
    if not ids:
        return set()
    in_job = (
        select(CandidateStage.id)
        .where(
            CandidateStage.job_id == Job.id,
            CandidateStage.candidate_id == candidate_id,
        )
        .exists()
    )
    stmt = select(Job.id).where(
        Job.id.in_(ids),
        Job.status == JobStatus.published,
        Job.work_state.in_(IN_WORK_STATES),
        ~in_job,
    )
    if scope is not None:
        stmt = stmt.where(scope)
    return {int(j) for j in (await db.scalars(stmt)).all()}


async def _already_in(
    db: AsyncSession,
    *,
    candidate_id: int,
    from_job_id: int,
    scope: Optional[ColumnElement],
) -> list[AlreadyIn]:
    """Otwarte rekrutacje z portfela, w których osoba już jest (karta w toku) —
    żeby DL nie szukał, czemu ich nie ma na liście."""
    latest = (
        select(
            CandidateStage.job_id,
            CandidateStage.stage,
            CandidateStage.stage_def_id,
            CandidateStage.moved_at,
        )
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id != from_job_id,
        )
        .distinct(CandidateStage.job_id)
        .order_by(
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .subquery()
    )
    stmt = (
        select(
            Job,
            latest.c.stage,
            PipelineStageDef.name,
            PipelineStageDef.category,
            PipelineStageDef.terminal_type,
        )
        .select_from(latest)
        .join(Job, Job.id == latest.c.job_id)
        .outerjoin(PipelineStageDef, PipelineStageDef.id == latest.c.stage_def_id)
        .where(Job.status == JobStatus.published, Job.work_state.in_(IN_WORK_STATES))
        .order_by(latest.c.moved_at.desc())
    )
    if scope is not None:
        stmt = stmt.where(scope)
    out: list[AlreadyIn] = []
    for job, stage, name, category, terminal in (await db.execute(stmt)).all():
        column = board_column_for(
            name,
            getattr(stage, "value", stage),
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal, "value", terminal),
        )
        if column in _CLOSED_COLUMNS:
            continue
        out.append(
            AlreadyIn(
                job_id=int(job.id),
                title=display_title(job),
                client_reference=job.client_reference,
                column=column,
            )
        )
        if len(out) >= MATCH_LIMIT:
            break
    return out


async def suggestions(
    db: AsyncSession, *, user: User, candidate: Candidate, from_job_id: int
) -> Suggestions:
    """„Pasuje też do Twoich rekrutacji” dla osoby z przeglądu w ``from_job_id``.

    Ocena = „Pasuje też do” rekrutera (≥ 70, zmierzona, dozwolona), tylko
    w portfelu DL-a i do :data:`MATCH_LIMIT`. Rekrutacje połączone z A
    („Podobne rekrutacje”) są zawsze na liście i zaznaczone — to wariant
    „Wysyłaj razem = zaznacza w przeglądzie”. Awaria Qdranta nie chowa
    połączonych: ``status`` mówi, że ocena się nie udała.
    """
    scope = await scope_for(db, user)
    fits = await also_fits_for_candidate(
        db,
        candidate=candidate,
        from_job_id=from_job_id,
        profile_user_id=user.id,
        scope_clause=scope,
        limit=MATCH_LIMIT,
    )
    linked_ids = await open_target_ids(
        db,
        candidate_id=candidate.id,
        from_job_id=from_job_id,
        job_ids=(await linked_job_ids(db, [from_job_id])).get(from_job_id, []),
        scope=scope,
    )
    scored = {j.job_id: j for j in fits.jobs}
    ids = sorted(set(scored) | linked_ids)
    jobs_by_id: dict[int, tuple[Job, Optional[str]]] = {}
    if ids:
        rows = (
            await db.execute(
                select(Job, client_display_name_expression())
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id.in_(ids))
            )
        ).all()
        jobs_by_id = {int(job.id): (job, client_name) for job, client_name in rows}

    out: list[MatchJob] = []
    stages_cache: dict[Optional[int], Optional[TemplateStages]] = {}
    for job_id in ids:
        if job_id not in jobs_by_id:
            continue
        job, client_name = jobs_by_id[job_id]
        out.append(
            await _match_job(
                db,
                job,
                client_name,
                fit=scored.get(job_id),
                linked=job_id in linked_ids,
                stages_cache=stages_cache,
            )
        )
    already = await _already_in(
        db, candidate_id=candidate.id, from_job_id=from_job_id, scope=scope
    )
    return Suggestions(
        status=fits.status, jobs=tuple(order_jobs(out)), already_in=tuple(already)
    )


async def _match_job(
    db: AsyncSession,
    job: Job,
    client_name: Optional[str],
    *,
    fit: Optional[AlsoFitsJob],
    linked: bool,
    stages_cache: dict[Optional[int], Optional[TemplateStages]],
    in_portfolio: bool = True,
    delivery_lead_name: Optional[str] = None,
) -> MatchJob:
    destination = destination_for(job.client_id)
    if job.pipeline_template_id not in stages_cache:
        stages_cache[job.pipeline_template_id] = await template_stages(db, job)
    stages = stages_cache[job.pipeline_template_id]
    return MatchJob(
        job_id=int(job.id),
        title=display_title(job),
        client_name=client_name,
        client_reference=job.client_reference,
        score=fit.score if fit is not None else None,
        matching_must=tuple(fit.matching_must) if fit is not None else (),
        gap_must=tuple(fit.gap_must) if fit is not None else (),
        linked=linked,
        destination=destination,
        sendable=stages is not None
        and stages.verified_id is not None
        and target_stage_id(stages, destination) is not None,
        budget_min_hourly=job.rate_budget_hourly_min,
        budget_max_hourly=job.rate_budget_hourly,
        in_portfolio=in_portfolio,
        delivery_lead_name=None if in_portfolio else delivery_lead_name,
    )


async def search_targets(
    db: AsyncSession, *, user: User, candidate_id: int, from_job_id: int, phrase: str
) -> tuple[MatchJob, ...]:
    """„+ Dodaj inną rekrutację” (prośba Igora 27.10.2026): DL sam wskazuje
    rekrutację, której ocena nie podsunęła. Szuka we wszystkich otwartych
    rekrutacjach firmy (decyzja Artura 27.10.2026), w których tej osoby nie
    ma — ta sama pula co wysyłka (:func:`open_target_ids`). Portfel DL-a na
    górze; przy cudzej rekrutacji jej DL. Po numerze u klienta, nazwie,
    kliencie i id; bez oceny dopasowania.
    """
    phrase = phrase.strip()
    if len(phrase) < SEARCH_MIN_CHARS:
        return ()
    scope = await scope_for(db, user)
    in_job = (
        select(CandidateStage.id)
        .where(
            CandidateStage.job_id == Job.id,
            CandidateStage.candidate_id == candidate_id,
        )
        .exists()
    )
    text = or_(
        polish_folded_ilike(Job.title, phrase),
        polish_folded_ilike(func.coalesce(Job.client_reference, ""), phrase),
        polish_folded_ilike(client_display_name_expression(), phrase),
    )
    if phrase.isdigit():
        text = or_(text, Job.id == int(phrase))
    lead = aliased(User)
    in_portfolio = (scope if scope is not None else true()).label("in_portfolio")
    stmt = (
        select(Job, client_display_name_expression(), lead.name, in_portfolio)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(lead, lead.id == Job.delivery_lead_id)
        .where(
            Job.id != from_job_id,
            Job.status == JobStatus.published,
            Job.work_state.in_(IN_WORK_STATES),
            ~in_job,
            text,
        )
        .order_by(in_portfolio.desc(), Job.id.desc())
        .limit(SEARCH_LIMIT)
    )
    stages_cache: dict[Optional[int], Optional[TemplateStages]] = {}
    return tuple(
        [
            await _match_job(
                db,
                job,
                client_name,
                fit=None,
                linked=False,
                stages_cache=stages_cache,
                in_portfolio=bool(mine),
                delivery_lead_name=lead_name,
            )
            for job, client_name, lead_name, mine in (await db.execute(stmt)).all()
        ]
    )
