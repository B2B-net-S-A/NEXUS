import enum
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, nulls_last, or_, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_invalidate
from app.core.database import get_db
from app.models.job import Job, JobStatus, RecruitmentType
from app.models.job_collaborator import JobCollaborator
from app.models.activity import Activity
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.schemas.job import (
    CcOverrideRequest,
    CcSuggestion,
    CcSuggestionsResponse,
    JobCloseRequest,
    JobCollaboratorAdd,
    JobCreate,
    JobOwnerAssignment,
    JobResponse,
    JobUpdate,
    UserBrief,
)
from app.api.clients_team import TAC_ASSIGNABLE_ROLES
from app.api.deps import CurrentUser, DeliveryLeadPlus, TacPlus
from app.services.auto_assign_owners import resolve_default_owners
from app.api.notifications import create_notification
from app.api.ws import manager as ws_manager
from app.core.config import settings
from app.services.champion_profile_events import (
    diff_champion_profile,
    summarize_sections,
)
from app.services.marketplace_service import (
    is_significant_job_update,
    run_marketplace_scan_safe,
)
from app.tasks.compute_proposals import (
    compute_proposal_for_job,
    create_pending_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# Fields that, when changed, should trigger re-embedding the job (Phase 2).
_EMBED_TRIGGER_FIELDS = {
    "title",
    "description",
    "requirements",
    "must_skills",
    "nice_skills",
    "seniority",
    "subcategory",
    "industry",
    # Phase 15 / Phase D: train_name goes into `_build_job_text` so changing
    # it must bump the embedding to keep same-train similarity consistent.
    "train_name",
}


async def _validate_owner_override(
    db: AsyncSession,
    *,
    user_id: int,
    allowed_roles: set[UserRole],
    field: str,
) -> None:
    """Ensure an explicit owner override references a valid, active user.

    Raises 404 if the user doesn't exist, 400 for inactive users or roles
    outside `allowed_roles`. Mirrors the validation in
    `/api/team-structure/tac-delivery-leads` (`team_structure.py:277,285`)
    so the caller sees the same UX on both surfaces.
    """
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"{field}: user not found"
        )
    if not user.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{field}: user is inactive",
        )
    if user.role not in allowed_roles:
        allowed = "/".join(sorted(r.value for r in allowed_roles))
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{field} must reference a user with role {allowed}",
        )


async def _maybe_embed_job(job_id: int, db: AsyncSession) -> None:
    """Fire-and-log job embedding; never raises."""
    try:
        from app.services.embedding_service import embed_job

        await embed_job(job_id, db)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[Job] embedding failed for job {job_id}: {e}")


async def _auto_extract_train_name(
    *,
    db: AsyncSession,
    title: str,
    description: str,
    client_id: Optional[int],
) -> Optional[str]:
    """Phase 15 / Phase D: best-effort train-name extraction.

    Loads the client name (lowercased → slug-like key) so the per-client
    dictionary can kick in. Falls back to regex-only when the client is
    unknown. Never raises; returns None on any error.
    """
    try:
        from app.services.train_name_extractor import extract_train_name
        from app.models.client import Client

        client_slug: Optional[str] = None
        if client_id is not None:
            client = (
                await db.execute(select(Client).where(Client.id == client_id))
            ).scalar_one_or_none()
            if client and client.name:
                client_slug = client.name.strip().lower()

        combined = f"{title}\n{description}".strip()
        return extract_train_name(combined, client_slug=client_slug)
    except Exception as exc:  # pragma: no cover
        logger.warning("[Job] train_name extraction failed: %s", exc)
        return None


# ── Recruiter ownership helpers ─────────────────────────────────────────────
# Primary owner lives on `jobs.recruiter_id` (nullable FK). Collaborators are
# rows in `job_collaborators` — same semantics for the "Moje projekty" filter
# but no write rights on the job itself.

_OWNERSHIP_ELIGIBLE_ROLES = {
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
}


async def _hydrate_owner_map(
    db: AsyncSession, user_ids: set[int]
) -> dict[int, UserBrief]:
    """Batch-load UserBrief objects keyed by id for owner/collaborator embedding."""
    if not user_ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {u.id: UserBrief.model_validate(u) for u in result.scalars().all()}


async def _load_collaborator_map(
    db: AsyncSession, job_ids: list[int]
) -> dict[int, list[int]]:
    """Return {job_id: [user_id, ...]} for the given job ids."""
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(JobCollaborator.job_id, JobCollaborator.user_id).where(
                JobCollaborator.job_id.in_(job_ids)
            )
        )
    ).all()
    out: dict[int, list[int]] = {}
    for job_id, user_id in rows:
        out.setdefault(job_id, []).append(user_id)
    return out


async def _require_manage_ownership(job: Job, current_user: User) -> None:
    """Gate for collaborator add/remove: admin, delivery_lead, or primary owner."""
    if current_user.role in (UserRole.admin, UserRole.delivery_lead):
        return
    if job.recruiter_id is not None and job.recruiter_id == current_user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Requires admin, delivery_lead, or primary owner of this job",
    )


class JobSort(str, enum.Enum):
    """Ordering options for GET /api/jobs (``newest`` is the default)."""

    newest = "newest"  # created_at DESC — most recently created first
    oldest = "oldest"  # created_at ASC — legacy implicit order (oldest first)
    deadline = "deadline"  # deadline ASC, NULLs last — soonest due first


