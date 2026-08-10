"""Regressions for two ways the Traffit sync used to lose records SILENTLY —
without an error, without freezing the watermark, and with `checks.traffit`
still reporting `healthy`.

1. A malformed page (bad JSON, or a JSON object where a list was expected) only
   logged and `return`ed on the default code path, which ends the pagination
   generator exactly like a clean last page. The phase saw no error, the
   orchestrator stamped `last_status="ok"` and ADVANCED the delta watermark, so
   everything behind that page was dropped — and once the delta window moved
   past it, unrecoverably. It affected every paginated phase: candidates, jobs,
   pipelines, activities, sources and the master-data phases.

2. The informational `total_count` probe gated nine phases: a single flaky count
   call returned from the phase before importing anything, so a whole night's
   candidates/jobs/pipelines simply did not arrive. The recorded error carried no
   `ext=`/`id=`, making it unattributable — `_blocking_errors` treats those as
   blocking and the quarantine has no row to park, so a persistently failing
   probe froze the watermark for good while importing nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

import app.services.traffit.importer as importer_mod
from app.services.traffit.client import TraffitClient, TraffitConfig
from app.services.traffit.importer import TraffitImporter

UTC = timezone.utc


def _config() -> TraffitConfig:
    return TraffitConfig(
        tenant="test", client_id="cid", client_secret="secret", throttle_rps=0
    )


def _preauth(client: TraffitClient) -> None:
    client._token = "tok"
    client._token_expires_at = datetime.now(UTC) + timedelta(hours=1)


def _ok_page(items):
    # Total-pages header is authoritative for the stop decision, so a full first
    # page keeps pagination going to page 2 (where the fault is planted).
    return httpx.Response(
        200, json=items, headers={"X-Result-Total-Pages": "2"}
    )


class _PageHandler:
    """Page 1 is a normal full page; page 2 carries the planted fault."""

    def __init__(self, bad: httpx.Response):
        self.bad = bad
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls == 1:
            return _ok_page([{"id": 1}, {"id": 2}])
        return self.bad


async def _drain(bad: httpx.Response) -> list:
    """Iterate get_pages on the DEFAULT path and collect pages until it stops."""
    handler = _PageHandler(bad)
    seen: list = []
    async with TraffitClient(_config()) as client:
        _preauth(client)
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            # No fallback_on_filter_rejection override — this is exactly how
            # every daily-sync phase calls it.
            async for page_no, items in client.get_pages("/employees/", page_size=2):
                seen.append((page_no, len(items)))
        finally:
            await client._http.aclose()
            client._http = None
    return seen


@pytest.mark.asyncio
async def test_bad_json_page_raises_instead_of_truncating_silently() -> None:
    bad = httpx.Response(200, content=b"{not json", headers={"content-type": "application/json"})

    with pytest.raises(RuntimeError, match="Bad JSON"):
        await _drain(bad)


@pytest.mark.asyncio
async def test_non_list_payload_raises_instead_of_truncating_silently() -> None:
    bad = httpx.Response(200, json={"detail": "unexpected object"})

    with pytest.raises(RuntimeError, match="Expected list"):
        await _drain(bad)


@pytest.mark.asyncio
async def test_pages_before_the_fault_are_still_yielded() -> None:
    """The failure must surface as an exception, not as a quiet short read —
    but records already fetched are still handed to the importer, which commits
    them; the raised error is what freezes the watermark so the tail is
    re-covered next run."""
    bad = httpx.Response(200, json={"detail": "boom"})
    seen: list = []
    handler = _PageHandler(bad)
    async with TraffitClient(_config()) as client:
        _preauth(client)
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(RuntimeError):
                async for page_no, items in client.get_pages(
                    "/employees/", page_size=2
                ):
                    seen.append((page_no, len(items)))
        finally:
            await client._http.aclose()
            client._http = None

    assert seen == [(1, 2)]  # page 1 delivered, page 2 raised


# ── total_count probe no longer gates a phase ────────────────────────────────


@pytest.mark.asyncio
async def test_probe_total_returns_zero_instead_of_raising() -> None:
    imp = TraffitImporter.__new__(TraffitImporter)
    imp.traffit = type(
        "T", (), {"total_count": AsyncMock(side_effect=RuntimeError("HTTP 502"))}
    )()

    assert await imp._probe_total("/employees/", "Candidates") == 0


@pytest.mark.asyncio
async def test_probe_total_passes_the_count_through() -> None:
    imp = TraffitImporter.__new__(TraffitImporter)
    imp.traffit = type("T", (), {"total_count": AsyncMock(return_value=49123)})()

    assert await imp._probe_total("/employees/", "Candidates") == 49123


def test_no_phase_still_gates_on_the_total_count_probe() -> None:
    """Structural guard: the old pattern recorded an unattributable
    `total_count failed` error and returned before importing anything. Behaviour
    tests would need every phase's DB fixtures to catch a reintroduction, so
    assert on the source — the marker string is unique to that dead pattern."""
    src = Path(importer_mod.__file__).read_text(encoding="utf-8")

    assert "total_count failed" not in src
    assert "_probe_total" in src
