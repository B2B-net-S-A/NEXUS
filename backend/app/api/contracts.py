from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import TemplateError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.contract_templates import _contract_vars, _jinja_env
from app.core.database import get_db
from app.models.activity import Activity
from app.models.call import Call
from app.models.candidate import Candidate
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    RateUnit,
)
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_equipment import ContractEquipment, EquipmentReturnStatus
from app.models.contract_onboarding import ContractOnboardingItem
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_template import ContractTemplate
from app.models.job import Job
from app.models.note import Note
from app.models.rate_benchmark import RateBenchmark
from app.models.rate_history import RateHistory
from app.models.user import User
from app.schemas.contract import (
    ContractActivateRequest,
    ContractActivityEntry,
    ContractBenchmarkComparison,
    ContractCreate,
    ContractDetailResponse,
    ContractDraftFinalizeResponse,
    ContractDraftResponse,
    ContractDraftUpdate,
    ContractList,
    ContractRateHistoryEntry,
    ContractResponse,
    ContractTemplateBrief,
    ContractTerminateRequest,
    ContractTimelineItem,
    ContractUpdate,
)
from app.schemas.contract_amendment import (
    ContractAmendmentCreate,
    ContractAmendmentResponse,
)
from app.schemas.contract_document import (
    ContractDocumentResponse,
    ContractDocumentUpdate,
)
from app.schemas.contract_equipment import (
    ContractEquipmentCreate,
    ContractEquipmentResponse,
    ContractEquipmentUpdate,
)
from app.schemas.contract_onboarding import (
    OnboardingItemCreate,
    OnboardingItemResponse,
    OnboardingItemUpdate,
)
from app.services import storage_service
from app.services.contract_service import validate_ready_for_activation
from app.tasks.contract_alerts import run_contract_alerts_cycle
from app.api.deps import AdminUser, CurrentUser, TacPlus

router = APIRouter()

# Upload limit — nothing fancy, we're storing contracts + PDFs, not media.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

EXPIRY_WARNING_DAYS = 30


def _to_detail(contract: Contract) -> ContractDetailResponse:
    """Serialize a Contract (with eager-loaded relations) to the detail schema."""
    data = {
        "id": contract.id,
        "candidate_id": contract.candidate_id,
        "client_id": contract.client_id,
        "job_id": contract.job_id,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "client_order_end_date": contract.client_order_end_date,
        "rate_candidate": contract.rate_candidate,
        "rate_client": contract.rate_client,
        "target_rate_min": contract.target_rate_min,
        "target_rate_max": contract.target_rate_max,
        "currency": contract.currency,
        "rate_unit": contract.rate_unit,
        "billing_hours_per_month": contract.billing_hours_per_month,
        "margin": contract.margin,
        "contract_type": contract.contract_type,
        "status": contract.status,
        "documents": contract.documents,
        "client_pm_name": contract.client_pm_name,
        "client_pm_email": contract.client_pm_email,
        "work_mode": contract.work_mode,
        "office_location": contract.office_location,
        "team_name": contract.team_name,
        "project_name": contract.project_name,
        "handover_notes": contract.handover_notes,
        "termination_reason": contract.termination_reason,
        "termination_lessons": contract.termination_lessons,
        "terminated_at": contract.terminated_at,
        "monthly_rate_candidate": contract.monthly_rate_candidate,
        "monthly_rate_client": contract.monthly_rate_client,
        "monthly_margin": contract.monthly_margin,
        "created_at": contract.created_at,
        "updated_at": contract.updated_at,
        "candidate_name": (
            f"{contract.candidate.name} {contract.candidate.lastname}"
            if contract.candidate
            else None
        ),
        "client_name": contract.client.name if contract.client else None,
        "job_title": contract.job.title if contract.job else None,
    }
    return ContractDetailResponse(**data)


@router.get("", response_model=ContractList)
async def list_contracts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[list[ContractStatus]] = Query(
        None,
        description=(
            "Filter by `status` — one or more values. Repeat the param for "
            "multi-select (e.g. `?status=active&status=ending`). OR-combined."
        ),
    ),
    client_id: Optional[int] = None,
    candidate_id: Optional[int] = None,
    contract_type: Optional[list[str]] = Query(
        None,
        description=(
            "Filter by `contract_type` (engagement model: body_leasing / "
            "fixed_price / t_and_m). Repeat the param for multi-select. OR-combined."
        ),
    ),
    start_from: Optional[date] = Query(None),
    start_to: Optional[date] = Query(None),
    end_from: Optional[date] = Query(None),
    end_to: Optional[date] = Query(None),
    rate_client_min: Optional[int] = Query(None, ge=0),
    rate_client_max: Optional[int] = Query(None, ge=0),
    margin_min: Optional[int] = Query(None),
    expiring_in_days: Optional[int] = Query(None, ge=0, le=365),
):
    """List contracts with advanced filters (Phase 9 C5)."""
    query = select(Contract)
    if status:
        query = query.where(Contract.status.in_(status))
    if client_id:
        query = query.where(Contract.client_id == client_id)
    if candidate_id:
        query = query.where(Contract.candidate_id == candidate_id)
    if contract_type:
        query = query.where(Contract.contract_type.in_(contract_type))
    if start_from:
        query = query.where(Contract.start_date >= start_from)
    if start_to:
        query = query.where(Contract.start_date <= start_to)
    if end_from:
        query = query.where(Contract.end_date >= end_from)
    if end_to:
        query = query.where(Contract.end_date <= end_to)
    if rate_client_min is not None:
        query = query.where(Contract.rate_client >= rate_client_min)
    if rate_client_max is not None:
        query = query.where(Contract.rate_client <= rate_client_max)
    if margin_min is not None:
        query = query.where(Contract.margin >= margin_min)
    if expiring_in_days is not None:
        today = date.today()
        cutoff = today + timedelta(days=expiring_in_days)
        query = query.where(
            Contract.end_date.isnot(None),
            Contract.end_date <= cutoff,
            Contract.end_date >= today,
        )
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return ContractList(
        items=list(result.scalars().all()), total=total, page=page, page_size=page_size
    )


