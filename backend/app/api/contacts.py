from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.models.contact import Contact, RelationshipStrength
from app.models.client import Client
from app.api.deps import CurrentUser

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class ContactCreate(BaseModel):
    client_id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    department: Optional[str] = None
    is_decision_maker: bool = False
    notes: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    # Key relationship fields (2026-05-11)
    is_key_relationship: bool = False
    relationship_strength: Optional[RelationshipStrength] = None
    relationship_notes: Optional[str] = None
    key_relationship_owner_id: Optional[int] = None
    last_personal_touchpoint_at: Optional[datetime] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    department: Optional[str] = None
    is_decision_maker: Optional[bool] = None
    notes: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    # Key relationship fields
    is_key_relationship: Optional[bool] = None
    relationship_strength: Optional[RelationshipStrength] = None
    relationship_notes: Optional[str] = None
    key_relationship_owner_id: Optional[int] = None
    last_personal_touchpoint_at: Optional[datetime] = None


class ContactResponse(BaseModel):
    id: int
    client_id: int
    name: str
    email: Optional[str]
    phone: Optional[str]
    position: Optional[str]
    department: Optional[str]
    is_decision_maker: bool
    notes: Optional[str]
    last_contacted_at: Optional[datetime]
    created_at: datetime
    # Key relationship fields
    is_key_relationship: bool
    relationship_strength: Optional[RelationshipStrength]
    relationship_notes: Optional[str]
    key_relationship_owner_id: Optional[int]
    last_personal_touchpoint_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ContactWithClientResponse(BaseModel):
    id: int
    client_id: int
    client_name: Optional[str]
    name: str
    email: Optional[str]
    phone: Optional[str]
    position: Optional[str]
    department: Optional[str]
    is_decision_maker: bool
    notes: Optional[str]
    last_contacted_at: Optional[datetime]
    created_at: datetime
    # Key relationship fields
    is_key_relationship: bool
    relationship_strength: Optional[RelationshipStrength]
    relationship_notes: Optional[str]
    key_relationship_owner_id: Optional[int]
    last_personal_touchpoint_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/contacts", response_model=list[ContactWithClientResponse])
async def list_all_contacts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = Query(None, alias="search"),
):
    """Return all contacts across all clients with optional name/email search."""
    query = (
        select(Contact, Client.name.label("client_name"))
        .join(Client, Contact.client_id == Client.id)
        .order_by(Contact.is_decision_maker.desc(), Contact.name)
    )
    if search:
        query = query.where(
            or_(
                Contact.name.ilike(f"%{search}%"),
                Contact.email.ilike(f"%{search}%"),
            )
        )
    result = await db.execute(query)
    rows = result.all()
    contacts_out = []
    for contact, client_name in rows:
        contacts_out.append(
            ContactWithClientResponse(
                id=contact.id,
                client_id=contact.client_id,
                client_name=client_name,
                name=contact.name,
                email=contact.email,
                phone=contact.phone,
                position=contact.position,
                department=contact.department,
                is_decision_maker=contact.is_decision_maker,
                notes=contact.notes,
                last_contacted_at=contact.last_contacted_at,
                created_at=contact.created_at,
                # Key relationship fields (2026-05-11, migracja 0096)
                is_key_relationship=contact.is_key_relationship,
                relationship_strength=contact.relationship_strength,
                relationship_notes=contact.relationship_notes,
                key_relationship_owner_id=contact.key_relationship_owner_id,
                last_personal_touchpoint_at=contact.last_personal_touchpoint_at,
            )
        )
    return contacts_out


@router.get("/clients/{client_id}/contacts", response_model=list[ContactResponse])
async def list_client_contacts(
    client_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")

    result = await db.execute(
        select(Contact)
        .where(Contact.client_id == client_id)
        .order_by(Contact.is_decision_maker.desc(), Contact.name)
    )
    return list(result.scalars().all())


@router.post(
    "/contacts", response_model=ContactResponse, status_code=status.HTTP_201_CREATED
)
async def create_contact(
    data: ContactCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Client).where(Client.id == data.client_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")

    contact = Contact(**data.model_dump())
    db.add(contact)
    await db.flush()
    await db.refresh(contact)
    return contact


@router.put("/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int,
    data: ContactUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(contact, k, v)

    await db.flush()
    await db.refresh(contact)
    return contact


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    await db.delete(contact)
