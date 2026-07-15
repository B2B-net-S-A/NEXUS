"""Public response contracts shared by external-system integrations.

The integration is deliberately eventually consistent: domain writes succeed in
NEXUS first and a transactional outbox delivers them to Traffit after commit.
These lightweight contracts let clients make that state explicit instead of
presenting a local write as if it had already reached the remote system.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


IntegrationState = Literal[
    "synced",
    "pending",
    "conflict",
    "error",
    "manual_action_required",
]


class IntegrationSyncState(BaseModel):
    system: Literal["traffit"] = "traffit"
    state: IntegrationState
    external_id: Optional[str] = None
    remote_url: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    pending_events: int = Field(default=0, ge=0)
    conflict_id: Optional[int] = None
    message: Optional[str] = None


class DeletionRequestResponse(BaseModel):
    status: Literal["manual_review"] = "manual_review"
    conflict_id: int
    entity_type: str
    entity_id: int
    message: str


class ConflictResolveRequest(BaseModel):
    resolution: Literal["nexus", "traffit", "merged", "manual", "unlink"]
    merged_value: Any = None
    note: Optional[str] = Field(default=None, max_length=2000)


__all__ = [
    "ConflictResolveRequest",
    "DeletionRequestResponse",
    "IntegrationState",
    "IntegrationSyncState",
]
