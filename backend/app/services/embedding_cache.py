"""Postgres content-hash cache for Voyage embeddings (Item 4 modernization).

Read-through cache: compute SHA-256(model || input_type || text), look up the
row, return its embedding on hit. On miss, the caller computes the embedding
and writes it back via `store()`.

Why Postgres (not Redis):
- We already run Postgres in prod; adding Redis means another service to
  monitor on a single Hetzner CAX21.
- Cache is medium-volume (~50K rows after full reembed, growing slowly). PG
  with a primary key + (model, last_hit_at) index handles it for years.
- Reuses the read-through pattern from `match_score_cache.py:110`.

Storage: 1024 floats × 4 bytes = 4096 bytes/embedding. 50K rows ≈ 200MB.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def cache_key(model: str, input_type: str, text: str) -> str:
    """Stable hash so duplicate text on the same model+input_type collides."""
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"|")
    h.update(input_type.encode("utf-8"))
    h.update(b"|")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def _floats_to_bytes(emb: list[float]) -> bytes:
    """Pack floats as little-endian 4-byte float32 (matches numpy default)."""
    return struct.pack(f"<{len(emb)}f", *emb)


def _bytes_to_floats(b: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"<{dim}f", b))


async def get(
    text: str,
    *,
    model: str,
    input_type: str,
    dim: int,
    db: Optional[AsyncSession] = None,
) -> Optional[list[float]]:
    """Look up a cached embedding. Returns None on miss or any failure."""
    if not text:
        return None
    key = cache_key(model, input_type, text)
    own_session = db is None
    sess = db or AsyncSessionLocal()
    try:
        stmt = select(_table_row(sess)).where(_row_pk(sess) == key)
        result = await sess.execute(stmt)
        row = result.first()
        if row is None:
            return None
        # row is a Row; index into embedding column.
        embedding_bytes = row[0].embedding
        cached_dim = row[0].dim
        if cached_dim != dim:
            return None
        # Bump hit counter best-effort (don't block).
        try:
            await sess.execute(
                update(_table_row(sess))
                .where(_row_pk(sess) == key)
                .values(
                    hits=_table_row(sess).hits + 1,
                    last_hit_at=__import__("sqlalchemy").func.now(),
                )
            )
            await sess.commit()
        except Exception:  # noqa: BLE001
            await sess.rollback()
        return _bytes_to_floats(embedding_bytes, cached_dim)
    except Exception as e:  # noqa: BLE001
        logger.debug("[embedding_cache] get failed: %s", e)
        return None
    finally:
        if own_session:
            await sess.close()


async def store(
    text: str,
    embedding: list[float],
    *,
    model: str,
    input_type: str,
    db: Optional[AsyncSession] = None,
) -> None:
    """Best-effort write. Silent failure — cache is an optimization, not truth."""
    if not text or not embedding:
        return
    key = cache_key(model, input_type, text)
    own_session = db is None
    sess = db or AsyncSessionLocal()
    try:
        Cache = _table_row(sess)
        stmt = (
            pg_insert(Cache)
            .values(
                content_sha256=key,
                model=model,
                input_type=input_type,
                dim=len(embedding),
                embedding=_floats_to_bytes(embedding),
            )
            .on_conflict_do_nothing(index_elements=["content_sha256"])
        )
        await sess.execute(stmt)
        await sess.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("[embedding_cache] store failed: %s", e)
        try:
            await sess.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        if own_session:
            await sess.close()


# Lazy import of the model — avoids circular import (model uses Base).
_CACHE_MODEL = None


def _table_row(_session):
    global _CACHE_MODEL
    if _CACHE_MODEL is None:
        from app.models.embedding_cache import EmbeddingCache

        _CACHE_MODEL = EmbeddingCache
    return _CACHE_MODEL


def _row_pk(_session):
    return _table_row(_session).content_sha256
