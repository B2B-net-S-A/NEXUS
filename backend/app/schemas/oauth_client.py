"""Pydantic schemas for Settings → API integration (OAuth2 clients)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.oauth_client import OAuthScope


class OAuthClientOut(BaseModel):
    """Public-facing OAuth client representation. Never includes the secret."""

    id: int
    name: str
    client_id: str
    scopes: List[str]
    enabled: bool
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    last_used_at: Optional[datetime]

    model_config = {"from_attributes": True}


class OAuthClientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: List[OAuthScope] = Field(
        default_factory=list,
        description="OAuth scopes to grant. Empty list = no permissions.",
    )


class OAuthClientCreateResponse(BaseModel):
    """Special response for client creation — includes the plain secret.

    The secret is shown ONCE at creation time. After this response, only
    the bcrypt hash is stored. To rotate, the admin must regenerate.
    """

    client: OAuthClientOut
    client_secret: str = Field(
        ...,
        description=(
            "Plain-text client secret. Store this securely — it cannot be "
            "retrieved later. Regenerate to rotate."
        ),
    )


class OAuthClientUpdate(BaseModel):
    """Patch payload for ``PATCH /api/settings/oauth-clients/{id}``.

    Note: client_id and secret are immutable. Rotate by deleting + recreating.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=120)
    scopes: Optional[List[OAuthScope]] = None
    enabled: Optional[bool] = None


class ScopeInfo(BaseModel):
    """Scope metadata for the Settings UI scope picker."""

    value: str
    label: str
