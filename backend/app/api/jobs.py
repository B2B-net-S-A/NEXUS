import enum
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Optional

import httpx

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.concurrency import run_in_threadpool
from pydantic import Field
from sqlalchemy import (
    and_,
    case,
    func,
    not_,
    nulls_last,
    or_,
    select,
    true,
    tuple_,
    update as sql_update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.services.job_portals.service import (
    close_live_postings,
    close_postings_if_approved_for_other_client,
    has_live_postings,
)
from app.core.cache import cache_invalidate
from app.services.critical_events import audited_deletion
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.contract import Contract, ContractStatus
from app.services.pipeline_latest import latest_stage_ids
from app.services.access_scope import DL_CLIENT_OUT_OF_SCOPE_DETAIL
from app.models.competence_category import UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_work_assignment import WORK_ROLE, JobWorkAssignment
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
)
from app.schemas.job import (
    CcOverrideRequest,
    CcSuggestion,
    CcSuggestionsResponse,
    JobCloseRequest,
    JobCollaboratorAdd,
    JobCreate,
    HiringManagerOption,
    JobHandoffRequest,
    JobHiringManagerRequest,
    JobManageInNexusRequest,
    JobOwnerAssignment,
    JobPublishRequest,
    JobResponse,
    JobUpdate,
    UserBrief,
)
from app.schemas.job_team import JobRecruiterOut
from app.api.body_validation import validated_body
from app.api.clients_team import TAC_ASSIGNABLE_ROLES
from app.api.candidate_access import redact_job_for_viewer, resolve_client_rate_write
from app.api.deps import (
    CurrentUser,
    DeliveryLeadPlus,
    OperationalUser,
    RecruiterPlus,
    require_roles,
)
from app.api.permission_access import RecruitmentManageUser
from app.services.action_permissions import ProductAction, has_permission
from app.services.permission_denial import ensure_permission
from app.services.client_access import assert_client_assignable
from app.api.recruitment_access import (
    JobEditLevel,
    JobEditUser,
    JobStaffingUser,
    assert_delivery_lead_job_visible,
    delivery_lead_job_pairs,
    ensure_champion_job_editor,
    ensure_champion_job_read_visible,
    ensure_delivery_lead_job_visible,
    ensure_job_editor,
    ensure_job_membership,
    ensure_job_read_access,
    job_edit_level,
    user_can_set_job_priority,
    user_can_staff_job,
)
from app.services.requirement_contract import apply_requirement_source_update
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.core.config import settings
from app.services.request_work_state import (
    WORK_STATE_FINISHED,
    WORK_STATE_REOPENED,
    set_work_state,
)
from app.services.request_work_state import visible_state as _visible_work_state
from app.services.recruitment_allocation import (
    allocation_lock,
    assign_operator,
    effective_allocation_mode,
    release_operator,
)
from app.services.candidate_search_predicates import (
    FILTER_DATE_MAX,
    FILTER_DATE_MIN,
    business_date_range,
)
from app.services.job_priority import (
    PRIORITY_LEVELS,
    priorities_for_levels,
    priority_rank_expr,
)
from app.services.job_team import (
    WORK_ROLES,
    TeamPerson,
    jobs_nobody_working_clause,
    jobs_worked_by_clause,
    manual_collaborator_job_ids,
    owner_is_working_clause,
    recruiters_for_jobs,
    remove_recruiter,
    working_assignment_job_ids,
)
from app.services.request_allocation import (
    job_in_pool,
    manual_add,
    void_manual_release,
)
from app.services.workforce_availability import (
    operational_owner_clause,
    operational_job_owner_clause,
)
from app.services import champion_view
from app.services import job_lifecycle
from app.services.job_readiness import job_handoff_blockers as _compute_job_readiness
from app.services.job_readiness import job_handoff_blocker_items
from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
from app.services.candidate_contact_hooks import (
    maybe_close_job_contact_opportunities,
)
from app.services.marketplace_service import (
    is_significant_job_update,
    run_marketplace_scan_safe,
)
from app.services.recruitment_process_commands import open_process

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

# Postgres INTEGER (int4) upper bound. Id filters bound against int4 columns
# must stay within this range, otherwise asyncpg raises OverflowError while
# encoding the parameter and the request fails with a 500 instead of a 422.
PG_INT4_MAX = 2_147_483_647
DbId = Annotated[int, Field(ge=1, le=PG_INT4_MAX)]


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

# Organisation-wide readers of the request history (every client; fee amounts
# only where ``can_read_client_finance`` allows — a DL sees the portfolio's,
# runda 6 audytu, decyzja Artura 26.09.2026).
# Everyone else reaches the Historia tab only as a member of the recruitment's
# team — same client only, without fee amounts (decision 17.09.2026).
_HISTORY_ORG_READER_ROLES = (UserRole.admin, UserRole.delivery_lead, UserRole.finance)


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
            detail=DL_CLIENT_OUT_OF_SCOPE_DETAIL,
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


async def _history_fee_visible(current_user: User, db: AsyncSession):
    """Czy wiersz historii requestów może nieść kwoty (marża) — per klient.

    Runda 6 audytu (decyzja Artura 26.09.2026): Historia i baner podglądu
    oddawały Delivery Leadowi ``fee_rate`` (marżę) KAŻDEGO klienta, także
    z ``?cross_client=true``. Kwoty jednego klienta rozstrzyga wspólna reguła
    ``can_read_client_finance`` — DL (także hybryda HoR+DL) widzi je tylko
    u klientów swojego portfela, admin i Finanse wszędzie.
    """
    from app.api.financial_access import (
        can_read_client_finance,
        has_financial_access,
    )
    from app.services.access_scope import resolve_delivery_lead_finance_client_ids

    boundary = await resolve_delivery_lead_finance_client_ids(current_user, db)

    def visible(client_id: int | None) -> bool:
        if client_id is None:
            return has_financial_access(current_user)
        return can_read_client_finance(
            current_user,
            client_id=client_id,
            delivery_lead_finance_client_ids=boundary,
        )

    return visible


def _history_entry_payload(entry, *, show_fee: bool) -> dict:
    data = dict(entry.__dict__)
    if not show_fee:
        # Wpisy serwisu to zamrożone dataclassy — redakcja na kopii.
        data.update(fee_rate=None, fee_currency=None, rate_unit=None)
    return data


def _may_write_salary_range(current_user: User) -> bool:
    """Widełki wynagrodzenia zostają przy roli: admin (do 0411 także TAC).

    Do 0410 rekrutację zakładał tylko admin i Delivery Lead, więc wystarczało
    odmówić DL/TCM. Uprawnienie „Rekrutacje” może dostać każda rola — nadanie
    nie może dawać więcej niż ma jego domyślny posiadacz (Delivery Lead).
    """

    return current_user.has_role(UserRole.admin)


def _assert_delivery_lead_finance_write(
    fields_set: set[str],
    current_user: User,
) -> None:
    """Only admin may create or mutate recruitment budget fields."""

    if {"salary_min", "salary_max"} & fields_set and not _may_write_salary_range(
        current_user
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Widełki wynagrodzenia może ustawić tylko admin",
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
    # Wyliczany także ze stawki Championa — lista nie jest jego powierzchnią.
    "effective_budget_hourly",
    "effective_budget_hourly_min",
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
    "matching_requirements",
    "requirements_reviewed",
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
# Pola, których zmiana na OPUBLIKOWANEJ rekrutacji zgłasza ją do auto-matchu
# i nocnego pełnego przeglądu bazy (21.09.2026) — poza `_SIGNIFICANT_FIELDS`
# Targu: budżet i warunki pracy (dealbreakery przeglądu).
_AUTO_REVIEW_EXTRA_FIELDS = (
    "rate_budget_hourly",
    "salary_min",
    "salary_max",
    "remote_policy",
    "onsite_days_per_week",
)

_SCORING_INPUT_FIELDS = _EMBED_TRIGGER_FIELDS | {
    "location",
    "remote_policy",
    "deadline",
}


_OWNER_FIELD_LABELS = {
    "tac_id": "TAC",
    "delivery_lead_id": "Delivery Lead",
    "recruiter_id": "Rekruter",
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
    # Komunikaty po polsku (runda 6 audytu), bo trafiają wprost do okna
    # edycji rekrutacji — „delivery_lead_id: user is inactive” nic nie mówił.
    label = _OWNER_FIELD_LABELS.get(field, field)
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"{label}: nie znaleziono takiej osoby.",
        )
    if not user.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{label}: to konto jest nieaktywne — wybierz inną osobę.",
        )
    if not user.has_any_role(*allowed_roles):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{label}: ta osoba nie ma odpowiedniej roli.",
        )


async def _assert_job_references_valid(
    db: AsyncSession,
    *,
    job_id: Optional[int] = None,
    pipeline_template_id: Optional[int] = None,
    competence_category_id: Optional[int] = None,
    secondary_cc_ids: Optional[list[int]] = None,
    reference_number: Optional[str] = None,
) -> None:
    """Odrzuć przed zapisem odwołania, na których padłby więz bazy.

    Runda 9 (R9-N15-5): nieistniejący szablon procesu albo kategoria kończyły
    się `ForeignKeyViolation`, a zajęty numer referencyjny — naruszeniem
    UNIQUE; oba jako 500 bez CORS („Network Error”). Brak = 422, zajęty
    numer = 409.
    """
    from app.models.competence_category import CompetenceCategory  # noqa: PLC0415
    from app.models.pipeline_template import PipelineTemplate  # noqa: PLC0415

    if pipeline_template_id is not None and not await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.id == pipeline_template_id)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Szablon procesu: nie znaleziono takiego szablonu.",
        )
    cc_ids = {
        cc_id
        for cc_id in [competence_category_id, *(secondary_cc_ids or [])]
        if cc_id is not None
    }
    if cc_ids:
        found = set(
            (
                await db.scalars(
                    select(CompetenceCategory.id).where(
                        CompetenceCategory.id.in_(cc_ids)
                    )
                )
            ).all()
        )
        if cc_ids - found:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Kategoria kompetencji: nie znaleziono takiej kategorii.",
            )
    if reference_number:
        clash = select(Job.id).where(Job.reference_number == reference_number)
        if job_id is not None:
            clash = clash.where(Job.id != job_id)
        if await db.scalar(clash.limit(1)) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "reference_number_taken",
                    "message": "Ten numer referencyjny ma już inna rekrutacja.",
                },
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
            detail="TAC: ta osoba nie jest przypisana do wybranego klienta.",
        )


async def _sync_job_status_payload(job: Job) -> None:
    """Status w payloadzie punktu oferty w Qdrancie — tani zapis, bez Voyage'a.

    Runda 8 (R8-N11-2): zmiana statusu nie zmienia tekstu embeddingu, więc nie
    wywołuje re-embedu, a filtr puli ofert (`search_jobs_semantic(statuses=…)`)
    czyta status z payloadu. Oferta bez `embedding_id` nie ma punktu — pomijamy.
    Wołać PO commicie; nigdy nie rzuca. Oferty bez punktu nie sprawdzamy
    tutaj — `sync_job_status_payloads` pomija punkty, których nie ma.
    """
    try:
        from app.services.embedding_service import (
            job_status_value,
            sync_job_status_payloads,
        )

        await sync_job_status_payloads({job.id: job_status_value(job.status)})
    except Exception as exc:  # noqa: BLE001 — payload dogoni reconciler
        logger.warning(
            "[Job] status payload sync failed job=%s: %s", job.id, type(exc).__name__
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
        extracted = extract_train_name(combined, client_slug=client_slug)
        # Runda 9 (R9-N15-5): kolumna ma 128 znaków, a słowo z opisu nie ma
        # limitu — dłuższy tag dawał 500 przy zapisie rekrutacji.
        return extracted[:128] if extracted else extracted
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
    UserRole.recruiter,
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
) -> dict[int, list[tuple[int, str]]]:
    """Return {job_id: [(user_id, source), ...]} for the given job ids.

    ``source`` = ``manual`` (dodany ręcznie — jest „Rekruterem” rekrutacji)
    albo ``auto_cc`` (cała kategoria kompetencji — nie jest). Front pokazuje
    w oknie edycji wyłącznie ręcznych; rolę „Rekruter” niesie ``recruiters``."""
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(
                JobCollaborator.job_id,
                JobCollaborator.user_id,
                JobCollaborator.source,
            )
            .where(
                JobCollaborator.job_id.in_(job_ids),
                # Osoba zdjęta z rekrutacji zostaje w tabeli tylko jako blokada
                # ponownego dodania z kategorii — uczestnikiem już nie jest.
                JobCollaborator.removed_from_auto_cc.is_(False),
            )
            .order_by(JobCollaborator.id)
        )
    ).all()
    out: dict[int, list[tuple[int, str]]] = {}
    for job_id, user_id, source in rows:
        out.setdefault(job_id, []).append(
            (user_id, getattr(source, "value", source) or "manual")
        )
    return out


def _collaborator_payload(
    entries: list[tuple[int, str]], user_brief_map: dict[int, UserBrief]
) -> list[dict]:
    """Współpracownicy rekrutacji do odpowiedzi — ``UserBrief`` + ``source``."""
    return [
        {**user_brief_map[uid].model_dump(), "source": source}
        for uid, source in entries
        if uid in user_brief_map
    ]


def _recruiters_payload(people: list[TeamPerson]) -> list[dict]:
    """Rola „Rekruter” do odpowiedzi — ten sam kształt na liście, w szczegółach
    i na pulpicie (``JobRecruiterOut``); propozycja automatu ma ``proposed``."""
    return [
        JobRecruiterOut.model_validate(person, from_attributes=True).model_dump()
        for person in people
    ]


class JobSort(str, enum.Enum):
    """Ordering options for GET /api/jobs (``newest`` is the default)."""

    newest = "newest"  # created_at DESC — most recently created first
    oldest = "oldest"  # created_at ASC — legacy implicit order (oldest first)
    deadline = "deadline"  # deadline ASC, NULLs last — soonest due first
    # Najpierw P1, potem „Wymaga ruchu" malejąco, przeterminowane, najbliższy
    # termin.
    attention = "attention"


class PriorityWorkJobFilter(str, enum.Enum):
    """Priority Work context independent from legacy ownership/collaboration."""

    assigned = "assigned"
    carry_over = "carry_over"
    either = "either"


# ── Predykaty filtrów „Szybkie" (lewa kolumna listy rekrutacji) ──────────────
#
# Każdy z nich jest WSPÓŁDZIELONY przez ``list_jobs`` i ``jobs_quick_counts``.
# To nie jest kosmetyka: licznik przy filtrze i lista, którą ten filtr zwraca,
# muszą odpowiadać na DOKŁADNIE to samo pytanie.  Dwie kopie predykatu
# rozjeżdżają się przy pierwszej poprawce jednej z nich, a objaw — „pisze 63,
# pokazuje 41" — jest cichy: obie liczby są poprawne, tylko liczą co innego.


