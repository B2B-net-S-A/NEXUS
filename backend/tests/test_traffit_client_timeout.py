"""Stage 1 regression: Traffit client split-timeout + transport retry.

The `candidate_activities` phase pinned prod `checks.traffit=degraded`: a bare
30s httpx timeout on the largest feed raised `httpx.ReadTimeout`, and the
`_get_raw` retry loop only retried on HTTP status — transport exceptions
bypassed it and aborted the whole phase. These tests lock in:
- a split timeout (long read, tight connect) applied by ``__aenter__``, and
- transport-level retries in ``_get_raw`` (backoff, then re-raise).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.traffit.client import TraffitClient, TraffitConfig

UTC = timezone.utc


def _config() -> TraffitConfig:
    return TraffitConfig(
        tenant="test",
        client_id="cid",
        client_secret="secret",
        throttle_rps=0,
    )


def _preauth(client: TraffitClient) -> None:
    """Seed a live token so ``_get_raw`` skips the OAuth round-trip."""
    client._token = "tok"
    client._token_expires_at = datetime.now(UTC) + timedelta(hours=1)


class _FlakyHandler:
    """Raise ReadTimeout for the first ``fail_times`` calls, then return 200."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise httpx.ReadTimeout("simulated timeout", request=request)
        return httpx.Response(200, json=[{"id": 1}])


@pytest.mark.asyncio
async def test_get_raw_retries_transport_error_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())  # skip real backoff waits
    handler = _FlakyHandler(fail_times=2)  # 2 fail, 3rd ok; max_retries=3
    async with TraffitClient(_config()) as client:
        _preauth(client)
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            resp = await client._get_raw(
                "/employees/activities", page=1, page_size=100
            )
        finally:
            await client._http.aclose()
            client._http = None

    assert resp.status_code == 200
    assert handler.calls == 3


@pytest.mark.asyncio
async def test_get_raw_reraises_transport_error_after_exhaustion(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    handler = _FlakyHandler(fail_times=99)  # always fail
    async with TraffitClient(_config()) as client:
        _preauth(client)
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(httpx.TransportError):
                await client._get_raw("/employees/activities", page=1, page_size=100)
        finally:
            await client._http.aclose()
            client._http = None

    assert handler.calls == _config().max_retries + 1  # 4 attempts total


@pytest.mark.asyncio
async def test_from_env_reads_split_timeouts(monkeypatch) -> None:
    monkeypatch.setenv("TRAFFIT_TENANT", "test")
    monkeypatch.setenv("TRAFFIT_CLIENT_ID", "cid")
    monkeypatch.setenv("TRAFFIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TRAFFIT_READ_TIMEOUT_S", "200")
    monkeypatch.setenv("TRAFFIT_CONNECT_TIMEOUT_S", "7")

    config = TraffitConfig.from_env()
    assert config.read_timeout_s == 200.0
    assert config.connect_timeout_s == 7.0

    async with TraffitClient(config) as client:
        timeout = client._http.timeout
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.read == 200.0
        assert timeout.connect == 7.0


@pytest.mark.asyncio
async def test_default_timeouts_are_split_long_read_tight_connect() -> None:
    async with TraffitClient(_config()) as client:
        timeout = client._http.timeout
        assert timeout.read == 180.0
        assert timeout.connect == 10.0
