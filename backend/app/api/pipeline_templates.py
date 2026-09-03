"""
CRUD for pipeline templates, stages, and rejection reasons.

RBAC:
- GET  endpoints require authenticated user
- all mutations require Manager or Admin role
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, ManagerOrAdmin
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.job import Job
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
)
from app.models.recruitment_pipeline import CandidateStage
from app.schemas.pipeline_template import (
    AssignTemplatePayload,
    PipelineTemplateCreate,
    PipelineTemplateDetail,
    PipelineTemplateSummary,
    PipelineTemplateUpdate,
    RejectionReasonCreate,
    RejectionReasonResponse,
    RejectionReasonUpdate,
    StageDefCreate,
    StageDefResponse,
    StageDefUpdate,
    StageReorderItem,
)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


# ── Template CRUD ────────────────────────────────────────────────────────────


@router.get("", response_model=List[PipelineTemplateSummary])
async def list_templates(
    current_user: CurrentUser,
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """List all pipeline templates (summary). Excludes archived by default."""
    stmt = select(
        PipelineTemplate.id,
        PipelineTemplate.name,
        PipelineTemplate.description,
        PipelineTemplate.is_default,
        PipelineTemplate.archived,
        PipelineTemplate.client_id,
        PipelineTemplate.created_at,
        PipelineTemplate.updated_at,
        func.count(PipelineStageDef.id).label("stage_count"),
    ).join(
        PipelineStageDef,
        PipelineStageDef.template_id == PipelineTemplate.id,
        isouter=True,
    )
    if not include_archived:
        stmt = stmt.where(PipelineTemplate.archived.is_(False))
    stmt = stmt.group_by(PipelineTemplate.id).order_by(
        PipelineTemplate.is_default.desc(), PipelineTemplate.name
    )
    rows = (await db.execute(stmt)).all()
    return [
        PipelineTemplateSummary(
            id=r.id,
            name=r.name,
            description=r.description,
            is_default=r.is_default,
            archived=r.archived,
            client_id=r.client_id,
            stage_count=r.stage_count,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/{template_id}", response_model=PipelineTemplateDetail)
async def get_template(
    template_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Eager-load stages + reasons via explicit queries (sorted)
    stages_result = await db.execute(
        select(PipelineStageDef)
        .where(PipelineStageDef.template_id == template_id)
        .order_by(PipelineStageDef.order)
    )
    reasons_result = await db.execute(
        select(RejectionReason)
        .where(
            RejectionReason.template_id == template_id, RejectionReason.active.is_(True)
        )
        .order_by(RejectionReason.category, RejectionReason.order)
    )
    return PipelineTemplateDetail(
        id=template.id,
        name=template.name,
        description=template.description,
        is_default=template.is_default,
        archived=template.archived,
        client_id=template.client_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
        stages=[
            StageDefResponse.model_validate(s) for s in stages_result.scalars().all()
        ],
        rejection_reasons=[
            RejectionReasonResponse.model_validate(r)
            for r in reasons_result.scalars().all()
        ],
    )


@router.post(
    "",
    response_model=PipelineTemplateDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    data: PipelineTemplateCreate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    # If marking default, unset any existing default atomically
    if data.is_default:
        await db.execute(
            select(PipelineTemplate).where(PipelineTemplate.is_default.is_(True))
        )
        # Raw UPDATE to avoid race (single statement)
        from sqlalchemy import update

        await db.execute(
            update(PipelineTemplate)
            .where(PipelineTemplate.is_default.is_(True))
            .values(is_default=False)
        )

    template = PipelineTemplate(
        name=data.name,
        description=data.description,
        is_default=data.is_default,
        client_id=data.client_id,
        created_by=current_user.id,
    )
    db.add(template)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Template name conflict: {e}"
        ) from e
    await db.refresh(template)
    return PipelineTemplateDetail(
        id=template.id,
        name=template.name,
        description=template.description,
        is_default=template.is_default,
        archived=template.archived,
        client_id=template.client_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
        stages=[],
        rejection_reasons=[],
    )


@router.patch("/{template_id}", response_model=PipelineTemplateSummary)
async def update_template(
    template_id: int,
    data: PipelineTemplateUpdate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = data.model_dump(exclude_unset=True)

    # ── M4 PR-02 (audyt P2.5): PATCH nie może ominąć ochron DELETE ─────────
    # `archived=true` przez PATCH omijał guardy endpointu DELETE (default /
    # in-use), a `is_default=false` na jedynym defaulcie zostawiał system bez
    # żadnego domyślnego template'u (resolver legacy stage'ów przestaje
    # działać).
    if update_data.get("archived") is True and not template.archived:
        if template.is_default:
            raise HTTPException(
                status_code=409, detail="Cannot archive the default template"
            )
        jobs_using = await db.scalar(
            select(func.count(Job.id)).where(Job.pipeline_template_id == template_id)
        )
        if jobs_using and jobs_using > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot archive: {jobs_using} job(s) still use this template",
            )
    if update_data.get("is_default") is False and template.is_default:
        raise HTTPException(
            status_code=409,
            detail=(
                "Nie można odebrać statusu default jedynemu domyślnemu "
                "template'owi — ustaw najpierw inny jako default."
            ),
        )

    # Handle is_default exclusivity
    if update_data.get("is_default"):
        from sqlalchemy import update

        await db.execute(
            update(PipelineTemplate)
            .where(
                PipelineTemplate.is_default.is_(True),
                PipelineTemplate.id != template_id,
            )
            .values(is_default=False)
        )

    for key, value in update_data.items():
        setattr(template, key, value)

    await db.commit()
    await db.refresh(template)

    # stage_count
    stages_count = await db.scalar(
        select(func.count(PipelineStageDef.id)).where(
            PipelineStageDef.template_id == template_id
        )
    )
    return PipelineTemplateSummary(
        id=template.id,
        name=template.name,
        description=template.description,
        is_default=template.is_default,
        archived=template.archived,
        client_id=template.client_id,
        stage_count=stages_count or 0,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_template(
    template_id: int,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Soft-archive (cannot archive a template with jobs attached)."""
    jobs_using = await db.scalar(
        select(func.count(Job.id)).where(Job.pipeline_template_id == template_id)
    )
    if jobs_using and jobs_using > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot archive: {jobs_using} job(s) still use this template",
        )

    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.is_default:
        raise HTTPException(
            status_code=409, detail="Cannot archive the default template"
        )
    template.archived = True
    await db.commit()


