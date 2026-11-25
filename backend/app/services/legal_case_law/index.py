"""Wektory orzeczeń w Qdrancie (``nexus_legal_cases``) — wzór: ``framework_contract_index``.

- Punkt = jedno orzeczenie, id punktu = ``legal_cases.id``, w payloadzie bez
  tekstu (tylko rodzaj sądu). Trafienie bez wiersza w bazie odpada.
- Wektor liczy Voyage (jak umowy ramowe) z sygnatury, sądu, tezy i początku
  uzasadnienia — całe orzeczenie przekracza okno modelu embeddingów.
- **Wektory są dodatkiem.** Bez Voyage albo Qdranta wyszukiwanie idzie po
  słowach; ``embedded_sha256`` mówi, które wiersze trzeba przeliczyć.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from qdrant_client import models as qmodels
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.legal_case_law import LegalCase
from app.services import embedding_service

logger = logging.getLogger(__name__)

# Nazwa NIE zaczyna się od ``nexus_candidates`` (kasowanie kandydata czyści
# każdą taką kolekcję po id punktu).
COLLECTION = "nexus_legal_cases"
PAYLOAD_COURT_TYPE = "court_type"
EMBED_CHARS = 6000
EMBED_BATCH = 64
VECTOR_HITS = 20


def embeddings_enabled() -> bool:
    return bool(getattr(settings, "FRAMEWORK_CONTRACT_EMBEDDINGS_ENABLED", True))


def embed_text(row: Any) -> str:
    parts = [row.signature, row.court, row.summary or "", row.text[:EMBED_CHARS]]
    return "\n".join(part for part in parts if part)


def ensure_collection(client: Any) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION not in existing:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qmodels.VectorParams(
                size=embedding_service.VECTOR_SIZE,
                distance=qmodels.Distance.COSINE,
            ),
        )


def upsert_points(
    client: Any,
    rows: Sequence[tuple[int, str]],
    vectors: Sequence[Sequence[float]],
) -> None:
    ensure_collection(client)
    client.upsert(
        collection_name=COLLECTION,
        points=[
            qmodels.PointStruct(
                id=int(case_id),
                vector=list(vector),
                payload={PAYLOAD_COURT_TYPE: court_type},
            )
            for (case_id, court_type), vector in zip(rows, vectors)
        ],
    )


def search_points(client: Any, vector: Sequence[float], limit: int) -> list[int]:
    hits = client.query_points(
        collection_name=COLLECTION,
        query=list(vector),
        limit=limit,
        with_payload=False,
    ).points
    return [int(hit.id) for hit in hits]


async def index_pending(db: AsyncSession, *, max_rows: int = 500) -> int:
    """Liczy wektory wierszy nowych albo zmienionych; zwraca liczbę zapisanych.

    Commit robi wołający. Awaria Voyage albo Qdranta = 0 i wpis w logu.
    """
    if not embeddings_enabled():
        return 0
    client = embedding_service._get_qdrant_client()
    if client is None:
        return 0
    rows = (
        (
            await db.execute(
                select(LegalCase)
                .where(
                    or_(
                        LegalCase.embedded_sha256.is_(None),
                        LegalCase.embedded_sha256 != LegalCase.content_sha256,
                    )
                )
                .order_by(LegalCase.id)
                .limit(max_rows)
            )
        )
        .scalars()
        .all()
    )
    done = 0
    for start in range(0, len(rows), EMBED_BATCH):
        batch = rows[start : start + EMBED_BATCH]
        vectors = await embedding_service._voyage_embed_batch(
            [embed_text(row) for row in batch], input_type="document"
        )
        if not vectors or any(vector is None for vector in vectors):
            logger.warning(
                "[orzecznictwo] embeddingi niedostępne — zostaje wyszukiwanie po słowach"
            )
            return done
        try:
            await embedding_service._run_qdrant(
                lambda: upsert_points(
                    client,
                    [(row.id, row.court_type) for row in batch],
                    vectors,  # type: ignore[arg-type]
                )
            )
        except Exception as exc:  # noqa: BLE001 — wektory są dodatkiem
            logger.warning("[orzecznictwo] Qdrant niedostępny: %s", type(exc).__name__)
            return done
        for row in batch:
            await db.execute(
                update(LegalCase)
                .where(LegalCase.id == row.id)
                .values(embedded_sha256=row.content_sha256)
            )
        done += len(batch)
    return done


async def vector_ranking(query: str) -> Optional[list[int]]:
    """Id orzeczeń najbliższych pytaniu; ``None`` = wektory niedostępne."""
    if not embeddings_enabled():
        return None
    vector = await embedding_service.generate_embedding(query, input_type="query")
    if vector is None:
        return None
    client = embedding_service._get_qdrant_client()
    if client is None:
        return None
    try:
        return await embedding_service._run_qdrant(
            lambda: search_points(client, vector, VECTOR_HITS)
        )
    except Exception as exc:  # noqa: BLE001 — zostaje wyszukiwanie po słowach
        logger.warning(
            "[orzecznictwo] wyszukiwanie wektorowe nieudane: %s", type(exc).__name__
        )
        return None
