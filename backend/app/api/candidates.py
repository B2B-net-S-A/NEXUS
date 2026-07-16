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
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import (
    Text,
    and_,
    case,
    delete,
    false,
    func,
    literal,
    not_,
    or_,
    select,
    text,
)
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
from app.models.user import User, UserRole
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
from app.services.text_cleaning import clean_rich_text
from app.services.note_mention_render import (
    build_traffit_user_label_map,
    collect_traffit_user_ids,
    render_traffit_mentions,
)
from app.api.deps import RecruiterPlus, DeliveryLeadPlus
from app.api.candidate_access import (
    CandidateDocumentAccess,
    CandidateExportAccess,
    CandidateFinanceAccess,
    CandidatePIIAccess,
    CandidateSearchAccess,
    privacy_workflow_unavailable,
)
from app.api.financial_access import has_financial_access, redact_financial_fields
from app.api.recruitment_access import RecruitmentRateEditAccess
from app.services import candidate_audit
from app.api import ws as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _candidate_history_response_for_user(response: dict, current_user) -> dict:  # type: ignore[no-untyped-def]
    """Return history with rate fields absent for non-finance roles."""

    if has_financial_access(current_user):
        return response
    return redact_financial_fields(response)


class DuplicateCheckPayload(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    name: Optional[str] = None
    lastname: Optional[str] = None
    exclude_candidate_id: Optional[int] = None


class CandidateFilterSpec(BaseModel):
    """Canonical candidate filters shared by list and export endpoints."""

    status: Optional[list[CandidateStatus]] = None
    location: Optional[str] = None
    q: Optional[str] = None
    skills: Optional[list[str]] = None
    skill_combine: str = "and"
    skills_any: Optional[list[str]] = None
    skills_none: Optional[list[str]] = None
    remote_policy: Optional[list[Literal["remote", "hybrid", "onsite"]]] = None
    min_salary: Optional[int] = Field(None, ge=0)
    max_salary: Optional[int] = Field(None, ge=0)
    min_rate: Optional[int] = Field(None, ge=0)
    max_rate: Optional[int] = Field(None, ge=0)
    min_experience: Optional[int] = Field(None, ge=0, le=60)
    max_experience: Optional[int] = Field(None, ge=0, le=60)
    employment: Optional[list[str]] = None
    availability: Optional[list[AvailabilityStatus]] = None
    added_by_user_id: Optional[list[int]] = None
    talent_pool_id: Optional[list[int]] = None
    current_company: Optional[list[str]] = None
    past_company: Optional[list[str]] = None
    current_title: Optional[list[str]] = None
    worked_at_client_id: Optional[list[int]] = None
    recruitment_id: Optional[list[int]] = None
    recruitment_match: Literal["assigned", "not_assigned"] = "assigned"
    recently_changed_jobs: Optional[int] = Field(None, ge=1, le=3)
    open_to: Optional[list[str]] = None
    q_all: Optional[list[str]] = None
    q_any: Optional[list[str]] = None
    q_any_group: Optional[list[str]] = None
    q_none: Optional[list[str]] = None
    pipeline_stage: Optional[list[PipelineStage]] = None
    stage_category: Optional[list[StageCategory]] = None
    stage_current_only: Optional[bool] = None
    stage_moved_by: Optional[list[int]] = None
    stage_moved_after: Optional[date] = None
    stage_moved_before: Optional[date] = None
    stage_client_id: Optional[list[int]] = None
    competence_category_id: Optional[list[int]] = None
    sort: Literal["newest", "oldest", "name", "relevance"] = "newest"
    id_after: Optional[int] = Field(None, ge=1)
    updated_after: Optional[datetime] = None

    @field_validator("remote_policy", mode="before")
    @classmethod
    def coerce_legacy_remote_policy(cls, value):
        """Accept the old scalar form while keeping v2 filters multi-select."""
        if isinstance(value, str):
            return [value]
        return value


class CandidateExportRequest(BaseModel):
    format: Literal["csv", "xlsx"] = "csv"
    scope: Literal["filtered", "selected"]
    filters: CandidateFilterSpec = Field(default_factory=CandidateFilterSpec)
    candidate_ids: list[int] = Field(default_factory=list)
    limit: int = Field(100_000, ge=1, le=100_000)

    @field_validator("candidate_ids")
    @classmethod
    def deduplicate_and_limit_candidate_ids(cls, value: list[int]) -> list[int]:
        unique_ids = list(dict.fromkeys(value))
        if len(unique_ids) > 10_000:
            raise ValueError("candidate_ids may contain at most 10000 unique ids")
        return unique_ids


def _build_response(data: dict) -> dict:
    return {"success": True, "data": data}


# Cap on how many open jobs we score per candidate when populating match stats.
# Keeps worst-case latency bounded: page_size × _MATCH_STATS_JOB_CAP score computes.
_MATCH_STATS_JOB_CAP = 50
_MATCH_STATS_DEFAULT_THRESHOLD = 50.0


# Podgląd notatki w kolumnie „Ostatnia notatka" na liście kandydatów. Kolumna
# renderuje 3 linie (compact) / 4 (cozy) w wierszu o stałej wysokości — przy
# ~45 znakach na linię 120 znaków starczało ledwie na 2 linie i marnowało miejsce
# pod notatką. Podnosimy cap, by zapełnić dostępny wiersz; pełna treść w profilu.
_NOTE_PREVIEW_MAX_CHARS = 220
# Powód odrzucenia pokazujemy w pełniejszej formie niż zwykłą notatkę — rekruter
# chce widzieć CAŁĄ treść powodu od razu w kolumnie (nie tylko 120 znaków). Realne
# wartości to krótkie kategorie ("Po CV", "Rezygnacja przez Kandydata", max ~37 zn.),
# ten cap jest tylko bezpiecznikiem na patologiczny free-text z natywnego flow.
_REJECTION_REASON_MAX_CHARS = 400
_RATE_UNIT_SHORT = {"hourly": "/h", "daily": "/d", "monthly": "/mc"}


def _format_note_preview(raw: str, max_chars: int = _NOTE_PREVIEW_MAX_CHARS) -> str:
    """Flatten a note to clean plain text + truncate. Notatki w NEXUS są
    zapisywane przez Tiptap editor — czasem jako HTML (legacy z Word/Outlook
    paste), czasem jako serializowany JSON document. Podgląd w liście kandydatów
    ma być czystym tekstem (patrz `clean_rich_text`). `max_chars` pozwala podnieść
    cap dla powodu odrzucenia (chcemy pełną treść, nie 120-znakowy podgląd).
    """
    text_only = clean_rich_text(raw)
    if len(text_only) <= max_chars:
        return text_only
    return text_only[: max_chars - 1].rstrip() + "…"


def _format_rejection_reason(
    *,
    reason_name: Optional[str],
    stage_notes: Optional[str],
    rejection_note: Optional[str],
) -> Optional[str]:
    """Zwróć powód odrzucenia: kategorię + notatkę rekrutera od razu w kolumnie.

    Dwa rozłączne sygnały na etapie `rejected`:
    - **Kategoria** (suchy bucket — KIEDY/jak odrzucono): `rejection_reason.name`
      (FK z pipeline_template przy odrzuceniu w NEXUS, np. "Po CV",
      "Brak kwalifikacji") albo — dla historycznego importu z Traffita —
      `CandidateStage.rejection_note` (tam backfill zapisuje samą nazwę kategorii).
    - **Notatka rekrutera** (DLACZEGO — wolny tekst): `CandidateStage.notes`.
      W NEXUS to pole "Notatka" z modala odrzucenia; dla importu z Traffita to
      `content.description` z aktywności "Zmiana etapu" (backfill go tam wpisuje,
      patrz `traffit/rejection_backfill.py`).

    Decyzja produktowa 2026-06-10: rekruter chce widzieć WŁAŚNIE swoją notatkę
    (np. "kandydat nie jest zainteresowany tą ofertą"), nie tylko suchy bucket.
    Gdy są oba → "Kategoria — notatka". Gdy jest tylko jedno → pokazujemy to.
    Świadomie NIE doklejamy " · job (client)" — kontekst projektu jest w kolumnie
    "Rekrutacje".
    """
    category = (reason_name or "").strip() or (rejection_note or "").strip()
    note_raw = (stage_notes or "").strip()
    note = (
        _format_note_preview(note_raw, max_chars=_REJECTION_REASON_MAX_CHARS)
        if note_raw
        else ""
    )
    # Notatka, która tylko powtarza kategorię (np. recruiter wpisał "Po CV" w
    # wolny tekst), nie wnosi nic — nie duplikuj.
    if note and category and note.casefold() == category.casefold():
        note = ""
    if category and note:
        return f"{category} — {note}"
    return category or note or "Odrzucony"


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


async def _build_candidate_filtered_query(
    db: AsyncSession,
    filters: CandidateFilterSpec,
    *,
    load_list_relations: bool = False,
):
    """Build the canonical candidate query used by list and filtered export.

    The returned OR-groups are also consumed by relevance ordering and list
    snippets, keeping parsing identical across both callers.
    """
    f = filters
    query = select(Candidate)
    if load_list_relations:
        query = query.options(*_candidate_list_options())

    if f.id_after:
        query = query.where(Candidate.id > f.id_after)
    if f.updated_after:
        query = query.where(Candidate.updated_at > f.updated_after)
    if f.status:
        query = query.where(Candidate.status.in_(f.status))
    if f.employment:
        invalid = [e for e in f.employment if e not in {"at_client", "available"}]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid employment values: {invalid}. "
                    "Allowed: 'at_client', 'available'."
                ),
            )
        emp_set = set(f.employment)
        if emp_set == {"at_client"}:
            query = query.where(_at_client_predicate())
        elif emp_set == {"available"}:
            query = query.where(not_(_at_client_predicate()))
    if f.availability:
        query = query.where(Candidate.availability_status.in_(f.availability))
    if f.open_to:
        open_to_fields = {
            "side_projects": Candidate.open_to_side_projects,
            "sales_support": Candidate.open_to_sales_support,
            "expert_consult": Candidate.open_to_expert_consult,
        }
        invalid = [value for value in f.open_to if value not in open_to_fields]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid open_to values: {invalid}. "
                    f"Allowed: {sorted(open_to_fields)}."
                ),
            )
        query = query.where(
            or_(*[open_to_fields[value].is_(True) for value in set(f.open_to)])
        )
    if f.location:
        query = query.where(Candidate.location.ilike(f"%{f.location}%"))
    if f.competence_category_id:
        # Match candidates carrying any of the selected competence categories —
        # as PRIMARY or SECONDARY (the M2M), OR via the legacy single FK for
        # profiles not yet backfilled into the M2M. The two stay in sync.
        from app.models.competence_category import CandidateCompetenceCategory

        query = query.where(
            or_(
                Candidate.competence_category_id.in_(f.competence_category_id),
                Candidate.id.in_(
                    select(CandidateCompetenceCategory.candidate_id).where(
                        CandidateCompetenceCategory.competence_category_id.in_(
                            f.competence_category_id
                        )
                    )
                ),
            )
        )

    from app.services.advanced_candidate_search import (
        build_advanced_filter,
        single_phrase_filter,
    )

    if f.q:
        q_stripped = f.q.strip()
        use_fuzzy = len(q_stripped) >= 3
        if use_fuzzy:
            trigram_threshold = 0.5 if " " in q_stripped else 0.2
            await db.execute(
                text(f"SET LOCAL pg_trgm.similarity_threshold = {trigram_threshold}")
            )
        phrase_clause = single_phrase_filter(q_stripped, fuzzy=use_fuzzy)
        if phrase_clause is not None:
            query = query.where(phrase_clause)

    q_any_groups = (
        [group.split("|") for group in f.q_any_group] if f.q_any_group else None
    )
    advanced = build_advanced_filter(f.q_all, f.q_any, f.q_none, q_any_groups)
    if advanced is not None:
        query = query.where(advanced)

    if f.skills or f.skills_any or f.skills_none:
        from app.services.scoring_service import canonical_skill_names

        def skill_predicate(skill: str):
            pattern = f"%{skill.lower()}%"
            return or_(
                func.lower(func.coalesce(Candidate.skills.cast(Text), "")).like(
                    pattern
                ),
                func.lower(func.coalesce(Candidate.verified_tech.cast(Text), "")).like(
                    pattern
                ),
                func.lower(func.coalesce(Candidate.tags.cast(Text), "")).like(pattern),
            )

        def skill_group(names: list[str]):
            wanted = [s for s in (canonical_skill_names(names) or []) if s]
            return or_(*[skill_predicate(s) for s in wanted]) if wanted else None

        if f.skills:
            wanted = [s for s in (canonical_skill_names(f.skills) or []) if s]
            if wanted:
                clauses = [skill_predicate(s) for s in wanted]
                combiner = or_ if f.skill_combine.strip().lower() == "or" else and_
                query = query.where(combiner(*clauses))
        if f.skills_any:
            for raw_group in f.skills_any:
                clause = skill_group(raw_group.split("|"))
                if clause is not None:
                    query = query.where(clause)
        if f.skills_none:
            for raw_group in f.skills_none:
                clause = skill_group(raw_group.split("|"))
                if clause is not None:
                    query = query.where(not_(clause))

    if f.remote_policy:
        query = query.where(
            or_(
                *[
                    Candidate.preferences.op("@>")(
                        func.jsonb_build_object(
                            "remote_modes", func.jsonb_build_array(mode)
                        )
                    )
                    for mode in set(f.remote_policy)
                ]
            )
        )
    if f.min_salary is not None:
        query = query.where(Candidate.salary_expectation >= f.min_salary)
    if f.max_salary is not None:
        query = query.where(Candidate.salary_expectation <= f.max_salary)
    if f.min_rate is not None:
        query = query.where(Candidate.expected_rate_hourly >= f.min_rate)
    if f.max_rate is not None:
        query = query.where(Candidate.expected_rate_hourly <= f.max_rate)

    if f.min_experience is not None or f.max_experience is not None:
        traffit_exp = Candidate.cv_extracted_data.op("->>")("traffit_experience")
        exp_lo = case(
            (Candidate.years_it_experience.is_not(None), Candidate.years_it_experience),
            (traffit_exp == "Poniżej 2", literal(0)),
            (traffit_exp == "2-5", literal(2)),
            (traffit_exp == "5+", literal(5)),
            else_=None,
        )
        exp_hi = case(
            (Candidate.years_it_experience.is_not(None), Candidate.years_it_experience),
            (traffit_exp == "Poniżej 2", literal(1)),
            (traffit_exp == "2-5", literal(5)),
            (traffit_exp == "5+", literal(60)),
            else_=None,
        )
        if f.min_experience is not None:
            query = query.where(exp_hi >= f.min_experience)
        if f.max_experience is not None:
            query = query.where(exp_lo <= f.max_experience)

    if f.added_by_user_id:
        real_ids = [uid for uid in f.added_by_user_id if uid != 0]
        include_null = 0 in f.added_by_user_id
        if include_null and real_ids:
            query = query.where(
                or_(Candidate.created_by.is_(None), Candidate.created_by.in_(real_ids))
            )
        elif include_null:
            query = query.where(Candidate.created_by.is_(None))
        elif real_ids:
            query = query.where(Candidate.created_by.in_(real_ids))

    if f.talent_pool_id:
        pool_exists = (
            select(1)
            .where(
                and_(
                    TalentPoolMembership.candidate_id == Candidate.id,
                    TalentPoolMembership.talent_pool_id.in_(f.talent_pool_id),
                )
            )
            .exists()
        )
        query = query.where(pool_exists)
    if f.current_company:
        query = query.where(_current_company_predicate(f.current_company))
    if f.past_company:
        query = query.where(_past_company_predicate(f.past_company))
    if f.current_title:
        query = query.where(_current_title_predicate(f.current_title))
    if f.worked_at_client_id:
        query = query.where(_worked_at_client_predicate(f.worked_at_client_id))
    if f.recruitment_id:
        in_recruitment = (
            select(1)
            .where(
                and_(
                    CandidateStage.candidate_id == Candidate.id,
                    CandidateStage.job_id.in_(f.recruitment_id),
                )
            )
            .exists()
        )
        query = query.where(
            ~in_recruitment if f.recruitment_match == "not_assigned" else in_recruitment
        )
    if f.recently_changed_jobs in (1, 2, 3):
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=30 * f.recently_changed_jobs
        )
        query = query.where(Candidate.linkedin_employment_changed_at >= cutoff)

    requested_stages: set[PipelineStage] = set(f.pipeline_stage or [])
    if f.stage_category:
        categories = set(f.stage_category)
        requested_stages.update(
            stage
            for stage, category in STAGE_CATEGORY.items()
            if category in categories
        )

    moved_after_dt = (
        datetime.combine(f.stage_moved_after, datetime.min.time(), tzinfo=timezone.utc)
        if f.stage_moved_after
        else None
    )
    moved_before_dt = (
        datetime.combine(
            f.stage_moved_before + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        if f.stage_moved_before
        else None
    )

    def move_predicates(moved_by_col, moved_at_col, job_id_col) -> list:
        predicates: list = []
        if f.stage_moved_by:
            real_ids = [uid for uid in f.stage_moved_by if uid != 0]
            include_null = 0 in f.stage_moved_by
            if include_null and real_ids:
                predicates.append(
                    or_(moved_by_col.is_(None), moved_by_col.in_(real_ids))
                )
            elif include_null:
                predicates.append(moved_by_col.is_(None))
            elif real_ids:
                predicates.append(moved_by_col.in_(real_ids))
        if moved_after_dt is not None:
            predicates.append(moved_at_col >= moved_after_dt)
        if moved_before_dt is not None:
            predicates.append(moved_at_col < moved_before_dt)
        if f.stage_client_id:
            predicates.append(
                select(1)
                .select_from(Job)
                .where(Job.id == job_id_col, Job.client_id.in_(f.stage_client_id))
                .exists()
            )
        return predicates

    has_move_filter = bool(
        f.stage_moved_by
        or moved_after_dt is not None
        or moved_before_dt is not None
        or f.stage_client_id
    )
    effective_current_only = (
        not has_move_filter if f.stage_current_only is None else f.stage_current_only
    )
    if requested_stages or has_move_filter:
        stage_values = list(requested_stages)
        if effective_current_only and stage_values:
            latest_per_pair = (
                select(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
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
            conditions = [
                latest_per_pair.c.candidate_id == Candidate.id,
                latest_per_pair.c.stage.in_(stage_values),
            ]
            conditions.extend(
                move_predicates(
                    latest_per_pair.c.moved_by,
                    latest_per_pair.c.moved_at,
                    latest_per_pair.c.job_id,
                )
            )
            stage_exists = (
                select(1).select_from(latest_per_pair).where(*conditions).exists()
            )
        else:
            conditions = [CandidateStage.candidate_id == Candidate.id]
            if stage_values:
                conditions.append(CandidateStage.stage.in_(stage_values))
            conditions.extend(
                move_predicates(
                    CandidateStage.moved_by,
                    CandidateStage.moved_at,
                    CandidateStage.job_id,
                )
            )
            stage_exists = select(1).where(*conditions).exists()
        query = query.where(stage_exists)

    return query, q_any_groups


def _apply_candidate_sort(query, filters: CandidateFilterSpec, q_any_groups):
    if filters.sort == "oldest":
        return query.order_by(Candidate.created_at.asc(), Candidate.id.asc())
    if filters.sort == "name":
        return query.order_by(
            Candidate.name.asc(), Candidate.lastname.asc(), Candidate.id.asc()
        )
    if filters.sort == "relevance":
        terms: list[str] = []
        if filters.q:
            terms.append(filters.q.strip())
        for bucket in (filters.q_all, filters.q_any):
            if bucket:
                terms.extend(value.strip() for value in bucket if value.strip())
        if q_any_groups:
            for group in q_any_groups:
                terms.extend(value.strip() for value in group if value.strip())
        if terms:
            haystack = (
                func.coalesce(Candidate.name, "")
                + " "
                + func.coalesce(Candidate.lastname, "")
                + " "
                + func.coalesce(Candidate.email, "")
            )
            score = sum(func.similarity(haystack, term) for term in terms)
            return query.order_by(
                score.desc(), Candidate.created_at.desc(), Candidate.id.desc()
            )
    return query.order_by(Candidate.created_at.desc(), Candidate.id.desc())


@router.get("", response_model=CandidateList)
async def list_candidates(
    current_user: CandidateSearchAccess,
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
        description=(
            "How to combine multiple `skills` filters — 'and' or 'or' "
            "(case-insensitive; anything other than 'or' is treated as 'and')."
        ),
    ),
    skills_any: Optional[list[str]] = Query(
        None,
        description=(
            "Skill OR-groups. Repeat the param; each value is a pipe-joined group "
            "of skills OR'd together, and the groups AND with each other and with "
            "`skills`/`skills_none` — e.g. `?skills_any=python|java&skills_any=aws|gcp` "
            "means `(python OR java) AND (aws OR gcp)`. Skill-scoped (skills / "
            "verified_tech / tags), same as `skills`."
        ),
    ),
    skills_none: Optional[list[str]] = Query(
        None,
        description=(
            "Skills to EXCLUDE (NOT). Repeat the param — a candidate is dropped if "
            "ANY listed skill is present. Skill-scoped, same fields as `skills`."
        ),
    ),
    remote_policy: Optional[list[Literal["remote", "hybrid", "onsite"]]] = Query(
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
    min_rate: Optional[int] = Query(
        None,
        ge=0,
        description=(
            "Minimum expected hourly rate (B2B, PLN/h) — matches "
            "`expected_rate_hourly`. Exclusive of nulls, like salary."
        ),
    ),
    max_rate: Optional[int] = Query(
        None,
        ge=0,
        description=("Maximum expected hourly rate (B2B, PLN/h) — see `min_rate`."),
    ),
    min_experience: Optional[int] = Query(
        None,
        ge=0,
        le=60,
        description=(
            "Minimum years of IT experience. Matches against a per-candidate "
            "experience interval: the exact `years_it_experience` when present, "
            "else the Traffit bucket (`Poniżej 2`→0-1, `2-5`→2-5, `5+`→5-60). "
            "Range-overlap semantics — a candidate matches when their interval "
            "overlaps [min, max]. Candidates with no experience signal are "
            "excluded (exclusive of nulls, like salary)."
        ),
    ),
    max_experience: Optional[int] = Query(
        None,
        ge=0,
        le=60,
        description="Maximum years of IT experience — see `min_experience`.",
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
            "When true, each candidate gets `active_recruitments` — every "
            "recruitment the candidate appears in (latest stage per job, "
            "including terminal rejected/withdrawn/hired; front differentiates "
            "by stage badge). One aggregated SQL per page (DISTINCT ON "
            "candidate_id, job_id, ordered by moved_at DESC) + JOIN Job + "
            "Client. No N+1."
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
    recruitment_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by assignment to specific recruitments (job ids). Repeat the "
            "param for multi-select (e.g. `?recruitment_id=3&recruitment_id=7`). "
            "OR-combined and interpreted via `recruitment_match`: `assigned` "
            "(default) keeps candidates in the pipeline of ANY of these jobs; "
            "`not_assigned` keeps candidates in NONE of them. A candidate counts "
            "as assigned when they have any `candidate_stages` row for the job "
            "(any stage, including terminal) — mirrors talent-pool membership."
        ),
    ),
    recruitment_match: str = Query(
        "assigned",
        pattern="^(assigned|not_assigned)$",
        description=(
            "Direction for `recruitment_id`: `assigned` (in the pipeline of any "
            "selected recruitment) or `not_assigned` (in none of them). Ignored "
            "when `recruitment_id` is empty."
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
            "who/when/client move-filter (`stage_moved_by` / `stage_moved_after` "
            "/ `stage_moved_before` / `stage_client_id`) is present the query "
            "becomes HISTORICAL — "
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
    stage_client_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by the CLIENT that owns the job on which the matched stage "
            "move happened (`Job.client_id` via `CandidateStage.job_id`) — one "
            "or more client ids, OR-combined. Correlated with "
            "`pipeline_stage`/`stage_moved_by`/`stage_moved_after`/"
            "`stage_moved_before` on the SAME move: e.g. "
            "`pipeline_stage=verified&stage_client_id=12` matches candidates "
            "moved onto Verified on one of client 12's jobs. Like the other "
            "who/when move-filters, its presence switches matching to HISTORICAL "
            "by default (any qualifying move counts even if the candidate has "
            "since progressed); pass `stage_current_only=true` to restrict to "
            "the candidate's CURRENT move per job-pair instead."
        ),
    ),
    competence_category_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by competence category — one or more CC ids, OR-combined "
            "(repeat the param). A candidate matches when the category is their "
            "PRIMARY or a SECONDARY assignment. Ids come from "
            "`GET /api/competence-categories`."
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
    id_after: Optional[int] = Query(
        None,
        ge=1,
        description=(
            "Only candidates with `id` greater than this value. PK watermark "
            "used by the saved-search alert scanner ('new since last check') — "
            "cuts the scanned set down to the few newest rows before any other "
            "filter (incl. free-text) runs."
        ),
    ),
    updated_after: Optional[datetime] = Query(
        None,
        description=(
            "Only candidates whose `updated_at` is strictly greater than this "
            "ISO-8601 timestamp. Used by the saved-search alert scanner to find "
            "EXISTING candidates that newly match after an edit (CV / skill / "
            "status), not just brand-new rows. Backed by ix_candidates_updated_at."
        ),
    ),
):
    filters = CandidateFilterSpec(
        status=status,
        location=location,
        q=q,
        skills=skills,
        skill_combine=skill_combine,
        skills_any=skills_any,
        skills_none=skills_none,
        remote_policy=remote_policy,
        min_salary=min_salary,
        max_salary=max_salary,
        min_rate=min_rate,
        max_rate=max_rate,
        min_experience=min_experience,
        max_experience=max_experience,
        employment=employment,
        availability=availability,
        added_by_user_id=added_by_user_id,
        talent_pool_id=talent_pool_id,
        current_company=current_company,
        past_company=past_company,
        current_title=current_title,
        worked_at_client_id=worked_at_client_id,
        recruitment_id=recruitment_id,
        recruitment_match=recruitment_match,
        recently_changed_jobs=recently_changed_jobs,
        open_to=open_to,
        q_all=q_all,
        q_any=q_any,
        q_any_group=q_any_group,
        q_none=q_none,
        pipeline_stage=pipeline_stage,
        stage_category=stage_category,
        stage_current_only=stage_current_only,
        stage_moved_by=stage_moved_by,
        stage_moved_after=stage_moved_after,
        stage_moved_before=stage_moved_before,
        stage_client_id=stage_client_id,
        competence_category_id=competence_category_id,
        sort=sort,
        id_after=id_after,
        updated_after=updated_after,
    )
    query, q_any_groups = await _build_candidate_filtered_query(
        db, filters, load_list_relations=True
    )
    query = _apply_candidate_sort(query, filters, q_any_groups)
    query = query.offset((page - 1) * page_size).limit(page_size)
    # Single pass: `count(*) OVER()` carries the full (pre-LIMIT) filtered total
    # on every returned row, so the search filter executes once for both the
    # page and the count. No partition/order in the window → it counts the whole
    # filtered set, matching the previous `count(query.subquery())` exactly (the
    # base query has no row-fanning joins — all relations are selectinload'd).
    # Empty result → no rows → total 0.
    result = await db.execute(
        query.add_columns(func.count().over().label("total_count"))
    )
    rows = result.all()
    items = [row[0] for row in rows]
    total = rows[0].total_count if rows else 0

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

    # Recruitments aggregation (WSZYSTKIE etapy — też terminalne). One SQL per
    # page: DISTINCT ON (candidate_id, job_id) ORDER BY moved_at DESC, id DESC →
    # najnowszy ruch per parę + JOIN Job + Client. Pokazujemy każdą rekrutację,
    # w której kandydat się pojawił (również rejected/withdrawn/hired) — front
    # różnicuje status badge'em. Wcześniej kolumna ukrywała terminalne etapy, więc
    # odrzucony/zatrudniony kandydat znikał z listy mimo bycia w pipeline. Lista
    # bezpieczna dla response — żadnych szczegółów scorecard/rate'ów.
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
            )
            .select_from(CandidateStage)
            .outerjoin(
                RejectionReason,
                RejectionReason.id == CandidateStage.rejection_reason_id,
            )
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
        ) in (await db.execute(last_rejection_stmt)).all():
            if cand_id is None:
                continue
            formatted = _format_rejection_reason(
                reason_name=reason_name,
                stage_notes=stage_notes,
                rejection_note=rejection_note,
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
    current_user: CandidateSearchAccess,
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
    current_user: CandidateSearchAccess,
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
    "expected_rate_hourly",
    "expected_rate_currency",
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
        c.expected_rate_hourly if c.expected_rate_hourly is not None else "",
        c.expected_rate_currency or "",
        c.availability_date.isoformat() if c.availability_date else "",
        "true" if c.champion else "false",
        c.created_at.isoformat() if c.created_at else "",
    ]


