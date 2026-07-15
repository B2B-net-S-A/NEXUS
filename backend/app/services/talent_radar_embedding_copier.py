"""
Phase 7a — copy pgvector embeddings from talent-radar to Qdrant (`nexus_candidates`).

Saves ~70k Voyage API calls (cv_embeddings in source are already 1024-dim,
same model family as Nexus).

Strategy:
- For each Nexus candidate with external_source='talent_radar' and a matching
  cv_embeddings.traffit_id, fetch the latest embedding (pick max indexed_at)
- Upsert into Qdrant with id=candidate_id (int), same schema as embedding_service
- Batch by `batch_size` to keep memory bounded
- Idempotent: Qdrant upsert overwrites by point id
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import asyncpg
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.services.embedding_service import candidate_collection_name

logger = logging.getLogger(__name__)


@dataclass
class CopyProgress:
    processed: int = 0
    copied: int = 0
    missing_source: int = 0
    errors: int = 0
    total: int = 0
    error_samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "processed": self.processed,
            "copied": self.copied,
            "missing_source": self.missing_source,
            "errors": self.errors,
            "total": self.total,
            "error_samples": self.error_samples[:20],
        }


def _collection_name() -> str:
    return candidate_collection_name()


class TalentRadarEmbeddingCopier:
    """Copy 1024-dim pgvector embeddings from talent-radar to Qdrant."""

    def __init__(
        self,
        source_dsn: str,
        target_db: AsyncSession,
        batch_size: int = 200,
        dry_run: bool = False,
    ) -> None:
        self.source_dsn = source_dsn
        self.target_db = target_db
        self.batch_size = batch_size
        self.dry_run = dry_run

    async def _count_target(self) -> int:
        row = await self.target_db.execute(
            text(
                "SELECT count(*)::int FROM candidates "
                "WHERE external_source='talent_radar' AND external_id IS NOT NULL"
            )
        )
        return int(row.scalar() or 0)

    async def _fetch_target_batch(self, last_id: int) -> list[Candidate]:
        res = await self.target_db.execute(
            select(Candidate)
            .where(
                Candidate.external_source == "talent_radar",
                Candidate.external_id.isnot(None),
                Candidate.id > last_id,
            )
            .order_by(Candidate.id)
            .limit(self.batch_size)
        )
        return list(res.scalars().all())

    async def _fetch_source_embeddings(
        self,
        source_conn: asyncpg.Connection,
        traffit_ids: list[int],
    ) -> dict[int, list[float]]:
        """Get the most recent embedding per traffit_id as a plain list[float]."""
        if not traffit_ids:
            return {}
        # DISTINCT ON (traffit_id) ORDER BY indexed_at DESC picks the latest
        rows = await source_conn.fetch(
            """
            SELECT DISTINCT ON (traffit_id) traffit_id, embedding::real[]
            FROM public.cv_embeddings
            WHERE traffit_id = ANY($1::int[])
              AND embedding IS NOT NULL
            ORDER BY traffit_id, indexed_at DESC NULLS LAST
            """,
            traffit_ids,
        )
        return {row["traffit_id"]: list(row["embedding"]) for row in rows}

    def _upsert_qdrant(
        self,
        points: list[tuple[int, list[float], dict]],
    ) -> None:
        from qdrant_client.models import PointStruct
        from app.services.qdrant_factory import get_qdrant_client

        client = get_qdrant_client()
        client.upsert(
            collection_name=_collection_name(),
            points=[
                PointStruct(id=pid, vector=vec, payload=payload)
                for pid, vec, payload in points
            ],
        )

    async def run(self) -> AsyncIterator[CopyProgress]:
        progress = CopyProgress()
        source_model = settings.TALENT_RADAR_EMBEDDING_MODEL.strip()
        source_dimension = settings.TALENT_RADAR_EMBEDDING_DIMENSION
        if (
            not settings.TALENT_RADAR_EMBEDDING_COPY_ENABLED
            or source_model != settings.VOYAGE_MODEL
            or source_dimension != settings.EMBEDDING_DIMENSION
        ):
            logger.warning(
                "Talent Radar embedding copy blocked: exact source model/dimension "
                "provenance is not approved"
            )
            yield progress
            return
        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await asyncpg.connect(self.source_dsn, statement_cache_size=0)
            progress.total = await self._count_target()
            yield progress

            last_id = 0
            while True:
                batch = await self._fetch_target_batch(last_id)
                if not batch:
                    break

                # Group by traffit_id
                traffit_ids: list[int] = []
                for c in batch:
                    try:
                        traffit_ids.append(int(c.external_id))
                    except (TypeError, ValueError):
                        progress.errors += 1
                        if len(progress.error_samples) < 20:
                            progress.error_samples.append(
                                f"candidate id={c.id} has non-int external_id={c.external_id!r}"
                            )
                        continue

                try:
                    emb_map = await self._fetch_source_embeddings(conn, traffit_ids)
                except Exception as e:  # noqa: BLE001
                    progress.errors += len(batch)
                    if len(progress.error_samples) < 20:
                        progress.error_samples.append(f"fetch embeddings: {e!r}")
                    last_id = batch[-1].id
                    continue

                points: list[tuple[int, list[float], dict]] = []
                cand_by_traffit: dict[int, Candidate] = {}
                for c in batch:
                    try:
                        tid = int(c.external_id)
                    except (TypeError, ValueError):
                        continue
                    cand_by_traffit[tid] = c

                for tid, vec in emb_map.items():
                    c = cand_by_traffit.get(tid)
                    if not c:
                        continue
                    if len(vec) != 1024:
                        progress.errors += 1
                        if len(progress.error_samples) < 20:
                            progress.error_samples.append(
                                f"traffit_id={tid} has dim={len(vec)} (expected 1024)"
                            )
                        continue
                    points.append(
                        (
                            c.id,
                            vec,
                            {
                                "candidate_id": c.id,
                                "name": f"{c.name} {c.lastname}",
                                "competence_category": c.competence_category or "",
                                "source": "talent_radar_copy",
                            },
                        )
                    )

                # Count missing
                progress.missing_source += len(traffit_ids) - len(emb_map)

                if points and not self.dry_run:
                    try:
                        await asyncio.to_thread(self._upsert_qdrant, points)
                        progress.copied += len(points)

                        # Mark embedding_id on candidate rows
                        ids_to_mark = [p[0] for p in points]
                        await self.target_db.execute(
                            text(
                                "UPDATE candidates SET embedding_id = id::text "
                                "WHERE id = ANY(:ids)"
                            ),
                            {"ids": ids_to_mark},
                        )
                        await self.target_db.commit()
                    except Exception as e:  # noqa: BLE001
                        progress.errors += len(points)
                        if len(progress.error_samples) < 20:
                            progress.error_samples.append(f"qdrant upsert: {e!r}")

                progress.processed += len(batch)
                last_id = batch[-1].id
                yield progress
                await asyncio.sleep(0)
        finally:
            if conn is not None:
                await conn.close()
