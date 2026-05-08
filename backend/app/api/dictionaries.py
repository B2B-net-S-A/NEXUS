"""Editable taxonomy CRUD (Settings → Słowniki, Traffit gap #8).

Admin-only endpoints. Read access (GET) returns all dictionaries + items
including archived; the UI hides archived rows behind a toggle but
historical references still resolve.

Public read access (e.g. for filling a UI dropdown on the candidate
form) is exposed via ``GET /api/dictionaries/{slug}/items?archived=0``
which is open to authenticated users (CurrentUser, not AdminUser).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.dictionary import Dictionary, DictionaryItem
from app.schemas.dictionary import (
    DictionaryItemCreate,
    DictionaryItemOut,
    DictionaryItemUpdate,
    DictionaryOut,
    DictionarySummary,
)

router = APIRouter()


# ── Public read (any authenticated user) ─────────────────────────────────────


@router.get("/dictionaries/{slug}/items", response_model=List[DictionaryItemOut])
async def list_dictionary_items(
    slug: str,
    _: CurrentUser,
    db: AsyncSession = Depends(get_db),
    include_archived: bool = Query(False),
) -> List[DictionaryItem]:
    """Read items of a dictionary by slug. Used by UI dropdowns / pickers.

    Returns 404 if the slug does not exist; archived items are hidden by
    default so dropdowns stay clean.
    """
    dictionary = await db.scalar(select(Dictionary).where(Dictionary.slug == slug))
    if dictionary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found"
        )

    stmt = (
        select(DictionaryItem)
        .where(DictionaryItem.dictionary_id == dictionary.id)
        .order_by(DictionaryItem.ordinal, DictionaryItem.id)
    )
    if not include_archived:
        stmt = stmt.where(DictionaryItem.archived.is_(False))

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ── Admin-only management ────────────────────────────────────────────────────


@router.get("/settings/dictionaries", response_model=List[DictionarySummary])
async def list_dictionaries(
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> List[DictionarySummary]:
    """Index page: list of dictionaries with item counts."""
    stmt = (
        select(
            Dictionary.slug,
            Dictionary.label_pl,
            Dictionary.description,
            Dictionary.enforced,
            func.count(DictionaryItem.id).label("item_count"),
        )
        .outerjoin(
            DictionaryItem,
            (DictionaryItem.dictionary_id == Dictionary.id)
            & DictionaryItem.archived.is_(False),
        )
        .group_by(Dictionary.id)
        .order_by(Dictionary.slug)
    )
    rows = await db.execute(stmt)
    return [
        DictionarySummary(
            slug=row.slug,
            label_pl=row.label_pl,
            description=row.description,
            enforced=row.enforced,
            item_count=int(row.item_count or 0),
        )
        for row in rows.all()
    ]


@router.get("/settings/dictionaries/{slug}", response_model=DictionaryOut)
async def get_dictionary(
    slug: str,
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Dictionary:
    """Full dictionary including all items (active + archived)."""
    stmt = (
        select(Dictionary)
        .where(Dictionary.slug == slug)
        .options(selectinload(Dictionary.items))
    )
    result = await db.execute(stmt)
    dictionary = result.scalar_one_or_none()
    if dictionary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found"
        )
    return dictionary


@router.post(
    "/settings/dictionaries/{slug}/items",
    response_model=DictionaryItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_dictionary_item(
    slug: str,
    payload: DictionaryItemCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> DictionaryItem:
    """Append a new value to a dictionary."""
    dictionary = await db.scalar(select(Dictionary).where(Dictionary.slug == slug))
    if dictionary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found"
        )

    # Reject duplicate keys before bumping into the unique constraint so the
    # error message is friendly.
    duplicate = await db.scalar(
        select(DictionaryItem).where(
            DictionaryItem.dictionary_id == dictionary.id,
            DictionaryItem.key == payload.key,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An item with this key already exists",
        )

    item = DictionaryItem(
        dictionary_id=dictionary.id,
        key=payload.key,
        label_pl=payload.label_pl,
        label_en=payload.label_en,
        ordinal=payload.ordinal,
        last_edited_by=admin.id,
        last_edited_at=datetime.now(timezone.utc),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch(
    "/settings/dictionaries/{slug}/items/{item_id}",
    response_model=DictionaryItemOut,
)
async def update_dictionary_item(
    slug: str,
    item_id: int,
    payload: DictionaryItemUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> DictionaryItem:
    """Edit / reorder / archive a dictionary item."""
    dictionary = await db.scalar(select(Dictionary).where(Dictionary.slug == slug))
    if dictionary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found"
        )

    item = await db.scalar(
        select(DictionaryItem).where(
            DictionaryItem.id == item_id,
            DictionaryItem.dictionary_id == dictionary.id,
        )
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )

    if payload.key is not None:
        item.key = payload.key
    if payload.label_pl is not None:
        item.label_pl = payload.label_pl
    if payload.label_en is not None:
        item.label_en = payload.label_en
    if payload.ordinal is not None:
        item.ordinal = payload.ordinal
    if payload.archived is not None:
        item.archived = payload.archived

    item.last_edited_by = admin.id
    item.last_edited_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(item)
    return item
