import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pydantic import BaseModel
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
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
from app.models.activity import Activity
from app.models.user_activity import UserActivity, UserActionType
from app.models.notification import Notification, NotificationType
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
)
from app.models.job import Job
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
)
from app.models.user import User, UserRole
from app.schemas.pipeline import (
    CandidateStageResponse,
    KanbanColumn,
    KanbanView,
    PendingVerificationListItem,
    PendingVerificationReject,
    StageMove,
    StageInfo,
    STAGE_LABELS,
)
from app.api.deps import ApproverPlus, CurrentUser, RecruiterPlus
from app.services.traffit.domain_commands import (
    capture_assignment_added,
    capture_stage_moved,
)

router = APIRouter()
logger = logging.getLogger(__name__)


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
    """Send `pending_verification` notification to all approver users.

    Approvers = admin + delivery_lead + head_of_recruitment. Best-effort —
    a notification failure must NOT block the stage move (the gate is the
    DB write, not the bell).
    """
    approvers = (
        await db.execute(
            select(User.id).where(
                User.role.in_(
                    [
                        UserRole.admin,
                        UserRole.delivery_lead,
                        UserRole.head_of_recruitment,
                    ]
                ),
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
    had_assignment = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == data.candidate_id,
            CandidateStage.job_id == data.job_id,
        )
        .limit(1)
    )

    stage_def = await _resolve_stage_def(
        db, job, stage_def_id=data.stage_def_id, legacy_stage=data.stage
    )

    # Derive effective legacy-enum value for backward-compat column
    legacy_enum: PipelineStage = data.stage or PipelineStage.new
    if stage_def and stage_def.legacy_enum_value:
        try:
            legacy_enum = PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            legacy_enum = data.stage or PipelineStage.new

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
        # Validate the FK
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

    # ── Pending verification gate (migracja 0056) ────────────────────────
    # Tylko ruch na stage `verified` triggeruje sprawdzenie rate vs budget.
    # Pozostałe stage'y zachowują defaultowe verification_status='active'.
    verification_status = VerificationStatus.active
    expected_rate_value = data.expected_rate_value
    expected_rate_unit = data.expected_rate_unit
    expected_rate_currency = data.expected_rate_currency or "PLN"
    budget_max_snapshot: Optional[int] = None
    needs_approval = False

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
            if Decimal(expected_rate_value) > Decimal(job.salary_max):
                verification_status = VerificationStatus.pending
                needs_approval = True

    stage = CandidateStage(
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        stage=legacy_enum,
        stage_def_id=stage_def.id if stage_def else None,
        rejection_reason_id=data.rejection_reason_id,
        moved_at=datetime.now(timezone.utc),
        moved_by=current_user.id,
        notes=data.notes,
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
    db.add(stage)
    await db.flush()
    await create_original_cv_snapshot(db, stage)
    if had_assignment is None:
        await capture_assignment_added(db, stage, job, actor_id=current_user.id)
    if not needs_approval:
        await capture_stage_moved(db, stage, job, actor_id=current_user.id)

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
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=current_user.id,
            details={
                "candidate_id": data.candidate_id,
                "job_id": data.job_id,
                "stage": legacy_enum.value,
                "stage_def_id": stage_def.id if stage_def else None,
                "stage_name": stage_display_name,
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

    # Configurable stage-transition notifications (migracja 0066).
    # Zastąpiło hardcoded recruiter-notify. Reguły wiszą na pipeline_stage_defs
    # (baseline) z opcjonalnym override per klient. Resolver + emitter robią
    # in-app + email (SMTP) per regułą. Best-effort: failure tu NIGDY nie
    # blokuje ruchu stage'a.
    try:
        from app.services.stage_notification_emitter import notify_stage_change

        # Najnowszy poprzedni stage tej pary candidate+job (do forward-only
        # check w resolverze).
        previous_stage = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == data.candidate_id,
                CandidateStage.job_id == data.job_id,
                CandidateStage.id != stage.id,
            )
            .order_by(CandidateStage.moved_at.desc())
            .limit(1)
        )
        candidate_obj = await db.scalar(
            select(Candidate).where(Candidate.id == data.candidate_id)
        )
        if candidate_obj is not None:
            await notify_stage_change(
                db,
                new_stage=stage,
                previous_stage=previous_stage,
                job=job,
                candidate=candidate_obj,
                mover=current_user,
                stage_display_name=stage_display_name,
            )
    except Exception as _exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "stage_notif top-level failure for stage=%s: %s", stage.id, _exc
        )

    # Phase 10 A1: auto-add candidate to a talent pool when CV is sent to the
    # client. The pool is resolved from the job title (classifier in
    # services/job_to_pool.py) against the existing curated catalogue, with the
    # candidate's skills disambiguating role variants. Best-effort — pool-add
    # failure must NOT block the stage change, so errors are swallowed/logged.
    if legacy_enum == PipelineStage.cv_sent:
        import logging

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
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "auto_add_on_cv_sent failed for candidate=%s job=%s: %s",
                data.candidate_id,
                job.id,
                e,
            )

    # Phase 9 A2 + DL portal refactor 2026-05-11:
    # Auto-create a draft Contract + draft ClientOrder when the candidate is
    # hired. DL fills in the rates/dates/PDF afterwards.
    if legacy_enum == PipelineStage.hired:
        from datetime import date as _date

        from app.models.client_order import ClientOrder, ClientOrderStatus
        from app.models.contract import Contract, ContractStatus
        from app.models.user import User, UserRole

        existing_draft = await db.scalar(
            select(Contract).where(
                Contract.candidate_id == data.candidate_id,
                Contract.client_id == job.client_id,
                Contract.job_id == job.id,
                Contract.status == ContractStatus.draft,
            )
        )
        if existing_draft is None and job.client_id:
            draft = Contract(
                candidate_id=data.candidate_id,
                client_id=job.client_id,
                job_id=job.id,
                start_date=_date.today(),
                status=ContractStatus.draft,
            )
            db.add(draft)
            await db.flush()

            # Order draft pod Contractem — DL uzupełni PDF + stawkę klienta
            # + dokładne daty. status=draft + auto-link do Job.
            cand = await db.scalar(
                select(Candidate).where(Candidate.id == data.candidate_id)
            )
            cand_name = cand.name if cand else f"#{data.candidate_id}"
            order_draft = ClientOrder(
                client_id=job.client_id,
                contract_id=draft.id,
                job_id=job.id,
                title=(
                    f"{cand_name} — {job.title}" if cand else f"Zamówienie #{job.id}"
                ),
                status=ClientOrderStatus.draft,
                start_date=_date.today(),
                created_by_user_id=current_user.id,
                notes=(
                    "Auto-utworzone z pipeline (kandydat na stage 'hired'). "
                    "Uzupełnij stawkę klienta, daty, i wgraj PDF zamówienia."
                ),
            )
            db.add(order_draft)
            await db.flush()

            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=draft.id,
                    action="auto_drafted_from_pipeline",
                    user_id=current_user.id,
                    details={
                        "candidate_id": data.candidate_id,
                        "job_id": job.id,
                        "stage": legacy_enum.value,
                        "order_id": order_draft.id,
                    },
                )
            )
            staff_ids_res = await db.execute(
                select(User.id).where(
                    User.role.in_(
                        [UserRole.admin, UserRole.delivery_lead, UserRole.tac]
                    ),
                    User.is_active.is_(True),
                )
            )
            for (uid,) in staff_ids_res.all():
                db.add(
                    Notification(
                        user_id=uid,
                        title=f"Nowy draft kontraktu + zamówienia #{draft.id}",
                        message=(
                            f"Kandydat {cand_name} został zatrudniony na "
                            f"ofertę '{job.title}' (#{job.id}). Uzupełnij stawki, "
                            "daty i wgraj PDF zamówienia."
                        ),
                        link=f"/clients/{job.client_id}?tab=zamowienia",
                        notification_type=NotificationType.contract_activated,
                        related_entity_type="contract",
                        related_entity_id=draft.id,
                    )
                )

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

    # Phase 17 (migracja 0068): event-driven recompute risk profile.
    # Best-effort — błąd nie blokuje response. Wymaga dodatkowego commitu
    # ponieważ poprzedni await db.commit() już zamknął transakcję.
    from app.services.candidate_risk import on_candidate_stage_change

    await on_candidate_stage_change(db, data.candidate_id)
    await db.commit()

    resp = _stage_response(stage)
    resp["scheduled_rejection_email_id"] = scheduled_rejection_email_id
    return CandidateStageResponse(**resp)