@router.post("", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def create_contract(
    data: ContractCreate, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    contract = Contract(**data.model_dump())
    db.add(contract)
    await db.flush()
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="created",
            user_id=current_user.id,
        )
    )
    await db.refresh(contract)
    return contract


@router.post("/alerts/run", status_code=status.HTTP_200_OK)
async def run_alerts_now(current_user: AdminUser):
    """Admin trigger for the contract-alerts cycle — useful for smoke tests."""
    stats = await run_contract_alerts_cycle()
    return stats


# ── Bulk operations (Phase 9 C3) ─────────────────────────────────────────────


@router.post("/bulk-extend", status_code=status.HTTP_200_OK)
async def bulk_extend_contracts(
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
    contract_ids: list[int] = Query(..., alias="ids"),
    months: int = Query(..., ge=1, le=24, description="Extension in months"),
):
    """Extend each selected contract's end_date by N months.

    If end_date is NULL, the contract is skipped. Returns per-id outcome.
    """
    if not contract_ids:
        raise HTTPException(status_code=422, detail="No contract ids provided")
    result = await db.execute(select(Contract).where(Contract.id.in_(contract_ids)))
    contracts = list(result.scalars().all())
    extended = 0
    skipped: list[int] = []
    for c in contracts:
        if c.end_date is None:
            skipped.append(c.id)
            continue
        # Add N months naively (month-wise; day may clamp if end-of-month)
        y, m = c.end_date.year, c.end_date.month + months
        while m > 12:
            m -= 12
            y += 1
        new_day = min(c.end_date.day, 28)  # safe for all months
        c.end_date = c.end_date.replace(year=y, month=m, day=new_day)
        # If the contract had rolled to ending/ended, bring it back to active
        if c.status in (ContractStatus.ending, ContractStatus.ended):
            c.status = ContractStatus.active
        extended += 1
    for cid in contract_ids:
        db.add(
            Activity(
                entity_type="contract",
                entity_id=cid,
                action=f"bulk_extended_{months}m",
                user_id=current_user.id,
            )
        )
    await db.commit()
    return {
        "requested": len(contract_ids),
        "extended": extended,
        "skipped_no_end_date": skipped,
    }


@router.post("/bulk-mark-ended", status_code=status.HTTP_200_OK)
async def bulk_mark_ended(
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
    contract_ids: list[int] = Query(..., alias="ids"),
):
    """Mark each selected contract as ended (status='ended')."""
    if not contract_ids:
        raise HTTPException(status_code=422, detail="No contract ids provided")
    result = await db.execute(select(Contract).where(Contract.id.in_(contract_ids)))
    contracts = list(result.scalars().all())
    changed = 0
    today = date.today()
    for c in contracts:
        c.status = ContractStatus.ended
        if c.end_date is None or c.end_date > today:
            c.end_date = today
        changed += 1
        db.add(
            Activity(
                entity_type="contract",
                entity_id=c.id,
                action="bulk_marked_ended",
                user_id=current_user.id,
            )
        )
    await db.commit()
    return {"requested": len(contract_ids), "changed": changed}


@router.get("/expiring", response_model=List[ContractResponse])
async def expiring_contracts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(EXPIRY_WARNING_DAYS, ge=1, le=90),
):
    """Return contracts expiring within N days."""
    cutoff = date.today() + timedelta(days=days)
    result = await db.execute(
        select(Contract).where(
            Contract.end_date <= cutoff,
            Contract.end_date >= date.today(),
            Contract.status == ContractStatus.active,
        )
    )
    return list(result.scalars().all())


