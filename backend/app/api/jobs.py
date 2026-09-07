import enum
import logging
from datetime import date, datetime, timezone
from typing import Annotated, Optional

import httpx

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import (
    and_,
    func,
    nulls_last,
    or_,
    select,
    tuple_,
    update as sql_update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.cache import cache_invalidate
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.contract import Contract, ContractStatus
from app.services.pipeline_latest import latest_stage_ids
from app.models.job import Job, JobStatus, RecruitmentType
from app.models.job_collaborator import JobCollaborator
from app.models.activity import Activity
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_priority import (
    PriorityChannel,
    PriorityMemberStatus,
    PriorityOriginKind,
    PriorityPlanStatus,
    RecruitmentPriorityAssignment,
    RecruitmentPriorityDemand,
    RecruitmentPriorityException,
    RecruitmentPriorityPlan,
    RecruitmentPriorityPlanMember,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.team_structure import ClientTacAssignment
from app.models.user import User, UserRole
from app.schemas.champion import (
    ChampionBriefingRequest,
    ChampionVerificationRequest,
    RecommendedSearchDecision,
)
from app.schemas.job import (
    CcOverrideRequest,
    CcSuggestion,
    CcSuggestionsResponse,
    JobCloseRequest,
    JobCollaboratorAdd,
    JobCreate,
    JobHandoffRequest,
    JobOwnerAssignment,
    JobResponse,
    JobUpdate,
    UserBrief,
)
from app.api.clients_team import TAC_ASSIGNABLE_ROLES
from app.api.candidate_access import redact_job_for_viewer
from app.api.deps import (
    CurrentUser,
    DeliveryLeadPlus,
    OperationalUser,
    RecruiterPlus,
    TacPlus,
    require_roles,
)
from app.services.auto_assign_owners import resolve_default_owners
from app.api.notifications import create_notification
from app.api.recruitment_access import (
    assert_delivery_lead_job_visible,
    delivery_lead_job_pairs,
    ensure_champion_job_read_visible,
    ensure_delivery_lead_job_visible,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.api.ws import manager as ws_manager
from app.core.config import settings
from app.services.recruitment_allocation import (
    allocation_lock,
    assign_operator,
    release_operator,
    enqueue_allocation,
)
from app.services.workforce_availability import (
    operational_owner_clause,
    operational_job_owner_clause,
)
from app.services import champion_view
from app.services.job_readiness import job_readiness_blockers as _compute_job_readiness
from app.services.champion_profile_events import (
    diff_champion_profile,
    summarize_sections,
)
from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
from app.services.candidate_contact_hooks import (
    maybe_close_job_contact_opportunities,
)
from app.services.marketplace_service import (
    is_significant_job_update,
    run_marketplace_scan_safe,
)
from app.services.similar_job_notify import run_similar_job_notify_safe
from app.services.recruitment_process_commands import open_process
from app.tasks.compute_proposals import (
    compute_proposal_for_job,
    create_pending_snapshot,
)
from app.models.proposal_snapshot import SOURCE_HANDOFF

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


# GET-only recruitment history/Champion surfaces. Finance gains organization-
# wide business read without inheriting any DeliveryLeadPlus mutations.
RecruitmentHistoryReadUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.finance,
        )
    ),
]


# Moved to `app.api.recruitment_access` so surfaces outside this router — a
# Champion suggestion, a note linked to a job — can reach the same guard
# without importing this 3 400-line module. Re-exported here so the 26 call
# sites below stay untouched and, more importantly, so there is exactly ONE
# implementation of "may this user see this job".
_delivery_lead_job_pairs = delivery_lead_job_pairs
_assert_delivery_lead_job_visible = assert_delivery_lead_job_visible
_ensure_delivery_lead_job_visible = ensure_delivery_lead_job_visible


def _apply_delivery_lead_job_scope(
    query,
    allowed_pairs: frozenset[tuple[int, int]] | None,
):
    """Apply the canonical client–TAC relationship graph to a Job list."""

    if allowed_pairs is None:
        return query
    return query.where(
        tuple_(Job.client_id, Job.tac_id).in_(sorted(allowed_pairs) or [(-1, -1)])
    )


def _assert_delivery_lead_client_visible(
    client_id: int | None,
    allowed_pairs: frozenset[tuple[int, int]] | None,
) -> None:
    """Fail closed when a DL addresses a client outside their assignments."""

    if allowed_pairs is None:
        return
    if client_id is None or not any(
        allowed_client_id == client_id for allowed_client_id, _ in allowed_pairs
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client is outside the resolved Delivery Lead scope",
        )


def _assert_delivery_lead_cross_client_disabled(
    cross_client: bool,
    allowed_pairs: frozenset[tuple[int, int]] | None,
) -> None:
    if allowed_pairs is not None and cross_client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-client job data is outside the Delivery Lead scope",
        )


def _assert_delivery_lead_finance_write(
    fields_set: set[str],
    current_user: User,
) -> None:
    """DL/TCM may never create or mutate recruitment budget fields."""

    if (
        current_user.has_any_role(
            UserRole.delivery_lead,
            UserRole.talent_community_manager,
        )
        and not current_user.has_role(UserRole.admin)
        and {"salary_min", "salary_max"} & fields_set
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery Leads cannot manage recruitment budget fields",
        )


def _redact_delivery_lead_job_finance(payload: dict, current_user: User) -> dict:
    """Remove recruitment budget fields from every non-Admin DL/TCM view."""

    if current_user.has_any_role(
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
    ) and not current_user.has_role(UserRole.admin):
        payload["salary_min"] = None
        payload["salary_max"] = None
    return payload


# Pola, których projekcja LISTY rekrutacji nie ma prawa wozić — niezależnie od
# roli pytającego.
_LIST_ONLY_STRIPPED_JOB_FIELDS: tuple[str, ...] = (
    "champion_profile",
    "close_notes",
)


def _strip_champion_payload_from_list_row(payload: dict) -> dict:
    """Zdejmij Profil Championa i wewnętrzne notatki z wiersza listy rekrutacji.

    Lista NIE jest powierzchnią Championa. `champion_profile` niesie nazwisko
    i `candidate_id` naszego konsultanta pracującego u klienta,
    `verification.client.key_corrections` (czego klient naprawdę potrzebuje),
    `internal_consultant_insight`, `sourcing.target_companies`, wzorcowe
    odpowiedzi screeningowe wraz z `deal_breaker` oraz klucz nagrania
    briefingu. `close_notes` to wewnętrzny komentarz do przegranej. Oba są na
    liście `_VIEWER_REDACTED_JOB_FIELDS` — repo od dawna uważa je za wrażliwe.

    Detal (`GET /api/jobs/{id}`) i dedykowany `.../champion-profile` mają dla
    nich bramkę ZAKRESU (`_ensure_delivery_lead_job_visible`) — pytają o jedną
    rekrutację, więc da się sprawdzić, czy pytający ma do NIEJ dostęp. Lista
    z definicji takiej bramki mieć nie może, bo zwraca N wierszy naraz, a jej
    widoczność jest regulowana wyłącznie filtrem zapytania. To czyni ją cichym
    kanałem obocznym: KAŻDE poszerzenie widoczności rejestru (np. otwarcie go
    Delivery Leadom, żeby pusty graf przypisań nie dawał „Brak rekrutacji")
    wynosi przy okazji Championa całej organizacji jednym żądaniem
    `?page_size=100`. Ta klasa wraca w repo raz po raz — bramka na jednej
    trasie, ta sama treść bez bramki na trasie równoległej
    (`champion_suggestions.py`: „any Delivery Lead could read another client's
    Champion draft by incrementing an integer"; tam trzeba było enumerować po
    jednym id, tutaj wystarcza jedno żądanie).

    Dlatego zdejmujemy je z projekcji BEZWARUNKOWO, zamiast dokładać kolejną
    redakcję zależną od roli: front nie ma tu konsumenta (`champion_profile`
    czytają wyłącznie detal, arkusz screeningowy i publiczna karta share), więc
    ten JSONB jechał do przeglądarki bez odbiorcy. Redakcja per rola musiałaby
    być poprawiana przy każdej zmianie widoczności listy; brak pola w
    projekcji nie musi.

    Ustawiamy `None`, nie usuwamy klucza — KSZTAŁT odpowiedzi zostaje bez
    zmian, tak samo jak w `redact_job_for_viewer`.
    """

    for field in _LIST_ONLY_STRIPPED_JOB_FIELDS:
        if field in payload:
            payload[field] = None
    return payload


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

