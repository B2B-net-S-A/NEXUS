from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional
import asyncio
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
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, delete, false, func, not_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.rate_limit import limiter
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.candidate_document import CandidateDocument
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.activity import Activity
from app.models.invite_link import CandidateInviteLink
from app.models.user_activity import UserActivity, UserActionType
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.models.pipeline_template import RejectionReason
from app.models.recruitment_pipeline import CandidateStage
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.talent_pool import TalentPoolMembership
from app.models.user import User
from app.schemas.candidate import (
    CandidateCreate,
    CandidateDocumentOut,
    CandidateEngagementUpdate,
    ActiveRecruitmentBrief,
    CandidateFromCVDuplicate,
    CandidateFromCVResponse,
    CandidateFromLinkedInCreate,
    CandidateFromLinkedInResponse,
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
from app.models.linkedin_snapshot import LinkedinSyncStatus
from app.models.recruitment_pipeline import STAGE_CATEGORY, PipelineStage, StageCategory
from app.schemas.pipeline import ClientRateUpdate
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


_NOTE_PREVIEW_MAX_CHARS = 120
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
# Frontend stores @-mentions inside Tiptap notes as `$$user_NN$$` markers
# (resolved client-side against the users cache). For the list preview we
# strip them down to a plain "@user" placeholder so the recruiter sees text,
# not internal ids.
_USER_MENTION_RE = re.compile(r"\$\$user_\d+\$\$")
_HTML_ENTITIES = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
}
_RATE_UNIT_SHORT = {"hourly": "/h", "daily": "/d", "monthly": "/mc"}


