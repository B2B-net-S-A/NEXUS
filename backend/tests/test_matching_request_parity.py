from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import matching
from app.core.config import settings
from tests.test_scoring_service import make_candidate, make_job


@pytest.mark.asyncio
@pytest.mark.parametrize("location,expected", [(None, [1, 2]), ("Warszawa", [1])])
async def test_compatibility_endpoint_only_filters_explicit_location(
    monkeypatch, location, expected
):
    job = make_job(location="Warszawa", description="Wstęp " * 500 + "Django na końcu")
    candidates = [
        make_candidate(id=1, location="Warszawa"),
        make_candidate(id=2, location=None),
    ]
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: job),
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: candidates)
                ),
            ]
        )
    )
    retrieval = AsyncMock(
        return_value=[{"candidate_id": c.id, "score": 0.8} for c in candidates]
    )
    monkeypatch.setattr(
        "app.services.retrieval_pool.retrieve_candidate_pool", retrieval
    )
    monkeypatch.setattr(settings, "AI_MATCHES_SHARED_ENGINE", True)

    async def gate(db, **kwargs):
        return kwargs["ordered"], {}, {}, 0, kwargs["inputs"]

    async def score(db, **kwargs):
        return [
            {"candidate": {"id": c.id, "location": c.location}, "match_score": 0.8}
            for c in kwargs["ordered"]
        ], False

    monkeypatch.setattr(matching, "_gate_and_dealbreakers", gate)
    monkeypatch.setattr(matching, "_shared_engine_matches", score)
    result = await matching.get_ai_matches(
        job.id, SimpleNamespace(id=1), min_score=0, limit=20, location=location, db=db
    )
    assert [m["candidate"]["id"] for m in result["matches"]] == expected
    assert result["location_filter"] == location
    assert retrieval.call_args.args[1] == matching._build_job_query(job)
    assert "Django na końcu" in retrieval.call_args.args[1]
