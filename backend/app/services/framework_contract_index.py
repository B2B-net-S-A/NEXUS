"""Indeks treści umów ramowych klientów: plik → fragmenty w bazie → wektory w Qdrancie.

Zgłoszenie 09.10.2026: Jarvis na pytanie o zapis umowy z klientem odpowiadał,
że nie ma dostępu do treści umów. Decyzje Artura z tego dnia: wyszukiwanie po
znaczeniu (embeddingi), treść umów może iść do Voyage i Anthropic.

Zasady:

- **Tekst mieszka w Postgresie** (``client_framework_contract_chunks``),
  w Qdrancie są same wektory. Identyfikator punktu = ``id`` wiersza fragmentu,
  więc trafienie bez wiersza w bazie (usunięta umowa, podmieniony plik) po
  prostu odpada, a o dostępie rozstrzyga baza.
- **Bez pętli i bez outboxu.** Odczyt uruchamia wgranie albo podmiana pliku
  (zadanie w tle), a gdy stan nie zgadza się z plikiem — pierwsze pytanie
  o umowę (``ensure_indexed``). Jeden bieg naraz na umowę w procesie.
- **Wektory są dodatkiem.** Bez Voyage albo Qdranta umowa ma stan
  ``text_only`` i odpowiada wyszukiwaniem po słowach; ponowienie najwcześniej
  po ``RETRY_AFTER``.
- Odczyt pliku i embedding nigdy nie biegną w otwartej transakcji.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from qdrant_client import models as qmodels
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, release_idle_connection
from app.core.tasks import spawn
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_framework_contract_chunk import ClientFrameworkContractChunk
from app.services import cv_text_extractor, embedding_service, storage_service
from app.services.framework_contract_text import (
    ChunkRef,
    Passage,
    build_passages,
    query_stems,
    rank_by_keywords,
    split_into_chunks,
)
from app.services.framework_contract_text_schema import (
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_TEXT_ONLY,
    STATUS_UNREADABLE,
)
from app.services.hybrid_search import reciprocal_rank_fusion

logger = logging.getLogger(__name__)

# Nazwa celowo NIE zaczyna się od ``nexus_candidates``:
# ``delete_candidate_embedding`` kasuje punkt o id kandydata z każdej takiej
# kolekcji, czyli skasowałby fragment umowy o tym samym numerze.
COLLECTION = "nexus_client_documents"
PAYLOAD_CONTRACT_ID = "framework_contract_id"

RETRY_AFTER = timedelta(minutes=10)
# Umowa na kilkaset stron; dalej fragmenty nie powstają (notatka w odpowiedzi).
MAX_CHUNKS = 2000
EMBED_BATCH = 128
UPSERT_BATCH = 256
VECTOR_HITS = 12
# Poniżej tylu znaków na stronę PDF to skan: OCR czyta tylko 10 pierwszych stron.
SCAN_CHARS_PER_PAGE = 200
# Tyle czeka żądanie na odczyt umowy; bieg trwa dalej w tle (transport Jarvisa
# ma 45 s na całe wywołanie narzędzia).
ENSURE_WAIT_SECONDS = 30.0

RETRIEVAL_HYBRID = "hybrid"
RETRIEVAL_KEYWORDS = "keywords"
RETRIEVAL_NONE = "none"

_inflight: dict[int, "asyncio.Task[None]"] = {}


def embeddings_enabled() -> bool:
    return bool(getattr(settings, "FRAMEWORK_CONTRACT_EMBEDDINGS_ENABLED", True))


# ── Qdrant (klient synchroniczny podawany z zewnątrz) ───────────────────────


def _contracts_filter(contract_ids: Sequence[int]) -> qmodels.Filter:
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key=PAYLOAD_CONTRACT_ID,
                match=qmodels.MatchAny(any=[int(i) for i in contract_ids]),
            )
        ]
    )


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
    # Idempotentne po stronie serwera; bez indeksu filtr po umowie jest liniowy.
    client.create_payload_index(
        collection_name=COLLECTION,
        field_name=PAYLOAD_CONTRACT_ID,
        field_schema=qmodels.PayloadSchemaType.INTEGER,
    )


def delete_points(client: Any, contract_id: int) -> None:
    """Usuwa punkty umowy po filtrze; brak kolekcji znaczy, że nie ma czego usuwać."""
    try:
        client.delete(
            collection_name=COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=_contracts_filter([contract_id])
            ),
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        missing = getattr(exc, "status_code", None) == 404 or "not found" in message
        if not (missing or "doesn't exist" in message):
            raise


def replace_points(
    client: Any,
    contract_id: int,
    chunk_ids: Sequence[int],
    vectors: Sequence[Sequence[float]],
) -> None:
    """Najpierw kasuje punkty umowy, potem zapisuje nowe — stare nie przeżywają."""
    ensure_collection(client)
    delete_points(client, contract_id)
    points = [
        qmodels.PointStruct(
            id=int(chunk_id),
            vector=list(vector),
            payload={PAYLOAD_CONTRACT_ID: int(contract_id), "chunk_index": index},
        )
        for index, (chunk_id, vector) in enumerate(zip(chunk_ids, vectors))
    ]
    # Paczkami: długa umowa w jednym żądaniu to kilkadziesiąt MB JSON-a.
    for start in range(0, len(points), UPSERT_BATCH):
        client.upsert(
            collection_name=COLLECTION, points=points[start : start + UPSERT_BATCH]
        )


def search_points(
    client: Any, vector: Sequence[float], contract_ids: Sequence[int], limit: int
) -> list[int]:
    hits = client.search(
        collection_name=COLLECTION,
        query_vector=list(vector),
        query_filter=_contracts_filter(contract_ids),
        limit=limit,
        with_payload=False,
    )
    return [int(hit.id) for hit in hits]


# ── odczyt pliku i embedding ────────────────────────────────────────────────


def _read_file(path: str, filename: str) -> tuple[str, Optional[int]]:
    """Tekst i liczba stron (tylko PDF). Blokujące — wołać w wątku."""
    try:
        text = cv_text_extractor.extract_text(path, filename)
    except cv_text_extractor.UnsupportedCvFormat:
        return "", None
    extension = (
        cv_text_extractor.sniff_extension(path) or os.path.splitext(filename)[1].lower()
    )
    pages = (
        cv_text_extractor.pdf_page_count_sandboxed(path)
        if extension == ".pdf"
        else None
    )
    return text, pages


async def _embed(texts: Sequence[str]) -> Optional[list[list[float]]]:
    """Wektory wszystkich fragmentów albo ``None`` — częściowy indeks nie powstaje."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = await embedding_service._voyage_embed_batch(
            list(texts[start : start + EMBED_BATCH]), input_type="document"
        )
        if not batch or any(vector is None for vector in batch):
            return None
        vectors.extend(batch)  # type: ignore[arg-type]
    return vectors


