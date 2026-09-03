import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from pydantic import BaseModel
from collections.abc import Iterable, Sequence
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    STAGE_CATEGORY,
    STAGE_ORDER,
    VerificationStatus,
)
from app.models.recruitment_priority import PriorityChannel
from app.models.activity import Activity
from app.models.user_activity import UserActivity, UserActionType
from app.models.notification import Notification, NotificationType
from app.services import champion_view
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
)
from app.services.candidate_contact_hooks import (
    load_contact_case_summaries,
    maybe_close_contact_opportunity,
    maybe_ensure_contact_opportunity,
)
from app.services.b2b_contract_automation import ensure_b2b_employment_draft
from app.models.job import Job, JobStatus
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
    TerminalType,
)
from app.models.user import User, UserRole
from app.schemas.pipeline import (
    CandidateStageResponse,
    HiringManagerVetoBrief,
    KanbanColumn,
    KanbanView,
    OffTemplateColumn,
    PendingVerificationListItem,
    PendingVerificationReject,
    StageMove,
    StageInfo,
    STAGE_LABELS,
)
from app.api.candidate_access import CandidateFinanceReadAccess, CandidatePIIAccess
from app.api.deps import AdminUser, CurrentUser, OperationalUser, RecruiterPlus
from app.api.recruitment_access import (
    ensure_job_read_access,
    ensure_job_membership,
    user_can_edit_rates,
    user_can_terminal_transition,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.services.hiring_manager_verdicts import (
    load_manager_rejections,
    puts_candidate_before_client,
    veto_for_candidate_stage,
)
from app.services.pipeline_eligibility import (
    assert_candidate_move_eligible,
    assert_candidates_move_eligible,
)
from app.services.rate_normalization import (
    POLICY_VERSION as RATE_POLICY_VERSION,
    normalize_rate_to_monthly,
)
from app.services.recruitment_process_commands import (
    accept_pending_verification,
    canonical_candidate_lock_order,
    lock_candidates_stmt,
    reject_pending_verification,
    transition_process,
)
from app.services.delivery_alert_recipients import load_delivery_alert_recipient_scope
from app.services.notification_access import notification_recipient_has_access

# Terminal wynikający wprost z legacy enuma — używane w gałęzi bez szablonu
# pipeline'u, żeby `KanbanColumn.terminal_type` był wypełniany tak samo jak
# w gałęzi z szablonem.
_LEGACY_TERMINAL_TYPE: dict[
    PipelineStage, Literal["hired", "rejected", "withdrawn"]
] = {
    PipelineStage.hired: "hired",
    PipelineStage.rejected: "rejected",
    PipelineStage.withdrawn: "withdrawn",
}

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)
logger = logging.getLogger(__name__)


# Referencje zadań w tle (fire-and-forget ``create_task`` gubi je pod GC —
# pętla zdarzeń trzyma tylko słabą referencję). Wzorzec z app/api/cortex.py,
# rozszerzony o log: powiadomienie Teams padłe w zadaniu nie ma czytelnika,
# więc bez done_callbacku znika bez śladu.
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro, label: str) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _done(finished: asyncio.Task) -> None:
        _bg_tasks.discard(finished)
        if finished.cancelled():
            logger.warning("pipeline background task cancelled: %s", label)
            return
        exc = finished.exception()
        if exc is not None:
            logger.exception("pipeline background task failed: %s", label, exc_info=exc)

    task.add_done_callback(_done)


# ── Helpers to bridge legacy enum ↔ new stage_def FK ────────────────────────


async def _default_template_id(db: AsyncSession) -> Optional[int]:
    """Return id of the is_default=true template (or None if unseeded)."""
    return await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )


async def _resolve_stage_def(
    db: AsyncSession,
    job: Optional[Job],
    *,
    stage_def_id: Optional[int] = None,
    legacy_stage: Optional[PipelineStage] = None,
) -> Optional[PipelineStageDef]:
    """Resolve a StageDef from either explicit id or legacy enum (via template)."""
    if stage_def_id:
        return await db.scalar(
            select(PipelineStageDef).where(PipelineStageDef.id == stage_def_id)
        )
    if legacy_stage is None:
        return None

    template_id = (
        job.pipeline_template_id if job else None
    ) or await _default_template_id(db)
    if not template_id:
        return None
    return await db.scalar(
        select(PipelineStageDef).where(
            PipelineStageDef.template_id == template_id,
            PipelineStageDef.legacy_enum_value == legacy_stage.value,
        )
    )


def _days_in_stage(moved_at: datetime) -> int:
    """Calculate days a candidate has been in the current stage."""
    now = datetime.now(timezone.utc)
    if moved_at.tzinfo is None:
        from datetime import timezone as tz

        moved_at = moved_at.replace(tzinfo=tz.utc)
    return max(0, (now - moved_at).days)


def _stage_response(
    stage: CandidateStage,
    *,
    candidate_name: Optional[str] = None,
    candidate_lastname: Optional[str] = None,
    added_to_job_by_name: Optional[str] = None,
    added_to_job_at: Optional[datetime] = None,
) -> dict:
    """Convert a CandidateStage to response dict with days_in_stage.

    Candidate name/lastname are optional — populated by the Kanban endpoint
    so the frontend can render card titles without an extra round-trip.

    ``added_to_job_by_name`` / ``added_to_job_at`` describe WHO assigned the
    candidate to the recruitment and WHEN — i.e. the mover on the *earliest*
    stage of this candidate/job pair, not the current-stage mover. Also
    populated by the Kanban endpoint (NULL elsewhere).
    """
    return {
        "id": stage.id,
        "candidate_id": stage.candidate_id,
        "job_id": stage.job_id,
        "stage": stage.stage,
        "stage_def_id": stage.stage_def_id,
        "rejection_reason_id": stage.rejection_reason_id,
        "moved_at": stage.moved_at,
        "moved_by": stage.moved_by,
        "notes": stage.notes,
        "rating": stage.rating,
        "created_at": stage.created_at,
        "days_in_stage": _days_in_stage(stage.moved_at),
        # Pending verification snapshot (migracja 0056)
        "verification_status": stage.verification_status,
        "expected_rate_value": stage.expected_rate_value,
        "expected_rate_unit": stage.expected_rate_unit,
        "expected_rate_currency": stage.expected_rate_currency,
        "budget_max_at_move": stage.budget_max_at_move,
        "approved_by": stage.approved_by,
        "approved_at": stage.approved_at,
        "rejected_by": stage.rejected_by,
        "rejected_at": stage.rejected_at,
        "rejection_note": stage.rejection_note,
        "name": candidate_name,
        "lastname": candidate_lastname,
        "added_to_job_by_name": added_to_job_by_name,
        "added_to_job_at": added_to_job_at,
    }


# ── Pending verification helper ─────────────────────────────────────────────


async def _notify_pending_verification(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    candidate: Optional[Candidate],
    job: Job,
) -> None:
    """Send `pending_verification` notification to administrators.

    Rate/budget exceptions are Admin-only. Delivery Lead and Head of
    Recruitment must not receive the financial values or candidate identity in
    this notification. A notification failure must not block the stage move.
    """
    approvers = (
        await db.execute(
            select(User.id).where(
                User.role == UserRole.admin,
                User.is_active.is_(True),
            )
        )
    ).all()
    candidate_label = (
        f"{candidate.name} {candidate.lastname}".strip()
        if candidate
        else f"Kandydat #{stage.candidate_id}"
    )
    rate_label = (
        f"{stage.expected_rate_value} "
        f"{(stage.expected_rate_currency or 'PLN')}/"
        f"{(stage.expected_rate_unit or 'monthly')}"
    )
    budget_label = (
        f"{stage.budget_max_at_move} PLN/m"
        if stage.budget_max_at_move is not None
        else "?"
    )
    for (uid,) in approvers:
        db.add(
            Notification(
                user_id=uid,
                title="Wymagana akceptacja weryfikacji",
                message=(
                    f"{candidate_label} na ofercie '{job.title}' — "
                    f"stawka {rate_label} przekracza budżet {budget_label}."
                ),
                link=f"/pending-verifications?stage={stage.id}",
                notification_type=NotificationType.pending_verification,
                related_entity_type="candidate_stage",
                related_entity_id=stage.id,
            )
        )