@router.get("")
async def list_jobs(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[list[JobStatus]] = Query(
        None,
        description=(
            "Filter by `status` — one or more values. Repeat the param for "
            "multi-select (e.g. `?status=published&status=draft`). OR-combined."
        ),
    ),
    open_only: bool = Query(
        False,
        description=(
            "'Otwarte' quick filter — True → only jobs that are NOT closed "
            "(status in draft/published). AND-combined with `status` if both set."
        ),
    ),
    sort: JobSort = Query(
        JobSort.newest,
        description=(
            "Result ordering. `newest` (default) → created_at DESC; `oldest` → "
            "created_at ASC; `deadline` → deadline ASC with NULLs last."
        ),
    ),
    recruitment_type: Optional[RecruitmentType] = None,
    client_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by client id — one or more ids. Repeat the param for "
            "multi-select (e.g. `?client_id=3&client_id=7`). OR-combined. "
            "Single-value calls remain backward-compatible."
        ),
    ),
    q: Optional[str] = None,
    owner_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by primary_owner user id (recruiter_id) — one or more ids. "
            "Repeat the param for multi-select. OR-combined."
        ),
    ),
    responsible_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by responsible person ('Osoba odpowiedzialna') — matches if "
            "the user is the recruiter OR TAC on the job. One or more ids, repeat "
            "the param for multi-select. OR-combined across both the id set and "
            "the two responsibility roles."
        ),
    ),
    competence_category_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by primary Competence Category id — one or more ids. Repeat "
            "the param for multi-select. OR-combined."
        ),
    ),
    needs_sourcing: Optional[bool] = Query(
        None,
        description=(
            "Filter by `needs_sourcing` flag ('Potrzebny search'). True → only "
            "jobs a Delivery Lead flagged as needing active sourcing."
        ),
    ),
    active_in_search: Optional[bool] = Query(
        None,
        description=(
            "Filter by 'Aktywni w searchu' — True → only jobs that have at least "
            "one active recruiter collaborator (job_collaborators row with "
            "removed_from_auto_cc=False). False → only jobs with none."
        ),
    ),
    deadline_from: Optional[date] = Query(
        None,
        description="Lower bound (inclusive) on Job.deadline (ISO date).",
    ),
    deadline_to: Optional[date] = Query(
        None,
        description="Upper bound (inclusive) on Job.deadline (ISO date).",
    ),
    has_deadline: Optional[bool] = Query(
        None,
        description=(
            "True → only jobs with a deadline set. False → only jobs with no deadline."
        ),
    ),
    mine: bool = Query(
        False,
        description=(
            "Limit to jobs where current user is primary owner or collaborator."
        ),
    ),
    delivery_lead_id: Optional[int] = Query(
        None,
        description=(
            "Filter by Job.delivery_lead_id — single user id. Used by the DL Hub "
            "Active Jobs tab to show jobs assigned to a specific DL."
        ),
    ),
    include_stage_counts: bool = Query(
        False,
        description=(
            "Include per-job `stage_breakdown: {<stage>: count}` aggregating "
            "distinct candidates per pipeline stage. Opt-in (extra GROUP BY query)."
        ),
    ),
):
    from app.models.recruitment_pipeline import CandidateStage

    query = select(Job)
    # Defense-in-depth: nigdy nie zwracaj jobs z NULL client_id na liście.
    # Od migracji 0120 (2026-05-27) DB ma NOT NULL constraint — ten filtr
    # chroni przed regresją gdyby ktoś kiedyś constraint zdjął.
    query = query.where(Job.client_id.is_not(None))
    if status:
        query = query.where(Job.status.in_(status))
    if open_only:
        query = query.where(Job.status != JobStatus.closed)
    if recruitment_type:
        query = query.where(Job.recruitment_type == recruitment_type)
    if client_id:
        query = query.where(Job.client_id.in_(client_id))
    if q:
        query = query.where(Job.title.ilike(f"%{q}%"))
    if owner_id:
        query = query.where(Job.recruiter_id.in_(owner_id))
    if responsible_id:
        query = query.where(
            or_(
                Job.recruiter_id.in_(responsible_id),
                Job.tac_id.in_(responsible_id),
            )
        )
    if competence_category_id:
        query = query.where(Job.competence_category_id.in_(competence_category_id))
    if needs_sourcing is not None:
        query = query.where(Job.needs_sourcing.is_(needs_sourcing))
    if active_in_search is not None:
        active_collab_subq = select(JobCollaborator.job_id).where(
            JobCollaborator.removed_from_auto_cc.is_(False)
        )
        if active_in_search:
            query = query.where(Job.id.in_(active_collab_subq))
        else:
            query = query.where(Job.id.not_in(active_collab_subq))
    if deadline_from is not None:
        query = query.where(Job.deadline >= deadline_from)
    if deadline_to is not None:
        query = query.where(Job.deadline <= deadline_to)
    if has_deadline is not None:
        if has_deadline:
            query = query.where(Job.deadline.is_not(None))
        else:
            query = query.where(Job.deadline.is_(None))
    if delivery_lead_id is not None:
        query = query.where(Job.delivery_lead_id == delivery_lead_id)
    if mine:
        collab_subq = select(JobCollaborator.job_id).where(
            JobCollaborator.user_id == current_user.id
        )
        query = query.where(
            or_(Job.recruiter_id == current_user.id, Job.id.in_(collab_subq))
        )
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar()
    # Deterministic ordering (newest-first by default). Applied after the count
    # so it never leaks into the COUNT subquery. `id` is the stable tiebreaker.
    if sort == JobSort.oldest:
        query = query.order_by(Job.created_at.asc(), Job.id.asc())
    elif sort == JobSort.deadline:
        query = query.order_by(nulls_last(Job.deadline.asc()), Job.id.desc())
    else:  # JobSort.newest (default)
        query = query.order_by(Job.created_at.desc(), Job.id.desc())
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    jobs = list(result.scalars().all())

    # Candidate counts per job (distinct candidates in pipeline)
    job_ids = [j.id for j in jobs]
    counts: dict[int, int] = {}
    if job_ids:
        count_result = await db.execute(
            select(
                CandidateStage.job_id,
                func.count(func.distinct(CandidateStage.candidate_id)),
            )
            .where(CandidateStage.job_id.in_(job_ids))
            .group_by(CandidateStage.job_id)
        )
        counts = dict(count_result.all())

    # Optional: stage breakdown per job. Single GROUP BY (no N+1) — only the
    # *latest* stage per (candidate_id, job_id) counts, so we mirror the
    # pattern used in team_structure.my-team: id IN (MAX(id) GROUP BY pair).
    stage_breakdown: dict[int, dict[str, int]] = {}
    if include_stage_counts and job_ids:
        latest_per_cj = (
            select(func.max(CandidateStage.id).label("latest_id"))
            .where(CandidateStage.job_id.in_(job_ids))
            .group_by(CandidateStage.candidate_id, CandidateStage.job_id)
            .subquery()
        )
        breakdown_rows = (
            await db.execute(
                select(
                    CandidateStage.job_id,
                    CandidateStage.stage,
                    func.count(func.distinct(CandidateStage.candidate_id)),
                )
                .where(CandidateStage.id.in_(select(latest_per_cj.c.latest_id)))
                .group_by(CandidateStage.job_id, CandidateStage.stage)
            )
        ).all()
        for row_job_id, stage_enum, n in breakdown_rows:
            stage_breakdown.setdefault(row_job_id, {})[stage_enum.value] = int(n)

    # Hydrate primary_owner + collaborators in one pass (avoid N+1).
    collab_map = await _load_collaborator_map(db, job_ids)
    user_ids: set[int] = set()
    for j in jobs:
        if j.recruiter_id is not None:
            user_ids.add(j.recruiter_id)
    for ids in collab_map.values():
        user_ids.update(ids)
    user_brief_map = await _hydrate_owner_map(db, user_ids)

    # Hiring manager names batch lookup — denormalized na response żeby UI
    # nie musiało robić extra fetch per job.
    from app.models.contact import Contact  # noqa: PLC0415

    hm_ids = {j.hiring_manager_contact_id for j in jobs if j.hiring_manager_contact_id}
    hm_names: dict[int, str] = {}
    if hm_ids:
        hm_rows = await db.execute(
            select(Contact.id, Contact.name).where(Contact.id.in_(hm_ids))
        )
        hm_names = {row.id: row.name for row in hm_rows.all()}

    items = []
    for j in jobs:
        d = JobResponse.model_validate(j).model_dump()
        d["candidate_count"] = counts.get(j.id, 0)
        d["primary_owner"] = (
            user_brief_map.get(j.recruiter_id) if j.recruiter_id is not None else None
        )
        if d["primary_owner"] is not None:
            d["primary_owner"] = d["primary_owner"].model_dump()
        collab_ids = collab_map.get(j.id, [])
        d["collaborators"] = [
            user_brief_map[uid].model_dump()
            for uid in collab_ids
            if uid in user_brief_map
        ]
        d["hiring_manager_name"] = (
            hm_names.get(j.hiring_manager_contact_id)
            if j.hiring_manager_contact_id
            else None
        )
        if include_stage_counts:
            d["stage_breakdown"] = stage_breakdown.get(j.id, {})
        items.append(d)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobCreate,
    current_user: TacPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # AI CC matching (migracja 0041). If the caller didn't specify a CC and
    # opted into auto-suggest, we run the classifier *after* the embedding
    # has been generated (needs job text). For create we must persist first
    # to get `job.id`; classifier will be called below post-embed.
    payload = data.model_dump(
        exclude={"auto_suggest_cc", "secondary_cc_ids", "from_job_id", "copy_questions"}
    )
    secondary_cc_ids = data.secondary_cc_ids or []
    auto_suggest = data.auto_suggest_cc

    # "Skopiuj jako template" — dociąg pól z source jobu zanim wstawimy nowy.
    # Pola, które caller już wpisał w formularzu, mają precedencję (sprawdzamy
    # `not payload.get(field)` — `None`, pusty string, pusta lista wszystkie
    # liczą się jako "brak"). `champion_profile` kopiujemy TYLKO gdy nowy
    # request jest u tego samego klienta — championship to charakterystyka
    # kandydata u konkretnego klienta.
    src_job: Optional[Job] = None
    if data.from_job_id is not None:
        src_job = (
            await db.execute(select(Job).where(Job.id == data.from_job_id))
        ).scalar_one_or_none()
        if src_job is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"from_job_id: source job {data.from_job_id} not found",
            )
        copy_fields = (
            "description",
            "requirements",
            "must_skills",
            "nice_skills",
            "train_name",
            "seniority",
            "subcategory",
            "industry",
            "headcount",
            "work_mode",
            "remote_policy",
            "salary_min",
            "salary_max",
        )
        for field in copy_fields:
            if not payload.get(field):
                value = getattr(src_job, field, None)
                if isinstance(value, list):
                    payload[field] = list(value)
                elif isinstance(value, dict):
                    payload[field] = dict(value)
                else:
                    payload[field] = value
        same_client = payload.get("client_id") == src_job.client_id
        if (
            same_client
            and not payload.get("champion_profile")
            and src_job.champion_profile
        ):
            payload["champion_profile"] = dict(src_job.champion_profile)

    # Validate explicit owner overrides (tac_id / delivery_lead_id) before we
    # hit `resolve_default_owners`. Override always wins, but only when it
    # points to a real active user with an allowed role.
    if data.tac_id is not None:
        await _validate_owner_override(
            db,
            user_id=data.tac_id,
            allowed_roles=TAC_ASSIGNABLE_ROLES,
            field="tac_id",
        )
    if data.delivery_lead_id is not None:
        await _validate_owner_override(
            db,
            user_id=data.delivery_lead_id,
            allowed_roles={
                UserRole.delivery_lead,
                UserRole.admin,
                UserRole.head_of_recruitment,
            },
            field="delivery_lead_id",
        )

    # Auto-assign from Client ↔ TAC/DL assignments when the caller left the
    # field empty. Override semantics: if caller supplied the value, we
    # never touch it here.
    if payload.get("tac_id") is None or payload.get("delivery_lead_id") is None:
        resolved = await resolve_default_owners(db, payload.get("client_id"))
        if payload.get("tac_id") is None:
            payload["tac_id"] = resolved.tac_id
        if payload.get("delivery_lead_id") is None:
            payload["delivery_lead_id"] = resolved.delivery_lead_id

    # Phase 15 / Phase D: auto-extract train_name if the caller didn't set it.
    # Best-effort — never blocks save. Regex + per-client dictionary.
    if not payload.get("train_name"):
        payload["train_name"] = await _auto_extract_train_name(
            db=db,
            title=payload.get("title") or "",
            description=payload.get("description") or "",
            client_id=payload.get("client_id"),
        )

    job = Job(**payload, created_by=current_user.id)

    # Per-client pipeline template auto-pick (Traffit gap #1). If caller
    # didn't pin one explicitly, prefer a non-archived template tied to
    # this job's client; fall back to the global is_default template.
    # We resolve at flush time so we have the client_id from `payload`.
    if job.pipeline_template_id is None:
        from app.models.pipeline_template import PipelineTemplate

        chosen_template_id: Optional[int] = None
        if job.client_id is not None:
            chosen_template_id = await db.scalar(
                select(PipelineTemplate.id)
                .where(
                    PipelineTemplate.client_id == job.client_id,
                    PipelineTemplate.archived.is_(False),
                )
                .order_by(
                    PipelineTemplate.is_default.desc(), PipelineTemplate.id.desc()
                )
                .limit(1)
            )
        if chosen_template_id is None:
            chosen_template_id = await db.scalar(
                select(PipelineTemplate.id)
                .where(
                    PipelineTemplate.is_default.is_(True),
                    PipelineTemplate.archived.is_(False),
                )
                .limit(1)
            )
        if chosen_template_id is not None:
            job.pipeline_template_id = chosen_template_id

    db.add(job)
    await db.flush()

    # Auto-generate a human-readable reference number (Traffit parity) when
    # the caller didn't supply one and it wasn't carried over from a Traffit
    # import. Done post-flush so we have the persisted client_id; the UNIQUE
    # constraint on jobs.reference_number backstops concurrent creates.
    if not job.reference_number:
        from datetime import datetime, timezone

        from app.services.job_reference import generate_job_reference_number

        job.reference_number = await generate_job_reference_number(
            db,
            client_id=job.client_id,
            year=datetime.now(timezone.utc).year,
        )

    # Persist secondary CC links (manual from caller, if any)
    if secondary_cc_ids:
        from app.models.cc_feedback import JobSecondaryCc

        for cc_id in secondary_cc_ids[:2]:  # cap at 2
            db.add(JobSecondaryCc(job_id=job.id, competence_category_id=cc_id))

    activity_action = "created"
    activity_details: Optional[dict] = None
    if src_job is not None:
        activity_action = "created_from_template"
        activity_details = {"source_job_id": src_job.id}
        # Skopiuj pinned interview questions (job_questions) z source jobu —
        # idempotentne dzięki unique (job_id, question_id) na junction table.
        if data.copy_questions:
            from app.models.interview_question import JobQuestion

            existing_links = (
                await db.execute(
                    select(
                        JobQuestion.question_id,
                        JobQuestion.is_pinned,
                        JobQuestion.added_by_source,
                        JobQuestion.order_index,
                    ).where(JobQuestion.job_id == src_job.id)
                )
            ).all()
            for question_id, is_pinned, added_by_source, order_index in existing_links:
                db.add(
                    JobQuestion(
                        job_id=job.id,
                        question_id=question_id,
                        is_pinned=is_pinned,
                        added_by_source=added_by_source,
                        order_index=order_index,
                        added_by_user_id=current_user.id,
                    )
                )

    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action=activity_action,
            user_id=current_user.id,
            details=activity_details,
        )
    )
    await db.commit()
    await db.refresh(job)

    # Phase 2: embed the job so reverse matching picks it up.
    await _maybe_embed_job(job.id, db)

    # AI CC classification + auto-add collaborators (post-embed so classifier
    # has both keyword + embedding signal). Any failure is non-fatal.
    try:
        if job.competence_category_id is None and auto_suggest:
            from app.services.cc_classifier import classify_job_to_cc

            result = await classify_job_to_cc(job, db)
            if result.top and not result.tie:
                job.competence_category_id = result.top.cc_id
                await db.commit()
                await db.refresh(job)
        if job.competence_category_id is not None:
            from app.services.auto_cc_collaborators import auto_add_cc_collaborators

            await auto_add_cc_collaborators(
                db,
                job_id=job.id,
                competence_category_id=job.competence_category_id,
                added_by=current_user.id,
            )
    except Exception as e:  # pragma: no cover — never block job creation
        logger.warning("[Job] CC auto-assignment failed for job %s: %s", job.id, e)

    # Phase 13: kick off AI candidate proposals for the freshly-created job.
    # Snapshot is created synchronously (so the UI can start polling), and the
    # expensive scoring pass runs in the background.
    try:
        snapshot_id = await create_pending_snapshot(
            job.id,
            top_k=settings.MATCH_MAX_RESULTS,
            source="create",
            created_by=current_user.id,
        )
        background_tasks.add_task(
            compute_proposal_for_job,
            snapshot_id,
            job.id,
            top_k=settings.MATCH_MAX_RESULTS,
        )
    except Exception as e:  # pragma: no cover — never block job creation
        logger.warning(
            "[Job] proposal snapshot dispatch failed for job %s: %s", job.id, e
        )

    # Targ kandydatów (migracja 0052-0054): jeśli enabled, rescan puli marketplace
    # z tym nowym jobem i wygeneruj notyfikacje ≥ MARKETPLACE_SCORE_THRESHOLD.
    # Dedup przez uq_marketplace_alert_pair — ten sam job nigdy nie wygeneruje
    # drugiej notyfikacji dla tej samej pary (candidate_id, job_id).
    if settings.MARKETPLACE_ENABLED:
        background_tasks.add_task(run_marketplace_scan_safe, job.id)
    # Final refresh — upstream sesje (snapshot, auto_cc_collaborators,
    # classify_job_to_cc) mogly commitnac w miedzyczasie, co expire-uje
    # nasz `job` obiekt. FastAPI robi response_model walidacje przez
    # getattr na atrybutach joba — expired atrybut w async sesji rzuca
    # MissingGreenlet co objawia sie jako ResponseValidationError.
    await db.refresh(job)
    return job


