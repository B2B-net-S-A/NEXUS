"""Wiedza operacyjna o kliencie (Moduł 1, PR 1/7 — containment RBAC).

Wpisy konsumują m.in. ai_writer, prep_kit i question_suggestions — zapis
kontroluje więc kontekst podawany AI. Wcześniej create/delete działały na
samym ``CurrentUser``; teraz:

- odczyt: admin/Finance/TCM oraz Delivery Lead globalnie;
- create/delete: admin lub Delivery Lead globalnie;
- HoR/TAC/recruiter/sourcer są odcięci przez bramkę sekcji Delivery;
- każda mutacja zostawia audit event (kategoria, id — bez treści wpisu).
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.user import User
from app.api.deps import CurrentUser, get_current_user
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.services.client_access import (
    assert_client_exists,
    deny,
    record_client_audit,
    resolve_client_access,
)

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    category: Optional[KnowledgeCategory] = None,
):
    await assert_client_exists(db, client_id)
    access = await resolve_client_access(db, current_user, client_id)
    if not access.can_view_knowledge:
        raise deny("brak dostępu do wiedzy tego klienta")

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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_client_exists(db, client_id)
    access = await resolve_client_access(db, current_user, client_id)
    if not access.can_edit_knowledge:
        raise deny("dodawanie wiedzy klienta wymaga roli admin lub Delivery Lead")

    entry = ClientKnowledge(
        client_id=client_id,
        category=data.category,
        content=data.content,
        source=data.source,
        added_by=current_user.id,
    )
    db.add(entry)
    await db.flush()
    record_client_audit(
        db,
        client_id=client_id,
        actor_id=current_user.id,
        action="knowledge_created",
        details={"knowledge_id": entry.id, "category": data.category.value},
    )
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

    access = await resolve_client_access(db, current_user, entry.client_id)
    if not access.can_edit_knowledge:
        raise deny("usuwanie wiedzy klienta wymaga roli admin lub Delivery Lead")

    record_client_audit(
        db,
        client_id=entry.client_id,
        actor_id=current_user.id,
        action="knowledge_deleted",
        details={"knowledge_id": entry.id, "category": entry.category.value},
    )
    await db.delete(entry)
