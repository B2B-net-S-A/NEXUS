from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.client import Client
from app.api.deps import CurrentUser

router = APIRouter()


class ClientKnowledgeCreate(BaseModel):
    category: KnowledgeCategory
    content: str
    source: Optional[str] = None


class ClientKnowledgeResponse(BaseModel):
    id: int
    client_id: int
    category: KnowledgeCategory
    content: str
    added_by: Optional[int]
    source: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get(
    "/clients/{client_id}/knowledge", response_model=list[ClientKnowledgeResponse]
)
async def list_client_knowledge(
    client_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    category: Optional[KnowledgeCategory] = None,
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")

    query = select(ClientKnowledge).where(ClientKnowledge.client_id == client_id)
    if category:
        query = query.where(ClientKnowledge.category == category)
    query = query.order_by(ClientKnowledge.category, ClientKnowledge.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


@router.post(
    "/clients/{client_id}/knowledge",
    response_model=ClientKnowledgeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client_knowledge(
    client_id: int,
    data: ClientKnowledgeCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")

    entry = ClientKnowledge(
        client_id=client_id,
        category=data.category,
        content=data.content,
        source=data.source,
        added_by=current_user.id,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


@router.delete(
    "/client-knowledge/{knowledge_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_client_knowledge(
    knowledge_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientKnowledge).where(ClientKnowledge.id == knowledge_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    await db.delete(entry)