@router.get("/train-names")
async def list_train_names(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    client_id: Optional[int] = Query(
        default=None,
        description=(
            "When provided, restrict to train_names used on jobs of this client. "
            "When omitted, returns unique train_names across the whole corpus."
        ),
    ),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, list[str]]:
    """Phase 15 / Phase D: autocomplete source for the JobForm train_name field.

    Returns `{items: ["ART Payments", "CIB Mortgages", ...]}` — unique,
    non-null ``train_name`` values in case-insensitive alphabetical order.
    Cheap (single indexed SELECT) so it is safe to call on every client
    switch in the form.
    """
    # NOTE: Postgres wymaga aby expr z ORDER BY były w SELECT przy DISTINCT
    # (`for SELECT DISTINCT, ORDER BY expressions must appear in select list`),
    # więc używamy GROUP BY (brak tej restrykcji) żeby móc sortować
    # case-insensitive bez leakowania `lower(...)` do response.
    stmt = (
        select(Job.train_name)
        .where(Job.train_name.isnot(None))
        .where(func.length(func.trim(Job.train_name)) > 0)
    )
    if client_id is not None:
        stmt = stmt.where(Job.client_id == client_id)
    stmt = (
        stmt.group_by(Job.train_name).order_by(func.lower(Job.train_name)).limit(limit)
    )

    rows = (await db.execute(stmt)).all()
    items = [row[0] for row in rows if row[0]]
    return {"items": items}


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    collab_map = await _load_collaborator_map(db, [job.id])
    collab_ids = collab_map.get(job.id, [])
    user_ids: set[int] = set(collab_ids)
    if job.recruiter_id is not None:
        user_ids.add(job.recruiter_id)
    user_brief_map = await _hydrate_owner_map(db, user_ids)

    payload = JobResponse.model_validate(job).model_dump()
    payload["primary_owner"] = (
        user_brief_map[job.recruiter_id].model_dump()
        if job.recruiter_id in user_brief_map
        else None
    )
    payload["collaborators"] = [
        user_brief_map[uid].model_dump() for uid in collab_ids if uid in user_brief_map
    ]

    # Hiring manager name z Contact join'a (denormalized)
    if job.hiring_manager_contact_id:
        from app.models.contact import Contact  # noqa: PLC0415

        hm = await db.scalar(
            select(Contact.name).where(Contact.id == job.hiring_manager_contact_id)
        )
        payload["hiring_manager_name"] = hm
    else:
        payload["hiring_manager_name"] = None
    return payload


