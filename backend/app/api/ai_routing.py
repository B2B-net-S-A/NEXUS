"""Audited administrator-only activation of code-owned AI route registries."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import REGISTRIES, public_registry
from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.ai_platform import AIRoutingActivationLog, AIRoutingState

router = APIRouter(prefix="/admin/ai-routing", tags=["admin-ai-routing"])


class RoutingActivation(BaseModel):
    registry_version: str = Field(min_length=1, max_length=64)
    expected_current_version: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=10, max_length=1000)
    model_config = {"extra": "forbid"}


@router.post("/activate")
async def activate_routing(
    payload: RoutingActivation,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.registry_version not in REGISTRIES:
        raise HTTPException(status_code=422, detail="Unknown AI registry version")
    row = await db.scalar(
        select(AIRoutingState).where(AIRoutingState.id == 1).with_for_update()
    )
    if row is None:
        row = AIRoutingState(
            id=1,
            registry_version="v1_current",
            lock_version=1,
            reason="Initial safe baseline",
        )
        db.add(row)
        await db.flush()
    if row.registry_version != payload.expected_current_version:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "AI routing changed concurrently",
                "current_version": row.registry_version,
                "lock_version": row.lock_version,
            },
        )
    previous_version = row.registry_version
    row.registry_version = payload.registry_version
    row.lock_version += 1
    row.reason = payload.reason
    row.activated_by = admin.id
    row.activated_at = datetime.now(timezone.utc)
    db.add(
        AIRoutingActivationLog(
            previous_version=previous_version,
            registry_version=row.registry_version,
            lock_version=row.lock_version,
            reason=row.reason,
            activated_by=admin.id,
        )
    )
    await db.commit()
    return {
        "registry_version": row.registry_version,
        "lock_version": row.lock_version,
        "reason": row.reason,
        "routes": public_registry(row.registry_version),
    }
