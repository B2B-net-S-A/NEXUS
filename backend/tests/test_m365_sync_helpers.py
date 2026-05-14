"""Unit tests for `app.services.m365.sync` pure helpers.

Covers Phase 2.4 (delta cursor recovery) and Phase 2.5 (per-folder cursors).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.m365 import M365SyncStatus
from app.services.m365 import sync as sync_mod
from app.services.m365.sync import _is_valid_delta_link, _on_delta_invalidation


# ── _is_valid_delta_link ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url,expected",
    [
        # Real-shape Graph delta link.
        (
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=abc.123",
            True,
        ),
        # Wrong host.
        (
            "https://evil.com/v1.0/me/messages/delta?$deltatoken=abc",
            False,
        ),
        # Right host, no $deltatoken (this is a $skiptoken url — not terminal).
        (
            "https://graph.microsoft.com/v1.0/me/messages/delta?$skiptoken=xyz",
            False,
        ),
        # HTTP not HTTPS.
        (
            "http://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=abc",
            False,
        ),
        # None / empty.
        (None, False),
        ("", False),
        # Total garbage.
        ("not a url at all", False),
    ],
)
def test_is_valid_delta_link(url: str | None, expected: bool) -> None:
    assert _is_valid_delta_link(url) is expected


# ── _on_delta_invalidation ───────────────────────────────────────────────────


def _make_conn(
    *,
    delta_reset_count: int = 0,
    delta_last_reset_at: datetime | None = None,
    delta_token_inbox: str | None = "old-cursor",
    delta_token_sent: str | None = None,
    is_active: bool = True,
):
    """Minimal stand-in for M365Connection with just the fields the helper touches."""
    return SimpleNamespace(
        id=1,
        delta_reset_count=delta_reset_count,
        delta_last_reset_at=delta_last_reset_at,
        delta_token_inbox=delta_token_inbox,
        delta_token_sent=delta_token_sent,
        is_active=is_active,
        last_sync_status=M365SyncStatus.idle,
        last_error=None,
    )


async def test_on_delta_invalidation_first_time_starts_counter_at_one() -> None:
    """Fresh connection (never reset) gets count=1 and the cursor wiped."""
    conn = _make_conn()
    db = SimpleNamespace(commit=AsyncMock())

    await _on_delta_invalidation(db, conn, "Inbox", "delta_token_inbox")

    assert conn.delta_reset_count == 1
    assert conn.delta_last_reset_at is not None
    assert conn.delta_token_inbox is None  # cursor wiped
    assert conn.is_active is True  # one reset is normal — don't deactivate
    db.commit.assert_awaited_once()


async def test_on_delta_invalidation_within_24h_increments() -> None:
    """A second 410 within 24h bumps the existing counter rather than resetting."""
    last = datetime.now(timezone.utc) - timedelta(hours=2)
    conn = _make_conn(delta_reset_count=2, delta_last_reset_at=last)
    db = SimpleNamespace(commit=AsyncMock())

    await _on_delta_invalidation(db, conn, "Inbox", "delta_token_inbox")

    assert conn.delta_reset_count == 3
    assert conn.is_active is True  # still under the threshold


async def test_on_delta_invalidation_outside_24h_resets_to_one() -> None:
    """If the previous reset was >24h ago the count starts fresh at 1."""
    last = datetime.now(timezone.utc) - timedelta(hours=30)
    conn = _make_conn(delta_reset_count=2, delta_last_reset_at=last)
    db = SimpleNamespace(commit=AsyncMock())

    await _on_delta_invalidation(db, conn, "Inbox", "delta_token_inbox")

    assert conn.delta_reset_count == 1


async def test_on_delta_invalidation_exceeds_threshold_deactivates() -> None:
    """The 4th reset within 24h deactivates the connection."""
    last = datetime.now(timezone.utc) - timedelta(hours=1)
    conn = _make_conn(delta_reset_count=3, delta_last_reset_at=last)
    db = SimpleNamespace(commit=AsyncMock())

    await _on_delta_invalidation(db, conn, "SentItems", "delta_token_sent")

    assert conn.delta_reset_count == 4
    assert conn.is_active is False
    assert conn.last_sync_status == M365SyncStatus.error
    assert "SentItems" in (conn.last_error or "")
    assert "4×" in (conn.last_error or "") or "4x" in (conn.last_error or "")


async def test_on_delta_invalidation_threshold_constant_sane() -> None:
    """Sanity: the constant is positive and small enough to actually catch
    runaways (a 100-reset threshold would be useless)."""
    assert 1 <= sync_mod._MAX_DELTA_RESETS_PER_24H <= 10