def _extract_tiptap_text(node) -> str:
    """Walk Tiptap doc JSON and concatenate all `text` nodes. Tiptap shapes:
    {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"..."}]}]}
    Some richer notes wrap as {"content": [...]} or {"content": "raw text"} — we
    handle both. Anything we can't parse falls back to the raw string.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_extract_tiptap_text(item) for item in node if item is not None)
    if isinstance(node, dict):
        # Leaf text node
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            return node["text"]
        # Container — walk `content` recursively (Tiptap convention)
        if "content" in node:
            return _extract_tiptap_text(node["content"])
        # Fallback: join any string-valued field — defensive for legacy shapes.
        return " ".join(v for v in node.values() if isinstance(v, str) and v.strip())
    return ""


def _format_note_preview(raw: str) -> str:
    """Strip HTML / Tiptap JSON + collapse whitespace + truncate. Notatki w
    NEXUS są zapisywane przez Tiptap editor — czasem jako HTML (legacy z
    Word/Outlook paste), czasem jako serializowany JSON document. Podgląd w
    liście kandydatów ma być czystym tekstem.
    """
    if not raw:
        return ""
    raw = raw.strip()
    # JSON-shaped (Tiptap doc) — `{"type":"doc",…}` or `{"content":…}`.
    if raw.startswith("{") or raw.startswith("["):
        try:
            import json

            text_only = _extract_tiptap_text(json.loads(raw))
        except (ValueError, TypeError):
            text_only = raw
    else:
        text_only = raw
    text_only = _HTML_TAG_RE.sub(" ", text_only)
    text_only = _USER_MENTION_RE.sub("@user", text_only)
    for entity, replacement in _HTML_ENTITIES.items():
        text_only = text_only.replace(entity, replacement)
    text_only = _WHITESPACE_RE.sub(" ", text_only).strip()
    if len(text_only) <= _NOTE_PREVIEW_MAX_CHARS:
        return text_only
    return text_only[: _NOTE_PREVIEW_MAX_CHARS - 1].rstrip() + "…"


def _format_rejection_reason(
    *,
    reason_name: Optional[str],
    stage_notes: Optional[str],
    rejection_note: Optional[str],
    job_title: Optional[str],
    client_name: Optional[str],
) -> Optional[str]:
    """Compose triage label dla najnowszego odrzucenia. Priority:
    1. Structured rejection_reason.name (FK z pipeline_template). Cleanest signal.
    2. CandidateStage.rejection_note (free-text rejection blob from `verified` flow).
    3. CandidateStage.notes (general transition note).
    Doklejamy " · job · (client)" gdy są — dzięki temu rekruter widzi gdzie kandydat odpadł.
    """
    primary = (reason_name or "").strip()
    if not primary:
        primary = (rejection_note or "").strip()
    if not primary:
        primary = (stage_notes or "").strip()
    if not primary:
        primary = "Odrzucony"
    primary = _format_note_preview(primary) or "Odrzucony"

    context_parts: list[str] = []
    job = (job_title or "").strip()
    client = (client_name or "").strip()
    if job:
        context_parts.append(job)
    if client:
        context_parts.append(f"({client})")
    if context_parts:
        return f"{primary} · {' '.join(context_parts)}"
    return primary


def _format_rate(value, unit: Optional[str], currency: Optional[str]) -> str:
    """Render Decimal/int rate jako "150 PLN/h". Brak unit → bez sufiksu;
    brak currency → "PLN" jako default (dominujący w NEXUS).
    """
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return ""
    if amount.is_integer():
        amount_str = f"{int(amount):,}".replace(",", " ")
    else:
        amount_str = f"{amount:,.2f}".replace(",", " ")
    cur = (currency or "PLN").strip().upper() or "PLN"
    suffix = _RATE_UNIT_SHORT.get((unit or "").strip().lower(), "")
    return f"{amount_str} {cur}{suffix}".strip()


def _candidate_list_options():
    """Eager-load relations required to derive employment state without N+1 lazy loads."""
    from app.models.linkedin_snapshot import CandidateLinkedinSnapshot  # noqa: F401

    return (
        selectinload(Candidate.contracts).selectinload(Contract.client),
        selectinload(Candidate.conflicts).selectinload(CandidateConflict.client),
        # Pipeline stages → job → client: lets `_derive_employment` detect the
        # "currently hired" signal (latest stage per job == hired) and name the
        # client. Required by every `_derive_employment` caller to avoid an
        # async lazy-load (MissingGreenlet).
        selectinload(Candidate.pipeline_stages)
        .selectinload(CandidateStage.job)
        .selectinload(Job.client),
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
    Derived SQL predicate: candidate is currently employed at one of our
    clients. True when ANY of:
      • an active Contract, OR
      • an active `current_employment` conflict, OR
      • a recruitment whose LATEST stage is `hired`.

    The hired-stage clause is what makes `employment=at_client` return the real
    placed-consultant population. `candidate_stages.stage='hired'` is documented
    as "Zatrudniony / kontrakt aktywny" and is the signal the Traffit import
    populated — the `contracts` table was never backfilled, so the contract /
    conflict clauses alone matched ~1 row out of ~700 placed consultants.

    `candidate_stages` is append-only history, so "currently hired" means a
    `hired` row with no later move for the same job (mirrored in
    `_derive_employment`). Drives the inverse `employment=available` filter too,
    via `not_(_at_client_predicate())`.
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
    later_stage = aliased(CandidateStage)
    hired_latest_exists = (
        select(1)
        .where(
            and_(
                CandidateStage.candidate_id == Candidate.id,
                CandidateStage.stage == PipelineStage.hired,
                # No later move exists for the same job → `hired` is current.
                ~(
                    select(1)
                    .where(
                        and_(
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
                    )
                    .exists()
                ),
            )
        )
        .exists()
    )
    return or_(contract_exists, conflict_exists, hired_latest_exists)


def _current_company_predicate(values: list[str]):
    """Match candidates whose CURRENT company ILIKE any of values (OR).

    Resolves against (OR-combined):
      1. `linkedin_current_company` (Proxycurl-synced, freshest signal)
      2. ANY `experience[*]` entry where `end IS NULL` AND `company` ILIKE pat
         — the data convention (set by `backfill_candidate_experience`):
         `end IS NULL` is the canonical "current job" marker.

    Why not `experience[0].company`? The backfill places an empty placeholder
    slot at index 0 when it cannot disambiguate the current job from a
    multi-line aggregated `company` string in the CV. Real current employers
    routinely land at idx 2+ with `end=null`. Position-0 lookup would silently
    skip them — e.g. `?cur_co=Nordea` returned 1 result instead of ~406.
    Using the `end IS NULL` marker catches them all, irrespective of position.
    """
    clauses = []
    for i, v in enumerate(values):
        v = (v or "").strip()
        if not v:
            continue
        pat = f"%{v.lower()}%"
        exists_clause = text(
            "EXISTS ("
            "SELECT 1 FROM jsonb_array_elements("
            "CASE WHEN jsonb_typeof(candidates.experience) = 'array' "
            "THEN candidates.experience ELSE '[]'::jsonb END"
            ") AS e(elem) "
            "WHERE elem->>'end' IS NULL "
            f"AND lower(coalesce(elem->>'company', '')) LIKE :cur_co_{i}"
            ")"
        ).bindparams(**{f"cur_co_{i}": pat})
        clauses.append(
            or_(
                func.lower(func.coalesce(Candidate.linkedin_current_company, "")).like(
                    pat
                ),
                exists_clause,
            )
        )
    return or_(*clauses) if clauses else false()


def _current_title_predicate(values: list[str]):
    """Match candidates whose CURRENT role ILIKE any of values (OR).

    Same shape as `_current_company_predicate`:
      1. `linkedin_current_title` (Proxycurl-synced, freshest signal)
      2. ANY `experience[*]` entry where `end IS NULL` AND `role` ILIKE pat.

    Uses the `end IS NULL` marker rather than `experience[0].role` for the
    same reason — backfill placeholder slots at index 0 silently skip real
    current titles that sit at idx 2+ with end=null.
    """
    clauses = []
    for i, v in enumerate(values):
        v = (v or "").strip()
        if not v:
            continue
        pat = f"%{v.lower()}%"
        exists_clause = text(
            "EXISTS ("
            "SELECT 1 FROM jsonb_array_elements("
            "CASE WHEN jsonb_typeof(candidates.experience) = 'array' "
            "THEN candidates.experience ELSE '[]'::jsonb END"
            ") AS e(elem) "
            "WHERE elem->>'end' IS NULL "
            f"AND lower(coalesce(elem->>'role', '')) LIKE :cur_title_{i}"
            ")"
        ).bindparams(**{f"cur_title_{i}": pat})
        clauses.append(
            or_(
                func.lower(func.coalesce(Candidate.linkedin_current_title, "")).like(
                    pat
                ),
                exists_clause,
            )
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
    Compute EmploymentInfo from eager-loaded `contracts` + `conflicts` +
    `pipeline_stages`. Preference order: active Contract (source of truth) →
    active current_employment conflict (manual flag) → currently hired
    (latest pipeline stage == `hired`) → on_bench (has history, incl. past
    placements) → external (never engaged).

    Requires `pipeline_stages → job → client` eager-loaded (see
    `_candidate_list_options`) — otherwise the `hired` branch lazy-loads and
    raises MissingGreenlet in async.
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

    # Pipeline signal: candidate currently sits at `hired` in some recruitment.
    # `candidate_stages` is append-only history, so "current" = the latest row
    # per job. Mirrors the hired-latest clause in `_at_client_predicate`.
    latest_stage_by_job: dict[int, CandidateStage] = {}
    for st in candidate.pipeline_stages or []:
        cur = latest_stage_by_job.get(st.job_id)
        if cur is None or (st.moved_at, st.id) > (cur.moved_at, cur.id):
            latest_stage_by_job[st.job_id] = st
    hired_now = [
        st for st in latest_stage_by_job.values() if st.stage == PipelineStage.hired
    ]
    if hired_now:
        chosen = max(hired_now, key=lambda s: (s.moved_at, s.id))
        client = chosen.job.client if chosen.job else None
        return EmploymentInfo(
            state=EmploymentState.employed_at_client,
            client_id=client.id if client else None,
            client_name=client.name if client else None,
            contract_end_date=None,
            source="pipeline",
        )

    ever_hired = any(
        st.stage == PipelineStage.hired for st in (candidate.pipeline_stages or [])
    )
    has_history = (
        bool(candidate.contracts)
        or any(
            cf.type == ConflictType.current_employment
            for cf in (candidate.conflicts or [])
        )
        or ever_hired
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
    include_active_recruitments: bool = Query(
        False,
        description=(
            "When true, each candidate gets `active_recruitments` — list of "
            "non-terminal pipeline stages (stage NOT IN rejected/withdrawn/hired). "
            "One aggregated SQL per page (DISTINCT ON candidate_id, job_id, "
            "ordered by moved_at DESC) + JOIN Job + Client. No N+1."
        ),
    ),
    include_last_activity: bool = Query(
        False,
        description=(
            "When true, each candidate gets `last_note_preview`, "
            "`last_rejection_reason`, `last_rate` — used by the candidates list "
            "to show triage context inline (no need to click the candidate to "
            "see the most recent note / rejection reason / rate). Three DISTINCT "
            "ON-style queries per page; no N+1."
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
            "LinkedIn-Recruiter style. Match candidates whose CURRENT employer "
            "ILIKE any of the values. Resolves against `linkedin_current_company` "
            "(Proxycurl-synced) OR `experience[0].company` (top-of-CV JSONB) — "
            "same priority chain as the UI's `getCurrentCompany` helper, so the "
            "filter matches whatever the recruiter sees on the candidate card. "
            "OR-combined across values."
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
            "LinkedIn-Recruiter style. Match candidates whose CURRENT role "
            "ILIKE any of the values. Resolves against `linkedin_current_title` "
            "(Proxycurl-synced) OR `experience[0].role` (top-of-CV JSONB) — "
            "same priority chain as the UI's `getCurrentTitle` helper, so the "
            "filter matches whatever the recruiter sees on the candidate card. "
            "OR-combined across values."
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
            "See `q_all` for matched fields. This is OR-group 0; add more "
            "AND-ed OR-groups with `q_any_group`."
        ),
    ),
    q_any_group: Optional[list[str]] = Query(
        None,
        description=(
            "Advanced search — additional OR-groups for the ANY bucket. Each "
            "value is ONE group with phrases joined by `|`; the groups AND "
            "together (and with `q_any`). Example: "
            "`?q_any_group=react|vue&q_any_group=java|kotlin` ⇒ "
            "(react OR vue) AND (java OR kotlin). See `q_all` for matched fields."
        ),
    ),
    q_none: Optional[list[str]] = Query(
        None,
        description=(
            "Advanced search — none of these phrases may appear (NOT). "
            "See `q_all` for matched fields."
        ),
    ),
    pipeline_stage: Optional[list[PipelineStage]] = Query(
        None,
        description=(
            "Filter by candidate's pipeline stage — one or more values "
            "(e.g. `new`, `screening`, `verified`, `interview`, `cv_sent`, "
            "`client_interview`, `acceptance`, `negotiation`, `onboarding`, "
            "`hired`, `rejected`, `withdrawn`). Repeat the param for "
            "multi-select. OR-combined. By default matches CURRENT stage "
            "(latest `CandidateStage.moved_at` per `(candidate_id, job_id)`); "
            "switch with `stage_current_only=false` to match historical "
            "presence on any of these stages."
        ),
    ),
    stage_category: Optional[list[StageCategory]] = Query(
        None,
        description=(
            "Coarse-grained pipeline filter — expands to `pipeline_stage` "
            "by category (`internal`, `external`, `terminal`). Combined "
            "with `pipeline_stage` via OR. Use when the recruiter wants "
            "'every candidate currently in any external client step' "
            "without listing all 4 external stages individually."
        ),
    ),
    stage_current_only: Optional[bool] = Query(
        None,
        description=(
            "When true, `pipeline_stage` / `stage_category` match the CURRENT "
            "stage of each candidate-job pair (latest move per pair). When "
            "false, match any historical presence on the selected stages — "
            "useful for 'show everyone who was ever rejected' style queries. "
            "When omitted (default), the mode is resolved automatically: a "
            "bare stage filter matches the CURRENT stage, but as soon as a "
            "who/when move-filter (`stage_moved_by` / `stage_moved_after` / "
            "`stage_moved_before`) is present the query becomes HISTORICAL — "
            "because 'everyone Jan moved onto Verified in May' must include "
            "candidates who have since progressed past Verified. Pass "
            "`stage_current_only=true` explicitly to override and keep the "
            "current-stage restriction even with a move-filter."
        ),
    ),
    stage_moved_by: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by WHO moved the candidate onto the matched stage "
            "(`CandidateStage.moved_by`) — one or more user ids, OR-combined. "
            "Correlated with `pipeline_stage`/`stage_category`: when a stage is "
            "also selected, only moves ONTO that stage count; with no stage "
            "selected, any stage move by these users matches. Sentinel `0` "
            "matches NULL (system / Traffit-imported moves). By default the "
            "presence of this filter switches matching to HISTORICAL (any "
            "qualifying move counts, even if the candidate has since moved on); "
            "pass `stage_current_only=true` to restrict to the candidate's "
            "CURRENT move per job-pair instead."
        ),
    ),
    stage_moved_after: Optional[date] = Query(
        None,
        description=(
            "Filter by WHEN the candidate was moved onto the matched stage — "
            "lower bound (inclusive), `YYYY-MM-DD`. Matches "
            "`CandidateStage.moved_at >= 00:00 UTC` of this day. Correlated "
            "with the stage filter exactly like `stage_moved_by`."
        ),
    ),
    stage_moved_before: Optional[date] = Query(
        None,
        description=(
            "Filter by WHEN the candidate was moved onto the matched stage — "
            "upper bound (inclusive), `YYYY-MM-DD`. Matches "
            "`CandidateStage.moved_at < 00:00 UTC` of the NEXT day, so the "
            "whole `before` day is included."
        ),
    ),
    sort: str = Query(
        "newest",
        pattern="^(newest|oldest|name|relevance)$",
        description=(
            "Sort order. 'newest' = created_at DESC; 'oldest' = created_at ASC; "
            "'name' = name ASC, lastname ASC; 'relevance' = trigram similarity "
            "between query phrase and name+lastname+email DESC (auto-falls "
            "back to 'newest' when no `q` / `q_all` / `q_any` is provided). "
            "All include `id` tie-breaker for 100% stable pagination across "
            "requests (required for next/prev candidate navigation in the UI)."
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
    # Simple search delegates to the same per-phrase predicate as the advanced
    # ALL/ANY/NONE buckets (see `app.services.advanced_candidate_search`). This
    # ensures `?q=Python` and `?q_all=Python` return the same candidates —
    # before this unification simple search was limited to name/lastname/email
    # + raw_cv_text (+ trigram on identity), causing a confusing UX where the
    # same phrase produced different result counts depending on which mode the
    # user happened to use. We additionally OR-in the trigram similarity test
    # on `name+lastname+email` so typos/case mismatches still match identity
    # via the GIN index.
    from app.services.advanced_candidate_search import (
        build_advanced_filter,
        single_phrase_filter,
    )

    if q:
        q_stripped = q.strip()
        phrase_clause = single_phrase_filter(q_stripped)
        if len(q_stripped) >= 3:
            identity_expr = (
                func.coalesce(Candidate.name, "")
                + " "
                + func.coalesce(Candidate.lastname, "")
                + " "
                + func.coalesce(Candidate.email, "")
            )
            # Adaptive trigram threshold: 0.2 (loose) fires for every "Piotr X"
            # candidate when the query is "Piotr Banulski" because shared "Piotr"
            # trigrams alone clear the bar. For multi-word queries (likely a
            # full name), require 0.5 — keeps mild typo tolerance ("Banulsky"
            # → "Banulski") while filtering shared-first-name noise. Single
            # tokens stay at 0.2 for aggressive typo matching ("Banulsk" → "Banulski").
            trigram_threshold = 0.5 if " " in q_stripped else 0.2
            trigram_clause = (
                func.similarity(identity_expr, q_stripped) > trigram_threshold
            )
            if phrase_clause is not None:
                query = query.where(or_(phrase_clause, trigram_clause))
            else:
                query = query.where(trigram_clause)
        elif phrase_clause is not None:
            query = query.where(phrase_clause)

    # Traffit-style advanced search — ALL / ANY / NONE buckets combine with `q`.
    # Each `q_any_group` value is one pipe-joined OR-group; split into phrases
    # (the service cleans/caps each group and drops the empties).
    q_any_groups = [g.split("|") for g in q_any_group] if q_any_group else None
    _advanced = build_advanced_filter(q_all, q_any, q_none, q_any_groups)
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

    # Pipeline stage filter — match candidates by current stage (default) or by
    # any historical move (`stage_current_only=false`). `stage_category` expands
    # to PipelineStage values via STAGE_CATEGORY mapping, then OR-combined with
    # `pipeline_stage` so the recruiter can mix coarse + specific selections.
    requested_stages: set[PipelineStage] = set(pipeline_stage or [])
    if stage_category:
        cat_set = set(stage_category)
        requested_stages.update(
            stage for stage, cat in STAGE_CATEGORY.items() if cat in cat_set
        )
    # "Kto dodał na etap i kiedy" — who/when of the stage move, correlated with
    # the stage filter so the recruiter can ask e.g. "candidates Jan moved onto
    # `verified` between X and Y". Date bounds are half-open UTC days:
    # [moved_after 00:00, moved_before + 1 day 00:00).
    moved_after_dt: Optional[datetime] = None
    if stage_moved_after is not None:
        moved_after_dt = datetime(
            stage_moved_after.year,
            stage_moved_after.month,
            stage_moved_after.day,
            tzinfo=timezone.utc,
        )
    moved_before_dt: Optional[datetime] = None
    if stage_moved_before is not None:
        _excl = stage_moved_before + timedelta(days=1)
        moved_before_dt = datetime(
            _excl.year, _excl.month, _excl.day, tzinfo=timezone.utc
        )

    def _move_predicates(moved_by_col, moved_at_col) -> list:
        """Correlated who/when predicates on the matched stage move."""
        preds: list = []
        if stage_moved_by:
            # Sentinel 0 = "no mover on record" (system / Traffit import).
            real_ids = [uid for uid in stage_moved_by if uid != 0]
            include_null = 0 in stage_moved_by
            if include_null and real_ids:
                preds.append(or_(moved_by_col.is_(None), moved_by_col.in_(real_ids)))
            elif include_null:
                preds.append(moved_by_col.is_(None))
            elif real_ids:
                preds.append(moved_by_col.in_(real_ids))
        if moved_after_dt is not None:
            preds.append(moved_at_col >= moved_after_dt)
        if moved_before_dt is not None:
            preds.append(moved_at_col < moved_before_dt)
        return preds

    has_move_filter = (
        bool(stage_moved_by)
        or moved_after_dt is not None
        or moved_before_dt is not None
    )

    # Resolve current-vs-historical matching. An explicit `stage_current_only`
    # always wins. When unspecified (None), a who/when move-filter implies a
    # historical question — "everyone X moved onto Verified in May", most of
    # whom have since progressed past Verified — so we match any qualifying
    # move; a bare stage filter keeps the current-stage default. (Without this,
    # the default current-only matching silently drops ~80-95% of the recruiter's
    # answer: candidates who were verified but moved on.)
    if stage_current_only is None:
        effective_current_only = not has_move_filter
    else:
        effective_current_only = stage_current_only

    if requested_stages or has_move_filter:
        stage_values = list(requested_stages)
        if effective_current_only and stage_values:
            # CURRENT stage = latest move per (candidate_id, job_id). Use
            # DISTINCT ON to pick the freshest row per pair, then EXISTS that
            # the candidate has any pair whose current stage is in the set.
            # moved_by/moved_at are carried into the projection so the who/when
            # predicates apply to that SAME latest (current) move.
            latest_per_pair = (
                select(
                    CandidateStage.candidate_id,
                    CandidateStage.stage,
                    CandidateStage.moved_by,
                    CandidateStage.moved_at,
                )
                .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
                .order_by(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
                    CandidateStage.moved_at.desc(),
                    CandidateStage.id.desc(),
                )
                .subquery()
            )
            conds = [
                latest_per_pair.c.candidate_id == Candidate.id,
                latest_per_pair.c.stage.in_(stage_values),
            ]
            conds.extend(
                _move_predicates(latest_per_pair.c.moved_by, latest_per_pair.c.moved_at)
            )
            stage_exists = select(1).select_from(latest_per_pair).where(*conds).exists()
        else:
            # Historical presence (`stage_current_only=false`) OR a who/when
            # filter with no stage selected. Match ANY CandidateStage row that
            # satisfies the (optional) stage set + who/when predicates.
            conds = [CandidateStage.candidate_id == Candidate.id]
            if stage_values:
                conds.append(CandidateStage.stage.in_(stage_values))
            conds.extend(
                _move_predicates(CandidateStage.moved_by, CandidateStage.moved_at)
            )
            stage_exists = select(1).where(*conds).exists()
        query = query.where(stage_exists)

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
    elif sort == "relevance":
        # Relevance ranking: trigram similarity between the user's phrase
        # and `name + lastname + email`. Higher score = better identity
        # match. When no search phrase exists (recruiter sorted by
        # relevance with empty query), fall back to newest-first so the
        # list is still useful and not arbitrarily ordered.
        relevance_terms: list[str] = []
        if q:
            relevance_terms.append(q.strip())
        for bucket in (q_all, q_any):
            if bucket:
                relevance_terms.extend(s.strip() for s in bucket if s and s.strip())
        if q_any_groups:
            for group in q_any_groups:
                relevance_terms.extend(s.strip() for s in group if s and s.strip())

        if relevance_terms:
            # Concatenate all candidate identity fields into a single haystack
            # the trigram index can score against. Joining with " " keeps
            # word boundaries intact so "Jan Kowalski" ranks above
            # "Janowski Smith" for the query "Jan Kowalski".
            haystack = (
                func.coalesce(Candidate.name, "")
                + " "
                + func.coalesce(Candidate.lastname, "")
                + " "
                + func.coalesce(Candidate.email, "")
            )
            # SUM trigram similarity across all phrases — multi-phrase
            # queries reward candidates matching more of the buckets.
            score = sum(func.similarity(haystack, term) for term in relevance_terms)
            query = query.order_by(
                score.desc(), Candidate.created_at.desc(), Candidate.id.desc()
            )
        else:
            # Defensive fallback — UI shouldn't request relevance without
            # a phrase, but we still ship a stable order if it does.
            query = query.order_by(Candidate.created_at.desc(), Candidate.id.desc())
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

    # Active recruitments aggregation (non-terminal stages). One SQL per page:
    # DISTINCT ON (candidate_id, job_id) ORDER BY moved_at DESC, id DESC →
    # najnowszy ruch per parę. Następnie WHERE stage NOT IN terminal
    # (rejected/withdrawn/hired) + JOIN Job + Client. Lista bezpieczna dla
    # response — żadnych szczegółów scorecard/rate'ów.
    active_recruitments_by_candidate: dict[int, list[ActiveRecruitmentBrief]] = {}
    if include_active_recruitments and items:
        candidate_ids = [c.id for c in items]
        # PostgreSQL DISTINCT ON — bierze pierwszy rekord per grupa zgodnie z ORDER BY.
        # DISTINCT ON wybiera najnowszy ruch per (candidate, job) — TEN SAM
        # rekord trzyma `moved_at`/`moved_by` (kto i kiedy przeniósł na bieżący
        # etap), więc atrybucję dostajemy bez dodatkowego zapytania (no N+1).
        latest_per_pair = (
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.stage,
                CandidateStage.moved_at,
                CandidateStage.moved_by,
            )
            .where(CandidateStage.candidate_id.in_(candidate_ids))
            .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
            .order_by(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.moved_at.desc(),
                CandidateStage.id.desc(),
            )
            .subquery()
        )
        terminal_stages = (
            PipelineStage.rejected,
            PipelineStage.withdrawn,
            PipelineStage.hired,
        )
        mover = aliased(User)
        active_stmt = (
            select(
                latest_per_pair.c.candidate_id,
                latest_per_pair.c.job_id,
                latest_per_pair.c.stage,
                Job.title,
                Client.name.label("client_name"),
                latest_per_pair.c.moved_at,
                mover.name.label("moved_by_name"),
            )
            .select_from(latest_per_pair)
            .join(Job, Job.id == latest_per_pair.c.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(mover, mover.id == latest_per_pair.c.moved_by)
            .where(latest_per_pair.c.stage.not_in(terminal_stages))
        )
        for (
            cand_id,
            job_id,
            stage,
            job_title,
            client_name,
            moved_at,
            moved_by_name,
        ) in (await db.execute(active_stmt)).all():
            active_recruitments_by_candidate.setdefault(cand_id, []).append(
                ActiveRecruitmentBrief(
                    job_id=job_id,
                    job_title=job_title or "—",
                    client_name=client_name,
                    stage=stage,
                    moved_at=moved_at,
                    moved_by_name=moved_by_name,
                )
            )

    # Last-activity aggregation (Phase „Search inline visibility"). 3 DISTINCT ON
    # queries po jednym SQL per page: najnowsza notatka, najnowszy rejection,
    # najnowsza pozaiownnio-zerowana stawka z pipeline'u. Brak N+1.
    last_note_by_candidate: dict[int, str] = {}
    last_rejection_by_candidate: dict[int, str] = {}
    last_rate_by_candidate: dict[int, str] = {}
    if include_last_activity and items:
        candidate_ids = [c.id for c in items]

        last_note_stmt = (
            select(Note.candidate_id, Note.content)
            .where(Note.candidate_id.in_(candidate_ids))
            .distinct(Note.candidate_id)
            .order_by(
                Note.candidate_id,
                Note.created_at.desc(),
                Note.id.desc(),
            )
        )
        for cand_id, content in (await db.execute(last_note_stmt)).all():
            if cand_id is None or not content:
                continue
            last_note_by_candidate[cand_id] = _format_note_preview(content)

        last_rejection_stmt = (
            select(
                CandidateStage.candidate_id,
                CandidateStage.notes,
                CandidateStage.rejection_note,
                RejectionReason.name.label("reason_name"),
                Job.title.label("job_title"),
                Client.name.label("client_name"),
            )
            .select_from(CandidateStage)
            .outerjoin(
                RejectionReason,
                RejectionReason.id == CandidateStage.rejection_reason_id,
            )
            .outerjoin(Job, Job.id == CandidateStage.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(
                CandidateStage.candidate_id.in_(candidate_ids),
                CandidateStage.stage == PipelineStage.rejected,
            )
            .distinct(CandidateStage.candidate_id)
            .order_by(
                CandidateStage.candidate_id,
                CandidateStage.moved_at.desc(),
                CandidateStage.id.desc(),
            )
        )
        for (
            cand_id,
            stage_notes,
            rejection_note,
            reason_name,
            job_title,
            client_name,
        ) in (await db.execute(last_rejection_stmt)).all():
            if cand_id is None:
                continue
            formatted = _format_rejection_reason(
                reason_name=reason_name,
                stage_notes=stage_notes,
                rejection_note=rejection_note,
                job_title=job_title,
                client_name=client_name,
            )
            if formatted:
                last_rejection_by_candidate[cand_id] = formatted

        last_rate_stmt = (
            select(
                CandidateStage.candidate_id,
                CandidateStage.expected_rate_value,
                CandidateStage.expected_rate_unit,
                CandidateStage.expected_rate_currency,
            )
            .where(
                CandidateStage.candidate_id.in_(candidate_ids),
                CandidateStage.expected_rate_value.is_not(None),
            )
            .distinct(CandidateStage.candidate_id)
            .order_by(
                CandidateStage.candidate_id,
                CandidateStage.moved_at.desc(),
                CandidateStage.id.desc(),
            )
        )
        for cand_id, value, unit, currency in (await db.execute(last_rate_stmt)).all():
            if cand_id is None or value is None:
                continue
            last_rate_by_candidate[cand_id] = _format_rate(value, unit, currency)

    # Snippet extraction (Phase: Traffit parity follow-up). Only computed
    # when the caller provided a positive search phrase — saves a notes
    # query for the common "browse all candidates" flow. Notes are batched
    # in a single IN-query so we don't N+1 across the page.
    from app.services.candidate_snippets import (
        extract_search_terms,
        extract_snippet,
    )

    search_terms = extract_search_terms(q, q_all, q_any, q_any_groups)
    notes_by_candidate: dict[int, list[str]] = {}
    if search_terms and items:
        notes_stmt = select(Note.candidate_id, Note.content).where(
            Note.candidate_id.in_([c.id for c in items])
        )
        for cid, content in (await db.execute(notes_stmt)).all():
            if cid is None or not content:
                continue
            notes_by_candidate.setdefault(cid, []).append(content)

    response_items: list[CandidateResponse] = []
    for cand in items:
        payload = _candidate_to_response(cand)
        # Strip eagerly-loaded snapshots from the list response — they are
        # only surfaced on the detail endpoint (trimmed to 5 there).
        payload = payload.model_copy(update={"linkedin_snapshots": None})
        stats = match_stats_by_candidate.get(cand.id)
        if stats is not None:
            payload = payload.model_copy(update={"match_stats": stats})
        if include_active_recruitments:
            payload = payload.model_copy(
                update={
                    "active_recruitments": active_recruitments_by_candidate.get(
                        cand.id, []
                    )
                }
            )
        if include_last_activity:
            payload = payload.model_copy(
                update={
                    "last_note_preview": last_note_by_candidate.get(cand.id),
                    "last_rejection_reason": last_rejection_by_candidate.get(cand.id),
                    "last_rate": last_rate_by_candidate.get(cand.id),
                }
            )
        if search_terms:
            snippet = extract_snippet(
                cand,
                search_terms,
                notes_contents=notes_by_candidate.get(cand.id),
            )
            if snippet:
                payload = payload.model_copy(update={"match_snippet": snippet})
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


# ── Autocomplete: job titles from candidate CV experience ───────────────────


class TitleSuggestion(BaseModel):
    """A job title extracted from any candidate's parsed CV experience."""

    name: str
    count: int


