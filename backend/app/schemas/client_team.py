"""Schemas for the Client ↔ Team (TAC + DL) assignment endpoints.

Surfaced by `GET /api/clients/{id}/team` and CRUD on
`/api/clients/{id}/tacs/*`. The DL side is managed by the pre-existing
`/api/team-structure/dl-clients/*` router — we still return DL data here
so the client page can render a single "Opiekunowie" tab with both.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ClientTacAssignmentCreate(BaseModel):
    """POST /api/clients/{id}/tacs body."""

    user_id: int
    # Omitted means "preserve" for an existing row and ``False`` for a new
    # row. This prevents callers using only the new priority field from
    # rewriting the legacy notification marker.
    is_primary: Optional[bool] = None
    # ``None`` means "keep/default according to expand policy": the first
    # client of a TAC becomes priority #1, subsequent clients do not.
    is_first_priority_for_tac: Optional[bool] = None


class ClientTacAssignmentRead(BaseModel):
    """TAC assignment projection with embedded user basics."""

    id: int
    user_id: int
    name: str
    email: str
    role: Optional[str] = None
    is_first_priority_for_tac: Optional[bool] = None
    is_primary: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ClientDlAssignmentRead(BaseModel):
    """Delivery Lead assignment projection (read-only here).

    Writes go through `/api/team-structure/dl-clients/*`.
    """

    id: int
    user_id: int
    name: str
    email: str
    role: Optional[str] = None
    is_head: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ClientTeamResponse(BaseModel):
    """Unified team view for a client."""

    tacs: list[ClientTacAssignmentRead]
    delivery_leads: list[ClientDlAssignmentRead]


class ClientTacFirstPriorityRead(BaseModel):
    """Result of an atomic TAC-centric first-priority change."""

    tac_user_id: int
    client_id: int
    is_first_priority_for_tac: bool


class ClientTacFirstPriorityUpdate(BaseModel):
    """PUT body for a TAC-centric first-priority change."""

    enabled: bool
    successor_client_id: Optional[int] = None
