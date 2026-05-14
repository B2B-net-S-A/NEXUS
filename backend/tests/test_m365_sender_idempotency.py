"""Unit tests for `app.services.m365.sender._build_idempotency_key`.

Pure function — fingerprints a send intent so a frontend retry or double-click
returns the cached row instead of issuing a second Graph POST. Tests pin the
normalization rules so they can't drift silently.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.m365.sender import _build_idempotency_key


def test_same_inputs_same_minute_yield_same_key() -> None:
    now = datetime(2026, 5, 14, 10, 30, 5, tzinfo=timezone.utc)
    k1 = _build_idempotency_key(
        user_id=42, to=["a@example.com"], cc=[], subject="Interview", now=now
    )
    k2 = _build_idempotency_key(
        user_id=42, to=["a@example.com"], cc=[], subject="Interview", now=now
    )
    assert k1 == k2


def test_minute_boundary_changes_key() -> None:
    """A retry that lands a minute later is treated as a new intent."""
    early = datetime(2026, 5, 14, 10, 30, 59, tzinfo=timezone.utc)
    late = datetime(2026, 5, 14, 10, 31, 0, tzinfo=timezone.utc)
    k_early = _build_idempotency_key(
        user_id=42, to=["a@b.com"], cc=[], subject="X", now=early
    )
    k_late = _build_idempotency_key(
        user_id=42, to=["a@b.com"], cc=[], subject="X", now=late
    )
    assert k_early != k_late


def test_recipient_case_and_order_normalized() -> None:
    """Case- and order-insensitive on recipient list — otherwise two users
    sending the "same" mail with shuffled To: lines would each hit their own
    idempotency slot."""
    now = datetime(2026, 5, 14, 10, 30, 5, tzinfo=timezone.utc)
    k1 = _build_idempotency_key(
        user_id=1, to=["a@b.com", "c@d.com"], cc=[], subject="S", now=now
    )
    k2 = _build_idempotency_key(
        user_id=1, to=["C@D.com", "A@B.com"], cc=[], subject="S", now=now
    )
    assert k1 == k2


def test_cc_affects_key() -> None:
    """Adding a CC must change the fingerprint — otherwise a typo'd cc could
    silently dedupe with the no-cc version of the same send."""
    now = datetime(2026, 5, 14, 10, 30, 5, tzinfo=timezone.utc)
    k1 = _build_idempotency_key(user_id=1, to=["a@b.com"], cc=[], subject="S", now=now)
    k2 = _build_idempotency_key(
        user_id=1, to=["a@b.com"], cc=["m@n.com"], subject="S", now=now
    )
    assert k1 != k2


def test_different_users_different_keys() -> None:
    """Even with identical message content, two users hitting send must NOT
    collide — otherwise user B's send could short-circuit to user A's row."""
    now = datetime(2026, 5, 14, 10, 30, 5, tzinfo=timezone.utc)
    k1 = _build_idempotency_key(user_id=1, to=["a@b.com"], cc=[], subject="S", now=now)
    k2 = _build_idempotency_key(user_id=2, to=["a@b.com"], cc=[], subject="S", now=now)
    assert k1 != k2


def test_subject_whitespace_stripped() -> None:
    now = datetime(2026, 5, 14, 10, 30, 5, tzinfo=timezone.utc)
    k1 = _build_idempotency_key(
        user_id=1, to=["a@b.com"], cc=[], subject=" Hello ", now=now
    )
    k2 = _build_idempotency_key(
        user_id=1, to=["a@b.com"], cc=[], subject="Hello", now=now
    )
    assert k1 == k2


def test_key_is_64_char_hex() -> None:
    now = datetime(2026, 5, 14, 10, 30, 5, tzinfo=timezone.utc)
    k = _build_idempotency_key(user_id=1, to=["a@b.com"], cc=[], subject="X", now=now)
    assert len(k) == 64
    assert all(c in "0123456789abcdef" for c in k)