async def _populate_hiring_manager_name(
    db: AsyncSession, payload: dict, job: Job
) -> dict:
    """Helper: dodaje hiring_manager_name do response payload z join'a na Contact."""
    if job.hiring_manager_contact_id:
        from app.models.contact import Contact  # noqa: PLC0415

        hm = await db.scalar(
            select(Contact.name).where(Contact.id == job.hiring_manager_contact_id)
        )
        payload["hiring_manager_name"] = hm
    else:
        payload["hiring_manager_name"] = None
    return payload


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: int,
    data: JobUpdate,
    current_user: TacPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Validate explicit owner overrides before applying any mutations.
    # `model_fields_set` only contains fields the caller actually sent, so
    # we never validate on an accidental `None`.
    if "tac_id" in data.model_fields_set and data.tac_id is not None:
        await _validate_owner_override(
            db,
            user_id=data.tac_id,
            allowed_roles=TAC_ASSIGNABLE_ROLES,
            field="tac_id",
        )
    if (
        "delivery_lead_id" in data.model_fields_set
        and data.delivery_lead_id is not None
    ):
        await _validate_owner_override(
            db,
            user_id=data.delivery_lead_id,
            allowed_roles={
                UserRole.delivery_lead,
                UserRole.admin,
                UserRole.head_of_recruitment,
            },
            field="delivery_lead_id",
        )

    updates = data.model_dump(exclude_unset=True)
    prev_status = job.status
    # Snapshot istotnych pól przed mutacją — potrzebne do marketplace diff.
    # Trzymamy kolumny z _SIGNIFICANT_FIELDS, nawet gdy nie ma ich w `updates`
    # (`is_significant_job_update` sam ignoruje niezmienione).
    _marketplace_snapshot_fields = (
        "must_skills",
        "nice_skills",
        "seniority",
        "subcategory",
        "industry",
        "title",
    )
    _before = {f: getattr(job, f) for f in _marketplace_snapshot_fields}
    for k, v in updates.items():
        setattr(job, k, v)

    # Phase 15 / Phase D: re-extract train_name if title/description changed
    # and the DL hasn't set one manually. Never overrides a DL-provided tag.
    train_fields_touched = (
        bool({"title", "description"} & updates.keys()) and "train_name" not in updates
    )
    if train_fields_touched and not job.train_name:
        extracted = await _auto_extract_train_name(
            db=db,
            title=job.title or "",
            description=job.description or "",
            client_id=job.client_id,
        )
        if extracted:
            job.train_name = extracted

    # Track closed_at transitions so `/api/reports/clients` can filter by
    # real close date (not updated_at). See migration 0047_job_closed_at.
    new_status = job.status
    status_flipped = "status" in updates and prev_status != new_status
    if status_flipped:
        if new_status == JobStatus.closed:
            job.closed_at = datetime.now(timezone.utc)
        elif prev_status == JobStatus.closed:
            job.closed_at = None

    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="updated",
            user_id=current_user.id,
            details=updates,
        )
    )
    await db.commit()
    await db.refresh(job)

    # Invalidate client hit-ratio cache on status changes (affects aggregates).
    if status_flipped:
        await cache_invalidate("reports:clients")

    # Phase 2: re-embed if any embed-relevant field changed
    changed = set(updates.keys())
    if _EMBED_TRIGGER_FIELDS & changed:
        await _maybe_embed_job(job_id, db)

    # Phase C1: invalidate cached (*, job) match scores when any scoring input
    # changes (_EMBED_TRIGGER_FIELDS covers must/nice, seniority, salary, etc.)
    if _EMBED_TRIGGER_FIELDS & changed:
        from app.services.match_score_cache import mark_stale_for_job

        await mark_stale_for_job(db, job_id)
        await db.commit()

    # Targ kandydatów: rescan tylko gdy zmieniły się pola wpływające na scoring
    # (_SIGNIFICANT_FIELDS z marketplace_service). Ignoruje zwykłe edycje opisu.
    if settings.MARKETPLACE_ENABLED:
        _after = {f: getattr(job, f) for f in _before.keys()}
        if is_significant_job_update(_before, _after):
            background_tasks.add_task(run_marketplace_scan_safe, job_id)

    # Populate hiring_manager_name żeby PATCH response zawierał aktualną nazwę
    # bez konieczności re-fetcha GET /jobs/{id} po stronie UI.
    payload = JobResponse.model_validate(job).model_dump()
    payload = await _populate_hiring_manager_name(db, payload, job)
    return payload


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="deleted",
            user_id=current_user.id,
        )
    )
    await db.delete(job)


