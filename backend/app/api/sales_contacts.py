"""Sprzedaż → Kontakty: osoby po stronie firm (decydenci, kupcy) — nie kandydaci.

Prefiks ``/api/sales/contacts`` (wpięty w ``app/main.py``). Odczyt:
„Sprzedaż: podgląd”, zapis: „Sprzedaż: edycja”.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.models.sales import SalesCompany, SalesContact
from app.services.polish_ilike import polish_folded_ilike

router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiego kontaktu."


class ContactFields(BaseModel):
    company_id: Optional[int] = None
    first_name: Optional[str] = Field(default=None, max_length=120)
    last_name: Optional[str] = Field(default=None, max_length=120)
    title: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=60)
    mobile_phone: Optional[str] = Field(default=None, max_length=60)
    linkedin_url: Optional[str] = Field(default=None, max_length=500)
    seniority: Optional[str] = Field(default=None, max_length=40)
    department: Optional[str] = Field(default=None, max_length=120)
    is_executive: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=10_000)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        if not value:
            return None
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Adres e-mail wygląda na niepełny.")
        return value.lower()


class ContactCreate(ContactFields):
    full_name: Optional[str] = Field(default=None, max_length=255)


class ContactUpdate(ContactFields):
    full_name: Optional[str] = Field(default=None, max_length=255)


class ContactOut(BaseModel):
    id: int
    company_id: Optional[int]
    company_name: Optional[str]
    full_name: str
    first_name: Optional[str]
    last_name: Optional[str]
    title: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    mobile_phone: Optional[str]
    linkedin_url: Optional[str]
    seniority: Optional[str]
    department: Optional[str]
    is_executive: bool
    notes: Optional[str]
    source: Optional[str]
    archived_at: Optional[datetime]
    created_at: datetime


class ContactList(BaseModel):
    items: list[ContactOut]
    total: int


def _full_name(fields: dict[str, Any], current: Optional[SalesContact] = None) -> str:
    explicit = (fields.get("full_name") or "").strip()
    if explicit:
        return explicit
    first = fields.get("first_name", current.first_name if current else None) or ""
    last = fields.get("last_name", current.last_name if current else None) or ""
    return f"{first.strip()} {last.strip()}".strip()


def _out(contact: SalesContact, company_name: Optional[str]) -> ContactOut:
    return ContactOut(
        **{
            key: getattr(contact, key)
            for key in ContactOut.model_fields
            if key != "company_name"
        },
        company_name=company_name,
    )


async def _check_company(db: AsyncSession, company_id: Optional[int]) -> None:
    if company_id is not None and await db.get(SalesCompany, company_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nie ma takiej firmy w kartotece sprzedaży.",
        )


async def _load(db: AsyncSession, contact_id: int) -> ContactOut:
    row = (
        await db.execute(
            select(SalesContact, SalesCompany.name)
            .outerjoin(SalesCompany, SalesCompany.id == SalesContact.company_id)
            .where(SalesContact.id == contact_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return _out(row[0], row[1])


def _apply(contact: SalesContact, fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        if key == "full_name":
            continue
        if isinstance(value, str):
            value = value.strip() or None
        setattr(contact, key, value)


@router.get("", response_model=ContactList)
async def list_contacts(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    company_id: Optional[int] = None,
    q: Optional[str] = Query(default=None, max_length=200),
    executives: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ContactList:
    query = (
        select(SalesContact, SalesCompany.name)
        .outerjoin(SalesCompany, SalesCompany.id == SalesContact.company_id)
        .where(SalesContact.archived_at.is_(None))
    )
    if company_id is not None:
        query = query.where(SalesContact.company_id == company_id)
    if executives:
        query = query.where(SalesContact.is_executive.is_(True))
    text = (q or "").strip()
    if text:
        query = query.where(
            or_(
                polish_folded_ilike(SalesContact.full_name, text),
                polish_folded_ilike(func.coalesce(SalesContact.title, ""), text),
                func.coalesce(SalesContact.email, "").ilike(f"%{text.lower()}%"),
                polish_folded_ilike(func.coalesce(SalesCompany.name, ""), text),
            )
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(SalesContact.full_name, SalesContact.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ContactList(
        items=[_out(contact, name) for contact, name in rows], total=int(total or 0)
    )


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactCreate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    fields = payload.model_dump(exclude_none=True)
    full_name = _full_name(fields)
    if not full_name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Podaj imię i nazwisko."
        )
    await _check_company(db, fields.get("company_id"))
    contact = SalesContact(
        full_name=full_name, source="manual", created_by_user_id=current_user.id
    )
    _apply(contact, fields)
    db.add(contact)
    await db.commit()
    return await _load(db, contact.id)


@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact(
    contact_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    return await _load(db, contact_id)


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    contact = await db.get(SalesContact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    fields = payload.model_dump(exclude_unset=True)
    await _check_company(db, fields.get("company_id"))
    _apply(contact, fields)
    if {"full_name", "first_name", "last_name"} & fields.keys():
        full_name = _full_name(fields, contact)
        if not full_name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Podaj imię i nazwisko."
            )
        contact.full_name = full_name
    await db.commit()
    return await _load(db, contact_id)


@router.post("/{contact_id}/archive", response_model=ContactOut)
async def archive_contact(
    contact_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    contact = await db.get(SalesContact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if contact.archived_at is None:
        contact.archived_at = datetime.now(timezone.utc)
        await db.commit()
    return await _load(db, contact_id)
