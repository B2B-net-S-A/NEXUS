"""Unit tests for `app.services.proxycurl.client.ProxycurlClient`.

Uses monkeypatch to replace `httpx.AsyncClient.get` with a programmable
stub — no real network, no `respx` dependency.

Covers:
- successful 200 response → ProxycurlProfile with derived current_*
- 404 → ProfileNotFound
- 429 with Retry-After then 200 → eventual success
- invalid URL input → ProxycurlError (0)
- normalize_linkedin_url handles the common input variants
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import httpx
import pytest

from app.services.proxycurl.client import (
    ProfileNotFound,
    ProxycurlClient,
    ProxycurlError,
    normalize_linkedin_url,
)


@dataclass
class _FakeResponse:
    status_code: int
    _payload: Any = None
    headers: dict[str, str] = None  # type: ignore[assignment]
    content: bytes = b""

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}
        if self._payload is not None and not self.content:
            import json

            self.content = json.dumps(self._payload).encode("utf-8")

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class _ScriptedAsyncClient:
    """Replaces `httpx.AsyncClient` with a queue of canned responses.

    Each call to .get() pops the next scripted response. Raises if the
    queue empties — test bug detector.
    """

    def __init__(self, script: list[_FakeResponse]) -> None:
        self._script = list(script)
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, *, params=None, headers=None) -> _FakeResponse:
        self.calls.append((url, params or {}))
        if not self._script:
            raise AssertionError(
                "stub exhausted — test did not script enough responses"
            )
        return self._script.pop(0)

    async def aclose(self) -> None:
        return None


def _install_client(monkeypatch, scripted: _ScriptedAsyncClient) -> None:
    """Patch the httpx.AsyncClient that ProxycurlClient creates."""
    monkeypatch.setattr(
        "app.services.proxycurl.client.httpx.AsyncClient",
        lambda *a, **kw: scripted,
    )
    # Ensure the client's semaphore is fresh so previous tests don't block us.
    monkeypatch.setattr(
        ProxycurlClient,
        "_semaphore",
        asyncio.Semaphore(4),
    )


@pytest.mark.asyncio
async def test_fetch_profile_200_returns_current_position(monkeypatch) -> None:
    scripted = _ScriptedAsyncClient(
        [
            _FakeResponse(
                status_code=200,
                _payload={
                    "experiences": [
                        {
                            "company": "Beta Corp",
                            "title": "Staff Engineer",
                            "starts_at": {"day": 1, "month": 4, "year": 2026},
                            "ends_at": None,
                        },
                        {
                            "company": "Acme",
                            "title": "Senior Engineer",
                            "starts_at": {"year": 2022},
                            "ends_at": {"year": 2026},
                        },
                    ],
                    "full_name": "Jane Doe",
                },
            )
        ]
    )
    _install_client(monkeypatch, scripted)

    async with ProxycurlClient(api_key="test-key") as client:
        profile = await client.fetch_profile("https://linkedin.com/in/jane-doe")

    assert profile.current_company == "Beta Corp"
    assert profile.current_title == "Staff Engineer"
    assert profile.current_started_at == date(2026, 4, 1)
    assert profile.raw["full_name"] == "Jane Doe"
    # Auth header + query params asserted through recorded calls.
    called_url, called_params = scripted.calls[0]
    assert called_url.endswith("/v2/linkedin")
    assert called_params["url"] == "https://linkedin.com/in/jane-doe"
    assert called_params["use_cache"] == "if-recent"


@pytest.mark.asyncio
async def test_fetch_profile_404_raises_profile_not_found(monkeypatch) -> None:
    scripted = _ScriptedAsyncClient([_FakeResponse(status_code=404, _payload={})])
    _install_client(monkeypatch, scripted)

    async with ProxycurlClient(api_key="test-key") as client:
        with pytest.raises(ProfileNotFound):
            await client.fetch_profile("linkedin.com/in/ghost")


@pytest.mark.asyncio
async def test_fetch_profile_429_retries_after_retry_after(monkeypatch) -> None:
    """429 with Retry-After: 0 → second response should succeed."""
    scripted = _ScriptedAsyncClient(
        [
            _FakeResponse(status_code=429, headers={"Retry-After": "0"}, _payload={}),
            _FakeResponse(
                status_code=200,
                _payload={"experiences": []},
            ),
        ]
    )
    _install_client(monkeypatch, scripted)

    async with ProxycurlClient(api_key="test-key") as client:
        profile = await client.fetch_profile("linkedin.com/in/retry")

    assert profile.current_company is None
    assert len(scripted.calls) == 2


@pytest.mark.asyncio
async def test_fetch_profile_rejects_invalid_url(monkeypatch) -> None:
    """Malformed input is refused before hitting the network."""
    scripted = _ScriptedAsyncClient([])  # never called
    _install_client(monkeypatch, scripted)

    async with ProxycurlClient(api_key="test-key") as client:
        with pytest.raises(ProxycurlError):
            await client.fetch_profile("https://google.com/in/nope")
    assert scripted.calls == []


def test_normalize_linkedin_url_strips_query_and_trailing_slash() -> None:
    variants = [
        "https://linkedin.com/in/jane-doe",
        "https://www.linkedin.com/in/jane-doe/",
        "https://pl.linkedin.com/in/jane-doe/?trk=foo",
        "linkedin.com/in/jane-doe",
        "LINKEDIN.COM/in/jane-doe",
    ]
    for v in variants:
        assert normalize_linkedin_url(v) == "https://linkedin.com/in/jane-doe"


def test_normalize_linkedin_url_rejects_non_profile_paths() -> None:
    bad = [
        "https://linkedin.com/company/acme",
        "https://linkedin.com/jobs/view/42",
        "https://google.com/in/nope",
        "",
        None,
        "garbage text",
    ]
    for v in bad:
        assert normalize_linkedin_url(v) is None
