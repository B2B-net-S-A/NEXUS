from datetime import date, timedelta
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
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.activity import Activity
from app.models.contract import Contract, ContractStatus
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.rate_history import RateHistory
from app.models.user import User
from app.schemas.contract import (
    ContractActivityEntry,
    ContractCreate,
    ContractDetailResponse,
    ContractList,
    ContractRateHistoryEntry,
    ContractResponse,
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
from app.services import storage_service
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
        "rate_candidate": contract.rate_candidate,
        "rate_client": contract.rate_client,
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
    status: Optional[ContractStatus] = None,
    client_id: Optional[int] = None,
):
    query = select(Contract)
    if status:
        query = query.where(Contract.status == status)
    if client_id:
        query = query.where(Contract.client_id == client_id)
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
