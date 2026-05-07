from datetime import date, datetime, timedelta, timezone
from typing import Optional
import io
import logging
import re
import zipfile
import aiofiles
import os

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, false, func, not_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.candidate_document import CandidateDocument
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.contract import Contract, ContractStatus
from app.models.activity import Activity
from app.models.invite_link import CandidateInviteLink
from app.models.user_activity import UserActivity, UserActionType
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.job import Job, JobStatus
from app.models.talent_pool import TalentPoolMembership
from app.models.user import User
from app.schemas.candidate import (
    CandidateCreate,
    CandidateDocumentOut,
    CandidateEngagementUpdate,
    CandidateFromCVDuplicate,
    CandidateFromCVResponse,
    CandidateLinkedinSyncResponse,
    CandidateList,
    CandidateLocationUpdate,
    CandidateResponse,
    CandidateUpdate,
    EmploymentInfo,
    EmploymentState,
    InviteSourceBrief,
    LinkedinSnapshotSummary,
    MatchStats,
    TalentPoolBrief,
)
from app.services.scoring_service import (
    DEFAULT_PROFILE,
    WeightProfile,
    rank_jobs_for_candidate,
    resolve_active_profile,
    summarize_match_stats,
)
from app.services.dedup_service import find_candidate_duplicates
from app.api.deps import CurrentUser, RecruiterPlus, DeliveryLeadPlus
from app.api import ws as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class DuplicateCheckPayload(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    name: Optional[str] = None
    lastname: Optional[str] = None
    exclude_candidate_id: Optional[int] = None


def _build_response(data: dict) -> dict:
    return {"success": True, "data": data}


# Cap on how many open jobs we score per candidate when populating match stats.
# Keeps worst-case latency bounded: page_size × _MATCH_STATS_JOB_CAP score computes.
_MATCH_STATS_JOB_CAP = 50
_MATCH_STATS_DEFAULT_THRESHOLD = 50.0


def _candidate_list_options():
    """Eager-load relations required to derive employment state without N+1 lazy loads."""
    from app.models.linkedin_snapshot import CandidateLinkedinSnapshot  # noqa: F401

    return (
        selectinload(Candidate.contracts).selectinload(Contract.client),
        selectinload(Candidate.conflicts).selectinload(CandidateConflict.client),
        selectinload(Candidate.creator),
        # Pool membership + pool name for the `talent_pools` field on
        # CandidateResponse (used by the tile view and the "Puli" chips).
        selectinload(Candidate.pool_memberships).selectinload(
            TalentPoolMembership.pool
        ),
        # LinkedIn snapshots must be eager-loaded so Pydantic's from_attributes
        # validation does not trigger a lazy async load (MissingGreenlet). The
        # list endpoint strips them via `model_copy` to keep responses small;
        # the detail endpoint overrides with the top 5 via a separate query.
        selectinload(Candidate.linkedin_snapshots),
    )


def _at_client_predicate():
    """
    Derived SQL predicate: candidate has either an active Contract OR an active
    current_employment conflict. Used to filter the candidates list.
    """
    contract_exists = (
        select(1)
        .where(
            and_(
                Contract.candidate_id == Candidate.id,
                Contract.status == ContractStatus.active,
            )
        )
        .exists()
    )
    conflict_exists = (
        select(1)
        .where(
            and_(
                CandidateConflict.candidate_id == Candidate.id,
                CandidateConflict.type == ConflictType.current_employment,
                CandidateConflict.active.is_(True),
            )
        )
        .exists()
    )
    return or_(contract_exists, conflict_exists)


def _current_company_predicate(values: list[str]):
    """Match candidates whose experience[0].company ILIKE any of values (OR)."""
    clauses = []
    for v in values:
        v = (v or "").strip()
        if not v:
            continue
        pat = f"%{v.lower()}%"
        clauses.append(
            func.lower(
                func.coalesce(Candidate.experience.op("->")(0).op("->>")("company"), "")
            ).like(pat)
        )
    return or_(*clauses) if clauses else false()


def _current_title_predicate(values: list[str]):
    """Match candidates whose experience[0].role ILIKE any of values (OR)."""
    clauses = []
    for v in values:
        v = (v or "").strip()
        if not v:
            continue
        pat = f"%{v.lower()}%"
        clauses.append(
            func.lower(
                func.coalesce(Candidate.experience.op("->")(0).op("->>")("role"), "")
            ).like(pat)
        )
    return or_(*clauses) if clauses else false()


def _past_company_predicate(values: list[str]):
    """Match candidates with any NON-current experience at company matching value.

    Uses jsonb_array_elements WITH ORDINALITY; `ordinality > 1` skips the
    current job (index 0 in SQL ordinality terms). OR-combined across values.

    Guards against non-array `experience` values (legacy rows may have scalar/
    object JSONB) — `jsonb_array_elements` raises otherwise.
    """
    clauses = []
    for i, v in enumerate(values):
        v = (v or "").strip()
        if not v:
            continue
        pat = f"%{v.lower()}%"
        clauses.append(
            text(
                "EXISTS ("
                "SELECT 1 FROM jsonb_array_elements("
                "CASE WHEN jsonb_typeof(candidates.experience) = 'array' "
                "THEN candidates.experience ELSE '[]'::jsonb END"
                ") WITH ORDINALITY AS e(elem, idx) "
                f"WHERE idx > 1 AND lower(elem->>'company') LIKE :past_co_{i}"
                ")"
            ).bindparams(**{f"past_co_{i}": pat})
        )
    return or_(*clauses) if clauses else false()


def _worked_at_client_predicate(client_ids: list[int]):
    """Candidates who had ANY historical contract with, or a current_employment
    conflict flag for, one of these client ids.

    Intentionally ignores `Contract.status` and `CandidateConflict.active` — the
    filter means "ever worked at this client of ours". Current-only semantics
    are available via `employment=at_client`.
    """
    contract_any_exists = (
        select(1)
        .where(
            and_(
                Contract.candidate_id == Candidate.id,
                Contract.client_id.in_(client_ids),
            )
        )
        .exists()
    )
    conflict_any_exists = (
        select(1)
        .where(
            and_(
                CandidateConflict.candidate_id == Candidate.id,
                CandidateConflict.client_id.in_(client_ids),
                CandidateConflict.type == ConflictType.current_employment,
            )
        )
        .exists()
    )
    return or_(contract_any_exists, conflict_any_exists)


def _talent_pools_for(candidate: Candidate) -> list[TalentPoolBrief]:
    """Flatten eager-loaded pool_memberships into TalentPoolBrief list.

    Safe to call only when `pool_memberships.pool` is eager-loaded via
    `_candidate_list_options()` (otherwise raises MissingGreenlet in async).
    """
    return [
        TalentPoolBrief(id=m.pool.id, name=m.pool.name)
        for m in (candidate.pool_memberships or [])
        if m.pool is not None
    ]


def _candidate_to_response(candidate: Candidate) -> CandidateResponse:
    """Build CandidateResponse with derived employment + talent pools.

    Single-candidate endpoints (POST, PATCH /engagement, PATCH /location, etc.)
    use this helper so the response shape stays consistent with the list
    endpoint and Pydantic doesn't trip on the missing `talent_pools` attribute
    on the ORM model.
    """
    payload = CandidateResponse.model_validate(candidate)
    return payload.model_copy(
        update={
            "employment": _derive_employment(candidate),
            "talent_pools": _talent_pools_for(candidate),
        }
    )


def _derive_employment(candidate: Candidate) -> EmploymentInfo:
    """
    Compute EmploymentInfo from eager-loaded `contracts` + `conflicts`.
    Preference order: active Contract (source of truth) → active
    current_employment conflict (manual flag) → on_bench (has history) →
    external (never engaged).
    """
    active_contracts = [
        c for c in (candidate.contracts or []) if c.status == ContractStatus.active
    ]
    if active_contracts:
        chosen = max(
            active_contracts,
            key=lambda c: c.end_date or date.max,
        )
        return EmploymentInfo(
            state=EmploymentState.employed_at_client,
            client_id=chosen.client_id,
            client_name=chosen.client.name if chosen.client else None,
            contract_end_date=chosen.end_date,
            source="contract",
        )

    active_conflicts = [
        cf
        for cf in (candidate.conflicts or [])
        if cf.active and cf.type == ConflictType.current_employment
    ]
    if active_conflicts:
        chosen = active_conflicts[0]
        return EmploymentInfo(
            state=EmploymentState.employed_at_client,
            client_id=chosen.client_id,
            client_name=chosen.client.name if chosen.client else None,
            contract_end_date=None,
            source="conflict",
        )

    has_history = bool(candidate.contracts) or any(
        cf.type == ConflictType.current_employment for cf in (candidate.conflicts or [])
    )
    if has_history:
        return EmploymentInfo(state=EmploymentState.on_bench, source="none")
    return EmploymentInfo(state=EmploymentState.external, source="none")


@router.get("", response_model=CandidateList)
async def list_candidates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[list[CandidateStatus]] = Query(
        None,
        description=(
            "Filter by `status` — one or more values. Repeat the param for "
            "multi-select (e.g. `?status=active&status=passive`). OR-combined."
        ),
    ),
    location: Optional[str] = None,
    q: Optional[str] = None,
    skills: Optional[list[str]] = Query(
        None,
        description=(
            "Filter by canonical skill names (resolved against the alias taxonomy "
            "on the scoring engine). Multiple values combined by `skill_combine`."
        ),
    ),
    skill_combine: str = Query(
        "and",
        pattern="^(and|or)$",
        description="How to combine multiple `skills` filters — 'and' or 'or'.",
    ),
    remote_policy: Optional[str] = Query(
        None,
        description="Filter by candidate remote preference (remote/hybrid/onsite).",
    ),
    min_salary: Optional[int] = Query(
        None,
        ge=0,
        description="Minimum salary expectation (PLN) — exclusive of nulls.",
    ),
    max_salary: Optional[int] = Query(
        None,
        ge=0,
        description="Maximum salary expectation (PLN) — exclusive of nulls.",
    ),
    include_match_stats: bool = Query(
        False,
        description=(
            "When true, each candidate gets a `match_stats` summary with the number "
            "of open jobs they match (score ≥ threshold) and their top match score. "
            "O(page_size × open_jobs) scoring work — enable lazily on the UI."
        ),
    ),
    match_threshold: float = Query(
        _MATCH_STATS_DEFAULT_THRESHOLD,
        ge=0.0,
        le=100.0,
        description="Minimum total score (0-100) to count an open job as matching.",
    ),
    profile_id: Optional[int] = Query(
        None,
        description="Phase D1 scoring weight profile id. None = auto-resolve by user.",
    ),
    employment: Optional[list[str]] = Query(
        None,
        description=(
            "Derived employment filter — one or more of {'at_client', 'available'}. "
            "Repeat the param for multi-select. 'at_client' = consultant is employed "
            "at one of our clients (active contract OR active current_employment "
            "conflict); 'available' = the inverse. Empty = no filter. Multiple "
            "values OR-combined (effectively shows everyone if both selected)."
        ),
    ),
    availability: Optional[list[AvailabilityStatus]] = Query(
        None,
        description=(
            "Filter by `availability_status` — one or more of "
            "{actively_looking, open_to_offers, not_looking, unknown}. "
            "Repeat the param for multi-select. OR-combined."
        ),
    ),
    added_by_user_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by `created_by` — one or more user ids. "
            "Sentinel `0` matches NULL (pre-backfill / system-imported rows)."
        ),
    ),
    talent_pool_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by talent pool membership — one or more pool ids, OR-combined."
        ),
    ),
    current_company: Optional[list[str]] = Query(
        None,
        description=(
            "LinkedIn-Recruiter style. Match candidates whose CURRENT job "
            "(`experience[0].company`) ILIKE any of the values. OR-combined."
        ),
    ),
    past_company: Optional[list[str]] = Query(
        None,
        description=(
            "LinkedIn-Recruiter style. Match candidates who had any NON-current "
            "experience entry with a company ILIKE any of the values. OR-combined."
        ),
    ),
    current_title: Optional[list[str]] = Query(
        None,
        description=(
            "Match candidates whose CURRENT role (`experience[0].role`) ILIKE "
            "any of the values. OR-combined."
        ),
    ),
    worked_at_client_id: Optional[list[int]] = Query(
        None,
        description=(
            "Candidates who at any point had a contract with, or were flagged "
            "as current_employment at, one of these client ids. OR-combined. "
            "Historical (ignores contract status / conflict active flag)."
        ),
    ),
    recently_changed_jobs: Optional[int] = Query(
        None,
        ge=1,
        le=3,
        description=(
            "Filter candidates whose LinkedIn profile indicated an employer "
            "change in the last N months (1/2/3). Powered by the scheduled "
            "Proxycurl sync — see `linkedin_employment_changed_at`."
        ),
    ),
    open_to: Optional[list[str]] = Query(
        None,
        description=(
            "Filter candidates who declared openness to extra engagement. "
            "Values: one or more of {'side_projects', 'sales_support', "
            "'expert_consult'} — OR-combined (candidate needs AT LEAST ONE "
            "of the selected flags set to True). Repeat the param for "
            "multi-select (e.g. `?open_to=side_projects&open_to=sales_support`)."
        ),
    ),
    q_all: Optional[list[str]] = Query(
        None,
        description=(
            "Advanced search — every phrase must appear in the candidate "
            "(AND). Matches case-insensitive ILIKE across name/email/CV/"
            "ai_summary/competence_category/experience/skills/tags. "
            "Repeat the param per phrase."
        ),
    ),
    q_any: Optional[list[str]] = Query(
        None,
        description=(
            "Advanced search — at least one phrase must appear (OR). "
            "See `q_all` for matched fields."
        ),
    ),
    q_none: Optional[list[str]] = Query(
        None,
        description=(
            "Advanced search — none of these phrases may appear (NOT). "
            "See `q_all` for matched fields."
        ),
    ),
    sort: str = Query(
        "newest",
        pattern="^(newest|oldest|name)$",
        description=(
            "Sort order. 'newest' = created_at DESC; 'oldest' = created_at ASC; "
            "'name' = name ASC, lastname ASC. All include `id` tie-breaker for "
            "100% stable pagination across requests (required for next/prev "
            "candidate navigation in the UI)."
        ),
    ),
):
    query = select(Candidate).options(*_candidate_list_options())
    if status:
        query = query.where(Candidate.status.in_(status))
    if employment:
        invalid = [e for e in employment if e not in {"at_client", "available"}]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid employment values: {invalid}. "
                    "Allowed: 'at_client', 'available'."
                ),
            )
        # Both selected = no-op (covers everyone). Otherwise apply the chosen side.
        emp_set = set(employment)
        if emp_set == {"at_client"}:
            query = query.where(_at_client_predicate())
        elif emp_set == {"available"}:
            query = query.where(not_(_at_client_predicate()))
        # emp_set == {"at_client", "available"} → no filter (all candidates)
    if availability:
        query = query.where(Candidate.availability_status.in_(availability))
    if open_to:
        _OPEN_TO_FIELDS = {
            "side_projects": Candidate.open_to_side_projects,
            "sales_support": Candidate.open_to_sales_support,
            "expert_consult": Candidate.open_to_expert_consult,
        }
        invalid = [v for v in open_to if v not in _OPEN_TO_FIELDS]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid open_to values: {invalid}. "
                    f"Allowed: {sorted(_OPEN_TO_FIELDS)}."
                ),
            )
        clauses = [_OPEN_TO_FIELDS[v].is_(True) for v in set(open_to)]
        query = query.where(or_(*clauses))
    if location:
        query = query.where(Candidate.location.ilike(f"%{location}%"))
    if q:
        q_stripped = q.strip()
        # Phase B2: for longer queries use pg_trgm similarity over name+lastname+email
        # + raw_cv_text; fall back to ilike for 1-2 char queries where trigram
        # similarity is noisy.
        if len(q_stripped) >= 3:
            identity_expr = (
                func.coalesce(Candidate.name, "")
                + " "
                + func.coalesce(Candidate.lastname, "")
                + " "
                + func.coalesce(Candidate.email, "")
            )
            like_pat = f"%{q_stripped}%"
            # `func.similarity(a, q) > 0.2` uses the GIN trigram index on the
            # expression; robust against typos and case mismatches. Also keep
            # raw ilike on raw_cv_text (index-backed via ix_candidates_cv_trgm).
            query = query.where(
                or_(
                    func.similarity(identity_expr, q_stripped) > 0.2,
                    Candidate.raw_cv_text.ilike(like_pat),
                    Candidate.name.ilike(like_pat),
                    Candidate.lastname.ilike(like_pat),
                    Candidate.email.ilike(like_pat),
                )
            )
        else:
            like_pat = f"%{q_stripped}%"
            query = query.where(
                or_(
                    Candidate.name.ilike(like_pat),
                    Candidate.lastname.ilike(like_pat),
                    Candidate.email.ilike(like_pat),
                )
            )
    # Traffit-style advanced search — ALL / ANY / NONE buckets combine with `q`.
    from app.services.advanced_candidate_search import build_advanced_filter

    _advanced = build_advanced_filter(q_all, q_any, q_none)
    if _advanced is not None:
        query = query.where(_advanced)
    # Phase B3: structured filters over JSONB
    if skills:
        # skills is a list of canonical/alias names; normalize through the
        # scoring engine so UI can ship whatever the user typed.
        from app.services.scoring_service import canonical_skill_names

        wanted = [s for s in (canonical_skill_names(skills) or []) if s]
        if wanted:
            # Case-insensitive text LIKE on the JSONB payload — handles both
            # shapes the seed data ships with:
            #   [{"name": "Python"}, ...]             → matches "name": "python"
            #   {"technologies": ["Python", ...]}     → matches "python"
            # Also checks tags + verified_tech for a generous match.
            def _skill_predicate(s: str):
                pat = f"%{s.lower()}%"
                return or_(
                    func.lower(
                        Candidate.skills.cast(__import__("sqlalchemy").Text)
                    ).like(pat),
                    func.lower(
                        Candidate.verified_tech.cast(__import__("sqlalchemy").Text)
                    ).like(pat),
                    func.lower(Candidate.tags.cast(__import__("sqlalchemy").Text)).like(
                        pat
                    ),
                )

            skill_clauses = [_skill_predicate(s) for s in wanted]
            combiner = __import__("sqlalchemy").and_ if skill_combine == "and" else or_
            query = query.where(combiner(*skill_clauses))

    if remote_policy:
        # Stored inside `preferences.remote_modes` JSON array
        query = query.where(
            Candidate.preferences.op("@>")(
                func.jsonb_build_object(
                    "remote_modes", func.jsonb_build_array(remote_policy)
                )
            )
        )

    if min_salary is not None:
        query = query.where(Candidate.salary_expectation >= min_salary)
    if max_salary is not None:
        query = query.where(Candidate.salary_expectation <= max_salary)

    if added_by_user_id:
        # Sentinel 0 = "no created_by on record" (pre-backfill / system import).
        real_ids = [uid for uid in added_by_user_id if uid != 0]
        include_null = 0 in added_by_user_id
        if include_null and real_ids:
            query = query.where(
                or_(Candidate.created_by.is_(None), Candidate.created_by.in_(real_ids))
            )
        elif include_null:
            query = query.where(Candidate.created_by.is_(None))
        elif real_ids:
            query = query.where(Candidate.created_by.in_(real_ids))

    if talent_pool_id:
        pool_exists = (
            select(1)
            .where(
                and_(
                    TalentPoolMembership.candidate_id == Candidate.id,
                    TalentPoolMembership.talent_pool_id.in_(talent_pool_id),
                )
            )
            .exists()
        )
        query = query.where(pool_exists)

    # LinkedIn-Recruiter-style position/company filters (reads Candidate.experience JSONB)
    if current_company:
        query = query.where(_current_company_predicate(current_company))
    if past_company:
        query = query.where(_past_company_predicate(past_company))
    if current_title:
        query = query.where(_current_title_predicate(current_title))
    if worked_at_client_id:
        query = query.where(_worked_at_client_predicate(worked_at_client_id))

    # Phase: LinkedIn sync — filter by detected employer change window.
    # Uses ix_candidates_linkedin_employment_changed_at for fast planner path.
    if recently_changed_jobs in (1, 2, 3):
        cutoff = datetime.now(timezone.utc) - timedelta(days=30 * recently_changed_jobs)
        query = query.where(Candidate.linkedin_employment_changed_at >= cutoff)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    # Stable ORDER BY before pagination — required so next/prev candidate
    # navigation walks the same sequence between requests. id tie-breaker
    # disambiguates rows with identical sort key.
    if sort == "oldest":
        query = query.order_by(Candidate.created_at.asc(), Candidate.id.asc())
    elif sort == "name":
        query = query.order_by(
            Candidate.name.asc(), Candidate.lastname.asc(), Candidate.id.asc()
        )
    else:  # "newest" (default)
        query = query.order_by(Candidate.created_at.desc(), Candidate.id.desc())

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    # Phase D1: resolve which weight profile to use for the match-stats column.
    profile: WeightProfile = DEFAULT_PROFILE
    if include_match_stats and items:
        if profile_id is not None:
            from app.models.scoring_weight_profile import ScoringWeightProfile

            row = await db.scalar(
                select(ScoringWeightProfile).where(
                    ScoringWeightProfile.id == profile_id
                )
            )
            if row:
                profile = WeightProfile.from_record(row)
        else:
            profile = await resolve_active_profile(db, user_id=current_user.id)

    match_stats_by_candidate: dict[int, MatchStats] = {}
    if include_match_stats and items:
        open_jobs_stmt = (
            select(Job)
            .where(Job.status == JobStatus.published)
            .limit(_MATCH_STATS_JOB_CAP)
        )
        open_jobs = list((await db.execute(open_jobs_stmt)).scalars().all())
        total_open = len(open_jobs)
        if total_open:
            for cand in items:
                breakdowns = await rank_jobs_for_candidate(
                    cand, open_jobs, db, profile=profile
                )
                stats = summarize_match_stats(
                    breakdowns, total_open=total_open, min_score=match_threshold
                )
                match_stats_by_candidate[cand.id] = MatchStats(**stats)
        else:
            zero = MatchStats(open_count=0, total_open=0, top_score=0.0)
            for cand in items:
                match_stats_by_candidate[cand.id] = zero

    response_items: list[CandidateResponse] = []
    for cand in items:
        payload = _candidate_to_response(cand)
        # Strip eagerly-loaded snapshots from the list response — they are
        # only surfaced on the detail endpoint (trimmed to 5 there).
        payload = payload.model_copy(update={"linkedin_snapshots": None})
        stats = match_stats_by_candidate.get(cand.id)
        if stats is not None:
            payload = payload.model_copy(update={"match_stats": stats})
        response_items.append(payload)

    return CandidateList(
        items=response_items, total=total, page=page, page_size=page_size
    )