@router.post("/{job_id}/close", response_model=JobResponse)
async def close_job(
    job_id: int,
    data: JobCloseRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Close a job with a structured reason.

    Atomically: status → closed, closed_at = now, close_reason + close_notes
    persisted. Invalidates `reports:clients` cache so hit ratio reflects the
    change. For unstructured close (legacy) use PATCH /jobs/{id} with
    `status=closed` — setter still writes `closed_at` but leaves reason NULL.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.closed
    job.closed_at = datetime.now(timezone.utc)
    job.close_reason = data.reason
    job.close_notes = data.notes

    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="closed",
            user_id=current_user.id,
            details={
                "reason": data.reason.value,
                "notes": data.notes,
            },
        )
    )
    await db.commit()
    await db.refresh(job)

    await cache_invalidate("reports:clients")
    return job


@router.post("/{job_id}/publish")
async def publish_job(
    job_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    """Publish job — mark as published and queue portal syndication."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.published
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="published",
            user_id=current_user.id,
        )
    )
    return {"status": "published", "job_id": job_id}


# ── Champion Profile (Phase 10) ─────────────────────────────────────────────


@router.get("/{job_id}/champion-profile")
async def get_champion_profile(
    job_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> dict:
    """Return the Delivery Lead's Champion Profile for this job (or {}).

    Side effect: any unread ``champion_profile_updated`` notifications
    addressed to the caller for this specific job are marked as read —
    this implements "powiadomienie znika jak Rekruter otworzy" regardless
    of whether the user arrived via the notification dropdown, a direct
    URL, or an internal link.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    await db.execute(
        sql_update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.notification_type == NotificationType.champion_profile_updated,
            Notification.related_entity_type == "job",
            Notification.related_entity_id == job_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()

    return {
        "job_id": job.id,
        "job_title": job.title,
        "champion_profile": job.champion_profile or {},
    }


async def _champion_profile_recipients(
    db: AsyncSession, job: Job, exclude_user_id: int
) -> list[int]:
    """Return the distinct user ids that should be notified of a CP edit.

    The set is the primary ``recruiter_id`` plus everyone in
    ``job_collaborators`` — minus the editor themselves. Nulls are
    filtered out.
    """
    rows = await db.execute(
        select(JobCollaborator.user_id).where(JobCollaborator.job_id == job.id)
    )
    collaborator_ids = {uid for (uid,) in rows.all() if uid is not None}
    if job.recruiter_id is not None:
        collaborator_ids.add(job.recruiter_id)
    collaborator_ids.discard(exclude_user_id)
    return sorted(collaborator_ids)


@router.put("/{job_id}/champion-profile")
async def update_champion_profile(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
) -> dict:
    """Upsert Champion Profile (Delivery Lead / admin only).

    On a content change, notifies everyone assigned to the job
    (``recruiter_id`` + ``job_collaborators``) minus the editor. Emits
    both the standard ``notification`` WS event (for the bell badge) and
    a dedicated ``champion_profile_changed`` event so any open editor
    can refetch and show an inline "someone just updated this" banner.
    """
    from app.schemas.champion import ChampionProfile

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    old_profile = dict(job.champion_profile) if job.champion_profile else {}
    profile = ChampionProfile.model_validate(payload or {})
    new_profile = profile.model_dump()

    fields_changed = diff_champion_profile(old_profile, new_profile)
    if not fields_changed:
        return {"job_id": job.id, "champion_profile": job.champion_profile or {}}

    job.champion_profile = new_profile
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="champion_profile_updated",
            user_id=current_user.id,
        )
    )

    recipients = await _champion_profile_recipients(
        db, job, exclude_user_id=current_user.id
    )
    editor_name = (current_user.name or "Ktoś").strip() or "Ktoś"
    sections_pl = summarize_sections(fields_changed)
    title = "Profil Championa zaktualizowany"
    message_text = (
        f"{editor_name} zmienił {sections_pl} dla: {job.title}"
        if sections_pl
        else f"{editor_name} zaktualizował profil dla: {job.title}"
    )
    link = f"/jobs/{job.id}?tab=champion-profile"

    for recipient_id in recipients:
        await create_notification(
            db=db,
            user_id=recipient_id,
            title=title,
            message=message_text,
            notification_type=NotificationType.champion_profile_updated,
            link=link,
            related_entity_type="job",
            related_entity_id=job.id,
            dedupe_resurface=True,
        )

    await db.commit()
    await db.refresh(job)

    now_iso = datetime.now(timezone.utc).isoformat()
    bell_event = {
        "type": "notification",
        "data": {
            "title": title,
            "message": message_text,
            "link": link,
            "notification_type": NotificationType.champion_profile_updated.value,
            "related_entity_type": "job",
            "related_entity_id": job.id,
            "created_at": now_iso,
        },
    }
    live_event = {
        "type": "champion_profile_changed",
        "data": {
            "job_id": job.id,
            "updated_by_user_id": current_user.id,
            "updated_by_name": editor_name,
            "updated_at": now_iso,
            "fields_changed": fields_changed,
        },
    }
    for recipient_id in recipients:
        try:
            await ws_manager.notify_user(recipient_id, bell_event)
            await ws_manager.notify_user(recipient_id, live_event)
        except Exception as e:  # pragma: no cover — WS push must never 500 the write
            logger.warning(
                "[Champion Profile] WS notify failed user=%s job=%s: %s",
                recipient_id,
                job.id,
                e,
            )

    return {"job_id": job.id, "champion_profile": job.champion_profile}