@router.get("/stages", response_model=List[StageInfo])
async def list_stages(
    current_user: CurrentUser,
    job_id: Optional[int] = Query(
        None, description="If provided, return stages of this job's template."
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return pipeline stages.

    - With `job_id`: stages of the template attached to that job.
    - Without: stages of the default template.

    Fallback: if no templates exist yet (e.g. during migration), returns the
    legacy hardcoded enum stages so the UI keeps rendering.
    """
    # Resolve template id
    template_id: Optional[int] = None
    if job_id is not None:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        template_id = job.pipeline_template_id
    if template_id is None:
        template_id = await _default_template_id(db)

    if template_id is not None:
        rows = (
            (
                await db.execute(
                    select(PipelineStageDef)
                    .where(PipelineStageDef.template_id == template_id)
                    .order_by(PipelineStageDef.order)
                )
            )
            .scalars()
            .all()
        )
        result: list[StageInfo] = []
        for sd in rows:
            # Map new category enum → legacy StageCategory for BC
            legacy_enum = None
            if sd.legacy_enum_value:
                try:
                    legacy_enum = PipelineStage(sd.legacy_enum_value)
                except ValueError:
                    legacy_enum = None
            result.append(
                StageInfo(
                    stage=legacy_enum
                    or PipelineStage.new,  # fallback for custom stages
                    category=sd.category,
                    label=sd.name,
                    order=sd.order,
                    stage_def_id=sd.id,
                    is_terminal=sd.is_terminal,
                )
            )
        return result

    # Legacy fallback — pre-seed / no template world
    result = []
    for i, stage in enumerate(STAGE_ORDER):
        result.append(
            StageInfo(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                label=STAGE_LABELS[stage],
                order=i,
                is_terminal=False,
            )
        )
    for stage in [PipelineStage.rejected, PipelineStage.withdrawn]:
        result.append(
            StageInfo(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                label=STAGE_LABELS[stage],
                order=99,
                is_terminal=True,
            )
        )
    return result


@router.post("/move", response_model=CandidateStageResponse)
async def move_candidate(
    data: StageMove,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Move a candidate to a new pipeline stage for a given job.

    Accepts either `stage` (legacy enum) or `stage_def_id` (new FK). For
    custom stages introduced via templates, the legacy enum is set to
    `PipelineStage.new` as a placeholder — the real identifier is stage_def_id.
    """
    if data.stage is None and data.stage_def_id is None:
        raise HTTPException(
            status_code=422,
            detail="Either `stage` (legacy enum) or `stage_def_id` must be provided",
        )

    job = await db.scalar(select(Job).where(Job.id == data.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # ── P1-PIPE-01: resource scope ── a caller may only touch the pipeline of
    # a job they belong to (owner/DL/TAC/collaborator) or oversee (admin/HoR).
    # Runs before any target/capability work so a non-member learns nothing
    # about the requested move.
    await ensure_job_membership(db, current_user, job.id)

    stage_def = await _resolve_stage_def(
        db, job, stage_def_id=data.stage_def_id, legacy_stage=data.stage
    )

    # ── M4 PR-02: integrity walidacja TARGETU ruchu (audyt P1.1) ───────────
    # Walidujemy WYŁĄCZNIE target — baseline PR-00 pokazał 79k istniejących
    # latest rows ze stage_def spoza template'u joba (import Traffit); ruch
    # Z takiego stanu musi pozostać legalny, ruch NA obcy etap — nie.
    if data.stage_def_id and stage_def is None:
        raise HTTPException(
            status_code=422,
            detail=f"stage_def_id={data.stage_def_id} nie istnieje",
        )
    effective_template_id = job.pipeline_template_id or await _default_template_id(db)
    if (
        stage_def is not None
        and effective_template_id is not None
        and stage_def.template_id != effective_template_id
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Etap '{stage_def.name}' należy do innego template'u niż "
                "template tej rekrutacji."
            ),
        )
    if (
        data.stage is not None
        and stage_def is not None
        and stage_def.legacy_enum_value
        and stage_def.legacy_enum_value != data.stage.value
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Sprzeczne `stage`={data.stage.value} i `stage_def_id` "
                f"(etap '{stage_def.name}' mapuje się na "
                f"'{stage_def.legacy_enum_value}')."
            ),
        )

    # Use the same first lock as the signed-contract automation. Besides
    # serializing two pipeline moves, this prevents the inverse
    # CandidateStage-FK → Candidate-FOR-UPDATE lock order that could deadlock
    # with a concurrent signature confirmation.
    locked_candidate_id = await db.scalar(
        select(Candidate.id).where(Candidate.id == data.candidate_id).with_for_update()
    )
    if locked_candidate_id is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Current row pary — kanoniczny tiebreaker (moved_at DESC, id DESC).
    # Reużywany niżej: pending-block, cancel maili przy restore, notyfikacje.
    previous_stage_row = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == data.candidate_id,
            CandidateStage.job_id == data.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )

    # M4 PR-02 (audyt P0.4): gdy current row czeka na akceptację stawki,
    # kolejny move nie może ominąć gate'u — najpierw decyzja approvera.
    if (
        previous_stage_row is not None
        and previous_stage_row.verification_status == VerificationStatus.pending
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Proces czeka na akceptację weryfikacji stawki "
                "(pending verification). Zaakceptuj lub odrzuć weryfikację "
                "zanim wykonasz kolejny ruch."
            ),
        )

    # Derive effective legacy-enum value for backward-compat column
    legacy_enum: PipelineStage = data.stage or PipelineStage.new
    if stage_def and stage_def.legacy_enum_value:
        try:
            legacy_enum = PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            legacy_enum = data.stage or PipelineStage.new
    elif stage_def and stage_def.is_terminal and legacy_enum == PipelineStage.new:
        # M4-P0.2: a CUSTOM terminal stage carries no legacy_enum_value (the
        # StageDef schema has no such field and clone_template doesn't copy it),
        # so it would fall through as `new` — a custom "Zatrudniony" would never
        # trigger the auto-draft Contract (line ~700 keys on `hired`) and a
        # custom "Odrzucony" would never fire the rejection mail. Derive the
        # hire/reject/withdraw signal from terminal_type so those side effects
        # fire. list_stages also can't return `hired` for custom stages, so the
        # FE can't supply it either — this is the only place it can be inferred.
        _terminal_to_legacy = {
            TerminalType.hired: PipelineStage.hired,
            TerminalType.rejected: PipelineStage.rejected,
            TerminalType.withdrawn: PipelineStage.withdrawn,
        }
        mapped = _terminal_to_legacy.get(stage_def.terminal_type)
        if mapped is not None:
            legacy_enum = mapped

    # ── M4 PR-01: capability guard na ruchy terminalne i rate-bearing ──────
    # Terminal (po stage_def LUB legacy enum): sourcer nie zamyka rekrutacji
    # (audyt P0.3 — RecruiterPlus obejmuje sourcera, a terminal nie miał
    # osobnego guardu). Ruch na `verified` niesie stawkę kandydata
    # (expected_rate_*), więc wymaga capability edycji stawek.
    is_terminal_target = bool(stage_def and stage_def.is_terminal) or legacy_enum in (
        PipelineStage.hired,
        PipelineStage.rejected,
        PipelineStage.withdrawn,
    )
    if is_terminal_target and not user_can_terminal_transition(current_user):
        raise HTTPException(
            status_code=403,
            detail=(
                "Ruch na etap terminalny (hired/rejected/withdrawn) wymaga roli "
                "recruiter/tac/delivery_lead/admin."
            ),
        )
    # A concurrent confirm or pipeline move may have completed while this
    # request waited for the candidate lock. Treat an identical hired move as
    # an idempotent replay instead of appending a second terminal stage.
    if (
        legacy_enum == PipelineStage.hired
        and previous_stage_row is not None
        and previous_stage_row.stage == PipelineStage.hired
    ):
        resp = _stage_response(previous_stage_row)
        resp["scheduled_rejection_email_id"] = None
        await db.commit()
        return CandidateStageResponse(**resp)

    if legacy_enum == PipelineStage.verified and not user_can_edit_rates(current_user):
        raise HTTPException(
            status_code=403,
            detail=(
                "Ruch na etap 'Zweryfikowany' ustawia stawkę kandydata i wymaga "
                "roli recruiter/tac/delivery_lead/admin."
            ),
        )

    # ── P1-PIPE-01: eligibility gate ── same hard block the assign ingresses
    # enforce (global blacklist / active client blacklist·NDA·competitor) →
    # 409 with the Polish reason. Skipped for terminal REMOVAL moves so a
    # blacklisted/conflicted candidate can always be closed OUT (rejected /
    # withdrawn); a forward or `hired` move of such a candidate is blocked.
    is_removal_move = legacy_enum in (
        PipelineStage.rejected,
        PipelineStage.withdrawn,
    ) or bool(
        stage_def
        and stage_def.is_terminal
        and stage_def.terminal_type
        and stage_def.terminal_type.value in ("rejected", "withdrawn")
    )
    if not is_removal_move:
        await assert_candidate_move_eligible(
            db,
            candidate_id=data.candidate_id,
            job=job,
            now=datetime.now(timezone.utc),
            enforce_manager_verdict=puts_candidate_before_client(legacy_enum),
        )

    # Terminal-move validation: require rejection_reason_id
    is_terminal_move_stagedef = bool(
        stage_def
        and stage_def.is_terminal
        and stage_def.terminal_type
        and stage_def.terminal_type.value in ("rejected", "withdrawn")
    )
    # Phase 17 (migracja 0068): legacy enum path — pilnujemy WYŁĄCZNIE
    # `withdrawn`, bo to ma CHECK constraint na DB. Reszta legacy paths
    # zachowuje wcześniejsze zachowanie (BC-friendly).
    is_terminal_move_legacy_withdrawn = legacy_enum == PipelineStage.withdrawn
    # M4 PR-02: withdrawn (stagedef LUB legacy) ZAWSZE wymaga powodu ze
    # słownika — DB CHECK ck_candidate_stages_withdrawn_requires_reason i tak
    # odrzuci NULL, więc free-text dawał 500 zamiast czytelnego 422.
    is_withdrawn_target = is_terminal_move_legacy_withdrawn or bool(
        stage_def
        and stage_def.is_terminal
        and stage_def.terminal_type
        and stage_def.terminal_type.value == "withdrawn"
    )
    if is_withdrawn_target and not data.rejection_reason_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Etap 'withdrawn' wymaga powodu ze słownika "
                "(rejection_reason_id) — sam opis tekstowy nie wystarcza."
            ),
        )
    if is_terminal_move_stagedef or is_terminal_move_legacy_withdrawn:
        if not data.rejection_reason_id and not data.rejection_reason:
            terminal_label = (
                stage_def.terminal_type.value
                if is_terminal_move_stagedef
                else legacy_enum.value
            )
            raise HTTPException(
                status_code=422,
                detail=f"Terminal stage ({terminal_label}) requires rejection_reason_id",
            )
    # M4 PR-02 (audyt P1.1): walidacja powodu ZAWSZE gdy podany — dotąd
    # legacy `rejected` zapisywał dowolny FK bez sprawdzenia template'u,
    # kategorii i stage-bindingu.
    if data.rejection_reason_id:
        reason = await db.scalar(
            select(RejectionReason).where(
                RejectionReason.id == data.rejection_reason_id
            )
        )
        if not reason or not reason.active:
            raise HTTPException(
                status_code=422,
                detail="rejection_reason_id not found or inactive",
            )
        if not (
            is_terminal_move_stagedef
            or legacy_enum
            in (
                PipelineStage.rejected,
                PipelineStage.withdrawn,
            )
        ):
            raise HTTPException(
                status_code=422,
                detail="rejection_reason_id dozwolony tylko dla ruchu terminalnego",
            )
        if (
            effective_template_id is not None
            and reason.template_id != effective_template_id
        ):
            raise HTTPException(
                status_code=422,
                detail="Powód odrzucenia należy do innego template'u niż rekrutacja.",
            )
        expected_category = (
            stage_def.terminal_type.value
            if is_terminal_move_stagedef
            else legacy_enum.value
        )
        if reason.category.value != expected_category:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Powód ma kategorię '{reason.category.value}', "
                    f"a ruch jest '{expected_category}'."
                ),
            )
        if (
            reason.stage_def_id is not None
            and stage_def is not None
            and reason.stage_def_id != stage_def.id
        ):
            raise HTTPException(
                status_code=422,
                detail="Powód jest przypisany do innego etapu.",
            )

    # ── Pending verification gate (migracja 0056) ────────────────────────
    # Tylko ruch na stage `verified` triggeruje sprawdzenie rate vs budget.
    # Pozostałe stage'y zachowują defaultowe verification_status='active'.
    verification_status = VerificationStatus.active
    expected_rate_value = data.expected_rate_value
    expected_rate_unit = data.expected_rate_unit
    expected_rate_currency = data.expected_rate_currency or "PLN"
    budget_max_snapshot: Optional[int] = None
    needs_approval = False
    normalization_note: Optional[str] = None

    if legacy_enum == PipelineStage.verified:
        if expected_rate_value is None or expected_rate_unit is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Ruch na stage 'verified' wymaga `expected_rate_value` "
                    "i `expected_rate_unit`."
                ),
            )
        if job.salary_max is not None:
            budget_max_snapshot = int(job.salary_max)
            # M4 PR-02 (audyt P0.5): porównanie w JEDNEJ jednostce. Dotąd
            # surowe 150 (PLN/h) < 25000 (PLN/mc) przechodziło jako "w
            # budżecie". Normalizacja: hourly×168, daily×21; waluta ≠ PLN
            # lub nieznana jednostka → fail-closed do manual review.
            normalized_monthly, normalization_note = normalize_rate_to_monthly(
                Decimal(expected_rate_value),
                expected_rate_unit.value if expected_rate_unit else None,
                expected_rate_currency,
            )
            if normalized_monthly is None or normalized_monthly > Decimal(
                job.salary_max
            ):
                verification_status = VerificationStatus.pending
                needs_approval = True

    # M4 PR-02 (audyt P1.1): free-text reason był przyjmowany, "zaliczał"
    # walidację terminalną i znikał (nie ma kolumny). Utrwalamy go w notes,
    # żeby audyt widział podany powód.
    effective_notes = data.notes
    if data.rejection_reason and not data.rejection_reason_id:
        prefix = f"Powód ({legacy_enum.value}): {data.rejection_reason.strip()}"
        effective_notes = f"{prefix}\n{data.notes}" if data.notes else prefix

    stage = await transition_process(
        db,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        stage=legacy_enum,
        stage_def_id=stage_def.id if stage_def else None,
        rejection_reason_id=data.rejection_reason_id,
        moved_at=datetime.now(timezone.utc),
        actor_user_id=current_user.id,
        work_channel=PriorityChannel.database,
        notes=effective_notes,
        rating=data.rating,
        verification_status=verification_status,
        expected_rate_value=expected_rate_value,
        expected_rate_unit=(expected_rate_unit.value if expected_rate_unit else None),
        expected_rate_currency=(
            expected_rate_currency if expected_rate_value is not None else None
        ),
        budget_max_at_move=budget_max_snapshot,
        # Phase 17 (migracja 0068) — kandydata reakcja na ofertę po akcepcie.
        candidate_offer_response=data.candidate_offer_response,
    )
    await create_original_cv_snapshot(db, stage)
    if is_terminal_target:
        await maybe_close_contact_opportunity(
            db,
            candidate_id=data.candidate_id,
            job_id=data.job_id,
            actor_user_id=current_user.id,
            reason=f"pipeline_terminal:{legacy_enum.value}",
            occurred_at=stage.moved_at,
        )
    else:
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=data.candidate_id,
            job_id=data.job_id,
            source="pipeline",
            occurred_at=stage.moved_at,
        )

    if needs_approval:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == data.candidate_id)
        )
        await _notify_pending_verification(
            db, stage=stage, candidate=candidate, job=job
        )

    stage_display_name = (
        stage_def.name
        if stage_def
        else STAGE_LABELS.get(legacy_enum, legacy_enum.value)
    )

    # Activity log
    activity_details: dict = {
        "candidate_id": data.candidate_id,
        "job_id": data.job_id,
        "stage": legacy_enum.value,
        "stage_def_id": stage_def.id if stage_def else None,
        "stage_name": stage_display_name,
    }
    if legacy_enum == PipelineStage.verified and budget_max_snapshot is not None:
        # M4 PR-02: audyt decyzji gate'u — z jakiej normalizacji wynikła.
        activity_details["rate_gate"] = {
            "policy": RATE_POLICY_VERSION,
            "note": normalization_note,
            "pending": needs_approval,
            "budget_max": budget_max_snapshot,
        }
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=current_user.id,
            details=activity_details,
        )
    )

    # M4 PR-02 (audyt P1.7): restore/ruch na etap NIEterminalny anuluje
    # niewysłane maile odrzucenia tej pary — w TEJ SAMEJ transakcji co move.
    # Dotąd przywrócony kandydat mógł dostać zaplanowane wcześniej odrzucenie.
    if not is_terminal_target:
        from app.models.rejection_email import (
            RejectionEmailStatus,
            ScheduledRejectionEmail,
        )

        pending_mails = (
            (
                await db.execute(
                    select(ScheduledRejectionEmail).where(
                        ScheduledRejectionEmail.candidate_id == data.candidate_id,
                        ScheduledRejectionEmail.job_id == data.job_id,
                        ScheduledRejectionEmail.status == RejectionEmailStatus.pending,
                    )
                )
            )
            .scalars()
            .all()
        )
        for mail_row in pending_mails:
            mail_row.status = RejectionEmailStatus.cancelled
            mail_row.cancelled_at = datetime.now(timezone.utc)
            mail_row.cancelled_by = current_user.id
            db.add(
                Activity(
                    entity_type="candidate",
                    entity_id=data.candidate_id,
                    action="rejection_email_cancelled_on_restore",
                    user_id=current_user.id,
                    details={
                        "scheduled_rejection_email_id": mail_row.id,
                        "job_id": data.job_id,
                        "restored_to_stage": legacy_enum.value,
                    },
                )
            )

    # UserActivity for leaderboard/performance tracking
    db.add(
        UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.stage_changed,
            entity_type="pipeline",
            entity_id=stage.id,
            details={
                "candidate_id": data.candidate_id,
                "job_id": data.job_id,
                "stage": legacy_enum.value,
                "stage_def_id": stage_def.id if stage_def else None,
            },
        )
    )

    # M4 PR-02 (audyt P0.6): notify_stage_change (in-app + SMTP) oraz
    # talent-pool auto-add przeniesione ZA commit — patrz sekcja post-commit
    # niżej. Dotąd SMTP mógł wyjść przed commitem: mail o przejściu, którego
    # DB ostatecznie nie zatwierdziła.

    # Phase 9 A2 + DL portal refactor 2026-05-11:
    # Auto-create a draft Contract + draft ClientOrder when the candidate is
    # hired. DL fills in the rates/dates/PDF afterwards.
    if legacy_enum == PipelineStage.hired and job.client_id is not None:
        employment = await ensure_b2b_employment_draft(
            db,
            candidate_id=data.candidate_id,
            job=job,
            actor_id=current_user.id,
            default_start_date=date.today(),
            ensure_order=True,
            # The stage was inserted and flushed just above. The idempotent
            # guard sees it as latest and never appends a duplicate.
            ensure_hired=True,
            require_b2b=False,
            ensure_detail=False,
        )
        if employment.created_contract or employment.created_order:
            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=employment.contract.id,
                    action=(
                        "auto_drafted_from_pipeline"
                        if employment.created_contract
                        else "order_auto_drafted_from_pipeline"
                    ),
                    user_id=current_user.id,
                    details={
                        "candidate_id": data.candidate_id,
                        "job_id": job.id,
                        "stage": legacy_enum.value,
                        "order_id": (employment.order.id if employment.order else None),
                    },
                )
            )
            cand = await db.scalar(
                select(Candidate).where(Candidate.id == data.candidate_id)
            )
            cand_name = (
                f"{cand.name} {cand.lastname}".strip()
                if cand
                else f"#{data.candidate_id}"
            )
            delivery_recipients = await load_delivery_alert_recipient_scope(db)
            for uid in delivery_recipients.for_client(job.client_id):
                db.add(
                    Notification(
                        user_id=uid,
                        title=(
                            "Nowy draft kontraktu + zamówienia "
                            f"#{employment.contract.id}"
                        ),
                        message=(
                            f"Kandydat {cand_name} został zatrudniony na "
                            f"rekrutację '{job.title}' (#{job.id}). Uzupełnij stawki, "
                            "daty i wgraj PDF zamówienia."
                        ),
                        link=f"/clients/{job.client_id}?tab=zamowienia",
                        notification_type=NotificationType.contract_activated,
                        related_entity_type="contract",
                        related_entity_id=employment.contract.id,
                    )
                )

    # Obsada kompletna → PODPOWIEDŹ zamknięcia rekrutacji, nie automat.
    #
    # Zatrudnienie nie zmieniało dotąd stanu rekrutacji: `headcount` nie był
    # dekrementowany, a `close_reason = filled_by_us` nie był ustawiany nigdzie
    # w kodzie pipeline'u — stąd 315 rekrutacji zamkniętych w 90 dni BEZ powodu
    # i raport wygranych/przegranych bez czego liczyć wygranej.
    #
    # Automatu tu nie ma świadomie (decyzja właściciela 2026-09-03): 99,6% ruchu
    # pochodzi z importu, więc automatyczne domykanie działałoby retroaktywnie
    # na tysiącach rekrutacji, o które nikt nie prosił. Powiadomienie prowadzi
    # do ISTNIEJĄCEGO `POST /api/jobs/{job_id}/close`, który zapisuje powód
    # i loguje `Activity`.
    if legacy_enum == PipelineStage.hired:
        try:
            from app.services.job_fill import is_fully_staffed, placements_by_job

            # Skrót: właśnie kogoś zatrudniliśmy, więc obsada >= 1. Przy
            # `headcount = 1` (default) wiemy to bez pytania widoku
            # `analytics_first_milestones` — a to gorąca ścieżka `/move`.
            headcount = int(job.headcount or 1)
            filled = (
                1
                if headcount <= 1
                else (await placements_by_job(db, [job.id])).get(job.id, 0)
            )
            already_hinted = await db.scalar(
                select(Notification.id)
                .where(
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job.id,
                    Notification.notification_type
                    == NotificationType.suggest_next_step,
                )
                .limit(1)
            )
            if (
                is_fully_staffed(headcount, filled)
                and job.status != JobStatus.closed
                # Bez dedupu KAŻDE kolejne zatrudnienie na tej rekrutacji
                # rozsyłałoby ten sam komunikat do wszystkich admin/DL/TAC.
                # Podpowiedź ma być jedna — jeśli ktoś ją zignorował, powtórka
                # niczego nie doda, a nauczy ignorować powiadomienia.
                and already_hinted is None
            ):
                staff_rows = await db.execute(
                    select(User.id).where(
                        User.role.in_(
                            [UserRole.admin, UserRole.delivery_lead, UserRole.tac]
                        ),
                        User.is_active.is_(True),
                    )
                )
                for (uid,) in staff_rows.all():
                    db.add(
                        Notification(
                            user_id=uid,
                            title=f"Rekrutacja '{job.title}' ma komplet obsady",
                            message=(
                                f"Obsadzono {filled} z {job.headcount or 1} "
                                "etatów. Jeśli to koniec — zamknij rekrutację "
                                "z powodem „Obsadzone przez nas”, żeby raport "
                                "wygranych i przegranych miał z czego liczyć."
                            ),
                            link=f"/jobs/{job.id}",
                            notification_type=NotificationType.suggest_next_step,
                            related_entity_type="job",
                            related_entity_id=job.id,
                        )
                    )
        except Exception as _exc:  # noqa: BLE001
            # Podpowiedź nie może wywrócić zatrudnienia.
            logger.warning("fully-staffed hint failed for job=%s: %s", job.id, _exc)

    # Automatic rejection-email scheduling (0045_rejection_emails).
    # Runs when the current move is a rejection AND the caller didn't
    # explicitly opt out. `maybe_schedule` is idempotent for non-eligible
    # moves (returns None for internal-only rejections, missing email, etc.)
    # so we can call it unconditionally when the flag allows.
    scheduled_rejection_email_id: Optional[int] = None
    if legacy_enum == PipelineStage.rejected and data.send_rejection_email is not False:
        from app.services.rejection_email_scheduler import maybe_schedule

        scheduled = await maybe_schedule(
            db,
            stage=stage,
            job=job,
            recruiter_id=job.recruiter_id,
            template_override_id=data.rejection_email_template_id,
        )
        if scheduled is not None:
            scheduled_rejection_email_id = scheduled.id

    await db.commit()
    await db.refresh(stage)

    # ── Post-commit best-effort side effects (M4 PR-02, audyt P0.6) ────────
    # Transition jest już trwały. Nic poniżej nie może zwrócić 500 ani
    # cofnąć ruchu — każdy blok ma własny try/except + rollback, żeby błąd
    # SQL nie zostawił sesji w failed transaction (PendingRollbackError
    # → fałszywe 500 po zapisanym ruchu; scenariusz B audytu).

    # Configurable stage-transition notifications (migracja 0066) —
    # in-app + email (SMTP) per regułą; teraz wyłącznie PO commicie.
    try:
        from app.services.stage_notification_emitter import notify_stage_change

        candidate_obj = await db.scalar(
            select(Candidate).where(Candidate.id == data.candidate_id)
        )
        if candidate_obj is not None:
            await notify_stage_change(
                db,
                new_stage=stage,
                previous_stage=previous_stage_row,
                job=job,
                candidate=candidate_obj,
                mover=current_user,
                stage_display_name=stage_display_name,
            )
        await db.commit()
    except Exception as _exc:  # noqa: BLE001
        logger.warning("stage_notif top-level failure for stage=%s: %s", stage.id, _exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Phase 10 A1: auto-add candidate to a talent pool when CV is sent to
    # the client. Best-effort — po commicie ruchu.
    if legacy_enum == PipelineStage.cv_sent:
        from app.services.talent_pool_auto_add import auto_add_on_cv_sent

        try:
            pool_candidate = await db.scalar(
                select(Candidate).where(Candidate.id == data.candidate_id)
            )
            await auto_add_on_cv_sent(
                db=db,
                candidate_id=data.candidate_id,
                job=job,
                user_id=current_user.id,
                candidate=pool_candidate,
            )
            await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "auto_add_on_cv_sent failed for candidate=%s job=%s: %s",
                data.candidate_id,
                job.id,
                e,
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    # Phase 17 (migracja 0068): event-driven recompute risk profile.
    # Best-effort — błąd NIE może wywołać 500 po zapisanym transition.
    try:
        from app.services.candidate_risk import on_candidate_stage_change

        await on_candidate_stage_change(db, data.candidate_id)
        await db.commit()
    except Exception as _exc:  # noqa: BLE001
        logger.warning(
            "risk recompute failed post-move candidate=%s: %s",
            data.candidate_id,
            _exc,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    resp = _stage_response(stage)
    resp["scheduled_rejection_email_id"] = scheduled_rejection_email_id
    return CandidateStageResponse(**resp)


def _bucket_by_stage_def(
    entries: Iterable[CandidateStage],
    stage_defs: Sequence[PipelineStageDef],
) -> tuple[dict[int, list[CandidateStage]], list[CandidateStage]]:
    """Rozdziel karty na kolumny szablonu i kubełek „poza szablonem".

    Partycja jest **wyczerpująca i rozłączna** — każdy wpis trafia dokładnie
    w jedno miejsce. Wcześniej ta pętla miała dwie ścieżki wyjścia i brak
    trzeciej, więc karta, która nie pasowała do żadnej kolumny, po prostu
    znikała: bez kolumny, bez licznika, bez ostrzeżenia (1 633 karty na
    produkcji, pomiar 2026-09-02).

    Każda gałąź kończy się `continue`, żeby nie dało się dopisać czwartej
    ścieżki, która znowu po cichu zgubi wpis. Czysta funkcja — testowalna bez
    bazy i bez HTTP, więc strażnik przeżyje refaktor endpointu.
    """

    enum_to_def: dict[str, PipelineStageDef] = {
        sd.legacy_enum_value: sd for sd in stage_defs if sd.legacy_enum_value
    }
    columns_map: dict[int, list[CandidateStage]] = {sd.id: [] for sd in stage_defs}
    off_template: list[CandidateStage] = []

    for entry in entries:
        # `None not in columns_map` — klucze to int-y, więc wiersz bez
        # `stage_def_id` (produkuje go dziś `/bulk-move` i `open_process`)
        # poprawnie spada do fallbacku po legacy enumie.
        if entry.stage_def_id in columns_map:
            columns_map[entry.stage_def_id].append(entry)
            continue
        mapped = enum_to_def.get(entry.stage.value) if entry.stage else None
        if mapped is not None:
            columns_map[mapped.id].append(entry)
            continue
        off_template.append(entry)

    return columns_map, off_template


async def _build_off_template(
    db: AsyncSession,
    *,
    job_id: int,
    entries: Sequence[CandidateStage],
    render,
) -> Optional[OffTemplateColumn]:
    """Zbuduj kubełek — albo `None`, gdy szablon pokrywa każdą kartę.

    Etykiety mówią, na jakich etapach te karty stoją; bez nich rekruter widzi
    kubełek, ale nie wie, dokąd kartę wyprowadzić. Zapytanie o nazwy etapów
    z obcego szablonu leci **tylko gdy kubełek jest niepusty**, więc zdrowa
    tablica nie płaci za to ani jednym round-tripem.
    """

    if not entries:
        return None

    labels: list[str] = []
    foreign_def_ids = {e.stage_def_id for e in entries if e.stage_def_id is not None}
    names_by_def_id: dict[int, str] = {}
    if foreign_def_ids:
        rows = await db.execute(
            select(PipelineStageDef.id, PipelineStageDef.name).where(
                PipelineStageDef.id.in_(foreign_def_ids)
            )
        )
        names_by_def_id = {def_id: name for def_id, name in rows.all()}

    for entry in entries:
        label = names_by_def_id.get(entry.stage_def_id) if entry.stage_def_id else None
        if label is None and entry.stage is not None:
            label = STAGE_LABELS.get(entry.stage, entry.stage.value)
        if label and label not in labels:
            labels.append(label)

    # Metryka spadku bez zmiany zachowania — sieroty powstają NADAL
    # (`/bulk-move` i `open_process` zapisują `stage_def_id=NULL`), więc ten
    # licznik ma rosnąć albo maleć, a nie zostać zapomniany.
    logger.warning(
        "kanban off-template bucket: job=%s cards=%d stages=%s",
        job_id,
        len(entries),
        labels,
    )

    return OffTemplateColumn(
        name="Poza szablonem",
        count=len(entries),
        items=[CandidateStageResponse(**render(e)) for e in entries],
        missing_stage_labels=labels,
    )


@router.get("/kanban/{job_id}", response_model=KanbanView)
async def get_kanban(
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """
    Return kanban view for a job — columns driven by the job's pipeline template.

    Backward-compat: rows whose stage_def_id is NULL are bucketed by legacy enum
    via PipelineStageDef.legacy_enum_value lookup.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # P1-PIPE-01: reading a job's board is a pipeline ingress — members only.
    await ensure_job_read_access(db, current_user, job.id)

    # All CandidateStage rows for this job, newest→oldest per candidate.
    # Secondary id.desc() makes the per-candidate "first" (latest) and "last"
    # (earliest) rows deterministic when two moves share a `moved_at`.
    result = await db.execute(
        select(CandidateStage)
        .where(CandidateStage.job_id == job_id)
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
    )
    all_stages = result.scalars().all()
    # First row per candidate = current (latest) stage → the card.
    # Last row per candidate = earliest stage → who assigned them to the job.
    seen: dict[int, CandidateStage] = {}
    earliest: dict[int, CandidateStage] = {}
    for s in all_stages:
        if s.candidate_id not in seen:
            seen[s.candidate_id] = s
        earliest[s.candidate_id] = s  # overwritten; last write wins (oldest row)

    # Bulk-load candidate names so cards render with real names (not "Kandydat" fallback)
    candidate_ids = list(seen.keys())
    contact_case_by_candidate = await load_contact_case_summaries(db, candidate_ids)
    name_by_id: dict[int, tuple[Optional[str], Optional[str]]] = {}
    if candidate_ids:
        rows = await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname).where(
                Candidate.id.in_(candidate_ids)
            )
        )
        for cid, cname, clastname in rows.all():
            name_by_id[cid] = (cname, clastname)

    # Bulk-load names of the recruiters who first assigned each candidate to the
    # job (mover on the earliest stage). One query, no per-card N+1.
    added_by_user_ids = {
        e.moved_by for e in earliest.values() if e.moved_by is not None
    }
    user_name_by_id: dict[int, Optional[str]] = {}
    if added_by_user_ids:
        urows = await db.execute(
            select(User.id, User.name).where(User.id.in_(added_by_user_ids))
        )
        for uid, uname in urows.all():
            user_name_by_id[uid] = uname

    # Standing rejections by this job's hiring manager, one batched query for
    # the whole board (none at all when the job has no manager set). Lets the
    # recruiter see the block before dragging a card into it, instead of
    # discovering it as a 409 halfway through the move.
    manager_verdicts = await load_manager_rejections(
        db, job=job, candidate_ids=candidate_ids
    )

    def _stage_resp_with_name(e: CandidateStage) -> dict:
        n, ln = name_by_id.get(e.candidate_id, (None, None))
        first = earliest.get(e.candidate_id)
        added_by_name = (
            user_name_by_id.get(first.moved_by)
            if first is not None and first.moved_by is not None
            else None
        )
        added_at = first.moved_at if first is not None else None
        payload = _stage_response(
            e,
            candidate_name=n,
            candidate_lastname=ln,
            added_to_job_by_name=added_by_name,
            added_to_job_at=added_at,
        )
        payload["contact_case"] = contact_case_by_candidate.get(e.candidate_id)
        verdict = manager_verdicts.get(e.candidate_id)
        if verdict is not None:
            payload["hm_veto"] = HiringManagerVetoBrief(
                hiring_manager_contact_id=verdict.hiring_manager_contact_id,
                hiring_manager_name=verdict.hiring_manager_name,
                source_job_id=verdict.source_job_id,
                source_job_title=verdict.source_job_title,
                rejected_at=verdict.rejected_at,
                rejection_reason_name=verdict.rejection_reason_name,
                rejection_note=verdict.rejection_note,
            )
        return payload

    # Resolve target template
    template_id = job.pipeline_template_id or await _default_template_id(db)

    if template_id is not None:
        # Template-driven columns
        stage_defs = (
            (
                await db.execute(
                    select(PipelineStageDef)
                    .where(PipelineStageDef.template_id == template_id)
                    .order_by(PipelineStageDef.order)
                )
            )
            .scalars()
            .all()
        )

        columns_map, off_template_entries = _bucket_by_stage_def(
            seen.values(), stage_defs
        )

        columns = []
        for sd in stage_defs:
            entries = columns_map.get(sd.id, [])
            legacy = None
            if sd.legacy_enum_value:
                try:
                    legacy = PipelineStage(sd.legacy_enum_value)
                except ValueError:
                    legacy = PipelineStage.new
            columns.append(
                KanbanColumn(
                    stage=legacy or PipelineStage.new,
                    category=sd.category,
                    count=len(entries),
                    items=[
                        CandidateStageResponse(**_stage_resp_with_name(e))
                        for e in entries
                    ],
                    stage_def_id=sd.id,
                    name=sd.name,
                    order=sd.order,
                    terminal_type=(
                        sd.terminal_type.value if sd.terminal_type else None
                    ),
                )
            )
        return KanbanView(
            job_id=job_id,
            columns=columns,
            off_template=await _build_off_template(
                db,
                job_id=job_id,
                entries=off_template_entries,
                render=_stage_resp_with_name,
            ),
        )

    # ── Legacy fallback (no template seeded yet) ──────────────────────────────
    # Ta gałąź pokrywa cały `PipelineStage`, więc dziś nic tu nie ginie. Kubełek
    # jest mimo to zbierany, żeby inwariant „suma kolumn + kubełek == liczba par"
    # trzymał na OBU ścieżkach i test regresji nie musiał się rozgałęziać.
    columns_map_legacy: dict[PipelineStage, list[CandidateStage]] = {
        s: [] for s in STAGE_ORDER
    }
    columns_map_legacy[PipelineStage.rejected] = []
    columns_map_legacy[PipelineStage.withdrawn] = []
    off_template_entries = []
    for stage_entry in seen.values():
        if stage_entry.stage in columns_map_legacy:
            columns_map_legacy[stage_entry.stage].append(stage_entry)
            continue
        off_template_entries.append(stage_entry)

    columns = []
    for stage in list(STAGE_ORDER) + [PipelineStage.rejected, PipelineStage.withdrawn]:
        entries = columns_map_legacy.get(stage, [])
        columns.append(
            KanbanColumn(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                count=len(entries),
                items=[
                    CandidateStageResponse(**_stage_resp_with_name(e)) for e in entries
                ],
                name=STAGE_LABELS[stage],
                # W tej gałęzi (brak szablonu) kolumny SĄ legacy enumami, więc
                # terminal wynika wprost z nazwy etapu. Wypełniamy to samo pole
                # co wyżej, żeby frontend miał jeden sposób rozpoznawania
                # terminala niezależnie od tego, którą ścieżką poszedł backend.
                terminal_type=_LEGACY_TERMINAL_TYPE.get(stage),
            )
        )
    return KanbanView(
        job_id=job_id,
        columns=columns,
        off_template=await _build_off_template(
            db,
            job_id=job_id,
            entries=off_template_entries,
            render=_stage_resp_with_name,
        ),
    )


@router.get(
    "/history/{candidate_id}/{job_id}", response_model=List[CandidateStageResponse]
)
async def get_stage_history(
    candidate_id: int,
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Full stage history for a candidate in a specific job."""
    # P1-PIPE-01: stage history is a per-job pipeline read — members only
    # (same scope as the kanban board).
    await ensure_job_read_access(db, current_user, job_id)
    result = await db.execute(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id, CandidateStage.job_id == job_id
        )
        .order_by(CandidateStage.moved_at.asc())
    )
    stages = result.scalars().all()
    return [CandidateStageResponse(**_stage_response(s)) for s in stages]


# ── Champion-profile screening answers (Phase 10) ───────────────────────────


@router.get("/stages/{stage_id}/screening")
async def get_stage_screening(
    stage_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Return recruiter screening answers + the job's Champion Profile."""
    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    job = await db.scalar(select(Job).where(Job.id == stage.job_id))
    return {
        "stage_id": stage.id,
        "candidate_id": stage.candidate_id,
        "job_id": stage.job_id,
        # Ten sam kontrakt co `/jobs/{id}/champion-profile`: front zna wyłącznie
        # siedem sekcji, a surowy kształt sprzed 09.2026 pokazałby mu pustkę na
        # wypełnionym profilu.
        "champion_profile": champion_view.api_response(
            job.champion_profile if job else None
        ),
        "screening_answers": stage.screening_answers or None,
    }


@router.post("/stages/{stage_id}/screening")
async def submit_stage_screening(
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Recruiter records answers to the Champion Profile screening questions.
    Also invalidates the (candidate, *) match score cache so the next
    recommendation read recomputes `champion_fit`.
    """
    from app.schemas.champion import ScreeningAnswers
    from app.services.match_score_cache import mark_stale_for_candidate

    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    answers = ScreeningAnswers.model_validate(payload or {})
    answers.answered_at = datetime.now(timezone.utc)
    answers.answered_by = current_user.id

    stage.screening_answers = answers.model_dump(mode="json")
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage.id,
            action="screening_answered",
            user_id=current_user.id,
            details={
                "candidate_id": stage.candidate_id,
                "job_id": stage.job_id,
                "overall_fit": answers.overall_fit,
                "match_percent": answers.match_percent(),
            },
        )
    )
    await db.commit()

    # Mark cached scores stale — champion_fit layer depends on these answers.
    # Cache nie ma TTL, więc nieudana invalidacja NIE naprawia się sama: kompozyt
    # (kandydat, oferta) serwuje przedscreeningowy `champion_fit` do czasu, aż coś
    # innego przypadkiem oznaczy tego kandydata. Milczące połknięcie czytało się
    # jak „AI nie zgadza się z moim screeningiem", więc zostawiamy ślad w logu
    # (LoggingIntegration mostkuje to do Sentry) i mówimy UI, że wynik jest stary.
    cache_invalidated = True
    try:
        await mark_stale_for_candidate(db, stage.candidate_id)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        cache_invalidated = False
        logger.warning(
            "match-score staleness marking failed for candidate=%s stage=%s: %s",
            stage.candidate_id,
            stage.id,
            exc,
        )
        await db.rollback()

    await db.refresh(stage)
    return {
        "stage_id": stage.id,
        "match_percent": answers.match_percent(),
        "screening_answers": stage.screening_answers,
        "cache_invalidated": cache_invalidated,
    }


# ── Champion Card share tokens (Phase 12) ───────────────────────────────────


@router.post("/stages/{stage_id}/share-token")
async def create_share_token(
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    expires_in_days: int = Query(30, ge=1, le=365),
):
    """Generate a shareable token for this CandidateStage's Champion card."""
    import hashlib
    import secrets
    from datetime import timedelta

    from app.models.champion_share import ChampionCardShareToken

    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    # Resource scope: wystawienie linku dla klienta to działanie NA rekrutacji,
    # nie ogólna operacja rekrutera. Bez tego członek zespołu oferty A mógł
    # wygenerować działający, publiczny link do karty kandydata z oferty B.
    await ensure_job_membership(db, current_user, stage.job_id)

    # Same outbound gate as the CV share link — this card goes to the client too.
    verdict = await veto_for_candidate_stage(db, candidate_stage_id=stage_id)
    if verdict is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{verdict.as_polish_detail()} Nie wysyłaj mu go ponownie.",
        )

    # v2: the secret lives only in the URL and as a SHA-256 digest in the DB.
    # The PK holds a non-secret revoke key, so a DB leak yields no working link.
    raw_token = secrets.token_urlsafe(36)
    revoke_key = f"v2${secrets.token_hex(16)}"
    token_digest = hashlib.sha256(raw_token.encode()).hexdigest()
    token = raw_token  # goes into the share URL
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    row = ChampionCardShareToken(
        token=revoke_key,
        token_sha256=token_digest,
        candidate_stage_id=stage_id,
        created_by=current_user.id,
        expires_at=expires_at,
    )
    db.add(row)
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage_id,
            action="champion_share_created",
            user_id=current_user.id,
            details={"expires_at": expires_at.isoformat()},
        )
    )
    await db.commit()
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "share_url_suffix": f"/share/champion-card/{token}",
    }


