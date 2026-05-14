"""Connection lifecycle helpers — kept out of the package __init__ to avoid
circular imports with sync.py / graph_client.py.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.m365 import M365Connection, M365SyncStatus

logger = logging.getLogger(__name__)


async def mark_reconnect_required(
    db: AsyncSession, conn: M365Connection, reason: str
) -> None:
    """Mark a connection as needing a fresh OAuth flow and wipe dead ciphertext.

    Called when the stored tokens cannot be decrypted (encryption key rotated)
    or when Microsoft rejects the refresh token (invalid_grant). The frontend
    surfaces this as a "Reconnect required" banner in Microsoft365Card.
    """
    conn.is_active = False
    conn.last_sync_status = M365SyncStatus.reconnect_required
    conn.last_error = reason
    # Wipe ciphertext — it's unusable and we don't want stale decrypt attempts
    # to keep generating Sentry noise on every sync iteration.
    conn.access_token_ct = ""
    conn.refresh_token_ct = ""
    conn.delta_token_messages = None
    conn.delta_token_events = None
    await db.commit()
    logger.warning(
        "m365 connection %s (user_id=%s) marked reconnect_required: %s",
        conn.id,
        conn.user_id,
        reason,
    )
