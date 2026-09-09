import pytest

from app.services.full_candidate_scan import (
    CandidateEvaluation,
    CandidateSnapshot,
    scan_population,
)


def evaluation(item, score=80, measurement="measured", eligible=True):
    return CandidateEvaluation(
        item.candidate_id, item.version, eligible, score, measurement
    )


@pytest.mark.asyncio
async def test_good_candidate_outside_first_batch_is_found_and_pages_are_stable():
    population = [CandidateSnapshot(i, "v1") for i in range(1, 8)]
    visited = []

    async def evaluate(batch):
        visited.extend(row.candidate_id for row in batch)
        return [
            evaluation(row, score=99 if row.candidate_id == 7 else 80)
            for row in reversed(batch)
        ]

    result = await scan_population(population, evaluate, batch_size=2)
    assert visited == list(range(1, 8))
    assert result.ranking_complete
    first = result.page(limit=3)
    second = result.page(offset=first["next_offset"], limit=3)
    assert [r.candidate_id for r in first["rows"]] == [7, 1, 2]
    assert [r.candidate_id for r in second["rows"]] == [3, 4, 5]
    assert first["total_after_threshold"] == 7


@pytest.mark.asyncio
async def test_provider_failure_is_incomplete_and_later_batches_are_still_checked():
    population = [CandidateSnapshot(i, "v1") for i in range(1, 7)]

    async def evaluate(batch):
        if batch[0].candidate_id == 3:
            raise RuntimeError("provider body must not leak")
        return [evaluation(row) for row in batch]

    result = await scan_population(population, evaluate, batch_size=2)
    assert result.failed_ids == [3, 4]
    assert [r.candidate_id for r in result.evaluated] == [1, 2, 5, 6]
    assert not result.coverage_complete
    assert not result.ranking_complete
    assert result.errors == ["RuntimeError"]


@pytest.mark.asyncio
async def test_missing_index_is_not_a_zero_match_and_survives_threshold():
    population = [CandidateSnapshot(1, "v1")]

    async def evaluate(batch):
        return [evaluation(batch[0], score=None, measurement="missing_index")]

    result = await scan_population(population, evaluate)
    assert result.coverage_complete and not result.ranking_complete
    assert result.page(min_score=90)["total_after_threshold"] == 1
    assert result.counts()["needs_verification"] == 1


@pytest.mark.asyncio
async def test_deleted_or_changed_records_invalidate_coverage():
    population = [CandidateSnapshot(1, "old"), CandidateSnapshot(2, "old")]

    async def evaluate(batch):
        return [evaluation(CandidateSnapshot(1, "new"))]

    result = await scan_population(population, evaluate)
    assert result.failed_ids == [1, 2]
    assert not result.coverage_complete


@pytest.mark.asyncio
async def test_ineligible_candidates_are_accounted_for_without_requiring_vectors():
    async def evaluate(batch):
        return [
            evaluation(
                batch[0], eligible=False, score=None, measurement="missing_index"
            )
        ]

    result = await scan_population([CandidateSnapshot(1, "v1")], evaluate)
    assert result.ranking_complete
    assert result.counts()["excluded"] == 1
    assert result.page()["rows"] == []


def test_unmeasured_score_cannot_masquerade_as_zero():
    with pytest.raises(ValueError):
        CandidateEvaluation(1, "v1", True, 0, "unavailable")


@pytest.mark.parametrize(
    "score,state",
    [
        (None, "measured"),
        (True, "measured"),
        (False, "measured"),
        (None, "not_a_state"),
    ],
)
def test_invalid_measurement_cannot_claim_complete_ranking(score, state):
    with pytest.raises(ValueError):
        CandidateEvaluation(1, "v1", True, score, state)


def test_real_zero_is_measured_but_unknown_is_not():
    measured = CandidateEvaluation(1, "v1", True, 0, "measured")
    unknown = CandidateEvaluation(2, "v1", True, None, "missing_index")
    assert measured.fit_score == 0
    assert unknown.fit_score is None