# Fields that feed the deterministic scorer / eligibility but NOT the embedding
# text. Editing them must invalidate cached scores + flag the snapshot stale so
# the recruiter is prompted to re-run — but must NOT re-embed (they are absent
# from `_build_job_text`). `location`/`remote_policy` drive the location layer
# (scoring_service `_score_location`); `deadline` drives availability. Salary is
# intentionally omitted: candidate B2B PLN/h vs job PLN/month is always
# not_comparable → neutral, so it never moves a score (see P0-B1).
_SCORING_INPUT_FIELDS = _EMBED_TRIGGER_FIELDS | {
    "location",
    "remote_policy",
    "deadline",
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
    if not user.has_any_role(*allowed_roles):
        allowed = "/".join(sorted(r.value for r in allowed_roles))
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{field} must reference a user with role {allowed}",
        )


async def _validate_tac_client_assignment(
    db: AsyncSession,
    *,
    user_id: int,
    client_id: int,
) -> None:
    """Require an explicit Job TAC to belong to the selected client team."""

    assignment_id = (
        await db.execute(
            select(ClientTacAssignment.id).where(
                ClientTacAssignment.tac_user_id == user_id,
                ClientTacAssignment.client_id == client_id,
            )
        )
    ).scalar_one_or_none()
    if assignment_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=("tac_id must reference a TAC assigned to the selected client_id"),
        )


async def _maybe_embed_job(job_id: int, db: AsyncSession) -> None:
    """Fire-and-log job embedding (or enqueue a reindex); never raises."""
    try:
        from app.services.index_outbox_service import schedule_or_embed_job

        await schedule_or_embed_job(job_id, db)
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
    if current_user.has_any_role(UserRole.admin, UserRole.delivery_lead):
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


