"""Teams notification channels CRUD — Phase 7.6 of the M365 plan.

Admin-only endpoints to configure which Microsoft Teams channels receive
Adaptive Card notifications for ATS events. See
``app.services.teams_notifications`` for the card builders and Graph send.

Endpoints (mounted under /api/teams-channels):
- GET    /                  — list all channels
- POST   /                  — create
- PATCH  /{id}              — partial update (label, types, enabled)
- DELETE /{id}              — hard delete (drop the row; UI calls this for
                              "remove channel"; soft-disable uses PATCH
                              with enabled=false)
- POST   /{id}/test         — send a test Adaptive Card to verify wiring

All write endpoints validate `notification_types` against the canonical
``NOTIFICATION_TYPES`` set so the FE chip selector and the trigger fan-out
stay in sync without a separate enum table.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.teams_channel import TeamsNotificationChannel
from app.services.teams_notifications import (
    NOTIFICATION_TYPES,
    TeamsNotConfigured,
    TeamsSendError,
    build_test_card,
    send_to_channel,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────


class TeamsChannelCreate(BaseModel):
    workspace_label: str = Field(min_length=1, max_length=120)
    team_id: str = Field(min_length=1, max_length=255)
    channel_id: str = Field(min_length=1, max_length=255)
    notification_types: List[str] = Field(default_factory=list)

    @field_validator("notification_types")
    @classmethod
    def _validate_types(cls, v: List[str]) -> List[str]:
        unknown = [t for t in v if t not in NOTIFICATION_TYPES]
        if unknown:
            raise ValueError(
                f"Unknown notification types: {unknown}. "
                f"Allowed: {sorted(NOTIFICATION_TYPES)}"
            )
        # De-duplicate while preserving order.
        seen: set[str] = set()
        out: List[str] = []
        for t in v:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out


class TeamsChannelUpdate(BaseModel):
    workspace_label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    notification_types: Optional[List[str]] = None
    enabled: Optional[bool] = None

    @field_validator("notification_types")
    @classmethod
    def _validate_types(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        unknown = [t for t in v if t not in NOTIFICATION_TYPES]
        if unknown:
            raise ValueError(
                f"Unknown notification types: {unknown}. "
                f"Allowed: {sorted(NOTIFICATION_TYPES)}"
            )
        seen: set[str] = set()
        out: List[str] = []
        for t in v:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out


class TeamsChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_label: str
    team_id: str
    channel_id: str
    notification_types: List[str]
    enabled: bool
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=List[TeamsChannelResponse])
async def list_channels(
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> List[TeamsChannelResponse]:
    rows = (
        (
            await db.execute(
                select(TeamsNotificationChannel).order_by(
                    TeamsNotificationChannel.created_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [TeamsChannelResponse.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=TeamsChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    payload: TeamsChannelCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> TeamsChannelResponse:
    existing = await db.scalar(
        select(TeamsNotificationChannel).where(
            TeamsNotificationChannel.team_id == payload.team_id,
            TeamsNotificationChannel.channel_id == payload.channel_id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A channel with this (team_id, channel_id) is already registered",
        )

    row = TeamsNotificationChannel(
        workspace_label=payload.workspace_label,
        team_id=payload.team_id,
        channel_id=payload.channel_id,
        notification_types=payload.notification_types,
        enabled=True,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return TeamsChannelResponse.model_validate(row)


@router.patch("/{channel_db_id}", response_model=TeamsChannelResponse)
async def update_channel(
    channel_db_id: int,
    payload: TeamsChannelUpdate,
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> TeamsChannelResponse:
    row = await db.scalar(
        select(TeamsNotificationChannel).where(
            TeamsNotificationChannel.id == channel_db_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Teams channel not found")

    if payload.workspace_label is not None:
        row.workspace_label = payload.workspace_label
    if payload.notification_types is not None:
        row.notification_types = payload.notification_types
    if payload.enabled is not None:
        row.enabled = payload.enabled

    await db.commit()
    await db.refresh(row)
    return TeamsChannelResponse.model_validate(row)


@router.delete("/{channel_db_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_db_id: int,
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.scalar(
        select(TeamsNotificationChannel).where(
            TeamsNotificationChannel.id == channel_db_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Teams channel not found")
    await db.delete(row)
    await db.commit()


class TeamsChannelTestResponse(BaseModel):
    sent: bool
    detail: Optional[str] = None


@router.post("/{channel_db_id}/test", response_model=TeamsChannelTestResponse)
async def test_channel(
    channel_db_id: int,
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> TeamsChannelTestResponse:
    """Send a test Adaptive Card and report whether it landed.

    Errors are reported back to the admin as readable strings so they can
    diagnose missing admin consent (403) vs. wrong channel id (404) vs.
    revoked credentials (401) without leaving the Settings page.
    """
    row = await db.scalar(
        select(TeamsNotificationChannel).where(
            TeamsNotificationChannel.id == channel_db_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Teams channel not found")

    try:
        ok = await send_to_channel(
            team_id=row.team_id,
            channel_id=row.channel_id,
            card=build_test_card(),
        )
    except TeamsNotConfigured as exc:
        return TeamsChannelTestResponse(sent=False, detail=str(exc))
    except TeamsSendError as exc:
        return TeamsChannelTestResponse(sent=False, detail=str(exc))

    if not ok:
        # Hit when the kill-switch is off — `send_to_channel` returns False
        # before contacting Graph. Surface that to the admin instead of
        # silently reporting success.
        return TeamsChannelTestResponse(
            sent=False,
            detail=(
                "Integracja Teams jest wyłączona. Ustaw TEAMS_NOTIFICATIONS_ENABLED=true "
                "w Coolify env vault."
            ),
        )
    return TeamsChannelTestResponse(sent=True)
