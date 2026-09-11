"""Index hygiene an admin reviews first and queues second.

Two defects the read-only audits could only report:

* **Orphan candidate points** — vectors whose candidate row is gone (merges,
  hard deletes from before the delete outbox existed). No read by candidate id
  ever returns them, but ANN search does, and each one still carries whatever
  text was embedded for a person who is no longer in the database.
* **Jobs without a vector or without the stamp** — a job whose point never
  landed (or whose ``embedding_id`` commit failed) silently drops out of
  reverse matching and job similarity.

Same review contract as ``candidate_index_audit`` (audit → repair): the plan is
read-only and fingerprinted; queuing rebuilds it and proceeds only when it is
still exactly what the admin approved. Nothing is deleted or embedded here —
intents go to the durable index outbox. Orphan deletes carry
``ORPHAN_POINT_DELETE`` so the worker re-checks, when it gets to them, that the
candidate row is still absent: the point of an existing candidate is never
deleted by this path.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models.candidate import Candidate
from app.models.index_outbox import IndexOutboxEvent
from app.models.job import Job
from app.services import embedding_service as embeddings
from app.services.candidate_index_audit import fingerprint
from app.services.index_outbox_service import (
    CANDIDATE,
    JOB,
    ORPHAN_POINT_DELETE,
    record_bulk_reindex,
    worker_enabled,
)

SCHEMA = "index-cleanup-v1"
_SCROLL_PAGE = 1000
_CHUNK = 500
# Events the worker will still pick up (failed is retried); dead is final, so a
# new approval may queue a fresh attempt for it.
_OPEN_STATES = ("pending", "processing", "failed")
# What an approval is FOR: exactly the ids it would queue (plus the ids it
# deliberately leaves alone) in exactly these collections. Global totals
# (candidates, points, jobs) stay in the response but out of the fingerprint:
# every unrelated candidate embedded between review and approval moved them,
# so a busy index answered every approval with 409 and the plan could never
# be queued.
_APPROVED_PARTS = (
    "schema",
    "collections",
    "orphan_candidate_point_ids",
    "jobs_to_embed",
    "jobs_without_text",
)


class IndexUnavailable(RuntimeError):
    """The index could not be read completely; no plan can be trusted."""


class CleanupPlanChanged(ValueError):
    """The index or the database moved since the plan was reviewed."""


def _chunks(values: list[int]):
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


async def _point_ids(collection: str) -> tuple[set[int], int]:
    """Every point id of ``collection`` — ids only, no payload, no vectors.

    Returns the integer ids and how many ids are not integers (UUID points no
    entity of ours can own; reported, never acted on).
    """
    ids: set[int] = set()
    unaddressable = 0
    cursor = None
    seen_cursors: set[str] = set()
    while True:

        def scroll(offset=cursor):
            client = embeddings._get_qdrant_client()
            if client is None:
                raise IndexUnavailable("Qdrant client unavailable")
            try:
                return client.scroll(
                    collection_name=collection,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
            finally:
                client.close()

        try:
            points, next_cursor = await embeddings._run_qdrant(scroll)
        except IndexUnavailable:
            raise
        except Exception as exc:
            raise IndexUnavailable(type(exc).__name__) from exc
        for point in points:
            if isinstance(point.id, int) and not isinstance(point.id, bool):
                ids.add(point.id)
            else:
                unaddressable += 1
        if next_cursor is None:
            return ids, unaddressable
        if str(next_cursor) in seen_cursors:
            raise IndexUnavailable("Index cursor did not advance")
        seen_cursors.add(str(next_cursor))
        cursor = next_cursor


async def _split_by_text(db, job_ids: list[int]) -> tuple[list[int], list[int]]:
    """Jobs the embed path can index vs jobs with no text to embed.

    ``embed_job`` refuses an empty document, so queuing those would only mint
    events that fail until they are dead.
    """
    embeddable: list[int] = []
    without_text: list[int] = []
    for chunk in _chunks(job_ids):
        jobs = (await db.execute(select(Job).where(Job.id.in_(chunk)))).scalars()
        for job in jobs:
            text = embeddings._build_job_text(job)
            (embeddable if text.strip() else without_text).append(job.id)
    return sorted(embeddable), sorted(without_text)


async def build_plan(db) -> dict:
    """Read-only: what an approval would queue, with a fingerprint to approve."""
    candidates_collection = embeddings.candidates_collection_name()
    jobs_collection = embeddings.jobs_collection_name()
    # Index FIRST, database second. A candidate embedded during the scroll had
    # its row committed before its point was written, so reading SQL after the
    # scroll can never mistake a brand-new candidate for an orphan.
    candidate_points, candidate_unaddressable = await _point_ids(candidates_collection)
    job_points, job_unaddressable = await _point_ids(jobs_collection)

    candidate_ids = set((await db.execute(select(Candidate.id))).scalars().all())
    orphans = sorted(candidate_points - candidate_ids)

    job_rows = (await db.execute(select(Job.id, Job.embedding_id.is_not(None)))).all()
    missing_point = sorted(job_id for job_id, _ in job_rows if job_id not in job_points)
    unstamped = sorted(job_id for job_id, stamped in job_rows if not stamped)
    embeddable, without_text = await _split_by_text(
        db, sorted(set(missing_point) | set(unstamped))
    )

    plan = {
        "schema": SCHEMA,
        "collections": {"candidates": candidates_collection, "jobs": jobs_collection},
        "orphan_candidate_point_ids": orphans,
        "jobs_to_embed": embeddable,
        "jobs_missing_point": missing_point,
        "jobs_unstamped": unstamped,
        "jobs_without_text": without_text,
        "unaddressable_point_ids": {
            "candidates": candidate_unaddressable,
            "jobs": job_unaddressable,
        },
        "counts": {
            "candidate_points": len(candidate_points),
            "candidates": len(candidate_ids),
            "orphan_candidate_points": len(orphans),
            "job_points": len(job_points),
            "jobs": len(job_rows),
            "jobs_missing_point": len(missing_point),
            "jobs_unstamped": len(unstamped),
            "jobs_to_embed": len(embeddable),
            "jobs_without_text": len(without_text),
        },
    }
    plan["fingerprint"] = fingerprint({key: plan[key] for key in _APPROVED_PARTS})
    return plan


async def _open_event_ids(
    db, entity_type: str, operation: str, ids: list[int]
) -> set[int]:
    found: set[int] = set()
    for chunk in _chunks(ids):
        found.update(
            (
                await db.execute(
                    select(IndexOutboxEvent.entity_id).where(
                        IndexOutboxEvent.entity_type == entity_type,
                        IndexOutboxEvent.operation == operation,
                        IndexOutboxEvent.entity_id.in_(chunk),
                        IndexOutboxEvent.status.in_(_OPEN_STATES),
                    )
                )
            )
            .scalars()
            .all()
        )
    return found


async def enqueue_reviewed_cleanup(
    db, *, expected_fingerprint: str, orphan_count: int, job_count: int
) -> dict:
    """Queue exactly the reviewed plan; the caller owns (and commits) the session.

    Idempotent: an orphan with an open delete event and a job with an open
    upsert event are not queued again, so repeating an approval while the
    worker has not caught up queues nothing new.
    """
    plan = await build_plan(db)
    counts = plan["counts"]
    if (
        plan["fingerprint"] != expected_fingerprint
        or counts["orphan_candidate_points"] != orphan_count
        or counts["jobs_to_embed"] != job_count
    ):
        raise CleanupPlanChanged("Plan changed since review; review it again")

    orphans = plan["orphan_candidate_point_ids"]
    # Re-read in THIS transaction, statement by statement: a row committed after
    # the plan's snapshot must stop its delete here, not only in the worker.
    for chunk in _chunks(orphans):
        alive = (
            (await db.execute(select(Candidate.id).where(Candidate.id.in_(chunk))))
            .scalars()
            .all()
        )
        if alive:
            raise CleanupPlanChanged("A planned orphan has a candidate row again")

    open_deletes = await _open_event_ids(db, CANDIDATE, "delete", orphans)
    new_deletes = [cid for cid in orphans if cid not in open_deletes]
    # Newer than any revision indexed for the old row, so a completed upsert
    # of the deleted candidate can never mark this delete as superseded.
    revision = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    for candidate_id in new_deletes:
        db.add(
            IndexOutboxEvent(
                entity_type=CANDIDATE,
                entity_id=candidate_id,
                entity_revision=revision,
                desired_hash=ORPHAN_POINT_DELETE,
                operation="delete",
                status="pending",
            )
        )

    jobs = plan["jobs_to_embed"]
    open_upserts = await _open_event_ids(db, JOB, "upsert", jobs)
    new_jobs = [job_id for job_id in jobs if job_id not in open_upserts]
    queued_jobs = 0
    for chunk in _chunks(new_jobs):
        queued_jobs += await record_bulk_reindex(db, JOB, chunk)
    await db.flush()
    return {
        "fingerprint": plan["fingerprint"],
        "queued_orphan_deletes": len(new_deletes),
        "orphan_deletes_already_open": len(orphans) - len(new_deletes),
        "queued_job_embeds": queued_jobs,
        "job_embeds_already_open": len(jobs) - len(new_jobs),
        "jobs_without_text": len(plan["jobs_without_text"]),
        # Queued is not done: until the worker drains the outbox nothing moves.
        "worker_enabled": worker_enabled(),
    }