@router.get("/titles/suggest", response_model=list[TitleSuggestion])
async def suggest_titles(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(
        "",
        max_length=100,
        description="Substring to match (ILIKE). Empty = top-N overall.",
    ),
    limit: int = Query(20, ge=1, le=50),
):
    """Return top-N job titles aggregated from all candidates' `experience[].role`.

    Mirrors `/companies/suggest` for the `current_title` chip autocomplete.
    Groups by lowercased role — same MVP trade-off (collapses "Senior Engineer"
    / "senior engineer" to one suggestion).
    """
    pat = f"%{q.strip().lower()}%" if q.strip() else ""
    sql = text(
        "SELECT lower(elem->>'role') AS role, COUNT(DISTINCT c.id) AS n "
        "FROM candidates c, "
        "jsonb_array_elements("
        "CASE WHEN jsonb_typeof(c.experience) = 'array' "
        "THEN c.experience ELSE '[]'::jsonb END"
        ") AS elem "
        "WHERE elem ? 'role' "
        "AND elem->>'role' IS NOT NULL "
        "AND elem->>'role' <> '' "
        "AND (:pat = '' OR lower(elem->>'role') LIKE :pat) "
        "GROUP BY lower(elem->>'role') "
        "ORDER BY n DESC, role ASC "
        "LIMIT :lim"
    )
    result = await db.execute(sql, {"pat": pat, "lim": limit})
    return [TitleSuggestion(name=row[0], count=int(row[1])) for row in result]


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

    # Notify all managers/admins about new candidate (real-time).
    # "manager" was the legacy enum name; the live `userrole` enum has
    # `head_of_recruitment` (Olaf-type manager — see app/models/user.py).
    # Sending "manager" raised InvalidTextRepresentationError on every
    # POST /api/candidates (Sentry NEXUS-BE-1N, 9 events 2026-05-25).
    managers_result = await db.execute(
        select(User).where(
            User.is_active, User.role.in_(["admin", "head_of_recruitment"])
        )
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
    # Phase 7.6 — fire-and-forget Teams card to all subscribed channels.
    # `notify_teams` opens its own AsyncSession so the background task is safe
    # after the request session closes. Kill-switch off → notify_teams returns
    # 0 immediately without hitting the DB.
    try:
        from app.services.teams_notifications import (
            candidate_payload,
            notify_teams,
        )

        teams_db_payload = candidate_payload(
            candidate=candidate,
            recruiter_name=current_user.name or current_user.email,
        )
        asyncio.create_task(notify_teams("candidate_added", teams_db_payload))
    except Exception as exc:  # noqa: BLE001 — never block create on a notifier
        logger.warning("Teams notify (candidate_added) scheduling failed: %s", exc)

    # Reload with eager-loaded contracts/conflicts so _derive_employment has data.
    reloaded = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate.id)
    )
    full = reloaded.scalar_one()
    return _candidate_to_response(full)


