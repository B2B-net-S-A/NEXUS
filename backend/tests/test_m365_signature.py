"""Unit tests for `app.services.m365.signature_cache` + sender integration.

Phase 7.7 — Outlook signature pull. Tests pin:

- ``extract_signature`` heuristic (each sigsep flavour, no-marker fallback,
  oversized-tail guard).
- ``get_outlook_signature`` caching: cache hit avoids Graph; TTL expiry
  triggers a fresh fetch; negative results are also cached.
- Graph failure paths: ``GraphRequestError`` and unexpected exceptions both
  resolve to ``None`` (we never want a signature lookup to break a send).
- ``send_new`` integration: when a signature is available the outbound
  payload's body ends with the appended signature; with the kill-switch
  off, no Graph signature lookup happens at all.

The GraphClient is stubbed via ``SimpleNamespace`` + ``AsyncMock`` so the
suite runs in CI without postgres or a real Microsoft account.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services.m365 import sender as sender_mod
from app.services.m365 import signature_cache
from app.services.m365.graph_client import GraphRequestError
from app.services.m365.signature_cache import (
    _clear_cache_for_tests,
    extract_signature,
    get_outlook_signature,
)


# ── extract_signature ────────────────────────────────────────────────────────


def test_extract_signature_br_dash_br() -> None:
    """The most common Outlook sigsep: <br>--<br> right before the block."""
    body = (
        "<p>Hi,</p><p>Please find attached the CV.</p>"
        "<br>--<br>"
        "<p>Jan Kowalski</p><p>Recruiter, b2bnetwork.pl</p>"
    )
    sig = extract_signature(body)
    assert sig is not None
    assert "Jan Kowalski" in sig
    assert "Please find" not in sig


def test_extract_signature_paragraph_dash() -> None:
    """Outlook web emits <p>--</p> in some compose paths."""
    body = "<p>Body text.</p><p>--</p><p>Signature line</p>"
    sig = extract_signature(body)
    assert sig is not None
    assert "Signature line" in sig


def test_extract_signature_div_dash() -> None:
    """Some clients wrap the sigsep in a div."""
    body = "<div>Body</div><div>--</div><div>Sig</div>"
    sig = extract_signature(body)
    assert sig is not None
    assert "Sig" in sig


def test_extract_signature_picks_last_sigsep() -> None:
    """An earlier '--' inside a quoted reply must not steal the match — the
    real signature is at the tail."""
    body = (
        "<p>My reply.</p>"
        "<br>--<br>"
        "<p>Quoted body from someone else.</p>"
        "<br>--<br>"
        "<p>My real signature</p>"
    )
    sig = extract_signature(body)
    assert sig is not None
    assert "My real signature" in sig
    assert "Quoted body" not in sig


def test_extract_signature_no_marker_returns_none() -> None:
    """No sigsep → no signature. We refuse to guess (don't embed body as sig)."""
    body = "<p>Just a body, no separator</p>"
    assert extract_signature(body) is None


def test_extract_signature_empty_body() -> None:
    assert extract_signature("") is None
    assert extract_signature(None) is None  # type: ignore[arg-type]


def test_extract_signature_oversized_tail_rejected() -> None:
    """A tail longer than 8 KB is treated as a misfire (probably embedded body)."""
    huge_tail = "x" * 9000
    body = f"<p>Body</p><br>--<br>{huge_tail}"
    assert extract_signature(body) is None


# ── get_outlook_signature: caching ───────────────────────────────────────────


def _make_gc(
    *, response: dict[str, Any] | None = None, raises: Exception | None = None
):
    """Build a stub GraphClient whose .get() returns or raises as configured."""
    if raises is not None:
        get_mock = AsyncMock(side_effect=raises)
    else:
        get_mock = AsyncMock(return_value=response or {"value": []})
    return SimpleNamespace(get=get_mock)


@pytest.fixture(autouse=True)
def _reset_signature_cache() -> None:
    """Module-level cache leaks between tests — wipe before each."""
    _clear_cache_for_tests()


async def test_cache_hit_avoids_second_graph_call() -> None:
    """Two calls within TTL → exactly one Graph request."""
    sent_response = {
        "value": [
            {
                "body": {
                    "contentType": "html",
                    "content": "<p>Body</p><br>--<br><p>Anna Nowak</p>",
                }
            }
        ]
    }
    gc = _make_gc(response=sent_response)

    sig1 = await get_outlook_signature(gc, user_id=1, mailbox_upn="a@b.com")
    sig2 = await get_outlook_signature(gc, user_id=1, mailbox_upn="a@b.com")

    assert sig1 is not None and "Anna Nowak" in sig1
    assert sig1 == sig2
    assert gc.get.await_count == 1


async def test_cache_miss_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force-expire the entry and the next call must re-fetch."""
    sent_response = {
        "value": [
            {
                "body": {
                    "contentType": "html",
                    "content": "<p>Body</p><br>--<br><p>Sig v1</p>",
                }
            }
        ]
    }
    gc = _make_gc(response=sent_response)

    await get_outlook_signature(gc, user_id=1, mailbox_upn="a@b.com")
    # Manually rewind the expiry into the past.
    key = (1, "a@b.com")
    cached_sig, _ = signature_cache._cache[key]
    signature_cache._cache[key] = (
        cached_sig,
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    await get_outlook_signature(gc, user_id=1, mailbox_upn="a@b.com")
    assert gc.get.await_count == 2


async def test_negative_result_is_cached() -> None:
    """A user with no signature (empty sent items) shouldn't trigger a Graph
    call on every send_new — we cache the None too."""
    gc = _make_gc(response={"value": []})

    sig1 = await get_outlook_signature(gc, user_id=7, mailbox_upn="x@y.com")
    sig2 = await get_outlook_signature(gc, user_id=7, mailbox_upn="x@y.com")

    assert sig1 is None and sig2 is None
    assert gc.get.await_count == 1


async def test_different_users_isolated() -> None:
    """Cache key includes user_id — user B's lookup must not return user A's
    signature even when they share a mailbox alias."""
    gc_a = _make_gc(
        response={
            "value": [
                {
                    "body": {
                        "contentType": "html",
                        "content": "<p>body</p><br>--<br><p>Alice</p>",
                    }
                }
            ]
        }
    )
    gc_b = _make_gc(
        response={
            "value": [
                {
                    "body": {
                        "contentType": "html",
                        "content": "<p>body</p><br>--<br><p>Bob</p>",
                    }
                }
            ]
        }
    )

    sig_a = await get_outlook_signature(gc_a, user_id=1, mailbox_upn="shared@b.com")
    sig_b = await get_outlook_signature(gc_b, user_id=2, mailbox_upn="shared@b.com")

    assert sig_a is not None and "Alice" in sig_a
    assert sig_b is not None and "Bob" in sig_b


# ── get_outlook_signature: failure paths ─────────────────────────────────────


async def test_graph_request_error_returns_none() -> None:
    """A Graph 403/500/etc must NOT propagate — silently skip the signature."""
    gc = _make_gc(raises=GraphRequestError(500, "boom"))

    sig = await get_outlook_signature(gc, user_id=1, mailbox_upn="a@b.com")

    assert sig is None
    assert gc.get.await_count == 1


async def test_unexpected_exception_returns_none() -> None:
    """A bug or network blow-up still resolves to None — sends must not break."""
    gc = _make_gc(raises=RuntimeError("network melted"))

    sig = await get_outlook_signature(gc, user_id=1, mailbox_upn="a@b.com")

    assert sig is None


async def test_plain_text_body_treated_as_no_signature() -> None:
    """Graph returns ``contentType: text`` for some legacy clients; we only
    parse HTML signatures, so plaintext bodies short-circuit to None."""
    gc = _make_gc(
        response={
            "value": [
                {
                    "body": {
                        "contentType": "text",
                        "content": "Body\n--\nSig as plaintext",
                    }
                }
            ]
        }
    )
    sig = await get_outlook_signature(gc, user_id=1, mailbox_upn="a@b.com")
    assert sig is None


# ── sender.send_new() integration ────────────────────────────────────────────


class _FakeAsyncSession:
    """Stand-in for AsyncSession — only the methods send_new() touches."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.scalar = AsyncMock(return_value=None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:  # noqa: D401 — fake
        return None


class _FakeGraphClient:
    """Replaces app.services.m365.sender.GraphClient for integration tests.

    The real GraphClient decrypts tokens in ``__init__`` which would force us
    to wire up the encryption key. Patching the class to this fake lets us
    record what was posted to Graph without touching crypto or network.
    """

    def __init__(self, connection: Any, db: Any) -> None:
        self.connection = connection
        self.posts: list[tuple[str, Any]] = []
        self.gets: list[tuple[str, Any]] = []
        # Default: pretend the user's sent-items has a signature.
        self._signature_response: dict[str, Any] = {
            "value": [
                {
                    "body": {
                        "contentType": "html",
                        "content": (
                            "<p>An earlier body</p><br>--<br>"
                            "<p>Outlook Signature Line</p>"
                        ),
                    }
                }
            ]
        }

    async def __aenter__(self) -> "_FakeGraphClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def get(self, url: str, params: Any = None) -> Any:
        self.gets.append((url, params))
        return self._signature_response

    async def post(self, url: str, json: Any = None) -> Any:
        self.posts.append((url, json))
        # Mimic the draft creation response so send_new() can read .id off it.
        if url == "/me/messages":
            return {
                "id": "FAKE-DRAFT-ID",
                "conversationId": "FAKE-CONV-ID",
                "internetMessageId": "<fake@msg>",
            }
        return {}


def _fake_connection() -> SimpleNamespace:
    """Minimal stand-in for M365Connection — only fields sender touches."""
    return SimpleNamespace(user_id=99, mailbox_upn="me@b2bnet.pl")


async def test_send_new_appends_signature_to_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: a configured user gets their Outlook signature appended."""
    monkeypatch.setattr(sender_mod, "GraphClient", _FakeGraphClient)
    monkeypatch.setattr(settings, "M365_SIGNATURE_INJECTION_ENABLED", True)

    db = _FakeAsyncSession()
    conn = _fake_connection()

    # Capture the fake GraphClient we instantiate so we can inspect posts.
    instances: list[_FakeGraphClient] = []
    real_init = _FakeGraphClient.__init__

    def _capture_init(self: _FakeGraphClient, connection: Any, db_: Any) -> None:
        real_init(self, connection, db_)
        instances.append(self)

    monkeypatch.setattr(_FakeGraphClient, "__init__", _capture_init)

    await sender_mod.send_new(
        db,  # type: ignore[arg-type]
        conn,  # type: ignore[arg-type]
        to=["candidate@example.com"],
        subject="Welcome",
        body_html="<p>Hello there</p>",
    )

    assert len(instances) == 1
    gc = instances[0]
    # First POST: draft creation with the merged body.
    draft_post = next(p for p in gc.posts if p[0] == "/me/messages")
    body_sent = draft_post[1]["body"]["content"]
    assert "Hello there" in body_sent
    assert "Outlook Signature Line" in body_sent
    assert "nexus-signature" in body_sent  # divider class hook is preserved


async def test_send_new_no_signature_leaves_body_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user has no signature, the body is sent verbatim."""
    monkeypatch.setattr(sender_mod, "GraphClient", _FakeGraphClient)
    monkeypatch.setattr(settings, "M365_SIGNATURE_INJECTION_ENABLED", True)

    # Patch the fake to report no sent items.
    original_init = _FakeGraphClient.__init__

    def _empty_sent_items(self: _FakeGraphClient, connection: Any, db_: Any) -> None:
        original_init(self, connection, db_)
        self._signature_response = {"value": []}

    monkeypatch.setattr(_FakeGraphClient, "__init__", _empty_sent_items)

    db = _FakeAsyncSession()
    conn = _fake_connection()

    await sender_mod.send_new(
        db,  # type: ignore[arg-type]
        conn,  # type: ignore[arg-type]
        to=["candidate@example.com"],
        subject="Plain",
        body_html="<p>Body only</p>",
    )

    persisted = db.added[0]
    assert "Body only" in persisted.body_html
    assert "nexus-signature" not in persisted.body_html


async def test_send_new_kill_switch_skips_graph_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With M365_SIGNATURE_INJECTION_ENABLED=False we never call Graph for
    the signature — measured by zero ``GET`` calls on the fake client."""
    monkeypatch.setattr(sender_mod, "GraphClient", _FakeGraphClient)
    monkeypatch.setattr(settings, "M365_SIGNATURE_INJECTION_ENABLED", False)

    instances: list[_FakeGraphClient] = []
    original_init = _FakeGraphClient.__init__

    def _capture(self: _FakeGraphClient, connection: Any, db_: Any) -> None:
        original_init(self, connection, db_)
        instances.append(self)

    monkeypatch.setattr(_FakeGraphClient, "__init__", _capture)

    db = _FakeAsyncSession()
    conn = _fake_connection()

    await sender_mod.send_new(
        db,  # type: ignore[arg-type]
        conn,  # type: ignore[arg-type]
        to=["candidate@example.com"],
        subject="No-sig",
        body_html="<p>No sig wanted</p>",
    )

    assert len(instances) == 1
    gc = instances[0]
    # No GET (we never asked for the signature) — only the draft+send POSTs.
    assert gc.gets == []
    assert all(p[0].startswith("/me/messages") for p in gc.posts)
