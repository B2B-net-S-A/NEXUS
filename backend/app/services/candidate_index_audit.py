"""Read-only ID/content reconciliation; counts alone cannot prove index coverage."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass

from sqlalchemy import select

from app.models.candidate import Candidate
from app.services import embedding_service as embeddings
from app.services.full_candidate_scan import (
    snapshot_candidate_population,
    load_snapshot_batch,
)


@dataclass(frozen=True)
class IndexPoint:
    point_id: str
    content_hash: str | None
    model: str | None
    valid_vector: bool


def describe_point(point) -> IndexPoint:
    vector = point.vector
    valid = (
        isinstance(vector, list)
        and len(vector) == embeddings.VECTOR_SIZE
        and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in vector
        )
        and any(v != 0 for v in vector)
    )
    payload = point.payload if isinstance(point.payload, dict) else {}
    return IndexPoint(
        str(point.id),
        payload.get("content_hash"),
        payload.get("embedding_model"),
        valid,
    )


def text_hash(candidate) -> str | None:
    text = embeddings._build_candidate_text(candidate)
    return hashlib.sha256(text.encode()).hexdigest() if text.strip() else None


def classify(expected_hash: str, point: IndexPoint | None, model: str) -> str:
    if point is None:
        return "missing"
    if not point.valid_vector:
        return "invalid_vector"
    if point.model != model:
        return "wrong_or_unknown_model"
    if point.content_hash != expected_hash:
        return "stale_or_unverified_content"
    return "current"


def fingerprint(manifest: dict) -> str:
    contents = {k: v for k, v in manifest.items() if k != "fingerprint"}
    return hashlib.sha256(
        json.dumps(
            contents, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


async def index_points() -> dict[str, IndexPoint]:
    """Scroll every point, one bounded response at a time; no approximate search."""
    cursor = None
    seen_cursors = set()
    output = {}
    while True:

        def scroll():
            client = embeddings._get_qdrant_client()
            if client is None:
                raise RuntimeError("Index unavailable; coverage is unknown")
            try:
                return client.scroll(
                    collection_name=embeddings._collection(),
                    limit=200,
                    offset=cursor,
                    with_payload=True,
                    with_vectors=True,
                )
            finally:
                client.close()

        points, next_cursor = await embeddings._run_qdrant(scroll)
        for point in points:
            descriptor = describe_point(point)
            if descriptor.point_id in output:
                raise RuntimeError("Index changed during scan: duplicate point")
            output[descriptor.point_id] = descriptor
        if next_cursor is None:
            return output
        if str(next_cursor) in seen_cursors:
            raise RuntimeError("Index cursor did not advance")
        seen_cursors.add(str(next_cursor))
        cursor = next_cursor


async def audit_candidates(db, *, batch_size: int = 100) -> dict:
    if not 1 <= batch_size <= 500:
        raise ValueError("Batch size must be 1–500")
    population = await snapshot_candidate_population(db)
    points = await index_points()
    rows = []
    for start in range(0, len(population), batch_size):
        batch = population[start : start + batch_size]
        candidates = await load_snapshot_batch(db, batch)
        for item in batch:
            candidate = candidates.get(item.candidate_id)
            expected = text_hash(candidate) if candidate is not None else None
            observed = points.get(str(item.candidate_id))
            rows.append(
                {
                    "candidate_id": item.candidate_id,
                    "candidate_version": item.version,
                    "content_hash": expected,
                    "indexed": asdict(observed) if observed else None,
                    "state": classify(
                        expected,
                        points.get(str(item.candidate_id)),
                        embeddings._voyage_model(),
                    )
                    if expected
                    else "changed_during_scan"
                    if candidate is None
                    else "no_indexable_text",
                }
            )
    # SQL content/membership changes must not produce an apparently approved repair plan.
    after = await snapshot_candidate_population(db)
    sql_ids = {str(item.candidate_id) for item in population}
    orphans = sorted(set(points) - sql_ids)
    manifest = {
        "schema": "candidate-index-audit-v1",
        "collection": embeddings._collection(),
        "model": embeddings._voyage_model(),
        "database_unchanged": population == after,
        "counts": dict(sorted(Counter(row["state"] for row in rows).items())),
        "population": len(population),
        "index_points": len(points),
        "orphan_point_ids": orphans,
        "candidates": rows,
    }
    manifest["fingerprint"] = fingerprint(manifest)
    return manifest


async def enqueue_approved_repair(
    db, manifest: dict, expected_fingerprint: str
) -> dict:
    """Queue only missing/stale candidate IDs from the reviewed manifest; no deletes."""
    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex

    if (
        fingerprint(manifest) != expected_fingerprint
        or manifest.get("fingerprint") != expected_fingerprint
    ):
        raise ValueError("Repair manifest fingerprint does not match approval")
    if manifest.get("schema") != "candidate-index-audit-v1" or not manifest.get(
        "database_unchanged"
    ):
        raise ValueError("Audit is incomplete or changed; repeat the dry run")
    if (
        manifest["collection"] != embeddings._collection()
        or manifest["model"] != embeddings._voyage_model()
    ):
        raise ValueError("Index/model configuration changed; repeat the dry run")
    allowed = {
        "missing",
        "invalid_vector",
        "wrong_or_unknown_model",
        "stale_or_unverified_content",
    }
    if any(
        row["state"] not in allowed | {"current", "no_indexable_text"}
        for row in manifest["candidates"]
    ):
        raise ValueError("Audit contains unverified candidates")
    targets = [row for row in manifest["candidates"] if row["state"] in allowed]
    ids = [row["candidate_id"] for row in targets]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate candidate IDs in manifest")
    # Lock exactly the approved rows while checking versions and recording intents.
    for start in range(0, len(targets), 100):
        batch = targets[start : start + 100]
        current = {
            row.id: row
            for row in (
                await db.execute(
                    select(Candidate)
                    .where(Candidate.id.in_([r["candidate_id"] for r in batch]))
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        }
        for item in batch:
            candidate = current.get(item["candidate_id"])
            if (
                candidate is None
                or str(candidate.updated_at) != item["candidate_version"]
                or text_hash(candidate) != item["content_hash"]
            ):
                raise ValueError("Approved candidate changed; repeat the dry run")
    # Caller owns the transaction: validation failure never commits partial work.
    from app.models.index_outbox import IndexOutboxEvent

    queued = already_pending = 0
    for start in range(0, len(targets), 100):
        batch = targets[start : start + 100]
        pending = set(
            (
                await db.execute(
                    select(
                        IndexOutboxEvent.entity_id, IndexOutboxEvent.desired_hash
                    ).where(
                        IndexOutboxEvent.entity_type == CANDIDATE,
                        IndexOutboxEvent.entity_id.in_(
                            [row["candidate_id"] for row in batch]
                        ),
                        IndexOutboxEvent.operation == "upsert",
                        IndexOutboxEvent.status.in_(
                            ["pending", "processing", "failed"]
                        ),
                    )
                )
            ).all()
        )
        new_ids = [
            row["candidate_id"]
            for row in batch
            if (row["candidate_id"], row["content_hash"]) not in pending
        ]
        already_pending += len(batch) - len(new_ids)
        queued += await record_bulk_reindex(db, CANDIDATE, new_ids)
        await db.flush()
    return {
        "queued": queued,
        "already_pending": already_pending,
        "deleted": 0,
        "orphans_reported_only": len(manifest["orphan_point_ids"]),
    }
