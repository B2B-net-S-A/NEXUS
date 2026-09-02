"""Queries for the process-focused recruitment operations dashboard.

The module deliberately does not reuse the organization-wide jobs list.  Every
job-producing query carries the recruitment membership scope, including the
secondary semantic-similarity result set.

On this dashboard a "process" is one published recruitment request (``Job``).
The candidate-by-request ``RecruitmentProcess`` / pipeline attempts are rolled
up into the stage counts shown inside that request; they are not separate rows.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from fastapi import HTTPException, status
from sqlalchemy import (
    Integer,
    Select,
    column,
    false,
    func,
    or_,
    select,
    table,
    true,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from app.api.recruitment_access import delivery_lead_job_pairs, job_scope_clause
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competence_category import CompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.schemas.recruitment_operations import (
    RecruitmentOperationsCategory,
    RecruitmentOperationsDetailResponse,
    RecruitmentOperationsFavorite,
    RecruitmentOperationsFavoriteOption,
    RecruitmentOperationsListResponse,
    RecruitmentOperationsLookup,
    RecruitmentOperationsOwners,
    RecruitmentOperationsPerson,
    RecruitmentOperationsPreset,
    RecruitmentOperationsProcess,
    RecruitmentOperationsSimilarProcess,
    RecruitmentOperationsStageCounts,
    RecruitmentOperationsSummary,
    SimilarityStatus,
)
from app.services.client_identity import client_display_name_expression
from app.services.similar_job_candidates import SimilarJobRef, fetch_similar_jobs


# Published recruitment rows retain ``hired`` in the Finalization group and as
# a possible final favorite. Only negative exits disappear from row counts and
# favorite options. Cross-process sharing is deliberately stricter below:
# a hired person is a historical outcome, not an operational overlap signal.
_PROCESS_HIDDEN_STAGES = frozenset({PipelineStage.rejected, PipelineStage.withdrawn})
_OVERLAP_INACTIVE_STAGES = frozenset(
    {PipelineStage.rejected, PipelineStage.withdrawn, PipelineStage.hired}
)
_STAGE_GROUPS: dict[str, frozenset[PipelineStage]] = {
    "sourcing": frozenset(
        {PipelineStage.new, PipelineStage.prep_call, PipelineStage.screening}
    ),
    "verified": frozenset({PipelineStage.verified}),
    "recommended": frozenset({PipelineStage.cv_sent}),
    "interview": frozenset({PipelineStage.interview, PipelineStage.client_interview}),
    "accepted": frozenset(
        {
            PipelineStage.acceptance,
            PipelineStage.negotiation,
            PipelineStage.onboarding,
            PipelineStage.hired,
        }
    ),
}
_CURRENT_PIPELINE = table(
    "analytics_current_pipeline",
    column("candidate_id", Integer),
    column("job_id", Integer),
    column("stage", CandidateStage.__table__.c.stage.type),
)


@dataclass(frozen=True)
class _JobRecord:
    id: int
    title: str
    client_id: int
    client_name: str
    competence_category_id: int | None
    competence_category_name: str | None
    recruiter_id: int | None
    tac_id: int | None
    delivery_lead_id: int | None
    favorite_candidate_id: int | None
    shared_candidate_count: int = 0


@dataclass(frozen=True)
class _LatestStage:
    candidate_id: int
    job_id: int
    stage: PipelineStage


@dataclass(frozen=True)
class _RecruitmentOperationsScope:
    preset: RecruitmentOperationsPreset
    delivery_pairs: frozenset[tuple[int, int]] | None = None


async def _resolve_operations_scope(
    db: AsyncSession,
    user: User,
    preset: RecruitmentOperationsPreset,
) -> _RecruitmentOperationsScope:
    if preset != "delivery-lead":
        return _RecruitmentOperationsScope(preset=preset)
    delivery_pairs = await delivery_lead_job_pairs(
        user,
        db,
        head_of_recruitment_bypass=False,
    )
    if delivery_pairs is None and not user.has_role(UserRole.admin):
        # The resolver uses ``None`` both for oversight and for non-DL callers.
        # Route validation rejects the latter, while the service still fails
        # closed when called directly.
        delivery_pairs = frozenset()
    return _RecruitmentOperationsScope(
        preset=preset,
        delivery_pairs=delivery_pairs,
    )


def _job_filters(
    user: User,
    *,
    scope: _RecruitmentOperationsScope,
    q: str | None = None,
    category_id: int | None = None,
    mine_only: bool = False,
) -> list[object]:
    filters: list[object] = [Job.status == JobStatus.published]
    if scope.preset == "finance":
        # Finance has an explicit organization-wide read preset.  Keep this
        # separate from ownership-based command policy: seeing a process here
        # does not make Finance its recruiter/TAC/DL owner.
        filters.append(true())
    elif scope.preset == "delivery-lead":
        if scope.delivery_pairs is None:
            filters.append(true())
        elif not scope.delivery_pairs:
            filters.append(false())
        else:
            filters.append(tuple_(Job.client_id, Job.tac_id).in_(scope.delivery_pairs))
    else:
        filters.append(
            job_scope_clause(
                user,
                Job.id,
                oversight_bypass=scope.preset != "my-work",
            )
        )
    if mine_only:
        # Explicit assignment only.  This intentionally does not reuse the
        # role-aware scope bypass above: an admin/HoR/Finance user may read the
        # whole preset, but "Moje przypisane" must still mean an ownership or
        # active collaborator row bearing this exact user's id.
        filters.append(
            or_(
                Job.recruiter_id == user.id,
                Job.delivery_lead_id == user.id,
                Job.tac_id == user.id,
                Job.id.in_(
                    select(JobCollaborator.job_id).where(
                        JobCollaborator.user_id == user.id,
                        JobCollaborator.removed_from_auto_cc.is_(False),
                    )
                ),
            )
        )
    normalized_q = (q or "").strip()
    if normalized_q:
        escaped_q = (
            normalized_q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_q}%"
        filters.append(
            or_(
                Job.title.ilike(pattern, escape="\\"),
                client_display_name_expression().ilike(pattern, escape="\\"),
            )
        )
    if category_id is not None:
        filters.append(Job.competence_category_id == category_id)
    return filters


def _job_rows_statement() -> Select:
    return (
        select(
            Job.id.label("id"),
            Job.title.label("title"),
            Job.client_id.label("client_id"),
            client_display_name_expression().label("client_name"),
            Job.competence_category_id.label("competence_category_id"),
            CompetenceCategory.name_pl.label("competence_category_name"),
            Job.recruiter_id.label("recruiter_id"),
            Job.tac_id.label("tac_id"),
            Job.delivery_lead_id.label("delivery_lead_id"),
            Job.favorite_candidate_id.label("favorite_candidate_id"),
        )
        .join(Client, Client.id == Job.client_id)
        .outerjoin(
            CompetenceCategory,
            CompetenceCategory.id == Job.competence_category_id,
        )
    )


def _record_from_mapping(row: object) -> _JobRecord:
    return _JobRecord(
        id=row.id,
        title=row.title,
        client_id=row.client_id,
        client_name=row.client_name,
        competence_category_id=row.competence_category_id,
        competence_category_name=row.competence_category_name,
        recruiter_id=row.recruiter_id,
        tac_id=row.tac_id,
        delivery_lead_id=row.delivery_lead_id,
        favorite_candidate_id=row.favorite_candidate_id,
        shared_candidate_count=int(getattr(row, "shared_candidate_count", 0) or 0),
    )


def _current_pipeline_subquery(*, job_ids: Select | None = None):
    statement = select(
        _CURRENT_PIPELINE.c.candidate_id,
        _CURRENT_PIPELINE.c.job_id,
        _CURRENT_PIPELINE.c.stage,
    )
    if job_ids is not None:
        statement = statement.where(_CURRENT_PIPELINE.c.job_id.in_(job_ids))
    return statement.subquery()


@dataclass(frozen=True)
class _SharedCandidateReadModels:
    """Scoped aggregates for factual cross-process candidate sharing.

    A shared candidate has a current, non-terminal/non-hired stage in at least
    two published jobs visible in the selected preset.  These read models do
    not expose candidate identity and deliberately make no semantic-fit claim.
    """

    global_candidates: Subquery
    global_memberships: Subquery
    process_counts: Subquery
    category_counts: Subquery


def _shared_candidate_read_models(
    scoped_jobs: Subquery,
) -> _SharedCandidateReadModels:
    latest = _current_pipeline_subquery(job_ids=select(scoped_jobs.c.job_id))
    active_memberships = (
        select(
            latest.c.candidate_id,
            latest.c.job_id,
            scoped_jobs.c.competence_category_id,
        )
        .select_from(latest)
        .join(scoped_jobs, scoped_jobs.c.job_id == latest.c.job_id)
        .where(latest.c.stage.notin_(_OVERLAP_INACTIVE_STAGES))
        .distinct()
        .subquery()
    )

    global_candidates = (
        select(active_memberships.c.candidate_id)
        .group_by(active_memberships.c.candidate_id)
        .having(func.count(func.distinct(active_memberships.c.job_id)) > 1)
        .subquery()
    )
    global_memberships = (
        select(
            active_memberships.c.candidate_id,
            active_memberships.c.job_id,
        )
        .join(
            global_candidates,
            global_candidates.c.candidate_id == active_memberships.c.candidate_id,
        )
        .subquery()
    )
    process_counts = (
        select(
            global_memberships.c.job_id,
            func.count(func.distinct(global_memberships.c.candidate_id)).label(
                "shared_candidate_count"
            ),
        )
        .group_by(global_memberships.c.job_id)
        .subquery()
    )

    # Category cards describe where globally shared candidates are present.
    # The other process may belong to another category; requiring two jobs in
    # the same category would silently lose exactly those cross-category reuse
    # signals the operational view is meant to surface.
    category_memberships = (
        select(
            active_memberships.c.competence_category_id,
            active_memberships.c.candidate_id,
            active_memberships.c.job_id,
        )
        .join(
            global_candidates,
            global_candidates.c.candidate_id == active_memberships.c.candidate_id,
        )
        .subquery()
    )
    category_counts = (
        select(
            category_memberships.c.competence_category_id,
            func.count(func.distinct(category_memberships.c.candidate_id)).label(
                "shared_candidates"
            ),
            func.count(func.distinct(category_memberships.c.job_id)).label(
                "processes_with_shared_candidates"
            ),
        )
        .group_by(category_memberships.c.competence_category_id)
        .subquery()
    )
    return _SharedCandidateReadModels(
        global_candidates=global_candidates,
        global_memberships=global_memberships,
        process_counts=process_counts,
        category_counts=category_counts,
    )


def _pipeline_stage(value: PipelineStage | str) -> PipelineStage:
    return value if isinstance(value, PipelineStage) else PipelineStage(value)


async def _load_latest_stages(
    db: AsyncSession, job_ids: Sequence[int]
) -> list[_LatestStage]:
    if not job_ids:
        return []
    latest = _current_pipeline_subquery(
        job_ids=select(Job.id).where(Job.id.in_(job_ids))
    )
    result = await db.execute(
        select(latest.c.candidate_id, latest.c.job_id, latest.c.stage)
    )
    return [
        _LatestStage(
            candidate_id=row.candidate_id,
            job_id=row.job_id,
            stage=_pipeline_stage(row.stage),
        )
        for row in result.all()
    ]


def _visible_process_stages(rows: Iterable[_LatestStage]) -> list[_LatestStage]:
    return [row for row in rows if row.stage not in _PROCESS_HIDDEN_STAGES]


def _overlap_candidate_ids(rows: Iterable[_LatestStage]) -> set[int]:
    return {
        row.candidate_id for row in rows if row.stage not in _OVERLAP_INACTIVE_STAGES
    }


def _stage_counts(rows: Iterable[_LatestStage]) -> RecruitmentOperationsStageCounts:
    counts = {name: 0 for name in _STAGE_GROUPS}
    for row in rows:
        for group, stages in _STAGE_GROUPS.items():
            if row.stage in stages:
                counts[group] += 1
                break
    return RecruitmentOperationsStageCounts(**counts)


def _candidate_name(candidate: Candidate) -> str:
    return " ".join(
        part for part in (candidate.name, candidate.lastname) if part
    ).strip()


def _can_edit_favorite(user: User, job: Job | _JobRecord) -> bool:
    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return True
    is_owner = user.id in {
        job.recruiter_id,
        job.tac_id,
        job.delivery_lead_id,
    }
    if is_owner and user.has_any_role(
        UserRole.recruiter,
        UserRole.tac,
        UserRole.delivery_lead,
    ):
        return True
    return False


def _ensure_favorite_write_access(user: User, job: Job | _JobRecord) -> None:
    """Favourite selection is a command, not a consequence of read scope."""

    if _can_edit_favorite(user, job):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Faworyta może zmienić administrator, Head of Recruitment albo "
            "właściciel procesu (rekruter / TAC / Delivery Lead)."
        ),
    )


async def _load_people(
    db: AsyncSession, job_rows: Sequence[_JobRecord]
) -> tuple[dict[int, User], dict[int, list[int]]]:
    job_ids = [row.id for row in job_rows]
    collaborators_by_job: dict[int, list[int]] = defaultdict(list)
    if job_ids:
        collaborator_result = await db.execute(
            select(JobCollaborator.job_id, JobCollaborator.user_id)
            .join(User, User.id == JobCollaborator.user_id)
            .where(
                JobCollaborator.job_id.in_(job_ids),
                JobCollaborator.removed_from_auto_cc.is_(False),
                User.is_active.is_(True),
            )
            .order_by(JobCollaborator.job_id, User.name, User.id)
        )
        for job_id, user_id in collaborator_result.all():
            collaborators_by_job[job_id].append(user_id)

    user_ids: set[int] = set()
    for row in job_rows:
        user_ids.update(
            value
            for value in (row.recruiter_id, row.tac_id, row.delivery_lead_id)
            if value is not None
        )
        user_ids.update(collaborators_by_job[row.id])
    if not user_ids:
        return {}, collaborators_by_job
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {user.id: user for user in result.scalars().all()}, collaborators_by_job


async def _load_candidates(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> dict[int, Candidate]:
    ids = set(candidate_ids)
    if not ids:
        return {}
    result = await db.execute(select(Candidate).where(Candidate.id.in_(ids)))
    return {candidate.id: candidate for candidate in result.scalars().all()}


def _person(user_id: int | None, users: dict[int, User]):
    user = users.get(user_id) if user_id is not None else None
    if user is None:
        return None
    return RecruitmentOperationsPerson(id=user.id, name=user.name)


async def _build_processes(
    db: AsyncSession,
    job_rows: Sequence[_JobRecord],
    *,
    latest_rows: Sequence[_LatestStage] | None = None,
) -> list[RecruitmentOperationsProcess]:
    if not job_rows:
        return []
    if latest_rows is None:
        latest_rows = await _load_latest_stages(db, [row.id for row in job_rows])
    active = _visible_process_stages(latest_rows)
    stages_by_job: dict[int, list[_LatestStage]] = defaultdict(list)
    stage_by_pair: dict[tuple[int, int], PipelineStage] = {}
    for stage in active:
        stages_by_job[stage.job_id].append(stage)
        stage_by_pair[(stage.job_id, stage.candidate_id)] = stage.stage

    users, collaborators_by_job = await _load_people(db, job_rows)
    candidate_by_id = await _load_candidates(
        db,
        (
            row.favorite_candidate_id
            for row in job_rows
            if row.favorite_candidate_id is not None
        ),
    )

    output: list[RecruitmentOperationsProcess] = []
    for row in job_rows:
        row_stages = stages_by_job[row.id]
        favorite = None
        favorite_stage = (
            stage_by_pair.get((row.id, row.favorite_candidate_id))
            if row.favorite_candidate_id is not None
            else None
        )
        favorite_candidate = (
            candidate_by_id.get(row.favorite_candidate_id)
            if row.favorite_candidate_id is not None
            else None
        )
        # A candidate can become rejected/withdrawn after being selected.  Keep
        # persistence for audit, but do not present that stale choice as active.
        if favorite_candidate is not None and favorite_stage is not None:
            favorite = RecruitmentOperationsFavorite(
                id=favorite_candidate.id,
                name=_candidate_name(favorite_candidate),
                stage=favorite_stage.value,
            )

        collaborator_users = [
            users[user_id]
            for user_id in collaborators_by_job[row.id]
            if user_id in users
        ]
        output.append(
            RecruitmentOperationsProcess(
                job_id=row.id,
                title=row.title,
                client=RecruitmentOperationsLookup(
                    id=row.client_id,
                    name=row.client_name,
                ),
                competence_category=(
                    RecruitmentOperationsLookup(
                        id=row.competence_category_id,
                        name=row.competence_category_name or "Bez kategorii",
                    )
                    if row.competence_category_id is not None
                    else None
                ),
                candidate_count=len(row_stages),
                shared_candidate_count=row.shared_candidate_count,
                stage_counts=_stage_counts(row_stages),
                favorite_candidate=favorite,
                owners=RecruitmentOperationsOwners(
                    recruiter=_person(row.recruiter_id, users),
                    tac=_person(row.tac_id, users),
                    delivery_lead=_person(row.delivery_lead_id, users),
                    collaborators=[
                        RecruitmentOperationsPerson(id=user.id, name=user.name)
                        for user in collaborator_users
                    ],
                ),
                href=f"/jobs/{row.id}",
            )
        )
    return output


async def list_recruitment_operations(
    db: AsyncSession,
    user: User,
    *,
    preset: RecruitmentOperationsPreset,
    page: int,
    page_size: int,
    q: str | None,
    category_id: int | None,
    mine_only: bool = False,
) -> RecruitmentOperationsListResponse:
    scope = await _resolve_operations_scope(db, user, preset)
    scope_filters = _job_filters(user, scope=scope, mine_only=mine_only)
    item_filters = _job_filters(
        user,
        scope=scope,
        q=q,
        category_id=category_id,
        mine_only=mine_only,
    )
    scoped_jobs = (
        select(
            Job.id.label("job_id"),
            Job.competence_category_id.label("competence_category_id"),
            Job.favorite_candidate_id.label("favorite_candidate_id"),
        )
        .join(Client, Client.id == Job.client_id)
        .where(*scope_filters)
        .subquery()
    )
    shared = _shared_candidate_read_models(scoped_jobs)
    summary_row = (
        await db.execute(
            select(
                func.count(scoped_jobs.c.job_id).label("total"),
                func.count(func.distinct(scoped_jobs.c.competence_category_id)).label(
                    "category_total"
                ),
            )
        )
    ).one()
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(Job)
            .join(Client, Client.id == Job.client_id)
            .where(*item_filters)
        )
        or 0
    )

    all_job_ids = select(scoped_jobs.c.job_id)
    latest_all = _current_pipeline_subquery(job_ids=all_job_ids)
    pipeline_summary_row = (
        await db.execute(
            select(
                func.count()
                .filter(latest_all.c.stage.notin_(_OVERLAP_INACTIVE_STAGES))
                .label("active_candidates"),
                func.count()
                .filter(
                    latest_all.c.stage.notin_(_PROCESS_HIDDEN_STAGES),
                    latest_all.c.candidate_id == scoped_jobs.c.favorite_candidate_id,
                )
                .label("active_favorites"),
                select(func.count())
                .select_from(shared.global_candidates)
                .scalar_subquery()
                .label("shared_candidates"),
                select(func.count(func.distinct(shared.global_memberships.c.job_id)))
                .select_from(shared.global_memberships)
                .scalar_subquery()
                .label("processes_with_shared_candidates"),
            )
            .select_from(latest_all)
            .join(
                scoped_jobs,
                scoped_jobs.c.job_id == latest_all.c.job_id,
            )
        )
    ).one()
    active_candidates = int(pipeline_summary_row.active_candidates or 0)
    active_favorites = int(pipeline_summary_row.active_favorites or 0)
    shared_candidates = int(pipeline_summary_row.shared_candidates or 0)
    processes_with_shared_candidates = int(
        pipeline_summary_row.processes_with_shared_candidates or 0
    )

    category_rows = (
        await db.execute(
            select(
                scoped_jobs.c.competence_category_id,
                CompetenceCategory.name_pl,
                func.count(scoped_jobs.c.job_id).label("total"),
                func.coalesce(
                    func.max(shared.category_counts.c.shared_candidates), 0
                ).label("shared_candidates"),
                func.coalesce(
                    func.max(shared.category_counts.c.processes_with_shared_candidates),
                    0,
                ).label("processes_with_shared_candidates"),
            )
            .outerjoin(
                CompetenceCategory,
                CompetenceCategory.id == scoped_jobs.c.competence_category_id,
            )
            .outerjoin(
                shared.category_counts,
                shared.category_counts.c.competence_category_id.is_not_distinct_from(
                    scoped_jobs.c.competence_category_id
                ),
            )
            .group_by(
                scoped_jobs.c.competence_category_id,
                CompetenceCategory.name_pl,
            )
            .order_by(
                func.count(scoped_jobs.c.job_id).desc(), CompetenceCategory.name_pl
            )
        )
    ).all()
    categories = [
        RecruitmentOperationsCategory(
            id=row.competence_category_id,
            name=row.name_pl or "Bez kategorii",
            total=int(row.total),
            shared_candidates=int(row.shared_candidates or 0),
            processes_with_shared_candidates=int(
                row.processes_with_shared_candidates or 0
            ),
        )
        for row in category_rows
    ]

    page_result = await db.execute(
        _job_rows_statement()
        .add_columns(
            func.coalesce(shared.process_counts.c.shared_candidate_count, 0).label(
                "shared_candidate_count"
            )
        )
        .outerjoin(
            shared.process_counts,
            shared.process_counts.c.job_id == Job.id,
        )
        .where(*item_filters)
        .order_by(Job.deadline.asc().nullslast(), Job.created_at.desc(), Job.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    job_rows = [_record_from_mapping(row) for row in page_result.all()]
    processes = await _build_processes(db, job_rows)
    return RecruitmentOperationsListResponse(
        generated_at=datetime.now(timezone.utc),
        page=page,
        page_size=page_size,
        total=total,
        summary=RecruitmentOperationsSummary(
            open_processes=int(summary_row.total or 0),
            competence_categories=int(summary_row.category_total or 0),
            active_candidates=active_candidates,
            processes_without_favorite=int(summary_row.total or 0) - active_favorites,
            shared_candidates=shared_candidates,
            processes_with_shared_candidates=processes_with_shared_candidates,
        ),
        categories=categories,
        items=processes,
    )


async def _load_scoped_job_record(
    db: AsyncSession,
    user: User,
    job_id: int,
    *,
    scope: _RecruitmentOperationsScope,
) -> _JobRecord:
    scope_filters = _job_filters(user, scope=scope)
    scoped_jobs = (
        select(
            Job.id.label("job_id"),
            Job.competence_category_id.label("competence_category_id"),
            Job.favorite_candidate_id.label("favorite_candidate_id"),
        )
        .join(Client, Client.id == Job.client_id)
        .where(*scope_filters)
        .subquery()
    )
    shared = _shared_candidate_read_models(scoped_jobs)
    result = await db.execute(
        _job_rows_statement()
        .add_columns(
            func.coalesce(shared.process_counts.c.shared_candidate_count, 0).label(
                "shared_candidate_count"
            )
        )
        .outerjoin(
            shared.process_counts,
            shared.process_counts.c.job_id == Job.id,
        )
        .where(Job.id == job_id, *scope_filters)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Opublikowana rekrutacja nie istnieje.",
        )
    return _record_from_mapping(row)


def _visible_similarity_status(
    original_status: SimilarityStatus,
    visible_refs: Sequence[SimilarJobRef],
) -> SimilarityStatus:
    if original_status == "degraded":
        return "degraded"
    if not visible_refs:
        return "empty"
    return "extended" if any(ref.tier == "B" for ref in visible_refs) else "primary"


async def get_recruitment_operation_detail(
    db: AsyncSession,
    user: User,
    job_id: int,
    *,
    preset: RecruitmentOperationsPreset,
) -> RecruitmentOperationsDetailResponse:
    scope = await _resolve_operations_scope(db, user, preset)
    job_row = await _load_scoped_job_record(
        db,
        user,
        job_id,
        scope=scope,
    )
    latest_source = await _load_latest_stages(db, [job_id])
    active_source = _visible_process_stages(latest_source)
    process = (await _build_processes(db, [job_row], latest_rows=latest_source))[0]
    candidates = await _load_candidates(db, (row.candidate_id for row in active_source))
    favorite_options = sorted(
        (
            RecruitmentOperationsFavoriteOption(
                id=row.candidate_id,
                name=_candidate_name(candidates[row.candidate_id]),
                stage=row.stage.value,
            )
            for row in active_source
            if row.candidate_id in candidates
        ),
        key=lambda item: (item.name.casefold(), item.id),
    )

    similar_refs, similarity_status = await fetch_similar_jobs(job_id, tier="all")
    eligible_refs = [ref for ref in similar_refs if ref.similarity >= 0.60]
    visible_by_id: dict[int, _JobRecord] = {}
    if eligible_refs:
        similar_result = await db.execute(
            _job_rows_statement().where(
                Job.id.in_([ref.job_id for ref in eligible_refs]),
                Job.id != job_id,
                *_job_filters(user, scope=scope),
            )
        )
        visible_by_id = {
            record.id: record
            for record in (_record_from_mapping(row) for row in similar_result.all())
        }
    visible_refs = [ref for ref in eligible_refs if ref.job_id in visible_by_id][:3]
    visible_rows = [visible_by_id[ref.job_id] for ref in visible_refs]
    latest_similar = await _load_latest_stages(
        db, [record.id for record in visible_rows]
    )
    active_ids_by_job: dict[int, set[int]] = defaultdict(set)
    for row in latest_similar:
        if row.stage not in _OVERLAP_INACTIVE_STAGES:
            active_ids_by_job[row.job_id].add(row.candidate_id)
    source_ids = _overlap_candidate_ids(latest_source)

    similar_processes = [
        RecruitmentOperationsSimilarProcess(
            job_id=record.id,
            title=record.title,
            client=RecruitmentOperationsLookup(
                id=record.client_id,
                name=record.client_name,
            ),
            competence_category=(
                RecruitmentOperationsLookup(
                    id=record.competence_category_id,
                    name=record.competence_category_name or "Bez kategorii",
                )
                if record.competence_category_id is not None
                else None
            ),
            similarity=round(ref.similarity, 4),
            candidate_overlap=len(source_ids & active_ids_by_job[record.id]),
            href=f"/jobs/{record.id}",
        )
        for ref, record in ((ref, visible_by_id[ref.job_id]) for ref in visible_refs)
    ]
    return RecruitmentOperationsDetailResponse(
        generated_at=datetime.now(timezone.utc),
        process=process,
        can_edit_favorite=_can_edit_favorite(user, job_row),
        favorite_options=favorite_options,
        similarity_status=_visible_similarity_status(similarity_status, visible_refs),
        similar_processes=similar_processes,
    )


async def set_recruitment_operation_favorite(
    db: AsyncSession,
    user: User,
    job_id: int,
    candidate_id: int | None,
    *,
    preset: RecruitmentOperationsPreset,
) -> RecruitmentOperationsFavorite | None:
    scope = await _resolve_operations_scope(db, user, preset)
    job = await db.scalar(
        select(Job)
        .where(
            Job.id == job_id,
            *_job_filters(user, scope=scope),
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Opublikowana rekrutacja nie istnieje.",
        )
    _ensure_favorite_write_access(user, job)

    candidate: Candidate | None = None
    latest_stage: PipelineStage | None = None
    if candidate_id is not None:
        stage_value = await db.scalar(
            select(CandidateStage.stage)
            .where(
                CandidateStage.job_id == job_id,
                CandidateStage.candidate_id == candidate_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        if stage_value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Kandydat nie należy do tej rekrutacji.",
            )
        latest_stage = _pipeline_stage(stage_value)
        if latest_stage in _PROCESS_HIDDEN_STAGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Odrzucony lub wycofany kandydat nie może być faworytem.",
            )
        candidate = await db.get(Candidate, candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Kandydat nie istnieje.",
            )

    previous_candidate_id = job.favorite_candidate_id
    if previous_candidate_id != candidate_id:
        job.favorite_candidate_id = candidate_id
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.id,
                action="favorite_candidate_changed",
                user_id=user.id,
                details={
                    "previous_candidate_id": previous_candidate_id,
                    "candidate_id": candidate_id,
                },
            )
        )
        await db.commit()

    if candidate is None or latest_stage is None:
        return None
    return RecruitmentOperationsFavorite(
        id=candidate.id,
        name=_candidate_name(candidate),
        stage=latest_stage.value,
    )