# ── Autocomplete: companies from candidate CV experience ────────────────────


class CompanySuggestion(BaseModel):
    """A company name extracted from any candidate's parsed CV experience."""

    name: str
    count: int


@router.get("/companies/suggest", response_model=list[CompanySuggestion])
async def suggest_companies(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(
        "",
        max_length=100,
        description="Substring to match (ILIKE). Empty = top-N overall.",
    ),
    limit: int = Query(20, ge=1, le=50),
):
    """Return top-N companies aggregated from all candidates' `experience[].company`.

    Used by the frontend CompanyAutocomplete to power the current/past company
    filters. Groups by lowercased name — acceptable MVP trade-off (collapses
    "Google" / "google" to one suggestion).
    """
    pat = f"%{q.strip().lower()}%" if q.strip() else ""
    sql = text(
        "SELECT lower(elem->>'company') AS company, COUNT(DISTINCT c.id) AS n "
        "FROM candidates c, "
        "jsonb_array_elements("
        "CASE WHEN jsonb_typeof(c.experience) = 'array' "
        "THEN c.experience ELSE '[]'::jsonb END"
        ") AS elem "
        "WHERE elem ? 'company' "
        "AND elem->>'company' IS NOT NULL "
        "AND elem->>'company' <> '' "
        "AND (:pat = '' OR lower(elem->>'company') LIKE :pat) "
        "GROUP BY lower(elem->>'company') "
        "ORDER BY n DESC, company ASC "
        "LIMIT :lim"
    )
    result = await db.execute(sql, {"pat": pat, "lim": limit})
    return [CompanySuggestion(name=row[0], count=int(row[1])) for row in result]


