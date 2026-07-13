"""OAuth2 token endpoint (client_credentials grant).

External integrations call ``POST /api/oauth/token`` with their client_id +
client_secret to receive a short-lived JWT carrying the granted scopes.
The JWT can then be presented as ``Authorization: Bearer <token>`` to any
NEXUS endpoint guarded by ``@require_scope(...)``.

Design notes:
- Same central PyJWT machinery as user tokens, but with ``type="client"`` and
  scope claim — so ``get_current_user`` cleanly rejects them (it requires
  ``type=="access"``).
- Default TTL = 1 hour (configurable via env later); shorter than user
  tokens because we don't have refresh.
- Issued tokens carry exactly the scopes the requester asked for, ANDed
  with what the OAuthClient has granted. Asking for an unowned scope is
  a 400, not a silent narrowing — keeps integrations honest.

Security:
- Client secret is verified against bcrypt hash via the same passlib
  context user passwords use.
- Disabled clients (``enabled=False``) are rejected even if creds match.
- ``last_used_at`` is stamped on every successful exchange so admin can
  see "this integration is dead — disable it" in the Settings UI.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import JWTError, jwt
from app.core.security import ALGORITHM, verify_password
from app.models.oauth_client import OAuthClient, OAuthScope

router = APIRouter()

# Default TTL for client_credentials tokens. Shorter than user JWTs because
# OAuth clients can re-request silently (no UX cost) and short-lived tokens
# limit blast radius of a leaked Authorization header.
_TOKEN_TTL_SECONDS = 3600

_bearer = HTTPBearer(auto_error=False)


# ── Request / response schemas ───────────────────────────────────────────────


class TokenRequest(BaseModel):
    """OAuth2 client_credentials grant payload.

    Standard OAuth2 form fields, but accepted as JSON for simpler curl/n8n
    integration. ``scope`` is space-separated per RFC 6749 §3.3.
    """

    grant_type: str = Field(
        ..., pattern="^client_credentials$", description="Must be 'client_credentials'"
    )
    client_id: str
    client_secret: str
    scope: Optional[str] = Field(
        None,
        description=(
            "Space-separated list of requested scopes. Must be a subset of "
            "the client's granted scopes. If omitted, all granted scopes are issued."
        ),
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = _TOKEN_TTL_SECONDS
    scope: str = Field(..., description="Space-separated scopes carried by the token")


# ── Token issuance ───────────────────────────────────────────────────────────


def _create_client_token(client: OAuthClient, scopes: List[str]) -> str:
    """Mint a JWT carrying ``type=client`` + ``scope=...`` claims.

    Reuses ``settings.SECRET_KEY`` + HS256 — same as user tokens — so a
    single ``decode_token`` call validates either kind. Differentiation
    happens via the ``type`` claim at the consumer side.
    """
    expire = datetime.now(timezone.utc) + timedelta(seconds=_TOKEN_TTL_SECONDS)
    payload = {
        "sub": client.client_id,  # public id, not int user pk
        "type": "client",
        "scope": " ".join(scopes),
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


@router.post("/oauth/token", response_model=TokenResponse)
async def issue_token(
    payload: TokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange client credentials for a scoped access token."""
    # Look up client. We answer ALL credential failures with the same 401
    # message + body so a probing caller cannot tell whether the client_id
    # exists or the secret is wrong.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_client",
    )

    result = await db.execute(
        select(OAuthClient).where(OAuthClient.client_id == payload.client_id)
    )
    client = result.scalar_one_or_none()
    if client is None or not client.enabled:
        raise invalid

    if not verify_password(payload.client_secret, client.secret_hash):
        raise invalid

    granted = set(client.scopes or [])

    # Requested scopes — default to everything the client has been granted.
    if payload.scope:
        requested = set(payload.scope.split())
        unknown = requested - {s.value for s in OAuthScope}
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_scope",
                    "unknown": sorted(unknown),
                },
            )
        ungranted = requested - granted
        if ungranted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_scope",
                    "not_granted": sorted(ungranted),
                },
            )
        scopes_to_issue = sorted(requested)
    else:
        scopes_to_issue = sorted(granted)

    # Stamp last_used_at so admin can see "dead integration" in the UI.
    client.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    token = _create_client_token(client, scopes_to_issue)
    return TokenResponse(
        access_token=token,
        scope=" ".join(scopes_to_issue),
    )


# ── Scope-checking dependency for protected endpoints ────────────────────────


class ClientPrincipal(BaseModel):
    """Decoded JWT payload for an OAuth client request.

    Distinct from ``User`` so endpoints can branch on caller type if needed.
    """

    client_id: str
    scopes: List[str]


def require_scope(*required: OAuthScope):
    """FastAPI dependency factory that asserts the caller has all listed scopes.

    Usage::

        @router.get("/api/integrations/candidates")
        async def list_candidates(
            principal: ClientPrincipal = Depends(
                require_scope(OAuthScope.candidate_read)
            ),
        ): ...

    Returns 401 for missing/invalid token, 403 for missing scope.
    """
    required_set = {s.value for s in required}

    async def dep(
        creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    ) -> ClientPrincipal:
        if creds is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing_token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            payload = jwt.decode(
                creds.credentials, settings.SECRET_KEY, algorithms=[ALGORITHM]
            )
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        if payload.get("type") != "client":
            # User JWTs hit user-side endpoints; this dependency is only for
            # client_credentials tokens.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token_type"
            )

        granted = set((payload.get("scope") or "").split())
        missing = required_set - granted
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_scope",
                    "required": sorted(required_set),
                    "missing": sorted(missing),
                },
            )

        return ClientPrincipal(
            client_id=str(payload.get("sub", "")),
            scopes=sorted(granted),
        )

    return dep
