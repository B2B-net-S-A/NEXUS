"""Tests for versioned-collection manifest + backfill planner (plan PR6).

Pure/DB-free: covers deterministic collection naming, the capacity/cost gate,
resumable checkpoint, and coverage diff.
"""

from __future__ import annotations

from app.services.backfill_planner import (
    Checkpoint,
    capacity_gate,
    coverage,
    estimate_cost,
)
from app.services.collection_manifest import (
    CANDIDATE_ALIAS,
    JOB_ALIAS,
    CollectionManifest,
)


def _m(entity="candidate", **kw) -> CollectionManifest:
    base = dict(
        entity_type=entity,
        provider="voyage",
        model="voyage-3-large",
        dimension=1024,
        text_schema_version="text-v1-legacy",
    )
    base.update(kw)
    return CollectionManifest(**base)


def test_collection_name_is_deterministic_and_sanitised():
    m = _m()
    name = m.collection_name()
    assert name == m.collection_name()  # deterministic
    assert name == (
        "nexus_candidates__voyage_voyage_3_large__d1024__ttext_v1_legacy__eentity_v1"
    )
    # No hyphens or other unsafe chars leak into a Qdrant collection name.
    assert all(c.isalnum() or c == "_" for c in name)


def test_alias_and_base_by_entity():
    assert _m("candidate").alias == CANDIDATE_ALIAS
    assert _m("job").alias == JOB_ALIAS
    assert _m("candidate").base == "nexus_candidates"
    assert _m("job").base == "nexus_jobs"


def test_manifest_matches_only_when_space_identical():
    a = _m()
    assert a.matches(_m())
    assert not a.matches(_m(model="voyage-4"))
    assert not a.matches(_m(dimension=2048))
    assert not a.matches(_m(text_schema_version="text-v2"))


def test_estimate_cost_scales_with_points():
    e = estimate_cost(1_000_000, avg_tokens_per_point=400, usd_per_million_tokens=0.18)
    assert e.est_tokens == 400_000_000
    assert e.est_usd == round(400_000_000 / 1_000_000 * 0.18, 4)
    assert estimate_cost(0).est_usd == 0.0


def test_capacity_gate_passes_within_limits():
    est = estimate_cost(1000)
    g = capacity_gate(
        estimate=est, max_usd=100.0, free_disk_bytes=10**9, required_disk_bytes=10**6
    )
    assert g.ok is True


def test_capacity_gate_fails_over_budget():
    est = estimate_cost(100_000_000)  # large
    g = capacity_gate(
        estimate=est, max_usd=1.0, free_disk_bytes=10**12, required_disk_bytes=10**6
    )
    assert g.ok is False
    assert any("budget" in r for r in g.reasons)


def test_capacity_gate_fails_on_insufficient_disk():
    est = estimate_cost(10)
    g = capacity_gate(
        estimate=est,
        max_usd=100.0,
        free_disk_bytes=100,
        required_disk_bytes=1000,  # ×1.5 margin = 1500 > 100
    )
    assert g.ok is False
    assert any("disk" in r for r in g.reasons)


def test_capacity_gate_records_unconstrained_reasons():
    g = capacity_gate(
        estimate=estimate_cost(10),
        max_usd=None,
        free_disk_bytes=None,
        required_disk_bytes=None,
    )
    # Unconstrained still passes but must not silently hide the missing limits.
    assert g.ok is True
    assert any("unconstrained" in r for r in g.reasons)


def test_checkpoint_advance_never_moves_backwards():
    ck = Checkpoint(entity_type="candidate", target_collection="c")
    ck.advance(last_id=50, processed=50)
    ck.advance(last_id=30, processed=10)  # out-of-order batch
    assert ck.last_id == 50
    assert ck.done_count == 60


def test_checkpoint_round_trip():
    ck = Checkpoint(entity_type="job", target_collection="c", last_id=7, done_count=7)
    ck.failed_ids.append(3)
    restored = Checkpoint.from_dict(ck.to_dict())
    assert restored.last_id == 7
    assert restored.failed_ids == [3]


def test_coverage_diff():
    cov = coverage(expected_ids={1, 2, 3, 4}, indexed_ids={1, 2, 99})
    assert cov["expected"] == 4
    assert cov["indexed"] == 3
    assert cov["missing"] == 2  # 3, 4
    assert cov["orphan"] == 1  # 99
    assert cov["coverage_ratio"] == round(2 / 4, 4)
