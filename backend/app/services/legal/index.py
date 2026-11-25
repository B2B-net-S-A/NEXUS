"""Wektory przepisów w Qdrancie ``nexus_legal_corpus`` (Voyage).

Wzór: indeks umów ramowych (``framework_contract_index``). Tekst mieszka
w Postgresie (``legal_provisions``), w Qdrancie same wektory: **id punktu =
id przepisu**, w payloadzie tylko ``act_id`` i ``version_id``. Trafienie bez
wiersza w bazie odpada samo. Nazwa kolekcji nie zaczyna się od
``nexus_candidates`` (``delete_candidate_embedding`` kasuje punkty o id
kandydata z każdej takiej kolekcji).

Wektor dostają artykuły, paragrafy i ustępy (głębokość ≤ 1), bez uchylonych
i bardzo krótkich; punkty i litery znajduje ranking po słowach i jednostka
nadrzędna. Wektory są dodatkiem: bez Voyage albo Qdranta działa ranking po
słowach (``corpus.search_provisions``), a wyłącznik
``LEGAL_CORPUS_EMBEDDINGS_ENABLED`` zatrzymuje wysyłkę tekstów do Voyage.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Optional

from qdrant_client import models as qmodels

from app.core.config import settings
from app.services import embedding_service

logger = logging.getLogger(__name__)

COLLECTION = "nexus_legal_corpus"
PAYLOAD_ACT_ID = "act_id"
PAYLOAD_VERSION_ID = "version_id"
EMBED_BATCH = 128
UPSERT_BATCH = 256
VECTOR_HITS = 30
MAX_EMBED_DEPTH = 1
MIN_EMBED_CHARS = 40
EMBED_TEXT_CHARS = 4000


def embeddings_enabled() -> bool:
    return bool(getattr(settings, "LEGAL_CORPUS_EMBEDDINGS_ENABLED", True)) and bool(
        getattr(settings, "VOYAGE_API_KEY", "")
    )


def should_embed(depth: int, text: str, repealed: bool) -> bool:
    return depth <= MAX_EMBED_DEPTH and not repealed and len(text) >= MIN_EMBED_CHARS


def embed_text(short_name: str, ref: str, heading: Optional[str], text: str) -> str:
    head = f"{short_name} {ref}"
    if heading:
        head += f" ({heading})"
    return f"{head}\n{text[:EMBED_TEXT_CHARS]}"


def ensure_collection(client: Any) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION not in existing:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qmodels.VectorParams(
                size=embedding_service.VECTOR_SIZE, distance=qmodels.Distance.COSINE
            ),
        )
    for field_name in (PAYLOAD_ACT_ID, PAYLOAD_VERSION_ID):
        client.create_payload_index(
            collection_name=COLLECTION,
            field_name=field_name,
            field_schema=qmodels.PayloadSchemaType.INTEGER,
        )


def _version_filter(version_ids: Sequence[int]) -> qmodels.Filter:
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key=PAYLOAD_VERSION_ID,
                match=qmodels.MatchAny(any=[int(v) for v in version_ids]),
            )
        ]
    )


def delete_version_points(client: Any, version_id: int) -> None:
    try:
        client.delete(
            collection_name=COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=_version_filter([version_id])
            ),
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if not (
            getattr(exc, "status_code", None) == 404
            or "not found" in message
            or "doesn't exist" in message
        ):
            raise


def upsert_points(
    client: Any,
    act_id: int,
    version_id: int,
    provision_ids: Sequence[int],
    vectors: Sequence[Sequence[float]],
) -> None:
    ensure_collection(client)
    points = [
        qmodels.PointStruct(
            id=int(pid),
            vector=list(vector),
            payload={PAYLOAD_ACT_ID: int(act_id), PAYLOAD_VERSION_ID: int(version_id)},
        )
        for pid, vector in zip(provision_ids, vectors)
    ]
    for start in range(0, len(points), UPSERT_BATCH):
        client.upsert(
            collection_name=COLLECTION, points=points[start : start + UPSERT_BATCH]
        )


def search_points(
    client: Any, vector: Sequence[float], version_ids: Sequence[int], limit: int
) -> list[int]:
    hits = client.query_points(
        collection_name=COLLECTION,
        query=list(vector),
        query_filter=_version_filter(version_ids),
        limit=limit,
        with_payload=False,
    ).points
    return [int(hit.id) for hit in hits]


async def embed(texts: Sequence[str]) -> Optional[list[list[float]]]:
    """Wektory wszystkich tekstów albo ``None`` — częściowy indeks nie powstaje."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = await embedding_service._voyage_embed_batch(
            list(texts[start : start + EMBED_BATCH]), input_type="document"
        )
        if not batch or any(vector is None for vector in batch):
            return None
        vectors.extend(batch)  # type: ignore[arg-type]
    return vectors


async def index_version(
    act_id: int,
    version_id: int,
    rows: Sequence[tuple[int, str]],
    previous_version_id: Optional[int] = None,
) -> int:
    """Wektory przepisów wersji (``rows`` = (id przepisu, tekst do wektora)).

    Zwraca liczbę zapisanych punktów; 0 = wektorów nie ma (ranking po słowach).
    Punkty poprzedniej wersji znikają, bo wyszukiwanie po znaczeniu dotyczy
    tekstu obowiązującego.
    """
    if not rows or not embeddings_enabled():
        return 0
    client = embedding_service._get_qdrant_client()
    if client is None:
        return 0
    vectors = await embed([text for _pid, text in rows])
    if vectors is None:
        logger.warning("[legal] Voyage nie zwrócił wektorów wersji %s", version_id)
        return 0
    try:
        await embedding_service._run_qdrant(
            lambda: upsert_points(
                client, act_id, version_id, [p for p, _t in rows], vectors
            )
        )
        if previous_version_id:
            await embedding_service._run_qdrant(
                lambda: delete_version_points(client, previous_version_id)
            )
    except Exception as exc:  # noqa: BLE001 — zostaje ranking po słowach
        logger.warning("[legal] zapis wektorów nieudany: %s", type(exc).__name__)
        return 0
    return len(rows)


async def vector_ranking(query: str, version_ids: Sequence[int]) -> Optional[list[int]]:
    """Id przepisów najbliższych pytaniu; ``None`` = wektory niedostępne."""
    if not version_ids or not embeddings_enabled():
        return None
    vector = await embedding_service.generate_embedding(query, input_type="query")
    if vector is None:
        return None
    client = embedding_service._get_qdrant_client()
    if client is None:
        return None
    try:
        return await embedding_service._run_qdrant(
            lambda: search_points(client, vector, version_ids, VECTOR_HITS)
        )
    except Exception as exc:  # noqa: BLE001 — zostaje wyszukiwanie po słowach
        logger.warning(
            "[legal] wyszukiwanie wektorowe nieudane: %s", type(exc).__name__
        )
        return None