@router.delete("/stages/share-token/{token}")
async def revoke_share_token(
    token: str,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Revoke (soft-delete) a previously issued share token."""
    import hashlib

    from app.models.champion_share import ChampionCardShareToken

    # The caller holds the raw secret from the share URL, not the v2 PK
    # (revoke_key), so match the same dual-read way the public lookup does —
    # otherwise v2 tokens would be unrevocable.
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = await db.scalar(
        select(ChampionCardShareToken).where(
            (ChampionCardShareToken.token_sha256 == digest)
            | (
                (ChampionCardShareToken.token == token)
                & (ChampionCardShareToken.token_sha256.is_(None))
            )
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Token not found")

    # Resource scope — token adresuje zasób bez `stage_id` w ścieżce, więc
    # rekrutację wyprowadzamy z `candidate_stage_id` tokenu. Odwołanie cudzego
    # linku to zmiana stanu w cudzej rekrutacji (i sygnał, że taki link
    # istnieje), więc podlega tej samej bramce co jego wystawienie.
    job_id = await db.scalar(
        select(CandidateStage.job_id).where(CandidateStage.id == row.candidate_stage_id)
    )
    if job_id is None:
        raise HTTPException(status_code=404, detail="Token not found")
    await ensure_job_membership(db, current_user, job_id)

    row.revoked = True
    await db.commit()
    return {"status": "revoked", "token": token}


@router.get("/overview")
async def pipeline_overview(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Manager dashboard: bird's eye view across ALL jobs.
    Returns per-job stage counts + bottleneck alerts + workload per recruiter.

    F-07: gated to OperationalUser (excludes the read-only ``user`` viewer).
    The overview aggregates pipeline data across every job — recruiter workload,
    per-job candidate counts — which is operational intelligence, not a public
    dashboard. The bare ``CurrentUser`` let a QC/client viewer read it all.
    """

    # Optymalizacja 2026-07-27: dawniej `select(CandidateStage)` bez WHERE i bez
    # LIMIT (pełna hydratacja ~158k obiektów ORM z JSONB `scorecard_answers` /
    # `screening_answers` + Text `notes`) i dedupe pętlą w Pythonie, bez cache.
    # Teraz agregaty liczy Postgres na widoku `analytics_current_pipeline`
    # (DISTINCT ON per para, indeks `ix_analytics_cs_cand_job_moved`) — wzorzec
    # z `api/dashboard.py::pipeline_funnel`. Kształt odpowiedzi bez zmian.
    BOTTLENECK_THRESHOLD = 3  # More than 3 candidates in prep_call/screening → alert
    AGING_THRESHOLD_DAYS = 5  # Candidate stuck > 5 days → aging alert

    # ── Per-job breakdown (GROUP BY job_id, stage) ──
    # `first_candidate` = MIN(candidate_id): odtwarza kolejność pierwszego
    # wystąpienia joba przy dawnym skanie posortowanym po (candidate_id, job_id).
    per_job_rows = (
        await db.execute(
            text(
                "SELECT job_id, stage::text AS stage, COUNT(*)::int AS cnt, "
                "MIN(candidate_id) AS first_candidate "
                "FROM analytics_current_pipeline GROUP BY job_id, stage"
            )
        )
    ).all()

    jobs_data: dict[int, dict] = {}
    job_first_seen: dict[int, int] = {}
    for row in per_job_rows:
        jid = row.job_id
        bucket = jobs_data.setdefault(jid, {"stages": {}, "total": 0})
        bucket["stages"][row.stage] = bucket["stages"].get(row.stage, 0) + row.cnt
        bucket["total"] += row.cnt
        prev = job_first_seen.get(jid)
        if prev is None or row.first_candidate < prev:
            job_first_seen[jid] = row.first_candidate
    ordered_job_ids = sorted(jobs_data, key=lambda j: (job_first_seen[j], j))

    # Fetch job titles
    job_ids = list(jobs_data.keys())
    job_titles: dict[int, str] = {}
    job_recruiters: dict[int, int | None] = {}
    if job_ids:
        jobs_result = await db.execute(select(Job).where(Job.id.in_(job_ids)))
        for job in jobs_result.scalars().all():
            job_titles[job.id] = job.title
            job_recruiters[job.id] = job.recruiter_id

    # ── Bottleneck detection ──
    bottlenecks = []

    # ── Aging alerts (top 20 wg dni w etapie) ──
    # `days` liczone w SQL identycznie jak `_days_in_stage`: floor po dniach,
    # ucięte do 0. Sortowanie `days DESC, candidate_id, job_id` odtwarza stabilny
    # `sort(key=-days)` na liście, która była już posortowana po parze.
    aging_rows = (
        await db.execute(
            text(
                "WITH cur AS ("
                "  SELECT candidate_id, job_id, stage::text AS stage,"
                "         GREATEST(0, FLOOR("
                "             EXTRACT(EPOCH FROM (now() - moved_at)) / 86400"
                "         ))::int AS days"
                "  FROM analytics_current_pipeline"
                ") "
                "SELECT candidate_id, job_id, stage, days FROM cur "
                "WHERE stage NOT IN ('hired', 'rejected', 'withdrawn') "
                "  AND days > :aging_threshold "
                "ORDER BY days DESC, candidate_id, job_id "
                "LIMIT 20"
            ),
            {"aging_threshold": AGING_THRESHOLD_DAYS},
        )
    ).all()
    aging_alerts = [
        {
            "candidate_id": row.candidate_id,
            "job_id": row.job_id,
            "stage": row.stage,
            "days": row.days,
            "job_title": job_titles.get(row.job_id, "?"),
        }
        for row in aging_rows
    ]

    for jid in ordered_job_ids:
        data = jobs_data[jid]
        for stage_key in ["prep_call", "screening", "cv_sent"]:
            count = data["stages"].get(stage_key, 0)
            if count >= BOTTLENECK_THRESHOLD:
                bottlenecks.append(
                    {
                        "job_id": jid,
                        "job_title": job_titles.get(jid, "?"),
                        "stage": stage_key,
                        "count": count,
                        "message": f"Dużo kandydatów ({count}) czeka na {STAGE_LABELS.get(PipelineStage(stage_key), stage_key)} — potrzebna pomoc!",
                    }
                )

    # ── Workload per recruiter (by moved_by of latest entries) ──
    from app.models.user import User

    # `moved_by IS NULL` → bucket 0 ("Nieprzypisany"), jak w dawnej pętli.
    # Tie-break przy równym `cnt`: pierwsze wystąpienie rekrutera w skanie
    # posortowanym po (candidate_id, job_id) — stąd MIN(candidate_id), MIN(job_id).
    workload_rows = (
        await db.execute(
            text(
                "SELECT COALESCE(moved_by, 0) AS rid, COUNT(*)::int AS cnt, "
                "       MIN(candidate_id) AS first_candidate, "
                "       MIN(job_id) AS first_job "
                "FROM analytics_current_pipeline "
                "WHERE stage::text NOT IN ('hired', 'rejected', 'withdrawn') "
                "GROUP BY COALESCE(moved_by, 0) "
                "ORDER BY cnt DESC, first_candidate, first_job"
            )
        )
    ).all()

    recruiter_ids = [row.rid for row in workload_rows if row.rid > 0]
    recruiter_names: dict[int, str] = {}
    if recruiter_ids:
        users_result = await db.execute(select(User).where(User.id.in_(recruiter_ids)))
        for u in users_result.scalars().all():
            recruiter_names[u.id] = u.name

    workload = [
        {
            "recruiter_id": row.rid,
            "name": recruiter_names.get(row.rid, "Nieprzypisany"),
            "active_candidates": row.cnt,
        }
        for row in workload_rows
    ]

    # ── Opportunity alerts (acceptance/negotiation → help close!) ──
    opportunities = []
    for jid in ordered_job_ids:
        data = jobs_data[jid]
        acceptance_count = data["stages"].get("acceptance", 0) + data["stages"].get(
            "negotiation", 0
        )
        if acceptance_count > 0:
            opportunities.append(
                {
                    "job_id": jid,
                    "job_title": job_titles.get(jid, "?"),
                    "count": acceptance_count,
                    "message": f"{acceptance_count} kandydat(ów) do domknięcia w {job_titles.get(jid, '?')} — manager, pomóż!",
                }
            )

    return {
        "jobs": [
            {
                "job_id": jid,
                "title": job_titles.get(jid, "?"),
                "recruiter_id": job_recruiters.get(jid),
                "stages": jobs_data[jid]["stages"],
                "total": jobs_data[jid]["total"],
            }
            for jid in ordered_job_ids
        ],
        "bottlenecks": bottlenecks,
        "aging_alerts": aging_alerts,  # Top 20 (LIMIT w SQL)
        "opportunities": opportunities,
        "workload": workload,
        "stage_labels": {s.value: STAGE_LABELS[s] for s in PipelineStage},
    }


# ── Pending verification endpoints (migracja 0056) ──────────────────────────


@router.get(
    "/pending-verifications",
    response_model=List[PendingVerificationListItem],
)
async def list_pending_verifications(
    current_user: CandidateFinanceReadAccess,
    job_id: Optional[int] = Query(None, description="Filter by job_id"),
    mine: bool = Query(
        False,
        description=(
            "Legacy compatibility filter: limit to jobs where the current "
            "user is also the assigned delivery_lead. This flag only narrows "
            "the Admin/Finance read scope."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Lista kandydatów oczekujących akceptacji (verification_status=pending).

    Dostępna dla administratora i Finance. Rekruter, Delivery Lead i Head of
    Recruitment dostaną 403, ponieważ wiersze zawierają oczekiwaną stawkę oraz
    budżet stanowiska. Akceptacja i odrzucenie pozostają Admin-only.
    """
    query = (
        select(CandidateStage, Candidate, Job, User)
        .join(Candidate, Candidate.id == CandidateStage.candidate_id)
        .join(Job, Job.id == CandidateStage.job_id)
        .outerjoin(User, User.id == CandidateStage.moved_by)
        .where(CandidateStage.verification_status == VerificationStatus.pending)
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )
    if job_id is not None:
        query = query.where(CandidateStage.job_id == job_id)
    if mine:
        query = query.where(Job.delivery_lead_id == current_user.id)

    rows = (await db.execute(query)).all()
    items: list[PendingVerificationListItem] = []
    for cs, cand, job, mover in rows:
        full_name = f"{cand.name} {cand.lastname}".strip() or f"#{cand.id}"
        # M4 PR-02: znormalizowane porównanie dla approvera (P0.5).
        normalized_monthly = None
        normalization_note = None
        if cs.expected_rate_value is not None:
            normalized_monthly, normalization_note = normalize_rate_to_monthly(
                cs.expected_rate_value,
                cs.expected_rate_unit,
                cs.expected_rate_currency,
            )
        items.append(
            PendingVerificationListItem(
                candidate_stage_id=cs.id,
                candidate_id=cand.id,
                candidate_name=full_name,
                job_id=job.id,
                job_title=job.title,
                expected_rate_value=cs.expected_rate_value,
                expected_rate_unit=cs.expected_rate_unit,
                expected_rate_currency=cs.expected_rate_currency,
                budget_max_at_move=cs.budget_max_at_move,
                normalized_monthly_value=normalized_monthly,
                normalization_note=normalization_note,
                moved_at=cs.moved_at,
                moved_by=cs.moved_by,
                moved_by_name=mover.name if mover else None,
                notes=cs.notes,
            )
        )
    return items


@router.post(
    "/{candidate_stage_id}/accept-verification",
    response_model=CandidateStageResponse,
)
async def accept_verification(
    candidate_stage_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Akceptacja pending verification → status = active.

    Audit: zapisujemy approved_by + approved_at na samym CandidateStage,
    plus Activity log. Notyfikacja do recruitera który wrzucił (`moved_by`).
    """
    stage = await accept_pending_verification(
        db,
        candidate_stage_id=candidate_stage_id,
        approver_user_id=current_user.id,
    )

    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage.id,
            action="verification_accepted",
            user_id=current_user.id,
            details={
                "candidate_id": stage.candidate_id,
                "job_id": stage.job_id,
                "expected_rate_value": (
                    str(stage.expected_rate_value)
                    if stage.expected_rate_value is not None
                    else None
                ),
                "budget_max_at_move": stage.budget_max_at_move,
            },
        )
    )

    if (
        stage.moved_by
        and stage.moved_by != current_user.id
        and await notification_recipient_has_access(
            db,
            stage.moved_by,
            NotificationType.pending_verification,
            related_entity_type="candidate_stage",
            link=f"/jobs/{stage.job_id}",
        )
    ):
        db.add(
            Notification(
                user_id=stage.moved_by,
                title="Weryfikacja zaakceptowana",
                message=(
                    f"Twoja weryfikacja kandydata #{stage.candidate_id} "
                    f"na ofercie #{stage.job_id} została zaakceptowana."
                ),
                link=f"/jobs/{stage.job_id}",
                notification_type=NotificationType.pending_verification,
                related_entity_type="candidate_stage",
                related_entity_id=stage.id,
            )
        )

    await db.commit()
    await db.refresh(stage)

    # Phase 7.6 — fire-and-forget Teams notification (post-commit so the row
    # is durable before the background task resolves it from its own session).
    try:
        from app.services.teams_notifications import notify_decision_by_stage_id

        _spawn(
            notify_decision_by_stage_id(
                stage.id,
                decision="accepted",
                actor_name=current_user.name or current_user.email,
            ),
            f"teams_notify_decision_accepted(stage={stage.id})",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Teams notify (decision_accepted) scheduling failed: %s", exc)

    return CandidateStageResponse(**_stage_response(stage))


@router.post(
    "/{candidate_stage_id}/reject-verification",
    response_model=CandidateStageResponse,
)
async def reject_verification(
    candidate_stage_id: int,
    payload: PendingVerificationReject,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Odrzucenie pending verification → kandydat wraca na poprzedni stage.

    Akcje:
    1. Obecny CandidateStage dostaje status 'rejected' + audit fields.
    2. Tworzymy NOWY CandidateStage z poprzednim stage'em (najnowszy przed
       obecnym dla pary candidate+job) + notatkę "Rejected verification: …".
    3. Activity log + notification do recruitera (`moved_by`).
    """
    stage, revert = await reject_pending_verification(
        db,
        candidate_stage_id=candidate_stage_id,
        approver_user_id=current_user.id,
        note=payload.note,
    )
    revert_stage = revert.stage
    await create_original_cv_snapshot(db, revert)
    await maybe_ensure_contact_opportunity(
        db,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        source="pipeline",
        occurred_at=revert.moved_at,
    )

    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage.id,
            action="verification_rejected",
            user_id=current_user.id,
            details={
                "candidate_id": stage.candidate_id,
                "job_id": stage.job_id,
                "reverted_to_stage": revert_stage.value,
                "note": payload.note,
            },
        )
    )

    if (
        stage.moved_by
        and stage.moved_by != current_user.id
        and await notification_recipient_has_access(
            db,
            stage.moved_by,
            NotificationType.pending_verification,
            related_entity_type="candidate_stage",
            link=f"/jobs/{stage.job_id}",
        )
    ):
        db.add(
            Notification(
                user_id=stage.moved_by,
                title="Weryfikacja odrzucona",
                message=(
                    f"Twoja weryfikacja kandydata #{stage.candidate_id} "
                    f"na ofercie #{stage.job_id} została odrzucona: {payload.note}"
                ),
                link=f"/jobs/{stage.job_id}",
                notification_type=NotificationType.pending_verification,
                related_entity_type="candidate_stage",
                related_entity_id=stage.id,
            )
        )

    await db.commit()
    await db.refresh(stage)

    # Phase 7.6 — fire-and-forget Teams notification.
    try:
        from app.services.teams_notifications import notify_decision_by_stage_id

        _spawn(
            notify_decision_by_stage_id(
                stage.id,
                decision="rejected",
                actor_name=current_user.name or current_user.email,
                note=payload.note,
            ),
            f"teams_notify_decision_rejected(stage={stage.id})",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Teams notify (decision_rejected) scheduling failed: %s", exc)

    return CandidateStageResponse(**_stage_response(stage))


class BulkMoveRequest(BaseModel):
    candidate_ids: list[int]
    job_id: int
    stage: PipelineStage
    notes: str | None = None


@router.post("/bulk-move")
async def bulk_move_candidates(
    data: BulkMoveRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Move multiple candidates to a stage at once."""
    if not data.candidate_ids or not data.job_id:
        raise HTTPException(status_code=400, detail="candidate_ids and job_id required")

    # Phase 17 (migracja 0068): bulk-move nie obsługuje rejection_reason_id,
    # więc terminal stages (rejected/withdrawn) zablokowane — wymagają indywidualnego
    # ruchu z powodem. CHECK constraint na DB i tak by to wyłapał, ale clean 422
    # jest dużo lepszy niż IntegrityError.
    if data.stage in (PipelineStage.rejected, PipelineStage.withdrawn):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Bulk-move na stage '{data.stage.value}' niedozwolony — "
                "użyj indywidualnego /move z rejection_reason_id."
            ),
        )

    # M4 PR-02 (audyt P0.4/P0.7/P0.10): bulk nie robi terminal/gate shortcuts.
    # `verified` z bulk omijał gate budżetowy (default verification_status=
    # 'active', zero stawki), `hired` z bulk omijał hook Contract+ClientOrder
    # (baseline PR-00: 499 par hired-bez-kontraktu). FE nie używa bulk-move —
    # 422 z instrukcją zamiast cichej dziury. Nadrzędne wobec wcześniejszych
    # guardów ról z PR-01 (blokada dotyczy wszystkich).
    if data.stage in (PipelineStage.verified, PipelineStage.hired):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Bulk-move na stage '{data.stage.value}' niedozwolony — "
                "wymaga indywidualnego /move (gate stawki / artefakty "
                "zatrudnienia)."
            ),
        )

    # M4 PR-02 (audyt P0.7): limit, dedupe i walidacja wejścia.
    # Canonical command service takes a row lock per candidate.  Stable order
    # prevents two overlapping bulk requests with reversed input order from
    # deadlocking each other.
    unique_ids = canonical_candidate_lock_order(data.candidate_ids)
    if len(unique_ids) > 100:
        raise HTTPException(
            status_code=422,
            detail=f"Bulk-move przyjmuje maksymalnie 100 kandydatów "
            f"(otrzymano {len(unique_ids)} unikalnych).",
        )
    job = await db.scalar(select(Job).where(Job.id == data.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # P1-PIPE-01: bulk pipeline write — members only (same gate as /move).
    # Runs after the pure-input terminal/gate 422s above (which reveal nothing
    # job-specific) and before any candidate lookup.
    await ensure_job_membership(db, current_user, job.id)

    # Faza 1 globalnej kolejności blokad: komplet kandydatów rosnąco, ZANIM
    # `transition_process` w pętli niżej weźmie blokadę oferty. Bez tego pętla
    # przeplatała kandydat→oferta→kandydat i zakleszczała się z wsadowym
    # `sync_external_observed_processes` (Traffit), który blokuje wszystkich
    # kandydatów przed jakąkolwiek ofertą. Sam sort tego nie zamykał.
    # Kontrola istnienia jedzie na tym samym zapytaniu — zero dodatkowych rund.
    existing_ids = set(
        (await db.execute(lock_candidates_stmt(unique_ids))).scalars().all()
    )
    missing = [cid for cid in unique_ids if cid not in existing_ids]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Nieistniejący kandydaci: {missing[:20]}",
        )
    # P1-PIPE-01: eligibility gate ── bulk-move only ever targets non-terminal
    # stages (terminal/verified/hired 422 above), so every candidate is a
    # forward move and the hard block applies to all. Fail-closed: any
    # blacklisted / client-conflicted candidate rejects the batch (409),
    # identical to the single /move contract.
    await assert_candidates_move_eligible(
        db,
        candidate_ids=unique_ids,
        job=job,
        now=datetime.now(timezone.utc),
        enforce_manager_verdict=puts_candidate_before_client(data.stage),
    )

    moved = 0
    for cid in unique_ids:
        entry = await transition_process(
            db,
            candidate_id=cid,
            job_id=data.job_id,
            stage=data.stage,
            moved_at=datetime.now(timezone.utc),
            actor_user_id=current_user.id,
            work_channel=PriorityChannel.database,
            notes=data.notes,
        )
        await create_original_cv_snapshot(db, entry)
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=cid,
            job_id=data.job_id,
            source="pipeline",
            occurred_at=entry.moved_at,
        )
        moved += 1

    await db.commit()

    # Phase 17 (migracja 0068): recompute risk dla każdego kandydata.
    # Best-effort — pojedynczy fail nie blokuje response ani nie zostawia
    # sesji w failed transaction (M4 PR-02).
    from app.services.candidate_risk import on_candidate_stage_change

    try:
        for cid in unique_ids:
            await on_candidate_stage_change(db, cid)
        await db.commit()
    except Exception as _exc:  # noqa: BLE001
        logger.warning("bulk risk recompute failed: %s", _exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Auto-add to a talent pool when the bulk move is "CV → klient" (same
    # signal as the single /move path). Best-effort: a failure must not affect
    # the move that already committed above.
    if data.stage == PipelineStage.cv_sent:
        import logging as _logging

        from app.services.talent_pool_auto_add import auto_add_on_cv_sent

        pool_job = await db.scalar(select(Job).where(Job.id == data.job_id))
        if pool_job is not None:
            for cid in unique_ids:
                try:
                    pool_candidate = await db.scalar(
                        select(Candidate).where(Candidate.id == cid)
                    )
                    await auto_add_on_cv_sent(
                        db=db,
                        candidate_id=cid,
                        job=pool_job,
                        user_id=current_user.id,
                        candidate=pool_candidate,
                    )
                except Exception as e:  # noqa: BLE001
                    await db.rollback()
                    _logging.getLogger(__name__).warning(
                        "bulk auto_add_on_cv_sent failed candidate=%s job=%s: %s",
                        cid,
                        data.job_id,
                        e,
                    )
            await db.commit()

    return {"moved": moved, "stage": data.stage.value, "job_id": data.job_id}