class PriorityWorkJobFilter(str, enum.Enum):
    """Priority Work context independent from legacy ownership/collaboration."""

    assigned = "assigned"
    carry_over = "carry_over"
    either = "either"


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
    priority_work: Optional[PriorityWorkJobFilter] = Query(
        None,
        description=(
            "Filter by the current user's published Priority Work assignment, "
            "open carry-over ownership, or either. Independent from `mine`, "
            "job owner and collaborators."
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

    # The recruitment register is an organization-wide discovery surface.
    # Delivery Leads still have their exact client–TAC scope enforced on job
    # details and every mutation below, but an empty relationship graph must
    # not turn the top-level /jobs register into "Brak rekrutacji".  Other
    # operational roles already see this complete register; DLs now follow the
    # same read-only list contract while finance fields remain redacted.
    query = select(Job)
    # Pary klient–TAC liczone RAZ dla całej strony (a nie per wiersz): to jedno
    # zapytanie, a używamy ich tylko do oznaczenia, które wiersze da się otworzyć.
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    priority_now = datetime.now(timezone.utc)
    priority_assignment_job_ids = (
        select(RecruitmentPriorityAssignment.job_id)
        .join(
            RecruitmentPriorityPlanMember,
            RecruitmentPriorityPlanMember.id
            == RecruitmentPriorityAssignment.plan_member_id,
        )
        .join(
            RecruitmentPriorityPlan,
            RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
        )
        .where(
            RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
            RecruitmentPriorityPlan.effective_from <= priority_now,
            operational_job_owner_clause(
                RecruitmentPriorityPlanMember.user_id,
                RecruitmentPriorityAssignment.job_id,
                current_user,
            ),
            RecruitmentPriorityPlanMember.status == PriorityMemberStatus.active,
        )
    )
    priority_carry_job_ids = select(RecruitmentProcess.job_id).where(
        operational_owner_clause(RecruitmentProcess.owner_user_id, current_user),
        RecruitmentProcess.status == ProcessStatus.open,
    )
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
            or_(
                operational_owner_clause(Job.recruiter_id, current_user),
                Job.id.in_(collab_subq),
            )
        )
    if priority_work == PriorityWorkJobFilter.assigned:
        query = query.where(Job.id.in_(priority_assignment_job_ids))
    elif priority_work == PriorityWorkJobFilter.carry_over:
        query = query.where(Job.id.in_(priority_carry_job_ids))
    elif priority_work == PriorityWorkJobFilter.either:
        query = query.where(
            or_(
                Job.id.in_(priority_assignment_job_ids),
                Job.id.in_(priority_carry_job_ids),
            )
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

    # Optional: stage breakdown per job. Single GROUP BY (no N+1) — liczy się
    # wyłącznie *bieżący* etap pary, wg kanonicznego `(moved_at DESC, id DESC)`.
    # Dawniej `MAX(id)`, co przy backdated imporcie z Traffita wskazywało inny
    # wiersz niż tablica i KPI (2 712 rozjeżdżonych par na produkcji).
    stage_breakdown: dict[int, dict[str, int]] = {}
    if include_stage_counts and job_ids:
        latest_per_cj = latest_stage_ids(job_ids=job_ids)
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

    # Client names batch lookup — denormalized na response (kolumna "Klient"
    # na liście ofert). coalesce(display_name, name) = kanoniczna nazwa
    # (spójne z /api/clients-lookup).
    from app.models.client import Client  # noqa: PLC0415

    client_ids_set = {j.client_id for j in jobs if j.client_id is not None}
    client_names: dict[int, str] = {}
    if client_ids_set:
        client_rows = await db.execute(
            select(Client.id, func.coalesce(Client.display_name, Client.name)).where(
                Client.id.in_(client_ids_set)
            )
        )
        client_names = {row[0]: row[1] for row in client_rows.all()}

    # Priority Work context is hydrated in two batch queries.  It deliberately
    # does not consult Job.recruiter_id or JobCollaborator: those legacy
    # concepts grant neither sourcing permission nor carry-over duty.
    priority_assignment_map: dict[int, dict[str, object]] = {}
    priority_carry_counts: dict[int, int] = {}
    if job_ids:
        priority_rows = (
            await db.execute(
                select(
                    RecruitmentPriorityAssignment.job_id,
                    RecruitmentPriorityAssignment.id,
                    RecruitmentPriorityAssignment.rank,
                    RecruitmentPriorityAssignment.position,
                    RecruitmentPriorityAssignment.channel,
                )
                .join(
                    RecruitmentPriorityPlanMember,
                    RecruitmentPriorityPlanMember.id
                    == RecruitmentPriorityAssignment.plan_member_id,
                )
                .join(
                    RecruitmentPriorityPlan,
                    RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
                )
                .where(
                    RecruitmentPriorityAssignment.job_id.in_(job_ids),
                    RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
                    RecruitmentPriorityPlan.effective_from <= priority_now,
                    operational_job_owner_clause(
                        RecruitmentPriorityPlanMember.user_id,
                        RecruitmentPriorityAssignment.job_id,
                        current_user,
                    ),
                    RecruitmentPriorityPlanMember.status == PriorityMemberStatus.active,
                )
                .order_by(RecruitmentPriorityAssignment.position)
            )
        ).all()
        for row in priority_rows:
            priority_assignment_map.setdefault(
                row.job_id,
                {
                    "id": row.id,
                    "rank": row.rank.value if row.rank else None,
                    "position": row.position,
                    "channel": row.channel.value,
                },
            )

        carry_rows = (
            await db.execute(
                select(
                    RecruitmentProcess.job_id,
                    func.count(RecruitmentProcess.id),
                )
                .where(
                    RecruitmentProcess.job_id.in_(job_ids),
                    operational_owner_clause(
                        RecruitmentProcess.owner_user_id, current_user
                    ),
                    RecruitmentProcess.status == ProcessStatus.open,
                )
                .group_by(RecruitmentProcess.job_id)
            )
        ).all()
        priority_carry_counts = {
            row_job_id: int(count) for row_job_id, count in carry_rows
        }

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
        d["client_name"] = (
            client_names.get(j.client_id) if j.client_id is not None else None
        )
        if include_stage_counts:
            d["stage_breakdown"] = stage_breakdown.get(j.id, {})
        d["priority_assignment"] = priority_assignment_map.get(j.id)
        d["priority_carry_over_count"] = priority_carry_counts.get(j.id, 0)
        redact_job_for_viewer(d, current_user)
        _redact_delivery_lead_job_finance(d, current_user)
        _strip_champion_payload_from_list_row(d)
        # Czy TEN wiersz da się otworzyć. Rejestr jest świadomie
        # ogólnofirmowy (komentarz przy budowie zapytania wyżej), ale detal
        # egzekwuje dokładny zakres klient–TAC, więc Delivery Lead bez
        # przypisań klikał kolejne wiersze i za każdym razem dostawał 403.
        # Komunikat 403 jest dobry, ale przychodzi PO kliknięciu — a dla DL
        # bez przypisań to znaczy: dwadzieścia kliknięć, dwadzieścia ślepych
        # zaułków. Flaga nie ujawnia niczego nowego: te wiersze i tak są na
        # liście, zmienia się tylko to, że użytkownik wie o nich ZAWCZASU.
        d["can_open"] = (
            delivery_lead_pairs is None
            or (j.client_id, j.tac_id) in delivery_lead_pairs
        )
        items.append(d)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobCreate,
    current_user: TacPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    _assert_delivery_lead_finance_write(data.model_fields_set, current_user)
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)

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
        _assert_delivery_lead_job_visible(src_job, delivery_lead_pairs)
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

    if current_user.has_role(UserRole.delivery_lead) and not current_user.has_role(
        UserRole.admin
    ):
        # A template must not become a side channel for copying recruitment
        # budget fields into a DL-created role.
        payload["salary_min"] = None
        payload["salary_max"] = None

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
        await _validate_tac_client_assignment(
            db,
            user_id=data.tac_id,
            client_id=payload["client_id"],
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
            if resolved.tac_selection_required:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "TAC_OWNER_REQUIRED",
                        "message": (
                            "Client has multiple assigned TACs; choose the "
                            "request owner explicitly"
                        ),
                    },
                )
            payload["tac_id"] = resolved.tac_id
        if payload.get("delivery_lead_id") is None:
            payload["delivery_lead_id"] = resolved.delivery_lead_id

    if (
        delivery_lead_pairs is not None
        and (
            payload.get("client_id"),
            payload.get("tac_id"),
        )
        not in delivery_lead_pairs
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Job is outside the resolved Delivery Lead scope",
        )

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
            # Title-first (deterministic, handles PL/EN role names), hybrid
            # keyword+embedding classifier as confident-only fallback.
            from app.services.job_cc import resolve_job_cc_id

            cc_id = await resolve_job_cc_id(job, db)
            if cc_id is not None:
                job.competence_category_id = cc_id
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

    # P0-A: the operational ranking is NO LONGER produced at create time. A
    # freshly-created job normally has no Champion yet, so a create-time snapshot
    # was a pre-Champion ranking that then persisted as "the" ranking even after
    # the Delivery Lead filled the Champion. The ranking is now produced by the
    # explicit "Przekaż do searchu" handoff (POST /jobs/{id}/handoff), after the
    # readiness gate (Champion required) passes. The job is still embedded above
    # (_maybe_embed_job) so reverse matching (candidate → jobs) keeps working,
    # and the widget falls back to the live recommendation path until the first
    # handoff snapshot exists.

    # Targ kandydatów (migracja 0052-0054): jeśli enabled, rescan puli marketplace
    # z tym nowym jobem i wygeneruj notyfikacje ≥ MARKETPLACE_SCORE_THRESHOLD.
    # Dedup przez uq_marketplace_alert_pair — ten sam job nigdy nie wygeneruje
    # drugiej notyfikacji dla tej samej pary (candidate_id, job_id).
    if settings.MARKETPLACE_ENABLED:
        background_tasks.add_task(run_marketplace_scan_safe, job.id)

    # Szybkie przepinanie (Faza 1): jeśli nowy request przypomina historyczne
    # (Tier A) z kandydatami po etapach klienckich — powiadom recruiter/TAC/
    # twórcę z deep-linkiem do sekcji „Kandydaci z podobnych projektów".
    # Embedding joba już istnieje (await _maybe_embed_job wyżej).
    if settings.SIMILAR_JOB_NOTIFY_ENABLED:
        background_tasks.add_task(run_similar_job_notify_safe, job.id)
    # Final refresh — upstream sesje (snapshot, auto_cc_collaborators,
    # classify_job_to_cc) mogly commitnac w miedzyczasie, co expire-uje
    # nasz `job` obiekt. FastAPI robi response_model walidacje przez
    # getattr na atrybutach joba — expired atrybut w async sesji rzuca
    # MissingGreenlet co objawia sie jako ResponseValidationError.
    await db.refresh(job)
    response = JobResponse.model_validate(job).model_dump()
    return _redact_delivery_lead_job_finance(response, current_user)


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
    stmt = _apply_delivery_lead_job_scope(
        stmt,
        await _delivery_lead_job_pairs(current_user, db),
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
    _assert_delivery_lead_job_visible(
        job,
        await _delivery_lead_job_pairs(current_user, db),
    )

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

    # Client name (denormalized, spójne z list_jobs)
    if job.client_id is not None:
        from app.models.client import Client  # noqa: PLC0415

        payload["client_name"] = await db.scalar(
            select(func.coalesce(Client.display_name, Client.name)).where(
                Client.id == job.client_id
            )
        )
    redact_job_for_viewer(payload, current_user)
    _redact_delivery_lead_job_finance(payload, current_user)
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
    result = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    _assert_delivery_lead_job_visible(job, delivery_lead_pairs)
    _assert_delivery_lead_finance_write(data.model_fields_set, current_user)

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

    # Changing either half of the relationship must leave a valid pair.  We
    # intentionally do not re-validate untouched historical Jobs during the
    # expand phase; only explicit owner/client mutations cross this gate.
    if {"tac_id", "client_id"} & data.model_fields_set:
        effective_tac_id = (
            data.tac_id if "tac_id" in data.model_fields_set else job.tac_id
        )
        effective_client_id = (
            data.client_id if "client_id" in data.model_fields_set else job.client_id
        )
        if effective_tac_id is not None and effective_client_id is not None:
            await _validate_tac_client_assignment(
                db,
                user_id=effective_tac_id,
                client_id=effective_client_id,
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
    if "needs_sourcing" in updates:
        job.favorite_sourcing_paused = False
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
    _assert_delivery_lead_job_visible(job, delivery_lead_pairs)

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
            # Lustro `close_job`. Odwrotnie NIE działa: wyjście ze stanu
            # `closed` nie wskrzesza `is_open`, bo „prowadzimy tę rekrutację"
            # jest decyzją człowieka (handoff), a nie skutkiem ubocznym
            # odblokowania statusu przez sync Traffita.
            job.is_open = False
            await maybe_close_job_contact_opportunities(
                db,
                job_id=job_id,
                actor_user_id=current_user.id,
                reason="job_closed",
                occurred_at=job.closed_at,
            )
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
    # changes. This uses the WIDER `_SCORING_INPUT_FIELDS` (not the embed set):
    # location/remote_policy/deadline move the score without changing the
    # embedding text, so gating on `_EMBED_TRIGGER_FIELDS` would leave a ranking
    # silently stale after those edits (P0-03a).
    if _SCORING_INPUT_FIELDS & changed:
        from app.services.match_score_cache import mark_stale_for_job

        await mark_stale_for_job(db, job_id)
        await db.commit()

        # P0-B: a brief edit changed a matching input — flag the latest proposal
        # snapshot stale so the recruiter is prompted to re-run instead of seeing
        # an outdated ranking as current.
        from app.services.job_matching_refresh import mark_latest_snapshot_stale

        await mark_latest_snapshot_stale(job_id, db)

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
    return _redact_delivery_lead_job_finance(payload, current_user)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    process_rows = int(
        await db.scalar(
            select(func.count(RecruitmentProcess.id)).where(
                RecruitmentProcess.job_id == job_id,
            )
        )
        or 0
    )
    stage_rows = int(
        await db.scalar(
            select(func.count(CandidateStage.id)).where(CandidateStage.job_id == job_id)
        )
        or 0
    )
    # Trzy tabele priority trzymają FK do jobs z ON DELETE RESTRICT (migracja 0200),
    # a Job nie ma do nich relacji, więc db.delete(job) nie kasuje dzieci — bez tego
    # zliczenia Postgres wywalał ForeignKeyViolation → nieobsłużone 500 zamiast 409.
    priority_demand_rows = int(
        await db.scalar(
            select(func.count(RecruitmentPriorityDemand.id)).where(
                RecruitmentPriorityDemand.job_id == job_id
            )
        )
        or 0
    )
    priority_assignment_rows = int(
        await db.scalar(
            select(func.count(RecruitmentPriorityAssignment.id)).where(
                RecruitmentPriorityAssignment.job_id == job_id
            )
        )
        or 0
    )
    priority_exception_rows = int(
        await db.scalar(
            select(func.count(RecruitmentPriorityException.id)).where(
                RecruitmentPriorityException.job_id == job_id
            )
        )
        or 0
    )
    if (
        process_rows
        or stage_rows
        or priority_demand_rows
        or priority_assignment_rows
        or priority_exception_rows
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PRIORITY_CARRY_OVER_EXISTS",
                "job_id": job_id,
                "process_rows": process_rows,
                "candidate_stage_rows": stage_rows,
                "priority_demand_rows": priority_demand_rows,
                "priority_assignment_rows": priority_assignment_rows,
                "priority_exception_rows": priority_exception_rows,
                "message": (
                    "Request ma historię kandydatów lub otwarte carry-over. "
                    "Zamknij request zamiast usuwać jego audytowalny pipeline."
                ),
            },
        )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="deleted",
            user_id=current_user.id,
        )
    )
    await maybe_close_job_contact_opportunities(
        db,
        job_id=job_id,
        actor_user_id=current_user.id,
        reason="job_deleted",
        occurred_at=datetime.now(timezone.utc),
    )
    await db.delete(job)
    await db.commit()


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
    result = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    job.status = JobStatus.closed
    job.closed_at = datetime.now(timezone.utc)
    # Zamknięta rekrutacja nie jest przez nikogo prowadzona — bez tego digest
    # dopasowań i alerty terminów chodziłyby po niej dalej (0270).
    job.is_open = False
    job.close_reason = data.reason
    job.close_notes = data.notes
    await maybe_close_job_contact_opportunities(
        db,
        job_id=job_id,
        actor_user_id=current_user.id,
        reason="job_closed",
        occurred_at=job.closed_at,
    )

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
    payload = JobResponse.model_validate(job).model_dump()
    return _redact_delivery_lead_job_finance(payload, current_user)