def jobs_register_base_clause():
    """Wspólna podstawa rejestru: nigdy nie pokazuj rekrutacji bez klienta.

    Od migracji 0120 (2026-05-27) baza ma na tej kolumnie NOT NULL — filtr
    zostaje jako defense-in-depth, gdyby ktoś kiedyś ograniczenie zdjął.
    Klient ukryty albo usunięty nie wnosi rekrutacji do rejestru (UAT B73).
    """
    from app.services.client_identity import job_client_listed_clause

    return and_(Job.client_id.is_not(None), job_client_listed_clause(Job.client_id))


def jobs_search_clause(q: str):
    """Pole „Szukaj" rejestru: tytuł, numer referencyjny, klient, technologie.

    Placeholder w UI obiecuje „Tytuł, klient, technologia…", a do 09.2026
    backend filtrował wyłącznie po tytule — i to bez escapowania, więc `%`
    zwracało pełną listę. Klient przez EXISTS (nie JOIN): jeden wiersz na
    rekrutację, więc `total` liczone z tego samego zapytania się zgadza.
    `must_skills` to JSONB — porównujemy jego tekst, bez rozbijania listy.
    """
    from sqlalchemy import cast, exists
    from sqlalchemy.types import Text

    from app.models.client import Client
    from app.services.polish_ilike import polish_folded_ilike

    needle = q.strip()
    if not needle:
        return true()
    client_match = exists(
        select(Client.id).where(
            Client.id == Job.client_id,
            or_(
                polish_folded_ilike(Client.name, needle),
                polish_folded_ilike(Client.display_name, needle),
            ),
        )
    )
    return or_(
        polish_folded_ilike(Job.title, needle),
        polish_folded_ilike(Job.reference_number, needle),
        polish_folded_ilike(Job.working_title, needle),
        polish_folded_ilike(Job.client_reference, needle),
        client_match,
        polish_folded_ilike(cast(Job.must_skills, Text), needle),
    )


# ── „Rekruter” rekrutacji — reguła żyje w ``services/job_team`` ──────────────
# Lista, pulpit „Requesty i obłożenie” i panel rekrutacji liczą jedną regułą
# (decyzja Artura 02.10.2026). Stare nazwy zostają importowalne stąd — czytają
# je testy i cztery moduły (zakres osobisty, „Moje następne kroki”, operacje
# rekrutacji, kreator metryk). Zmiana znaczenia: „pracuje” = przypisanie
# AKTYWNE (``state = 'active'``); propozycja automatu czeka na akceptację Head
# of Recruitment i pracą nie jest.
_live_work_assignment_job_ids = working_assignment_job_ids
_owner_is_working_clause = owner_is_working_clause
_manual_collaborator_job_ids = manual_collaborator_job_ids


def jobs_mine_clause(current_user: User):
    """„Moje projekty" — właściciel operacyjny, RĘCZNIE dopisany współpracownik
    ALBO osoba z aktywnym przypisaniem do requestu (``job_work_assignments``).

    Runda 9 (R9-N15-2): sourcer 2. priorytetu, drugi rekruter i osoba dodana
    ręcznie na pulpicie „Requesty i obłożenie” pracują nad requestem, a do tej
    rundy nie widzieli go w „Moje”. Ta sama klauzula liczy listę, liczniki
    zakresu i „Moje następne kroki”.

    Delivery Lead rekrutacji (``delivery_lead_id``) też jest „mój” (zgłoszenie
    30.09.2026): DL ma „Moje” jako zakres domyślny, a świeżo założona przez
    niego rekrutacja bez rekrutera pokazywała „Moje 0”. Kreator metryk pulpitu
    liczył DL-a jako „moje” od początku.

    Wiersze ``auto_cc`` się NIE liczą (02.10.2026): dopisywały całą kategorię
    kompetencji, więc „Moje” pokazywało rekrutacje, przy których osoba nic nie
    robi. Te mają osobny zakres — ``jobs_my_category_clause``.
    """
    return or_(
        operational_owner_clause(Job.recruiter_id, current_user),
        operational_owner_clause(Job.delivery_lead_id, current_user),
        Job.id.in_(manual_collaborator_job_ids([current_user.id])),
        Job.id.in_(working_assignment_job_ids([current_user.id])),
    )


def jobs_my_category_clause(current_user: User):
    """Zakres „Moja kategoria” — NIEZAMKNIĘTE rekrutacje, których GŁÓWNA
    kategoria kompetencji jest jedną z kategorii osoby (1. albo 2. priorytet).

    To następca wierszy ``auto_cc`` w „Moje”: pokazuje, co osoba mogłaby wziąć,
    a nie przy czym pracuje. Osoba bez kategorii dostaje pusty wynik (pusty
    podzbiór w ``IN``), nigdy cały rejestr; kategorie dodatkowe rekrutacji się
    nie liczą — inaczej zakres mieszałby cudze requesty z własnymi.
    """
    my_categories = select(UserCompetenceCategory.competence_category_id).where(
        UserCompetenceCategory.user_id == current_user.id
    )
    return and_(Job.competence_category_id.in_(my_categories), jobs_open_only_clause())


def jobs_open_only_clause():
    """„Niezamknięte" — wszystko poza ``closed``; Draft też się liczy."""
    return Job.status != JobStatus.closed


def jobs_mine_scope_clause(current_user: User):
    """Zakres „Moje” listy ``/jobs`` — MOJE i NIEZAMKNIĘTE.

    Runda 7 (R7-N8-1, decyzja Artura 26.09.2026): zamknięte rekrutacje
    (archiwum z Traffita, 0377/0378) widać wyłącznie w „Wszystkie”. Lista
    dostaje ``mine`` + ``open_only``; liczniki zakresu „Moje” liczą tym.
    """
    return and_(jobs_mine_clause(current_user), jobs_open_only_clause())


def jobs_needs_sourcing_clause(value: bool = True):
    """„Potrzebny search" — flaga postawiona przez Delivery Leada."""
    return Job.needs_sourcing.is_(value)


def jobs_active_in_search_clause(value: bool = True):
    """„Aktywni w searchu" — rekrutacja ma czynnego współpracownika."""
    active_collab_subq = select(JobCollaborator.job_id).where(
        JobCollaborator.removed_from_auto_cc.is_(False)
    )
    if value:
        return Job.id.in_(active_collab_subq)
    return Job.id.not_in(active_collab_subq)


def jobs_owner_missing_clause(value: bool = True):
    """„Brak ownera requestu" — LUSTRO warunku, który liczyła przeglądarka.

    Kolumną jest ``tac_id``, nie ``recruiter_id``: „owner requestu" to TAC,
    który request przyjął, a ``recruiter_id`` niesie właściciela prowadzącego
    i wychodzi w odpowiedzi jako ``primary_owner``.  Do 09.2026 ten filtr żył
    WYŁĄCZNIE w przeglądarce (``lib/jobs-quick-filters.ts``), bo lista nie
    miała czego zapytać — zawężał więc już wczytaną stronę, nie bazę.
    """
    return Job.tac_id.is_(None) if value else Job.tac_id.is_not(None)


def _normalize_deadline_time(updates: dict, current_deadline: Optional[date]) -> None:
    """0406: godzina terminu istnieje tylko przy dacie.

    Wyczyszczona data zabiera godzinę; godzina bez daty (także zapisanej) = 422.
    """
    if "deadline" in updates and updates["deadline"] is None:
        updates["deadline_time"] = None
        return
    effective_deadline = updates.get("deadline", current_deadline)
    if updates.get("deadline_time") is not None and effective_deadline is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Godzinę terminu można ustawić tylko razem z datą.",
        )


def jobs_deadline_clauses(
    deadline_from: Optional[date], deadline_to: Optional[date]
) -> list:
    """Granice okna terminu — każda niezależnie, obie opcjonalne."""
    clauses = []
    if deadline_from is not None:
        clauses.append(Job.deadline >= deadline_from)
    if deadline_to is not None:
        clauses.append(Job.deadline <= deadline_to)
    return clauses


def jobs_opened_clauses(opened_from: Optional[date], opened_to: Optional[date]) -> list:
    """Okno „Data otwarcia” — obie daty włącznie, doba w kalendarzu firmy.

    Data otwarcia to ``opened_at``, a bez niej ``created_at``: ``opened_at``
    stempluje tylko import Traffita, więc rekrutacja założona w NEXUSIE ma je
    puste i wypadałaby z każdego zakresu. Ta sama wartość idzie w wierszu jako
    ``opened_effective_at``.
    """
    start, end = business_date_range(opened_from, opened_to)
    opened = func.coalesce(Job.opened_at, Job.created_at)
    clauses = []
    if start is not None:
        clauses.append(opened >= start)
    if end is not None:
        clauses.append(opened < end)
    return clauses


# Etapy „CV wysłane albo dalej" — kamienie milowe po stronie klienta.
# `interview` (rozmowa WEWNĘTRZNA) świadomie poza: kandydat nie poszedł jeszcze
# do klienta. `acceptance`/`hired` są w zbiorze, bo import Traffita potrafi
# przeskoczyć „CV wysłane" — osoba zaakceptowana przez klienta była wysłana.
SENT_TO_CLIENT_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.cv_sent,
    PipelineStage.client_interview,
    PipelineStage.acceptance,
    PipelineStage.hired,
)


