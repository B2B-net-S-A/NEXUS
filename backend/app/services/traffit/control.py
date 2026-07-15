"""Effective runtime controls for the bidirectional Traffit integration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.traffit_integration import TraffitIntegrationControl


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(getattr(app_settings, name, default))
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def integration_master_enabled() -> bool:
    """Cheap fail-closed check safe to call before the migration exists."""
    return _env_bool("TRAFFIT_INTEGRATION_ENABLED", False)


@dataclass(frozen=True)
class EffectiveTraffitControl:
    master_enabled: bool = False
    webhook_accept_enabled: bool = False
    inbound_apply_enabled: bool = False
    poll_enabled: bool = False
    outbound_enabled: bool = False
    dry_run: bool = True
    paused_reason: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


async def get_control_row(
    db: AsyncSession,
    *,
    create: bool = False,
) -> Optional[TraffitIntegrationControl]:
    row = await db.scalar(
        select(TraffitIntegrationControl).where(
            TraffitIntegrationControl.integration == "traffit"
        )
    )
    if row is None and create:
        row = TraffitIntegrationControl(
            integration="traffit",
            webhook_accept_enabled=False,
            inbound_apply_enabled=False,
            poll_enabled=False,
            outbound_enabled=False,
            dry_run=True,
            settings={},
        )
        db.add(row)
        await db.flush()
    return row


async def effective_control(db: AsyncSession) -> EffectiveTraffitControl:
    """Combine DB switches with fail-closed environment kill-switches."""
    row = await get_control_row(db)
    master = integration_master_enabled()
    if row is None:
        return EffectiveTraffitControl(master_enabled=master)
    return EffectiveTraffitControl(
        master_enabled=master,
        webhook_accept_enabled=(
            master
            and _env_bool("TRAFFIT_WEBHOOK_ACCEPT_ENABLED", False)
            and bool(row.webhook_accept_enabled)
        ),
        inbound_apply_enabled=(
            master
            and _env_bool("TRAFFIT_INBOUND_APPLY_ENABLED", False)
            and bool(row.inbound_apply_enabled)
        ),
        poll_enabled=(
            master
            and _env_bool("TRAFFIT_POLL_ENABLED", False)
            and bool(row.poll_enabled)
        ),
        outbound_enabled=(
            master
            and _env_bool("TRAFFIT_OUTBOUND_ENABLED", False)
            and bool(row.outbound_enabled)
        ),
        # Environment can force dry-run even when DB says live. Default true.
        dry_run=bool(row.dry_run) or _env_bool("TRAFFIT_DRY_RUN", True),
        paused_reason=row.paused_reason,
        settings=dict(row.settings or {}),
    )