@router.get("/kanban/{job_id}", response_model=KanbanView)
async def get_kanban(
    job_id: int,
    current_user: CurrentUser,
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

    def _stage_resp_with_name(e: CandidateStage) -> dict:
        n, ln = name_by_id.get(e.candidate_id, (None, None))
        first = earliest.get(e.candidate_id)
        added_by_name = (
            user_name_by_id.get(first.moved_by)
            if first is not None and first.moved_by is not None
            else None
        )
        added_at = first.moved_at if first is not None else None
        return _stage_response(
            e,
            candidate_name=n,
            candidate_lastname=ln,
            added_to_job_by_name=added_by_name,
            added_to_job_at=added_at,
        )

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

        enum_to_def: dict[str, PipelineStageDef] = {
            sd.legacy_enum_value: sd for sd in stage_defs if sd.legacy_enum_value
        }

        columns_map: dict[int, list[CandidateStage]] = {sd.id: [] for sd in stage_defs}

        for entry in seen.values():
            # Prefer explicit FK; fall back to legacy enum mapping
            if entry.stage_def_id in columns_map:
                columns_map[entry.stage_def_id].append(entry)
            else:
                mapped = enum_to_def.get(entry.stage.value) if entry.stage else None
                if mapped:
                    columns_map[mapped.id].append(entry)

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
                )
            )
        return KanbanView(job_id=job_id, columns=columns)

    # ── Legacy fallback (no template seeded yet) ──────────────────────────────
    columns_map_legacy: dict[PipelineStage, list[CandidateStage]] = {
        s: [] for s in STAGE_ORDER
    }
    columns_map_legacy[PipelineStage.rejected] = []
    columns_map_legacy[PipelineStage.withdrawn] = []
    for stage_entry in seen.values():
        if stage_entry.stage in columns_map_legacy:
            columns_map_legacy[stage_entry.stage].append(stage_entry)

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
            )
        )
    return KanbanView(job_id=job_id, columns=columns)


