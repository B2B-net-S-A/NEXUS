"""Backfill planning primitives for versioned-collection rebuilds (plan PR6).

Pure, side-effect-free helpers the backfill runner uses so the gating and resume
logic can be unit-tested without Voyage/Qdrant/disk. Covers the capacity/cost
gate that MUST pass before a full re-embed and the resumable checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass(frozen=True)
class CostEstimate:
    num_points: int
    est_tokens: int
    est_usd: float


def estimate_cost(
    num_points: int,
    *,
    avg_tokens_per_point: int = 400,
    usd_per_million_tokens: float = 0.18,
) -> CostEstimate:
    """Rough Voyage embedding cost for a full backfill of ``num_points``."""
    tokens = max(0, num_points) * max(0, avg_tokens_per_point)
    usd = tokens / 1_000_000 * max(0.0, usd_per_million_tokens)
    return CostEstimate(num_points=num_points, est_tokens=tokens, est_usd=round(usd, 4))


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reasons: tuple[str, ...]


def capacity_gate(
    *,
    estimate: CostEstimate,
    max_usd: Optional[float],
    free_disk_bytes: Optional[int],
    required_disk_bytes: Optional[int],
    disk_safety_margin: float = 1.5,
) -> GateResult:
    """Decide whether a full backfill may proceed.

    Fails (with reasons) when the projected cost exceeds ``max_usd`` or the free
    disk cannot hold the new collection plus a safety margin (active +
    challenger + rollback copy must coexist). ``None`` limits are treated as
    "unconstrained" but recorded so a silent skip can never masquerade as a
    passed gate.
    """
    reasons: list[str] = []
    ok = True

    if max_usd is not None and estimate.est_usd > max_usd:
        ok = False
        reasons.append(f"projected cost ${estimate.est_usd} exceeds budget ${max_usd}")
    elif max_usd is None:
        reasons.append("no cost cap set (unconstrained)")

    if free_disk_bytes is not None and required_disk_bytes is not None:
        needed = required_disk_bytes * disk_safety_margin
        if free_disk_bytes < needed:
            ok = False
            reasons.append(
                f"free disk {free_disk_bytes}B < required {int(needed)}B "
                f"({required_disk_bytes}B × {disk_safety_margin} margin)"
            )
    elif free_disk_bytes is None or required_disk_bytes is None:
        reasons.append("disk headroom not measured (unconstrained)")

    return GateResult(ok=ok, reasons=tuple(reasons))


@dataclass
class Checkpoint:
    """Resumable backfill cursor. ``last_id`` is the highest id fully upserted."""

    entity_type: str
    target_collection: str
    last_id: int = 0
    done_count: int = 0
    failed_ids: list[int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.failed_ids is None:
            self.failed_ids = []

    def advance(self, last_id: int, processed: int) -> None:
        # Never move the cursor backwards — a resumed run must not re-skip work.
        self.last_id = max(self.last_id, last_id)
        self.done_count += processed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        return cls(
            entity_type=data["entity_type"],
            target_collection=data["target_collection"],
            last_id=int(data.get("last_id", 0)),
            done_count=int(data.get("done_count", 0)),
            failed_ids=list(data.get("failed_ids", [])),
        )


def coverage(expected_ids: set[int], indexed_ids: set[int]) -> dict:
    """DB-expected vs indexed set diff — the mandatory freshness measurement."""
    missing = expected_ids - indexed_ids
    orphan = indexed_ids - expected_ids
    denom = len(expected_ids) or 1
    return {
        "expected": len(expected_ids),
        "indexed": len(indexed_ids),
        "missing": len(missing),
        "orphan": len(orphan),
        "coverage_ratio": round((len(expected_ids) - len(missing)) / denom, 4),
        "missing_sample": sorted(missing)[:20],
        "orphan_sample": sorted(orphan)[:20],
    }
