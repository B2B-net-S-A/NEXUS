"""Settings → API integration: OAuth2 client management (admin-only).

CRUD for ``OAuthClient`` rows. Token issue endpoint
(``POST /api/oauth/token`` — client_credentials grant) lives elsewhere
and lands in a follow-up commit — this module only manages the storage.

Secrets are generated server-side and returned ONCE in the create response.
After creation, only the bcrypt hash is stored; clients that lose the secret
must regenerate via DELETE + create.
"""

from __future__ import annotations

import secrets
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.core.security import hash_password
from app.models.oauth_client import SCOPE_LABELS, OAuthClient, OAuthScope
from app.schemas.oauth_client import (
    OAuthClientCreate,
    OAuthClientCreateResponse,
    OAuthClientOut,
    OAuthClientUpdate,
    ScopeInfo,
)

router = APIRouter(prefix="/settings/oauth-clients", tags=["oauth-clients"])


def _generate_client_id() -> str:
    """Opaque, URL-safe identifier exposed publicly to integration partners."""
    return uuid.uuid4().hex


def _generate_client_secret() -> str:
    """Cryptographically random secret. 48 bytes ≈ 64 chars urlsafe."""
    return secrets.token_urlsafe(48)


@router.get("/scopes", response_model=List[ScopeInfo])
async def list_scopes(_: AdminUser) -> List[ScopeInfo]:
    """Return the scope vocabulary + display labels for the Settings UI."""
    return [
        ScopeInfo(value=scope.value, label=SCOPE_LABELS.get(scope, scope.value))
        for scope in OAuthScope
    ]


@router.get("", response_model=List[OAuthClientOut])
async def list_clients(
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> List[OAuthClient]:
    """List every configured OAuth client. Secrets are never returned."""
    result = await db.execute(
        select(OAuthClient).order_by(OAuthClient.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "",
    response_model=OAuthClientCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client(
    payload: OAuthClientCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> OAuthClientCreateResponse:
    """Create a new OAuth client. Returns the plain secret ONCE.

    Subsequent reads only expose the hash. To rotate, DELETE + recreate.
    """
    client_id = _generate_client_id()
    client_secret = _generate_client_secret()

    client = OAuthClient(
        name=payload.name,
        client_id=client_id,
        secret_hash=hash_password(client_secret),
        scopes=[s.value for s in payload.scopes],
        enabled=True,
        created_by=admin.id,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)

    return OAuthClientCreateResponse(
        client=OAuthClientOut.model_validate(client),
        client_secret=client_secret,
    )


@router.patch("/{client_pk}", response_model=OAuthClientOut)
async def update_client(
    client_pk: int,
    payload: OAuthClientUpdate,
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> OAuthClient:
    """Toggle enabled flag, rename, or update scopes. Secret is immutable here."""
    result = await db.execute(select(OAuthClient).where(OAuthClient.id == client_pk))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="OAuth client not found"
        )

    if payload.name is not None:
        client.name = payload.name
    if payload.scopes is not None:
        client.scopes = [s.value for s in payload.scopes]
    if payload.enabled is not None:
        client.enabled = payload.enabled

    await db.commit()
    await db.refresh(client)
    return client


@router.delete("/{client_pk}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_pk: int,
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard-delete an OAuth client. All issued JWTs remain valid until expiry —
    the only way to immediately revoke is to set ``enabled=False`` (PATCH)
    *before* the next token request, since the token endpoint reads the row.
    """
    result = await db.execute(select(OAuthClient).where(OAuthClient.id == client_pk))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="OAuth client not found"
        )

    await db.delete(client)
    await db.commit()
