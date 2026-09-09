"""One-off re-embed: regenerate Qdrant vectors for candidates and jobs.

Used after switching `VOYAGE_MODEL` (e.g. voyage-3 -> voyage-3-large) — old
embeddings live in a different semantic space, so retrieval against the new
query embeddings degrades until we re-embed.

Run:
    # candidates only, dry run (counts what would be processed)
    python -m scripts.reembed_collections --target candidates --dry-run

    # jobs only, with commit
    python -m scripts.reembed_collections --target jobs --commit

    # both, commit, batch size 50, max 200 (testing)
    python -m scripts.reembed_collections --target all --commit --batch 50 --limit 200

    # progress logging every 100 entities
    python -m scripts.reembed_collections --target all --commit --log-every 100

    # close an indexing gap: embed ONLY what Qdrant is missing
    python -m scripts.reembed_collections --target candidates --only-missing --dry-run
    python -m scripts.reembed_collections --target candidates --only-missing --commit --batch 128

    # the other direction: drop vectors of rows that no longer exist
    python -m scripts.reembed_collections --target all --prune-orphans --dry-run
    python -m scripts.reembed_collections --target all --prune-orphans --commit

Note on scope: without ``--only-missing`` this re-embeds EVERY row, which costs
the same Voyage spend as the original import. That is the right thing after a
``VOYAGE_MODEL`` change (old vectors live in a different semantic space) and the
wrong thing when you merely want to fill a gap.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import String, cast, select, update  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.services.embedding_service import (  # noqa: E402
    _build_candidate_text,
    _build_job_text,
    _collection,
    _jobs_collection,
    _voyage_embed_batch,
    _voyage_model,
)

logger = logging.getLogger("reembed_collections")


async def _bulk_upsert_qdrant(collection: str, points: list[dict]) -> int:
    """Bulk upsert points into Qdrant. Returns number upserted."""
    if not points:
        return 0
    from qdrant_client import QdrantClient  # noqa: PLC0415
    from qdrant_client.models import PointStruct  # noqa: PLC0415

    def _upsert():
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        client.upsert(
            collection_name=collection,
            points=[PointStruct(**p) for p in points],
        )

    await asyncio.to_thread(_upsert)
    return len(points)


async def _mark_embedded(model: "type[Candidate] | type[Job]", ids: list[int]) -> None:
    """Set `embedding_id` on rows this script just pushed into Qdrant.

    `embed_candidate` / `embed_job` write this column on every single-row embed
    (as `str(id)` — the column is a copy of the identifier, so its only content
    is "NULL or not", i.e. the predicate "has a vector"). This script upserted
    without it, so a bulk re-embed left the column saying "no vector" for rows
    that had one. Measured on prod 2026-08-07: column 45 317, Qdrant 47 921.

    For jobs the gap is not merely cosmetic — `marketplace_service` and
    `question_suggestions` bail out on `if not job.embedding_id`, so a job
    embedded only by this script silently produced no proposals.

    Best-effort: the vector is already in Qdrant, which is the authority. A
    failed marker must not be reported as a failed embed.
    """
    if not ids:
        return
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(model)
                .where(model.id.in_(ids))
                .values(embedding_id=cast(model.id, String))
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[reembed] vectors upserted but embedding_id not marked for %s ids: %s",
            len(ids),
            exc,
        )


async def _delete_qdrant_points(collection: str, ids: list[int]) -> int:
    """Delete points by id. Returns how many ids were submitted."""
    if not ids:
        return 0
    from qdrant_client import QdrantClient  # noqa: PLC0415
    from qdrant_client.models import PointIdsList  # noqa: PLC0415

    def _delete():
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        for start in range(0, len(ids), 1000):
            client.delete(
                collection_name=collection,
                points_selector=PointIdsList(points=ids[start : start + 1000]),
                wait=True,
            )

    await asyncio.to_thread(_delete)
    return len(ids)


async def _prune_orphans(
    *, entity: str, collection: str, id_column, commit: bool
) -> int:
    """Delete points whose entity no longer exists in the database.

    Right-to-erasure does not reach the vector store today. A candidate vector
    is built from text containing the person's name and up to ~3 000 characters
    of their CV, and the point payload carries `name` outright — so a row that
    is gone from Postgres still has its personal data sitting in Qdrant.

    Measured on prod 2026-08-07: 1 932 orphaned candidate points and 23 job
    points. The likely source is `scripts/merge_duplicate_candidates.py`, which
    merged ~1 884 TalentRadar/Traffit duplicates and deleted the losing rows —
    it re-points every child table and even disables immutability triggers to
    avoid "orphaned PII", but has no notion of the vector store at all.

    Deliberately NOT wired into the main re-embed loop: deleting is not the
    same risk as writing, and an operator should be able to see the count
    before anything is removed. Run with `--dry-run` first.
    """
    indexed = await _qdrant_point_ids(collection)
    async with AsyncSessionLocal() as db:
        live = {row for (row,) in (await db.execute(select(id_column))).all()}

    orphans = sorted(indexed - live)
    logger.info(
        "[prune %s] %s points in Qdrant, %s rows in DB → %s orphaned",
        entity,
        len(indexed),
        len(live),
        len(orphans),
    )
    if not orphans:
        return 0
    if not commit:
        logger.info(
            "[prune %s] DRY RUN — would delete %s points (first 10: %s)",
            entity,
            len(orphans),
            orphans[:10],
        )
        return len(orphans)

    await _delete_qdrant_points(collection, orphans)
    logger.info("[prune %s] deleted %s orphaned points", entity, len(orphans))
    return len(orphans)


async def _qdrant_point_ids(collection: str) -> set[int]:
    """Every point id currently stored in ``collection``.

    Scrolls with vectors and payload switched off, so this pulls ids only —
    the whole candidate collection is ~48k integers, a few MB.

    This, not ``candidates.embedding_id``, is the authority on what is indexed.
    ``_mark_embedded`` now keeps that column in step with what this script
    upserts (it did not, hence the ~2.6k-row disagreement measured on prod
    2026-08-07: column 45 317, Qdrant 47 921), but the column still cannot be
    the authority here: a vector can disappear outside every write path this
    codebase owns — a manual ``delete`` in Qdrant, a rebuilt or renamed
    collection, a restore from an older snapshot. Trusting it would re-embed
    thousands of candidates that already have a vector and miss orphaned points
    entirely. The set difference is only meaningful against Qdrant itself.
    """
    from qdrant_client import QdrantClient  # noqa: PLC0415

    def _scroll() -> set[int]:
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        found: set[int] = set()
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                limit=10_000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            found.update(int(p.id) for p in points)
            if offset is None:
                break
        return found

    try:
        return await asyncio.to_thread(_scroll)
    except Exception as exc:  # noqa: BLE001
        # Fail loudly rather than with a raw traceback: without this the two
        # modes that depend on the scroll (--only-missing, --prune-orphans)
        # crash in a way that reads like a bug in the script rather than
        # "Qdrant is not reachable from here".
        raise RuntimeError(
            f"Cannot read Qdrant collection {collection!r} at "
            f"{settings.QDRANT_HOST}:{settings.QDRANT_PORT} — --only-missing "
            f"and --prune-orphans both need it to compute a set difference. "
            f"Original error: {exc}"
        ) from exc


async def _reembed_candidates(
    *,
    commit: bool,
    batch: int,
    limit: Optional[int],
    log_every: int,
    only_missing: bool = False,
) -> tuple[int, int, int]:
    """Returns (processed, succeeded, failed). Batches Voyage calls (up to 128/req)."""
    processed = succeeded = failed = 0

    # Ids first, rows later, one batch at a time. Loading whole ORM objects up
    # front pulled every `raw_cv_text` on the box into memory at once (~56k rows
    # on prod, 0.5-1.5 GB) — enough to OOM the container before the first Voyage
    # call went out.
    async with AsyncSessionLocal() as db:
        stmt = select(Candidate.id).order_by(Candidate.id.asc())
        # With --only-missing the cap is applied AFTER the set difference, so
        # `--limit 1000` means "a thousand candidates that need a vector".
        # Capping the DB query first would take the thousand lowest ids —
        # nearly all already indexed — and report ~0 work to do.
        if limit is not None and not only_missing:
            stmt = stmt.limit(limit)
        all_ids = [cid for (cid,) in (await db.execute(stmt)).all()]

    if only_missing:
        indexed = await _qdrant_point_ids(_collection())
        before = len(all_ids)
        all_ids = [cid for cid in all_ids if cid not in indexed]
        if limit is not None:
            all_ids = all_ids[:limit]
        logger.info(
            "[reembed candidates] --only-missing: %s of %s lack a vector "
            "(%s already indexed in Qdrant)",
            len(all_ids),
            before,
            len(indexed),
        )

    total = len(all_ids)
    logger.info(
        "Found %s candidates to re-embed (model=%s, batch=%s, commit=%s)",
        total,
        settings.VOYAGE_MODEL,
        batch,
        commit,
    )
    if not commit:
        return total, 0, 0

    for i in range(0, total, batch):
        id_chunk = all_ids[i : i + batch]
        async with AsyncSessionLocal() as db:
            chunk = (
                (
                    await db.execute(
                        select(Candidate)
                        .where(Candidate.id.in_(id_chunk))
                        .order_by(Candidate.id.asc())
                    )
                )
                .scalars()
                .all()
            )
        texts = [_build_candidate_text(c) for c in chunk]
        # Filter out blanks to align with embedding response.
        keep_idx = [j for j, t in enumerate(texts) if t and t.strip()]
        if not keep_idx:
            processed += len(chunk)
            failed += len(chunk)
            continue

        keep_texts = [texts[j] for j in keep_idx]
        embeddings = await _voyage_embed_batch(keep_texts, input_type="document")
        if embeddings is None:
            processed += len(chunk)
            failed += len(chunk)
            logger.warning(
                "[reembed candidates] batch %s-%s failed entirely", i, i + len(chunk)
            )
            continue

        points: list[dict] = []
        for k, j in enumerate(keep_idx):
            emb = embeddings[k] if k < len(embeddings) else None
            c = chunk[j]
            if emb is None:
                failed += 1
                continue
            points.append(
                dict(
                    id=int(c.id),
                    vector=emb,
                    # Bez "name" — parytet z embed_candidate (runda 2): nikt
                    # nie czyta go z payloadu, a PII w indeksie to koszt RODO.
                    payload={
                        "candidate_id": int(c.id),
                        "content_hash": hashlib.sha256(texts[j].encode()).hexdigest(),
                        "embedding_model": _voyage_model(),
                        "competence_category": c.competence_category or "",
                    },
                )
            )

        # Identyfikatory wyliczone PRZED `try`. W środku ta lista byłaby objęta
        # `except`, który raportuje wyłącznie „qdrant upsert failed” — więc błąd
        # budowania punktów (np. brak klucza "id" po refaktorze) zostałby
        # zaksięgowany jako awaria Qdranta i wysłał diagnozę w las.
        point_ids = [int(p["id"]) for p in points]
        try:
            await _bulk_upsert_qdrant(_collection(), points)
            await _mark_embedded(Candidate, point_ids)
            succeeded += len(points)
        except Exception as e:  # noqa: BLE001
            logger.warning("[reembed candidates] qdrant upsert failed: %s", e)
            failed += len(points)

        processed += len(chunk)
        if processed // log_every > (processed - len(chunk)) // log_every:
            logger.info(
                "[reembed candidates] %s/%s (ok=%s, fail=%s)",
                processed,
                total,
                succeeded,
                failed,
            )

    logger.info(
        "[reembed candidates] DONE %s/%s (ok=%s, fail=%s)",
        processed,
        total,
        succeeded,
        failed,
    )
    return processed, succeeded, failed


async def _reembed_jobs(
    *,
    commit: bool,
    batch: int,
    limit: Optional[int],
    log_every: int,
    only_missing: bool = False,
) -> tuple[int, int, int]:
    """Same batched pattern as candidates."""
    processed = succeeded = failed = 0
    async with AsyncSessionLocal() as db:
        stmt = select(Job.id).order_by(Job.id.asc())
        # See `_reembed_candidates` — with --only-missing the cap applies after
        # the diff, so it means "N that need a vector".
        if limit is not None and not only_missing:
            stmt = stmt.limit(limit)
        all_ids = [jid for (jid,) in (await db.execute(stmt)).all()]

    if only_missing:
        indexed = await _qdrant_point_ids(_jobs_collection())
        before = len(all_ids)
        all_ids = [jid for jid in all_ids if jid not in indexed]
        if limit is not None:
            all_ids = all_ids[:limit]
        logger.info(
            "[reembed jobs] --only-missing: %s of %s lack a vector "
            "(%s already indexed in Qdrant)",
            len(all_ids),
            before,
            len(indexed),
        )

    total = len(all_ids)
    logger.info(
        "Found %s jobs to re-embed (model=%s, batch=%s, commit=%s)",
        total,
        settings.VOYAGE_MODEL,
        batch,
        commit,
    )
    if not commit:
        return total, 0, 0

    for i in range(0, total, batch):
        id_chunk = all_ids[i : i + batch]
        async with AsyncSessionLocal() as db:
            chunk = (
                (
                    await db.execute(
                        select(Job).where(Job.id.in_(id_chunk)).order_by(Job.id.asc())
                    )
                )
                .scalars()
                .all()
            )
        texts = [_build_job_text(j) for j in chunk]
        keep_idx = [k for k, t in enumerate(texts) if t and t.strip()]
        if not keep_idx:
            processed += len(chunk)
            failed += len(chunk)
            continue

        keep_texts = [texts[k] for k in keep_idx]
        embeddings = await _voyage_embed_batch(keep_texts, input_type="document")
        if embeddings is None:
            processed += len(chunk)
            failed += len(chunk)
            logger.warning(
                "[reembed jobs] batch %s-%s failed entirely", i, i + len(chunk)
            )
            continue

        points: list[dict] = []
        for k, j in enumerate(keep_idx):
            emb = embeddings[k] if k < len(embeddings) else None
            job = chunk[j]
            if emb is None:
                failed += 1
                continue
            payload = {
                "job_id": int(job.id),
                "title": job.title or "",
                "client_id": job.client_id,
                "industry": job.industry or "",
            }
            train_name = getattr(job, "train_name", None)
            if train_name:
                payload["train_name"] = train_name
            points.append(dict(id=int(job.id), vector=emb, payload=payload))

        # Identyfikatory wyliczone PRZED `try`. W środku ta lista byłaby objęta
        # `except`, który raportuje wyłącznie „qdrant upsert failed” — więc błąd
        # budowania punktów (np. brak klucza "id" po refaktorze) zostałby
        # zaksięgowany jako awaria Qdranta i wysłał diagnozę w las.
        point_ids = [int(p["id"]) for p in points]
        try:
            await _bulk_upsert_qdrant(_jobs_collection(), points)
            await _mark_embedded(Job, point_ids)
            succeeded += len(points)
        except Exception as e:  # noqa: BLE001
            logger.warning("[reembed jobs] qdrant upsert failed: %s", e)
            failed += len(points)

        processed += len(chunk)
        if processed // log_every > (processed - len(chunk)) // log_every:
            logger.info(
                "[reembed jobs] %s/%s (ok=%s, fail=%s)",
                processed,
                total,
                succeeded,
                failed,
            )

    logger.info(
        "[reembed jobs] DONE %s/%s (ok=%s, fail=%s)",
        processed,
        total,
        succeeded,
        failed,
    )
    return processed, succeeded, failed


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--target", choices=["candidates", "jobs", "all"], default="all")
    p.add_argument(
        "--ensure-collection",
        action="store_true",
        help=(
            "utwórz kolekcje z init_qdrant_collection() przed biegiem — "
            "potrzebne przy budowie kolekcji side-by-side "
            "(QDRANT_COLLECTION wskazuje nową, jeszcze nieistniejącą)"
        ),
    )
    p.add_argument(
        "--commit", action="store_true", help="actually call Voyage + upsert Qdrant"
    )
    p.add_argument("--dry-run", action="store_true", help="count only, no API calls")
    p.add_argument(
        "--batch",
        type=int,
        default=128,
        help="Voyage batch size (max 128, default 128 for ~390 calls / 50K candidates)",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="cap number of entities (testing)"
    )
    p.add_argument(
        "--log-every", type=int, default=100, help="progress log every N entities"
    )
    p.add_argument(
        "--only-missing",
        action="store_true",
        help=(
            "Embed only entities absent from Qdrant (set difference against a "
            "scroll of the collection). Use this to close an indexing gap: a "
            "full re-embed of every row costs the same Voyage spend as the "
            "original import and is only needed after a model change."
        ),
    )
    p.add_argument(
        "--prune-orphans",
        action="store_true",
        help=(
            "Delete points whose row no longer exists in the database. These "
            "hold the person's name and CV text after the record was removed, "
            "so erasure never reached them. Runs instead of embedding; honours "
            "--dry-run. Check the reported count before committing."
        ),
    )
    args = p.parse_args(argv)
    if not args.commit and not args.dry_run:
        p.error("must pass --commit or --dry-run")
    if args.commit and args.dry_run:
        p.error("--commit and --dry-run are mutually exclusive")
    return args


async def _main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.ensure_collection:
        from app.services.embedding_service import init_qdrant_collection

        init_qdrant_collection()

    if args.prune_orphans:
        # Runs INSTEAD of embedding: deleting and writing are different risks,
        # and mixing them in one invocation makes the dry-run output ambiguous.
        if args.target in ("candidates", "all"):
            await _prune_orphans(
                entity="candidates",
                collection=_collection(),
                id_column=Candidate.id,
                commit=args.commit,
            )
        if args.target in ("jobs", "all"):
            await _prune_orphans(
                entity="jobs",
                collection=_jobs_collection(),
                id_column=Job.id,
                commit=args.commit,
            )
        return 0

    if args.target in ("candidates", "all"):
        await _reembed_candidates(
            commit=args.commit,
            batch=args.batch,
            limit=args.limit,
            log_every=args.log_every,
            only_missing=args.only_missing,
        )
    if args.target in ("jobs", "all"):
        await _reembed_jobs(
            commit=args.commit,
            batch=args.batch,
            limit=args.limit,
            log_every=args.log_every,
            only_missing=args.only_missing,
        )
    return 0


def main() -> int:
    return asyncio.run(_main(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
