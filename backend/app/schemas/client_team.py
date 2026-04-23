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
    is_primary: bool = False


class ClientTacAssignmentRead(BaseModel):
    """TAC assignment projection with embedded user basics."""

    id: int
    user_id: int
    name: str
    email: str
    role: Optional[str] = None
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
