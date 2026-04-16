from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.client import Client
from app.models.activity import Activity
from app.schemas.client import ClientCreate, ClientList, ClientResponse, ClientUpdate
from app.api.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ClientList)
async def list_clients(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = None,
):
    query = select(Client)
    if q:
        query = query.where(Client.name.ilike(f"%{q}%"))
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return ClientList(
        items=list(result.scalars().all()), total=total, page=page, page_size=page_size
    )


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    data: ClientCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    client = Client(**data.model_dump())
    db.add(client)
    await db.flush()
    db.add(
        Activity(
            entity_type="client",
            entity_id=client.id,
            action="created",
            user_id=current_user.id,
        )
    )
    await db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    data: ClientUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(client, k, v)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="updated",
            user_id=current_user.id,
            details=updates,
        )
    )
    await db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="deleted",
            user_id=current_user.id,
        )
    )
    await db.delete(client)