# ── Bulk export (Phase 7b.4) ────────────────────────────────────────────────


_EXPORT_COLUMNS = [
    "id",
    "name",
    "lastname",
    "email",
    "phone",
    "location",
    "competence_category",
    "years_it_experience",
    "skills",
    "tags",
    "status",
    "source",
    "salary_expectation",
    "salary_currency",
    "availability_date",
    "champion",
    "created_at",
]


def _skill_names_flat(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, list):
        out: list[str] = []
        for it in raw:
            if isinstance(it, dict):
                v = it.get("name")
                if v:
                    out.append(str(v))
            elif isinstance(it, str):
                out.append(it)
        return ", ".join(out)
    return str(raw)


def _row_for_export(c: Candidate) -> list:
    return [
        c.id,
        c.name or "",
        c.lastname or "",
        c.email or "",
        c.phone or "",
        c.location or "",
        c.competence_category or "",
        c.years_it_experience if c.years_it_experience is not None else "",
        _skill_names_flat(c.skills),
        _skill_names_flat(c.tags),
        c.status.value if c.status else "",
        c.source or "",
        c.salary_expectation if c.salary_expectation is not None else "",
        c.salary_currency or "",
        c.availability_date.isoformat() if c.availability_date else "",
        "true" if c.champion else "false",
        c.created_at.isoformat() if c.created_at else "",
    ]


@router.get("/export")
async def export_candidates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    format: str = Query("csv", regex="^(csv|xlsx)$"),
    status_: Optional[CandidateStatus] = Query(None, alias="status"),
    q: Optional[str] = None,
    location: Optional[str] = None,
    limit: int = Query(10000, ge=1, le=50000),
):
    """Stream candidates as CSV or Excel file respecting the same filters as list."""
    query = select(Candidate)
    if status_:
        query = query.where(Candidate.status == status_)
    if location:
        query = query.where(Candidate.location.ilike(f"%{location}%"))
    if q:
        query = query.where(
            or_(
                Candidate.name.ilike(f"%{q}%"),
                Candidate.lastname.ilike(f"%{q}%"),
                Candidate.email.ilike(f"%{q}%"),
            )
        )
    query = query.order_by(Candidate.id).limit(limit)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if format == "xlsx":
        from io import BytesIO
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Candidates"
        ws.append(_EXPORT_COLUMNS)
        for c in rows:
            ws.append(_row_for_export(c))

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"candidates_{ts}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # CSV (default)
    import csv
    from io import StringIO

    buf = StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(_EXPORT_COLUMNS)
    for c in rows:
        writer.writerow(_row_for_export(c))
    buf.seek(0)
    filename = f"candidates_{ts}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", response_model=CandidateResponse, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    data: CandidateCreate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    candidate = Candidate(**data.model_dump())
    candidate.created_by = current_user.id
    db.add(candidate)
    await db.flush()
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate.id,
        action="created",
        user_id=current_user.id,
        details={"name": f"{candidate.name} {candidate.lastname}"},
    )
    db.add(activity)
    user_activity = UserActivity(
        user_id=current_user.id,
        action_type=UserActionType.candidate_added,
        entity_type="candidate",
        entity_id=candidate.id,
        details={
            "name": f"{candidate.name} {candidate.lastname}",
            "source": candidate.source,
        },
    )
    db.add(user_activity)
    await db.flush()

    # Notify all managers/admins about new candidate (real-time)
    managers_result = await db.execute(
        select(User).where(User.is_active, User.role.in_(["admin", "manager"]))
    )
    managers = managers_result.scalars().all()
    notif_ids = []
    for mgr in managers:
        if mgr.id != current_user.id:
            notif = Notification(
                user_id=mgr.id,
                title="Nowy kandydat dodany",
                message=f"Kandydat {candidate.name} {candidate.lastname} został dodany do systemu.",
                link=f"/candidates/{candidate.id}",
                notification_type=NotificationType.candidate_added,
            )
            db.add(notif)
            notif_ids.append((mgr.id, notif))
    await db.flush()
    for mgr_id, notif in notif_ids:
        await ws_manager.notify_user(
            mgr_id,
            {
                "type": "notification",
                "data": {
                    "id": notif.id,
                    "title": notif.title,
                    "message": notif.message,
                    "link": notif.link,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )

    await db.refresh(candidate)
    # Reload with eager-loaded contracts/conflicts so _derive_employment has data.
    reloaded = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate.id)
    )
    full = reloaded.scalar_one()
    return _candidate_to_response(full)