@router.get("/{contract_id}", response_model=ContractDetailResponse)
async def get_contract(
    contract_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Return contract with denormalized candidate/client/job names."""
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return _to_detail(contract)


@router.get("/{contract_id}/activities", response_model=List[ContractActivityEntry])
async def contract_activities(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """Return activity log entries for a contract, newest first."""
    contract_exists = await db.execute(
        select(Contract.id).where(Contract.id == contract_id)
    )
    if contract_exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    result = await db.execute(
        select(Activity, User.email)
        .outerjoin(User, Activity.user_id == User.id)
        .where(Activity.entity_type == "contract", Activity.entity_id == contract_id)
        .order_by(Activity.created_at.desc())
        .limit(limit)
    )
    entries: list[ContractActivityEntry] = []
    for activity, user_email in result.all():
        entries.append(
            ContractActivityEntry(
                id=activity.id,
                action=activity.action,
                details=activity.details,
                user_id=activity.user_id,
                user_name=user_email,
                created_at=activity.created_at,
            )
        )
    return entries


@router.get(
    "/{contract_id}/rate-history", response_model=List[ContractRateHistoryEntry]
)
async def contract_rate_history(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return rate history for this contract's candidate+client combination."""
    contract_result = await db.execute(
        select(Contract).where(Contract.id == contract_id)
    )
    contract = contract_result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    history_query = select(RateHistory).where(
        RateHistory.candidate_id == contract.candidate_id
    )
    history_query = history_query.where(
        (RateHistory.client_id == contract.client_id)
        | (RateHistory.client_id.is_(None))
    )
    history_query = history_query.order_by(RateHistory.start_date.desc())

    result = await db.execute(history_query)
    return [
        ContractRateHistoryEntry(
            id=r.id,
            rate=r.rate,
            currency=r.currency,
            contract_type=r.contract_type.value
            if hasattr(r.contract_type, "value")
            else str(r.contract_type),
            start_date=r.start_date,
            end_date=r.end_date,
            notes=r.notes,
            created_at=r.created_at,
        )
        for r in result.scalars().all()
    ]


@router.patch("/{contract_id}", response_model=ContractDetailResponse)
async def update_contract(
    contract_id: int,
    data: ContractUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(contract, k, v)
    contract.margin = contract.calculate_margin()
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="updated",
            user_id=current_user.id,
            details={
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in updates.items()
            },
        )
    )
    await db.flush()
    await db.refresh(contract)
    return _to_detail(contract)


@router.post("/{contract_id}/activate", response_model=ContractDetailResponse)
async def activate_contract(
    contract_id: int,
    _: ContractActivateRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Flip a draft contract to `active` after validating required fields.

    Contractor module — called from the DraftCompletionModal after the client
    has PATCH-ed the draft with start_date / end_date / rates / type / mode.
    Returns 409 with the list of missing fields if anything is still blank,
    so the UI can re-render the form without losing filled data.
    """
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.status != ContractStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contract is already {contract.status.value}, cannot activate",
        )

    missing = validate_ready_for_activation(contract)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Missing required fields", "missing": missing},
        )

    contract.status = ContractStatus.active
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="contract_activated",
            user_id=current_user.id,
            details={"from_status": "draft", "to_status": "active"},
        )
    )

    # Deliberately no Notification row here — the auto-draft hook in
    # pipeline.py already fired a `contract_activated` notification for this
    # contract on the same day when the candidate moved to `hired`. The
    # per-day dedup index (user_id, notification_type, related_entity_id,
    # day) would collide. Activation is a routine follow-up to a draft
    # that admins were already alerted about, so re-notifying adds no
    # value. The Activity row above provides the audit trail.

    await db.flush()
    await db.refresh(contract)
    return _to_detail(contract)


# ── Editable draft (migracja 0058) ───────────────────────────────────────────


async def _load_contract_with_relations(
    db: AsyncSession, contract_id: int
) -> Contract:
    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
        )
    )
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


async def _list_templates_for_contract_type(
    db: AsyncSession, contract_type_value: str
) -> list[ContractTemplate]:
    res = await db.execute(
        select(ContractTemplate)
        .where(ContractTemplate.contract_type == contract_type_value)
        .order_by(ContractTemplate.is_default.desc(), ContractTemplate.name)
    )
    return list(res.scalars().all())


def _render_draft_body(template: ContractTemplate, contract: Contract) -> str:
    """Render Jinja template against contract context. Returns raw HTML body
    (no <html> wrap — that's added by the printable endpoint)."""
    try:
        return _jinja_env.from_string(template.content_jinja).render(
            **_contract_vars(contract)
        )
    except TemplateError as exc:
        raise HTTPException(
            status_code=422, detail=f"Template render error: {exc}"
        )


def _wrap_printable(body_html: str, contract_id: int, title: str) -> str:
    """Wrap raw body HTML with print-friendly stylesheet + auto-print script."""
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{title} — kontrakt #{contract_id}</title>"
        "<style>"
        "body{font-family:'Helvetica',Arial,sans-serif;max-width:780px;"
        "margin:40px auto;line-height:1.55;color:#222;padding:0 20px;}"
        "h1,h2,h3{color:#111}"
        "table{border-collapse:collapse;width:100%;margin:1em 0}"
        "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}"
        "@media print{body{margin:0;padding:0}}"
        "</style>"
        "<script>window.addEventListener('load',()=>setTimeout("
        "()=>window.print(),300));</script>"
        "</head><body>"
        f"{body_html}"
        "</body></html>"
    )


def _draft_response(
    contract: Contract,
    available_templates: list[ContractTemplate],
    updated_by_name: Optional[str],
    rendered_from_default: bool,
) -> ContractDraftResponse:
    return ContractDraftResponse(
        contract_id=contract.id,
        content_html=contract.draft_content_html,
        template_id=contract.draft_template_id,
        updated_at=contract.draft_updated_at,
        updated_by=contract.draft_updated_by,
        updated_by_name=updated_by_name,
        available_templates=[
            ContractTemplateBrief.model_validate(t) for t in available_templates
        ],
        rendered_from_default=rendered_from_default,
    )


@router.get("/{contract_id}/draft", response_model=ContractDraftResponse)
async def get_contract_draft(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return editable draft state for a contract.

    First call (`draft_content_html IS NULL`) lazy-renders the default
    template for this `contract_type` and persists it. If no default exists,
    the response carries an empty body and the FE prompts for template
    selection from `available_templates`.
    """
    contract = await _load_contract_with_relations(db, contract_id)
    contract_type_value = (
        contract.contract_type.value
        if hasattr(contract.contract_type, "value")
        else str(contract.contract_type)
    )
    available = await _list_templates_for_contract_type(db, contract_type_value)

    rendered_from_default = False
    if contract.draft_content_html is None:
        default = next((t for t in available if t.is_default), None)
        if default is not None:
            contract.draft_content_html = _render_draft_body(default, contract)
            contract.draft_template_id = default.id
            contract.draft_updated_at = datetime.now(timezone.utc)
            contract.draft_updated_by = current_user.id
            rendered_from_default = True
            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=contract.id,
                    action="draft_initialized",
                    user_id=current_user.id,
                    details={"template_id": default.id, "template_name": default.name},
                )
            )
            await db.flush()

    updated_by_name: Optional[str] = None
    if contract.draft_updated_by:
        updated_by_name = await db.scalar(
            select(User.email).where(User.id == contract.draft_updated_by)
        )

    return _draft_response(
        contract, available, updated_by_name, rendered_from_default
    )


@router.patch("/{contract_id}/draft", response_model=ContractDraftResponse)
async def update_contract_draft(
    contract_id: int,
    payload: ContractDraftUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Update the draft body. Two mutually exclusive modes:

    - `template_id` only → re-render that template (overwrites content).
    - `content_html` only → save edited body verbatim.
    """
    if payload.template_id is None and payload.content_html is None:
        raise HTTPException(
            status_code=422,
            detail="Provide either `template_id` (re-render) or `content_html` (save).",
        )
    if payload.template_id is not None and payload.content_html is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Choose one: `template_id` re-renders and discards manual edits, "
                "`content_html` saves manual edits."
            ),
        )

    contract = await _load_contract_with_relations(db, contract_id)

    if payload.template_id is not None:
        tpl = await db.scalar(
            select(ContractTemplate).where(ContractTemplate.id == payload.template_id)
        )
        if not tpl:
            raise HTTPException(status_code=404, detail="Template not found")
        contract.draft_content_html = _render_draft_body(tpl, contract)
        contract.draft_template_id = tpl.id
        action = "draft_template_changed"
        details = {"template_id": tpl.id, "template_name": tpl.name}
    else:
        contract.draft_content_html = payload.content_html
        action = "draft_edited"
        details = {"length": len(payload.content_html or "")}

    contract.draft_updated_at = datetime.now(timezone.utc)
    contract.draft_updated_by = current_user.id

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action=action,
            user_id=current_user.id,
            details=details,
        )
    )
    await db.flush()

    contract_type_value = (
        contract.contract_type.value
        if hasattr(contract.contract_type, "value")
        else str(contract.contract_type)
    )
    available = await _list_templates_for_contract_type(db, contract_type_value)
    updated_by_name = await db.scalar(
        select(User.email).where(User.id == current_user.id)
    )
    return _draft_response(contract, available, updated_by_name, False)


