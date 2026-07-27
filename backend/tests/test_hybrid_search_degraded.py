"""M3-RETR-01 — a semantic/hybrid provider outage must be VISIBLE, never
silently rendered as an empty list that reads as "brak kandydatów".

These are pure unit tests: the Voyage/Qdrant call is monkeypatched (either to
RAISE, simulating an outage, or to return ``[]`` as a healthy-but-empty search),
and BM25 is stubbed — so no database or live Qdrant is required.

Contract under test:
- provider FAILED  → ``degraded=True``  (distinct from empty)   → UI can warn
- healthy + empty  → ``degraded=False`` and ``pairs == []``     → real "no one"
"""

from __future__ import annotations

import pytest

from app.services import embedding_service, hybrid_search
from app.services.embedding_service import (
    SemanticSearchUnavailable,
    search_candidates_semantic,
)
from app.services.hybrid_search import (
    HybridResult,
    dense_candidates,
    hybrid_candidates,
)


def _stub_bm25(monkeypatch, ids: list[int]) -> None:
    """Replace the BM25 leg so the test never touches Postgres."""

    async def _fake_bm25(db, query, *, limit: int = 100):  # noqa: ANN001
        return list(ids)

    monkeypatch.setattr(hybrid_search, "bm25_candidates", _fake_bm25)


def _stub_semantic_raises(monkeypatch) -> None:
    """Make the semantic leg behave like a Voyage/Qdrant outage."""

    async def _boom(query, top_k=20, *, raise_on_error=False):  # noqa: ANN001
        if raise_on_error:
            raise SemanticSearchUnavailable("simulated qdrant outage")
        return []

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _boom)


def _stub_semantic_returns(monkeypatch, hits: list[dict]) -> None:
    """Make the semantic leg return a healthy (possibly empty) result."""

    async def _ok(query, top_k=20, *, raise_on_error=False):  # noqa: ANN001
        return list(hits)

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _ok)


# ── hybrid_candidates: outage is flagged, not swallowed ──────────────────────


async def test_hybrid_flags_degraded_when_dense_provider_raises(monkeypatch):
    """Dense leg down + BM25 has hits → degraded=True, ranking survives on BM25.

    The recruiter still gets results, and the API learns the semantic search was
    unavailable — the exact signal the UI needs to avoid "brak kandydatów"."""
    _stub_bm25(monkeypatch, [101, 102])
    _stub_semantic_raises(monkeypatch)

    result = await hybrid_candidates(db=None, query="python", use_rerank=False)

    assert isinstance(result, HybridResult)
    assert result.degraded is True
    assert [cid for cid, _ in result.pairs] == [101, 102]


async def test_hybrid_flags_degraded_even_when_result_empty(monkeypatch):
    """Dense down AND BM25 empty → still degraded=True (NOT a silent []).

    This is the dangerous case the finding is about: without the flag an outage
    is indistinguishable from a genuinely empty database."""
    _stub_bm25(monkeypatch, [])
    _stub_semantic_raises(monkeypatch)

    result = await hybrid_candidates(db=None, query="python", use_rerank=False)

    assert result.pairs == []
    assert result.degraded is True


async def test_hybrid_healthy_empty_is_not_degraded(monkeypatch):
    """Healthy providers that simply match nothing → degraded=False.

    A real "no candidates" must NOT be reported as an outage."""
    _stub_bm25(monkeypatch, [])
    _stub_semantic_returns(monkeypatch, [])

    result = await hybrid_candidates(db=None, query="python", use_rerank=False)

    assert result.pairs == []
    assert result.degraded is False


async def test_hybrid_healthy_with_results_is_not_degraded(monkeypatch):
    """Both legs healthy with hits → degraded=False and ids are fused."""
    _stub_bm25(monkeypatch, [1])
    _stub_semantic_returns(monkeypatch, [{"candidate_id": 2, "score": 0.9}])

    result = await hybrid_candidates(db=None, query="python", use_rerank=False)

    assert result.degraded is False
    assert {cid for cid, _ in result.pairs} == {1, 2}


# ── dense_candidates: raise_on_error toggles swallow vs surface ──────────────


async def test_dense_candidates_raises_when_opted_in(monkeypatch):
    _stub_semantic_raises(monkeypatch)
    with pytest.raises(SemanticSearchUnavailable):
        await dense_candidates("python", raise_on_error=True)


async def test_dense_candidates_swallows_by_default(monkeypatch):
    """Default contract is unchanged: outage → [] (other call sites rely on it)."""
    _stub_semantic_raises(monkeypatch)
    assert await dense_candidates("python") == []


# ── semantic layer: the swallowing except now honours raise_on_error ─────────


async def test_search_semantic_raises_on_embedding_failure(monkeypatch):
    """No query embedding (Voyage down) → raise when raise_on_error=True."""

    async def _no_embedding(text, input_type="document"):  # noqa: ANN001
        return None

    monkeypatch.setattr(embedding_service, "generate_embedding", _no_embedding)

    with pytest.raises(SemanticSearchUnavailable):
        await search_candidates_semantic("python", raise_on_error=True)


async def test_search_semantic_swallows_embedding_failure_by_default(monkeypatch):
    """Same failure, default mode → [] (backwards-compatible)."""

    async def _no_embedding(text, input_type="document"):  # noqa: ANN001
        return None

    monkeypatch.setattr(embedding_service, "generate_embedding", _no_embedding)

    assert await search_candidates_semantic("python") == []