# ── Chrome extension: POST /api/candidates/from-linkedin ────────────────────


_LINKEDIN_STALE_DAYS = 7


def _slug_from_linkedin_url(url: str) -> str:
    """Extract the slug ("jan-kowalski") from a canonical LinkedIn URL.

    Mirrors ``find_candidate_duplicates`` semantics so dedup is consistent.
    """
    stripped = (url or "").strip().rstrip("/")
    if not stripped:
        return ""
    return stripped.split("/")[-1].lower()


def _derive_names_from_preview(
    preview: Optional[object], normalized_url: str
) -> tuple[str, str]:
    """Pick name/lastname for the new candidate stub.

    Prefers the DOM-scraped preview when present; otherwise falls back to
    ``("LinkedIn", <slug>)`` so the row is identifiable until Proxycurl
    enrichment overwrites it within minutes.
    """
    name: Optional[str] = None
    lastname: Optional[str] = None
    if preview is not None:
        name = getattr(preview, "name", None)
        lastname = getattr(preview, "lastname", None)
    name = (name or "").strip()
    lastname = (lastname or "").strip()
    if not name and not lastname:
        slug = _slug_from_linkedin_url(normalized_url) or "Profile"
        return "LinkedIn", slug
    if not name:
        return "LinkedIn", lastname
    if not lastname:
        return name, _slug_from_linkedin_url(normalized_url) or "Unknown"
    return name, lastname


