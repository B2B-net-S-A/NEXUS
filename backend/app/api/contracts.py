from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.activity import Activity
from app.models.contract import Contract, ContractStatus
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
from app.api.deps import CurrentUser, TacPlus

router = APIRouter()

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
        "margin": contract.margin,
        "contract_type": contract.contract_type,
        "status": contract.status,
        "documents": contract.documents,
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
