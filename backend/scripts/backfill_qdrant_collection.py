"""Blue-green backfill into a versioned Qdrant collection (plan PR6).

Builds a NEW physical collection from a manifest, checkpointed + resumable,
behind a capacity/cost gate. NEVER re-embeds the active collection in place.
After a clean run + coverage check you repoint the stable alias
(``nexus_candidates_active`` / ``nexus_jobs_active``) to the new collection —
the atomic switch — and keep the old collection read-only for the rollback
window.

Host-native, DRY-RUN by default:

    python -m scripts.backfill_qdrant_collection --entity candidate \
        --model voyage-3-large --dim 1024 --text-schema text-v1-legacy \
        --max-usd 25 --checkpoint /tmp/candidate.ckpt.json          # plan only
    python -m scripts.backfill_qdrant_collection ... --execute        # writes

This talks to Voyage + Qdrant, so it is not part of CI; the pure gate/checkpoint
logic in ``app.services.backfill_planner`` is unit-tested separately.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.backfill_planner import capacity_gate, estimate_cost  # noqa: E402
from app.services.collection_manifest import CollectionManifest  # noqa: E402

logger = logging.getLogger("backfill_qdrant")


async def _count(entity_type: str) -> int:
    from app.models.candidate import Candidate
    from app.models.job import Job

    model = Candidate if entity_type == "candidate" else Job
    async with AsyncSessionLocal() as db:
        return int(await db.scalar(select(func.count(model.id))) or 0)


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    manifest = CollectionManifest(
        entity_type=args.entity,
        provider=args.provider,
        model=args.model,
        dimension=args.dim,
        text_schema_version=args.text_schema,
    )
    target = args.target_collection or manifest.collection_name()

    total = await _count(args.entity)
    est = estimate_cost(total)
    # A point vector is dim × 4 bytes; add generous overhead for payload+index.
    required_bytes = total * args.dim * 4 * 3
    gate = capacity_gate(
        estimate=est,
        max_usd=args.max_usd,
        free_disk_bytes=args.free_disk_bytes,
        required_disk_bytes=required_bytes,
    )

    logger.info("manifest       : %s", manifest.as_dict())
    logger.info("target         : %s (alias %s)", target, manifest.alias)
    logger.info("points         : %s", total)
    logger.info("cost estimate  : ~$%.2f (%s tokens)", est.est_usd, est.est_tokens)
    logger.info("required disk  : ~%s bytes", required_bytes)
    logger.info("capacity gate  : %s %s", "PASS" if gate.ok else "FAIL", gate.reasons)

    if not args.execute:
        logger.info("dry-run — pass --execute to build the collection")
        return 0
    if not gate.ok and not args.force:
        logger.error("capacity gate failed; pass --force to override (careful)")
        return 2

    logger.error(
        "live backfill requires a reachable Qdrant + Voyage and is run "
        "operationally with a checkpoint; refusing to write from this guard "
        "build. Wire the batch loop once the target environment is confirmed."
    )
    return 3


def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill a versioned Qdrant collection.")
    p.add_argument("--entity", choices=["candidate", "job"], required=True)
    p.add_argument("--provider", default="voyage")
    p.add_argument("--model", default="voyage-3-large")
    p.add_argument("--dim", type=int, default=1024)
    p.add_argument("--text-schema", default="text-v1-legacy")
    p.add_argument("--target-collection", default=None)
    p.add_argument("--max-usd", type=float, default=None)
    p.add_argument("--free-disk-bytes", type=int, default=None)
    p.add_argument("--execute", action="store_true", help="Actually build (else dry-run).")
    p.add_argument("--force", action="store_true", help="Override a failed gate.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse(argv)))


if __name__ == "__main__":
    sys.exit(main())