@router.get("/{contract_id}/draft/render-pdf", response_class=HTMLResponse)
async def render_draft_for_print(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return the draft body wrapped in a printable HTML page.

    The browser opens this URL in a new tab; an embedded `window.print()`
    fires the OS print dialog where the user picks "Save as PDF". No
    server-side PDF dependency required.
    """
    contract = await _load_contract_with_relations(db, contract_id)
    body = contract.draft_content_html
    if not body:
        raise HTTPException(
            status_code=404,
            detail="Draft is empty — open the editor and pick a template first.",
        )
    title = (
        contract.candidate
        and f"{contract.candidate.name} {contract.candidate.lastname}"
    ) or "Umowa"
    return HTMLResponse(content=_wrap_printable(body, contract.id, title))


@router.post(
    "/{contract_id}/draft/finalize",
    response_model=ContractDraftFinalizeResponse,
)
async def finalize_contract_draft(
    contract_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Snapshot the draft as a `ContractDocument(doc_type=contract)` and
    flip the contract from `draft` to `active`.

    Reuses the same field-validation rule as `/activate` so the UI can
    show a consistent missing-field list.
    """
    contract = await _load_contract_with_relations(db, contract_id)

    if contract.status != ContractStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contract is already {contract.status.value}, cannot finalize draft",
        )

    if not contract.draft_content_html:
        raise HTTPException(
            status_code=422,
            detail="Draft is empty — generate or paste content before finalizing.",
        )

    missing = validate_ready_for_activation(contract)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Missing required fields", "missing": missing},
        )

    # Persist the rendered draft as an immutable HTML snapshot.
    candidate_label = (
        f"{contract.candidate.name}_{contract.candidate.lastname}"
        if contract.candidate
        else f"contract_{contract.id}"
    )
    filename = (
        f"umowa_{candidate_label}_{contract.start_date.isoformat()}.html"
    ).replace(" ", "_")
    snapshot_html = _wrap_printable(
        contract.draft_content_html, contract.id, "Umowa (snapshot draftu)"
    )
    blob = snapshot_html.encode("utf-8")
    relative_path, size = storage_service.save_contract_document(
        contract_id=contract.id,
        upload_filename=filename,
        source=BytesIO(blob),
    )

    doc = ContractDocument(
        contract_id=contract.id,
        filename=filename,
        file_path=relative_path,
        content_type="text/html",
        size_bytes=size,
        doc_type=ContractDocumentType.contract,
        uploaded_by=current_user.id,
    )
    db.add(doc)

    contract.status = ContractStatus.active
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="draft_finalized",
            user_id=current_user.id,
            details={
                "from_status": "draft",
                "to_status": "active",
                "snapshot_filename": filename,
            },
        )
    )
    await db.flush()
    await db.refresh(doc)

    return ContractDraftFinalizeResponse(
        contract_id=contract.id,
        status=contract.status,
        document_id=doc.id,
        document_filename=doc.filename,
    )


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    contract_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Contract).where(Contract.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="deleted",
            user_id=current_user.id,
        )
    )
    await db.delete(contract)


