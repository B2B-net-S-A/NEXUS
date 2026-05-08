"""Custom field schema editor (Settings → Konfiguracja pól, gap #7).

Admin-only CRUD on ``entity_field_defs``. Reads (e.g. for the form
renderer) are open to any authenticated user via the same GET endpoint.

The drag-drop reorder operation maps to a single PATCH per moved field
that updates ``ordinal`` (and possibly ``section`` if dropped into a
different column). The frontend keeps a local optimistic state and
batches saves.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.entity_field import (
    FIELD_TYPE_LABELS,
    EntityFieldDef,
    EntityType,
    FieldType,
)
from app.schemas.entity_field import (
    EntityFieldDefCreate,
    EntityFieldDefOut,
    EntityFieldDefUpdate,
    FieldTypeInfo,
    SchemaListResponse,
)

router = APIRouter()


@router.get("/entity-schema/{entity_type}", response_model=SchemaListResponse)
async def get_entity_schema(
    entity_type: EntityType,
    _: CurrentUser,
    db: AsyncSession = Depends(get_db),
    include_archived: bool = False,
) -> SchemaListResponse:
    """Return all custom field definitions for an entity. Used by both
    the admin editor and the runtime form renderer.
    """
    stmt = (
        select(EntityFieldDef)
        .where(EntityFieldDef.entity_type == entity_type)
        .order_by(EntityFieldDef.section, EntityFieldDef.ordinal, EntityFieldDef.id)
    )
    if not include_archived:
        stmt = stmt.where(EntityFieldDef.archived.is_(False))

    result = await db.execute(stmt)
    fields = list(result.scalars().all())
    return SchemaListResponse(entity_type=entity_type, fields=fields)


@router.get("/settings/entity-fields/types", response_model=List[FieldTypeInfo])
async def list_field_types(_: AdminUser) -> List[FieldTypeInfo]:
    """Field type vocabulary + Polish labels. Powers the type picker in
    the editor's "Add field" form.
    """
    return [
        FieldTypeInfo(value=ft, label=FIELD_TYPE_LABELS.get(ft, ft.value))
        for ft in FieldType
    ]


@router.post(
    "/settings/entity-fields",
    response_model=EntityFieldDefOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_entity_field(
    payload: EntityFieldDefCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> EntityFieldDef:
    """Add a new custom field to an entity."""
    # Friendly duplicate-key error (the unique constraint would still catch it).
    duplicate = await db.scalar(
        select(EntityFieldDef).where(
            EntityFieldDef.entity_type == payload.entity_type,
            EntityFieldDef.key == payload.key,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Field '{payload.key}' already exists on {payload.entity_type.value}",
        )

    field = EntityFieldDef(
        entity_type=payload.entity_type,
        key=payload.key,
        label_pl=payload.label_pl,
        label_en=payload.label_en,
        help_text=payload.help_text,
        field_type=payload.field_type,
        options=payload.options or {},
        required=payload.required,
        section=payload.section or "middle",
        ordinal=payload.ordinal,
        created_by=admin.id,
        last_edited_at=datetime.now(timezone.utc),
    )
    db.add(field)
    await db.commit()
    await db.refresh(field)
    return field


@router.patch(
    "/settings/entity-fields/{field_id}",
    response_model=EntityFieldDefOut,
)
async def update_entity_field(
    field_id: int,
    payload: EntityFieldDefUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> EntityFieldDef:
    """Edit / reorder / archive a custom field.

    Note: ``key``, ``entity_type``, and ``field_type`` are intentionally
    immutable here — changing them would orphan all stored values in
    candidate.custom_fields / job.custom_fields. Recreate via DELETE +
    POST if you need to repurpose a field.
    """
    field = await db.scalar(select(EntityFieldDef).where(EntityFieldDef.id == field_id))
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Field not found"
        )

    if payload.label_pl is not None:
        field.label_pl = payload.label_pl
    if payload.label_en is not None:
        field.label_en = payload.label_en
    if payload.help_text is not None:
        field.help_text = payload.help_text
    if payload.options is not None:
        field.options = payload.options
    if payload.required is not None:
        field.required = payload.required
    if payload.section is not None:
        field.section = payload.section
    if payload.ordinal is not None:
        field.ordinal = payload.ordinal
    if payload.archived is not None:
        field.archived = payload.archived

    field.last_edited_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(field)
    return field
