"""Tests for TraffitClient — focus on pagination edge cases."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.traffit.client import TraffitClient, TraffitConfig


def _config() -> TraffitConfig:
    return TraffitConfig(
        tenant="test",
        client_id="cid",
        client_secret="secret",
        throttle_rps=0,
    )


def _token_route(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": "tok", "expires_in": 3600, "token_type": "Bearer"}
    )


class _PaginatedHandler:
    """Mock /clients/ where the server caps page_size at 100 even when we ask for 200.

    Mirrors real Traffit behavior on b2bnetwork tenant: 146 total clients,
    page=1 returns 100, page=2 returns 46. X-Result-Page-Size always reports 100.
    """

    def __init__(self, total: int, server_cap: int) -> None:
        self.total = total
        self.server_cap = server_cap
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        page = int(request.headers.get("X-Request-Current-Page", "1"))
        requested_size = int(request.headers.get("X-Request-Page-Size", "200"))
        effective_size = min(requested_size, self.server_cap)
        start = (page - 1) * effective_size
        end = min(start + effective_size, self.total)
        items = [{"id": i + 1} for i in range(start, end)]
        total_pages = (self.total + effective_size - 1) // effective_size
        self.calls.append({"page": page, "size_req": requested_size})
        return httpx.Response(
            200,
            json=items,
            headers={
                "X-Result-Count": str(len(items)),
                "X-Result-Current-Page": str(page),
                "X-Result-Page-Size": str(effective_size),
                "X-Result-Total-Count": str(self.total),
                "X-Result-Total-Pages": str(total_pages),
            },
        )


@pytest.mark.asyncio
async def test_get_paginated_handles_server_capped_page_size() -> None:
    """Regression: when server caps page_size below what we requested, paginator
    must keep going past page 1 (use X-Result-Page-Size, not user-supplied size)."""
    handler = _PaginatedHandler(total=146, server_cap=100)
    transport = httpx.MockTransport(
        lambda req: (
            _token_route(req) if req.url.path == "/oauth2/token" else handler(req)
        )
    )

    config = _config()
    async with TraffitClient(config) as client:
        client._http = httpx.AsyncClient(transport=transport, follow_redirects=True)
        try:
            items = [
                item async for item in client.get_paginated("/clients/", page_size=200)
            ]
        finally:
            await client._http.aclose()
            client._http = None

    assert len(items) == 146
    assert {it["id"] for it in items} == set(range(1, 147))
    assert [c["page"] for c in handler.calls] == [1, 2]


@pytest.mark.asyncio
async def test_get_paginated_stops_when_server_returns_full_total_pages() -> None:
    """Honors X-Result-Total-Pages even when last page is full."""
    handler = _PaginatedHandler(total=200, server_cap=100)
    transport = httpx.MockTransport(
        lambda req: (
            _token_route(req) if req.url.path == "/oauth2/token" else handler(req)
        )
    )
    async with TraffitClient(_config()) as client:
        client._http = httpx.AsyncClient(transport=transport, follow_redirects=True)
        try:
            items = [
                item
                async for item in client.get_paginated("/employees/", page_size=200)
            ]
        finally:
            await client._http.aclose()
            client._http = None

    assert len(items) == 200
    assert [c["page"] for c in handler.calls] == [1, 2]


@pytest.mark.asyncio
async def test_get_paginated_empty_collection() -> None:
    """Empty page=1 yields nothing and stops."""
    handler = _PaginatedHandler(total=0, server_cap=100)
    transport = httpx.MockTransport(
        lambda req: (
            _token_route(req) if req.url.path == "/oauth2/token" else handler(req)
        )
    )
    async with TraffitClient(_config()) as client:
        client._http = httpx.AsyncClient(transport=transport, follow_redirects=True)
        try:
            items = [
                item async for item in client.get_paginated("/clients/", page_size=200)
            ]
        finally:
            await client._http.aclose()
            client._http = None

    assert items == []
    assert len(handler.calls) == 1


@pytest.mark.asyncio
async def test_get_paginated_clamps_oversized_page_size_to_100() -> None:
    """Some Traffit endpoints (/workflows/) return HTTP 400 if page_size > 100.
    Client must clamp to MAX_PAGE_SIZE=100 before sending."""
    seen_sizes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return _token_route(request)
        size = request.headers.get("X-Request-Page-Size")
        seen_sizes.append(size or "")
        return httpx.Response(
            200,
            json=[{"id": 1}, {"id": 2}],
            headers={
                "X-Result-Count": "2",
                "X-Result-Current-Page": "1",
                "X-Result-Page-Size": "100",
                "X-Result-Total-Count": "2",
                "X-Result-Total-Pages": "1",
            },
        )

    transport = httpx.MockTransport(handler)
    async with TraffitClient(_config()) as client:
        client._http = httpx.AsyncClient(transport=transport, follow_redirects=True)
        try:
            items = [
                item
                async for item in client.get_paginated("/workflows/", page_size=200)
            ]
        finally:
            await client._http.aclose()
            client._http = None

    assert items == [{"id": 1}, {"id": 2}]
    assert all(int(s) <= 100 for s in seen_sizes if s)


@pytest.mark.asyncio
async def test_total_count_reads_header() -> None:
    handler = _PaginatedHandler(total=43573, server_cap=100)
    transport = httpx.MockTransport(
        lambda req: (
            _token_route(req) if req.url.path == "/oauth2/token" else handler(req)
        )
    )
    async with TraffitClient(_config()) as client:
        client._http = httpx.AsyncClient(transport=transport, follow_redirects=True)
        try:
            count = await client.total_count("/employees/")
        finally:
            await client._http.aclose()
            client._http = None

    assert count == 43573