def jobs_sent_to_client_subquery(job_ids):
    """``(job_id, sent_n)`` — OSOBY (distinct kandydat) wysłane do klienta.

    Liczone z widoku ``analytics_first_milestones`` (reguła D2: pierwsze
    wejście pary na etap; wykluczone placementy już odfiltrowane w widoku),
    więc powrót na etap nie dubluje osoby. ``job_ids`` — podzapytanie
    przefiltrowanej listy, żeby widok nie liczył całej bazy.
    """
    from sqlalchemy import Enum as SAEnum, Integer, column, table  # noqa: PLC0415

    milestones = table(
        "analytics_first_milestones",
        column("candidate_id", Integer),
        column("job_id", Integer),
        # Typ enuma, nie String — w bazie kolumna jest natywnym `pipelinestage`.
        column("stage", SAEnum(PipelineStage, name="pipelinestage")),
    )
    return (
        select(
            milestones.c.job_id.label("job_id"),
            func.count(func.distinct(milestones.c.candidate_id)).label("sent_n"),
        )
        .where(
            milestones.c.stage.in_(SENT_TO_CLIENT_STAGES),
            milestones.c.job_id.in_(job_ids),
        )
        .group_by(milestones.c.job_id)
        .subquery()
    )


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
            "created_at ASC; `deadline` → deadline ASC with NULLs last; "
            "`attention` → P1 priority first, then most candidates waiting for "
            "the recruiter (`needs_action_count` DESC), then overdue deadlines, "
            "then deadline."
        ),
    ),
    client_id: Optional[list[DbId]] = Query(
        None,
        description=(
            "Filter by client id — one or more ids. Repeat the param for "
            "multi-select (e.g. `?client_id=3&client_id=7`). OR-combined. "
            "Single-value calls remain backward-compatible."
        ),
    ),
    q: Optional[str] = None,
    owner_id: Optional[list[DbId]] = Query(
        None,
        description=(
            "Filter by primary_owner user id (recruiter_id) — one or more ids. "
            "Repeat the param for multi-select. OR-combined."
        ),
    ),
    responsible_id: Optional[list[DbId]] = Query(
        None,
        description=(
            "Filter by responsible person ('Osoba odpowiedzialna') — matches if "
            "the user is the recruiter OR TAC on the job. One or more ids, repeat "
            "the param for multi-select. OR-combined across both the id set and "
            "the two responsibility roles."
        ),
    ),
    competence_category_id: Optional[list[DbId]] = Query(
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
    owner_missing: Optional[bool] = Query(
        None,
        description=(
            "'Brak ownera requestu' — True → only jobs with no TAC owner "
            "(`tac_id IS NULL`). False → only jobs that have one. Mirrors the "
            "badge shown on every row; before this param the filter could only "
            "narrow the already-loaded page in the browser."
        ),
    ),
    mine: bool = Query(
        False,
        description=(
            "Limit to jobs the current user works on or leads: lead recruiter, "
            "Delivery Lead, MANUALLY added collaborator or an active request "
            "assignment. Collaborators added with the whole competence "
            "category (`auto_cc`) do not count — see `my_category`."
        ),
    ),
    my_category: bool = Query(
        False,
        description=(
            "Zakres „Moja kategoria” — niezamknięte rekrutacje, których GŁÓWNA "
            "kategoria kompetencji jest jedną z kategorii bieżącej osoby. "
            "Osoba bez kategorii dostaje pustą listę."
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
    delivery_lead_id: Optional[list[DbId]] = Query(
        None,
        description=(
            "Filter by Job.delivery_lead_id — one or more user ids (repeat the "
            "param, OR-combined). Used by the DL Hub Active Jobs tab (single id) "
            "and the 'Delivery Lead' filter of the jobs list."
        ),
    ),
    min_sent: Optional[int] = Query(
        None,
        ge=0,
        le=PG_INT4_MAX,
        description=(
            "Only jobs where AT LEAST this many people (distinct candidates) "
            "reached 'CV wysłane' or a later client-side stage "
            "(`analytics_first_milestones`, rule D2)."
        ),
    ),
    max_sent: Optional[int] = Query(
        None,
        le=PG_INT4_MAX,
        ge=0,
        description=(
            "Only jobs where AT MOST this many people reached 'CV wysłane' or "
            "later. `max_sent=0` → nobody sent to the client yet."
        ),
    ),
    request_status: Optional[list[str]] = Query(
        None,
        description=(
            "Filter by computed request status (0341): closed · filled · "
            "contract · champion · incomplete · searching. Repeatable, "
            "OR-combined. Same rule as the `request_status` field of each row."
        ),
    ),
    work_state: Optional[list[str]] = Query(
        None,
        description=(
            "0371: stan pracy nad requestem widoczny dla ludzi — to_review · "
            "searching · champion · client_silent · finished. Powtarzalny, "
            "łączony przez LUB (`request_work_state.visible_state`)."
        ),
    ),
    request_stage: Optional[list[str]] = Query(
        None,
        description=(
            "Stan requestu z jednego rzędu pigułek listy (25.09.2026): "
            "incomplete · to_review · searching · champion · contract · "
            "client_silent (oraz filled · finished · closed). Jedna wartość na "
            "rekrutację (`job_similarity.request_stage_expr`), powtarzalny, "
            "łączony przez LUB."
        ),
    ),
    worked_by: Optional[list[DbId]] = Query(
        None,
        description=(
            "Filtr „Rekruter” — id osób, które pracują nad rekrutacją: "
            "prowadzący (`recruiter_id`), aktywne przypisanie "
            "(`job_work_assignments.state = 'active'`) albo ręcznie dopisany "
            "współpracownik. Propozycja automatu się nie liczy. Powtarzalny, LUB."
        ),
    ),
    nobody_working: Optional[bool] = Query(
        None,
        description=(
            "„Bez rekrutera”: True → tylko rekrutacje, nad którymi nikt nie "
            "pracuje (sama propozycja automatu to za mało); False → tylko te "
            "z Rekruterem. Razem z `worked_by` (true) = LUB: rekrutacje tych "
            "osób albo bez nikogo."
        ),
    ),
    priority_level: Optional[list[str]] = Query(
        None,
        description=(
            "Priorytet w trzech poziomach: p1 („P1 Pilne”) · p2 („P2 Standard”) "
            "· accepting („Przyjmujemy kandydatów”). Powtarzalny, LUB "
            "(`services/job_priority`)."
        ),
    ),
    opened_from: Optional[date] = Query(
        None,
        ge=FILTER_DATE_MIN,
        le=FILTER_DATE_MAX,
        description=(
            "„Data otwarcia” od (włącznie): `opened_at`, a bez niej "
            "`created_at`, od 00:00 Europe/Warsaw tego dnia."
        ),
    ),
    opened_to: Optional[date] = Query(
        None,
        ge=FILTER_DATE_MIN,
        le=FILTER_DATE_MAX,
        description=(
            "„Data otwarcia” do (włącznie) — do 00:00 Europe/Warsaw "
            "NASTĘPNEGO dnia, więc cały ten dzień się liczy."
        ),
    ),
    include_stage_counts: bool = Query(
        False,
        description=(
            "Include per-job `stage_breakdown: {<stage>: count}` aggregating "
            "distinct candidates per pipeline stage. Opt-in (extra GROUP BY query). "
            "Also adds `needs_action_count` (candidates whose next move belongs "
            "to the recruiter) and `open_proposals_count` (team-wide: proposed "
            "candidates nobody has added or dismissed yet)."
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
    query = query.where(jobs_register_base_clause())
    if status:
        query = query.where(Job.status.in_(status))
    if open_only:
        query = query.where(jobs_open_only_clause())
    if client_id:
        query = query.where(Job.client_id.in_(client_id))
    if q:
        query = query.where(jobs_search_clause(q))
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
        query = query.where(jobs_needs_sourcing_clause(needs_sourcing))
    if active_in_search is not None:
        query = query.where(jobs_active_in_search_clause(active_in_search))
    if owner_missing is not None:
        query = query.where(jobs_owner_missing_clause(owner_missing))
    for deadline_clause in jobs_deadline_clauses(deadline_from, deadline_to):
        query = query.where(deadline_clause)
    if has_deadline is not None:
        if has_deadline:
            query = query.where(Job.deadline.is_not(None))
        else:
            query = query.where(Job.deadline.is_(None))
    if delivery_lead_id:
        query = query.where(Job.delivery_lead_id.in_(delivery_lead_id))
    if mine:
        query = query.where(jobs_mine_clause(current_user))
    if my_category:
        query = query.where(jobs_my_category_clause(current_user))
    if priority_level:
        unknown = sorted(set(priority_level) - set(PRIORITY_LEVELS))
        if unknown:
            raise HTTPException(422, f"Nieznany priorytet: {', '.join(unknown)}")
        query = query.where(Job.priority.in_(priorities_for_levels(priority_level)))
    if opened_from is not None and opened_to is not None and opened_from > opened_to:
        raise HTTPException(
            422, "Zakres „Data otwarcia”: data początkowa późniejsza niż końcowa."
        )
    for opened_clause in jobs_opened_clauses(opened_from, opened_to):
        query = query.where(opened_clause)
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
    if request_status:
        from app.services import job_similarity as _sim  # noqa: PLC0415

        unknown = sorted(set(request_status) - set(_sim.REQUEST_STATUSES))
        if unknown:
            raise HTTPException(422, f"Nieznany status requestu: {', '.join(unknown)}")
        status_sq = _sim.request_status_subquery(query.with_only_columns(Job.id))
        query = query.outerjoin(status_sq, status_sq.c.job_id == Job.id).where(
            _sim.request_status_expr(status_sq).in_(request_status)
        )
    if work_state:
        from app.services.request_work_state import (  # noqa: PLC0415
            VISIBLE_STATES,
            visible_state_clause,
        )

        unknown = sorted(set(work_state) - set(VISIBLE_STATES))
        if unknown:
            raise HTTPException(422, f"Nieznany stan requestu: {', '.join(unknown)}")
        query = query.where(visible_state_clause(work_state))
    if request_stage:
        from app.services import job_similarity as _sim  # noqa: PLC0415

        unknown = sorted(set(request_stage) - set(_sim.REQUEST_STAGES))
        if unknown:
            raise HTTPException(422, f"Nieznany stan requestu: {', '.join(unknown)}")
        stage_sq = _sim.request_status_subquery(query.with_only_columns(Job.id))
        query = query.outerjoin(stage_sq, stage_sq.c.job_id == Job.id).where(
            _sim.request_stage_expr(stage_sq).in_(request_stage)
        )
    # „Rekruter: ja, nikt” = którykolwiek z warunków (LUB). Przez AND
    # („ktoś pracuje” i „nikt nie pracuje”) lista byłaby zawsze pusta.
    if worked_by and nobody_working:
        query = query.where(
            or_(jobs_worked_by_clause(worked_by), jobs_nobody_working_clause())
        )
    else:
        if worked_by:
            query = query.where(jobs_worked_by_clause(worked_by))
        if nobody_working is not None:
            nobody = jobs_nobody_working_clause()
            query = query.where(nobody if nobody_working else not_(nobody))
    if min_sent is not None or max_sent is not None:
        if min_sent is not None and max_sent is not None and min_sent > max_sent:
            raise HTTPException(
                422, "Zakres „Wysłanych do klienta”: minimum większe niż maksimum."
            )
        sent_sq = jobs_sent_to_client_subquery(query.with_only_columns(Job.id))
        sent_n = func.coalesce(sent_sq.c.sent_n, 0)
        query = query.outerjoin(sent_sq, sent_sq.c.job_id == Job.id)
        if min_sent is not None:
            query = query.where(sent_n >= min_sent)
        if max_sent is not None:
            query = query.where(sent_n <= max_sent)
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar()
    # Deterministic ordering (newest-first by default). Applied after the count
    # so it never leaks into the COUNT subquery. `id` is the stable tiebreaker.
    default_template_id_for_counts: Optional[int] = None
    if sort == JobSort.attention or include_stage_counts:
        from app.api.pipeline import _default_template_id  # noqa: PLC0415

        default_template_id_for_counts = await _default_template_id(db)
    if sort == JobSort.attention:
        # Klucz sortowania liczy się nad CAŁYM przefiltrowanym zbiorem (nie nad
        # stroną), więc paginacja jest poprawna; `Job.id` domyka kolejność.
        from app.services.job_needs_action import (  # noqa: PLC0415
            needs_action_subquery,
        )

        attention = await needs_action_subquery(
            db,
            job_ids=query.with_only_columns(Job.id),
            default_template_id=default_template_id_for_counts,
        )
        query = query.outerjoin(attention, attention.c.job_id == Job.id).order_by(
            # P1 („Pilne”) zawsze na górze (02.10.2026) — tak samo ustawia
            # kolejkę automat przydziału (`job_priority.priority_rank`).
            priority_rank_expr().asc(),
            func.coalesce(attention.c.needs_action_count, 0).desc(),
            # Przeterminowane przed resztą; brak terminu nie jest zaległością.
            case((Job.deadline < business_today(), 0), else_=1),
            nulls_last(Job.deadline.asc()),
            Job.id.desc(),
        )
    elif sort == JobSort.oldest:
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
    # `stage_columns`: kolumny szablonu rekrutacji z liczbami — TE SAME
    # kolumny (i to samo kubełkowanie) co `GET /api/pipeline/kanban/{id}`, więc
    # mini-lejek listy i szyny szczegółów grupują jedną funkcją frontu. Legacy
    # `stage_breakdown` (po enumie) zostaje dla starszych konsumentów; sam nie
    # odróżnia własnego etapu szablonu od „Nowi" (UAT B33).
    stage_columns: dict[int, list[dict]] = {}
    off_template_counts: dict[int, int] = {}
    attention_by_job: dict[int, tuple[int, int]] = {}
    open_proposals: dict[int, int] = {}
    if include_stage_counts and job_ids:
        from app.services.job_needs_action import (  # noqa: PLC0415
            attention_counts,
        )
        from app.services.job_proposals import open_counts_for_jobs  # noqa: PLC0415

        # Po jednym zapytaniu na stronę: „wymaga ruchu" (ta sama reguła i to
        # samo wyrażenie co `sort=attention`) i otwarte propozycje (zespołowo).
        attention_by_job = await attention_counts(
            db,
            job_ids=job_ids,
            default_template_id=default_template_id_for_counts,
        )
        open_proposals = await open_counts_for_jobs(db, job_ids)
        from app.api.pipeline import (  # noqa: PLC0415
            StageTally,
            legacy_stage_column_summaries,
            stage_column_summaries,
        )
        from app.models.pipeline_template import PipelineStageDef  # noqa: PLC0415

        latest_per_cj = latest_stage_ids(job_ids=job_ids)
        tally_rows = (
            await db.execute(
                select(
                    CandidateStage.job_id,
                    CandidateStage.stage_def_id,
                    CandidateStage.stage,
                    func.count(func.distinct(CandidateStage.candidate_id)),
                )
                .where(CandidateStage.id.in_(select(latest_per_cj.c.latest_id)))
                .group_by(
                    CandidateStage.job_id,
                    CandidateStage.stage_def_id,
                    CandidateStage.stage,
                )
            )
        ).all()
        tallies: dict[int, list[StageTally]] = {}
        for row_job_id, stage_def_id, stage_enum, n in tally_rows:
            per_job = stage_breakdown.setdefault(row_job_id, {})
            per_job[stage_enum.value] = per_job.get(stage_enum.value, 0) + int(n)
            tallies.setdefault(row_job_id, []).append(
                StageTally(stage_def_id=stage_def_id, stage=stage_enum, count=int(n))
            )

        # Policzony wyżej (raz na żądanie) — ten sam szablon domyślny zasila
        # kolumny i licznik „wymaga ruchu".
        default_template_id = default_template_id_for_counts
        template_ids = {
            tid
            for tid in (j.pipeline_template_id or default_template_id for j in jobs)
            if tid is not None
        }
        defs_by_template: dict[int, list[PipelineStageDef]] = {}
        # Wszystkie definicje (kilkadziesiąt wierszy): etapy z innych szablonów
        # (import Traffita) trafiają do kolumn tą samą regułą co na tablicy.
        all_defs: dict[int, PipelineStageDef] = {}
        if template_ids:
            def_rows = (
                await db.execute(
                    select(PipelineStageDef).order_by(
                        PipelineStageDef.template_id, PipelineStageDef.order
                    )
                )
            ).scalars()
            for sd in def_rows:
                all_defs[sd.id] = sd
                if sd.template_id in template_ids:
                    defs_by_template.setdefault(sd.template_id, []).append(sd)
        for j in jobs:
            tid = j.pipeline_template_id or default_template_id
            entries = tallies.get(j.id, [])
            if tid is not None and defs_by_template.get(tid):
                cols, off = stage_column_summaries(
                    defs_by_template[tid],
                    entries,
                    {i: d for i, d in all_defs.items() if d.template_id != tid},
                )
            else:
                cols, off = legacy_stage_column_summaries(entries)
            stage_columns[j.id] = [
                {**c, "stage": c["stage"].value, "category": c["category"].value}
                for c in cols
            ]
            off_template_counts[j.id] = off

    # 0341: status requestu (ta sama reguła co filtr) + podobne rekrutacje.
    from app.services import job_similarity as sim_service  # noqa: PLC0415

    request_state_map = await sim_service.request_statuses_and_stages(db, job_ids)
    similar_linked: dict[int, list[int]] = {}
    similar_briefs: dict[int, dict] = {}
    similar_suggested: dict[int, dict] = {}
    reassigned_map: dict[int, int] = {}
    if include_stage_counts and job_ids:
        similar_linked = await sim_service.linked_job_ids(db, job_ids)
        reassigned_map = await sim_service.reassign_counts(db, job_ids)
        first_linked = {ids[0] for ids in similar_linked.values() if ids}
        if first_linked:
            brief_rows = (
                await db.execute(
                    select(Job.id, Job.title, Job.reference_number).where(
                        Job.id.in_(first_linked)
                    )
                )
            ).all()
            similar_briefs = {
                r[0]: {"id": r[0], "title": r[1], "reference_number": r[2]}
                for r in brief_rows
            }
        try:
            similar_suggested = await sim_service.suggestion_summaries(
                db, jobs, similar_linked
            )
        except Exception:  # noqa: BLE001 — podpowiedź, nie warunek listy
            logger.exception("jobs list: similar suggestions failed")
            similar_suggested = {}

    # Hydrate primary_owner + collaborators in one pass (avoid N+1).
    collab_map = await _load_collaborator_map(db, job_ids)
    user_ids: set[int] = set()
    for j in jobs:
        if j.recruiter_id is not None:
            user_ids.add(j.recruiter_id)
        if j.delivery_lead_id is not None:
            user_ids.add(j.delivery_lead_id)
    for entries in collab_map.values():
        user_ids.update(uid for uid, _source in entries)
    user_brief_map = await _hydrate_owner_map(db, user_ids)
    # Rola „Rekruter” — jedno wywołanie na stronę, ta sama reguła co filtr
    # `worked_by` i pulpit „Requesty i obłożenie” (`services/job_team`).
    recruiters_by_job = await recruiters_for_jobs(db, job_ids)

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
        delivery_lead = (
            user_brief_map.get(j.delivery_lead_id)
            if j.delivery_lead_id is not None
            else None
        )
        d["delivery_lead_user"] = (
            delivery_lead.model_dump() if delivery_lead is not None else None
        )
        d["collaborators"] = _collaborator_payload(
            collab_map.get(j.id, []), user_brief_map
        )
        d["recruiters"] = _recruiters_payload(recruiters_by_job.get(j.id, []))
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
            d["stage_columns"] = stage_columns.get(j.id, [])
            d["off_template_count"] = off_template_counts.get(j.id, 0)
            needs_n, review_n = attention_by_job.get(j.id, (0, 0))
            d["needs_action_count"] = needs_n
            # Stos wejściowy (Ogłoszenia, Nowi) — osobno od „wymaga ruchu".
            d["review_count"] = review_n
            d["open_proposals_count"] = open_proposals.get(j.id, 0)
            linked_ids = similar_linked.get(j.id, [])
            d["similar"] = {
                "linked_count": len(linked_ids),
                "linked_first": (
                    similar_briefs.get(linked_ids[0]) if linked_ids else None
                ),
                "reassigned_count": reassigned_map.get(j.id, 0),
                "suggested": similar_suggested.get(j.id),
            }
        request_status_value, request_stage_value = request_state_map.get(
            j.id, ("searching", "to_review")
        )
        d["request_status"] = request_status_value
        d["request_stage"] = request_stage_value
        d["visible_work_state"] = _visible_work_state(j.work_state, j.champion_found_at)
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


# Trasa MUSI stać przed ``GET /{job_id}`` — FastAPI dopasowuje w kolejności
# deklaracji, więc zarejestrowana później „quick-counts" wpadłaby w parametr
# ścieżki i skończyła się 422 (ten sam powód, dla którego „/train-names" też
# stoi wyżej).
@router.get("/quick-counts")
async def jobs_quick_counts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    deadline_from: Optional[date] = Query(
        None,
        description=(
            "Lower bound of the 'Deadline ≤ 7 dni' window. Defaults to today. "
            "The list view sends the window IT uses, so the counter can never "
            "disagree with the rows the same filter returns."
        ),
    ),
    deadline_to: Optional[date] = Query(
        None,
        description=(
            "Upper bound of the 'Deadline ≤ 7 dni' window. Defaults to today + 7 days."
        ),
    ),
    overdue_to: Optional[date] = Query(
        None,
        description=(
            "Ostatni dzień okna „Po terminie” (termin do wczoraj włącznie). "
            "Lista wysyła tę samą datę, którą przekazuje filtrowi terminu. "
            "Domyślnie wczoraj."
        ),
    ),
):
    """Liczniki sześciu filtrów „Szybkie" — GLOBALNE, nie „z tej strony".

    Do 09.2026 lista potrafiła podać tylko jedną z tych liczb i tylko dla już
    wczytanej strony wyników (``lib/jobs-quick-filters.ts``).  „63" przy filtrze
    znaczyło wtedy „63 na dwudziestu widocznych wierszach", a nie „63 w bazie" —
    czyli liczbę, której nikt nie potrafił zinterpretować.

    Każdy licznik używa **tego samego predykatu**, co odpowiadający mu filtr
    w ``list_jobs`` (funkcje ``jobs_*_clause`` wyżej), więc kliknięcie filtra nie
    może dać innej liczby wierszy niż ta wypisana obok jego nazwy.

    Zakres widoczności jest ten sam co rejestru: świadomie ogólnofirmowy (patrz
    komentarz przy zapytaniu w ``list_jobs``).  Liczniki NIE są zawężane
    pozostałymi aktywnymi filtrami — opisują całą bazę, tak jak w makiecie.

    Wszystko idzie JEDNYM zapytaniem (``count(*) FILTER (WHERE …)``), a nie
    sześcioma — sześć osobnych rund po bazie przy każdej zmianie filtra jest
    dokładnie tym kosztem, przez który tych liczników wcześniej nie było.
    """
    today = business_today()
    window_from = deadline_from if deadline_from is not None else today
    window_to = deadline_to if deadline_to is not None else today + timedelta(days=7)
    deadline_clauses = jobs_deadline_clauses(window_from, window_to)

    row = (
        await db.execute(
            select(
                # Cały rejestr — licznik segmentu „Wszystkie" obok „Moje".
                func.count().label("all_jobs"),
                func.count().filter(jobs_mine_scope_clause(current_user)).label("mine"),
                func.count().filter(jobs_open_only_clause()).label("open"),
                func.count()
                .filter(jobs_needs_sourcing_clause())
                .label("needs_sourcing"),
                func.count()
                .filter(jobs_active_in_search_clause())
                .label("active_in_search"),
                func.count().filter(jobs_owner_missing_clause()).label("owner_missing"),
                func.count().filter(and_(*deadline_clauses)).label("deadline_7d"),
                func.count()
                .filter(jobs_my_category_clause(current_user))
                .label("my_category"),
            )
            .select_from(Job)
            .where(jobs_register_base_clause())
        )
    ).one()
    # Zakres „Moja kategoria” istnieje tylko dla osoby, która ma kategorię —
    # dla reszty `null`, żeby front go nie pokazywał (zero znaczyłoby „masz
    # kategorię, tylko bez rekrutacji”).
    has_category = (
        await db.scalar(
            select(UserCompetenceCategory.id)
            .where(UserCompetenceCategory.user_id == current_user.id)
            .limit(1)
        )
    ) is not None

    # Liczniki pigułek „Status requestu" — TO SAMO wyrażenie co filtr
    # ``request_status`` w ``list_jobs`` (``request_status_expr``), jedno GROUP BY
    # na cały rejestr. Obok liczby dla całego rejestru idzie liczba „moich"
    # (``count() FILTER``), żeby pigułki w zakresie „Moje" nie obiecywały
    # tysięcy wierszy, których ten zakres nie pokaże. Statusy inne niż
    # ``closed`` dotyczą z definicji tylko rekrutacji niezamkniętych, więc
    # liczba „rejestru" jest zarazem liczbą w zakresie „Otwarte".
    from app.services import job_similarity as _sim  # noqa: PLC0415

    # Ostatnie etapy par (``DISTINCT ON`` po ``candidate_stages``) tylko dla
    # NIEZAMKNIĘTYCH: „closed" wynika z samego ``jobs.status`` (pierwsza gałąź
    # ``request_status_expr``), a zamkniętych z Traffita jest ~4 tys. Zamknięta
    # rekrutacja łączy się z pustym wierszem podzapytania i dalej liczy się
    # jako „closed" — liczby bez zmian (audyt 24.09.2026).
    register_ids = select(Job.id).where(
        jobs_register_base_clause(), jobs_open_only_clause()
    )
    status_sq = _sim.request_status_subquery(register_ids)
    # Status liczony w podzapytaniu, grupowanie po jego kolumnie: `CASE`
    # z parametrami w SELECT i GROUP BY dostałby dwa różne zestawy `$n`
    # i Postgres nie uznałby ich za to samo wyrażenie.
    # „Nikogo nie wysłano” — ta sama liczba osób co filtr ``max_sent=0``;
    # oba zakresy z liczbami („Otwarte”, „Moje”) są niezamknięte (R7-N8-1).
    sent_ids = select(Job.id).where(
        jobs_register_base_clause(), jobs_open_only_clause()
    )
    sent_sq = jobs_sent_to_client_subquery(sent_ids)
    overdue_until = overdue_to if overdue_to is not None else today - timedelta(days=1)
    per_job = (
        select(
            _sim.request_status_expr(status_sq).label("status"),
            _sim.request_stage_expr(status_sq).label("stage"),
            jobs_mine_scope_clause(current_user).label("is_mine"),
            jobs_open_only_clause().label("is_open"),
            and_(*jobs_deadline_clauses(None, overdue_until)).label("overdue"),
            jobs_nobody_working_clause().label("nobody_working"),
            (func.coalesce(sent_sq.c.sent_n, 0) == 0).label("nobody_sent"),
        )
        .select_from(Job)
        .outerjoin(status_sq, status_sq.c.job_id == Job.id)
        .outerjoin(sent_sq, sent_sq.c.job_id == Job.id)
        .where(jobs_register_base_clause())
        .subquery()
    )
    status_rows = (
        await db.execute(
            select(
                per_job.c.status,
                func.count().label("n"),
                func.count().filter(per_job.c.is_mine).label("mine_n"),
            ).group_by(per_job.c.status)
        )
    ).all()
    request_status_counts = {value: 0 for value in _sim.REQUEST_STATUSES}
    request_status_mine = {value: 0 for value in _sim.REQUEST_STATUSES}
    for status_row in status_rows:
        request_status_counts[status_row.status] = int(status_row.n)
        request_status_mine[status_row.status] = int(status_row.mine_n)

    # Pigułki „Stan requestu” (25.09.2026) — ``request_stage_expr``, to samo
    # wyrażenie co filtr ``request_stage``.
    stage_rows = (
        await db.execute(
            select(
                per_job.c.stage,
                func.count().label("n"),
                func.count().filter(per_job.c.is_mine).label("mine_n"),
            ).group_by(per_job.c.stage)
        )
    ).all()
    request_stage_counts = {value: 0 for value in _sim.REQUEST_STAGES}
    request_stage_mine = {value: 0 for value in _sim.REQUEST_STAGES}
    for stage_row in stage_rows:
        request_stage_counts[stage_row.stage] = int(stage_row.n)
        request_stage_mine[stage_row.stage] = int(stage_row.mine_n)

    # Trzy przełączniki paska („Po terminie”, „Bez rekrutera”, „Nikogo nie
    # wysłano”) — dla zakresu „Otwarte” i „Moje”. Zakres „Wszystkie” nie ma
    # liczb: objąłby archiwum, które dla tych pytań nie ma sensu. „Moja
    # kategoria” ma tylko liczbę zakresu (`my_category`), bez rozbicia.
    attention_row = (
        await db.execute(
            select(
                *(
                    func.count()
                    .filter(and_(scope_col, getattr(per_job.c, flag)))
                    .label(f"{scope_name}_{flag}")
                    for scope_name, scope_col in (
                        ("open", per_job.c.is_open),
                        ("mine", per_job.c.is_mine),
                    )
                    for flag in ("overdue", "nobody_working", "nobody_sent")
                )
            )
        )
    ).one()
    attention = {
        scope_name: {
            flag: int(getattr(attention_row, f"{scope_name}_{flag}"))
            for flag in ("overdue", "nobody_working", "nobody_sent")
        }
        for scope_name in ("open", "mine")
    }

    return {
        "all": row.all_jobs,
        "mine": row.mine,
        "my_category": row.my_category if has_category else None,
        "open": row.open,
        "needs_sourcing": row.needs_sourcing,
        "active_in_search": row.active_in_search,
        "owner_missing": row.owner_missing,
        "deadline_7d": row.deadline_7d,
        "request_status": request_status_counts,
        "request_status_mine": request_status_mine,
        "request_stage": request_stage_counts,
        "request_stage_mine": request_stage_mine,
        "attention": attention["open"],
        "attention_mine": attention["mine"],
    }


def _policy_value(policy: Any) -> Optional[str]:
    return getattr(policy, "value", policy)


def _office_days_error(exc: ValueError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _normalize_office_days_for_create(payload: dict) -> None:
    """Dni w biurze: wpis miesięczny wyznacza tygodniowy (0407)."""
    from app.services import office_days

    try:
        week, month = office_days.normalize(
            payload.get("onsite_days_per_week"),
            payload.get("onsite_days_per_month"),
            _policy_value(payload.get("remote_policy")),
        )
    except ValueError as exc:
        raise _office_days_error(exc) from exc
    payload["onsite_days_per_week"] = week
    payload["onsite_days_per_month"] = month


def _normalize_office_days_for_update(job: Job, updates: dict) -> None:
    """PATCH: wpis tygodniowy czyści miesięczny, miesięczny wyznacza tygodniowy.

    Zmiana trybu na inny niż hybrydowy zdejmuje zapisany wpis miesięczny
    (tygodniowa liczba zostaje); jawny wpis miesięczny przy takim trybie = 422.
    """
    from app.services import office_days

    policy = _policy_value(updates.get("remote_policy", job.remote_policy))
    if "onsite_days_per_month" in updates:
        week = updates.get("onsite_days_per_week", job.onsite_days_per_week)
        try:
            week, month = office_days.normalize(
                week, updates["onsite_days_per_month"], policy
            )
        except ValueError as exc:
            raise _office_days_error(exc) from exc
        if month is not None or "onsite_days_per_week" in updates:
            updates["onsite_days_per_week"] = week
        updates["onsite_days_per_month"] = month
    elif "onsite_days_per_week" in updates:
        updates["onsite_days_per_month"] = None
    elif (
        job.onsite_days_per_month is not None
        and policy is not None
        and policy != "hybrid"
    ):
        updates["onsite_days_per_month"] = None


def _normalize_budget_range_for_update(job: Job, updates: dict) -> None:
    """PATCH: „od” musi być mniejsze niż budżet (0420).

    Jawnie wysłane „od” nie mniejsze od budżetu = 422 (pole widać w oknie
    edycji). Sama zmiana budżetu poniżej zapisanego „od” czyści „od” —
    budżetem jest górna granica, a „od” jest tylko do wyświetlania.
    """
    from app.services import job_budget_range
    from app.services.scoring_service import get_champion_hourly_rate

    if "rate_budget_hourly" not in updates and "rate_budget_hourly_min" not in updates:
        return
    budget = updates.get("rate_budget_hourly", job.rate_budget_hourly)
    if budget is None:
        budget = get_champion_hourly_rate(job)
    if "rate_budget_hourly_min" in updates:
        if not job_budget_range.min_below_max(
            updates["rate_budget_hourly_min"], budget
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=job_budget_range.MSG_MIN_NOT_BELOW_MAX,
            )
    elif not job_budget_range.min_below_max(job.rate_budget_hourly_min, budget):
        updates["rate_budget_hourly_min"] = None


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobCreate,
    current_user: RecruitmentManageUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Utworzenie rekrutacji = przekazanie do searchu = publikacja (04.10.2026).

    Jedno żądanie, JEDNA transakcja: wiersz rekrutacji, decyzja o hiring
    managerze, Profil Championa, bramka przekazania, przekazanie (rekruter albo
    automat), podobne rekrutacje, publikacja. Brak czegokolwiek, czego wymaga
    bramka „Przekaż do searchu”, = 422 ``job_not_ready`` z listą
    ``[{code, message}]`` — ``get_db`` cofa wtedy wszystko, więc szkic nie
    powstaje nigdy. Efekty po commicie (wektor, migawka dopasowań, Targ,
    powiadomienia) — dopiero po zapisie.
    """
    effects = job_lifecycle.PostCommit(background_tasks)
    # Kolejność blokad jak w `/owner` i automacie przydziału.
    await allocation_lock(db)
    job = await job_lifecycle.create_job_core(db, data, current_user, effects)
    await job_lifecycle.apply_hiring_manager_decision(
        db, job, data.hiring_manager, current_user
    )
    await job_lifecycle.save_champion_core(
        db, job, data.champion_profile, current_user, effects, notify=False
    )
    job_lifecycle.clear_decision_flags(job)
    await db.flush()
    job_lifecycle.ensure_handoff_ready(job)
    await job_lifecycle.handoff_core(db, job, data.handoff, current_user, effects)
    await job_lifecycle.link_similar_on_create(
        db, job, data.similar_job_ids, current_user
    )
    await job_lifecycle.publish_core(
        db, job, current_user, effects, sync_status_payload=False
    )
    job_lifecycle.record_cc_override(db, job, data.cc_override, current_user)
    await job_lifecycle.delete_intake_form(db, data.intake_form_id, current_user.id)
    await db.commit()
    await job_lifecycle.run_post_commit(effects)
    # Efekty (klasyfikator kategorii, wektor) mogą commitować — świeży odczyt
    # przed walidacją odpowiedzi (wygasły atrybut w async = MissingGreenlet).
    await db.refresh(job)
    response = JobResponse.model_validate(job).model_dump()
    response = await _populate_hiring_manager_name(db, response, job)
    response["snapshot_id"] = effects.results.get("snapshot_id")
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


@router.get("/hiring-manager-options", response_model=list[HiringManagerOption])
async def list_hiring_manager_options(
    current_user: JobEditUser,
    client_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
):
    """Kontakty klienta do wyboru hiring managera (25.09.2026).

    Osobna, wąska lista zamiast ``GET /api/clients/{id}/contacts``: tamta jest
    za bramką zespołu klienta, więc rekruter jej nie dostaje, a HM wybiera
    każdy, kto redaguje rekrutację. Tylko id, imię i nazwisko, stanowisko.
    """
    from app.services.job_hiring_manager import hiring_manager_options

    return await hiring_manager_options(db, client_id=client_id)


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
    collab_entries = collab_map.get(job.id, [])
    user_ids: set[int] = {uid for uid, _source in collab_entries}
    if job.recruiter_id is not None:
        user_ids.add(job.recruiter_id)
    if job.delivery_lead_id is not None:
        user_ids.add(job.delivery_lead_id)
    user_brief_map = await _hydrate_owner_map(db, user_ids)

    payload = JobResponse.model_validate(job).model_dump()
    payload["primary_owner"] = (
        user_brief_map[job.recruiter_id].model_dump()
        if job.recruiter_id in user_brief_map
        else None
    )
    # Brief Profilu Championa pokazuje DL („Kto prowadzi”) z tej odpowiedzi.
    payload["delivery_lead_user"] = (
        user_brief_map[job.delivery_lead_id].model_dump()
        if job.delivery_lead_id in user_brief_map
        else None
    )
    payload["collaborators"] = _collaborator_payload(collab_entries, user_brief_map)
    # Rola „Rekruter” — ta sama reguła i ten sam loader co wiersz listy.
    payload["recruiters"] = _recruiters_payload(
        (await recruiters_for_jobs(db, [job.id])).get(job.id, [])
    )

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
    # Tablica i warsztat „CV do klienta" pokazują pole stawki do klienta TYLKO
    # osobom, które mogą ją zapisać (ta sama funkcja co bramka PATCH).
    payload["can_write_client_rate"] = await resolve_client_rate_write(
        db, current_user, job
    )
    # Czy bieżący użytkownik redaguje tę rekrutację (opis, ogłoszenia,
    # Champion) i czy prowadzi jej cykl życia — ta sama reguła co bramka PATCH.
    pipeline_writer = (
        section_access_for_user(current_user, ProductSection.pipeline)
        >= SectionAccess.write
    )
    edit_level = (
        await job_edit_level(db, current_user, job) if pipeline_writer else None
    )
    payload["can_edit"] = edit_level is not None
    payload["can_manage"] = edit_level is JobEditLevel.full
    # Kto przydziela i zdejmuje rekruterów (bramka `/owner`) i kto ustawia
    # priorytet (wyjątek w `ensure_job_editor`) — Head of Recruitment ma oba
    # bez pełnej redakcji, więc `can_manage` tego nie wyraża (02.10.2026).
    payload["can_staff"] = pipeline_writer and await user_can_staff_job(
        db, current_user, job
    )
    payload["can_set_priority"] = pipeline_writer and await user_can_set_job_priority(
        db, current_user, job
    )
    # 0341: status requestu — ta sama reguła co wiersz listy.
    from app.services.job_similarity import request_statuses  # noqa: PLC0415

    payload["request_status"] = (await request_statuses(db, [job.id])).get(job.id)
    from app.services.board_stage_badges import cpro_enabled_for_client  # noqa: PLC0415

    payload["cpro_enabled"] = cpro_enabled_for_client(job.client_id)
    # 0353: jedna osoba wysyła do Cpro kandydatów tej rekrutacji.
    payload["cpro_sender_id"] = job.cpro_sender_id if payload["cpro_enabled"] else None
    payload["cpro_sender_name"] = (
        await db.scalar(
            select(func.coalesce(User.name, User.email)).where(
                User.id == job.cpro_sender_id
            )
        )
        if payload["cpro_sender_id"] is not None
        else None
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
    current_user: JobEditUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Zmiana rekrutera rusza przypisania do requestu, a te chroni blokada
    # przydziału — bierzemy ją PRZED wierszem rekrutacji (kolejność z
    # `allocation_lock`, ta sama co `/owner`) i tylko gdy żądanie niesie to pole.
    # Rekrutera zmienia w PATCH wyłącznie osoba z pełną redakcją (uprawnienie
    # do prowadzenia rekrutacji — `JOB_MEMBER_LOCKED_FIELDS`); pozostali
    # dostaną 403 niżej, więc nie zajmują globalnej blokady na czas odmowy.
    if "recruiter_id" in data.model_fields_set and has_permission(
        current_user, ProductAction.recruitment_manage
    ):
        await allocation_lock(db)
    result = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    _assert_delivery_lead_job_visible(job, delivery_lead_pairs)
    # Treść rekrutacji redaguje też osoba, która ją prowadzi, i współpracownicy
    # (decyzja 22.09.2026) — ale bez statusu, klienta, obsady i widełek.
    await ensure_job_editor(db, current_user, job, fields=data.model_fields_set)
    _assert_delivery_lead_finance_write(data.model_fields_set, current_user)

    # Rekrutacja bez szkiców (04.10.2026): okno edycji nie robi z rekrutacji
    # szkicu ani jej nie otwiera — otwarcie zamkniętej przechodzi bramkę
    # przekazania w `POST …/publish` („Otwórz ponownie”). Ten sam status co
    # obecny (okno odsyła komplet pól) przechodzi bez zmian.
    if "status" in data.model_fields_set and data.status != job.status:
        if data.status == JobStatus.draft:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "draft_not_allowed",
                    "message": "Rekrutacja nie może wrócić do szkicu.",
                },
            )
        if data.status == JobStatus.published:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "reopen_required",
                    "message": (
                        "Zamkniętą rekrutację otwórz przyciskiem „Otwórz ponownie”."
                    ),
                },
            )
    # Ochrona rekrutacji w pracy: zapis odmawia tylko przy NOWYM braku bramki
    # przekazania (porównanie po kodach, przed i po zapisie).
    regression_baseline = job_lifecycle.regression_baseline(job)

    # Validate explicit owner overrides before applying any mutations.
    # Walidujemy wyłącznie REALNĄ zmianę wartości (runda 6 audytu), bo okno
    # edycji rekrutacji odsyła `client_id` i `delivery_lead_id` przy każdym
    # zapisie — rekrutacja z nieaktywnym już DL-em albo TAC-iem bez przypisania
    # do klienta nie dawała się wtedy zapisać w ogóle, choć nikt tych pól nie
    # ruszał.
    sent = data.model_fields_set
    tac_changed = "tac_id" in sent and data.tac_id != job.tac_id
    client_changed = "client_id" in sent and data.client_id != job.client_id
    hiring_manager_changed = (
        "hiring_manager_contact_id" in sent
        and data.hiring_manager_contact_id != job.hiring_manager_contact_id
    )
    delivery_lead_changed = (
        "delivery_lead_id" in sent and data.delivery_lead_id != job.delivery_lead_id
    )
    recruiter_changed = "recruiter_id" in sent and data.recruiter_id != job.recruiter_id
    if client_changed:
        await assert_client_assignable(db, data.client_id)
    elif (
        "status" in sent
        and data.status is not None
        and data.status != JobStatus.closed
        and job.status == JobStatus.closed
    ):
        # Runda 9 (R9-N4-1): ponowne otwarcie rekrutacji usuniętego albo
        # scalonego klienta dawało żywą rekrutację, której nie widać w żadnym
        # rejestrze (lustro zakładania — `create_job`).
        await assert_client_assignable(db, job.client_id)
    if tac_changed and data.tac_id is not None:
        await _validate_owner_override(
            db,
            user_id=data.tac_id,
            allowed_roles=TAC_ASSIGNABLE_ROLES,
            field="tac_id",
        )

    # Changing either half of the relationship must leave a valid pair.  We
    # intentionally do not re-validate untouched historical Jobs during the
    # expand phase; only explicit owner/client mutations cross this gate.
    if tac_changed or client_changed:
        effective_tac_id = data.tac_id if "tac_id" in sent else job.tac_id
        effective_client_id = data.client_id if "client_id" in sent else job.client_id
        if effective_tac_id is not None and effective_client_id is not None:
            await _validate_tac_client_assignment(
                db,
                user_id=effective_tac_id,
                client_id=effective_client_id,
            )
    if delivery_lead_changed and data.delivery_lead_id is not None:
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
    # Runda 8 (R8-X1-3): tylko przy realnej zmianie — formularz odsyła
    # niezmienionego (także nieaktywnego już) prowadzącego przy każdym zapisie.
    if recruiter_changed and data.recruiter_id is not None:
        await _validate_owner_override(
            db,
            user_id=data.recruiter_id,
            allowed_roles=set(_HANDOFF_RECRUITER_ROLES),
            field="recruiter_id",
        )

    # Runda 9 (R9-N15-5): tylko przy realnej zmianie — okno edycji odsyła
    # komplet pól przy każdym zapisie.
    await _assert_job_references_valid(
        db,
        job_id=job.id,
        pipeline_template_id=(
            data.pipeline_template_id
            if "pipeline_template_id" in sent
            and data.pipeline_template_id != job.pipeline_template_id
            else None
        ),
        competence_category_id=(
            data.competence_category_id
            if "competence_category_id" in sent
            and data.competence_category_id != job.competence_category_id
            else None
        ),
        reference_number=(
            data.reference_number
            if "reference_number" in sent
            and data.reference_number != job.reference_number
            else None
        ),
    )

    updates = data.model_dump(exclude_unset=True)
    _assert_skill_columns_follow_rows(job, updates)
    _normalize_deadline_time(updates, job.deadline)
    # Wejścia rankingu sprzed zapisu (runda 6 audytu): wektor i ranking
    # unieważnia REALNA zmiana wartości, nie sam klucz w żądaniu — okno edycji
    # odsyła tytuł, lokalizację i tryb pracy przy każdym zapisie.
    _scoring_before = {f: getattr(job, f) for f in _SCORING_INPUT_FIELDS}
    if (
        "delivery_lead_id" in updates
        and updates["delivery_lead_id"] != job.delivery_lead_id
    ):
        # Ręczna zmiana DL-a: od teraz nietykalny dla `job_delivery_lead_fill`.
        job.delivery_lead_auto_filled = False
    # 0380: ręczny tytuł dla rekrutera wyłącza automat, pusty go przywraca.
    working_title_reset = False
    if "working_title" in updates:
        manual = (updates["working_title"] or "").strip() or None
        updates["working_title"] = manual
        job.working_title_auto = manual is None
        working_title_reset = manual is None
    if "client_reference" in updates:
        from app.services.job_working_title import normalize_client_reference

        updates["client_reference"] = normalize_client_reference(
            updates["client_reference"]
        )
    if "champion_profile" in updates:
        from app.api.champion_intake import invalid_champion_profile
        from app.services.champion_intake import user_edit

        try:
            updates["champion_profile"] = user_edit(
                job.champion_profile,
                updates["champion_profile"] or {},
                current_user.id,
                actor_name=(current_user.name or "").strip() or current_user.email,
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise invalid_champion_profile(exc) from exc
    _normalize_office_days_for_update(job, updates)
    _normalize_budget_range_for_update(job, updates)
    from app.services.requirement_contract import invalidate_changed_requirements

    invalidate_changed_requirements(job, updates)
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
    # Budżet i warunki biura nie wpływają na Targ, ale zmieniają to, kogo
    # pokaże pełny przegląd bazy i auto-match (dealbreakery) — osobna lista,
    # żeby nie wywoływać nimi rescanów Targu.
    _review_before = {f: getattr(job, f) for f in _AUTO_REVIEW_EXTRA_FIELDS}
    _status_before = job.status
    _hiring_manager_before = job.hiring_manager_contact_id
    _recruiter_before = job.recruiter_id
    _category_before = job.competence_category_id
    for k, v in updates.items():
        setattr(job, k, v)
    _assert_delivery_lead_job_visible(job, delivery_lead_pairs)
    # Okno edycji zmienia rekrutera PATCH-em, nie przez `/owner` — rola
    # „Rekruter” ma po obu drogach wyglądać tak samo (02.10.2026): poprzednia
    # osoba traci aktywne przypisanie, nowa dostaje je w puli przydziału.
    if recruiter_changed and job.recruiter_id != _recruiter_before:
        await _sync_work_assignments_with_owner(
            db,
            job=job,
            previous_owner_id=_recruiter_before,
            owner=(
                await db.get(User, job.recruiter_id)
                if job.recruiter_id is not None
                else None
            ),
            actor_id=current_user.id,
        )
    # Hiring manager musi być kontaktem klienta rekrutacji. Jawnie wskazany
    # z innej firmy = 422; zmiana klienta zdejmuje HM poprzedniego klienta,
    # zamiast zostawić na rekrutacji osobę z cudzej firmy (25.09.2026).
    # Runda 7 (R7-X1-5): po zmianie WARTOŚCI, nie po kluczu żądania — okno
    # edycji odsyła `client_id` i HM przy każdym zapisie, więc HM z innej firmy
    # (np. po przeniesieniu rekrutacji między klientami) znikał razem z wetem
    # przy zapisie samego tytułu.
    if job.hiring_manager_contact_id is not None and (
        hiring_manager_changed or client_changed
    ):
        from app.services.job_hiring_manager import assert_contact_of_client

        if hiring_manager_changed:
            await assert_contact_of_client(
                db,
                contact_id=job.hiring_manager_contact_id,
                client_id=job.client_id,
            )
        else:
            from app.models.contact import Contact  # noqa: PLC0415

            hm_client_id = await db.scalar(
                select(Contact.client_id).where(
                    Contact.id == job.hiring_manager_contact_id
                )
            )
            if hm_client_id != job.client_id:
                job.hiring_manager_contact_id = None
                # 0415: HM zdjęty przez zmianę klienta to skutek tej zmiany,
                # nie nowy brak wprowadzony przez osobę — okno edycji wskazuje
                # nowego HM osobnym zapisem PO zmianie klienta (kontakt musi
                # należeć już do nowego klienta). Bez tego każda zmiana klienta
                # rekrutacji w pracy kończyła się 422 `handoff_regression`.
                if regression_baseline is not None:
                    regression_baseline.add("hiring_manager")
    if job.hiring_manager_contact_id != _hiring_manager_before:
        # Runda 10 (R10-V2-5): zmiana klienta zeruje HM — to też zdjęcie weta.
        await _assert_may_change_vetoing_manager(
            db, current_user, job_id=job.id, previous=_hiring_manager_before
        )
    if client_changed:
        # Runda 7 (N7-2): DL wpisany automatem należał do poprzedniego klienta.
        # Uzupełnienie wpisuje głównego DL-a nowego klienta albo zdejmuje
        # automatycznego DL-a; ręcznie wpisanego nie rusza.
        from app.services.job_delivery_lead_fill import (  # noqa: PLC0415
            fill_missing_job_delivery_leads,
        )

        if job.client_id is None:
            if job.delivery_lead_auto_filled:
                job.delivery_lead_id = None
                job.delivery_lead_auto_filled = False
        else:
            await db.flush()
            await fill_missing_job_delivery_leads(db, [job.client_id])
            await db.refresh(job, ["delivery_lead_id", "delivery_lead_auto_filled"])
        # Runda 9 (R9-V2-7): opis publiczny zatwierdzony przy starym kliencie
        # wraca do szkicu — ogłoszenia na portalach idą do zamknięcia.
        await close_postings_if_approved_for_other_client(db, job)
    if (
        working_title_reset
        or {
            "title",
            "must_skills",
            "client_reference",
            "champion_profile",
        }
        & updates.keys()
    ):
        from app.services.job_working_title import refresh_working_title

        await refresh_working_title(db, job)

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
            await set_work_state(
                db, job, "finished", actor_id=current_user.id, reason="job_closed"
            )
            await maybe_close_job_contact_opportunities(
                db,
                job_id=job_id,
                actor_user_id=current_user.id,
                reason="job_closed",
                occurred_at=job.closed_at,
            )
            # 0381: zamknięta rekrutacja zamyka ogłoszenia na portalach.
            await close_live_postings(db, job_id)
            # Audyt 06.10.2026 (R6): lustro `close_job_core` — otwarte
            # propozycje zamkniętej rekrutacji wygasają.
            from app.services.job_proposals import expire_open_for_job

            await expire_open_for_job(db, job_id=job_id)
        elif prev_status == JobStatus.closed:
            job.closed_at = None
            _take_over_reopened_traffit_job(db, job, current_user)
            # Lustro zamknięcia (0371): ponownie otwarta rekrutacja wraca do
            # „Do przejrzenia” — z „Zakończonego” wypadała z puli przydziału,
            # pulpitu „Requesty” i nocnego przeglądu bazy (audyt 24.09.2026).
            if job.work_state == WORK_STATE_FINISHED:
                await set_work_state(
                    db,
                    job,
                    WORK_STATE_REOPENED,
                    actor_id=current_user.id,
                    reason="job_reopened",
                )

    # Inna kategoria = inni uczestnicy: osoby poprzedniej kategorii schodzą,
    # osoby nowej dochodzą. Dopisani ręcznie i zdjęci z rekrutacji zostają.
    if job.competence_category_id != _category_before:
        from app.services.auto_cc_collaborators import sync_cc_participants

        # Savepoint jak przy tworzeniu: błąd synchronizacji nie cofa zapisu
        # rekrutacji — listę wyrówna pętla godzinowa.
        try:
            async with db.begin_nested():
                await sync_cc_participants(
                    db, job_ids=[job.id], added_by=current_user.id
                )
        except Exception:
            logger.exception(
                "[Job] synchronizacja uczestników kategorii nie powiodła się (job %s)",
                job.id,
            )

    changed = {f for f, old in _scoring_before.items() if getattr(job, f) != old}
    # 0415: zapisana wartość zdejmuje „Klient nie podał” — PO zdjęciu HM przy
    # zmianie klienta, żeby jawne „Klient nie podał” w tym samym zapisie zostało.
    job_lifecycle.clear_decision_flags(job)
    job_lifecycle.assert_no_new_handoff_blockers(regression_baseline, job)
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
        await _sync_job_status_payload(job)

    # Phase 2: re-embed if any embed-relevant field changed
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

    # Auto-match: publikacja albo istotna zmiana wymagań opublikowanej rekrutacji.
    if job.status == JobStatus.published and (
        _status_before != JobStatus.published
        or is_significant_job_update(
            _before, {f: getattr(job, f) for f in _before.keys()}
        )
        or any(getattr(job, f) != old for f, old in _review_before.items())
    ):
        from app.services.auto_match_outbox import enqueue_job_safe

        background_tasks.add_task(enqueue_job_safe, job_id)

    # Populate hiring_manager_name żeby PATCH response zawierał aktualną nazwę
    # bez konieczności re-fetcha GET /jobs/{id} po stronie UI.
    payload = JobResponse.model_validate(job).model_dump()
    payload = await _populate_hiring_manager_name(db, payload, job)
    return _redact_delivery_lead_job_finance(payload, current_user)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
):
    # Runda 7 (R7-N8-3): usunięcie rekrutacji trafia do Historii zdarzeń —
    # także odmowa. Do 26.09 ślad zostawał tylko w ``activities``.
    async with audited_deletion(
        db,
        actor=current_user,
        event_type="job.delete",
        entity_type="job",
        entity_id=job_id,
    ) as audit:
        result = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        audit.describe(
            label=f"Rekrutacja #{job.id} — {job.title}", client_id=job.client_id
        )
        await _ensure_delivery_lead_job_visible(job, current_user, db)
        # Runda 7 (R7-N8-3): zamknięta rekrutacja jest mianownikiem hit ratio Ligi
        # DL (``closed_at`` w kwartale) — jej usunięcie podnosiłoby wskaźnik, który
        # wypłaca nagrodę. Zamknięta zostaje w archiwum.
        if job.status == JobStatus.closed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "job_is_closed",
                    "message": "Zamkniętej rekrutacji nie usuwa się — zostaje "
                    "w archiwum i w statystykach.",
                },
            )
        # Runda 7 (R7-N8-4): rekrutację z Traffita nocny import założyłby od nowa
        # (upsert po ``external_id``) pod nowym id — usunięcie byłoby pozorne.
        if job.external_source == "traffit":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "job_from_traffit",
                    "message": "Rekrutacji z Traffita nie usuwa się — wróciłaby "
                    "z nocnym importem. Zamknij ją zamiast usuwać.",
                },
            )
        # 0381: kaskada skasowałaby wiersz publikacji, a ogłoszenie zostałoby na
        # portalu bez możliwości zamknięcia z NEXUSA.
        if await has_live_postings(db, job_id):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "job_has_live_postings",
                    "message": "Najpierw wycofaj ogłoszenia z portali — rekrutacja "
                    "jest opublikowana na zewnątrz.",
                },
            )
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
                select(func.count(CandidateStage.id)).where(
                    CandidateStage.job_id == job_id
                )
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
        # Runda 7 (R7-N8-5): ``calendar_events.job_id`` nie ma ON DELETE, a ``Job``
        # nie ma do nich relacji — bez tego zliczenia DELETE kończył się
        # ForeignKeyViolation → 500 zamiast czytelnej odmowy.
        from app.models.calendar_event import CalendarEvent  # noqa: PLC0415

        calendar_rows = int(
            await db.scalar(
                select(func.count(CalendarEvent.id)).where(
                    CalendarEvent.job_id == job_id
                )
            )
            or 0
        )
        if calendar_rows:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "job_has_calendar_events",
                    "calendar_event_rows": calendar_rows,
                    "message": "Rekrutacja ma spotkania w kalendarzu. Zamknij ją "
                    "zamiast usuwać albo najpierw usuń spotkania.",
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
        try:
            await db.flush()
        except IntegrityError:
            # Inne tabele bez ON DELETE (np. historia dopasowań, historia stawek)
            # — odmowa zamiast nieobsłużonego 500.
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "job_referenced",
                    "message": "Rekrutację wskazują inne zapisy w systemie. "
                    "Zamknij ją zamiast usuwać.",
                },
            ) from None
    await db.commit()


@router.post("/{job_id}/close", response_model=JobResponse)
async def close_job(
    job_id: int,
    data: JobCloseRequest,
    current_user: RecruitmentManageUser,
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
    if job.status == JobStatus.closed:
        # Runda 9 (R9-N15-4): ponowne zamknięcie przestawiało `closed_at`,
        # a hit ratio Ligi DL liczy rekrutacje zamknięte w kwartale po tej dacie.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_already_closed",
                "message": "Rekrutacja jest już zamknięta.",
            },
        )

    effects = job_lifecycle.PostCommit()
    await job_lifecycle.close_job_core(
        db,
        job,
        reason=data.reason,
        notes=data.notes,
        actor_id=current_user.id,
        effects=effects,
    )
    await db.commit()
    await db.refresh(job)
    await job_lifecycle.run_post_commit(effects)
    payload = JobResponse.model_validate(job).model_dump()
    return _redact_delivery_lead_job_finance(payload, current_user)


def _take_over_reopened_traffit_job(db: AsyncSession, job: Job, user) -> None:
    """Otwarta ponownie rekrutacja z Traffita przechodzi do NEXUSA.

    Rekrutacje z Traffita są w NEXUSIE archiwum (24.09.2026,
    `services/traffit_job_archive.py`) — nocny sync zamyka każdą, która nie jest
    „Prowadzona w NEXUSIE”. Kto ją otwiera z powrotem, prowadzi ją tutaj, więc
    przełącznik włącza się sam (z tym samym wpisem w historii co ręczny) —
    inaczej najbliższy sync zamknąłby ją znowu bez słowa.
    """
    if job.external_source != "traffit" or job.managed_in_nexus:
        return
    job.managed_in_nexus = True
    job.managed_in_nexus_at = datetime.now(timezone.utc)
    job.managed_in_nexus_by = user.id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="managed_in_nexus_changed",
            user_id=user.id,
            details={"enabled": True, "previous": False, "reason": "job_reopened"},
        )
    )


@router.post("/{job_id}/manage-in-nexus", response_model=JobResponse)
async def set_job_managed_in_nexus(
    job_id: int,
    data: JobManageInNexusRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Przełącznik „Rekrutacja prowadzona w NEXUSIE" (0325).

    Osobna trasa, nie pole w PATCH: przełączenie ma własny wpis w `activities`
    z poprzednią wartością, a formularz edycji nie może przełączyć „przy okazji".
    Idempotentna. Włącza każdy członek zespołu rekrutacji (``RecruiterPlus``
    + ``ensure_job_membership``; od 23.09.2026 bez wymogu roli TAC).
    Wyłączenie tylko z uprawnieniem „Rekrutacje: zakładanie, zamykanie,
    wysyłka CV do klienta” (domyślnie admin i Delivery Lead) — powrót do
    Traffita oznacza, że najbliższy import nadpisze ruchy zrobione w NEXUSIE.

    Członkostwo sprawdzane PO odczycie oferty: `ensure_job_membership` na
    nieistniejącej ofercie daje osobie spoza ról nadzoru 403, a nie 404.
    """
    job = (
        await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await ensure_job_membership(db, current_user, job_id)
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    if job.external_source != "traffit":
        raise HTTPException(
            status_code=409,
            detail=(
                "Ta rekrutacja nie pochodzi z Traffita — przełącznik nie ma "
                "zastosowania."
            ),
        )
    if not data.enabled:
        # Powrót do Traffita to decyzja o cyklu życia rekrutacji — to samo
        # uprawnienie co jej zamknięcie (odmowa nazywa je).
        ensure_permission(current_user, ProductAction.recruitment_manage)
    previous = bool(job.managed_in_nexus)
    if previous != data.enabled:
        job.managed_in_nexus = data.enabled
        job.managed_in_nexus_at = datetime.now(timezone.utc)
        job.managed_in_nexus_by = current_user.id
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="managed_in_nexus_changed",
                user_id=current_user.id,
                details={"enabled": data.enabled, "previous": previous},
            )
        )
        await db.commit()
        # `updated_at` ma serwerowy `onupdate` — po UPDATE atrybut jest wygasły.
        await db.refresh(job)
    else:
        # Commit, nie rollback: zwalnia blokadę FOR UPDATE, a `rollback()`
        # wygasiłby `current_user`, którego `get_job` jeszcze używa.
        await db.commit()
    return await get_job(job_id=job_id, current_user=current_user, db=db)


async def _assert_may_change_vetoing_manager(
    db: AsyncSession, user: User, *, job_id: int, previous: Optional[int]
) -> None:
    """Runda 10 (R10-V2-5): zmiana albo wyczyszczenie HM rekrutacji, której
    pary niosą weto tego managera, zdejmuje weto we wszystkich jego
    rekrutacjach. Jak przy usunięciu pary (R9-N11-5) — tylko admin albo HoR."""
    if previous is None or user.has_any_role(
        UserRole.admin, UserRole.head_of_recruitment
    ):
        return
    from app.services.hiring_manager_verdicts import job_carries_manager_veto

    if await job_carries_manager_veto(db, job_id=job_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Nie można zmienić hiring managera — odrzucił on w tej "
                "rekrutacji osobę po rozmowie, a zmiana zdjęłaby jego weto "
                "we wszystkich jego rekrutacjach. Zrobi to admin albo Head "
                "of Recruitment."
            ),
        )


@router.put("/{job_id}/hiring-manager", response_model=JobResponse)
async def set_job_hiring_manager(
    job_id: int,
    data: JobHiringManagerRequest,
    current_user: JobEditUser,
    db: AsyncSession = Depends(get_db),
):
    """Hiring manager rekrutacji: kontakt z listy, nowa osoba, „Klient nie
    podał” (0415) albo brak (25.09.2026).

    Nową osobę zakłada serwis jako kontakt KLIENTA tej rekrutacji — po
    dopasowaniu do istniejących kontaktów, żeby weto HM nie rozbiło się na
    duplikaty. Bramka jak w PATCH: pole nie jest w ``JOB_MEMBER_LOCKED_FIELDS``,
    więc rekruter prowadzący i współpracownicy też je ustawiają (decyzja
    Artura), bez uprawnienia do edycji kontaktów klienta.
    """
    job = (
        await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
    _assert_delivery_lead_job_visible(job, delivery_lead_pairs)
    await ensure_job_editor(db, current_user, job, fields={"hiring_manager_contact_id"})

    # Rekrutacja w pracy: wyczyszczenie HM bez „Klient nie podał” byłoby
    # nowym brakiem bramki przekazania (04.10.2026).
    regression_baseline = job_lifecycle.regression_baseline(job)
    await job_lifecycle.apply_hiring_manager_decision(db, job, data, current_user)
    job_lifecycle.assert_no_new_handoff_blockers(regression_baseline, job)
    # Commit także bez zmiany: zwalnia blokadę FOR UPDATE i zapisuje ewentualne
    # uzupełnienie pustego stanowiska/e-maila kontaktu (fill-only).
    await db.commit()
    await db.refresh(job)
    return await get_job(job_id=job_id, current_user=current_user, db=db)


@router.post("/{job_id}/publish")
async def publish_job(
    job_id: int,
    current_user: RecruitmentManageUser,
    background_tasks: BackgroundTasks,
    payload: Optional[JobPublishRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """„Otwórz ponownie” — publikacja przez bramkę przekazania (04.10.2026).

    Rekrutacja nigdy nie jest szkicem: otwarcie zamkniętej, dokończenie starego
    szkicu albo rekrutacji opublikowanej bez przekazania wymaga przekazania do
    searchu (ciało jak ``/handoff``) i przechodzi tę samą bramkę braków co
    zakładanie — z pytaniami liczonymi także przy ``is_open``. Brak = 422
    ``job_not_ready`` i nic się nie zmienia. Rekrutacja już w pracy
    (opublikowana i przekazana) = 200 bez zmian.
    """
    await allocation_lock(db)
    result = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    if job.status == JobStatus.published and job.is_open:
        return {"status": "published", "job_id": job_id, "unchanged": True}
    if payload is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "handoff_required",
                "message": (
                    "Otwarcie rekrutacji wymaga przekazania do searchu — wybierz "
                    "rekrutera albo przydział automatyczny."
                ),
            },
        )
    effects = job_lifecycle.PostCommit(background_tasks)
    await job_lifecycle.publish_core(
        db, job, current_user, effects, reason=payload.reason
    )
    job_lifecycle.ensure_handoff_ready(
        job, message=job_lifecycle.MSG_NOT_REOPENED, include_open=True
    )
    handoff = await job_lifecycle.handoff_core(db, job, payload, current_user, effects)
    await db.commit()
    await job_lifecycle.run_post_commit(effects)
    return {
        "status": "published",
        "job_id": job_id,
        "recruiter_id": handoff.get("recruiter_id"),
        "snapshot_id": effects.results.get("snapshot_id"),
    }


# ── Champion Profile (Phase 10) ─────────────────────────────────────────────


# Alias na `champion_view.api_response` — normalizacja profilu do siedmiu sekcji
# mieszka tam, gdzie reszta wiedzy o obu kształtach, a nie w routerze. Nazwa
# zostaje krótka, bo pojawia się w dziewięciu miejscach tego pliku.
_champion_response = champion_view.api_response


@router.get("/{job_id}/champion-profile")
async def get_champion_profile(
    job_id: int,
    request: Request,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    mark_read: bool = Query(True),
) -> dict:
    """Return the Delivery Lead's Champion Profile for this job (or {}).

    Side effect: any unread ``champion_profile_updated`` notifications
    addressed to the caller for this specific job are marked as read —
    this implements "powiadomienie znika jak Rekruter otworzy" regardless
    of whether the user arrived via the notification dropdown, a direct
    URL, or an internal link.

    Runda 9 (R9-N1-2, R9-V2-4): nic nie oznaczamy w „podglądzie jako”
    (admin czyta cudzy ekran, powiadomienia należą do podglądanej osoby) ani
    przy ``mark_read=false`` — tak czyta profil kopiowanie szablonu na
    ``/jobs/new``, gdzie nikt tej rekrutacji nie otwiera.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    previewing = getattr(request.state, "impersonator_id", None) is not None
    if mark_read and not previewing:
        await db.execute(
            sql_update(Notification)
            .where(
                Notification.user_id == current_user.id,
                Notification.notification_type
                == NotificationType.champion_profile_updated,
                Notification.related_entity_type == "job",
                Notification.related_entity_id == job_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await db.commit()

    from app.services.champion_intake import response_context

    return {
        **response_context(job),
        "job_id": job.id,
        "job_title": job.title,
        "champion_profile": _champion_response(job.champion_profile),
    }


async def _champion_profile_recipients(
    db: AsyncSession, job: Job, exclude_user_id: int, *, link: str
) -> list[int]:
    """Return the distinct user ids that should be notified of a CP edit.

    The set is the primary ``recruiter_id`` plus everyone in
    ``job_collaborators`` — minus the editor themselves. Nulls are
    filtered out.

    Runda 9 (R9-N2-7): bez współpracowników zdjętych z auto-CC
    (``removed_from_auto_cc``) i przez bramkę odbiorcy
    (``filter_notification_recipients``: aktywne konto, sekcja, wyciszenia) —
    do tej rundy dzwonek dostawały też konta nieaktywne i osoby wypisane
    z rekrutacji.
    """
    from app.services.notification_access import filter_notification_recipients

    # 06.10.2026 (D7): uczestnicy z kategorii (`auto_cc`) nie dostają dzwonków
    # rekrutacji — widzą ją w „Moja kategoria”. Delivery Lead rekrutacji
    # dostaje dzwonek (N2): do tej daty zmiany rekrutera w Championie
    # docierały do DL-a w 6 z 49 par, więc DL nadpisywał je nieświadomie.
    rows = await db.execute(
        select(JobCollaborator.user_id).where(
            JobCollaborator.job_id == job.id,
            JobCollaborator.removed_from_auto_cc.is_(False),
            JobCollaborator.source != JobCollaboratorSource.auto_cc,
        )
    )
    collaborator_ids = {uid for (uid,) in rows.all() if uid is not None}
    if job.recruiter_id is not None:
        collaborator_ids.add(job.recruiter_id)
    if job.delivery_lead_id is not None:
        collaborator_ids.add(job.delivery_lead_id)
    collaborator_ids.discard(exclude_user_id)
    allowed = await filter_notification_recipients(
        db,
        collaborator_ids,
        NotificationType.champion_profile_updated,
        related_entity_type="job",
        link=link,
    )
    return sorted(user.id for user in allowed)


@router.put("/{job_id}/champion-profile")
async def update_champion_profile(
    job_id: int,
    current_user: JobEditUser,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
) -> dict:
    # Audyt 06.10.2026 (N2): edytor wysyła odcisk profilu, który wczytał —
    # zapis na profilu zmienionym w międzyczasie kończy się 409, nie
    # nadpisaniem. Klucz nie jest sekcją profilu, więc zdejmujemy go z ładunku.
    body = dict(payload or {})
    expected = body.pop("expected_profile_hash", None)
    if expected is not None and not isinstance(expected, str):
        raise HTTPException(422, "expected_profile_hash musi być tekstem.")
    return await _save_champion_profile(
        job_id, current_user, db, body, expected_profile_hash=expected
    )


@router.post("/{job_id}/champion-profile/apply-import")
async def apply_champion_import(
    job_id: int,
    current_user: JobEditUser,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.champion_intake import SYNC_FIELDS

    expected = payload.get("expected_fingerprint")
    fields = payload.get("sync_fields", [])
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or not isinstance(payload.get("profile"), dict)
    ):
        raise HTTPException(422, "Wymagany jest profil i odcisk aktualnego podglądu.")
    if not isinstance(fields, list) or any(
        not isinstance(field, str) or field not in SYNC_FIELDS for field in fields
    ):
        raise HTTPException(422, "Nieznane pole uzgodnienia rekrutacji.")
    return await _save_champion_profile(
        job_id,
        current_user,
        db,
        payload["profile"],
        imported=True,
        expected_fingerprint=expected,
        sync_fields=fields,
    )


async def _save_champion_profile(
    job_id: int,
    current_user: User,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
    *,
    imported: bool = False,
    expected_fingerprint: str | None = None,
    sync_fields: list[str] | None = None,
    expected_profile_hash: str | None = None,
) -> dict:
    """Upsert Champion Profile (Delivery Lead / admin / zespół rekrutacji).

    Rdzeń zapisu (``job_lifecycle.save_champion_core``) robi wszystko bez
    commitu; tu blokada wiersza, commit i efekty po commicie (przeliczenie
    dopasowań, auto-match, WebSocket ``champion_profile_changed``). Rekrutacja
    w pracy odmawia 422 ``handoff_regression`` przy zapisie, który zostawia
    nowy brak bramki przekazania.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    effects = job_lifecycle.PostCommit()
    await job_lifecycle.save_champion_core(
        db,
        job,
        payload,
        current_user,
        effects,
        imported=imported,
        expected_fingerprint=expected_fingerprint,
        sync_fields=sync_fields,
        expected_profile_hash=expected_profile_hash,
    )
    await db.commit()
    # Odpowiedź (z odciskiem `fingerprint`) ze stanu PO zapisie — ten sam odczyt
    # da następne żądanie, więc odcisk musi się z nim zgadzać.
    await db.refresh(job)
    from app.services.champion_intake import response_context

    response = {
        "job_id": job.id,
        "champion_profile": _champion_response(job.champion_profile),
        **response_context(job),
        # Uwagi zapisu (np. krytyczne, które przestały być technologią).
        "notices": list(effects.results.get("notices") or []),
    }
    await job_lifecycle.run_post_commit(effects)
    return response


# ── "Przekaż do searchu" — DL handoff that starts matching (P0-A) ────────────


_HANDOFF_RECRUITER_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.recruiter,
    UserRole.finance,
)


@router.get("/{job_id}/readiness")
async def get_job_readiness(
    job_id: int,
    current_user: RecruitmentManageUser,
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

    # Zamknięta rekrutacja nie jest „niegotowa" — jej się po prostu nie
    # przekazuje. Lustro guardu 409 w samym handoffie; bez tego przycisk
    # wyglądałby na możliwy do odblokowania uzupełnieniem Championa. Braki
    # liczymy i dla niej (04.10.2026): okno „Otwórz ponownie” przechodzi tę
    # samą bramkę z pytaniami liczonymi także przy ``is_open``.
    is_closed = job.status == JobStatus.closed
    blocker_items = job_handoff_blocker_items(job, include_open=is_closed)
    blockers = [item["message"] for item in blocker_items]
    return {
        "job_id": job.id,
        "ready": not blockers and not is_closed,
        "blockers": blockers,
        # Te same braki z kodami (klucze lustra frontu + `champion:<kod>`).
        "blocker_items": blocker_items,
        "closed": is_closed,
        "already_handed_off": job.is_open,
        "allocation_enabled": settings.RECRUITMENT_ALLOCATION_ENABLED,
        # `off` = „Zaproponuje automat” jest niedostępne (lustro odmowy 409
        # w handoffie); `shadow` — automat proponuje, akceptuje Head of
        # Recruitment; `auto` — przydziela sam.
        "allocation_mode": await _allocation_mode(db),
    }


# Jedna reguła dla gotowości, odmowy 409 i `/jobs/new` (`handoff-options`).
_allocation_mode = effective_allocation_mode


@router.post("/{job_id}/handoff", status_code=202)
async def handoff_job_to_search(
    job_id: int,
    current_user: RecruitmentManageUser,
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

    from app.services.champion_intake import enforce_operation

    enforce_operation(job, "handoff")
    blockers = _compute_job_readiness(job)
    if blockers:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Rekrutacja nie jest gotowa do przekazania do searchu.",
                "blockers": blockers,
            },
        )

    effects = job_lifecycle.PostCommit(background_tasks)
    result = await job_lifecycle.handoff_core(db, job, payload, current_user, effects)
    # Rekrutacja bez szkiców (04.10.2026): stary szkic przekazany do searchu
    # jest od razu publikowany.
    if job.status != JobStatus.published:
        await job_lifecycle.publish_core(db, job, current_user, effects)
    await db.commit()
    await job_lifecycle.run_post_commit(effects)
    return {**result, "snapshot_id": effects.results.get("snapshot_id")}


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
    apply_requirement_source_update(
        job, "champion_profile", validated.model_dump(mode="json")
    )

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


@router.post("/{job_id}/champion-profile/client-history")
async def refresh_champion_client_history(
    job_id: int,
    current_user: JobEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Przelicza blok „Z historii klienta” (sekcja 8 profilu Championa).

    Woła go strona /jobs/new tuż po utworzeniu rekrutacji (bez czekania na
    wynik) i przycisk „Odśwież” w edytorze. Awaria modelu NIE jest błędem
    trasy: blok dostaje `status="failed"` i komunikat, a odpowiedź to 200 —
    AI jest tu dodatkiem, nigdy bramką. Model jest wołany tylko wtedy, gdy
    dane wejściowe zmieniły się od ostatniego podsumowania.
    """
    from app.schemas.champion import ChampionProfile
    from app.services.champion_client_history import summarize_client_history

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    await ensure_champion_job_editor(job, current_user, db)
    if job.client_id is None:
        raise HTTPException(
            422, "Rekrutacja nie ma klienta — nie ma czyjej historii podsumować."
        )

    stored = ChampionProfile.model_validate(job.champion_profile or {})
    role = stored.basics.role_name or job.title or ""
    summary = await summarize_client_history(
        db,
        client_id=job.client_id,
        role=role,
        stored=stored.client_history.model_dump(mode="json"),
        user_id=current_user.id,
    )

    # Blok liczony poza blokadą wiersza (model trwa kilka–kilkanaście sekund);
    # zapis na świeżo zablokowanym profilu, żeby nie nadpisać równoległej
    # edycji innych sekcji. `populate_existing` jest konieczne: bez niego
    # SQLAlchemy zwraca obiekt z mapy tożsamości sesji z profilem SPRZED
    # wywołania modelu i zapis cofał edycję zrobioną w tym czasie.
    job = await db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current = dict(job.champion_profile or {})
    defaults = ChampionProfile().model_dump(mode="json")
    for key, value in defaults.items():
        current.setdefault(key, value)
    current["client_history"] = summary
    validated = ChampionProfile.model_validate(current)
    apply_requirement_source_update(
        job, "champion_profile", validated.model_dump(mode="json")
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
    apply_requirement_source_update(
        job, "champion_profile", validated.model_dump(mode="json")
    )


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
            detail="Briefing musi być notatką ze spotkania.",
        )
    from app.services.note_job_link import ensure_note_linkable_to_job

    await ensure_note_linkable_to_job(db, note, job_id)

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


async def _briefing_audio_referenced_elsewhere(
    db: AsyncSession, storage_key: str, job_id: int
) -> bool:
    """Czy nagranie briefingu wskazuje jeszcze inna rekrutacja (runda 6 audytu)."""
    other = await db.scalar(
        select(Job.id)
        .where(
            Job.id != job_id,
            Job.champion_profile["briefing"]["audio_storage_key"].astext == storage_key,
        )
        .limit(1)
    )
    return other is not None


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
    # Kopie rekrutacji sprzed rundy 6 audytu niosą briefing źródła z TYM SAMYM
    # kluczem nagrania — kasujemy obiekt tylko wtedy, gdy żadna inna rekrutacja
    # go nie wskazuje, bo inaczej odpięcie na kopii zabiera nagranie źródłu.
    if old_key and await _briefing_audio_referenced_elsewhere(db, old_key, job_id):
        old_key = None
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
        RAW_DESCRIPTION_LIMITS,
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

    body = validated_body(GenerateFromJdPayload, payload or {}, RAW_DESCRIPTION_LIMITS)
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

    body = validated_body(GenerateFromHistoryPayload, payload or {})
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

    body = validated_body(HistoricalMatchesPreviewRequest, payload or {})
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
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    top_k: int = Query(default=10, ge=1, le=30),
    cross_client: bool = Query(default=False),
    include_open: bool = Query(default=True),
):
    """List sibling requests for a job — Historia tab.

    Splits the list into `closed` and `in_progress`. `skill_frequency` is
    computed only on closed entries (open jobs have no hire yet). Cheap by
    default — same-client SQL hit avoids Voyage entirely.

    Admin / Delivery Lead / Finance read it organisation-wide, as before —
    fee amounts only for clients whose finances the reader sees (a Delivery
    Lead: own portfolio; runda 6 audytu).
    Any other operational role reads it only as a member of this recruitment's
    team: history of THIS client only (``cross_client`` is ignored) and without
    fee amounts (17.09.2026).
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
    is_org_reader = current_user.has_any_role(*_HISTORY_ORG_READER_ROLES)
    if is_org_reader:
        delivery_lead_pairs = await _delivery_lead_job_pairs(current_user, db)
        await ensure_champion_job_read_visible(job, current_user, db)
        _assert_delivery_lead_cross_client_disabled(cross_client, delivery_lead_pairs)
    else:
        await ensure_job_read_access(db, current_user, job.id)
        # Recruitment team members see this client's history only.
        cross_client = False

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

    if not is_org_reader:
        # ``cross_client=False`` alone is not a client scope: a job without a
        # client makes the semantic step unscoped. Keep this client's rows only.
        entries = [
            e
            for e in entries
            if job.client_id is not None and e.client_id == job.client_id
        ]

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

    fee_visible = await _history_fee_visible(current_user, db)

    def _entry(e) -> RequestHistoryEntrySchema:
        # Członek zespołu spoza ról organizacyjnych nie widzi kwot wcale;
        # czytelnik organizacyjny — tylko u klientów, których kwoty widzi
        # (runda 6 audytu).
        show_fee = is_org_reader and fee_visible(e.client_id)
        return RequestHistoryEntrySchema.model_validate(
            _history_entry_payload(e, show_fee=show_fee)
        )

    return RequestHistoryResponse(
        closed=[_entry(e) for e in closed],
        in_progress=[_entry(e) for e in in_progress],
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

    body = validated_body(RequestHistoryPreviewRequest, payload or {})
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
    # Bliźniacza ścieżka Historii: te same kwoty, ta sama reguła (runda 6).
    fee_visible = await _history_fee_visible(current_user, db)

    def _entry(e) -> RequestHistoryEntrySchema:
        return RequestHistoryEntrySchema.model_validate(
            _history_entry_payload(e, show_fee=fee_visible(e.client_id))
        )

    return RequestHistoryResponse(
        closed=[_entry(e) for e in closed],
        in_progress=[_entry(e) for e in in_progress],
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

    payload = validated_body(AddCandidateFromHistoryPayload, body or {})

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
        entry_source="added_manual",
        claim_for_user_id=current_user.id,
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
# Rekrutera prowadzącego (`recruiter_id`) zmienia posiadacz uprawnienia
# „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta” (domyślnie admin
# i Delivery Lead) oraz — od 02.10.2026, z tytułu roli — Head of Recruitment
# (`JobStaffingUser`): to on układa pracę zespołu, a do tej daty nie mógł
# zmienić rekrutera w żadnej rekrutacji.
# "Claim" is self-assign on an unassigned job — open to anyone who can write
# to jobs (admin/DL/TAC/recruiter/sourcer). The `user` read-only role is
# blocked.

# Role, którym przypisanie do requestu zakłada wiersz pracy — lustro pulpitu
# „Requesty i obłożenie” (`request_board.add_person`).
_WORK_ASSIGNMENT_ROLES = WORK_ROLES


def _in_allocation_pool(job: Job) -> bool:
    """Request w puli przydziału: opublikowany, „Szukamy kandydatów”, bez championa.

    Lustro ``request_allocation._pool_clause``. Tylko tu wiersz przypisania ma
    sens — poza pulą automat zwalnia go przy najbliższym przebiegu.
    """
    return job_in_pool(job)


def _assert_skill_columns_follow_rows(job: Job, updates: dict) -> None:
    """Kolumny must/nice rekrutacji z wierszami wymagań idą za Championem.

    Audyt 06.10.2026 (P7): „Kryteria” (PATCH ``must_skills``/``nice_skills``)
    nadpisywały kolumny z pominięciem wierszy — bramka krytycznych i ocena
    czytały wtedy co innego niż Profil Championa, a następny zapis profilu
    cofał zmianę po cichu. Porównanie po nazwach: okno edycji odsyła komplet
    pól, także niezmienione.
    """
    from app.services.champion_requirement_rows import (
        ROWS_OWN_COLUMNS_DETAIL,
        profile_has_rows,
        skill_column_names,
    )

    if not profile_has_rows(job.champion_profile):
        return
    for column in ("must_skills", "nice_skills"):
        if column in updates and skill_column_names(
            updates[column]
        ) != skill_column_names(getattr(job, column)):
            raise HTTPException(status_code=409, detail=ROWS_OWN_COLUMNS_DETAIL)


async def _notify_new_owner(db: AsyncSession, *, job: Job, user_id: int) -> None:
    """Dzwonek „Nowy request do pracy” — ta sama treść co przy przydziale
    automatu (``notify_assigned``: savepoint, nie cofa zmiany rekrutera)."""
    from app.models.client import Client
    from app.services.job_working_title import display_title
    from app.services.request_allocation_notices import notify_assigned

    client_name = (
        await db.scalar(select(Client.name).where(Client.id == job.client_id))
        if job.client_id is not None
        else None
    )
    await notify_assigned(
        db,
        job_id=job.id,
        title=display_title(job),
        client_name=client_name,
        user_id=user_id,
    )


async def _sync_work_assignments_with_owner(
    db: AsyncSession,
    *,
    job: Job,
    previous_owner_id: Optional[int],
    owner: Optional[User],
    actor_id: int,
) -> None:
    """Rola „Rekruter” po zmianie rekrutera prowadzącego (``/owner``, ``/claim``,
    PATCH ``recruiter_id`` z okna edycji).

    Wołać PO wpisaniu ``job.recruiter_id``; wołający trzyma ``allocation_lock``
    i blokadę wiersza rekrutacji (w tej kolejności). ``owner=None`` = pole
    wyczyszczone: zostaje samo zwolnienie poprzedniej osoby.

    * Poprzednia osoba traci aktywne przypisanie — inaczej zostawałaby
      „Rekruterem” obok nowej, choć ktoś właśnie ją zastąpił. Powód
      ``owner_changed`` nie blokuje jej powrotu z automatu.
    * Wcześniejsze ręczne zdjęcie nowej osoby przestaje obowiązywać: człowiek
      przypisał ją świadomie. Bez tego osoba zdjęta i przypisana ponownie
      w tym samym stanie requestu byłaby prowadzącą, a mimo to „nie pracowała”
      (``owner_is_working_clause``) — poza pulą bez żadnej drogi powrotu.
      Regułę ma jedno miejsce: ``request_allocation.void_manual_release``.
    * Nowa osoba dostaje ręczne przypisanie, gdy request jest w puli — żeby
      automat nie dobierał do requestu kolejnej osoby.
    * Nowa osoba dostaje dzwonek „Nowy request do pracy” (audyt 06.10.2026,
      H1): do tej daty dzwonił wyłącznie handoff i automat, a ``/owner``,
      ``/claim`` i zmiana rekrutera w oknie edycji nie mówiły nikomu nic.
      Bez dzwonka dla siebie (``/claim``) i dla osoby, która już prowadziła.
      Jedno miejsce dla wszystkich ścieżek — handoff nie dzwoni osobno.
    """
    new_owner_id = owner.id if owner is not None else None
    if owner is not None and owner.id not in (actor_id, previous_owner_id):
        await _notify_new_owner(db, job=job, user_id=owner.id)
    if previous_owner_id is not None and previous_owner_id != new_owner_id:
        await db.execute(
            sql_update(JobWorkAssignment)
            .where(
                JobWorkAssignment.job_id == job.id,
                JobWorkAssignment.user_id == previous_owner_id,
                JobWorkAssignment.state == "active",
            )
            .values(
                state="released",
                released_at=datetime.now(timezone.utc),
                release_reason="owner_changed",
            )
            .execution_options(synchronize_session=False)
        )
    if owner is None:
        return
    if _in_allocation_pool(job) and owner.has_any_role(*_WORK_ASSIGNMENT_ROLES):
        # `manual_add` samo znosi wcześniejsze ręczne zdjęcie tej osoby.
        await manual_add(
            db,
            job_id=job.id,
            user_id=owner.id,
            role=WORK_ROLE,
            actor_id=actor_id,
        )
    else:
        await void_manual_release(db, job_id=job.id, user_id=owner.id)


@router.post("/{job_id}/owner", response_model=JobResponse)
async def assign_owner(
    job_id: int,
    payload: JobOwnerAssignment,
    current_user: JobStaffingUser,
    db: AsyncSession = Depends(get_db),
):
    """Ustaw albo zmień rekrutera prowadzącego (``recruiter_id``).

    Uprawnienie „Rekrutacje: zakładanie…” albo Head of Recruitment.
    """
    await allocation_lock(db)
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    # Lustro `/claim` (R8-X2-3): zamkniętej rekrutacji nikt nie dostaje do
    # prowadzenia — „prowadzący” widzi stawki umów B2B wydanych w tej
    # rekrutacji. Zdjęcie (DELETE) zostaje dozwolone, bo to sprzątanie.
    if job.status == JobStatus.closed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Zamkniętej rekrutacji nie można przypisać rekrutera.",
        )

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if not target or not target.is_active:
        raise HTTPException(status_code=409, detail="Target user not found or inactive")
    if not target.has_any_role(*_OWNERSHIP_ELIGIBLE_ROLES):
        raise HTTPException(
            status_code=409,
            detail=f"Role {target.role.value} cannot own a job",
        )

    previous_owner_id = job.recruiter_id
    if job.is_open and target.has_role(UserRole.recruiter):
        channel = PriorityChannel.linkedin
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
    await _sync_work_assignments_with_owner(
        db,
        job=job,
        previous_owner_id=previous_owner_id,
        owner=target,
        actor_id=current_user.id,
    )
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
    current_user: JobStaffingUser,
    db: AsyncSession = Depends(get_db),
):
    """Zdejmij rekrutera prowadzącego. Ta sama bramka co przypisanie.

    Osoba znika z roli „Rekruter” w całości (``job_team.remove_recruiter``):
    przestaje być prowadzącą, traci aktywne przypisanie i ręczne dopisanie jako
    współpracownik. Do 02.10.2026 czyszczone było samo ``recruiter_id``, więc
    osoba z przypisaniem zostawała „Rekruterem” na liście i pulpicie.
    """
    await allocation_lock(db)
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    previous = job.recruiter_id
    if previous is not None:
        # Wpis `owner_released` w historii zostawia `remove_recruiter`.
        await remove_recruiter(db, job=job, user_id=previous, actor_id=current_user.id)
    # Commit także bez prowadzącego: zwalnia blokady (doradczą i wiersza).
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
            detail="Rola tylko do odczytu nie może przejąć rekrutacji",
        )

    await allocation_lock(db)
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)
    # Runda 9 (R9-V2-2): prowadzący z nieaktywnym kontem to brak prowadzącego —
    # do tej rundy przejęcie takiej rekrutacji kończyło się 409, a front nie
    # pokazywał „Przejmij”, więc nikt nie mógł jej prowadzić.
    if job.recruiter_id is not None and await db.scalar(
        select(User.is_active).where(User.id == job.recruiter_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ta rekrutacja ma już rekrutera",
        )
    # Runda 8 (R8-X2-3): zamkniętej rekrutacji (także archiwum z Traffita bez
    # prowadzącego) nikt już nie przejmuje — „prowadzący” odsłaniał stawki
    # wszystkich umów B2B wydanych w tej rekrutacji.
    if job.status == JobStatus.closed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Zamkniętej rekrutacji nie można przejąć.",
        )

    # Poprzedni prowadzący może tu być tylko nieaktywnym kontem (wyżej 409).
    previous_owner_id = job.recruiter_id
    if job.is_open and current_user.has_role(UserRole.recruiter):
        channel = PriorityChannel.linkedin
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
    await _sync_work_assignments_with_owner(
        db,
        job=job,
        previous_owner_id=previous_owner_id,
        owner=current_user,
        actor_id=current_user.id,
    )
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
                .where(
                    JobCollaborator.job_id == job_id,
                    JobCollaborator.removed_from_auto_cc.is_(False),
                )
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
    """Dodaj współpracownika — każdy, kto redaguje rekrutację (``ensure_job_editor``).

    Decyzja Artura 29.09.2026: kilka osób pracuje nad jedną rekrutacją, więc
    współpracowników dopisuje każdy, kto redaguje jej treść (lustro okna
    edycji). Zmiana prowadzącego (``/owner``, ``/claim``) ma własne bramki.

    Idempotent at the DB layer via UNIQUE(job_id, user_id) — duplicate inserts
    return the existing row instead of raising. Wiersz ``auto_cc`` (cała
    kategoria) dodany ręcznie staje się ``manual`` — od tej chwili osoba jest
    „Rekruterem” rekrutacji (``services/job_team``).
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    await ensure_job_editor(db, current_user, job)

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
    elif (
        existing.source != JobCollaboratorSource.manual or existing.removed_from_auto_cc
    ):
        existing.source = JobCollaboratorSource.manual
        existing.removed_from_auto_cc = False
        existing.removed_at = None
        existing.added_by = current_user.id
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="collaborator_added",
                user_id=current_user.id,
                details={"collaborator_id": target.id, "promoted_from": "auto_cc"},
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
    """Usuń współpracownika — ta sama bramka co dodanie (``ensure_job_editor``)."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _ensure_delivery_lead_job_visible(job, current_user, db)

    await ensure_job_editor(db, current_user, job)

    link = await db.scalar(
        select(JobCollaborator).where(
            JobCollaborator.job_id == job_id,
            JobCollaborator.user_id == user_id,
        )
    )
    if link is None or link.removed_from_auto_cc:
        # Idempotent: deleting a missing (or already removed) link is a
        # success (204).
        return
    removed_source = link.source.value if link.source else "manual"
    if removed_source == "auto_cc":
        # Osoba z kategorii: wiersz zostaje z flagą, bo samo skasowanie
        # cofnęłaby najbliższa synchronizacja uczestników z kategorią.
        link.removed_from_auto_cc = True
        link.removed_at = datetime.now(timezone.utc)
    else:
        await db.delete(link)
    # Feedback loop: when an auto_cc collaborator is removed we log to Activity
    # so Head of Recruitment can spot patterns (e.g. one sourcer removed 10×
    # from the same CC → revise user↔CC mapping).
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