@router.get(
    "/history/{candidate_id}/{job_id}", response_model=List[CandidateStageResponse]
)
async def get_stage_history(
    candidate_id: int,
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Full stage history for a candidate in a specific job."""
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
    current_user: CurrentUser,
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
        "champion_profile": (job.champion_profile if job else None) or {},
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
    try:
        await mark_stale_for_candidate(db, stage.candidate_id)
        await db.commit()
    except Exception:
        await db.rollback()

    await db.refresh(stage)
    return {
        "stage_id": stage.id,
        "match_percent": answers.match_percent(),
        "screening_answers": stage.screening_answers,
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
    import secrets
    from datetime import timedelta

    from app.models.champion_share import ChampionCardShareToken

    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    token = secrets.token_urlsafe(36)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    row = ChampionCardShareToken(
        token=token,
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
    from app.models.champion_share import ChampionCardShareToken

    row = await db.scalar(
        select(ChampionCardShareToken).where(ChampionCardShareToken.token == token)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Token not found")
    row.revoked = True
    await db.commit()
    return {"status": "revoked", "token": token}


@router.get("/overview")
async def pipeline_overview(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Manager dashboard: bird's eye view across ALL jobs.
    Returns per-job stage counts + bottleneck alerts + workload per recruiter.
    """

    # Get latest stage per candidate per job
    result = await db.execute(
        select(CandidateStage).order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
        )
    )
    all_entries = result.scalars().all()

    # Deduplicate: latest stage per (candidate, job) pair
    seen_keys: set[tuple[int, int]] = set()
    latest: list[CandidateStage] = []
    for entry in all_entries:
        key = (entry.candidate_id, entry.job_id)
        if key not in seen_keys:
            seen_keys.add(key)
            latest.append(entry)

    # ── Per-job breakdown ──
    jobs_data: dict[int, dict] = {}
    for entry in latest:
        jid = entry.job_id
        if jid not in jobs_data:
            jobs_data[jid] = {"stages": {}, "total": 0}
        stage_val = entry.stage.value
        jobs_data[jid]["stages"][stage_val] = (
            jobs_data[jid]["stages"].get(stage_val, 0) + 1
        )
        jobs_data[jid]["total"] += 1

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
    BOTTLENECK_THRESHOLD = 3  # More than 3 candidates in prep_call/screening → alert
    AGING_THRESHOLD_DAYS = 5  # Candidate stuck > 5 days → aging alert
    bottlenecks = []
    aging_alerts = []

    for entry in latest:
        days = _days_in_stage(entry.moved_at)
        if days > AGING_THRESHOLD_DAYS and entry.stage not in (
            PipelineStage.hired,
            PipelineStage.rejected,
            PipelineStage.withdrawn,
        ):
            aging_alerts.append(
                {
                    "candidate_id": entry.candidate_id,
                    "job_id": entry.job_id,
                    "stage": entry.stage.value,
                    "days": days,
                    "job_title": job_titles.get(entry.job_id, "?"),
                }
            )

    for jid, data in jobs_data.items():
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

    recruiter_load: dict[int, int] = {}
    for entry in latest:
        if entry.stage not in (
            PipelineStage.hired,
            PipelineStage.rejected,
            PipelineStage.withdrawn,
        ):
            rid = entry.moved_by or 0
            recruiter_load[rid] = recruiter_load.get(rid, 0) + 1

    recruiter_ids = [r for r in recruiter_load if r > 0]
    recruiter_names: dict[int, str] = {}
    if recruiter_ids:
        users_result = await db.execute(select(User).where(User.id.in_(recruiter_ids)))
        for u in users_result.scalars().all():
            recruiter_names[u.id] = u.name

    workload = [
        {
            "recruiter_id": rid,
            "name": recruiter_names.get(rid, "Nieprzypisany"),
            "active_candidates": count,
        }
        for rid, count in sorted(recruiter_load.items(), key=lambda x: -x[1])
    ]

    # ── Opportunity alerts (acceptance/negotiation → help close!) ──
    opportunities = []
    for jid, data in jobs_data.items():
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

    # Sort aging by days desc
    aging_alerts.sort(key=lambda x: -x["days"])

    return {
        "jobs": [
            {
                "job_id": jid,
                "title": job_titles.get(jid, "?"),
                "recruiter_id": job_recruiters.get(jid),
                "stages": data["stages"],
                "total": data["total"],
            }
            for jid, data in jobs_data.items()
        ],
        "bottlenecks": bottlenecks,
        "aging_alerts": aging_alerts[:20],  # Top 20
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
    current_user: ApproverPlus,
    job_id: Optional[int] = Query(None, description="Filter by job_id"),
    mine: bool = Query(
        False,
        description=(
            "Limit to jobs where current user is the delivery_lead. "
            "Used by the DL Hub widget to scope verifications to the logged-in DL."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Lista kandydatów oczekujących akceptacji (verification_status=pending).

    Dostępna tylko dla approverów (admin/delivery_lead/head_of_recruitment).
    Recruiter dostanie 403.
    """
    query = (
        select(CandidateStage, Candidate, Job, User)
        .join(Candidate, Candidate.id == CandidateStage.candidate_id)
        .join(Job, Job.id == CandidateStage.job_id)
        .outerjoin(User, User.id == CandidateStage.moved_by)
        .where(CandidateStage.verification_status == VerificationStatus.pending)
        .order_by(CandidateStage.moved_at.desc())
    )
    if job_id is not None:
        query = query.where(CandidateStage.job_id == job_id)
    if mine:
        query = query.where(Job.delivery_lead_id == current_user.id)

    rows = (await db.execute(query)).all()
    items: list[PendingVerificationListItem] = []
    for cs, cand, job, mover in rows:
        full_name = f"{cand.name} {cand.lastname}".strip() or f"#{cand.id}"
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
    current_user: ApproverPlus,
    db: AsyncSession = Depends(get_db),
):
    """Akceptacja pending verification → status = active.

    Audit: zapisujemy approved_by + approved_at na samym CandidateStage,
    plus Activity log. Notyfikacja do recruitera który wrzucił (`moved_by`).
    """
    stage = await db.scalar(
        select(CandidateStage).where(CandidateStage.id == candidate_stage_id)
    )
    if not stage:
        raise HTTPException(status_code=404, detail="CandidateStage not found")
    if stage.stage != PipelineStage.verified:
        raise HTTPException(
            status_code=422,
            detail="Akceptacja dotyczy wyłącznie stage'a 'verified'",
        )
    if stage.verification_status != VerificationStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=f"Status nie jest 'pending' (obecny: {stage.verification_status.value})",
        )

    stage.verification_status = VerificationStatus.active
    stage.approved_by = current_user.id
    stage.approved_at = datetime.now(timezone.utc)

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

    if stage.moved_by and stage.moved_by != current_user.id:
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

    stage_job = await db.scalar(select(Job).where(Job.id == stage.job_id))
    if stage_job is not None:
        await capture_stage_moved(
            db, stage, stage_job, actor_id=current_user.id
        )
    await db.commit()
    await db.refresh(stage)

    # Phase 7.6 — fire-and-forget Teams notification (post-commit so the row
    # is durable before the background task resolves it from its own session).
    try:
        from app.services.teams_notifications import notify_decision_by_stage_id

        asyncio.create_task(
            notify_decision_by_stage_id(
                stage.id,
                decision="accepted",
                actor_name=current_user.name or current_user.email,
            )
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
    current_user: ApproverPlus,
    db: AsyncSession = Depends(get_db),
):
    """Odrzucenie pending verification → kandydat wraca na poprzedni stage.

    Akcje:
    1. Obecny CandidateStage dostaje status 'rejected' + audit fields.
    2. Tworzymy NOWY CandidateStage z poprzednim stage'em (najnowszy przed
       obecnym dla pary candidate+job) + notatkę "Rejected verification: …".
    3. Activity log + notification do recruitera (`moved_by`).
    """
    stage = await db.scalar(
        select(CandidateStage).where(CandidateStage.id == candidate_stage_id)
    )
    if not stage:
        raise HTTPException(status_code=404, detail="CandidateStage not found")
    if stage.stage != PipelineStage.verified:
        raise HTTPException(
            status_code=422,
            detail="Reject dotyczy wyłącznie stage'a 'verified'",
        )
    if stage.verification_status != VerificationStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=f"Status nie jest 'pending' (obecny: {stage.verification_status.value})",
        )

    # Mark current as rejected (audit trail)
    now = datetime.now(timezone.utc)
    stage.verification_status = VerificationStatus.rejected
    stage.rejected_by = current_user.id
    stage.rejected_at = now
    stage.rejection_note = payload.note

    # Find previous stage for this (candidate, job) pair
    previous = await db.scalar(
        select(CandidateStage)
        .where(
            and_(
                CandidateStage.candidate_id == stage.candidate_id,
                CandidateStage.job_id == stage.job_id,
                CandidateStage.id != stage.id,
                CandidateStage.moved_at < stage.moved_at,
            )
        )
        .order_by(CandidateStage.moved_at.desc())
        .limit(1)
    )

    if previous is None:
        # Nigdy nie było wcześniejszego ruchu — wracamy na 'new'
        revert_stage = PipelineStage.new
        revert_stage_def_id: Optional[int] = None
    else:
        revert_stage = previous.stage
        revert_stage_def_id = previous.stage_def_id

    rate_label = (
        f"{stage.expected_rate_value} "
        f"{(stage.expected_rate_currency or 'PLN')}/"
        f"{(stage.expected_rate_unit or 'monthly')}"
    )
    budget_label = (
        f"{stage.budget_max_at_move}" if stage.budget_max_at_move is not None else "?"
    )
    revert = CandidateStage(
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        stage=revert_stage,
        stage_def_id=revert_stage_def_id,
        moved_at=now,
        moved_by=current_user.id,
        notes=(
            f"Rejected verification: {payload.note} "
            f"(rate {rate_label} > budżet {budget_label})"
        ),
        verification_status=VerificationStatus.active,
    )
    db.add(revert)
    await db.flush()
    await create_original_cv_snapshot(db, revert)

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

    if stage.moved_by and stage.moved_by != current_user.id:
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

        asyncio.create_task(
            notify_decision_by_stage_id(
                stage.id,
                decision="rejected",
                actor_name=current_user.name or current_user.email,
                note=payload.note,
            )
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

    job = await db.scalar(select(Job).where(Job.id == data.job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    moved = 0
    for cid in data.candidate_ids:
        had_assignment = await db.scalar(
            select(CandidateStage.id)
            .where(
                CandidateStage.candidate_id == cid,
                CandidateStage.job_id == data.job_id,
            )
            .limit(1)
        )
        entry = CandidateStage(
            candidate_id=cid,
            job_id=data.job_id,
            stage=data.stage,
            moved_at=datetime.now(timezone.utc),
            moved_by=current_user.id,
            notes=data.notes,
        )
        db.add(entry)
        await db.flush()
        await create_original_cv_snapshot(db, entry)
        if had_assignment is None:
            await capture_assignment_added(
                db, entry, job, actor_id=current_user.id
            )
        await capture_stage_moved(db, entry, job, actor_id=current_user.id)
        moved += 1

    await db.commit()

    # Phase 17 (migracja 0068): recompute risk dla każdego kandydata.
    # Best-effort — pojedynczy fail nie blokuje response.
    from app.services.candidate_risk import on_candidate_stage_change

    for cid in data.candidate_ids:
        await on_candidate_stage_change(db, cid)
    await db.commit()

    # Auto-add to a talent pool when the bulk move is "CV → klient" (same
    # signal as the single /move path). Best-effort: a failure must not affect
    # the move that already committed above.
    if data.stage == PipelineStage.cv_sent:
        import logging as _logging

        from app.services.talent_pool_auto_add import auto_add_on_cv_sent

        pool_job = await db.scalar(select(Job).where(Job.id == data.job_id))
        if pool_job is not None:
            for cid in data.candidate_ids:
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