async def _resolve_invite_source(
    candidate_id: int, db: AsyncSession
) -> Optional[InviteSourceBrief]:
    """Resolve the most recent `applied_via_invite` event into badge data.

    Returns None when the candidate never applied via an invite link (the
    common case). Picks the latest Activity so a re-apply shows the current
    recruiter/channel, and surfaces `previous_created_by_name` when the
    apply transferred ownership (see #4).
    """
    stmt = (
        select(Activity)
        .where(
            Activity.entity_type == "candidate",
            Activity.entity_id == candidate_id,
            Activity.action == "applied_via_invite",
        )
        .order_by(Activity.created_at.desc())
        .limit(1)
    )
    activity = (await db.execute(stmt)).scalar_one_or_none()
    if activity is None:
        return None

    details = activity.details or {}
    token_prefix = details.get("invite_token")  # first 8 chars only

    # Best-effort label lookup from the invite link record. Prefix LIKE
    # query; 48-bit entropy makes collisions a non-issue in practice.
    label: Optional[str] = None
    if isinstance(token_prefix, str) and token_prefix:
        link = await db.scalar(
            select(CandidateInviteLink).where(
                CandidateInviteLink.token.like(f"{token_prefix}%")
            )
        )
        if link is not None:
            label = link.label

    # Recruiter names — activity.user_id is the new owner; previous_created_by
    # (if any) is the recruiter replaced by this apply.
    created_by_name = "—"
    if activity.user_id is not None:
        creator = await db.scalar(select(User).where(User.id == activity.user_id))
        if creator is not None:
            created_by_name = creator.name

    previous_created_by_name: Optional[str] = None
    prev_id = details.get("previous_created_by")
    if isinstance(prev_id, int):
        prev_user = await db.scalar(select(User).where(User.id == prev_id))
        if prev_user is not None:
            previous_created_by_name = prev_user.name

    return InviteSourceBrief(
        label=label,
        created_by_name=created_by_name,
        applied_at=activity.created_at,
        previous_created_by_name=previous_created_by_name,
    )


