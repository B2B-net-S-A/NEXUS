"""Pydantic schemas for candidate invite links."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


InviteLinkStatus = Literal["active", "used", "revoked", "expired"]


class InviteLinkCreate(BaseModel):
    job_id: int = Field(..., description="Published job this link applies to.")
    label: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Private recruiter note, e.g. 'LinkedIn post 04/26'.",
    )
    expires_in_days: Literal[7, 14, 30, 90] = Field(
        default=30, description="Link validity window."
    )


class InviteLinkJobBrief(BaseModel):
    id: int
    title: str


class InviteLinkCreatorBrief(BaseModel):
    id: int
    name: str


class InviteLinkResponse(BaseModel):
    token: str
    url: str
    job: InviteLinkJobBrief
    label: Optional[str] = None
    expires_at: datetime
    revoked: bool = False
    use_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime
    status: InviteLinkStatus
    origin_assignment_id: Optional[int] = None
    priority_compliant_at_create: Optional[bool] = None
    created_by_user: Optional[InviteLinkCreatorBrief] = None

    model_config = {"from_attributes": True}