async def _enrich_linkedin_background(candidate_id: int) -> None:
    """Background task: open a fresh DB session and run Proxycurl enrichment.

    Wrapped in try/except so any Proxycurl failure (network, 503, rate limit)
    never propagates — the candidate is already persisted; the scheduled
    ``linkedin_sync_loop`` will retry on its next tick.
    """
    try:
        from app.core.database import AsyncSessionLocal as _SessionLocal
        from app.services.proxycurl import sync_candidate_linkedin as _sync

        async with _SessionLocal() as bg_db:
            candidate = await bg_db.scalar(
                select(Candidate).where(Candidate.id == candidate_id)
            )
            if candidate is None or not candidate.linkedin:
                return
            await _sync(bg_db, candidate)
    except Exception:  # noqa: BLE001 — defensive: BG task must never raise
        logger.exception(
            "Background LinkedIn enrichment failed for candidate %s", candidate_id
        )


async def _assign_candidate_to_job(
    *,
    db: AsyncSession,
    candidate_id: int,
    job_id: int,
    stage: PipelineStage,
    user_id: int,
) -> CandidateStage:
    """Light-weight pipeline assignment for the extension flow.

    Mirrors a small subset of ``app.api.pipeline.move_candidate`` — just enough
    to put a candidate on the kanban at the default ``new`` stage. NOT used
    for terminal stages, verification gating, or rate validation (those flow
    through the full pipeline endpoint).

    Raises ``HTTPException(404)`` if the job does not exist.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    stage_row = CandidateStage(
        candidate_id=candidate_id,
        job_id=job_id,
        stage=stage,
        moved_by=user_id,
    )
    db.add(stage_row)
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="assigned_to_job",
            user_id=user_id,
            details={"job_id": job_id, "stage": stage.value},
        )
    )
    return stage_row


def _is_sync_stale(
    synced_at: Optional[datetime], days: int = _LINKEDIN_STALE_DAYS
) -> bool:
    if synced_at is None:
        return True
    threshold = datetime.now(timezone.utc) - timedelta(days=days)
    # Tolerate naive datetimes coming back from the DB
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=timezone.utc)
    return synced_at < threshold


@router.post(
    "/from-linkedin",
    response_model=CandidateFromLinkedInResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": CandidateFromLinkedInResponse}},
)
async def create_candidate_from_linkedin(
    data: CandidateFromLinkedInCreate,
    current_user: RecruiterPlus,
    background_tasks: BackgroundTasks,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """One-click "Dodaj z LinkedIn" from the NEXUS Chrome extension.

    Flow:
    1. Normalize LinkedIn URL (reject company/jobs/invalid).
    2. Dedup against existing candidates via slug match.
       - If found → return ``action="existing"``; opcjonalnie przypisz do job;
         odpal resync gdy stary >7d.
    3. Otherwise create a stub (``name``/``lastname`` from preview or fallback),
       opcjonalnie przypisz do job (atomicznie), queue Proxycurl enrichment.
    """
    from app.services.proxycurl import normalize_linkedin_url

    normalized = normalize_linkedin_url(data.linkedin_url)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid LinkedIn profile URL. Expected a "
                "'linkedin.com/in/<slug>' profile link."
            ),
        )

    target_stage = data.stage or PipelineStage.new

    # ── Dedup fast-path ────────────────────────────────────────────────────
    duplicates = await find_candidate_duplicates(db, linkedin=normalized)
    if duplicates:
        match = duplicates[0]
        existing_id: int = match["candidate_id"]
        existing = await db.scalar(select(Candidate).where(Candidate.id == existing_id))
        assert existing is not None  # find_candidate_duplicates just returned it

        assigned_job: Optional[int] = None
        if data.job_id is not None:
            already = await db.scalar(
                select(CandidateStage).where(
                    CandidateStage.candidate_id == existing_id,
                    CandidateStage.job_id == data.job_id,
                )
            )
            if already is None:
                await _assign_candidate_to_job(
                    db=db,
                    candidate_id=existing_id,
                    job_id=data.job_id,
                    stage=target_stage,
                    user_id=current_user.id,
                )
            assigned_job = data.job_id

        resync = _is_sync_stale(existing.linkedin_synced_at)
        if resync:
            background_tasks.add_task(_enrich_linkedin_background, existing_id)

        await db.commit()

        response.status_code = status.HTTP_200_OK
        return CandidateFromLinkedInResponse(
            action="existing",
            candidate_id=existing_id,
            name=f"{existing.name} {existing.lastname}".strip(),
            linkedin_url=existing.linkedin or normalized,
            linkedin_sync_status=existing.linkedin_sync_status
            or LinkedinSyncStatus.disabled,
            assigned_to_job_id=assigned_job,
            profile_url_path=f"/candidates/{existing_id}",
            resync_scheduled=resync,
        )

    # ── Create stub ────────────────────────────────────────────────────────
    name, lastname = _derive_names_from_preview(data.preview, normalized)
    preview_location: Optional[str] = (
        data.preview.location if data.preview is not None else None
    )

    candidate = Candidate(
        name=name,
        lastname=lastname,
        linkedin=normalized,
        location=preview_location,
        source="linkedin_extension",
        created_by=current_user.id,
        tags=data.tags or None,
        ai_summary=data.notes,
    )
    db.add(candidate)
    await db.flush()

    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="created",
            user_id=current_user.id,
            details={
                "name": f"{candidate.name} {candidate.lastname}",
                "source": "linkedin_extension",
                "linkedin_url": normalized,
            },
        )
    )
    db.add(
        UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.candidate_added,
            entity_type="candidate",
            entity_id=candidate.id,
            details={
                "name": f"{candidate.name} {candidate.lastname}",
                "source": "linkedin_extension",
            },
        )
    )

    assigned_job_id: Optional[int] = None
    if data.job_id is not None:
        await _assign_candidate_to_job(
            db=db,
            candidate_id=candidate.id,
            job_id=data.job_id,
            stage=target_stage,
            user_id=current_user.id,
        )
        assigned_job_id = data.job_id

    await db.commit()
    await db.refresh(candidate)

    # Background enrichment — runs AFTER the response is returned to the client.
    background_tasks.add_task(_enrich_linkedin_background, candidate.id)

    return CandidateFromLinkedInResponse(
        action="created",
        candidate_id=candidate.id,
        name=f"{candidate.name} {candidate.lastname}".strip(),
        linkedin_url=normalized,
        linkedin_sync_status=candidate.linkedin_sync_status
        or LinkedinSyncStatus.disabled,
        assigned_to_job_id=assigned_job_id,
        profile_url_path=f"/candidates/{candidate.id}",
        resync_scheduled=False,
    )


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


# ── Outlook Add-in: existence lookup by email (Phase 7.4) ───────────────────
#
# IMPORTANT: This route MUST stay above ``@router.get("/{candidate_id}")``.
# FastAPI matches routes in declaration order; declaring it after the
# parametrised path makes "check-exists" hit the integer parser and return
# 422 ("unable to parse string as an integer"). Other static GET routes in
# this file (`/companies/suggest`, `/export`) follow the same pattern.


class CheckExistsResponse(BaseModel):
    """Compact existence card for the Outlook Add-in sidebar.

    Returned fields cover the only three things the add-in needs to render:
    yes/no, who is it, where is the profile. `current_stage` + `last_activity_at`
    are nullable because a candidate may exist without ever being placed on
    a pipeline (legacy import) and the activity log may be empty for
    bulk-imported rows.
    """

    found: bool
    candidate_id: Optional[int] = None
    candidate_name: Optional[str] = None
    profile_url: Optional[str] = None
    current_stage: Optional[str] = None
    last_activity_at: Optional[datetime] = None


@router.get("/check-exists", response_model=CheckExistsResponse)
@limiter.limit("60/minute")
async def check_exists(
    request: Request,
    current_user: CurrentUser,
    email: EmailStr = Query(..., description="Email do wyszukania (case-insensitive)"),
    db: AsyncSession = Depends(get_db),
):
    """Lookup candidate by email — designed for the Outlook Add-in sidebar.

    Case-insensitive match on ``Candidate.email``. Rate-limited (60/min/IP)
    because the add-in fires on every email selection in Outlook and a fast
    operator clicking through a flooded inbox can otherwise hammer the API.
    """
    email_lower = email.lower()
    candidate = await db.scalar(
        select(Candidate).where(func.lower(Candidate.email) == email_lower)
    )
    if candidate is None:
        return CheckExistsResponse(found=False)

    # Latest stage transition — drives the "currently in: <stage>" line on
    # the card. Order by `moved_at` desc and take 1; no filter on stage to
    # show terminal stages (hired / rejected / withdrawn) as well — they're
    # useful signal for the recruiter reading the inbox.
    latest_stage = await db.scalar(
        select(CandidateStage)
        .where(CandidateStage.candidate_id == candidate.id)
        .order_by(CandidateStage.moved_at.desc())
        .limit(1)
    )
    current_stage = latest_stage.stage.value if latest_stage else None

    # Last activity — prefer Activity log (audit trail of every CRUD on the
    # candidate), fall back to candidate.updated_at if the activity table is
    # empty for this row (bulk-imported pre-audit-log candidates).
    last_activity_at = await db.scalar(
        select(Activity.created_at)
        .where(
            Activity.entity_type == "candidate",
            Activity.entity_id == candidate.id,
        )
        .order_by(Activity.created_at.desc())
        .limit(1)
    )
    if last_activity_at is None:
        last_activity_at = candidate.updated_at

    profile_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/candidates/{candidate.id}"
    full_name = f"{candidate.name} {candidate.lastname}".strip()

    return CheckExistsResponse(
        found=True,
        candidate_id=candidate.id,
        candidate_name=full_name,
        profile_url=profile_url,
        current_stage=current_stage,
        last_activity_at=last_activity_at,
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

    # Stage changes — outerjoin User aby pokazać KTO przeniósł kandydata na etap
    # (analogicznie do `author_name` przy notatkach). `moved_by` bywa NULL dla
    # ruchów z importu Traffit, stąd outerjoin + Optional name.
    mover = aliased(User)
    stages_result = await db.execute(
        select(CandidateStage, Job.title, mover.name.label("moved_by_name"))
        .join(Job, CandidateStage.job_id == Job.id)
        .outerjoin(mover, mover.id == CandidateStage.moved_by)
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.moved_at.desc())
        .limit(limit)
    )
    for stage, job_title, moved_by_name in stages_result.all():
        timeline.append(
            {
                "type": "stage_change",
                "id": stage.id,
                "timestamp": stage.moved_at.isoformat() if stage.moved_at else None,
                "stage": stage.stage.value,
                "job_id": stage.job_id,
                "job_title": job_title,
                "moved_by": stage.moved_by,
                "moved_by_name": moved_by_name,
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
                # Stawki per rekrutacja — odczyt = ostatnia (najnowsza) niepusta
                # wartość w obrębie tej rekrutacji. `stages_result` jest
                # posortowany moved_at DESC, więc pierwszy napotkany non-null
                # to ten najświeższy. client_rate = cena wysłania do klienta
                # (sell), expected_rate = oczekiwania kandydata (kontekst marży).
                "client_rate": None,
                "expected_rate": None,
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
        if entry["client_rate"] is None and stage.client_rate_value is not None:
            entry["client_rate"] = {
                "value": float(stage.client_rate_value),
                "unit": stage.client_rate_unit,
                "currency": stage.client_rate_currency or "PLN",
            }
        if entry["expected_rate"] is None and stage.expected_rate_value is not None:
            entry["expected_rate"] = {
                "value": float(stage.expected_rate_value),
                "unit": stage.expected_rate_unit,
                "currency": stage.expected_rate_currency or "PLN",
            }
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


@router.patch("/{candidate_id}/recruitments/{job_id}/client-rate")
async def set_recruitment_client_rate(
    candidate_id: int,
    job_id: int,
    payload: ClientRateUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Ustaw/wyczyść „Stawkę do klienta" (cena wysłania kandydata do klienta)
    dla danej rekrutacji (candidate, job).

    PATCH /api/candidates/{candidate_id}/recruitments/{job_id}/client-rate

    Wartość zapisujemy na najnowszym `CandidateStage` tej rekrutacji; odczyt w
    `/history` bierze ostatnią niepustą wartość (analogicznie do expected_rate).
    `rate_value=None` czyści stawkę. Każdy ruch na nowy etap startuje z pustą
    stawką — wtedy wystarczy uzupełnić ją ponownie.
    """
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc())
        .limit(1)
    )
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail="Brak rekrutacji dla tego kandydata i tej oferty.",
        )

    if payload.rate_value is None:
        latest.client_rate_value = None
        latest.client_rate_unit = None
        latest.client_rate_currency = None
    else:
        latest.client_rate_value = payload.rate_value
        latest.client_rate_unit = (payload.rate_unit or RateUnit.monthly).value
        latest.client_rate_currency = (payload.rate_currency or "PLN")[:3].upper()

    await db.commit()
    await db.refresh(latest)

    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "client_rate": (
            {
                "value": float(latest.client_rate_value),
                "unit": latest.client_rate_unit,
                "currency": latest.client_rate_currency or "PLN",
            }
            if latest.client_rate_value is not None
            else None
        ),
    }


