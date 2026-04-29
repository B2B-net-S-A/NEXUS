"""Procedures (SOP) API — wewnętrzna baza wiedzy dla zespołu.

Czytelne dla wszystkich zalogowanych; edycja zarezerwowana dla admina.
Search po tytule i treści (ILIKE, case-insensitive).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.models.procedure import Procedure
from app.models.user import UserRole
from app.api.deps import AdminUser, CurrentUser

router = APIRouter()


# ── Pydantic schemas ────────────────────────────────────────────────────────


class ProcedureCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    content: str = Field(min_length=1)
    sort_order: int = 0
    is_published: bool = True


class ProcedureUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=255)
    content: Optional[str] = Field(default=None, min_length=1)
    sort_order: Optional[int] = None
    is_published: Optional[bool] = None


class ProcedureSummary(BaseModel):
    id: int
    slug: str
    title: str
    sort_order: int
    is_published: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProcedureResponse(BaseModel):
    id: int
    slug: str
    title: str
    content: str
    sort_order: int
    is_published: bool
    created_by: Optional[int]
    updated_by: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ─────────────────────────────────────────────────────────────────


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    """Prosty, deterministyczny slugifier (ASCII, myślniki)."""
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower().strip()
    slug = _SLUG_STRIP_RE.sub("-", lower).strip("-")
    return slug or "procedura"


async def _ensure_unique_slug(
    db: AsyncSession, base: str, exclude_id: Optional[int] = None
) -> str:
    """Zwraca slug, dodając sufiks -2, -3, … jeśli już istnieje."""
    candidate = base
    suffix = 2
    while True:
        stmt = select(Procedure.id).where(Procedure.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.where(Procedure.id != exclude_id)
        existing = await db.scalar(stmt)
        if existing is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def _is_admin(user) -> bool:
    return user.role == UserRole.admin


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/procedures", response_model=list[ProcedureSummary])
async def list_procedures(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(default=None, description="Wyszukaj po tytule i treści"),
    published_only: bool = Query(
        default=True,
        description="Domyślnie true; admin może przekazać false aby widzieć szkice",
    ),
) -> list[Procedure]:
    stmt = select(Procedure)

    # Non-admin zawsze widzi tylko opublikowane, niezależnie od query param
    effective_published_only = published_only or not _is_admin(current_user)
    if effective_published_only:
        stmt = stmt.where(Procedure.is_published.is_(True))

    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Procedure.title.ilike(pattern), Procedure.content.ilike(pattern))
        )

    stmt = stmt.order_by(Procedure.sort_order.desc(), Procedure.updated_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/procedures/{id_or_slug}", response_model=ProcedureResponse)
async def get_procedure(
    id_or_slug: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Procedure:
    if id_or_slug.isdigit():
        stmt = select(Procedure).where(Procedure.id == int(id_or_slug))
    else:
        stmt = select(Procedure).where(Procedure.slug == id_or_slug)
    procedure = await db.scalar(stmt)
    if procedure is None:
        raise HTTPException(status_code=404, detail="Procedure not found")
    # Non-admin nie widzi szkiców
    if not procedure.is_published and not _is_admin(current_user):
        raise HTTPException(status_code=404, detail="Procedure not found")
    return procedure


@router.post(
    "/procedures",
    response_model=ProcedureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_procedure(
    data: ProcedureCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Procedure:
    slug = await _ensure_unique_slug(db, _slugify(data.title))
    procedure = Procedure(
        title=data.title.strip(),
        slug=slug,
        content=data.content,
        sort_order=data.sort_order,
        is_published=data.is_published,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(procedure)
    await db.flush()
    await db.refresh(procedure)
    return procedure


@router.put("/procedures/{procedure_id}", response_model=ProcedureResponse)
async def update_procedure(
    procedure_id: int,
    data: ProcedureUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Procedure:
    procedure = await db.scalar(select(Procedure).where(Procedure.id == procedure_id))
    if procedure is None:
        raise HTTPException(status_code=404, detail="Procedure not found")

    if data.title is not None and data.title.strip() != procedure.title:
        procedure.title = data.title.strip()
        procedure.slug = await _ensure_unique_slug(
            db, _slugify(procedure.title), exclude_id=procedure.id
        )
    if data.content is not None:
        procedure.content = data.content
    if data.sort_order is not None:
        procedure.sort_order = data.sort_order
    if data.is_published is not None:
        procedure.is_published = data.is_published

    procedure.updated_by = current_user.id
    await db.flush()
    await db.refresh(procedure)
    return procedure


@router.delete(
    "/procedures/{procedure_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_procedure(
    procedure_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    procedure = await db.scalar(select(Procedure).where(Procedure.id == procedure_id))
    if procedure is None:
        raise HTTPException(status_code=404, detail="Procedure not found")
    await db.delete(procedure)
    await db.flush()