@router.get("/export")
async def export_candidates(
    current_user: CandidateExportAccess,
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

    # Immutable audit — no PII (filters carried as booleans, not values).
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.EXPORT_REQUESTED,
        user_id=current_user.id,
        details={
            "endpoint": "GET /api/candidates/export",
            "format": format,
            "row_count": len(rows),
            "limit": limit,
            "filtered_by_status": status_ is not None,
            "filtered_by_query": bool(q),
            "filtered_by_location": bool(location),
        },
    )
    await db.commit()

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


async def _stream_candidate_csv(db: AsyncSession, query):
    """Yield bounded CSV chunks while candidates are streamed from Postgres."""
    import csv
    from io import StringIO

    buffer = StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(_EXPORT_COLUMNS)
    stream = await db.stream_scalars(query.execution_options(yield_per=500))
    async for candidate in stream:
        writer.writerow(_row_for_export(candidate))
        if buffer.tell() >= 64 * 1024:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    if buffer.tell():
        yield buffer.getvalue()


async def _candidate_xlsx(db: AsyncSession, query) -> io.BytesIO:
    """Build an XLSX with openpyxl's constant-memory write-only worksheets."""
    from openpyxl import Workbook

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(title="Candidates")
    sheet.append(_EXPORT_COLUMNS)
    stream = await db.stream_scalars(query.execution_options(yield_per=500))
    async for candidate in stream:
        sheet.append(_row_for_export(candidate))

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