@router.get("/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    payload = _candidate_to_response(candidate)
    invite_source = await _resolve_invite_source(candidate_id, db)
    # Snapshots are eager-loaded by _candidate_list_options (ordered desc by
    # fetched_at); trim to the 5 most recent for the detail payload.
    snapshots = [
        LinkedinSnapshotSummary.model_validate(s)
        for s in (candidate.linkedin_snapshots or [])[:5]
    ]
    return payload.model_copy(
        update={"invite_source": invite_source, "linkedin_snapshots": snapshots}
    )


@router.get("/{candidate_id}/timeline")
async def get_candidate_timeline(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Chronological feed of all activities for this candidate:
    notes, stage changes, calls, system events.
    GET /api/candidates/{id}/timeline
    """
    # Check candidate exists
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    timeline = []

    # Notes — JOIN User for author_name (Faza A: po imporcie 131 Traffit
    # userów chcemy wyświetlać "kto" dodał notatkę. NotatkiTab w UI używa
    # `author_name` z tego pola).
    notes_result = await db.execute(
        select(Note, User.name.label("author_name"), User.email.label("author_email"))
        .outerjoin(User, Note.author_id == User.id)
        .where(Note.candidate_id == candidate_id)
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    for note, author_name, author_email in notes_result.all():
        timeline.append(
            {
                "type": "note",
                "id": note.id,
                "timestamp": note.created_at.isoformat() if note.created_at else None,
                "note_type": note.note_type.value if note.note_type else None,
                "content": note.content,
                "author_id": note.author_id,
                "author_name": author_name,
                "author_email": author_email,
            }
        )

    # Stage changes
    stages_result = await db.execute(
        select(CandidateStage, Job.title)
        .join(Job, CandidateStage.job_id == Job.id)
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.moved_at.desc())
        .limit(limit)
    )
    for stage, job_title in stages_result.all():
        timeline.append(
            {
                "type": "stage_change",
                "id": stage.id,
                "timestamp": stage.moved_at.isoformat() if stage.moved_at else None,
                "stage": stage.stage.value,
                "job_id": stage.job_id,
                "job_title": job_title,
                "moved_by": stage.moved_by,
                "rating": stage.rating,
                "notes": stage.notes,
            }
        )

    # Activities (system events)
    activities_result = await db.execute(
        select(Activity)
        .where(Activity.entity_type == "candidate", Activity.entity_id == candidate_id)
        .order_by(Activity.created_at.desc())
        .limit(limit)
    )
    activities = list(activities_result.scalars().all())

    # Resolve user names for `applied_via_invite` events so the UI can
    # render "Przejęto opiekę: X → Y" without a second round-trip. Pulls
    # both the activity author and any `previous_created_by` in one query.
    invite_user_ids: set[int] = set()
    for act in activities:
        if act.action == "applied_via_invite":
            if act.user_id is not None:
                invite_user_ids.add(act.user_id)
            prev = (act.details or {}).get("previous_created_by")
            if isinstance(prev, int):
                invite_user_ids.add(prev)
    user_names: dict[int, str] = {}
    if invite_user_ids:
        names_result = await db.execute(
            select(User.id, User.name).where(User.id.in_(invite_user_ids))
        )
        user_names = {uid: name for uid, name in names_result.all()}

    for act in activities:
        item: dict = {
            "type": "activity",
            "id": act.id,
            "timestamp": act.created_at.isoformat() if act.created_at else None,
            "action": act.action,
            "user_id": act.user_id,
            "details": act.details,
        }
        if act.action == "applied_via_invite":
            if act.user_id is not None and act.user_id in user_names:
                item["user_name"] = user_names[act.user_id]
            prev = (act.details or {}).get("previous_created_by")
            if isinstance(prev, int) and prev in user_names:
                item["previous_created_by_name"] = user_names[prev]
        timeline.append(item)

    # User activities
    user_acts_result = await db.execute(
        select(UserActivity)
        .where(
            UserActivity.entity_type == "candidate",
            UserActivity.entity_id == candidate_id,
        )
        .order_by(UserActivity.created_at.desc())
        .limit(limit)
    )
    for ua in user_acts_result.scalars().all():
        timeline.append(
            {
                "type": "user_activity",
                "id": ua.id,
                "timestamp": ua.created_at.isoformat() if ua.created_at else None,
                "action_type": ua.action_type.value,
                "user_id": ua.user_id,
                "details": ua.details,
            }
        )

    # Sort chronologically (newest first)
    timeline.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "candidate_id": candidate_id,
        "candidate_name": f"{candidate.name} {candidate.lastname}",
        "count": len(timeline),
        "timeline": timeline[:limit],
    }


@router.get("/{candidate_id}/history")
async def get_candidate_history(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Recruitment history — which jobs this candidate was in and what stages reached.
    GET /api/candidates/{id}/history
    """
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    stages_result = await db.execute(
        select(CandidateStage, Job.title, Job.status.label("job_status"))
        .join(Job, CandidateStage.job_id == Job.id)
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.moved_at.desc())
    )

    # Group by job
    jobs_map: dict = {}
    for stage, job_title, job_status in stages_result.all():
        job_id = stage.job_id
        if job_id not in jobs_map:
            jobs_map[job_id] = {
                "job_id": job_id,
                "job_title": job_title,
                "job_status": job_status,
                "stages": [],
                "latest_stage": None,
                # latest_stage_id wskazuje na najnowszy CandidateStage row
                # (potrzebne dla CV-per-rekrutacja: api wybiera stage_id by
                # wczytać snapshot oryginalnego CV i brandowane CV draft).
                "latest_stage_id": None,
                "first_seen": None,
                "last_seen": None,
            }
        entry = jobs_map[job_id]
        entry["stages"].append(
            {
                "stage_id": stage.id,
                "stage": stage.stage.value,
                "moved_at": stage.moved_at.isoformat() if stage.moved_at else None,
                "rating": stage.rating,
                "notes": stage.notes,
            }
        )
        # Track dates
        moved_at = stage.moved_at.isoformat() if stage.moved_at else None
        if moved_at:
            if not entry["first_seen"] or moved_at < entry["first_seen"]:
                entry["first_seen"] = moved_at
            if not entry["last_seen"] or moved_at > entry["last_seen"]:
                entry["last_seen"] = moved_at
                entry["latest_stage"] = stage.stage.value
                entry["latest_stage_id"] = stage.id

    # Contracts
    from app.models.contract import Contract
    from app.models.client import Client

    contracts_result = await db.execute(
        select(Contract, Client.name.label("client_name"))
        .join(Client, Contract.client_id == Client.id)
        .where(Contract.candidate_id == candidate_id)
        .order_by(Contract.start_date.desc())
    )
    contracts_history = []
    for contract, client_name in contracts_result.all():
        contracts_history.append(
            {
                "contract_id": contract.id,
                "client_name": client_name,
                "start_date": contract.start_date.isoformat()
                if contract.start_date
                else None,
                "end_date": contract.end_date.isoformat()
                if contract.end_date
                else None,
                "status": contract.status.value,
                "rate_candidate": contract.rate_candidate,
                "rate_client": contract.rate_client,
                "currency": contract.currency,
            }
        )

    # Risk summary (Phase 17 — read-only compute, migracja 0068)
    from app.services.candidate_risk import compute_summary as _risk_summary

    try:
        s = await _risk_summary(db, candidate_id)
        risk_summary = {
            "level": s["level"].value if hasattr(s["level"], "value") else s["level"],
            "score": s["score"],
            "breakdown": {
                "early": s["early_count"],
                "interview": s["interview_count"],
                "post_accept": s["post_accept_count"],
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("risk fetch failed for candidate=%s: %s", candidate_id, exc)
        risk_summary = None

    return {
        "candidate_id": candidate_id,
        "candidate_name": f"{candidate.name} {candidate.lastname}",
        "jobs": list(jobs_map.values()),
        "contracts": contracts_history,
        "risk_summary": risk_summary,
    }


@router.get(
    "/{candidate_id}/documents",
    response_model=list[CandidateDocumentOut],
)
async def list_candidate_documents(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """List wszystkich plików kandydata (multi-file CV, Faza A migracji
    Traffit). Primary plik jest pierwszy w response (sortowanie po
    `is_primary DESC`, `uploaded_at DESC`).

    Nie zwraca `file_content` — pobierz binary przez
    `/api/candidates/{candidate_id}/documents/{doc_id}/content`.
    """
    cand = (
        await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    ).scalar_one_or_none()
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    result = await db.execute(
        select(CandidateDocument)
        .where(CandidateDocument.candidate_id == candidate_id)
        .order_by(
            CandidateDocument.is_primary.desc(),
            CandidateDocument.uploaded_at.desc().nulls_last(),
            CandidateDocument.created_at.desc(),
        )
    )
    return list(result.scalars().all())


@router.get("/{candidate_id}/documents/{doc_id}/content")
async def download_candidate_document(
    candidate_id: int,
    doc_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz binary content pliku — StreamingResponse z proper
    Content-Type i Content-Disposition: attachment.
    """
    result = await db.execute(
        select(CandidateDocument).where(
            CandidateDocument.id == doc_id,
            CandidateDocument.candidate_id == candidate_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    filename = doc.filename or f"document-{doc.id}"

    # Po migracji do Hetzner Object Storage (audit-2026-05-07 Faza 3): jeśli
    # `storage_key` jest set, klient ściąga bezpośrednio przez presigned URL
    # — backend nie pośredniczy w bytestream.
    if doc.storage_key:
        from fastapi.responses import RedirectResponse

        from app.services.object_storage import (
            get_presigned_download_url,
            is_available,
        )

        if is_available():
            url = get_presigned_download_url(doc.storage_key, filename=filename)
            return RedirectResponse(url, status_code=302)
        # Storage env nie skonfigurowane — fallback do BYTEA jeśli jeszcze jest.

    # Legacy path: stream from postgres BYTEA. Po --finalize-delete-bytea
    # ta gałąź zwróci 404 dla zmigrowanych rekordów (file_content = NULL),
    # ale wtedy storage_key jest set i pierwsza gałąź obsługuje request.
    await db.refresh(doc, attribute_names=["file_content"])
    if not doc.file_content:
        raise HTTPException(status_code=404, detail="Document content not available")

    import io

    media_type = doc.content_type or "application/octet-stream"
    return StreamingResponse(
        io.BytesIO(doc.file_content),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(doc.file_content)),
        },
    )


@router.get("/{candidate_id}/risk")
async def get_candidate_risk(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Risk profile dla kandydata (Phase 17 — read-only, migracja 0068).

    Read-only compute — nie pisze do DB. Bezpieczne dla GET requestu.
    Dla nowych kandydatów bez historii / przy błędach DB — synth low/0
    (`profile_exists=true`, nigdy 404, nigdy 5xx).
    """
    from app.services.candidate_risk import compute_summary as _risk_summary

    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    s = await _risk_summary(db, candidate_id)
    return {
        "candidate_id": candidate_id,
        "level": s["level"].value if hasattr(s["level"], "value") else s["level"],
        "score": s["score"],
        "breakdown": {
            "early": s["early_count"],
            "interview": s["interview_count"],
            "post_accept": s["post_accept_count"],
        },
        "last_updated_at": s["computed_at"].isoformat() if s["computed_at"] else None,
        "recent_events": s["recent_events"],
        "profile_exists": True,
    }


# Fields that change the scoring inputs — mutating them invalidates cache entries.
_MATCH_CACHE_INVALIDATING_FIELDS = frozenset(
    {
        "skills",
        "verified_tech",
        "tags",
        "salary_expectation",
        "availability_date",
        "preferences",
        "location",
        "status",
    }
)


@router.patch("/{candidate_id}", response_model=CandidateResponse)
async def update_candidate(
    candidate_id: int,
    data: CandidateUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    updates = data.model_dump(exclude_unset=True)

    # Phase D4: flag manual edits to `experience` so a subsequent CV upload
    # does not silently overwrite recruiter-curated data with AI extraction.
    if "experience" in updates:
        current_extracted = dict(candidate.cv_extracted_data or {})
        current_extracted["_manual_override_experience"] = True
        updates["cv_extracted_data"] = current_extracted

    for field, value in updates.items():
        setattr(candidate, field, value)
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate.id,
        action="updated",
        user_id=current_user.id,
        details=updates,
    )
    db.add(activity)

    # Phase C1: invalidate cached (candidate, *) scores if matching-critical
    # fields changed. Cheap single UPDATE — much faster than refetching scores.
    if _MATCH_CACHE_INVALIDATING_FIELDS & set(updates.keys()):
        from app.services.match_score_cache import mark_stale_for_candidate

        await mark_stale_for_candidate(db, candidate.id)

    # Async SQLAlchemy doesn't autoflush before `refresh`, so setattr changes
    # could get overwritten by the in-memory state read. Flush first, then
    # reload with eager-loaded relations so `_derive_employment` sees current
    # contracts/conflicts.
    await db.flush()
    reloaded = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate.id)
    )
    full = reloaded.scalar_one()
    return _candidate_to_response(full)


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    candidate_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate_id,
        action="deleted",
        user_id=current_user.id,
    )
    db.add(activity)
    await db.delete(candidate)


_CV_CONTACT_FIELDS = ("first_name", "last_name", "email", "phone", "city")

# Placeholder values written by `/from-cv` when the LLM returns no name.
# `_apply_cv_contact_fields` treats these as "empty" so the next upload can
# override them even though the column is NOT NULL.
_CV_PLACEHOLDER_NAME = "Nieznane"


def _apply_cv_contact_fields(
    candidate: Candidate, parsed: dict, existing_extracted: dict
) -> None:
    """Backfill contact fields from a parse_cv() result.

    Each field is written only when:
      - the parsed value is truthy, AND
      - the candidate has no value yet (empty string / None / placeholder), AND
      - no `_manual_override_<field>` flag is set in `cv_extracted_data`.

    The location mapping writes to BOTH `candidate.location` (legacy
    free-text) and `candidate.city` (structured column) to keep the two
    columns aligned for existing filters and heat-maps.
    """

    def _blank(value) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            stripped = value.strip()
            return not stripped or stripped == _CV_PLACEHOLDER_NAME
        return False

    def _locked(field: str) -> bool:
        return bool(existing_extracted.get(f"_manual_override_{field}"))

    first_name = parsed.get("first_name")
    if first_name and _blank(candidate.name) and not _locked("first_name"):
        candidate.name = str(first_name).strip()[:100]

    last_name = parsed.get("last_name")
    if last_name and _blank(candidate.lastname) and not _locked("last_name"):
        candidate.lastname = str(last_name).strip()[:100]

    email = parsed.get("email")
    if email and _blank(candidate.email) and not _locked("email"):
        candidate.email = str(email).strip().lower()[:255]

    phone = parsed.get("phone")
    if phone and _blank(candidate.phone) and not _locked("phone"):
        candidate.phone = str(phone).strip()[:30]

    city = parsed.get("city")
    if city and not _locked("city"):
        city_value = str(city).strip()[:120]
        if _blank(candidate.city):
            candidate.city = city_value
        if _blank(candidate.location):
            # Legacy free-text column mirrors the structured city for filters
            # that still read from `location`.
            candidate.location = city_value[:255]


def _apply_cv_enrichment(candidate: Candidate, parsed: dict) -> int:
    """Pure function: mutate `candidate` fields from a `parse_cv()` result.

    Returns the number of companies that were written into `experience`
    (zero when the recruiter has manually curated it, or the AI returned no
    companies). This function is the unit-testable seam for Phase D4 — it
    has zero DB or async concerns.

    Contract:
      * Never clobbers recruiter-curated data (`_manual_override_experience`
        for employment; `_manual_override_<field>` for scalar contact fields).
      * Never downgrades a rich `experience` record (with roles) to a flat
        company-name list — bulk imports from Traffit are protected.
      * Preserves the manual-override flag across writes so the guard
        survives future uploads.
      * Contact fields (email/phone/first_name/last_name/city) are only
        backfilled when the candidate row has them empty — the recruiter's
        typed values always win.
    """
    existing_extracted = dict(candidate.cv_extracted_data or {})
    manual_override = bool(existing_extracted.get("_manual_override_experience", False))

    if parsed.get("years_it_experience") is not None:
        candidate.years_it_experience = parsed["years_it_experience"]
    if parsed.get("skills"):
        candidate.skills = parsed["skills"]
    if parsed.get("education"):
        candidate.education = parsed["education"]
    if parsed.get("languages"):
        candidate.languages = parsed["languages"]
    if parsed.get("career_summary"):
        candidate.ai_summary = parsed["career_summary"]
    # Only backfill LinkedIn URL when the recruiter hasn't set one manually —
    # we never want to clobber a curated value with a noisy regex hit.
    if parsed.get("linkedin_url") and not candidate.linkedin:
        from app.services.proxycurl import normalize_linkedin_url

        canonical = normalize_linkedin_url(parsed["linkedin_url"])
        if canonical:
            candidate.linkedin = canonical

    # v4: contact fields — only backfill empty slots, honour manual overrides.
    _apply_cv_contact_fields(candidate, parsed, existing_extracted)

    next_extracted = dict(parsed)
    if manual_override:
        next_extracted["_manual_override_experience"] = True
    # Preserve any per-field manual overrides already recorded.
    for field in _CV_CONTACT_FIELDS:
        key = f"_manual_override_{field}"
        if existing_extracted.get(key):
            next_extracted[key] = True
    candidate.cv_extracted_data = next_extracted

    companies = parsed.get("companies") or []
    has_rich_experience = bool(candidate.experience) and any(
        isinstance(e, dict) and e.get("role") for e in (candidate.experience or [])
    )
    written = 0
    if companies and not manual_override and not has_rich_experience:
        candidate.experience = [
            {
                "company": name,
                "role": None,
                "start": None,
                "end": None,
                "desc": None,
            }
            for name in companies
        ]
        written = len(companies)

    candidate.cv_parsed_at = datetime.now(timezone.utc)
    return written


async def _auto_assign_primary_cc(candidate: Candidate, db: AsyncSession) -> None:
    """Run CC classifier and persist the top hit as the candidate's primary CC.

    Mirrors the pattern used in `public_share.py` — only writes when the
    candidate has no CC yet (recruiter-curated value wins). Score ≥ 0.30 is
    required so very weak signals don't pollute the profile. Failures are
    logged but never surface to the caller: CC is enrichment, not required
    for the candidate record.
    """
    try:
        from app.services.cc_classifier import classify_candidate_to_cc

        scores = await classify_candidate_to_cc(candidate, db)
        if not scores:
            return
        top = scores[0]
        if top.score < 0.30:
            return
        if candidate.competence_category and candidate.competence_category_id:
            # Already curated — leave it alone.
            return
        candidate.competence_category = top.slug
        candidate.competence_category_id = top.cc_id
        logger.info(
            "[cv_cc] auto-assigned CC candidate=%s slug=%s score=%.3f",
            candidate.id,
            top.slug,
            top.score,
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[cv_cc] classify failed candidate=%s: %s", candidate.id, e)


async def _enrich_candidate_cv_task(candidate_id: int) -> None:
    """Background task: parse `raw_cv_text` and fan out to candidate fields.

    Runs with a fresh DB session because FastAPI's per-request session is
    closed once the response is returned. Never raises — every failure is
    logged and the upload response stays successful.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.cv_parser import parse_cv
    from app.services.match_score_cache import mark_stale_for_candidate

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Candidate).where(Candidate.id == candidate_id)
            )
            candidate = result.scalar_one_or_none()
            if not candidate or not candidate.raw_cv_text:
                return

            parsed = await parse_cv(candidate.raw_cv_text)
            written = _apply_cv_enrichment(candidate, parsed)
            await db.commit()

            # v4: CC auto-classification after enrichment writes skills/summary.
            # Needs a fresh read so the classifier sees the committed state.
            refreshed = await db.scalar(
                select(Candidate).where(Candidate.id == candidate_id)
            )
            if refreshed is not None:
                await _auto_assign_primary_cc(refreshed, db)
                await db.commit()

            await mark_stale_for_candidate(db, candidate_id)
            await db.commit()

            logger.info(
                "[cv_enrich] source=%s candidate=%s companies_written=%d",
                parsed.get("_source"),
                candidate_id,
                written,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(f"[cv_enrich] failed for candidate {candidate_id}: {e}")
            await db.rollback()


@router.post(
    "/from-cv",
    response_model=CandidateFromCVResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "A candidate that closely matches the parsed CV "
            "already exists (by email, phone, LinkedIn, or name). The response "
            "body carries `existing_candidate_id` + `matches` so the UI can "
            "offer 'open existing' / 'save anyway' actions.",
        }
    },
)
async def create_candidate_from_cv(
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    force: bool = Query(
        default=False,
        description="When true, bypass dedup check and create the candidate "
        "even if a close match exists. The duplicates array on the response "
        "is still populated for audit.",
    ),
):
    """One-shot onboarding: PDF/DOCX CV in → new Candidate out.

    Flow:
      1. Save upload to disk + extract raw text (PDF / DOCX / TXT).
      2. Run `parse_cv()` to pull contact fields, skills, education, etc.
      3. Scan for duplicates via `find_candidate_duplicates` — return 409
         with `existing_candidate_id` unless `?force=true`.
      4. Insert a Candidate, apply enrichment (contact fields, summary,
         experience), and auto-assign a primary Competence Category.
      5. Kick off embedding + match-cache invalidation in the background.

    `name` / `lastname` default to the placeholder "Nieznane" when the LLM
    could not extract them — they're NOT NULL columns, and the frontend flags
    them as low confidence so the recruiter completes them before saving.
    """
    import asyncio

    from app.services import cv_text_extractor
    from app.services.cv_parser import parse_cv

    # 1 — persist the upload and extract text
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    safe_name = (file.filename or "upload.pdf").replace("/", "_")
    # Temporary path — we rename once we know the candidate id.
    tmp_path = os.path.join(settings.UPLOAD_DIR, f"from_cv_tmp_{safe_name}")
    async with aiofiles.open(tmp_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    raw_text: Optional[str] = None
    try:
        raw_text = await asyncio.to_thread(
            cv_text_extractor.extract_text, tmp_path, file.filename or ""
        )
    except cv_text_extractor.UnsupportedCvFormat as e:
        os.remove(tmp_path)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported CV format: {e}",
        ) from e
    except Exception as e:
        logger.warning("[from-cv] text extraction failed: %s", e)

    if not raw_text or not raw_text.strip():
        os.remove(tmp_path)
        raise HTTPException(
            status_code=400,
            detail="Could not extract any text from the uploaded CV file.",
        )

    # 2 — parse structured facts
    parsed = await parse_cv(raw_text)

    # 3 — dedup scan
    dup_rows = await find_candidate_duplicates(
        db,
        email=parsed.get("email"),
        phone=parsed.get("phone"),
        linkedin=parsed.get("linkedin_url"),
        name=parsed.get("first_name"),
        lastname=parsed.get("last_name"),
    )
    duplicates = [
        CandidateFromCVDuplicate(
            candidate_id=row["candidate_id"],
            name=row.get("name"),
            lastname=row.get("lastname"),
            email=row.get("email"),
            match_score=float(row.get("match_score", 0.0)),
            match_reasons=list(row.get("match_reasons") or []),
        )
        for row in dup_rows
    ]
    if duplicates and not force:
        os.remove(tmp_path)
        top = duplicates[0]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": "Kandydat wygląda na duplikat istniejącego rekordu.",
                "existing_candidate_id": top.candidate_id,
                "matches": [m.model_dump() for m in duplicates],
            },
        )

    # 4 — insert and enrich
    first_name = (parsed.get("first_name") or "").strip() or _CV_PLACEHOLDER_NAME
    last_name = (parsed.get("last_name") or "").strip() or _CV_PLACEHOLDER_NAME
    candidate = Candidate(
        name=first_name[:100],
        lastname=last_name[:100],
        raw_cv_text=raw_text,
        cv_filename=file.filename,
        source="cv_upload",
        created_by=current_user.id,
    )
    db.add(candidate)
    await db.flush()  # allocate id so we can rename the file

    # Rename tmp upload to the permanent, candidate-scoped name.
    final_path = os.path.join(
        settings.UPLOAD_DIR, f"candidate_{candidate.id}_{safe_name}"
    )
    try:
        os.replace(tmp_path, final_path)
    except OSError as e:
        logger.warning("[from-cv] rename failed: %s", e)
    candidate.cv_filename = safe_name

    _apply_cv_enrichment(candidate, parsed)

    activity = Activity(
        entity_type="candidate",
        entity_id=candidate.id,
        action="created_from_cv",
        user_id=current_user.id,
        details={
            "filename": file.filename,
            "source": parsed.get("_source"),
        },
    )
    db.add(activity)
    db.add(
        UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.candidate_added,
            entity_type="candidate",
            entity_id=candidate.id,
            details={
                "filename": file.filename,
                "source": "from_cv",
            },
        )
    )
    await db.flush()

    # 5 — best-effort enrichment: embedding + CC classification.
    # Synchronous because the endpoint should return a fully-populated
    # candidate for the preview screen.
    try:
        from app.services.embedding_service import embed_candidate

        await embed_candidate(candidate.id, db)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[from-cv] embedding failed id=%s: %s", candidate.id, e)

    await _auto_assign_primary_cc(candidate, db)

    await db.commit()

    reloaded = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate.id)
    )
    full = reloaded.scalar_one()

    confidence = dict(parsed.get("_confidence") or {})
    return CandidateFromCVResponse(
        candidate=_candidate_to_response(full),
        confidence=confidence,
        duplicates=duplicates,
        source=parsed.get("_source"),
    )


@router.post("/{candidate_id}/cv", response_model=CandidateResponse)
async def upload_cv(
    candidate_id: int,
    current_user: RecruiterPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """Upload CV file for a candidate.

    Saves the file, extracts text (PDF/DOCX/TXT) into `raw_cv_text`, and
    schedules an async enrichment task that populates AI summary, companies
    and skill facts in the background. Response returns as soon as the file
    is on disk — callers don't block on the LLM.
    """
    import asyncio

    from app.services import cv_text_extractor

    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(
        settings.UPLOAD_DIR, f"candidate_{candidate_id}_{file.filename}"
    )
    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # Phase D4: extract text from PDF/DOCX/TXT so the enrichment task has
    # something to work with. Heavy libraries run in a thread to keep the
    # event loop responsive.
    try:
        raw_text = await asyncio.to_thread(
            cv_text_extractor.extract_text, file_path, file.filename or ""
        )
        if raw_text:
            candidate.raw_cv_text = raw_text
    except cv_text_extractor.UnsupportedCvFormat as e:
        logger.info(f"[CV upload] unsupported format for {candidate_id}: {e}")
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            f"[CV upload] text extraction failed for candidate {candidate_id}: {e}"
        )

    candidate.cv_filename = file.filename
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate_id,
        action="cv_uploaded",
        user_id=current_user.id,
        details={"filename": file.filename},
    )
    db.add(activity)
    user_activity = UserActivity(
        user_id=current_user.id,
        action_type=UserActionType.cv_uploaded,
        entity_type="candidate",
        entity_id=candidate_id,
        details={"filename": file.filename},
    )
    db.add(user_activity)
    await db.commit()
    await db.refresh(candidate)

    # Phase 1: auto-embed candidate after CV upload.
    # Non-blocking — CV is already saved; embedding failures are logged but not raised.
    try:
        from app.services.embedding_service import embed_candidate

        await embed_candidate(candidate_id, db)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            f"[CV upload] embedding failed for candidate {candidate_id}: {e}"
        )

    # Phase D4: schedule AI enrichment off the request path. Task runs in a
    # fresh DB session so it survives the response lifecycle.
    if candidate.raw_cv_text:
        background_tasks.add_task(_enrich_candidate_cv_task, candidate_id)

    # Re-fetch with eager-loaded relations so CandidateResponse can build
    # the derived `employment` field; upload_cv used to return the bare
    # Candidate, which tripped the response schema when strict validation
    # was introduced.
    reloaded = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate_id)
    )
    full = reloaded.scalar_one()
    return _candidate_to_response(full)


@router.get("/{candidate_id}/cv-download")
async def download_cv(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Download CV file for a candidate."""
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not candidate.cv_filename:
        raise HTTPException(status_code=404, detail="No CV uploaded for this candidate")
    file_path = os.path.join(
        settings.UPLOAD_DIR, f"candidate_{candidate_id}_{candidate.cv_filename}"
    )
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="CV file not found on disk")
    return FileResponse(
        path=file_path,
        filename=candidate.cv_filename,
        media_type="application/octet-stream",
    )


class BulkCvDownloadRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1, max_length=200)


_FILENAME_UNSAFE_RE = re.compile(r"[^\w\-. ]", re.UNICODE)


def _sanitize_zip_component(value: str) -> str:
    cleaned = _FILENAME_UNSAFE_RE.sub("_", (value or "").strip())
    cleaned = cleaned.replace("..", "_")
    return cleaned[:200] or "_"


@router.post("/bulk-cv-download")
async def bulk_cv_download(
    payload: BulkCvDownloadRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download multiple candidate CVs as a single ZIP archive.

    Skips candidates without an uploaded CV or missing file on disk and reports
    them in the `_manifest.txt` entry included at the archive root.
    """
    requested_ids = list(dict.fromkeys(payload.candidate_ids))

    result = await db.execute(select(Candidate).where(Candidate.id.in_(requested_ids)))
    candidates_by_id = {c.id: c for c in result.scalars().all()}

    manifest_rows: list[str] = ["id\tfirst\tlast\tcv_filename\tstatus"]
    included = 0
    skipped = 0

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        for cid in requested_ids:
            candidate = candidates_by_id.get(cid)
            if candidate is None:
                manifest_rows.append(f"{cid}\t\t\t\tskipped_not_found")
                skipped += 1
                continue
            if not candidate.cv_filename:
                manifest_rows.append(
                    f"{cid}\t{candidate.name}\t{candidate.lastname}\t\tskipped_no_cv"
                )
                skipped += 1
                continue

            file_path = os.path.join(
                settings.UPLOAD_DIR,
                f"candidate_{candidate.id}_{candidate.cv_filename}",
            )
            data: bytes | None = None
            if os.path.exists(file_path):
                try:
                    async with aiofiles.open(file_path, "rb") as f:
                        data = await f.read()
                except OSError as err:
                    logger.warning(
                        "bulk_cv_download: failed to read %s: %s", file_path, err
                    )
            elif candidate.cv_storage_key:
                # Round 2 migracja (audit-2026-05-07): CV w Hetzner Object Storage.
                from app.services.object_storage import (
                    download_cv as _download_cv,
                    is_available as _storage_available,
                )

                if _storage_available():
                    try:
                        data = _download_cv(candidate.cv_storage_key)
                    except Exception as err:
                        logger.warning(
                            "bulk_cv_download: storage fetch failed for %s: %s",
                            candidate.id,
                            err,
                        )
                # Fallback do BYTEA jeśli storage nie odpowiada — przed
                # finalize-delete-bytea oba mogą współistnieć.
                if data is None and candidate.cv_file_content:
                    data = candidate.cv_file_content
            elif candidate.cv_file_content:
                data = candidate.cv_file_content

            if data is None:
                manifest_rows.append(
                    f"{cid}\t{candidate.name}\t{candidate.lastname}\t"
                    f"{candidate.cv_filename}\tskipped_file_missing"
                )
                skipped += 1
                continue

            ext = os.path.splitext(candidate.cv_filename)[1] or ".pdf"
            entry_name = (
                f"{_sanitize_zip_component(candidate.lastname)}_"
                f"{_sanitize_zip_component(candidate.name)}_"
                f"{candidate.id}{ext}"
            )
            zf.writestr(entry_name, data)
            manifest_rows.append(
                f"{cid}\t{candidate.name}\t{candidate.lastname}\t"
                f"{candidate.cv_filename}\tincluded"
            )
            included += 1

        zf.writestr("_manifest.txt", "\n".join(manifest_rows) + "\n")

    archive_name = f"nexus-cvs-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{archive_name}"',
        "X-Included-Count": str(included),
        "X-Skipped-Count": str(skipped),
        "Access-Control-Expose-Headers": "Content-Disposition, X-Included-Count, X-Skipped-Count",
    }
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers=headers,
    )


@router.post("/bulk-import", status_code=status.HTTP_201_CREATED)
async def bulk_import_candidates(
    data: list[CandidateCreate],
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Import multiple candidates at once."""
    created = []
    for item in data:
        candidate = Candidate(**item.model_dump())
        candidate.created_by = current_user.id
        db.add(candidate)
        await db.flush()
        created.append(candidate.id)
        user_activity = UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.candidate_added,
            entity_type="candidate",
            entity_id=candidate.id,
            details={"name": f"{candidate.name} {candidate.lastname}", "bulk": True},
        )
        db.add(user_activity)
    activity = Activity(
        entity_type="candidate",
        entity_id=0,
        action="bulk_import",
        user_id=current_user.id,
        details={"count": len(created), "ids": created},
    )
    db.add(activity)
    return {"created": len(created), "ids": created}


@router.post("/check-duplicates")
async def check_duplicates(
    payload: DuplicateCheckPayload,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Return candidates matching the provided identifiers (email/phone/linkedin/name+lastname).

    Non-blocking — the API does not reject on duplicates. Callers (UI import modals,
    create/update flows) decide how to react. Used for duplicate-warning banners.
    """
    return await find_candidate_duplicates(
        db,
        email=payload.email,
        phone=payload.phone,
        linkedin=payload.linkedin,
        name=payload.name,
        lastname=payload.lastname,
        exclude_candidate_id=payload.exclude_candidate_id,
    )


# ── Engagement + location (Kontrakty expansion) ─────────────────────────────


@router.patch(
    "/{candidate_id}/engagement",
    response_model=CandidateResponse,
)
async def update_candidate_engagement(
    candidate_id: int,
    data: CandidateEngagementUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Update consultant engagement flags (ambassador, verifier, side projects…)."""
    candidate = await db.scalar(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate_id)
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No engagement fields provided")

    # Auto-update per-flag timestamps whenever an `open_to_*` value is touched —
    # nawet jeśli wartość się nie zmienia. Rekruter może „potwierdzić" świeżość
    # deklaracji przez nudge UI wysyłając tę samą wartość ponownie.
    _OPEN_TO_TIMESTAMP_FIELDS = (
        "open_to_side_projects",
        "open_to_sales_support",
        "open_to_expert_consult",
    )
    now = datetime.now(timezone.utc)
    for k, v in updates.items():
        setattr(candidate, k, v)
        if k in _OPEN_TO_TIMESTAMP_FIELDS:
            setattr(candidate, f"{k}_updated_at", now)

    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="engagement_updated",
            user_id=current_user.id,
            details=updates,
        )
    )
    await db.flush()
    await db.refresh(candidate)
    return _candidate_to_response(candidate)


