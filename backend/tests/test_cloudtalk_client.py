"""Unit tests for :class:`app.services.cloudtalk.CloudTalkClient`.

No real HTTP — uses httpx.MockTransport to simulate CloudTalk responses.
Exercises Basic Auth header construction, retry/backoff on 429/5xx,
and response normalization.
"""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from app.services.cloudtalk import (
    CloudTalkAuthError,
    CloudTalkClient,
    CloudTalkConfig,
)
from app.services.cloudtalk.client import CloudTalkNotFoundError


def _make_config(**overrides) -> CloudTalkConfig:
    base = {
        "base_url": "https://my.cloudtalk.io/api",
        "api_key_id": "TESTKEY",
        "api_key_secret": "TESTSECRET",
        "timeout_s": 5.0,
        "max_retries": 2,
    }
    base.update(overrides)
    return CloudTalkConfig(**base)


def _make_client_with_handler(config: CloudTalkConfig, handler) -> CloudTalkClient:
    """Build a client and replace its httpx with a MockTransport variant."""
    client = CloudTalkClient(config)
    transport = httpx.MockTransport(handler)
    client._http = httpx.AsyncClient(transport=transport, timeout=config.timeout_s)
    return client


def test_from_settings_raises_when_creds_missing(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CLOUDTALK_API_KEY_ID", "", raising=False)
    monkeypatch.setattr(settings, "CLOUDTALK_API_KEY_SECRET", "", raising=False)
    with pytest.raises(RuntimeError, match="CLOUDTALK_API_KEY_ID"):
        CloudTalkConfig.from_settings()


def test_from_settings_builds_config(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CLOUDTALK_API_KEY_ID", "X", raising=False)
    monkeypatch.setattr(settings, "CLOUDTALK_API_KEY_SECRET", "Y", raising=False)
    monkeypatch.setattr(
        settings, "CLOUDTALK_BASE_URL", "https://eu.cloudtalk.io/api/", raising=False
    )
    cfg = CloudTalkConfig.from_settings()
    assert cfg.api_key_id == "X"
    assert cfg.api_key_secret == "Y"
    assert cfg.base_url == "https://eu.cloudtalk.io/api"  # trailing slash stripped


def test_auth_header_is_basic_base64() -> None:
    cfg = _make_config()
    client = CloudTalkClient(cfg)
    header = client._auth_header()
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode("ascii")
    assert decoded == "TESTKEY:TESTSECRET"


@pytest.mark.asyncio
async def test_ping_returns_true_on_200() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"responseData": {"data": []}})

    client = _make_client_with_handler(_make_config(), handler)
    try:
        assert await client.ping() is True
    finally:
        await client._http.aclose()

    assert "agents/index.json" in seen["url"]
    assert seen["auth"].startswith("Basic ")


@pytest.mark.asyncio
async def test_list_agents_unwraps_responseData_data() -> None:
    payload = {
        "responseData": {
            "data": [
                {"Agent": {"id": 1, "email": "a@x", "firstname": "A"}},
                {"Agent": {"id": 2, "email": "b@x", "firstname": "B"}},
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = _make_client_with_handler(_make_config(), handler)
    try:
        agents = await client.list_agents(limit=2)
    finally:
        await client._http.aclose()

    assert agents == [
        {"id": 1, "email": "a@x", "firstname": "A"},
        {"id": 2, "email": "b@x", "firstname": "B"},
    ]


@pytest.mark.asyncio
async def test_401_raises_auth_error_without_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, text="bad creds")

    client = _make_client_with_handler(_make_config(), handler)
    try:
        with pytest.raises(CloudTalkAuthError):
            await client.ping()
    finally:
        await client._http.aclose()

    # No retry on 401 — auth failures are terminal.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_404_raises_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="gone")

    client = _make_client_with_handler(_make_config(), handler)
    try:
        with pytest.raises(CloudTalkNotFoundError):
            await client.ping()
    finally:
        await client._http.aclose()


@pytest.mark.asyncio
async def test_500_then_200_retries(monkeypatch) -> None:
    # Make backoff sleep instant. Patch the symbol the client module
    # actually uses — avoids recursion if we patch ``asyncio.sleep`` itself.
    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr("app.services.cloudtalk.client.asyncio.sleep", _instant)

    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] < 2:
            return httpx.Response(503, text="boom")
        return httpx.Response(200, json={"responseData": {"data": []}})

    client = _make_client_with_handler(_make_config(max_retries=3), handler)
    try:
        assert await client.ping() is True
    finally:
        await client._http.aclose()

    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_initiate_call_posts_correct_payload() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content) if request.content else None
        return httpx.Response(200, json={"status": 200, "data": {"call_id": 42}})

    client = _make_client_with_handler(_make_config(), handler)
    try:
        result = await client.initiate_call(agent_id=7, phone_number="+48123456789")
    finally:
        await client._http.aclose()

    assert seen["method"] == "POST"
    assert "calls/create.json" in seen["url"]
    assert seen["body"] == {"agent_id": 7, "callee_number": "+48123456789"}
    assert result["data"]["call_id"] == 42