@router.post("/{job_id}/publish")
async def publish_job(
    job_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    """Publish job — mark as published and queue portal syndication."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    job.status = JobStatus.published
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="published",
            user_id=current_user.id,
        )
    )
    await db.commit()
    return {"status": "published", "job_id": job_id}


# ── Champion Profile (Phase 10) ─────────────────────────────────────────────


# Alias na `champion_view.api_response` — normalizacja profilu do siedmiu sekcji
# mieszka tam, gdzie reszta wiedzy o obu kształtach, a nie w routerze. Nazwa
# zostaje krótka, bo pojawia się w dziewięciu miejscach tego pliku.
_champion_response = champion_view.api_response


@router.get("/{job_id}/champion-profile")
async def get_champion_profile(
    job_id: int, current_user: OperationalUser, db: AsyncSession = Depends(get_db)
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
    await _ensure_delivery_lead_job_visible(job, current_user, db)

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
        "champion_profile": _champion_response(job.champion_profile),
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
    from app.services.champion_job_sync import fill_job_columns_from_champion
    from app.services.job_matching_refresh import refresh_job_matching

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    old_profile = dict(job.champion_profile) if job.champion_profile else {}

    # Merge NA STARYM PROFILU, nie na samym payloadzie.
    #
    # Do 09.2026 walidacja szła wprost z payloadu, a `ChampionProfile` nie
    # deklarowało kluczy, które zapisuje parser dokumentu (`rate_value`,
    # `seniority_min_years`, `disqualifiers`, `client_standards`, `sectors`,
    # `role_name`, `work_mode`, `start_date`, `contract_length`, `rate_raw`).
    # Przy domyślnym `extra="ignore"` Pydantic je po cichu wyrzucał, więc
    # PIERWSZY zapis z edytora kasował 12 z 16 pól sparsowanego profilu —
    # w tym twardy sufit stawki i próg seniority, oba z realnym wpływem na
    # ranking. Nowy schemat zna wszystkie te pola, ale edytor nadal nie wysyła
    # każdego z nich, więc payload nakładamy NA zapisany profil.
    #
    # Stary profil najpierw MIGRUJEMY, potem nakładamy payload. Kolejność jest
    # nieprzypadkowa: gdyby scalać wprost, w bazie zostałyby obok siebie klucze
    # obu kształtów, a migracja uzupełnia puste pole nowej sekcji wartością ze
    # starego klucza — więc wyczyszczenie pola w edytorze nigdy by się nie
    # zapisało (kasujesz `search.keywords`, migracja wpisuje je z powrotem
    # z `sourcing.keywords`). Po normalizacji stare klucze już nie istnieją.
    normalized_old = (
        ChampionProfile.model_validate(old_profile).model_dump() if old_profile else {}
    )
    merged = dict(normalized_old)
    for key, value in (payload or {}).items():
        # Scalanie o jeden poziom w głąb: edytor wysyła komplet sekcji, ale
        # klient API może przysłać samo `{"basics": {"language": "EN"}}`.
        # Podmiana całej sekcji zgubiłaby wtedy stawkę i próg seniority —
        # dokładnie te pola, których utratę ten handler ma powstrzymać.
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    profile = ChampionProfile.model_validate(merged)
    new_profile = profile.model_dump()

    # Verification, briefing and recommended searches are server-stamped via
    # dedicated endpoints — a regular profile save must never overwrite
    # (or forge) them.
    for protected in ("verification", "briefing", "recommended_searches"):
        if old_profile.get(protected) is not None:
            new_profile[protected] = old_profile[protected]

    # Sekcja 3 „Stack technologiczny" jest jedynym miejscem w profilu, które ma
    # odpowiednik w KOLUMNACH oferty. Kolumny wygrywają wszędzie indziej
    # (scoring, `requirement_map`, filtry wyszukiwarki), a są puste na ~88%
    # ofert — więc nie zsynchronizowany stack byłby wpisany i niewidoczny dla
    # wszystkiego, co naprawdę go czyta.
    stack_must = [{"name": item.name, "level": None} for item in profile.stack.must]
    stack_nice = [{"name": item.name, "level": None} for item in profile.stack.nice]
    # Synchronizujemy, gdy edytor PRZYSŁAŁ sekcję `stack` — także wtedy, gdy
    # przysłał ją pustą. Warunek `if stack_must:` sprawiał, że wyczyszczenie
    # stacku w edytorze nigdy nie czyściło kolumn: Delivery Lead widział pustą
    # sekcję, a scoring, filtry i mapa wymagań dalej czytały skasowane
    # technologie. Payload BEZ sekcji `stack` nadal nie rusza kolumn — to
    # odróżnia „wyczyściłem" od „nie dotykałem".
    if "stack" in (payload or {}):
        job.must_skills = stack_must
        job.nice_skills = stack_nice

    # Sekcja 1 „Podstawowe informacje" ma odpowiednik w KOLUMNACH oferty
    # (`rate_budget_hourly`, `onsite_days_per_week`, `remote_policy`,
    # `location` — 0278). Te napędzają dealbreakery i bramkę handoffu, a bez
    # tej synchronizacji profil był dla nich martwy poza jednym ekranem
    # (generator uzasadnień dopasowania). FILL_EMPTY: nigdy nie nadpisuje
    # kolumny, która już ma wartość (ręczną albo z wcześniejszego zapisu
    # Championa) — patrz docstring `fill_job_columns_from_champion`.
    columns_filled = fill_job_columns_from_champion(job, profile.basics.model_dump())

    # Diff na ZNORMALIZOWANYM starym profilu. Porównanie kształtu sprzed
    # przebudowy z kształtem po niej zgłosiłoby zmianę każdej sekcji przy
    # pierwszym zapisie każdej z 949 ofert — czyli lawinę powiadomień „Delivery
    # Lead zmienił profil" o zmianie, której nie było.
    fields_changed = diff_champion_profile(normalized_old, new_profile)
    if not fields_changed:
        # Brak zmiany TREŚCI profilu nie znaczy brak zmiany dla silnika
        # matchingu: `columns_filled`/synchronizacja stacku żyją na `job`,
        # niezależnie od `champion_profile`. `get_db` commituje sesję na
        # wyjściu z handlera nawet bez tego jawnego commitu (kolumny by nie
        # przepadły), ale re-embed + inwalidacja cache'u wyników NIE
        # odpaliłyby się same — bez tego wypełnienie pustych kolumn nigdy
        # nie dotarłoby do rankingu recruitera.
        if columns_filled or "stack" in (payload or {}):
            await db.commit()
            await refresh_job_matching(job.id, db)
        return {
            "job_id": job.id,
            "champion_profile": _champion_response(job.champion_profile),
        }

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

    # P0-A: a Champion edit changes both the embedding (semantic query) and the
    # top-weighted scoring inputs — re-embed the job and invalidate cached match
    # scores so the Delivery Lead's work actually reaches the recruiter's ranking
    # (previously this write bypassed the refresh update_job does).
    await refresh_job_matching(job.id, db)

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

    return {
        "job_id": job.id,
        "champion_profile": _champion_response(job.champion_profile),
    }


# ── "Przekaż do searchu" — DL handoff that starts matching (P0-A) ────────────


_HANDOFF_RECRUITER_ROLES = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
    UserRole.sourcer,
)


@router.get("/{job_id}/readiness")
async def get_job_readiness(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Czego brakuje, żeby przekazać rekrutację do searchu — PRZED kliknięciem.

    Ta sama lista, którą `POST /jobs/{id}/handoff` zwraca w 422. Wystawiona
    osobno, bo dowiadywanie się o brakach dopiero z odrzuconego żądania jest
    najgorszym momentem: na próbce 100 rekrutacji z produkcji bramkę przechodzą
    23, więc trzy na cztery kliknięcia kończyły się błędem, który dało się
    pokazać wcześniej.

    Odczyt, nie mutacja — świadomie NIE tworzy snapshotu ani niczego nie
    stempluje, żeby dało się to wołać przy każdym renderze zakładki.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    blockers = _compute_job_readiness(job)
    # Zamknięta rekrutacja nie jest „niegotowa" — jej się po prostu nie
    # przekazuje. Lustro guardu 409 w samym handoffie; bez tego przycisk
    # wyglądałby na możliwy do odblokowania uzupełnieniem Championa.
    is_closed = job.status == JobStatus.closed
    return {
        "job_id": job.id,
        "ready": not blockers and not is_closed,
        "blockers": blockers,
        "closed": is_closed,
        "already_handed_off": job.is_open,
        "allocation_enabled": settings.RECRUITMENT_ALLOCATION_ENABLED,
    }


@router.post("/{job_id}/handoff", status_code=202)
async def handoff_job_to_search(
    job_id: int,
    current_user: DeliveryLeadPlus,
    background_tasks: BackgroundTasks,
    payload: JobHandoffRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """ "Przekaż do searchu" — the explicit DL handoff that starts matching.

    Replaces the create-time auto-ranking (P0-A): the ranking is produced only
    once the recruitment is ready (Champion filled) and a recruiter is assigned,
    so the recruiter never lands on a stale pre-Champion snapshot. Binds the
    recruiter via ``recruiter_id`` (job owner → job member); the Priority Work
    roster is written in the same transaction. Automatic handoffs are durably
    queued; an explicit manual retry produces a fresh matching snapshot.
    """
    await allocation_lock(db)
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    # Don't start a search for a closed recruitment — the ranking would be wasted
    # work on a job nobody is filling (PR #1036 review follow-up).
    if job.status == JobStatus.closed:
        raise HTTPException(
            status_code=409,
            detail="Rekrutacja jest zamknięta — nie można jej przekazać do searchu.",
        )

    blockers = _compute_job_readiness(job)
    if blockers:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Rekrutacja nie jest gotowa do przekazania do searchu.",
                "blockers": blockers,
            },
        )

    if payload.assignment_mode == "automatic":
        if not settings.RECRUITMENT_ALLOCATION_ENABLED:
            raise HTTPException(409, "Automatyczny przydział nie jest jeszcze włączony")
        if job.recruiter_id is not None:
            raise HTTPException(409, "Rekrutacja ma już prowadzącego; zmień go ręcznie")
        job.is_open = True
        job.needs_sourcing = True
        job.favorite_sourcing_paused = False
        request = await enqueue_allocation(
            db,
            job=job,
            actor_user_id=current_user.id,
            channel=PriorityChannel(payload.channel),
        )
        await db.commit()
        return {
            "status": "queued",
            "job_id": job.id,
            "recruiter_id": None,
            "snapshot_id": None,
            "allocation_request_id": request.id,
        }
    if payload.recruiter_id is None:
        raise HTTPException(422, "Wybierz prowadzącego albo przydział automatyczny")

    recruiter = await db.scalar(select(User).where(User.id == payload.recruiter_id))
    if recruiter is None or not recruiter.is_active:
        raise HTTPException(
            status_code=422,
            detail="Wybrany rekruter nie istnieje lub jest nieaktywny.",
        )
    if not recruiter.has_any_role(*_HANDOFF_RECRUITER_ROLES):
        raise HTTPException(
            status_code=422,
            detail="Wybrany użytkownik nie może prowadzić rekrutacji.",
        )

    await assign_operator(
        db,
        job=job,
        assignee=recruiter,
        channel=PriorityChannel(payload.channel),
        actor_user_id=current_user.id,
        source="manual_handoff",
        as_owner=True,
    )
    job.is_open = True
    job.needs_sourcing = True
    job.favorite_sourcing_paused = False
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="handed_off_to_search",
            user_id=current_user.id,
        )
    )
    await db.commit()

    top_k = payload.top_k or settings.MATCH_MAX_RESULTS
    snapshot_id = await create_pending_snapshot(
        job.id, top_k=top_k, source=SOURCE_HANDOFF, created_by=current_user.id
    )
    background_tasks.add_task(
        compute_proposal_for_job, snapshot_id, job.id, top_k=top_k
    )

    return {
        "status": "handed_off",
        "job_id": job.id,
        "recruiter_id": recruiter.id,
        "snapshot_id": snapshot_id,
    }


# ── Champion Profile two-sided verification ─────────────────────────────────


@router.post("/{job_id}/champion-profile/verification")
async def update_champion_verification(
    job_id: int,
    payload: ChampionVerificationRequest,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record one side of the two-sided Champion Profile verification.

    The DL confirms the profile against (a) a conversation with the client —
    forcing them to articulate what changed vs. the original request — and
    (b) a conversation with one of our consultants placed at that client.
    Soft signal only: nothing blocks publishing. Stamps (who/when) are set
    server-side so a profile PUT can neither forge nor wipe them.
    """
    from app.schemas.champion import (
        ChampionProfile,
        ChampionVerification,
        ClientVerification,
        ConsultantVerification,
    )

    job_res = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    current_profile = dict(job.champion_profile or {})
    verification = ChampionVerification.model_validate(
        current_profile.get("verification") or {}
    )

    actor_name = (current_user.name or "").strip() or current_user.email
    now = datetime.now(timezone.utc)

    if payload.side == "client":
        if payload.reset:
            verification.client = ClientVerification()
        else:
            data = payload.client
            if data is None:
                raise HTTPException(
                    status_code=422, detail="Brak danych weryfikacji z klientem."
                )
            corrections = data.key_corrections.strip()
            if not corrections and not data.confirmed_as_is:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Opisz co zmieniło się względem requestu klienta albo "
                        "zaznacz, że request został potwierdzony 1:1."
                    ),
                )
            verification.client = ClientVerification(
                status="verified",
                verified_by_id=current_user.id,
                verified_by_name=actor_name,
                verified_at=now,
                method=data.method,
                key_corrections=corrections,
                confirmed_as_is=data.confirmed_as_is,
            )
    else:  # consultant
        if payload.reset:
            verification.consultant = ConsultantVerification()
        else:
            data = payload.consultant
            if data is None:
                raise HTTPException(
                    status_code=422, detail="Brak danych weryfikacji z konsultantem."
                )
            if data.skipped:
                if not data.skip_reason.strip():
                    raise HTTPException(
                        status_code=422,
                        detail="Podaj powód pominięcia (np. brak konsultanta u klienta).",
                    )
                verification.consultant = ConsultantVerification(
                    status="skipped",
                    verified_by_id=current_user.id,
                    verified_by_name=actor_name,
                    verified_at=now,
                    skip_reason=data.skip_reason.strip(),
                )
            else:
                consultant_name = data.consultant_name.strip()
                if data.consultant_candidate_id is not None:
                    consultant = await db.scalar(
                        select(Candidate).where(
                            Candidate.id == data.consultant_candidate_id
                        )
                    )
                    if not consultant:
                        raise HTTPException(
                            status_code=404, detail="Nie znaleziono konsultanta."
                        )
                    consultant_name = (
                        f"{consultant.name or ''} {consultant.lastname or ''}".strip()
                        or consultant_name
                    )
                if not consultant_name and data.consultant_candidate_id is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Wybierz konsultanta albo wpisz jego imię i nazwisko.",
                    )
                if not data.insights.strip():
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Zapisz wnioski z rozmowy z konsultantem — jak "
                            "naprawdę wygląda praca u klienta."
                        ),
                    )
                verification.consultant = ConsultantVerification(
                    status="verified",
                    verified_by_id=current_user.id,
                    verified_by_name=actor_name,
                    verified_at=now,
                    consultant_candidate_id=data.consultant_candidate_id,
                    consultant_name=consultant_name or None,
                    insights=data.insights.strip(),
                )

    # Re-validate the whole profile so we never persist a malformed JSONB.
    defaults = ChampionProfile().model_dump(mode="json")
    for k, v in defaults.items():
        current_profile.setdefault(k, v)
    current_profile["verification"] = verification.model_dump(mode="json")
    validated = ChampionProfile.model_validate(current_profile)
    job.champion_profile = validated.model_dump(mode="json")

    side_status = (
        verification.client.status
        if payload.side == "client"
        else verification.consultant.status
    )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="champion_verification_updated",
            user_id=current_user.id,
            details={"side": payload.side, "status": side_status},
        )
    )
    await db.commit()
    await db.refresh(job)
    return {
        "job_id": job.id,
        "champion_profile": _champion_response(job.champion_profile),
    }