@router.post(
    "/{candidate_id}/engagement-declaration-link",
    status_code=201,
)
async def create_engagement_declaration_link(
    candidate_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Generuje magic-link dla kandydata do self-service deklaracji „Otwartość".

    Link jest jednokrotny, TTL 30 dni. Frontend formularz: `/engagement/{token}`.
    Wysyłka maila opcjonalna — endpoint zwraca tylko token i URL, rekruter kopiuje
    do swojej kanałowej komunikacji (Slack/email/SMS).

    Phase „Otwartość" Faza 2.6.
    """
    import secrets
    from app.models.engagement_token import EngagementDeclarationToken
    from datetime import timedelta as _timedelta

    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    token_str = secrets.token_urlsafe(24)  # ~32 chars urlsafe
    now = datetime.now(timezone.utc)
    expires_at = now + _timedelta(days=30)

    row = EngagementDeclarationToken(
        candidate_id=candidate_id,
        token=token_str,
        created_at=now,
        expires_at=expires_at,
        created_by=current_user.id,
    )
    db.add(row)
    await db.commit()

    base = (
        settings.PUBLIC_APP_URL.rstrip("/")
        if hasattr(settings, "PUBLIC_APP_URL") and settings.PUBLIC_APP_URL
        else "https://nexus.dynaminds.pl"
    )
    return {
        "token": token_str,
        "url": f"{base}/engagement/{token_str}",
        "expires_at": expires_at.isoformat(),
    }


@router.patch(
    "/{candidate_id}/location",
    response_model=CandidateResponse,
)
async def update_candidate_location(
    candidate_id: int,
    data: CandidateLocationUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Update consultant structured location (city / country / hub)."""
    candidate = await db.scalar(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate_id)
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No location fields provided")
    for k, v in updates.items():
        setattr(candidate, k, v)

    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="location_updated",
            user_id=current_user.id,
            details=updates,
        )
    )
    await db.flush()
    await db.refresh(candidate)
    return _candidate_to_response(candidate)


