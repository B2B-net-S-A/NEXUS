from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.contract import Contract, ContractStatus
from app.models.activity import Activity
from app.schemas.contract import (
    ContractCreate,
    ContractList,
    ContractResponse,
    ContractUpdate,
)
from app.api.deps import CurrentUser, TacPlus

router = APIRouter()

EXPIRY_WARNING_DAYS = 30


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
    # margin auto-calculated via SQLAlchemy event
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


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Contract).where(Contract.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@router.patch("/{contract_id}", response_model=ContractResponse)
async def update_contract(
    contract_id: int,
    data: ContractUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Contract).where(Contract.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(contract, k, v)
    # Recalculate margin if rates changed
    contract.margin = contract.calculate_margin()
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="updated",
            user_id=current_user.id,
            details=updates,
        )
    )
    await db.refresh(contract)
    return contract


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