# ── Documents (Phase 9 A4) ────────────────────────────────────────────────────


async def _assert_contract(db: AsyncSession, contract_id: int) -> None:
    exists = await db.execute(select(Contract.id).where(Contract.id == contract_id))
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Contract not found")


async def _document_to_response(
    db: AsyncSession, doc: ContractDocument
) -> ContractDocumentResponse:
    user_email: Optional[str] = None
    if doc.uploaded_by:
        user_email = await db.scalar(
            select(User.email).where(User.id == doc.uploaded_by)
        )
    return ContractDocumentResponse(
        id=doc.id,
        contract_id=doc.contract_id,
        filename=doc.filename,
        doc_type=doc.doc_type,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        expiry_date=doc.expiry_date,
        uploaded_by=doc.uploaded_by,
        uploaded_by_email=user_email,
        created_at=doc.created_at,
    )


@router.get(
    "/{contract_id}/documents",
    response_model=List[ContractDocumentResponse],
)
async def list_contract_documents(
    contract_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _assert_contract(db, contract_id)
    result = await db.execute(
        select(ContractDocument)
        .where(ContractDocument.contract_id == contract_id)
        .order_by(ContractDocument.created_at.desc())
    )
    docs = list(result.scalars().all())
    return [await _document_to_response(db, d) for d in docs]


@router.post(
    "/{contract_id}/documents",
    response_model=ContractDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_contract_document(
    contract_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    doc_type: ContractDocumentType = Form(ContractDocumentType.other),
    expiry_date: Optional[date] = Form(None),
):
    await _assert_contract(db, contract_id)

    # Rudimentary size guard — FastAPI's UploadFile is a SpooledTemporaryFile,
    # so we only know the true size after reading. We read via storage_service
    # which returns the byte count and lets us reject oversized files.
    relative_path, size = storage_service.save_contract_document(
        contract_id=contract_id,
        upload_filename=file.filename or "file",
        source=file.file,
    )
    if size > MAX_UPLOAD_BYTES:
        storage_service.delete_contract_document(relative_path)
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    doc = ContractDocument(
        contract_id=contract_id,
        filename=file.filename or "file",
        file_path=relative_path,
        content_type=file.content_type,
        size_bytes=size,
        doc_type=doc_type,
        expiry_date=expiry_date,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="document_uploaded",
            user_id=current_user.id,
            details={
                "filename": doc.filename,
                "doc_type": doc_type.value
                if hasattr(doc_type, "value")
                else str(doc_type),
                "size_bytes": size,
            },
        )
    )
    await db.flush()
    await db.refresh(doc)
    return await _document_to_response(db, doc)


@router.patch(
    "/{contract_id}/documents/{document_id}",
    response_model=ContractDocumentResponse,
)
async def update_contract_document(
    contract_id: int,
    document_id: int,
    data: ContractDocumentUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id)
    result = await db.execute(
        select(ContractDocument).where(
            ContractDocument.id == document_id,
            ContractDocument.contract_id == contract_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(doc, k, v)
    await db.flush()
    await db.refresh(doc)
    return await _document_to_response(db, doc)


@router.get("/{contract_id}/documents/{document_id}/download")
async def download_contract_document(
    contract_id: int,
    document_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id)
    result = await db.execute(
        select(ContractDocument).where(
            ContractDocument.id == document_id,
            ContractDocument.contract_id == contract_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        abs_path = storage_service.get_contract_document_path(doc.file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="File no longer on storage")
    return FileResponse(
        path=str(abs_path),
        filename=doc.filename,
        media_type=doc.content_type or "application/octet-stream",
    )


@router.delete(
    "/{contract_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract_document(
    contract_id: int,
    document_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id)
    result = await db.execute(
        select(ContractDocument).where(
            ContractDocument.id == document_id,
            ContractDocument.contract_id == contract_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    storage_service.delete_contract_document(doc.file_path)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="document_deleted",
            user_id=current_user.id,
            details={"filename": doc.filename},
        )
    )
    await db.delete(doc)


# ── Amendments (Phase 9 B3) ──────────────────────────────────────────────────


async def _amendment_to_response(
    db: AsyncSession, amendment: ContractAmendment
) -> ContractAmendmentResponse:
    user_email: Optional[str] = None
    if amendment.created_by:
        user_email = await db.scalar(
            select(User.email).where(User.id == amendment.created_by)
        )
    return ContractAmendmentResponse(
        id=amendment.id,
        contract_id=amendment.contract_id,
        amendment_type=amendment.amendment_type,
        old_values=amendment.old_values,
        new_values=amendment.new_values,
        effective_date=amendment.effective_date,
        reason=amendment.reason,
        document_id=amendment.document_id,
        created_by=amendment.created_by,
        created_by_email=user_email,
        created_at=amendment.created_at,
    )


@router.get(
    "/{contract_id}/amendments",
    response_model=List[ContractAmendmentResponse],
)
async def list_contract_amendments(
    contract_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _assert_contract(db, contract_id)
    result = await db.execute(
        select(ContractAmendment)
        .where(ContractAmendment.contract_id == contract_id)
        .order_by(ContractAmendment.created_at.desc())
    )
    amendments = list(result.scalars().all())
    return [await _amendment_to_response(db, a) for a in amendments]


@router.post(
    "/{contract_id}/amendments",
    response_model=ContractAmendmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract_amendment(
    contract_id: int,
    data: ContractAmendmentCreate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    contract_res = await db.execute(select(Contract).where(Contract.id == contract_id))
    contract = contract_res.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Snapshot only the fields that might change, for audit.
    old_values: dict = {
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "rate_candidate": contract.rate_candidate,
        "rate_client": contract.rate_client,
        "rate_unit": contract.rate_unit.value
        if hasattr(contract.rate_unit, "value")
        else str(contract.rate_unit),
        "billing_hours_per_month": contract.billing_hours_per_month,
        "project_name": contract.project_name,
        "team_name": contract.team_name,
        "status": contract.status.value
        if hasattr(contract.status, "value")
        else str(contract.status),
    }
    new_values: dict = {}

    # Apply changes per amendment_type
    if data.amendment_type == ContractAmendmentType.extension:
        if data.new_end_date is None:
            raise HTTPException(
                status_code=422,
                detail="new_end_date is required for extension amendment",
            )
        contract.end_date = data.new_end_date
        # If status was 'ending' or 'ended', flip back to active after extension.
        if contract.status in (ContractStatus.ending, ContractStatus.ended):
            contract.status = ContractStatus.active
        new_values["end_date"] = data.new_end_date.isoformat()
        new_values["status"] = contract.status.value

    elif data.amendment_type == ContractAmendmentType.rate_change:
        if data.new_rate_candidate is not None:
            contract.rate_candidate = data.new_rate_candidate
            new_values["rate_candidate"] = data.new_rate_candidate
        if data.new_rate_client is not None:
            contract.rate_client = data.new_rate_client
            new_values["rate_client"] = data.new_rate_client
        if data.new_rate_unit is not None:
            contract.rate_unit = data.new_rate_unit  # type: ignore[assignment]
            new_values["rate_unit"] = data.new_rate_unit
        if data.new_billing_hours_per_month is not None:
            contract.billing_hours_per_month = data.new_billing_hours_per_month
            new_values["billing_hours_per_month"] = data.new_billing_hours_per_month
        if not new_values:
            raise HTTPException(
                status_code=422,
                detail="At least one rate field must change for rate_change amendment",
            )
        contract.margin = contract.calculate_margin()

    elif data.amendment_type == ContractAmendmentType.scope_change:
        if data.new_project_name is not None:
            contract.project_name = data.new_project_name
            new_values["project_name"] = data.new_project_name
        if data.new_team_name is not None:
            contract.team_name = data.new_team_name
            new_values["team_name"] = data.new_team_name
        if not new_values:
            raise HTTPException(
                status_code=422,
                detail="scope_change requires new_project_name or new_team_name",
            )

    elif data.amendment_type == ContractAmendmentType.early_termination:
        end = data.new_end_date or data.effective_date
        contract.end_date = end
        contract.status = ContractStatus.ended
        new_values["end_date"] = end.isoformat()
        new_values["status"] = contract.status.value

    amendment = ContractAmendment(
        contract_id=contract_id,
        amendment_type=data.amendment_type,
        old_values=old_values,
        new_values=new_values,
        effective_date=data.effective_date,
        reason=data.reason,
        document_id=data.document_id,
        created_by=current_user.id,
    )
    db.add(amendment)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action=f"amendment_{data.amendment_type.value}",
            user_id=current_user.id,
            details={
                "old": old_values,
                "new": new_values,
                "effective_date": data.effective_date.isoformat(),
            },
        )
    )
    await db.flush()
    await db.refresh(amendment)
    return await _amendment_to_response(db, amendment)


# ── Onboarding checklist (Phase 9 B6) ────────────────────────────────────────


@router.get(
    "/{contract_id}/onboarding",
    response_model=List[OnboardingItemResponse],
)
async def list_onboarding_items(
    contract_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _assert_contract(db, contract_id)
    res = await db.execute(
        select(ContractOnboardingItem)
        .where(ContractOnboardingItem.contract_id == contract_id)
        .order_by(ContractOnboardingItem.order, ContractOnboardingItem.id)
    )
    return list(res.scalars().all())


@router.post(
    "/{contract_id}/onboarding",
    response_model=OnboardingItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_onboarding_item(
    contract_id: int,
    data: OnboardingItemCreate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id)
    item = ContractOnboardingItem(contract_id=contract_id, **data.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.patch(
    "/{contract_id}/onboarding/{item_id}",
    response_model=OnboardingItemResponse,
)
async def update_onboarding_item(
    contract_id: int,
    item_id: int,
    data: OnboardingItemUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id)
    item = await db.scalar(
        select(ContractOnboardingItem).where(
            ContractOnboardingItem.id == item_id,
            ContractOnboardingItem.contract_id == contract_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding item not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    await db.flush()
    await db.refresh(item)
    return item


@router.delete(
    "/{contract_id}/onboarding/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_onboarding_item(
    contract_id: int,
    item_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id)
    item = await db.scalar(
        select(ContractOnboardingItem).where(
            ContractOnboardingItem.id == item_id,
            ContractOnboardingItem.contract_id == contract_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding item not found")
    await db.delete(item)


# ── Equipment (Kontrakty expansion: ewidencja sprzętu) ──────────────────────


@router.get(
    "/{contract_id}/equipment",
    response_model=List[ContractEquipmentResponse],
)
async def list_contract_equipment(
    contract_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _assert_contract(db, contract_id)
    result = await db.execute(
        select(ContractEquipment)
        .where(ContractEquipment.contract_id == contract_id)
        .order_by(ContractEquipment.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/{contract_id}/equipment",
    response_model=ContractEquipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract_equipment(
    contract_id: int,
    data: ContractEquipmentCreate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    contract_res = await db.execute(select(Contract).where(Contract.id == contract_id))
    contract = contract_res.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    payload = data.model_dump()
    # If the caller didn't supply a return_due_date, default to the contract's
    # end_date so the alert task picks it up automatically.
    if payload.get("return_due_date") is None and contract.end_date is not None:
        payload["return_due_date"] = contract.end_date

    item = ContractEquipment(contract_id=contract_id, **payload)
    db.add(item)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="equipment_added",
            user_id=current_user.id,
            details={
                "item_type": item.item_type.value
                if hasattr(item.item_type, "value")
                else str(item.item_type),
                "serial_number": item.serial_number,
                "owner": item.owner.value
                if hasattr(item.owner, "value")
                else str(item.owner),
            },
        )
    )
    await db.flush()
    await db.refresh(item)
    return item


@router.patch(
    "/{contract_id}/equipment/{equipment_id}",
    response_model=ContractEquipmentResponse,
)
async def update_contract_equipment(
    contract_id: int,
    equipment_id: int,
    data: ContractEquipmentUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id)
    item = await db.scalar(
        select(ContractEquipment).where(
            ContractEquipment.id == equipment_id,
            ContractEquipment.contract_id == contract_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Equipment item not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(item, k, v)
    # Guard: returned_date requires return_status=returned (mark as returned).
    if item.returned_date is not None and item.return_status != EquipmentReturnStatus.returned:
        item.return_status = EquipmentReturnStatus.returned
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="equipment_updated",
            user_id=current_user.id,
            details={k: (v.isoformat() if hasattr(v, "isoformat") else v)
                     for k, v in updates.items()},
        )
    )
    await db.flush()
    await db.refresh(item)
    return item


@router.delete(
    "/{contract_id}/equipment/{equipment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract_equipment(
    contract_id: int,
    equipment_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id)
    item = await db.scalar(
        select(ContractEquipment).where(
            ContractEquipment.id == equipment_id,
            ContractEquipment.contract_id == contract_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Equipment item not found")
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="equipment_removed",
            user_id=current_user.id,
            details={"equipment_id": equipment_id},
        )
    )
    await db.delete(item)


# ── Termination (dedicated endpoint with structured reason) ──────────────────


@router.post(
    "/{contract_id}/terminate",
    response_model=ContractDetailResponse,
)
async def terminate_contract(
    contract_id: int,
    data: ContractTerminateRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Mark the contract as ended with a structured reason and optional lessons.

    If the effective date is earlier than the current end_date, an
    `early_termination` amendment is also recorded for audit.
    """
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    when = data.terminated_at or date.today()
    previous_end_date = contract.end_date

    contract.status = ContractStatus.ended
    contract.terminated_at = when
    contract.termination_reason = data.termination_reason
    contract.termination_lessons = data.termination_lessons
    # Keep end_date coherent — never let it lag the termination date.
    if contract.end_date is None or contract.end_date > when:
        contract.end_date = when

    # Audit amendment if the contract was cut short.
    if previous_end_date is not None and when < previous_end_date:
        db.add(
            ContractAmendment(
                contract_id=contract_id,
                amendment_type=ContractAmendmentType.early_termination,
                old_values={
                    "end_date": previous_end_date.isoformat(),
                    "status": "active",
                },
                new_values={"end_date": when.isoformat(), "status": "ended"},
                effective_date=when,
                reason=(
                    f"{data.termination_reason.value}: {data.termination_lessons}"
                    if data.termination_lessons
                    else data.termination_reason.value
                ),
                created_by=current_user.id,
            )
        )

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="terminated",
            user_id=current_user.id,
            details={
                "termination_reason": data.termination_reason.value,
                "terminated_at": when.isoformat(),
                "early": previous_end_date is not None and when < previous_end_date,
            },
        )
    )
    await db.flush()
    await db.refresh(contract)
    return _to_detail(contract)


# ── Notes + Calls timeline per contract ──────────────────────────────────────


@router.get(
    "/{contract_id}/notes",
    response_model=List[ContractTimelineItem],
)
async def contract_timeline(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
):
    """Chronological merge of notes + calls attached to this contract."""
    await _assert_contract(db, contract_id)

    notes_res = await db.execute(
        select(Note, User.email)
        .outerjoin(User, Note.author_id == User.id)
        .where(Note.contract_id == contract_id)
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    calls_res = await db.execute(
        select(Call, User.email)
        .outerjoin(User, Call.user_id == User.id)
        .where(Call.contract_id == contract_id)
        .order_by(Call.created_at.desc())
        .limit(limit)
    )

    items: list[ContractTimelineItem] = []

    for note, author_email in notes_res.all():
        items.append(
            ContractTimelineItem(
                id=note.id,
                kind="note",
                at=note.created_at,
                content=note.content,
                sub_type=note.note_type.value
                if hasattr(note.note_type, "value")
                else str(note.note_type),
                author_id=note.author_id,
                author_name=author_email,
            )
        )

    for call, author_email in calls_res.all():
        items.append(
            ContractTimelineItem(
                id=call.id,
                kind="call",
                at=call.created_at,
                summary=call.summary,
                content=call.transcript,
                sub_type=call.direction.value
                if hasattr(call.direction, "value")
                else str(call.direction),
                status=call.status.value
                if hasattr(call.status, "value")
                else str(call.status),
                author_id=call.user_id,
                author_name=author_email,
                duration_seconds=call.duration_seconds,
            )
        )

    items.sort(key=lambda i: i.at, reverse=True)
    return items[:limit]


# ── Benchmark comparison (rate vs internal avg vs market) ────────────────────


def _monthly_equivalent(rate: Optional[int], unit: RateUnit, hours: int) -> Optional[int]:
    if rate is None:
        return None
    if unit == RateUnit.monthly:
        return rate
    if unit == RateUnit.daily:
        return rate * 22
    if unit == RateUnit.hourly:
        return rate * (hours or 160)
    return rate


async def _resolve_role_for_contract(db: AsyncSession, contract: Contract) -> Optional[str]:
    """Best-effort role extraction: job.title → candidate.competence_category."""
    if contract.job_id:
        title = await db.scalar(select(Job.title).where(Job.id == contract.job_id))
        if title:
            return title
    cc = await db.scalar(
        select(Candidate.competence_category).where(Candidate.id == contract.candidate_id)
    )
    return cc


@router.get(
    "/{contract_id}/benchmark",
    response_model=ContractBenchmarkComparison,
)
async def contract_benchmark(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(selectinload(Contract.candidate))
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    role = await _resolve_role_for_contract(db, contract)
    contract_rate_monthly = _monthly_equivalent(
        contract.rate_client, contract.rate_unit, contract.billing_hours_per_month
    )

    # Internal average: other active contracts for the same role.
    internal_avg_monthly: Optional[int] = None
    internal_median_monthly: Optional[int] = None
    internal_sample_size = 0
    if role:
        peer_q = (
            select(Contract, Job.title, Candidate.competence_category)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Job, Job.id == Contract.job_id)
            .where(
                Contract.id != contract_id,
                Contract.status == ContractStatus.active,
                Contract.rate_client.isnot(None),
                or_(Job.title == role, Candidate.competence_category == role),
            )
        )
        rows = (await db.execute(peer_q)).all()
        monthly_values: list[int] = []
        for peer, _, _ in rows:
            peer_monthly = _monthly_equivalent(
                peer.rate_client, peer.rate_unit, peer.billing_hours_per_month
            )
            if peer_monthly is not None:
                monthly_values.append(peer_monthly)
        if monthly_values:
            internal_sample_size = len(monthly_values)
            internal_avg_monthly = int(sum(monthly_values) / internal_sample_size)
            sorted_v = sorted(monthly_values)
            mid = internal_sample_size // 2
            internal_median_monthly = (
                sorted_v[mid]
                if internal_sample_size % 2 == 1
                else (sorted_v[mid - 1] + sorted_v[mid]) // 2
            )

    # Market benchmark: pick the most recent entry for the role in same currency.
    market_row = None
    if role:
        market_q = (
            select(RateBenchmark)
            .where(
                RateBenchmark.role.ilike(role),
                RateBenchmark.currency == contract.currency,
            )
            .order_by(RateBenchmark.source_date.desc())
            .limit(1)
        )
        market_row = (await db.execute(market_q)).scalar_one_or_none()

    market_min_monthly: Optional[int] = None
    market_median_monthly: Optional[int] = None
    market_max_monthly: Optional[int] = None
    market_source = None
    market_source_date = None
    if market_row is not None:
        market_min_monthly = _monthly_equivalent(
            market_row.market_min, market_row.rate_unit, contract.billing_hours_per_month
        )
        market_median_monthly = _monthly_equivalent(
            market_row.market_median,
            market_row.rate_unit,
            contract.billing_hours_per_month,
        )
        market_max_monthly = _monthly_equivalent(
            market_row.market_max, market_row.rate_unit, contract.billing_hours_per_month
        )
        market_source = market_row.source
        market_source_date = market_row.source_date

    return ContractBenchmarkComparison(
        contract_rate_monthly=contract_rate_monthly,
        internal_avg_monthly=internal_avg_monthly,
        internal_median_monthly=internal_median_monthly,
        internal_sample_size=internal_sample_size,
        market_min=market_min_monthly,
        market_median=market_median_monthly,
        market_max=market_max_monthly,
        market_source=market_source,
        market_source_date=market_source_date,
        role_used=role,
        currency=contract.currency,
    )
