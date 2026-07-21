"""M3-CACHE-01 — a score computed during a provider outage is not cached fresh.

The single-pair ``get_cached_or_compute`` wrote the freshly computed breakdown
unconditionally (``stale=False``). The justification tab's ``_compute_breakdown``
catches a Qdrant/Voyage outage, leaves ``similarity=None``, and then called it —
persisting a neutral-semantic (degraded) breakdown as fresh into the SAME shared
``(candidate, job, DEFAULT_PROFILE)`` cache that ``/recommendations`` reads. So a
wrong score computed during an outage lived on long after recovery.

Fix (mirrors ``bulk_get_or_compute``): ``get_cached_or_compute`` gained
``allow_cache_write``, and ``_compute_breakdown`` passes ``False`` only when the
similarity lookup *raised* (a real outage) — not when it merely returned None
(a candidate with no embedding, which caches normally).

Pure unit tests: mocks, no DB. ``get_cached_or_compute`` builds a
``select(CandidateJobMatchScore)`` so the ORM registry must be configured — the
CI suite imports every model; run locally with ``import app.main`` first.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


async def test_get_cached_or_compute_skips_write_when_disallowed(monkeypatch):
    import app.services.match_score_cache as msc

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # cache miss → recompute path

    fake = SimpleNamespace(candidate_id=1, job_id=2, total=50.0, as_dict=lambda: {})

    async def fake_score(*_a, **_k):
        return fake

    upsert = AsyncMock()
    monkeypatch.setattr(msc, "score_candidate_job", fake_score)
    monkeypatch.setattr(msc, "_upsert_breakdown", upsert)

    cand = SimpleNamespace(id=1)
    job = SimpleNamespace(id=2)

    # Degraded mode: computed + returned, but NOT persisted.
    out = await msc.get_cached_or_compute(cand, job, db, allow_cache_write=False)
    assert out is fake
    upsert.assert_not_called()
    db.commit.assert_not_called()

    # Normal mode: persisted.
    await msc.get_cached_or_compute(cand, job, db, allow_cache_write=True)
    upsert.assert_awaited_once()


@pytest.mark.parametrize(
    "raises,expected_allow_write",
    [(True, False), (False, True)],
)
async def test_compute_breakdown_write_gate_follows_outage(
    monkeypatch, raises, expected_allow_write
):
    import app.services.embedding_service as es
    import app.services.match_justification_service as mjs

    monkeypatch.setattr(es, "_build_job_text", lambda _job: "job text")

    if raises:
        async def sim(*_a, **_k):
            raise RuntimeError("qdrant down")
    else:
        async def sim(_text, _ids):
            return {1: 0.83}

    monkeypatch.setattr(es, "similarity_for_candidate_ids", sim)

    captured: dict = {}

    async def fake_gcoc(_cand, _job, _db, **kw):
        captured.update(kw)
        return SimpleNamespace()

    monkeypatch.setattr(mjs, "get_cached_or_compute", fake_gcoc)

    await mjs._compute_breakdown(SimpleNamespace(id=1), SimpleNamespace(id=2), AsyncMock())

    assert captured.get("allow_cache_write") is expected_allow_write, (
        f"outage={raises}: expected allow_cache_write={expected_allow_write}, "
        f"got {captured.get('allow_cache_write')}"
    )
