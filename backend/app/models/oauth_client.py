"""OAuth2 client credentials for machine-to-machine API access.

Inspired by Traffit's "Integracja z API" panel where each external system
(n8n, ChatGPT, Jarvis, ...) gets its own client_id + secret + scoped
permissions. NEXUS becomes the API hub instead of being only a consumer.

Why per-client (not just JWT):
- Audit: per-system call logs are easier to attribute.
- Revocation: disable one integration without invalidating user JWTs.
- Scoping: read-only Zapier client cannot mutate, write client can.

This is the storage; the OAuth2 token endpoint
(``POST /api/oauth/token`` with grant_type=client_credentials) lands in a
follow-up commit. For now we expose CRUD endpoints in Settings → API.

Why hash the secret (not encrypt):
- Secrets are presented to admin once at creation. Storing only the hash
  means a DB leak doesn't expose tokens. Same model as user passwords.
- Trade-off: we cannot show the secret again. Admin must regenerate to
  rotate or recover.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class OAuthScope(str, enum.Enum):
    """Stable scope identifiers for OAuth2 client credentials.

    Names mirror Traffit's scope vocabulary so external systems migrating
    from Traffit can keep similar config. Adding a new scope: extend the
    enum, run a migration, surface in the Settings UI scope-picker.

    Naming convention: ``<resource>:<verb>``. ``read`` is implied by ``write``
    in handlers (a write-scope client can also read).
    """

    candidate_read = "candidate:read"
    candidate_write = "candidate:write"
    job_read = "job:read"
    job_write = "job:write"
    talent_pool_read = "talent_pool:read"
    talent_pool_write = "talent_pool:write"
    client_read = "client:read"
    client_write = "client:write"
    webhook_subscribe = "webhook:subscribe"
    dictionary_read = "dictionary:read"


SCOPE_LABELS: dict[OAuthScope, str] = {
    OAuthScope.candidate_read: "Odczyt kandydatów",
    OAuthScope.candidate_write: "Tworzenie / edycja kandydatów",
    OAuthScope.job_read: "Odczyt rekrutacji",
    OAuthScope.job_write: "Tworzenie / edycja rekrutacji",
    OAuthScope.talent_pool_read: "Odczyt talent pools",
    OAuthScope.talent_pool_write: "Edycja talent pools",
    OAuthScope.client_read: "Odczyt klientów (CRM)",
    OAuthScope.client_write: "Edycja klientów (CRM)",
    OAuthScope.webhook_subscribe: "Subskrypcja webhooków",
    OAuthScope.dictionary_read: "Odczyt słowników",
}


class OAuthClient(Base, TimestampMixin):
    """One OAuth2 client credentials integration.

    Stored fields:
    - ``client_id``: public, opaque uuid string presented at token request.
    - ``secret_hash``: bcrypt of the secret (cleartext shown to admin once).
    - ``scopes``: array of scope identifiers (Postgres ARRAY).
    - ``enabled``: revocable kill-switch — set false to block token issue.
    - ``last_used_at``: stamped by token endpoint each successful exchange.
    """

    __tablename__ = "oauth_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        doc="Display label, e.g. 'n8n Production' or 'Zapier'.",
    )

    client_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        doc="Public identifier (uuid hex). Presented at token request.",
    )

    secret_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Bcrypt hash of the secret. Plain secret is shown once on create.",
    )

    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        default=list,
        server_default="{}",
        doc="Granted OAuth scopes (e.g. ['candidate:read', 'job:write']).",
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Updated on each successful client_credentials exchange.",
    )