# ── Champion Profile AI Intake (Phase 14) ───────────────────────────────────


@router.post("/{job_id}/champion-profile/generate-from-jd")
async def generate_champion_from_jd(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Kick off LLM-based Champion Profile draft from a raw job description.

    Returns the newly-created `ChampionProfileSuggestion` (status=pending,
    unless the LLM / validation fails — then status=rejected).

    Subject to the Settings → AI quota for `champion_draft`.
    """
    from app.models.ai_feature import AIFeatureKey
    from app.schemas.champion_suggestion import (
        ChampionProfileSuggestionOut,
        GenerateFromJdPayload,
        patches_from_payload,
    )
    from app.services.ai_quota import AIQuotaExceeded, check_and_increment
    from app.services.champion_draft_service import generate_from_jd

    try:
        await check_and_increment(
            db, AIFeatureKey.champion_draft, user_id=current_user.id
        )
        await db.commit()
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc

    body = GenerateFromJdPayload.model_validate(payload or {})
    suggestion = await generate_from_jd(
        db,
        job_id=job_id,
        raw_description=body.raw_description,
        user_id=current_user.id,
    )
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return out


@router.post("/{job_id}/champion-profile/generate-from-history")
async def generate_champion_from_history(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Generate a Champion Profile draft from top-K similar closed jobs (Phase 15).

    Mirrors `generate-from-jd` but sources narrative + sourcing + screening
    data from historical roles with populated `champion_profile`. When there
    are too few matches for the job's client, returns a `rejected` suggestion
    with an explanatory `error_message` so the UI can tell the DL why.

    Subject to the Settings → AI quota for `champion_draft`.
    """
    from app.models.ai_feature import AIFeatureKey
    from app.schemas.champion_suggestion import (
        ChampionProfileSuggestionOut,
        GenerateFromHistoryPayload,
        patches_from_payload,
    )
    from app.services.ai_quota import AIQuotaExceeded, check_and_increment
    from app.services.champion_draft_service import generate_from_historical_jobs

    try:
        await check_and_increment(
            db, AIFeatureKey.champion_draft, user_id=current_user.id
        )
        await db.commit()
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc

    body = GenerateFromHistoryPayload.model_validate(payload or {})
    suggestion = await generate_from_historical_jobs(
        db,
        job_id=job_id,
        raw_description=body.raw_description,
        top_k=body.top_k,
        cross_client=body.cross_client,
        user_id=current_user.id,
    )
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return out


@router.get("/{job_id}/champion-profile/historical-matches")
async def get_champion_historical_matches(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    top_k: int = Query(default=5, ge=1, le=15),
    cross_client: bool = Query(default=False),
):
    """Preview the top-K historical matches for an existing Job (no LLM).

    Powers the side-panel cards DLs see before deciding whether to trigger
    generate-from-history. Cheap — only runs Voyage embed + Qdrant search +
    one SQL round-trip. Does NOT persist anything.
    """
    from app.schemas.champion_suggestion import (
        HistoricalMatchesResponse,
        HistoricalMatchPreview,
    )
    from app.services.historical_jobs_retrieval import (
        find_similar_historical_jobs,
        skill_frequency,
    )

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    matches = await find_similar_historical_jobs(
        db,
        client_id=job.client_id,
        title=job.title or "",
        raw_description=job.description or "",
        train_name=getattr(job, "train_name", None),
        top_k=top_k,
        cross_client=cross_client,
        exclude_job_id=job.id,
    )

    previews = [
        HistoricalMatchPreview(
            job_id=m.job_id,
            title=m.title,
            similarity=m.similarity,
            closed_at=m.closed_at,
            client_id=m.client_id,
            client_name=m.client_name,
            seniority=m.seniority,
            train_name=m.train_name,
            same_train=m.same_train,
            has_champion_profile=bool(m.champion_profile),
            must_skills_count=len(m.must_skills or []),
            nice_skills_count=len(m.nice_skills or []),
        )
        for m in matches
    ]
    return HistoricalMatchesResponse(
        matches=previews,
        skill_frequency=skill_frequency(matches),
    )


@router.post("/champion-profile/historical-matches")
async def preview_historical_matches_for_new_role(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Preview historical matches for an UNSAVED role (new-role wizard).

    Takes title/client_id/raw_description straight from the form, so the DL
    can see "you have 3 similar closed roles at this client" before even
    saving a draft. No persistence, no LLM.
    """
    from app.schemas.champion_suggestion import (
        HistoricalMatchesPreviewRequest,
        HistoricalMatchesResponse,
        HistoricalMatchPreview,
    )
    from app.services.historical_jobs_retrieval import (
        find_similar_historical_jobs,
        skill_frequency,
    )

    body = HistoricalMatchesPreviewRequest.model_validate(payload or {})

    matches = await find_similar_historical_jobs(
        db,
        client_id=body.client_id,
        title=body.title,
        raw_description=body.raw_description,
        train_name=body.train_name,
        top_k=body.top_k,
        cross_client=body.cross_client,
    )

    previews = [
        HistoricalMatchPreview(
            job_id=m.job_id,
            title=m.title,
            similarity=m.similarity,
            closed_at=m.closed_at,
            client_id=m.client_id,
            client_name=m.client_name,
            seniority=m.seniority,
            train_name=m.train_name,
            same_train=m.same_train,
            has_champion_profile=bool(m.champion_profile),
            must_skills_count=len(m.must_skills or []),
            nice_skills_count=len(m.nice_skills or []),
        )
        for m in matches
    ]
    return HistoricalMatchesResponse(
        matches=previews,
        skill_frequency=skill_frequency(matches),
    )


# ── Request history (Historia requestu) ────────────────────────────────────
# Sibling-request view in the job detail page. Differs from
# `champion-profile/historical-matches` (Phase 15) in three ways:
#   - includes BOTH closed and in-progress requests (unless `include_open=false`),
#   - does NOT require `champion_profile`,
#   - SQL fast-path same-client + Voyage fallback (progressive enhancement).
# Implemented in `services.request_history.find_similar_requests`.


def _split_entries(entries):
    """Split RequestHistoryEntry list into (closed, in_progress) buckets."""
    closed_out = []
    in_progress_out = []
    for e in entries:
        if e.is_in_progress:
            in_progress_out.append(e)
        else:
            closed_out.append(e)
    return closed_out, in_progress_out


@router.get("/{job_id}/request-history")
async def get_request_history(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    top_k: int = Query(default=10, ge=1, le=30),
    cross_client: bool = Query(default=False),
    include_open: bool = Query(default=True),
):
    """List sibling requests for a job — Historia tab.

    Splits the list into `closed` and `in_progress`. `skill_frequency` is
    computed only on closed entries (open jobs have no hire yet). Cheap by
    default — same-client SQL hit avoids Voyage entirely.
    """
    from app.schemas.request_history import (
        RequestHistoryEntry as RequestHistoryEntrySchema,
        RequestHistoryMeta,
        RequestHistoryResponse,
    )
    from app.services.request_history import (
        aggregate_meta_counts,
        find_similar_requests,
    )
    from app.services.historical_jobs_retrieval import (
        HistoricalJobMatch,
        skill_frequency,
    )

    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    entries = await find_similar_requests(
        db,
        client_id=job.client_id,
        title=job.title or "",
        raw_description=job.description or "",
        train_name=getattr(job, "train_name", None),
        top_k=top_k,
        cross_client=cross_client,
        exclude_job_id=job.id,
        include_open=include_open,
    )

    closed, in_progress = _split_entries(entries)

    # skill_frequency operates on HistoricalJobMatch — adapt closed entries by
    # loading must/nice from DB for those job_ids only. Cheap (1 SELECT).
    skill_freq: dict = {}
    if closed:
        closed_ids = [e.job_id for e in closed]
        rows = (
            await db.execute(
                select(Job.id, Job.must_skills, Job.nice_skills, Job.train_name).where(
                    Job.id.in_(closed_ids)
                )
            )
        ).all()
        proxy_matches = [
            HistoricalJobMatch(
                job_id=r[0],
                title="",
                similarity=0.0,
                closed_at=None,
                client_id=None,
                client_name=None,
                champion_profile={},
                must_skills=list(r[1] or []),
                nice_skills=list(r[2] or []),
                train_name=r[3],
                same_train=False,
            )
            for r in rows
        ]
        skill_freq = skill_frequency(proxy_matches)

    counts = aggregate_meta_counts(entries)
    return RequestHistoryResponse(
        closed=[RequestHistoryEntrySchema.model_validate(e.__dict__) for e in closed],
        in_progress=[
            RequestHistoryEntrySchema.model_validate(e.__dict__) for e in in_progress
        ],
        skill_frequency=skill_freq,
        meta=RequestHistoryMeta(
            sql_count=counts["sql_count"],
            voyage_count=counts["voyage_count"],
            total=counts["total"],
            skill_freq_sample=len(closed),
        ),
    )


@router.post("/request-history/preview")
async def preview_request_history(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Preview sibling requests for an UNSAVED role (banner in AddJobModal).

    Reuses the same engine; difference is `exclude_job_id=None` (no self) and
    no `Job` row to read defaults from.
    """
    from app.schemas.request_history import (
        RequestHistoryEntry as RequestHistoryEntrySchema,
        RequestHistoryMeta,
        RequestHistoryPreviewRequest,
        RequestHistoryResponse,
    )
    from app.services.request_history import (
        aggregate_meta_counts,
        find_similar_requests,
    )

    body = RequestHistoryPreviewRequest.model_validate(payload or {})

    entries = await find_similar_requests(
        db,
        client_id=body.client_id,
        title=body.title,
        raw_description=body.raw_description,
        train_name=body.train_name,
        top_k=body.top_k,
        cross_client=body.cross_client,
        include_open=body.include_open,
    )
    closed, in_progress = _split_entries(entries)
    counts = aggregate_meta_counts(entries)
    return RequestHistoryResponse(
        closed=[RequestHistoryEntrySchema.model_validate(e.__dict__) for e in closed],
        in_progress=[
            RequestHistoryEntrySchema.model_validate(e.__dict__) for e in in_progress
        ],
        skill_frequency={},  # banner doesn't need skill freq
        meta=RequestHistoryMeta(
            sql_count=counts["sql_count"],
            voyage_count=counts["voyage_count"],
            total=counts["total"],
            skill_freq_sample=0,
        ),
    )


@router.post(
    "/{job_id}/candidates",
    status_code=status.HTTP_201_CREATED,
)
async def add_candidate_from_history(
    job_id: int,
    body: dict,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Add a candidate as a `new` pipeline entry — used by 'Dodaj championa'.

    Idempotent: if `(candidate_id, job_id)` already exists in `candidate_stages`,
    returns 409 Conflict (UI surfaces 'kandydat już jest w pipeline').
    """
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.schemas.request_history import (
        AddCandidateFromHistoryPayload,
        AddCandidateFromHistoryResponse,
    )

    payload = AddCandidateFromHistoryPayload.model_validate(body or {})

    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Job not found")

    candidate = (
        await db.execute(select(Candidate).where(Candidate.id == payload.candidate_id))
    ).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    existing = (
        await db.execute(
            select(CandidateStage.id).where(
                CandidateStage.candidate_id == payload.candidate_id,
                CandidateStage.job_id == job_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Candidate already exists in this pipeline",
        )

    stage = CandidateStage(
        candidate_id=payload.candidate_id,
        job_id=job_id,
        stage=PipelineStage.new,
        moved_by=current_user.id,
    )
    db.add(stage)
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=0,  # filled after flush
            action="added_from_historical_job",
            user_id=current_user.id,
            details={
                "job_id": job_id,
                "candidate_id": payload.candidate_id,
                "source_job_id": payload.source_job_id,
            },
        )
    )
    await db.flush()
    # Update activity entity_id now that stage has an id.
    # Lazy approach: just commit — activity already references job_id+candidate_id
    # in details, that's sufficient for audit. Skip the second update query.
    await db.commit()
    await db.refresh(stage)

    return AddCandidateFromHistoryResponse(
        candidate_stage_id=stage.id,
        job_id=job_id,
        candidate_id=payload.candidate_id,
        stage=stage.stage.value,
        source_job_id=payload.source_job_id,
    )


@router.get("/{job_id}/champion-profile/suggestions")
async def list_champion_suggestions(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List Champion Profile suggestions for a job, newest first."""
    from app.models.champion_suggestion import (
        ChampionProfileSuggestion,
        SuggestionStatus,
    )
    from app.schemas.champion_suggestion import (
        ChampionProfileSuggestionListOut,
        ChampionProfileSuggestionOut,
        patches_from_payload,
    )

    stmt = select(ChampionProfileSuggestion).where(
        ChampionProfileSuggestion.job_id == job_id
    )
    if status_filter:
        try:
            status_enum = SuggestionStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        stmt = stmt.where(ChampionProfileSuggestion.status == status_enum)
    stmt = stmt.order_by(ChampionProfileSuggestion.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = []
    for row in rows:
        out = ChampionProfileSuggestionOut.model_validate(row)
        out.patches = patches_from_payload(row.payload or {})
        items.append(out)
    return ChampionProfileSuggestionListOut(items=items, total=len(items))


# ── Recruiter ownership endpoints ───────────────────────────────────────────
# Primary owner (`recruiter_id`) is changed by Admin + Delivery Lead only.
# "Claim" is self-assign on an unassigned job — open to anyone who can write
# to jobs (admin/DL/TAC/recruiter/sourcer). The `user` read-only role is
# blocked.


@router.post("/{job_id}/owner", response_model=JobResponse)
async def assign_owner(
    job_id: int,
    payload: JobOwnerAssignment,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Set/change the primary owner (recruiter_id). Admin + Delivery Lead only."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if not target or not target.is_active:
        raise HTTPException(status_code=409, detail="Target user not found or inactive")
    if target.role not in _OWNERSHIP_ELIGIBLE_ROLES:
        raise HTTPException(
            status_code=409,
            detail=f"Role {target.role.value} cannot own a job",
        )

    job.recruiter_id = target.id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="owner_assigned",
            user_id=current_user.id,
            details={"new_owner_id": target.id},
        )
    )
    await db.commit()
    await db.refresh(job)
    return await get_job(job_id, current_user, db)


@router.delete("/{job_id}/owner", response_model=JobResponse)
async def release_owner(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Unassign the primary owner (sets recruiter_id = NULL). Admin + DL only."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    previous = job.recruiter_id
    job.recruiter_id = None
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="owner_released",
            user_id=current_user.id,
            details={"previous_owner_id": previous},
        )
    )
    await db.commit()
    await db.refresh(job)
    return await get_job(job_id, current_user, db)


@router.post("/{job_id}/claim", response_model=JobResponse)
async def claim_job(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Self-assign an unassigned job to the current user.

    Rejects if the job already has a primary owner (409) or the current user
    is a read-only viewer (403). Any user in the ownership-eligible role set
    can claim.
    """
    if current_user.role not in _OWNERSHIP_ELIGIBLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Read-only viewers cannot claim jobs",
        )

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.recruiter_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job already has a primary owner",
        )

    job.recruiter_id = current_user.id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="claimed",
            user_id=current_user.id,
        )
    )
    await db.commit()
    await db.refresh(job)
    return await get_job(job_id, current_user, db)


@router.get("/{job_id}/collaborators", response_model=list[UserBrief])
async def list_collaborators(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """List collaborators (read-only participants) on a job."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    rows = (
        (
            await db.execute(
                select(User)
                .join(JobCollaborator, JobCollaborator.user_id == User.id)
                .where(JobCollaborator.job_id == job_id)
                .order_by(User.name)
            )
        )
        .scalars()
        .all()
    )
    return [UserBrief.model_validate(u) for u in rows]


@router.post(
    "/{job_id}/collaborators",
    response_model=UserBrief,
    status_code=status.HTTP_201_CREATED,
)
async def add_collaborator(
    job_id: int,
    payload: JobCollaboratorAdd,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Add a collaborator. Admin/DL always; otherwise primary owner only.

    Idempotent at the DB layer via UNIQUE(job_id, user_id) — duplicate inserts
    return the existing row instead of raising.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    await _require_manage_ownership(job, current_user)

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if not target or not target.is_active:
        raise HTTPException(status_code=409, detail="Target user not found or inactive")
    if target.role not in _OWNERSHIP_ELIGIBLE_ROLES:
        raise HTTPException(
            status_code=409,
            detail=f"Role {target.role.value} cannot be a collaborator",
        )
    if job.recruiter_id == target.id:
        raise HTTPException(
            status_code=409,
            detail="User is already the primary owner of this job",
        )

    existing = await db.scalar(
        select(JobCollaborator).where(
            JobCollaborator.job_id == job_id,
            JobCollaborator.user_id == target.id,
        )
    )
    if existing is None:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=target.id,
                added_by=current_user.id,
            )
        )
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="collaborator_added",
                user_id=current_user.id,
                details={"collaborator_id": target.id},
            )
        )
        await db.commit()
    return UserBrief.model_validate(target)