@router.get("/{job_id}/champion-profile/consultant-suggestions")
async def champion_consultant_suggestions(
    job_id: int,
    current_user: RecruitmentHistoryReadUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Our consultants currently working at this job's client.

    Source signals, mirroring the `employment=at_client` filter but scoped to
    one client: latest pipeline stage `hired` (no later move for that job),
    an active Contract, or an active `current_employment` conflict. Used to
    pre-fill the consultant picker in the verification checklist.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await ensure_champion_job_read_visible(job, current_user, db)

    later_stage = aliased(CandidateStage)
    no_later_move = ~(
        select(1)
        .where(
            later_stage.candidate_id == CandidateStage.candidate_id,
            later_stage.job_id == CandidateStage.job_id,
            or_(
                later_stage.moved_at > CandidateStage.moved_at,
                and_(
                    later_stage.moved_at == CandidateStage.moved_at,
                    later_stage.id > CandidateStage.id,
                ),
            ),
        )
        .exists()
    )
    hired_rows = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.name,
                Candidate.lastname,
                Job.title,
                CandidateStage.moved_at,
            )
            .join(CandidateStage, CandidateStage.candidate_id == Candidate.id)
            .join(Job, Job.id == CandidateStage.job_id)
            .where(
                Job.client_id == job.client_id,
                CandidateStage.stage == PipelineStage.hired,
                no_later_move,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(30)
        )
    ).all()

    contract_rows = (
        await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname)
            .join(Contract, Contract.candidate_id == Candidate.id)
            .where(
                Contract.client_id == job.client_id,
                Contract.status == ContractStatus.active,
            )
            .limit(30)
        )
    ).all()

    conflict_rows = (
        await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname)
            .join(CandidateConflict, CandidateConflict.candidate_id == Candidate.id)
            .where(
                CandidateConflict.client_id == job.client_id,
                CandidateConflict.type == ConflictType.current_employment,
                CandidateConflict.active.is_(True),
            )
            .limit(30)
        )
    ).all()

    out: list[dict] = []
    seen: set[int] = set()
    for cid, first, last, title, moved_at in hired_rows:
        if cid in seen:
            continue
        seen.add(cid)
        out.append(
            {
                "candidate_id": cid,
                "name": f"{first or ''} {last or ''}".strip(),
                "job_title": title,
                "since": moved_at.isoformat() if moved_at else None,
            }
        )
    for cid, first, last in [*contract_rows, *conflict_rows]:
        if cid in seen:
            continue
        seen.add(cid)
        out.append(
            {
                "candidate_id": cid,
                "name": f"{first or ''} {last or ''}".strip(),
                "job_title": None,
                "since": None,
            }
        )
    return out


