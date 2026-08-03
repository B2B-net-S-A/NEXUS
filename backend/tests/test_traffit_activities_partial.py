"""Stage 2 regression: a mid-stream fetch timeout in ``import_candidate_activities``
must NOT abort the phase.

Before: an ``httpx.ReadTimeout`` during pagination propagated out of the phase,
the orchestrator's generic ``except`` stamped a bare ``{"error": ...}`` (skipping
the quarantine/summary block), and — because ``promote_notes`` sits after the
loop — notes stopped flowing. After: the phase returns a ``PhaseProgress``
carrying a single *unattributable* error (which freezes the watermark, so the
un-fetched tail is re-covered next run), the partial batch is committed, and
notes are still promoted from what was already fetched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

import app.services.traffit.importer as importer_mod
from app.services.traffit.importer import PhaseProgress, TraffitImporter


class _FakeResult:
    def fetchone(self):
        return (1, True)  # (id, was_insert)


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, *a, **k):
        return _FakeResult()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeTraffit:
    """``total_count`` ok; ``get_paginated`` yields N rows then times out."""

    def __init__(self, yield_count: int) -> None:
        self.yield_count = yield_count

    async def total_count(self, path: str) -> int:
        return 99999

    async def get_paginated(self, path, *, page_size=100, filter_=None, **kw):
        for i in range(self.yield_count):
            yield {"id": i + 1}
        raise httpx.ReadTimeout("simulated mid-stream timeout")


@pytest.mark.asyncio
async def test_activities_timeout_returns_promotes_and_freezes(monkeypatch) -> None:
    imp = TraffitImporter(
        _FakeTraffit(yield_count=600), _FakeDB(), dry_run=False, batch_size=100
    )

    monkeypatch.setattr(
        imp, "_build_candidate_external_id_map", AsyncMock(return_value={})
    )
    monkeypatch.setattr(imp, "build_user_id_map", AsyncMock(return_value={}))
    promote = AsyncMock(return_value=7)
    monkeypatch.setattr(imp, "promote_notes", promote)
    monkeypatch.setattr(
        importer_mod,
        "traffit_activity_to_activity",
        lambda raw, cand_map, user_map: {
            "external_id": str(raw["id"]),
            "entity_type": "candidate",
            "entity_id": 1,
            "action": "note",
            "details": {},
            "user_id": None,
        },
    )
    monkeypatch.setattr(
        importer_mod,
        "backfill_rejection_notes_from_activities",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        importer_mod,
        "backfill_rejection_descriptions_from_activities",
        AsyncMock(return_value=0),
    )

    progress = await imp.import_candidate_activities(since=None)

    # Returned, not raised.
    assert isinstance(progress, PhaseProgress)
    # Exactly the shape the orchestrator freezes on: >=1 error, none attributable.
    assert progress.errors >= 1
    assert progress.error_refs == set()
    # It processed every row it received before the timeout.
    assert progress.processed == 600
    # The partial batch (600 rows > commit_every=500) was committed.
    assert imp.db.commits >= 1
    # Notes were still promoted from the committed rows.
    promote.assert_awaited_once()
    assert progress.notes_promoted == 7


@pytest.mark.asyncio
async def test_activities_total_count_timeout_does_not_skip_import(monkeypatch) -> None:
    """A timed-out ``total_count`` probe must record the error and continue, not
    return early (which used to skip both the import loop and note promotion)."""

    class _ProbeFailTraffit(_FakeTraffit):
        async def total_count(self, path: str) -> int:
            raise httpx.ReadTimeout("probe timeout")

        async def get_paginated(self, path, *, page_size=100, filter_=None, **kw):
            for i in range(3):
                yield {"id": i + 1}

    imp = TraffitImporter(
        _ProbeFailTraffit(yield_count=3), _FakeDB(), dry_run=False, batch_size=100
    )
    monkeypatch.setattr(
        imp, "_build_candidate_external_id_map", AsyncMock(return_value={})
    )
    monkeypatch.setattr(imp, "build_user_id_map", AsyncMock(return_value={}))
    promote = AsyncMock(return_value=2)
    monkeypatch.setattr(imp, "promote_notes", promote)
    monkeypatch.setattr(
        importer_mod,
        "traffit_activity_to_activity",
        lambda raw, cand_map, user_map: {
            "external_id": str(raw["id"]),
            "entity_type": "candidate",
            "entity_id": 1,
            "action": "note",
            "details": {},
            "user_id": None,
        },
    )
    monkeypatch.setattr(
        importer_mod,
        "backfill_rejection_notes_from_activities",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        importer_mod,
        "backfill_rejection_descriptions_from_activities",
        AsyncMock(return_value=0),
    )

    progress = await imp.import_candidate_activities(since=None)

    # Probe failure is logged, not recorded as a blocking error: the loop still
    # ran and promoted notes, and errors==0 means an otherwise-clean run is NOT
    # frozen by an informational probe timeout.
    assert progress.total_source == 0
    assert progress.processed == 3
    assert progress.errors == 0
    promote.assert_awaited_once()