@router.delete("/{candidate_id}/recruitments/{job_id}")
async def remove_candidate_from_recruitment(
    candidate_id: int,
    job_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Usuń kandydata z rekrutacji (oferty) — kasuje całą jego obecność w
    pipeline tej oferty.

    DELETE /api/candidates/{candidate_id}/recruitments/{job_id}

    Kasuje WSZYSTKIE `CandidateStage` pary (candidate, job) — czyli audit trail
    przejść między etapami — a kaskadowo (DB ON DELETE CASCADE) także powiązane
    artefakty per-rekrutacja: snapshoty CV oryginalnego i brandowanego
    (`candidate_stage_cvs` → `cv_share_tokens`), share-tokeny karty Championa
    (`champion_card_share_tokens`) oraz zaplanowane maile odrzucenia
    (`scheduled_rejection_emails`).

    To operacja KOREKCYJNA („dodano nie tego kandydata / nie na tę ofertę"),
    odrębna od odrzucenia (`reject`) i wycofania (`withdrawn`), które zostawiają
    kandydata w pipeline na etapie końcowym dla audytu. Kandydata można później
    dodać do tej rekrutacji ponownie. Sam rekord kandydata oraz jego umowy
    (`Contract`) i screeningi (`screening_notes`, kluczowane po candidate+job)
    pozostają nietknięte.
    """
    stage_rows = (
        (
            await db.execute(
                select(CandidateStage).where(
                    CandidateStage.candidate_id == candidate_id,
                    CandidateStage.job_id == job_id,
                )
            )
        )
        .scalars()
        .all()
    )

    if not stage_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brak rekrutacji dla tego kandydata i tej oferty.",
        )

    job_title = await db.scalar(select(Job.title).where(Job.id == job_id))
    removed_stages = [s.stage.value for s in stage_rows]

    await db.execute(
        delete(CandidateStage).where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
    )

    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="removed_from_recruitment",
            user_id=current_user.id,
            details={
                "job_id": job_id,
                "job_title": job_title,
                "removed_stage_count": len(stage_rows),
                "removed_stages": removed_stages,
            },
        )
    )

    await db.commit()

    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "removed_stage_count": len(stage_rows),
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
    disposition: Literal["attachment", "inline"] = Query(
        "attachment",
        description=(
            "`attachment` (default) — browser zapisze plik. `inline` — render "
            "w nowej karcie (preview PDF/obrazu)."
        ),
    ),
):
    """Pobierz binary content pliku — StreamingResponse z proper
    Content-Type i Content-Disposition: attachment/inline.
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
    media_type = doc.content_type or "application/octet-stream"

    # Po migracji do Hetzner Object Storage (audit-2026-05-07 Faza 3): plik
    # leży w buckecie pod `storage_key`. PROXY MODE — backend pobiera bytes
    # z storage i streamuje do klienta. Nie używamy 302 redirect do presigned
    # URL bo:
    #   1. Bucket Hetzner nie ma skonfigurowanego CORS → `responseType: blob`
    #      cross-origin fail w przeglądarce.
    #   2. `window.open` na cross-origin URL po `await` jest blocked przez
    #      Chromium Site Isolation (silent ignore set-location).
    # Proxy przez backend = same-origin XHR z Bearer JWT, niezawodne.
    if doc.storage_key:
        from app.services.object_storage import download_cv, is_available

        if is_available():
            content = download_cv(doc.storage_key)
            return StreamingResponse(
                io.BytesIO(content),
                media_type=media_type,
                headers={
                    "Content-Disposition": content_disposition(filename, disposition),
                    "Content-Length": str(len(content)),
                },
            )
        # Storage env nie skonfigurowane — fallback do BYTEA jeśli jeszcze jest.

    # Legacy path: stream from postgres BYTEA. Po --finalize-delete-bytea
    # ta gałąź zwróci 404 dla zmigrowanych rekordów (file_content = NULL),
    # ale wtedy storage_key jest set i pierwsza gałąź obsługuje request.
    await db.refresh(doc, attribute_names=["file_content"])
    if not doc.file_content:
        raise HTTPException(status_code=404, detail="Document content not available")

    return StreamingResponse(
        io.BytesIO(doc.file_content),
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(filename, disposition),
            "Content-Length": str(len(doc.file_content)),
        },
    )


@router.get("/{candidate_id}/documents/{doc_id}/url")
async def get_candidate_document_url(
    candidate_id: int,
    doc_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    disposition: Literal["attachment", "inline"] = Query(
        "attachment",
        description=(
            "`attachment` (default) — browser zapisze plik. `inline` — render "
            "w nowej karcie (preview PDF/obrazu)."
        ),
    ),
):
    """Zwróć URL z którego klient może pobrać/zobaczyć plik.

    Dwa warianty zwracanej `kind`:
    - `presigned` — krótkoterminowy URL bezpośrednio do Hetzner Object Storage
      (5 min TTL). Klient otwiera w `window.open` lub `<a href download>`.
    - `proxy` — plik nadal w BYTEA postgresa, presigned URL nie istnieje.
      Klient musi pobrać przez `/content` endpoint (backend streamuje).

    Endpoint zaprojektowany żeby ominąć CORS preflight na Hetzner bucket
    (XHR + 302 cross-origin zwykle się wywala bo bucket nie ma `Access-
    Control-Allow-Origin: nexus.dynaminds.pl`). Top-level navigation z
    `window.open(url)` nie wymaga CORS.
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

    if doc.storage_key:
        from app.services.object_storage import (
            get_presigned_download_url,
            is_available,
        )

        if is_available():
            url = get_presigned_download_url(
                doc.storage_key, filename=filename, disposition=disposition
            )
            return {
                "kind": "presigned",
                "url": url,
                "filename": filename,
                "content_type": doc.content_type,
            }

    # BYTEA fallback (lub storage env nie skonfigurowane): klient musi
    # pobrać przez backend stream. Nie zwracamy bezpośredniego URL z BYTEA
    # bo to wymagałoby tokena w query (security hole). Klient użyje
    # `/content` endpoint z Authorization Bearer w nagłówku.
    return {
        "kind": "proxy",
        "filename": filename,
        "content_type": doc.content_type,
    }


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

    Security: validates size + MIME + extension, and strips path components
    from the supplied filename. Same checks as the public_share invite-link
    upload (`_validate_cv_file` in `public_share.py`).
    """
    import asyncio
    import pathlib

    from app.services import cv_text_extractor

    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Read content first so we can size-check before writing to disk.
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="CV file is empty")
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"CV file too large (max {settings.MAX_UPLOAD_SIZE_MB} MB)",
        )
    # MIME + extension allowlist (PDF / DOC / DOCX). Either signal is enough
    # — clients sometimes send empty content_type, but the extension check
    # catches the obvious cases.
    _allowed_mime = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    _allowed_ext = {".pdf", ".doc", ".docx"}
    raw_filename = file.filename or "upload.pdf"
    _, ext = os.path.splitext(raw_filename.lower())
    mime_ok = (file.content_type or "") in _allowed_mime
    ext_ok = ext in _allowed_ext
    if not (mime_ok or ext_ok):
        raise HTTPException(
            status_code=415,
            detail="Unsupported CV format. Use PDF, DOC, or DOCX.",
        )
    # Strip directory components — pathlib.Path(...).name returns just the
    # last segment, defeating `../../etc/passwd` and similar traversal.
    safe_filename = pathlib.Path(raw_filename).name

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(
        settings.UPLOAD_DIR, f"candidate_{candidate_id}_{safe_filename}"
    )
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # Phase D4: extract text from PDF/DOCX/TXT so the enrichment task has
    # something to work with. Heavy libraries run in a thread to keep the
    # event loop responsive.
    try:
        raw_text = await asyncio.to_thread(
            cv_text_extractor.extract_text, file_path, safe_filename
        )
        if raw_text:
            candidate.raw_cv_text = raw_text
    except cv_text_extractor.UnsupportedCvFormat as e:
        logger.info(f"[CV upload] unsupported format for {candidate_id}: {e}")
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            f"[CV upload] text extraction failed for candidate {candidate_id}: {e}"
        )

    # Persist the sanitized filename — read path (download_cv) reconstructs
    # `UPLOAD_DIR/candidate_<id>_<cv_filename>`, so any directory components
    # left in cv_filename would re-introduce traversal on read.
    candidate.cv_filename = safe_filename
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate_id,
        action="cv_uploaded",
        user_id=current_user.id,
        details={"filename": safe_filename},
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
