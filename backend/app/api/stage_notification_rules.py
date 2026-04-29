"""CRUD reguł powiadomień stage transition.

Dwa routery:

- ``template_router`` (mount pod ``/api/pipeline-templates``) — baseline rules
  na poziomie ``PipelineStageDef``. Owner: admin/delivery_lead.

- ``client_router`` (mount pod ``/api/clients``) — overrides per klient,
  wypierają baseline. Owner: admin/delivery_lead.

Walidacje cross-field żyją w schematach Pydantic (`schemas/stage_notification.py`),
dodatkowo CHECK constraints w DB pełnią rolę safety net.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, ManagerOrAdmin
from app.core.database import get_db
from app.models.client import Client
from app.models.pipeline_template import PipelineStageDef
from app.models.stage_notification import (
    ClientStageNotificationOverride,
    StageNotificationRule,
)
from app.schemas.stage_notification import (
    ClientStageOverrideCreate,
    ClientStageOverrideResponse,
    ClientStageOverrideUpdate,
    StageNotificationRuleCreate,
    StageNotificationRuleResponse,
    StageNotificationRuleUpdate,
)

template_router = APIRouter()
client_router = APIRouter()


# ── Template-level baseline rules ────────────────────────────────────────────


async def _ensure_stage_in_template(
    db: AsyncSession, *, template_id: int, stage_def_id: int
) -> PipelineStageDef:
    stage = await db.scalar(
        select(PipelineStageDef).where(PipelineStageDef.id == stage_def_id)
    )
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage definition not found")
    if stage.template_id != template_id:
        raise HTTPException(
            status_code=400,
            detail="Stage does not belong to the requested template",
        )
    return stage


@template_router.get(
    "/{template_id}/stages/{stage_def_id}/notification-rules",
    response_model=List[StageNotificationRuleResponse],
)
async def list_rules(
    template_id: int,
    stage_def_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_stage_in_template(
        db, template_id=template_id, stage_def_id=stage_def_id
    )
    rows = await db.execute(
        select(StageNotificationRule)
        .where(StageNotificationRule.stage_def_id == stage_def_id)
        .order_by(StageNotificationRule.created_at)
    )
    return rows.scalars().all()


@template_router.post(
    "/{template_id}/stages/{stage_def_id}/notification-rules",
    response_model=StageNotificationRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    template_id: int,
    stage_def_id: int,
    payload: StageNotificationRuleCreate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_stage_in_template(
        db, template_id=template_id, stage_def_id=stage_def_id
    )
    rule = StageNotificationRule(
        stage_def_id=stage_def_id,
        recipient_type=payload.recipient_type,
        specific_user_id=payload.specific_user_id,
        role=payload.role,
        notify_inapp=payload.notify_inapp,
        notify_email=payload.notify_email,
        is_active=payload.is_active,
        created_by=current_user.id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@template_router.patch(
    "/{template_id}/stages/{stage_def_id}/notification-rules/{rule_id}",
    response_model=StageNotificationRuleResponse,
)
async def update_rule(
    template_id: int,
    stage_def_id: int,
    rule_id: int,
    payload: StageNotificationRuleUpdate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_stage_in_template(
        db, template_id=template_id, stage_def_id=stage_def_id
    )
    rule = await db.scalar(
        select(StageNotificationRule).where(
            StageNotificationRule.id == rule_id,
            StageNotificationRule.stage_def_id == stage_def_id,
        )
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(rule, field, value)

    # Re-validate full state via Pydantic — CHECK constraints i tak złapią,
    # ale lepszy komunikat z 422 niż 500 z IntegrityError.
    StageNotificationRuleCreate(
        recipient_type=rule.recipient_type,
        specific_user_id=rule.specific_user_id,
        role=rule.role,
        notify_inapp=rule.notify_inapp,
        notify_email=rule.notify_email,
        is_active=rule.is_active,
    )

    await db.commit()
    await db.refresh(rule)
    return rule


@template_router.delete(
    "/{template_id}/stages/{stage_def_id}/notification-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rule(
    template_id: int,
    stage_def_id: int,
    rule_id: int,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_stage_in_template(
        db, template_id=template_id, stage_def_id=stage_def_id
    )
    rule = await db.scalar(
        select(StageNotificationRule).where(
            StageNotificationRule.id == rule_id,
            StageNotificationRule.stage_def_id == stage_def_id,
        )
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()


# ── Client-level overrides ───────────────────────────────────────────────────


async def _ensure_client_exists(db: AsyncSession, client_id: int) -> None:
    exists = await db.scalar(select(Client.id).where(Client.id == client_id))
    if exists is None:
        raise HTTPException(status_code=404, detail="Client not found")


async def _ensure_stage_def_exists(db: AsyncSession, stage_def_id: int) -> None:
    exists = await db.scalar(
        select(PipelineStageDef.id).where(PipelineStageDef.id == stage_def_id)
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Stage definition not found")


@client_router.get(
    "/{client_id}/notification-overrides",
    response_model=List[ClientStageOverrideResponse],
)
async def list_overrides(
    client_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    stage_def_id: Optional[int] = None,
):
    await _ensure_client_exists(db, client_id)
    stmt = select(ClientStageNotificationOverride).where(
        ClientStageNotificationOverride.client_id == client_id
    )
    if stage_def_id is not None:
        stmt = stmt.where(ClientStageNotificationOverride.stage_def_id == stage_def_id)
    stmt = stmt.order_by(
        ClientStageNotificationOverride.stage_def_id,
        ClientStageNotificationOverride.created_at,
    )
    rows = await db.execute(stmt)
    return rows.scalars().all()


@client_router.post(
    "/{client_id}/notification-overrides",
    response_model=ClientStageOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_override(
    client_id: int,
    payload: ClientStageOverrideCreate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_client_exists(db, client_id)
    await _ensure_stage_def_exists(db, payload.stage_def_id)
    override = ClientStageNotificationOverride(
        client_id=client_id,
        stage_def_id=payload.stage_def_id,
        recipient_type=payload.recipient_type,
        specific_user_id=payload.specific_user_id,
        role=payload.role,
        notify_inapp=payload.notify_inapp,
        notify_email=payload.notify_email,
        is_active=payload.is_active,
        created_by=current_user.id,
    )
    db.add(override)
    try:
        await db.commit()
    except Exception as exc:  # pragma: no cover  (PG IntegrityError on uq_*)
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Override with this configuration already exists for the client/stage",
        ) from exc
    await db.refresh(override)
    return override


@client_router.patch(
    "/{client_id}/notification-overrides/{override_id}",
    response_model=ClientStageOverrideResponse,
)
async def update_override(
    client_id: int,
    override_id: int,
    payload: ClientStageOverrideUpdate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_client_exists(db, client_id)
    override = await db.scalar(
        select(ClientStageNotificationOverride).where(
            ClientStageNotificationOverride.id == override_id,
            ClientStageNotificationOverride.client_id == client_id,
        )
    )
    if override is None:
        raise HTTPException(status_code=404, detail="Override not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(override, field, value)

    # Re-validate spójność po update (lepszy komunikat niż 500 z CHECK).
    StageNotificationRuleCreate(
        recipient_type=override.recipient_type,
        specific_user_id=override.specific_user_id,
        role=override.role,
        notify_inapp=override.notify_inapp,
        notify_email=override.notify_email,
        is_active=override.is_active,
    )

    await db.commit()
    await db.refresh(override)
    return override


@client_router.delete(
    "/{client_id}/notification-overrides/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_override(
    client_id: int,
    override_id: int,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_client_exists(db, client_id)
    override = await db.scalar(
        select(ClientStageNotificationOverride).where(
            ClientStageNotificationOverride.id == override_id,
            ClientStageNotificationOverride.client_id == client_id,
        )
    )
    if override is None:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.delete(override)
    await db.commit()


__all__ = ["template_router", "client_router"]
