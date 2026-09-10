"""Reranker poza pulą kanonicznego scoringu — ta sama odpowiedź, bez kosztu.

Przy `HYBRID_POOL_ENABLED` + `RERANKER_ENABLED` fasada puli woła Voyage rerank
(plus pełny SELECT kandydatów puli), żeby ułożyć pulę w innej KOLEJNOŚCI.
Rekomendacje, `/ai-matches`, propozycje i digest tę kolejność wyrzucają: `score`
w puli to zawsze kosinus, a wynik sortuje kanoniczny fit z `candidate_id` jako
rozstrzygnięciem. Dowód, że `use_rerank=False` niczego w odpowiedzi nie zmienia,
składa się z trzech ogniw — każde ma tu własny test.
"""

import ast
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import canonical_fit
from app.services import embedding_service
from app.services import hybrid_search
from app.services import reranker_service
from app.services import retrieval_pool as rp
from app.services.full_search_measurement import VectorMeasurement
from app.services.hybrid_search import HybridResult
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job

BACKEND = Path(__file__).resolve().parents[1]
CANONICAL_CONSUMERS = (
    "app/api/recommendations.py",
    "app/api/matching.py",
    "app/tasks/compute_proposals.py",
    "app/tasks/match_digest.py",
)


@pytest.mark.asyncio
async def test_use_rerank_is_forwarded_and_defaults_to_the_setting(monkeypatch):
    seen: list = []

    async def fake_hybrid(db, query, *, pool, final_top_k, use_rerank, bm25_query):
        seen.append(use_rerank)
        return HybridResult(pairs=[(7, 0.03)])

    monkeypatch.setattr(hybrid_search, "hybrid_candidates", fake_hybrid)
    monkeypatch.setattr(
        embedding_service,
        "similarity_for_candidate_ids",
        AsyncMock(return_value={7: 0.8}),
    )
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    await rp.retrieve_candidate_pool(object(), "q", top_k=5)
    await rp.retrieve_candidate_pool(object(), "q", top_k=5, use_rerank=False)
    # None = RERANKER_ENABLED decides, exactly as before the parameter existed.
    assert seen == [None, False]


def test_canonical_consumers_skip_the_reranker():
    for rel in CANONICAL_CONSUMERS:
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "retrieve_candidate_pool"
        ]
        assert calls, f"{rel}: no pool call found"
        for call in calls:
            flags = [kw.value for kw in call.keywords if kw.arg == "use_rerank"]
            assert len(flags) == 1 and isinstance(flags[0], ast.Constant), rel
            assert flags[0].value is False, f"{rel}: reranker cost with no effect"


class _RerankDB:
    """Just enough session for the reranker branch's candidate SELECT."""

    def __init__(self, ids):
        self._rows = [SimpleNamespace(id=cid) for cid in ids]

    async def execute(self, _statement):
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: list(self._rows))
        )


@pytest.mark.asyncio
async def test_reranker_changes_only_the_order_never_members_or_scores(monkeypatch):
    """Link 1: membership and per-candidate cosine are the same either way."""
    dense = [{"candidate_id": cid, "score": 0.9 - cid / 100} for cid in (11, 12, 13)]

    async def fake_bm25(db, query, *, limit=100):
        return [14, 12]

    async def fake_dense(query, top_k=20, *, raise_on_error=False):
        return list(dense)

    async def reversed_rerank(query, documents, *, top_k=None):
        return [(i, 1.0 - i / 10) for i in reversed(range(len(documents)))]

    cosines = {11: 0.71, 12: 0.64, 13: 0.52, 14: 0.47}
    monkeypatch.setattr(hybrid_search, "bm25_candidates", fake_bm25)
    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_dense)
    monkeypatch.setattr(embedding_service, "_build_candidate_text", lambda c: "cv")
    monkeypatch.setattr(reranker_service, "rerank_or_passthrough", reversed_rerank)
    monkeypatch.setattr(
        embedding_service,
        "similarity_for_candidate_ids",
        AsyncMock(side_effect=lambda query, ids: {i: cosines[i] for i in ids}),
    )
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)
    db = _RerankDB(cosines)

    reranked = await rp.retrieve_candidate_pool(
        db, "q", top_k=10, bm25_query='"python"', use_rerank=True
    )
    plain = await rp.retrieve_candidate_pool(
        db, "q", top_k=10, bm25_query='"python"', use_rerank=False
    )

    assert [row["candidate_id"] for row in reranked] != [
        row["candidate_id"] for row in plain
    ], "the fake reranker must actually reorder, or this proves nothing"

    def by_id(pool):
        return {row["candidate_id"]: row for row in pool}

    assert by_id(reranked) == by_id(plain)
    assert set(by_id(plain)) == set(cosines)


@pytest.mark.asyncio
async def test_canonical_ranking_does_not_depend_on_pool_order(monkeypatch):
    """Link 2: the shared canonical scorer re-sorts, so pool order is inert."""
    skills = ["Python", "Django", "AWS", "Docker"]
    candidates = [
        make_candidate(id=cid, skills=skills[: 1 + cid % 4], location="Warszawa")
        for cid in range(1, 41)
    ]
    measurements = {
        c.id: VectorMeasurement(round(0.3 + (c.id % 7) / 20, 2), "measured")
        for c in candidates
    }
    measurements[5] = VectorMeasurement(None, "missing_index")
    context = build_request_context(
        make_job(must_skills=["Python", "Django"]), DEFAULT_PROFILE
    )
    monkeypatch.setattr(canonical_fit, "request_vector", AsyncMock(return_value=[1]))

    async def measure(_vector, batch):
        return {c.id: measurements[c.id] for c in batch}

    monkeypatch.setattr(canonical_fit, "measure_candidates", measure)

    in_pool_order = await canonical_fit.score_candidates(None, context, candidates)
    shuffled = list(candidates)
    random.Random(3).shuffle(shuffled)
    in_other_order = await canonical_fit.score_candidates(None, context, shuffled)

    def summary(fits):
        return [(f.breakdown.candidate_id, f.fit_score, f.measurement) for f in fits]

    assert summary(in_pool_order) == summary(in_other_order)
    # Ties exist (same skills, same similarity) — the tie-break is the id.
    scores = [f.fit_score for f in in_pool_order]
    assert len(set(scores)) < len(scores)