@router.post("/export")
async def export_candidates_v2(
    payload: CandidateExportRequest,
    current_user: CandidateExportAccess,
    db: AsyncSession = Depends(get_db),
):
    """Export an exact selection or the canonical filtered candidate set."""
    unique_ids = list(dict.fromkeys(payload.candidate_ids))
    if any(candidate_id <= 0 for candidate_id in unique_ids):
        raise HTTPException(
            status_code=422,
            detail="candidate_ids must contain positive integers",
        )

    if payload.scope == "selected":
        if not unique_ids:
            raise HTTPException(
                status_code=422,
                detail="scope='selected' requires at least one candidate_id",
            )
        found_count = int(
            await db.scalar(
                select(func.count(Candidate.id)).where(Candidate.id.in_(unique_ids))
            )
            or 0
        )
        if found_count != len(unique_ids):
            raise HTTPException(
                status_code=422,
                detail="One or more selected candidate_ids do not exist",
            )
        query = (
            select(Candidate)
            .where(Candidate.id.in_(unique_ids))
            .order_by(Candidate.id.asc())
        )
    else:
        if unique_ids:
            raise HTTPException(
                status_code=422,
                detail="scope='filtered' does not accept candidate_ids",
            )
        query, q_any_groups = await _build_candidate_filtered_query(db, payload.filters)
        total_query = select(func.count()).select_from(query.order_by(None).subquery())
        total = int(await db.scalar(total_query) or 0)
        if total > payload.limit:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Export contains {total} candidates, exceeding limit "
                    f"{payload.limit}. Narrow the filters or raise the limit."
                ),
            )
        query = _apply_candidate_sort(query, payload.filters, q_any_groups)

    # Immutable audit — scope + format only, no PII / filter values.
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.EXPORT_REQUESTED,
        user_id=current_user.id,
        details={
            "endpoint": "POST /api/candidates/export",
            "format": payload.format,
            "scope": payload.scope,
            "selected_count": len(unique_ids),
            "limit": payload.limit,
        },
    )
    await db.commit()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    extension = payload.format
    filename = f"candidates_{timestamp}.{extension}"
    headers = {"Content-Disposition": content_disposition(filename)}

    if payload.format == "xlsx":
        return StreamingResponse(
            await _candidate_xlsx(db, query),
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers=headers,
        )

    return StreamingResponse(
        _stream_candidate_csv(db, query),
        media_type="text/csv; charset=utf-8",
        headers=headers,
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
    current_user: CandidateSearchAccess,
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
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
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
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
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


# Legacy `activities` actions z importu Traffita, które DUPLIKUJĄ realne wpisy
# timeline (a same nie niosą czytelnej etykiety ani dodatkowego contentu), więc
# w feedzie kandydata są tylko szumem. Filtrujemy je na poziomie zapytania —
# dodatkowo nie pozwala im wypychać użytecznych aktywności spod `limit`.
#   - `traffit:Zmiana etapu` (170k) duplikuje wpisy `stage_change` (PR #416)
#   - `traffit:Notatka`      (40k)  duplikuje realne wpisy `Note` ("Notatka — …")
# Pozostałe `traffit:*` (Tag-dodany, Plik-dodany, Email, …) niosą content —
# ich NIE ukrywamy. `activities.action` jest NOT NULL → notin_ bezpieczne.
_HIDDEN_TIMELINE_ACTIONS = ("traffit:Zmiana etapu", "traffit:Notatka")


@router.get("/{candidate_id}/timeline")
async def get_candidate_timeline(
    candidate_id: int,
    current_user: CandidatePIIAccess,
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
    # outerjoin Job aby pokazać do której rekrutacji notatka jest przypięta
    # (job_id bywa NULL dla notatek "ogólnych" — stąd outerjoin + Optional title).
    notes_result = await db.execute(
        select(
            Note,
            User.name.label("author_name"),
            User.email.label("author_email"),
            Job.title.label("job_title"),
        )
        .outerjoin(User, Note.author_id == User.id)
        .outerjoin(Job, Note.job_id == Job.id)
        .where(Note.candidate_id == candidate_id)
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    notes_rows = notes_result.all()
    # Legacy Traffit notes embed @mentions as `$$user_NN$$` markers (NN = Traffit
    # user id). Resolve them to "@Imię Nazwisko" for display via users.external_id,
    # in a separate `content_rendered` field — raw `content` stays intact so
    # editing preserves the original token/HTML wrapper.
    mention_label_map = await build_traffit_user_label_map(
        db, collect_traffit_user_ids(note.content for note, *_ in notes_rows)
    )
    for note, author_name, author_email, job_title in notes_rows:
        timeline.append(
            {
                "type": "note",
                "id": note.id,
                "timestamp": note.created_at.isoformat() if note.created_at else None,
                "note_type": note.note_type.value if note.note_type else None,
                "content": note.content,
                "content_rendered": render_traffit_mentions(
                    note.content, mention_label_map
                ),
                "author_id": note.author_id,
                "author_name": author_name,
                "author_email": author_email,
                "job_id": note.job_id,
                "job_title": job_title,
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
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
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
    #
    # Pomijamy legacy szum z importu Traffita (patrz `_HIDDEN_TIMELINE_ACTIONS`):
    # `traffit:Zmiana etapu` duplikuje wpisy `stage_change`, a `traffit:Notatka`
    # duplikuje realne wpisy `Note` powyżej — w UI renderowały się jako gołe
    # etykiety "traffit:…" bez własnego contentu, więc tylko zaśmiecały feed.
    activities_result = await db.execute(
        select(Activity)
        .where(
            Activity.entity_type == "candidate",
            Activity.entity_id == candidate_id,
            Activity.action.notin_(_HIDDEN_TIMELINE_ACTIONS),
        )
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
    current_user: CandidatePIIAccess,
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
        select(
            CandidateStage,
            Job.title,
            Job.status.label("job_status"),
            RejectionReason.name.label("rejection_reason_name"),
        )
        .join(Job, CandidateStage.job_id == Job.id)
        .outerjoin(
            RejectionReason,
            RejectionReason.id == CandidateStage.rejection_reason_id,
        )
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )

    # Group by job
    jobs_map: dict = {}
    for stage, job_title, job_status, rejection_reason_name in stages_result.all():
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
                # Powód odrzucenia tej rekrutacji — wypełniany z NAJNOWSZEGO etapu
                # `rejected` (iterujemy moved_at DESC, więc pierwszy napotkany
                # rejected to ten najświeższy). None, gdy kandydat nie był odrzucony
                # w tej rekrutacji. Priorytet źródła jak w kolumnie „Powód
                # odrzucenia" na liście kandydatów (_format_rejection_reason).
                "rejection_reason": None,
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
        # Powód odrzucenia — z najnowszego etapu `rejected` tej rekrutacji.
        if entry["rejection_reason"] is None and stage.stage == PipelineStage.rejected:
            entry["rejection_reason"] = _format_rejection_reason(
                reason_name=rejection_reason_name,
                stage_notes=stage.notes,
                rejection_note=stage.rejection_note,
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

    response = {
        "candidate_id": candidate_id,
        "candidate_name": f"{candidate.name} {candidate.lastname}",
        "jobs": list(jobs_map.values()),
        "contracts": contracts_history,
        "risk_summary": risk_summary,
    }

    return _candidate_history_response_for_user(response, current_user)


@router.patch("/{candidate_id}/recruitments/{job_id}/client-rate")
async def set_recruitment_client_rate(
    candidate_id: int,
    job_id: int,
    payload: ClientRateUpdate,
    current_user: CandidateFinanceAccess,
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
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
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


@router.patch("/{candidate_id}/recruitments/{job_id}/expected-rate")
async def set_recruitment_expected_rate(
    candidate_id: int,
    job_id: int,
    payload: ClientRateUpdate,
    current_user: RecruitmentRateEditAccess,
    db: AsyncSession = Depends(get_db),
):
    """Ustaw/wyczyść „Stawkę kandydata" (oczekiwania kandydata, expected_rate)
    dla danej rekrutacji (candidate, job).

    PATCH /api/candidates/{candidate_id}/recruitments/{job_id}/expected-rate

    Body shape identyczny z `client-rate` (`ClientRateUpdate`:
    `{rate_value, rate_unit?, rate_currency?}`). Lustrzane do
    `set_recruitment_client_rate` — pozwala uzupełnić/skorygować stawkę
    kandydata bezpośrednio z profilu (dotąd ustawiana tylko przy ruchu na etap
    „Zweryfikowany" przez `VerifiedRateModal`). Zapis na najnowszym
    `CandidateStage` tej rekrutacji; odczyt w `/history` bierze ostatnią
    niepustą wartość. `rate_value=None` czyści stawkę.

    Uwaga: edycja NIE re-triggeruje budżetowego gate'u zatwierdzania (pending
    verification) — ten pozostaje na poziomie ruchu na etap `verified`, gdzie
    jest jego pierwotny cel.
    """
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail="Brak rekrutacji dla tego kandydata i tej oferty.",
        )

    if payload.rate_value is None:
        latest.expected_rate_value = None
        latest.expected_rate_unit = None
        latest.expected_rate_currency = None
    else:
        latest.expected_rate_value = payload.rate_value
        latest.expected_rate_unit = (payload.rate_unit or RateUnit.monthly).value
        latest.expected_rate_currency = (payload.rate_currency or "PLN")[:3].upper()

    await db.commit()
    await db.refresh(latest)

    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "expected_rate": (
            {
                "value": float(latest.expected_rate_value),
                "unit": latest.expected_rate_unit,
                "currency": latest.expected_rate_currency or "PLN",
            }
            if latest.expected_rate_value is not None
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

    # ── M4 PR-02 (audyt P0.8): historia z hired / z kontraktem nie znika ────
    # zwykłym API. Fizyczny DELETE kasuje audit trail zatrudnienia (baseline
    # PR-00: 499 par hired-bez-kontraktu częściowo stąd), a kontrakt/zamówienie
    # zostają osierocone. Admin może nadal (świadome korekty błędnych danych
    # — decyzja Artura 2026-07-16); pozostałe role dostają 409.
    if not current_user.has_any_role(UserRole.admin):
        has_hired = any(s.stage == PipelineStage.hired for s in stage_rows)
        from app.models.contract import Contract

        has_contract = (
            await db.scalar(
                select(func.count(Contract.id)).where(
                    Contract.candidate_id == candidate_id,
                    Contract.job_id == job_id,
                )
            )
        ) or 0
        if has_hired or has_contract:
            reason = (
                "historię z etapem 'hired'"
                if has_hired
                else f"rekrutację powiązaną z kontraktem ({has_contract})"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Nie można usunąć — {reason}. Usunięcie dowodów "
                    "zatrudnienia wymaga uprawnień administratora."
                ),
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
    current_user: CandidateDocumentAccess,
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
    current_user: CandidateDocumentAccess,
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

    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.DOCUMENT_DOWNLOADED,
        user_id=current_user.id,
        entity_id=candidate_id,
        details={"doc_id": doc_id, "disposition": disposition},
    )
    await db.commit()

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
            # boto3 get_object().read() is synchronous — offload to a worker
            # thread so the single-worker event loop stays responsive while the
            # CV/document streams from Hetzner Object Storage. Matches the
            # pattern in cv_source.py and asyncio.to_thread usage below.
            content = await asyncio.to_thread(download_cv, doc.storage_key)
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
    current_user: CandidateDocumentAccess,
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

    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.DOCUMENT_URL_ISSUED,
        user_id=current_user.id,
        entity_id=candidate_id,
        details={"doc_id": doc_id, "disposition": disposition},
    )
    await db.commit()

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
    current_user: CandidatePIIAccess,
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
    # M2 audit PR 1 (M2-PRIV-02): operational hard delete is DISABLED. The
    # ON DELETE CASCADE sweep (migrations 0141+0146) silently removes
    # contracts, notes, stages and audit history, while local CV files,
    # object-storage keys and integration payloads are NOT reliably cleaned
    # up. Erasure returns as an auditable privacy-executor workflow in PR 2
    # of the module plan (preview → approval → artifact manifest → retry).
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.SENSITIVE_OPERATION_BLOCKED,
        user_id=current_user.id,
        entity_id=candidate_id,
        details={"operation": "hard_delete", "reason": "privacy_workflow_required"},
    )
    await db.commit()
    raise privacy_workflow_unavailable("trwałe usunięcie kandydata")


# CV-enrichment helpers live in app.services.cv_enrichment so the Traffit
# importer and the name-backfill job can reuse the exact same contract without
# importing this API module. Imported here for use below and re-exported for
# existing call-sites (tests/test_cv_enrichment.py imports `_apply_cv_enrichment`
# from here; public_share imports `_enrich_candidate_cv_task` which uses it).
from app.services.cv_enrichment import (  # noqa: E402
    _CV_PLACEHOLDER_NAME,
    _apply_cv_enrichment,
)


async def _auto_assign_primary_cc(candidate: Candidate, db: AsyncSession) -> None:
    """Run CC classifier and persist the result as the candidate's CC set.

    Delegates to the shared writer (`apply_candidate_cc_scores`) which writes
    the M2M (primary + up to 2 secondary) and syncs the legacy slug + FK.
    `overwrite=False` preserves the historical "fill only when empty" behaviour
    on CV re-upload — a candidate that already has a primary keeps it, and
    manually-curated profiles are never touched. Failures are logged but never
    surface to the caller: CC is enrichment, not required for the record.
    """
    try:
        from app.services.candidate_cc_assignment import apply_candidate_cc_scores
        from app.services.cc_classifier import classify_candidate_to_cc

        scores = await classify_candidate_to_cc(candidate, db)
        summary = await apply_candidate_cc_scores(
            candidate, scores, db, overwrite=False
        )
        if summary:
            logger.info(
                "[cv_cc] auto-assigned CC candidate=%s primary=%s score=%.3f "
                "secondary=%s",
                candidate.id,
                summary["primary"],
                summary["primary_score"],
                summary["secondary"],
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
        from app.services.index_outbox_service import schedule_or_embed_candidate

        await schedule_or_embed_candidate(candidate.id, db)
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
        from app.services.index_outbox_service import schedule_or_embed_candidate

        await schedule_or_embed_candidate(candidate_id, db)
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
    current_user: CandidateDocumentAccess,
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
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.CV_DOWNLOADED,
        user_id=current_user.id,
        entity_id=candidate_id,
        details={"endpoint": "cv-download"},
    )
    await db.commit()
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
    current_user: CandidateDocumentAccess,
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
                        # Sync boto3 download — offload so the loop is not
                        # blocked for each of up to 200 CVs in this bulk request.
                        data = await asyncio.to_thread(
                            _download_cv, candidate.cv_storage_key
                        )
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

    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.BULK_CV_DOWNLOADED,
        user_id=current_user.id,
        details={
            "requested_count": len(requested_ids),
            "included_count": included,
            "skipped_count": skipped,
        },
    )
    await db.commit()

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
    current_user: CandidateSearchAccess,
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
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Return talent pools ranked by centroid similarity to this candidate."""
    from app.services.pool_suggester import suggest_pools_for_candidate

    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    suggestions = await suggest_pools_for_candidate(
        db,
        candidate_id,
        viewer_id=current_user.id,
        viewer_is_admin=current_user.has_role(UserRole.admin),
    )
    return [SuggestedPoolOut(**s.to_dict()) for s in suggestions]


@router.get(
    "/{candidate_id}/competence-categories",
    response_model=list[CandidateCcOut],
)
async def list_candidate_ccs(
    candidate_id: int,
    current_user: CandidatePIIAccess,
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