# ── AI CC matching + suggested pools (migracja 0041) ───────────────────────


class SuggestedPoolOut(BaseModel):
    pool_id: int
    pool_name: str
    score: float
    band: str  # "auto" | "suggest"
    already_member: bool


class CandidateCcOut(BaseModel):
    competence_category_id: int
    slug: str
    name_pl: str
    is_primary: bool
    confidence_score: float
    source: str


class CandidateCcAssign(BaseModel):
    competence_category_id: int
    is_primary: bool = False


@router.get(
    "/{candidate_id}/suggested-pools",
    response_model=list[SuggestedPoolOut],
)
async def get_suggested_pools(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return talent pools ranked by centroid similarity to this candidate."""
    from app.services.pool_suggester import suggest_pools_for_candidate

    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    suggestions = await suggest_pools_for_candidate(db, candidate_id)
    return [SuggestedPoolOut(**s.to_dict()) for s in suggestions]


@router.get(
    "/{candidate_id}/competence-categories",
    response_model=list[CandidateCcOut],
)
async def list_candidate_ccs(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return all CC assignments (primary + secondary) for a candidate."""
    from app.models.competence_category import (
        CandidateCompetenceCategory,
        CompetenceCategory,
    )

    rows = (
        await db.execute(
            select(CandidateCompetenceCategory, CompetenceCategory)
            .join(
                CompetenceCategory,
                CandidateCompetenceCategory.competence_category_id
                == CompetenceCategory.id,
            )
            .where(CandidateCompetenceCategory.candidate_id == candidate_id)
            .order_by(
                CandidateCompetenceCategory.is_primary.desc(),
                CandidateCompetenceCategory.confidence_score.desc(),
            )
        )
    ).all()
    return [
        CandidateCcOut(
            competence_category_id=cc.id,
            slug=cc.slug,
            name_pl=cc.name_pl,
            is_primary=ccc.is_primary,
            confidence_score=ccc.confidence_score,
            source=ccc.source.value
            if hasattr(ccc.source, "value")
            else str(ccc.source),
        )
        for ccc, cc in rows
    ]


@router.post(
    "/{candidate_id}/competence-categories",
    response_model=CandidateCcOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_candidate_cc(
    candidate_id: int,
    body: CandidateCcAssign,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Manually assign (or upsert) a CC to a candidate with `source='manual'`."""
    from app.models.competence_category import (
        CandidateCcCategorySource,
        CandidateCompetenceCategory,
        CompetenceCategory,
    )
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    cc = await db.scalar(
        select(CompetenceCategory).where(
            CompetenceCategory.id == body.competence_category_id
        )
    )
    if not cc:
        raise HTTPException(status_code=404, detail="Competence Category not found")

    # If assigning as primary: clear previous primary for this candidate
    if body.is_primary:
        await db.execute(
            CandidateCompetenceCategory.__table__.update()
            .where(CandidateCompetenceCategory.candidate_id == candidate_id)
            .values(is_primary=False)
        )

    # Upsert
    stmt = (
        pg_insert(CandidateCompetenceCategory)
        .values(
            candidate_id=candidate_id,
            competence_category_id=body.competence_category_id,
            is_primary=body.is_primary,
            confidence_score=1.0,
            source=CandidateCcCategorySource.manual.value,
        )
        .on_conflict_do_update(
            index_elements=["candidate_id", "competence_category_id"],
            set_={
                "is_primary": body.is_primary,
                "confidence_score": 1.0,
                "source": CandidateCcCategorySource.manual.value,
            },
        )
    )
    await db.execute(stmt)

    # Backwards-compat: keep legacy single FK in sync when primary flagged
    if body.is_primary:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id)
        )
        if candidate:
            candidate.competence_category_id = body.competence_category_id
    await db.commit()

    return CandidateCcOut(
        competence_category_id=cc.id,
        slug=cc.slug,
        name_pl=cc.name_pl,
        is_primary=body.is_primary,
        confidence_score=1.0,
        source="manual",
    )


@router.delete(
    "/{candidate_id}/competence-categories/{cc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unassign_candidate_cc(
    candidate_id: int,
    cc_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Remove a CC assignment from a candidate."""
    from app.models.competence_category import CandidateCompetenceCategory

    link = await db.scalar(
        select(CandidateCompetenceCategory).where(
            CandidateCompetenceCategory.candidate_id == candidate_id,
            CandidateCompetenceCategory.competence_category_id == cc_id,
        )
    )
    if link is None:
        return  # idempotent
    was_primary = link.is_primary
    await db.delete(link)
    if was_primary:
        # Clear legacy FK too; next classifier run may repopulate
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id)
        )
        if candidate and candidate.competence_category_id == cc_id:
            candidate.competence_category_id = None
    await db.commit()


@router.post(
    "/{candidate_id}/sync-linkedin",
    response_model=CandidateLinkedinSyncResponse,
)
async def sync_candidate_linkedin_now(
    candidate_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Force an immediate Proxycurl sync for this candidate.

    The scheduled `linkedin_sync_loop` picks candidates up every
    `PROXYCURL_CANDIDATE_STALE_DAYS` days; this endpoint lets the recruiter
    skip the queue. Inline (not background) so the UI gets the fresh
    `linkedin_sync_status` in the response and can update the badge
    without polling.
    """

    if not settings.PROXYCURL_ENABLED or not settings.PROXYCURL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LinkedIn sync is not configured (PROXYCURL_API_KEY missing)",
        )

    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not candidate.linkedin:
        raise HTTPException(
            status_code=400,
            detail="Candidate has no LinkedIn URL on file",
        )

    from app.services.proxycurl import sync_candidate_linkedin

    result = await sync_candidate_linkedin(db, candidate)

    # Map sync result → response status literal the frontend switches on.
    status_map = {
        "ok": "ok",
        "not_found": "not_found",
        "error": "error",
        "rate_limited": "error",
        "disabled": "disabled",
    }
    mapped = status_map.get(result.status.value, "error")
    message: Optional[str] = None
    if result.error:
        message = result.error
    elif result.change_kind:
        message = result.change_kind.value

    return CandidateLinkedinSyncResponse(
        status=mapped,
        candidate_id=candidate_id,
        message=message,
    )
