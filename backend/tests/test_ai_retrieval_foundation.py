from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.scoring_weights import ScoringWeightProfileCreate, WeightsPayload
from app.services.cc_classifier import CcScore, should_auto_assign
from app.services.hybrid_search import hybrid_candidates
from app.tasks.embedding_index_sync import source_hash


def _cc(score: float, cc_id: int = 1) -> CcScore:
    return CcScore(
        cc_id=cc_id,
        slug=f"cc-{cc_id}",
        name_pl=f"CC {cc_id}",
        score=score,
        keyword_ratio=score,
        embedding_score=score,
        keywords_matched=[],
    )


def test_six_weights_accept_float_tolerance() -> None:
    payload = WeightsPayload(
        semantic=35,
        skills=30,
        salary=12,
        location=8,
        availability=5,
        champion_fit=10,
    )
    assert payload.champion_fit == 10


def test_legacy_five_weights_are_migrated_to_champion_budget() -> None:
    payload = WeightsPayload(
        semantic=40,
        skills=30,
        salary=15,
        location=10,
        availability=5,
    )
    assert payload.champion_fit == 10
    assert sum(payload.model_dump().values()) == pytest.approx(100)
    assert payload.semantic == 36


def test_invalid_weight_sum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WeightsPayload(
            semantic=35,
            skills=30,
            salary=12,
            location=8,
            availability=5,
            champion_fit=9,
        )


def test_profile_cannot_mix_user_and_client_scope() -> None:
    with pytest.raises(ValidationError):
        ScoringWeightProfileCreate(
            name="mixed",
            user_id=1,
            client_id=2,
            weights={
                "semantic": 35,
                "skills": 30,
                "salary": 12,
                "location": 8,
                "availability": 5,
                "champion_fit": 10,
            },
        )


def test_cc_auto_assignment_requires_threshold_and_margin() -> None:
    assert should_auto_assign([_cc(0.80), _cc(0.70, 2)])
    assert not should_auto_assign([_cc(0.79), _cc(0.50, 2)])
    assert not should_auto_assign([_cc(0.85), _cc(0.76, 2)])


def test_embedding_source_hash_is_stable_and_content_bound() -> None:
    assert source_hash("python") == source_hash("python")
    assert source_hash("python") != source_hash("java")


@pytest.mark.asyncio
async def test_hybrid_bm25_only_has_no_standard_match_score(monkeypatch) -> None:
    async def fake_bm25(*args, **kwargs):  # noqa: ARG001
        return [10, 11]

    async def fake_dense(*args, **kwargs):  # noqa: ARG001
        return []

    monkeypatch.setattr("app.services.hybrid_search.bm25_candidates", fake_bm25)
    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", fake_dense
    )
    hits = await hybrid_candidates(
        SimpleNamespace(), "python", pool=10, final_top_k=10, use_rerank=False
    )
    assert hits == [(10, None), (11, None)]


@pytest.mark.asyncio
async def test_hybrid_cosine_is_score_when_rerank_disabled(monkeypatch) -> None:
    async def fake_bm25(*args, **kwargs):  # noqa: ARG001
        return [11]

    async def fake_dense(*args, **kwargs):  # noqa: ARG001
        return [
            {"candidate_id": 10, "score": 0.72},
            {"candidate_id": 11, "score": 0.61},
        ]

    monkeypatch.setattr("app.services.hybrid_search.bm25_candidates", fake_bm25)
    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", fake_dense
    )
    hits = await hybrid_candidates(
        SimpleNamespace(), "python", pool=10, final_top_k=10, use_rerank=False
    )
    assert dict(hits) == {10: 0.72, 11: 0.61}