# ── Champion Profile briefing (breakout session DL → rekruterzy) ────────────


async def _write_briefing_block(db: AsyncSession, job: Job, briefing: dict) -> None:
    """Persist the `briefing` block into champion_profile with full-profile
    re-validation (mirrors the verification endpoint)."""
    from app.schemas.champion import ChampionProfile

    current_profile = dict(job.champion_profile or {})
    defaults = ChampionProfile().model_dump(mode="json")
    for k, v in defaults.items():
        current_profile.setdefault(k, v)
    current_profile["briefing"] = briefing
    validated = ChampionProfile.model_validate(current_profile)
    job.champion_profile = validated.model_dump(mode="json")


@router.post("/{job_id}/champion-profile/briefing")
async def set_champion_briefing(
    job_id: int,
    payload: ChampionBriefingRequest,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Attach a Fireflies meeting Note as THE briefing for this job.

    The DL records a breakout session explaining the role in their own words;
    recruiters listen to it from the Champion Profile. If the note carries a
    Fireflies `audio_url` we copy the audio into Object Storage (their CDN
    links expire). Optionally fires LLM enrichment so anything said verbally
    but missing from the written profile comes back as a suggestion.
    """
    from app.models.note import Note, NoteType
    from app.services import object_storage

    job_res = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    note = await db.scalar(select(Note).where(Note.id == payload.note_id))
    if not note:
        raise HTTPException(status_code=404, detail="Nie znaleziono notatki.")
    if note.note_type != NoteType.meeting:
        raise HTTPException(
            status_code=422,
            detail="Briefing musi być notatką meetingową (Fireflies).",
        )
    if note.job_id is not None and note.job_id != job_id:
        raise HTTPException(
            status_code=422,
            detail="Ta notatka jest podpięta do innej rekrutacji.",
        )

    # Unattached meeting → attach to this job as part of designation.
    if note.job_id is None:
        note.job_id = job_id

    # Copy audio into our bucket (best-effort — briefing works without audio).
    audio_storage_key: Optional[str] = None
    if note.audio_url and object_storage.is_available():
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                resp = await client.get(note.audio_url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "audio/mpeg")
                suffix = ".mp3" if "mpeg" in content_type else ".m4a"
                # Sync boto3 put_object — offload so the multi-MB audio upload
                # does not block the single-worker event loop.
                audio_storage_key = await run_in_threadpool(
                    object_storage.upload_briefing_audio,
                    resp.content,
                    filename=f"briefing-job-{job_id}{suffix}",
                    content_type=content_type,
                )
        except Exception as exc:  # noqa: BLE001 — audio is optional
            logger.warning(
                "[Briefing] audio download failed job=%s note=%s: %s",
                job_id,
                note.id,
                exc,
            )

    title_line = (
        note.content.split("\n", 1)[0].lstrip("# ").strip() if note.content else ""
    )
    actor_name = (current_user.name or "").strip() or current_user.email
    await _write_briefing_block(
        db,
        job,
        {
            "status": "attached",
            "note_id": note.id,
            "title": title_line or f"Meeting #{note.id}",
            "audio_storage_key": audio_storage_key,
            "attached_by_id": current_user.id,
            "attached_by_name": actor_name,
            "attached_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="champion_briefing_attached",
            user_id=current_user.id,
            details={"note_id": note.id, "has_audio": bool(audio_storage_key)},
        )
    )
    await db.commit()
    await db.refresh(job)

    # Cross-check: anything the DL said verbally but the written profile
    # misses comes back as a ChampionProfileSuggestion to accept/reject.
    suggestion_id: Optional[int] = None
    if payload.enrich:
        try:
            from app.services.champion_draft_service import enrich_from_meeting

            suggestion = await enrich_from_meeting(
                db,
                job_id=job_id,
                meeting_title=title_line or f"Meeting #{note.id}",
                meeting_summary="",
                meeting_transcript=note.content or "",
                source_ref=f"note:{note.id}",
                user_id=current_user.id,
            )
            suggestion_id = suggestion.id
        except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
            logger.warning(
                "[Briefing] enrichment failed job=%s note=%s: %s",
                job_id,
                note.id,
                exc,
            )

    return {
        "job_id": job.id,
        "champion_profile": _champion_response(job.champion_profile),
        "suggestion_id": suggestion_id,
    }


@router.delete("/{job_id}/champion-profile/briefing")
async def clear_champion_briefing(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Detach the briefing (keeps the meeting Note itself)."""
    from app.schemas.champion import ChampionBriefing
    from app.services import object_storage

    job_res = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    old_key = ((job.champion_profile or {}).get("briefing") or {}).get(
        "audio_storage_key"
    )
    if old_key and object_storage.is_available():
        try:
            # Sync boto3 delete_object — offload off the event loop.
            await run_in_threadpool(object_storage.delete_cv, old_key)
        except Exception:  # noqa: BLE001 — orphaned audio is harmless
            pass

    await _write_briefing_block(db, job, ChampionBriefing().model_dump(mode="json"))
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="champion_briefing_detached",
            user_id=current_user.id,
        )
    )
    await db.commit()
    await db.refresh(job)
    return {
        "job_id": job.id,
        "champion_profile": _champion_response(job.champion_profile),
    }