# ── zapis stanu ─────────────────────────────────────────────────────────────


async def _save_state(contract_id: int, file_path: str, **values: Any) -> None:
    """Stan odczytu bez ruszania ``updated_at`` — to nie jest edycja umowy."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientFrameworkContract)
            .where(
                ClientFrameworkContract.id == contract_id,
                ClientFrameworkContract.file_path == file_path,
            )
            .values(
                text_file_path=file_path,
                text_attempted_at=datetime.now(timezone.utc),
                updated_at=ClientFrameworkContract.updated_at,
                **values,
            )
        )
        await db.commit()


async def _store_chunks(
    contract_id: int, file_path: str, chunks: Sequence[str], pages: Optional[int]
) -> Optional[list[int]]:
    """Podmienia fragmenty umowy pod blokadą wiersza. ``None`` = plik już inny."""
    async with AsyncSessionLocal() as db:
        current = await db.scalar(
            select(ClientFrameworkContract.file_path)
            .where(ClientFrameworkContract.id == contract_id)
            .with_for_update()
        )
        if current != file_path:
            return None
        await db.execute(
            delete(ClientFrameworkContractChunk).where(
                ClientFrameworkContractChunk.framework_contract_id == contract_id
            )
        )
        rows = [
            ClientFrameworkContractChunk(
                framework_contract_id=contract_id, chunk_index=index, text=text
            )
            for index, text in enumerate(chunks)
        ]
        db.add_all(rows)
        await db.flush()
        chunk_ids = [int(row.id) for row in rows]
        await db.execute(
            update(ClientFrameworkContract)
            .where(ClientFrameworkContract.id == contract_id)
            .values(
                text_status=STATUS_TEXT_ONLY if chunks else STATUS_UNREADABLE,
                text_file_path=file_path,
                text_chars=sum(len(text) for text in chunks),
                text_pages=pages,
                text_model=None,
                text_attempted_at=datetime.now(timezone.utc),
                updated_at=ClientFrameworkContract.updated_at,
            )
        )
        await db.commit()
        return chunk_ids


async def _qdrant_call(fn: Any) -> bool:
    try:
        await embedding_service._run_qdrant(fn)
        return True
    except Exception as exc:  # noqa: BLE001 — wektory są dodatkiem
        logger.warning("[umowy] Qdrant niedostępny: %s", type(exc).__name__)
        return False


async def index_contract(contract_id: int) -> None:
    """Czyta plik umowy i odbudowuje jej fragmenty oraz wektory."""
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(
                    ClientFrameworkContract.file_path,
                    ClientFrameworkContract.filename,
                ).where(ClientFrameworkContract.id == contract_id)
            )
        ).first()
    if row is None or row.file_path is None:
        return
    file_path, filename = row.file_path, row.filename or "umowa.pdf"

    try:
        abs_path = storage_service.get_client_framework_contract_path(file_path)
        text, pages = await asyncio.to_thread(_read_file, str(abs_path), filename)
    except Exception as exc:  # noqa: BLE001 — stan zamiast wyjątku w zadaniu tła
        logger.warning(
            "[umowy] odczyt pliku umowy %s nieudany: %s",
            contract_id,
            type(exc).__name__,
        )
        await _save_state(contract_id, file_path, text_status=STATUS_FAILED)
        return

    chunks = split_into_chunks(text)[:MAX_CHUNKS]
    vectors = await _embed(chunks) if chunks and embeddings_enabled() else None

    chunk_ids = await _store_chunks(contract_id, file_path, chunks, pages)
    if chunk_ids is None:
        return
    client = embedding_service._get_qdrant_client()
    if client is None:
        return
    if not chunks or vectors is None:
        # Punkty poprzedniego pliku nie mają już wierszy w bazie — sprzątamy.
        await _qdrant_call(lambda: delete_points(client, contract_id))
        return
    if await _qdrant_call(
        lambda: replace_points(client, contract_id, chunk_ids, vectors)
    ):
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ClientFrameworkContract)
                .where(
                    ClientFrameworkContract.id == contract_id,
                    ClientFrameworkContract.text_file_path == file_path,
                    ClientFrameworkContract.text_status == STATUS_TEXT_ONLY,
                )
                .values(
                    text_status=STATUS_INDEXED,
                    text_model=embedding_service._voyage_model(),
                    updated_at=ClientFrameworkContract.updated_at,
                )
            )
            await db.commit()


async def delete_contract_points(contract_id: int) -> None:
    client = embedding_service._get_qdrant_client()
    if client is not None:
        await _qdrant_call(lambda: delete_points(client, contract_id))


def index_after_upload(contract_id: int) -> None:
    """Po wgraniu albo podmianie pliku: odczyt w tle, żądanie nie czeka."""
    start_indexing(contract_id)


def forget_after_delete(contract_id: int) -> None:
    """Po trwałym usunięciu umowy (wiersze fragmentów znikają kaskadą)."""
    spawn(
        delete_contract_points(contract_id),
        f"framework-contract-forget:{contract_id}",
    )


def needs_indexing(
    contract: ClientFrameworkContract, *, now: Optional[datetime] = None
) -> bool:
    if contract.file_path is None:
        return False
    if contract.text_file_path != contract.file_path:
        return True
    retryable = contract.text_status == STATUS_FAILED or (
        contract.text_status == STATUS_TEXT_ONLY and embeddings_enabled()
    )
    if not retryable:
        return False
    attempted = contract.text_attempted_at
    return attempted is None or (now or datetime.now(timezone.utc)) - attempted > (
        RETRY_AFTER
    )


def start_indexing(contract_id: int) -> "asyncio.Task[None]":
    """Jeden bieg naraz na umowę w procesie; zwraca trwający albo nowy."""
    task = _inflight.get(contract_id)
    if task is None or task.done():
        task = spawn(
            index_contract(contract_id), f"framework-contract-index:{contract_id}"
        )
        _inflight[contract_id] = task

        def _done(finished: "asyncio.Task[None]") -> None:
            if _inflight.get(contract_id) is finished:
                del _inflight[contract_id]

        task.add_done_callback(_done)
    return task


async def ensure_indexed(
    db: AsyncSession,
    contracts: Sequence[ClientFrameworkContract],
    *,
    wait_seconds: float = ENSURE_WAIT_SECONDS,
) -> None:
    """Odbudowuje nieaktualne indeksy przed odczytem; czeka najwyżej ``wait_seconds``.

    Po przekroczeniu czasu bieg trwa dalej w tle (``shield``), a wołający
    odpowiada tym, co już jest.
    """
    stale = [contract for contract in contracts if needs_indexing(contract)]
    if not stale:
        return
    # Czekanie na odczyt pliku i Voyage nie może trzymać połączenia z puli.
    await release_idle_connection(db)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    for contract in stale:
        task = start_indexing(contract.id)
        remaining = deadline - loop.time()
        if remaining <= 0:
            continue
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
        except asyncio.TimeoutError:
            continue
        except Exception:  # noqa: BLE001 — porażkę loguje zadanie
            continue
        await db.refresh(contract)


# ── odczyt ──────────────────────────────────────────────────────────────────


def has_current_text(contract: ClientFrameworkContract) -> bool:
    return (
        contract.file_path is not None
        and contract.text_file_path == contract.file_path
        and contract.text_status in (STATUS_INDEXED, STATUS_TEXT_ONLY)
    )


def reading_note(contract: ClientFrameworkContract) -> Optional[str]:
    """Zdanie dla człowieka, gdy treści umowy nie ma albo jest niepełna."""
    if contract.file_path is None:
        return "Brak wgranego pliku — NEXUS zna tylko okres obowiązywania tej umowy."
    if contract.text_file_path != contract.file_path:
        return "Plik umowy jest właśnie czytany — zapytaj ponownie za chwilę."
    if contract.text_status == STATUS_UNREADABLE:
        return (
            "Z pliku nie da się odczytać tekstu (skan bez tekstu albo uszkodzony plik)."
        )
    if contract.text_status == STATUS_FAILED:
        return "Odczyt pliku się nie udał — spróbuj ponownie za kilka minut."
    pages, chars = contract.text_pages, contract.text_chars or 0
    if pages and chars < pages * SCAN_CHARS_PER_PAGE:
        return (
            "Plik wygląda na skan: odczytany jest tylko początek umowy "
            "(pierwsze 10 stron). Resztę trzeba sprawdzić w PDF-ie."
        )
    return None


async def load_chunks(db: AsyncSession, contract_ids: Sequence[int]) -> list[ChunkRef]:
    if not contract_ids:
        return []
    rows = await db.execute(
        select(
            ClientFrameworkContractChunk.id,
            ClientFrameworkContractChunk.framework_contract_id,
            ClientFrameworkContractChunk.chunk_index,
            ClientFrameworkContractChunk.text,
        )
        .where(ClientFrameworkContractChunk.framework_contract_id.in_(contract_ids))
        .order_by(
            ClientFrameworkContractChunk.framework_contract_id,
            ClientFrameworkContractChunk.chunk_index,
        )
    )
    return [
        ChunkRef(id=int(r.id), contract_id=int(r[1]), index=int(r[2]), text=r.text)
        for r in rows
    ]


async def vector_ranking(
    query: str, contract_ids: Sequence[int]
) -> Optional[list[int]]:
    """Identyfikatory fragmentów najbliższych pytaniu; ``None`` = wektory niedostępne."""
    if not contract_ids or not embeddings_enabled():
        return None
    vector = await embedding_service.generate_embedding(query, input_type="query")
    if vector is None:
        return None
    client = embedding_service._get_qdrant_client()
    if client is None:
        return None
    try:
        return await embedding_service._run_qdrant(
            lambda: search_points(client, vector, contract_ids, VECTOR_HITS)
        )
    except Exception as exc:  # noqa: BLE001 — zostaje wyszukiwanie po słowach
        logger.warning(
            "[umowy] wyszukiwanie wektorowe nieudane: %s", type(exc).__name__
        )
        return None


@dataclass(frozen=True)
class SearchOutcome:
    passages: list[Passage]
    retrieval: str


async def search(
    db: AsyncSession, contracts: Sequence[ClientFrameworkContract], query: str
) -> SearchOutcome:
    """Fragmenty umów pasujące do pytania: po znaczeniu i po słowach (RRF)."""
    readable = [contract for contract in contracts if has_current_text(contract)]
    chunks = await load_chunks(db, [contract.id for contract in readable])
    if not chunks:
        return SearchOutcome([], RETRIEVAL_NONE)
    keyword_ids = rank_by_keywords(query_stems(query), chunks)
    vector_ids = await vector_ranking(
        query, [c.id for c in readable if c.text_status == STATUS_INDEXED]
    )
    if vector_ids is None:
        return SearchOutcome(build_passages(keyword_ids, chunks), RETRIEVAL_KEYWORDS)
    known = {chunk.id for chunk in chunks}
    fused = reciprocal_rank_fusion(
        [[i for i in vector_ids if i in known], keyword_ids[:VECTOR_HITS]]
    )
    return SearchOutcome(
        build_passages([chunk_id for chunk_id, _score in fused], chunks),
        RETRIEVAL_HYBRID,
    )
