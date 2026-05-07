"""Unit tests for AutentiClient — token caching, retries, error mapping.

Pattern: monkeypatch ``httpx.AsyncClient.request`` (and ``.post`` for the
OAuth token endpoint) with a dataclass stub that returns canned responses.
This is the same approach used by ``test_proxycurl_client.py`` — no respx,
no pytest-httpx dependency.

Coverage target (per plan §6): 90% for ``app/services/autenti/client.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.autenti.client import (
    AutentiAuthError,
    AutentiClient,
    AutentiConfig,
    AutentiError,
    AutentiNotFoundError,
    AutentiRateLimitError,
)


# ── Test stubs ─────────────────────────────────────────────────────────────


@dataclass
class _FakeResponse:
    """Mimics ``httpx.Response`` for the slice of fields we use."""

    status_code: int
    json_payload: Any = None
    text_body: str = ""
    content_bytes: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return self.json_payload

    @property
    def text(self) -> str:
        return self.text_body

    @property
    def content(self) -> bytes:
        return self.content_bytes


def _make_config() -> AutentiConfig:
    return AutentiConfig(
        base_url="https://api.test.autenti.com/api/v2",
        oauth_url="https://api.test.autenti.com/oauth2/token",
        client_id="test-client",
        client_secret="test-secret",
        scope="bpa",
        timeout_s=5.0,
        max_retries=2,
    )


def _token_response(expires_in: int = 3600) -> _FakeResponse:
    return _FakeResponse(
        status_code=200,
        json_payload={
            "access_token": "test-token-abc",
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": "bpa",
        },
    )


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_acquired_then_cached(monkeypatch):
    """First call hits OAuth endpoint; second call reuses cached token."""
    config = _make_config()
    token_calls: list[str] = []
    request_calls: list[tuple[str, str]] = []

    async def fake_post(self, url, **kwargs):
        token_calls.append(url)
        return _token_response()

    async def fake_request(self, method, url, **kwargs):
        request_calls.append((method, url))
        return _FakeResponse(status_code=200, json_payload={"id": "proc-1"})

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)

    async with AutentiClient(config) as client:
        await client.create_document_process({"foo": "bar"})
        await client.create_document_process({"foo": "baz"})

    assert len(token_calls) == 1
    assert token_calls[0] == config.oauth_url
    assert len(request_calls) == 2


@pytest.mark.asyncio
async def test_token_request_failure_raises_auth_error(monkeypatch):
    """OAuth endpoint returns 401 → AutentiAuthError on first request."""
    config = _make_config()

    async def fake_post(self, url, **kwargs):
        return _FakeResponse(status_code=401, text_body="invalid_client")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    async with AutentiClient(config) as client:
        with pytest.raises(AutentiAuthError) as exc_info:
            await client.get_process("proc-1")

    assert exc_info.value.status == 401


@pytest.mark.asyncio
async def test_404_raises_not_found(monkeypatch):
    config = _make_config()

    async def fake_post(self, url, **kwargs):
        return _token_response()

    async def fake_request(self, method, url, **kwargs):
        return _FakeResponse(status_code=404, text_body="not found")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)

    async with AutentiClient(config) as client:
        with pytest.raises(AutentiNotFoundError):
            await client.get_process("missing-proc")


@pytest.mark.asyncio
async def test_401_triggers_one_retoken_then_succeeds(monkeypatch):
    """Mid-flight token expiry: 401 → re-acquire → retry succeeds."""
    config = _make_config()
    post_count = {"value": 0}

    async def fake_post(self, url, **kwargs):
        post_count["value"] += 1
        return _token_response()

    request_count = {"value": 0}

    async def fake_request(self, method, url, **kwargs):
        request_count["value"] += 1
        if request_count["value"] == 1:
            return _FakeResponse(status_code=401, text_body="token expired")
        return _FakeResponse(status_code=200, json_payload={"id": "proc-1"})

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)

    async with AutentiClient(config) as client:
        result = await client.get_process("proc-1")

    # 1 initial token + 1 forced re-acquire after 401
    assert post_count["value"] == 2
    assert request_count["value"] == 2
    assert result == {"id": "proc-1"}


@pytest.mark.asyncio
async def test_persistent_401_raises_auth_error(monkeypatch):
    """If re-acquisition still gets 401, propagate AutentiAuthError."""
    config = _make_config()

    async def fake_post(self, url, **kwargs):
        return _token_response()

    async def fake_request(self, method, url, **kwargs):
        return _FakeResponse(status_code=401, text_body="still bad")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)

    async with AutentiClient(config) as client:
        with pytest.raises(AutentiAuthError):
            await client.get_process("proc-1")


@pytest.mark.asyncio
async def test_retries_on_500_then_succeeds(monkeypatch):
    """5xx is retried with exponential backoff; success after 1 retry."""
    config = _make_config()

    async def fake_post(self, url, **kwargs):
        return _token_response()

    request_count = {"value": 0}

    async def fake_request(self, method, url, **kwargs):
        request_count["value"] += 1
        if request_count["value"] == 1:
            return _FakeResponse(status_code=503, text_body="upstream down")
        return _FakeResponse(status_code=200, json_payload={"id": "proc-1"})

    # Patch sleep to no-op so the test runs instantly.
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    async with AutentiClient(config) as client:
        result = await client.get_process("proc-1")

    assert request_count["value"] == 2
    assert result == {"id": "proc-1"}


@pytest.mark.asyncio
async def test_429_after_max_retries_raises_rate_limit(monkeypatch):
    """All retries exhausted on 429 → AutentiRateLimitError."""
    config = _make_config()  # max_retries=2 → 3 attempts total

    async def fake_post(self, url, **kwargs):
        return _token_response()

    async def fake_request(self, method, url, **kwargs):
        return _FakeResponse(status_code=429, text_body="too many")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    async with AutentiClient(config) as client:
        with pytest.raises(AutentiRateLimitError):
            await client.get_process("proc-1")


@pytest.mark.asyncio
async def test_400_terminal_error(monkeypatch):
    """Non-401/404/429 4xx is terminal — generic AutentiError."""
    config = _make_config()

    async def fake_post(self, url, **kwargs):
        return _token_response()

    async def fake_request(self, method, url, **kwargs):
        return _FakeResponse(status_code=400, text_body="bad payload shape")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)

    async with AutentiClient(config) as client:
        with pytest.raises(AutentiError) as exc_info:
            await client.create_document_process({"bad": "payload"})

    assert exc_info.value.status == 400


@pytest.mark.asyncio
async def test_idempotency_key_propagated(monkeypatch):
    """create_document_process passes Idempotency-Key header through."""
    config = _make_config()
    captured_headers: dict[str, str] = {}

    async def fake_post(self, url, **kwargs):
        return _token_response()

    async def fake_request(self, method, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return _FakeResponse(status_code=200, json_payload={"id": "proc-42"})

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)

    async with AutentiClient(config) as client:
        await client.create_document_process({"parties": []}, idempotency_key="sig-7")

    assert captured_headers.get("Idempotency-Key") == "sig-7"


@pytest.mark.asyncio
async def test_download_signed_file_returns_bytes(monkeypatch):
    """Binary download path uses Accept: application/pdf and returns bytes."""
    config = _make_config()

    async def fake_post(self, url, **kwargs):
        return _token_response()

    captured_headers: dict[str, str] = {}

    async def fake_request(self, method, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return _FakeResponse(status_code=200, content_bytes=b"%PDF-1.7\n...binary...")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)

    async with AutentiClient(config) as client:
        pdf_bytes = await client.download_signed_file("proc-9")

    assert pdf_bytes.startswith(b"%PDF-")
    assert captured_headers.get("Accept") == "application/pdf"


def test_config_from_settings_requires_credentials(monkeypatch):
    """from_settings raises clear error when credentials are blank."""
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "AUTENTI_CLIENT_ID", "")
    monkeypatch.setattr(cfg.settings, "AUTENTI_CLIENT_SECRET", "")

    with pytest.raises(RuntimeError, match="AUTENTI_CLIENT_ID"):
        AutentiConfig.from_settings()


def test_config_from_settings_loads_when_set(monkeypatch):
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "AUTENTI_CLIENT_ID", "id-abc")
    monkeypatch.setattr(cfg.settings, "AUTENTI_CLIENT_SECRET", "secret-xyz")
    monkeypatch.setattr(cfg.settings, "AUTENTI_OAUTH_SCOPE", "bpa")

    config = AutentiConfig.from_settings()

    assert config.client_id == "id-abc"
    assert config.client_secret == "secret-xyz"
    assert config.scope == "bpa"