@router.get("/{job_id}/champion-profile/briefing/audio-url")
async def champion_briefing_audio_url(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Short-lived presigned URL for the briefing audio.

    The <audio> element cannot send Authorization headers, so the FE fetches
    this endpoint (authed) and feeds the presigned URL into the player.
    """
    from app.services import object_storage

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    key = ((job.champion_profile or {}).get("briefing") or {}).get("audio_storage_key")
    if not key:
        raise HTTPException(status_code=404, detail="Briefing nie ma nagrania audio.")
    if not object_storage.is_available():
        raise HTTPException(status_code=503, detail="Object storage niedostępny.")
    url = object_storage.get_presigned_download_url(
        key, expires_in=600, filename="briefing.mp3", disposition="inline"
    )
    return {"url": url}


# ── Champion Profile recommended searches (AI-proposed, DL-approved) ────────


@router.post("/{job_id}/champion-profile/recommended-searches/generate")
async def generate_recommended_searches_endpoint(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """LLM proposes 2-3 candidate searches from the Champion Profile.

    Subject to the Settings → AI quota for `champion_draft`. Proposals are
    stored in champion_profile.recommended_searches with status `proposed`
    until the DL approves/rejects them.
    """
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import AIQuotaExceeded, ai_feature
    from app.services.champion_draft_service import generate_recommended_searches

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    # `ai_feature`, nie gołe `check_and_increment`: obciążenie i DEKLARACJA
    # w jednym kroku — bez deklaracji wywołanie dolatuje do granicy dostawcy
    # jako niezadeklarowane i pod AI_QUOTA_STRICT rzuca, mimo naliczonej kwoty.
    #
    # Przy okazji 429 → 503 (C-8 z audytu): to była JEDYNA trasa mapująca
    # wyczerpaną kwotę na 429 — dwie bliźniacze niżej zawsze zwracały 503 ze
    # słownikiem `detail`, i to ten kształt zna front.
    try:
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=current_user.id):
            profile = await generate_recommended_searches(
                db, job_id=job_id, user_id=current_user.id
            )
    except AIQuotaExceeded as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — LLM failures surface as 502
        logger.warning(
            "[RecommendedSearches] generation failed job=%s: %s", job_id, exc
        )
        raise HTTPException(
            status_code=502,
            detail="Nie udało się wygenerować propozycji wyszukiwań — spróbuj ponownie.",
        ) from exc
    return {"job_id": job_id, "champion_profile": _champion_response(profile)}


@router.post("/{job_id}/champion-profile/recommended-searches/decision")
async def decide_recommended_search(
    job_id: int,
    payload: RecommendedSearchDecision,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve / reject / reset one AI-proposed search.

    Approve materialises a `SavedSearch` (entity=candidates) pinned to this
    job and shared with the team — the job's "Wyszukaj manualnie" tab then
    surfaces it for every recruiter, who activates it in one click. Reset
    deletes the materialised SavedSearch (best-effort) and re-opens the
    proposal.
    """
    from app.models.saved_search import SavedSearch
    from app.schemas.champion import ChampionProfile, RecommendedSearch

    job_res = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    profile = dict(job.champion_profile or {})
    entries: list[RecommendedSearch] = []
    target: Optional[RecommendedSearch] = None
    for raw in profile.get("recommended_searches") or []:
        try:
            entry = RecommendedSearch.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue
        entries.append(entry)
        if entry.id == payload.search_id:
            target = entry
    if target is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono propozycji.")

    actor_name = (current_user.name or "").strip() or current_user.email
    now = datetime.now(timezone.utc)

    if payload.action == "approve":
        if not (target.status == "approved" and target.saved_search_id):
            saved = SavedSearch(
                user_id=current_user.id,
                name=target.name[:100],
                entity="candidates",
                # Shape = CandidateSearchRequest subset — the job's manual
                # search tab spreads it straight into its request state.
                filters=target.params.model_dump(exclude_none=True),
                shared=True,
                description=(target.rationale or "Rekomendacja AI")[:255],
                pinned_to_job_id=job_id,
            )
            db.add(saved)
            await db.flush()
            target.saved_search_id = saved.id
        target.status = "approved"
        target.decided_by_id = current_user.id
        target.decided_by_name = actor_name
        target.decided_at = now
    elif payload.action == "reject":
        target.status = "rejected"
        target.decided_by_id = current_user.id
        target.decided_by_name = actor_name
        target.decided_at = now
    else:  # reset
        if target.saved_search_id:
            stale = await db.scalar(
                select(SavedSearch).where(SavedSearch.id == target.saved_search_id)
            )
            if stale:
                await db.delete(stale)
        target.status = "proposed"
        target.saved_search_id = None
        target.decided_by_id = None
        target.decided_by_name = None
        target.decided_at = None

    defaults = ChampionProfile().model_dump(mode="json")
    for k, v in defaults.items():
        profile.setdefault(k, v)
    profile["recommended_searches"] = [e.model_dump(mode="json") for e in entries]
    validated = ChampionProfile.model_validate(profile)
    job.champion_profile = validated.model_dump(mode="json")

    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="champion_recommended_search_decision",
            user_id=current_user.id,
            details={"search_id": payload.search_id, "action": payload.action},
        )
    )
    await db.commit()
    await db.refresh(job)
    return {
        "job_id": job.id,
        "champion_profile": _champion_response(job.champion_profile),
    }


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
    from app.services.ai_quota import AIQuotaExceeded, ai_feature
    from app.services.champion_draft_service import generate_from_jd

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    body = GenerateFromJdPayload.model_validate(payload or {})
    try:
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=current_user.id):
            await db.commit()
            suggestion = await generate_from_jd(
                db,
                job_id=job_id,
                raw_description=body.raw_description,
                user_id=current_user.id,
            )
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
    from app.services.ai_quota import AIQuotaExceeded, ai_feature
    from app.services.champion_draft_service import generate_from_historical_jobs

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    body = GenerateFromHistoryPayload.model_validate(payload or {})
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    _assert_delivery_lead_cross_client_disabled(
        body.cross_client,
        delivery_lead_pairs,
    )
    from app.services.champion_draft_service import HistoricalSearchUnavailable

    try:
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=current_user.id):
            await db.commit()
            suggestion = await generate_from_historical_jobs(
                db,
                job_id=job_id,
                raw_description=body.raw_description,
                top_k=body.top_k,
                cross_client=body.cross_client,
                user_id=current_user.id,
            )
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
    except HistoricalSearchUnavailable as exc:
        # 503, nie 200 z odrzuceniem. Poprzednio awaria kończyła się wierszem
        # „znaleziono 0, wymagane co najmniej 2" — nieprawdą o danych klienta,
        # zapisaną do bazy, plus skasowaniem gotowej propozycji `pending`.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return out