@router.post(
    "/{template_id}/clone",
    response_model=PipelineTemplateDetail,
    status_code=status.HTTP_201_CREATED,
)
async def clone_template(
    template_id: int,
    current_user: ManagerOrAdmin,
    new_name: str = Query(..., max_length=100),
    db: AsyncSession = Depends(get_db),
):
    """Duplicate a template (incl. stages + rejection reasons) under a new name."""
    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == template_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Template not found")

    new_template = PipelineTemplate(
        name=new_name,
        description=source.description,
        is_default=False,
        created_by=current_user.id,
    )
    db.add(new_template)
    try:
        await db.flush()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Name conflict: {e}") from e

    stages_res = await db.execute(
        select(PipelineStageDef).where(PipelineStageDef.template_id == template_id)
    )
    for s in stages_res.scalars().all():
        db.add(
            PipelineStageDef(
                template_id=new_template.id,
                name=s.name,
                order=s.order,
                category=s.category,
                is_terminal=s.is_terminal,
                terminal_type=s.terminal_type,
                tracker_enabled=s.tracker_enabled,
                tracker_public_name=s.tracker_public_name,
                sla_max_days=s.sla_max_days,
                # M4-P0.2: carry the per-stage scorecard so a cloned template
                # keeps its evaluation rubric (was silently dropped → custom
                # processes lost their scorecards on clone).
                scorecard_schema=s.scorecard_schema,
                # legacy_enum_value intentionally NOT copied — only default template has it
            )
        )

    reasons_res = await db.execute(
        select(RejectionReason).where(RejectionReason.template_id == template_id)
    )
    for r in reasons_res.scalars().all():
        db.add(
            RejectionReason(
                template_id=new_template.id,
                name=r.name,
                order=r.order,
                category=r.category,
                active=r.active,
                # Bez tego sklonowany szablon cicho gubi blokadę hiring managera
                # — ten sam powód przestawałby dyskwalifikować na nowym procesie.
                disqualifies_person=r.disqualifies_person,
            )
        )

    await db.commit()
    # Return detail view
    return await get_template(new_template.id, current_user, db)