@router.delete(
    "/{job_id}/collaborators/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_collaborator(
    job_id: int,
    user_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Remove a collaborator. Admin/DL always; otherwise primary owner only."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    await _require_manage_ownership(job, current_user)

    link = await db.scalar(
        select(JobCollaborator).where(
            JobCollaborator.job_id == job_id,
            JobCollaborator.user_id == user_id,
        )
    )
    if link is None:
        # Idempotent: deleting a missing link is a success (204).
        return
    removed_source = link.source.value if link.source else "manual"
    await db.delete(link)
    # Feedback loop: when an auto_cc collaborator is removed we log to Activity
    # so Head of Recruitment can spot patterns (e.g. one sourcer removed 10×
    # from the same CC → revise user↔CC mapping). Stored on the Activity row
    # rather than the deleted row for queryability.
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=(
                "collaborator_removed_auto_cc"
                if removed_source == "auto_cc"
                else "collaborator_removed"
            ),
            user_id=current_user.id,
            details={
                "collaborator_id": user_id,
                "source": removed_source,
            },
        )
    )
    await db.commit()


# ── AI CC classification (migracja 0041) ────────────────────────────────────


def _cc_score_to_schema(score) -> CcSuggestion:
    """Map `cc_classifier.CcScore` → `CcSuggestion` pydantic schema."""
    return CcSuggestion(
        competence_category_id=score.cc_id,
        slug=score.slug,
        name_pl=score.name_pl,
        score=score.score,
        confidence_band=score.confidence_band,
        keywords_matched=score.keywords_matched,
    )


@router.post("/{job_id}/classify-cc", response_model=CcSuggestionsResponse)
async def classify_job_cc(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CcSuggestionsResponse:
    """Return top-3 CC suggestions for a job (current state, no DB write)."""
    from app.services.cc_classifier import classify_job_to_cc

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await classify_job_to_cc(job, db)
    top_schema = _cc_score_to_schema(result.top) if result.top else None
    alternatives = [_cc_score_to_schema(s) for s in result.alternatives]
    return CcSuggestionsResponse(
        top=top_schema, alternatives=alternatives, tie=result.tie
    )


@router.post("/{job_id}/cc-override", status_code=status.HTTP_201_CREATED)
async def log_cc_override(
    job_id: int,
    body: CcOverrideRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Log that a DL changed the AI-suggested CC. Used for feedback loop."""
    from app.models.cc_feedback import CcSuggestionOverride

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    override = CcSuggestionOverride(
        job_id=job_id,
        suggested_cc_id=body.suggested_cc_id,
        final_cc_id=body.final_cc_id,
        suggested_score=body.suggested_score,
        user_id=current_user.id,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return {
        "id": override.id,
        "job_id": job_id,
        "suggested_cc_id": body.suggested_cc_id,
        "final_cc_id": body.final_cc_id,
    }