@router.get("/{job_id}/champion-profile/historical-matches")
async def get_champion_historical_matches(
    job_id: int,
    current_user: RecruitmentHistoryReadUser,
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
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    await ensure_champion_job_read_visible(job, current_user, db)
    _assert_delivery_lead_cross_client_disabled(cross_client, delivery_lead_pairs)

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

    # `None` = wyszukiwanie nie odpowiedziało. Pusta lista z HTTP 200 czytałaby
    # się jako „u tego klienta nie ma podobnych domkniętych rekrutacji" — czyli
    # twierdzenie o danych klienta zamiast informacji o awarii.
    if matches is None:
        return HistoricalMatchesResponse(
            matches=[],
            skill_frequency={},
            degraded=True,
            degraded_reason=(
                "Wyszukiwanie podobnych rekrutacji jest chwilowo niedostępne — "
                "to nie znaczy, że u tego klienta ich nie ma."
            ),
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
    current_user: RecruitmentHistoryReadUser,
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
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    _assert_delivery_lead_client_visible(body.client_id, delivery_lead_pairs)
    _assert_delivery_lead_cross_client_disabled(
        body.cross_client,
        delivery_lead_pairs,
    )

    matches = await find_similar_historical_jobs(
        db,
        client_id=body.client_id,
        title=body.title,
        raw_description=body.raw_description,
        train_name=body.train_name,
        top_k=body.top_k,
        cross_client=body.cross_client,
    )

    # `None` = wyszukiwanie nie odpowiedziało. Pusta lista z HTTP 200 czytałaby
    # się jako „u tego klienta nie ma podobnych domkniętych rekrutacji" — czyli
    # twierdzenie o danych klienta zamiast informacji o awarii.
    if matches is None:
        return HistoricalMatchesResponse(
            matches=[],
            skill_frequency={},
            degraded=True,
            degraded_reason=(
                "Wyszukiwanie podobnych rekrutacji jest chwilowo niedostępne — "
                "to nie znaczy, że u tego klienta ich nie ma."
            ),
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
    current_user: RecruitmentHistoryReadUser,
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
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    await ensure_champion_job_read_visible(job, current_user, db)
    _assert_delivery_lead_cross_client_disabled(cross_client, delivery_lead_pairs)

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
    current_user: RecruitmentHistoryReadUser,
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
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    _assert_delivery_lead_client_visible(body.client_id, delivery_lead_pairs)
    _assert_delivery_lead_cross_client_disabled(
        body.cross_client,
        delivery_lead_pairs,
    )

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
    await _ensure_delivery_lead_job_visible(job, current_user, db)

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

    # "Dodaj championa z historii" is exactly the flow that resurrects someone
    # this job's hiring manager already interviewed and turned down.
    from app.services.hiring_manager_verdicts import load_manager_rejections

    verdicts = await load_manager_rejections(
        db, job=job, candidate_ids=[payload.candidate_id]
    )
    verdict = verdicts.get(payload.candidate_id)
    if verdict is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=verdict.as_polish_detail())

    stage = await open_process(
        db,
        candidate_id=payload.candidate_id,
        job_id=job_id,
        stage=PipelineStage.new,
        actor_user_id=current_user.id,
        work_channel=PriorityChannel.database,
        # A Delivery Lead/manager adding a historical candidate is still a
        # human-created pair. Ownership, collaboration or manager role must
        # not bypass the published Priority Work assignment.
        origin_kind=PriorityOriginKind.assigned,
    )
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
    await maybe_ensure_contact_opportunity(
        db,
        candidate_id=payload.candidate_id,
        job_id=job_id,
        source="pipeline",
        occurred_at=stage.moved_at,
    )
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
    current_user: RecruitmentHistoryReadUser,
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

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await ensure_champion_job_read_visible(job, current_user, db)

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
    await allocation_lock(db)
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if not target or not target.is_active:
        raise HTTPException(status_code=409, detail="Target user not found or inactive")
    if not target.has_any_role(*_OWNERSHIP_ELIGIBLE_ROLES):
        raise HTTPException(
            status_code=409,
            detail=f"Role {target.role.value} cannot own a job",
        )

    if job.is_open and target.has_any_role(
        UserRole.recruiter, UserRole.sourcer, UserRole.tac
    ):
        channel = (
            PriorityChannel.database
            if target.has_role(UserRole.sourcer)
            and not target.has_role(UserRole.recruiter)
            else PriorityChannel.linkedin
        )
        await assign_operator(
            db,
            job=job,
            assignee=target,
            channel=channel,
            actor_user_id=current_user.id,
            source="manual_owner",
            as_owner=True,
        )
    else:
        await release_operator(db, job=job)
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
    await allocation_lock(db)
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    previous = job.recruiter_id
    await release_operator(db, job=job)
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
    if not current_user.has_any_role(*_OWNERSHIP_ELIGIBLE_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Read-only viewers cannot claim jobs",
        )

    await allocation_lock(db)
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    if job.recruiter_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job already has a primary owner",
        )

    if job.is_open and current_user.has_any_role(
        UserRole.recruiter, UserRole.sourcer, UserRole.tac
    ):
        channel = (
            PriorityChannel.database
            if current_user.has_role(UserRole.sourcer)
            and not current_user.has_role(UserRole.recruiter)
            else PriorityChannel.linkedin
        )
        await assign_operator(
            db,
            job=job,
            assignee=current_user,
            channel=channel,
            actor_user_id=current_user.id,
            source="manual_claim",
            as_owner=True,
        )
    else:
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
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """List collaborators (read-only participants) on a job."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
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
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    await _require_manage_ownership(job, current_user)

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if not target or not target.is_active:
        raise HTTPException(status_code=409, detail="Target user not found or inactive")
    if not target.has_any_role(*_OWNERSHIP_ELIGIBLE_ROLES):
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
    await _ensure_delivery_lead_job_visible(job, current_user, db)

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
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> CcSuggestionsResponse:
    """Return top-3 CC suggestions for a job (current state, no DB write)."""
    from app.services.cc_classifier import classify_job_to_cc

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

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
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Log that a DL changed the AI-suggested CC. Used for feedback loop."""
    from app.models.cc_feedback import CcSuggestionOverride

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

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