# ── Stage CRUD within a template ────────────────────────────────────────────


@router.post(
    "/{template_id}/stages",
    response_model=StageDefResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_stage(
    template_id: int,
    data: StageDefCreate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    # Validate template exists
    exists = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.id == template_id)
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Template not found")

    # Validate terminal_type consistency
    if data.is_terminal and data.terminal_type is None:
        raise HTTPException(
            status_code=422,
            detail="is_terminal=True requires terminal_type",
        )
    # M4 PR-02 (audyt P2.5): symetryczny check — terminal_type na
    # NIEterminalnym etapie mylił reguły raportów/maili.
    if not data.is_terminal and data.terminal_type is not None:
        raise HTTPException(
            status_code=422,
            detail="terminal_type dozwolony tylko dla etapu terminalnego.",
        )

    stage = PipelineStageDef(template_id=template_id, **data.model_dump())
    db.add(stage)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Stage name/order conflict: {e}"
        ) from e
    await db.refresh(stage)
    return stage


# NOTE: the static `/stages/reorder` route MUST be declared before the
# parameterized `/stages/{stage_id}` route. FastAPI matches routes in
# declaration order, so if `{stage_id}` came first, `PATCH .../stages/reorder`
# would bind to it with stage_id="reorder" → 422 int_parsing and never reach
# reorder_stages. Keep reorder_stages above update_stage.
@router.patch("/{template_id}/stages/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_stages(
    template_id: int,
    items: List[StageReorderItem],
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Bulk reorder: body = [{stage_id, order}, ...]."""
    # Fetch current stages
    res = await db.execute(
        select(PipelineStageDef).where(PipelineStageDef.template_id == template_id)
    )
    stages = {s.id: s for s in res.scalars().all()}

    # M4 PR-02 (audyt P2.5): reorder wymaga PEŁNEJ permutacji etapów
    # template'u z unikalnymi orderami. Częściowa lista kolidowała orderami z
    # niedotkniętymi etapami (IntegrityError 500) albo zostawiała
    # niejednoznaczną kolejność.
    provided_ids = [item.stage_id for item in items]
    if len(set(provided_ids)) != len(provided_ids):
        raise HTTPException(
            status_code=422, detail="Zduplikowane stage_id w reorderze."
        )
    if set(provided_ids) != set(stages.keys()):
        missing = sorted(set(stages.keys()) - set(provided_ids))
        extra = sorted(set(provided_ids) - set(stages.keys()))
        raise HTTPException(
            status_code=422,
            detail=(
                "Reorder wymaga pełnej listy etapów template'u. "
                f"Brakujące: {missing}, spoza template'u: {extra}."
            ),
        )
    provided_orders = [item.order for item in items]
    if len(set(provided_orders)) != len(provided_orders):
        raise HTTPException(
            status_code=422, detail="Zduplikowane wartości order w reorderze."
        )

    # Two-phase update to avoid violating unique (template_id, order)
    # Phase 1: assign temporary negative orders to items we are reordering
    for i, item in enumerate(items, start=1):
        s = stages.get(item.stage_id)
        if not s:
            raise HTTPException(
                status_code=404,
                detail=f"Stage {item.stage_id} not in template {template_id}",
            )
        s.order = -i  # negative temp

    await db.flush()

    # Phase 2: assign target orders
    for item in items:
        stages[item.stage_id].order = item.order

    await db.commit()


@router.patch("/{template_id}/stages/{stage_id}", response_model=StageDefResponse)
async def update_stage(
    template_id: int,
    stage_id: int,
    data: StageDefUpdate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PipelineStageDef).where(
            PipelineStageDef.id == stage_id,
            PipelineStageDef.template_id == template_id,
        )
    )
    stage = result.scalar_one_or_none()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    update_data = data.model_dump(exclude_unset=True)

    # M4 PR-02 (audyt P2.5): spójność terminalności PO zastosowaniu patcha —
    # is_terminal bez terminal_type (i odwrotnie) tworzyło etapy, których
    # reguły hired/rejected/withdrawn nie umiały obsłużyć.
    resulting_is_terminal = update_data.get("is_terminal", stage.is_terminal)
    resulting_terminal_type = update_data.get("terminal_type", stage.terminal_type)
    if resulting_is_terminal and resulting_terminal_type is None:
        raise HTTPException(
            status_code=422,
            detail="Etap terminalny wymaga terminal_type (hired/rejected/withdrawn).",
        )
    if not resulting_is_terminal and resulting_terminal_type is not None:
        raise HTTPException(
            status_code=422,
            detail="terminal_type dozwolony tylko dla etapu terminalnego.",
        )

    for key, value in update_data.items():
        setattr(stage, key, value)

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    await db.refresh(stage)
    return stage


@router.delete(
    "/{template_id}/stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_stage(
    template_id: int,
    stage_id: int,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    # Block delete when candidates are currently in this stage
    in_use = await db.scalar(
        select(func.count(CandidateStage.id)).where(
            CandidateStage.stage_def_id == stage_id
        )
    )
    if in_use and in_use > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: {in_use} candidate(s) in this stage",
        )
    res = await db.execute(
        select(PipelineStageDef).where(
            PipelineStageDef.id == stage_id,
            PipelineStageDef.template_id == template_id,
        )
    )
    stage = res.scalar_one_or_none()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if stage.is_terminal:
        raise HTTPException(status_code=409, detail="Cannot delete a terminal stage")
    await db.delete(stage)
    await db.commit()


# ── Rejection reasons ───────────────────────────────────────────────────────


@router.post(
    "/{template_id}/rejection-reasons",
    response_model=RejectionReasonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_rejection_reason(
    template_id: int,
    data: RejectionReasonCreate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    exists = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.id == template_id)
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Template not found")

    reason = RejectionReason(template_id=template_id, **data.model_dump())
    db.add(reason)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    await db.refresh(reason)
    return reason


@router.patch(
    "/{template_id}/rejection-reasons/{reason_id}",
    response_model=RejectionReasonResponse,
)
async def update_rejection_reason(
    template_id: int,
    reason_id: int,
    data: RejectionReasonUpdate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(RejectionReason).where(
            RejectionReason.id == reason_id,
            RejectionReason.template_id == template_id,
        )
    )
    reason = res.scalar_one_or_none()
    if not reason:
        raise HTTPException(status_code=404, detail="Reason not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(reason, key, value)
    await db.commit()
    await db.refresh(reason)
    return reason


@router.delete(
    "/{template_id}/rejection-reasons/{reason_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_rejection_reason(
    template_id: int,
    reason_id: int,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Soft-disable (active=false) — preserves references on historical stages."""
    res = await db.execute(
        select(RejectionReason).where(
            RejectionReason.id == reason_id,
            RejectionReason.template_id == template_id,
        )
    )
    reason = res.scalar_one_or_none()
    if not reason:
        raise HTTPException(status_code=404, detail="Reason not found")
    reason.active = False
    await db.commit()


# ── Job-template assignment ─────────────────────────────────────────────────


@router.post("/assign-to-job/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def assign_template_to_job(
    job_id: int,
    data: AssignTemplatePayload,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Assign a pipeline template to a job."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    template = await db.scalar(
        select(PipelineTemplate).where(PipelineTemplate.id == data.template_id)
    )
    if not template or template.archived:
        raise HTTPException(status_code=404, detail="Template not found or archived")
    job.pipeline_template_id = data.template_id
    await db.commit()
