"""Indeks treści dokumentów kontraktu: plik → fragmenty w bazie → wektory w Qdrancie.

Ten sam układ co umowy ramowe klientów (``framework_contract_index``):

- **Tekst mieszka w Postgresie** (``contract_document_chunks``), w Qdrancie
  same wektory. Identyfikator punktu = ``id`` fragmentu, więc trafienie bez
  wiersza w bazie (usunięty dokument) odpada, a o dostępie rozstrzyga baza.
- **Bez pętli w tle.** Odczyt uruchamia wgranie pliku (zadanie w tle), a gdy
  stan nie zgadza się z plikiem — pierwsze pytanie o kontrakt
  (``ensure_indexed``). Istniejące dokumenty zasila
  ``scripts/backfill_contract_document_text.py``. Jeden bieg naraz na
  dokument w procesie.
- **Wektory są dodatkiem.** Bez Voyage albo Qdranta dokument ma stan
  ``text_only`` i odpowiada wyszukiwaniem po słowach.
- Odczyt pliku i embedding nigdy nie biegną w otwartej transakcji.
- **Do Voyage bez danych osoby.** Fragment przed embeddingiem przechodzi przez
  ``pseudonymize.mask`` z danymi Partnera kontraktu (imię i nazwisko z odmianą,
  firma, NIP, adres, e-mail, telefon); w bazie zostaje pełny tekst.

Czytamy tylko dokumenty, które niosą postanowienia umowy (``READ_TYPES``):
umowę, aneks, wypowiedzenie i porozumienie rozwiązujące. Zaświadczenia,
polisy i zamówienia nie są treścią umowy z Partnerem.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from qdrant_client import models as qmodels
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, release_idle_connection
from app.core.tasks import spawn
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_document_chunk import ContractDocumentChunk
from app.services import embedding_service, storage_service
from app.services.contract_document_text.schema import (
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_TEXT_ONLY,
    STATUS_UNREADABLE,
)
from app.services.framework_contract_index import (
    _embed,
    _read_file,
    _reading_slot,
    embeddings_enabled,
)
from app.services.framework_contract_text import ChunkRef, split_into_chunks
from app.services.legal.pseudonymize import Entity, mask, partner_entities

logger = logging.getLogger(__name__)

# Nazwa celowo NIE zaczyna się od ``nexus_candidates``:
# ``delete_candidate_embedding`` kasuje punkt o id kandydata z każdej takiej
# kolekcji, czyli skasowałby fragment dokumentu o tym samym numerze.
COLLECTION = "nexus_contract_documents"
PAYLOAD_DOCUMENT_ID = "contract_document_id"
PAYLOAD_CONTRACT_ID = "contract_id"

READ_TYPES: tuple[ContractDocumentType, ...] = (
    ContractDocumentType.contract,
    ContractDocumentType.annex,
    ContractDocumentType.termination_notice,
    ContractDocumentType.termination_agreement,
)

RETRY_AFTER = timedelta(minutes=10)
# Umowa B2B ma kilkanaście stron; limit chroni przed omyłkowo wgraną teczką.
MAX_CHUNKS = 600
UPSERT_BATCH = 256
VECTOR_HITS = 12
SCAN_CHARS_PER_PAGE = 200
ENSURE_WAIT_SECONDS = 30.0

_inflight: dict[int, "asyncio.Task[None]"] = {}


def is_read_type(doc_type: Any) -> bool:
    value = getattr(doc_type, "value", doc_type)
    return value in {t.value for t in READ_TYPES}


# ── Qdrant (klient synchroniczny podawany z zewnątrz) ───────────────────────


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
    for field_name in (PAYLOAD_DOCUMENT_ID, PAYLOAD_CONTRACT_ID):
        client.create_payload_index(
            collection_name=COLLECTION,
            field_name=field_name,
            field_schema=qmodels.PayloadSchemaType.INTEGER,
        )


def delete_points(client: Any, document_id: int) -> None:
    """Usuwa punkty dokumentu; brak kolekcji znaczy, że nie ma czego usuwać."""
    try:
        client.delete(
            collection_name=COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key=PAYLOAD_DOCUMENT_ID,
                            match=qmodels.MatchAny(any=[int(document_id)]),
                        )
                    ]
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        missing = getattr(exc, "status_code", None) == 404 or "not found" in message
        if not (missing or "doesn't exist" in message):
            raise


def replace_points(
    client: Any,
    document_id: int,
    contract_id: int,
    chunk_ids: Sequence[int],
    vectors: Sequence[Sequence[float]],
) -> None:
    """Najpierw kasuje punkty dokumentu, potem zapisuje nowe. Payload bez tekstu."""
    ensure_collection(client)
    delete_points(client, document_id)
    points = [
        qmodels.PointStruct(
            id=int(chunk_id),
            vector=list(vector),
            payload={
                PAYLOAD_DOCUMENT_ID: int(document_id),
                PAYLOAD_CONTRACT_ID: int(contract_id),
                "chunk_index": index,
            },
        )
        for index, (chunk_id, vector) in enumerate(zip(chunk_ids, vectors))
    ]
    for start in range(0, len(points), UPSERT_BATCH):
        client.upsert(
            collection_name=COLLECTION, points=points[start : start + UPSERT_BATCH]
        )


def search_points(
    client: Any, vector: Sequence[float], document_ids: Sequence[int], limit: int
) -> list[int]:
    hits = client.query_points(
        collection_name=COLLECTION,
        query=list(vector),
        query_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key=PAYLOAD_DOCUMENT_ID,
                    match=qmodels.MatchAny(any=[int(i) for i in document_ids]),
                )
            ]
        ),
        limit=limit,
        with_payload=False,
    ).points
    return [int(hit.id) for hit in hits]


async def _qdrant_call(fn: Callable[[], Any]) -> bool:
    try:
        await embedding_service._run_qdrant(fn)
        return True
    except Exception as exc:  # noqa: BLE001 — wektory są dodatkiem
        logger.warning(
            "[dokumenty kontraktu] Qdrant niedostępny: %s", type(exc).__name__
        )
        return False


# ── zapis stanu ─────────────────────────────────────────────────────────────


async def _save_state(document_id: int, file_path: str, **values: Any) -> None:
    """Stan odczytu bez ruszania ``updated_at`` — to nie jest edycja dokumentu."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ContractDocument)
            .where(
                ContractDocument.id == document_id,
                ContractDocument.file_path == file_path,
            )
            .values(
                text_file_path=file_path,
                text_attempted_at=datetime.now(timezone.utc),
                updated_at=ContractDocument.updated_at,
                **values,
            )
        )
        await db.commit()


async def _store_chunks(
    document_id: int,
    file_path: str,
    chunks: Sequence[str],
    pages: Optional[int],
    ocr_pages: int,
) -> Optional[tuple[int, list[int]]]:
    """Podmienia fragmenty pod blokadą wiersza. ``None`` = plik już inny."""
    async with AsyncSessionLocal() as db:
        current = (
            await db.execute(
                select(ContractDocument.file_path, ContractDocument.contract_id)
                .where(ContractDocument.id == document_id)
                .with_for_update()
            )
        ).first()
        if current is None or current[0] != file_path:
            return None
        contract_id = int(current[1])
        await db.execute(
            delete(ContractDocumentChunk).where(
                ContractDocumentChunk.contract_document_id == document_id
            )
        )
        rows = [
            ContractDocumentChunk(
                contract_document_id=document_id,
                contract_id=contract_id,
                chunk_index=index,
                text=text,
            )
            for index, text in enumerate(chunks)
        ]
        db.add_all(rows)
        await db.flush()
        chunk_ids = [int(row.id) for row in rows]
        await db.execute(
            update(ContractDocument)
            .where(ContractDocument.id == document_id)
            .values(
                text_status=STATUS_TEXT_ONLY if chunks else STATUS_UNREADABLE,
                text_file_path=file_path,
                text_chars=sum(len(text) for text in chunks),
                text_pages=pages,
                text_ocr_pages=ocr_pages,
                text_model=None,
                text_attempted_at=datetime.now(timezone.utc),
                updated_at=ContractDocument.updated_at,
            )
        )
        await db.commit()
        return contract_id, chunk_ids


def masked_for_embedding(
    chunks: Sequence[str], entities: Sequence[Entity]
) -> list[str]:
    """Fragmenty do wektorów: dane osoby z kontraktu i numery (PESEL, NIP,
    rachunek, e-mail, telefon) jako znaczniki ``pseudonymize``."""
    return [mask(chunk, entities)[0] for chunk in chunks]


async def _embedding_entities(document_id: int) -> list[Entity]:
    """Partner kontraktu dokumentu (umowa z Generatora, a bez niej karta osoby)."""
    from app.services.trainings.agreement import partner_from_contract  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        contract_id = await db.scalar(
            select(ContractDocument.contract_id).where(
                ContractDocument.id == document_id
            )
        )
        if contract_id is None:
            return []
        partner = await partner_from_contract(db, contract_id)
    return partner_entities(partner)


async def index_document(document_id: int) -> None:
    """Czyta plik dokumentu i odbudowuje jego fragmenty oraz wektory."""
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(
                    ContractDocument.file_path,
                    ContractDocument.filename,
                    ContractDocument.doc_type,
                ).where(ContractDocument.id == document_id)
            )
        ).first()
    if row is None or not row.file_path or not is_read_type(row.doc_type):
        return
    file_path, filename = row.file_path, row.filename or "umowa.pdf"

    try:
        abs_path = storage_service.get_contract_document_path(file_path)
        async with _reading_slot():
            text, pages, ocr_pages = await asyncio.to_thread(
                _read_file, str(abs_path), filename
            )
    except Exception as exc:  # noqa: BLE001 — stan zamiast wyjątku w zadaniu tła
        logger.warning(
            "[dokumenty kontraktu] odczyt pliku dokumentu %s nieudany: %s",
            document_id,
            type(exc).__name__,
        )
        await _save_state(document_id, file_path, text_status=STATUS_FAILED)
        return

    chunks = split_into_chunks(text)[:MAX_CHUNKS]
    vectors = None
    if chunks and embeddings_enabled():
        # Do Voyage idą fragmenty z danymi osoby jako znacznikami; w Postgresie
        # (czytanie, cytaty) zostaje pełny tekst.
        entities = await _embedding_entities(document_id)
        vectors = await _embed(masked_for_embedding(chunks, entities))

    stored = await _store_chunks(document_id, file_path, chunks, pages, ocr_pages)
    if stored is None:
        return
    contract_id, chunk_ids = stored
    client = embedding_service._get_qdrant_client()
    if client is None:
        return
    if not chunks or vectors is None:
        await _qdrant_call(lambda: delete_points(client, document_id))
        return
    if await _qdrant_call(
        lambda: replace_points(client, document_id, contract_id, chunk_ids, vectors)
    ):
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ContractDocument)
                .where(
                    ContractDocument.id == document_id,
                    ContractDocument.text_file_path == file_path,
                    ContractDocument.text_status == STATUS_TEXT_ONLY,
                )
                .values(
                    text_status=STATUS_INDEXED,
                    text_model=embedding_service._voyage_model(),
                    updated_at=ContractDocument.updated_at,
                )
            )
            await db.commit()


async def delete_document_points(document_id: int) -> None:
    client = embedding_service._get_qdrant_client()
    if client is not None:
        await _qdrant_call(lambda: delete_points(client, document_id))


def start_indexing(document_id: int) -> "asyncio.Task[None]":
    """Jeden bieg naraz na dokument w procesie; zwraca trwający albo nowy."""
    task = _inflight.get(document_id)
    if task is None or task.done():
        task = spawn(
            index_document(document_id), f"contract-document-text:{document_id}"
        )
        _inflight[document_id] = task

        def _done(finished: "asyncio.Task[None]") -> None:
            if _inflight.get(document_id) is finished:
                del _inflight[document_id]

        task.add_done_callback(_done)
    return task


def index_after_upload(document: Any) -> None:
    """Po wgraniu pliku: odczyt w tle, żądanie nie czeka."""
    if is_read_type(document.doc_type):
        start_indexing(int(document.id))


def forget_after_delete(document_id: int) -> None:
    """Po usunięciu dokumentu (wiersze fragmentów znikają kaskadą)."""
    spawn(
        delete_document_points(document_id),
        f"contract-document-text-forget:{document_id}",
    )


def needs_indexing(document: Any, *, now: Optional[datetime] = None) -> bool:
    if not document.file_path or not is_read_type(document.doc_type):
        return False
    if document.text_file_path != document.file_path:
        return True
    retryable = document.text_status == STATUS_FAILED or (
        document.text_status == STATUS_TEXT_ONLY and embeddings_enabled()
    )
    if not retryable:
        return False
    attempted = document.text_attempted_at
    return attempted is None or (now or datetime.now(timezone.utc)) - attempted > (
        RETRY_AFTER
    )


async def ensure_indexed(
    db: AsyncSession,
    documents: Sequence[ContractDocument],
    *,
    wait_seconds: float = ENSURE_WAIT_SECONDS,
) -> None:
    """Odbudowuje nieaktualne indeksy przed odczytem; czeka najwyżej ``wait_seconds``.

    Po przekroczeniu czasu bieg trwa dalej w tle (``shield``), a wołający
    odpowiada tym, co już jest.
    """
    stale = [document for document in documents if needs_indexing(document)]
    if not stale:
        return
    await release_idle_connection(db)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    for document in stale:
        task = start_indexing(document.id)
        remaining = deadline - loop.time()
        if remaining <= 0:
            continue
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
        except asyncio.TimeoutError:
            continue
        except Exception:  # noqa: BLE001 — porażkę loguje zadanie
            continue
        await db.refresh(document)


# ── odczyt ──────────────────────────────────────────────────────────────────


def has_current_text(document: Any) -> bool:
    return (
        bool(document.file_path)
        and document.text_file_path == document.file_path
        and document.text_status in (STATUS_INDEXED, STATUS_TEXT_ONLY)
    )


def reading_note(document: Any) -> Optional[str]:
    """Zdanie dla człowieka, gdy treści dokumentu nie ma albo jest niepełna."""
    if not is_read_type(document.doc_type):
        return "NEXUS nie czyta treści dokumentów tego typu."
    if document.text_file_path != document.file_path:
        return "Plik jest właśnie czytany — zapytaj ponownie za chwilę."
    if document.text_status == STATUS_UNREADABLE:
        return (
            "Z pliku nie da się odczytać tekstu (skan bez tekstu albo uszkodzony plik)."
        )
    if document.text_status == STATUS_FAILED:
        return "Odczyt pliku się nie udał (np. pliku nie ma na dysku) — sprawdź PDF."
    pages, chars = document.text_pages, document.text_chars or 0
    if pages and chars < pages * SCAN_CHARS_PER_PAGE:
        return (
            "Z pliku odczytano mało tekstu: część stron może nie być w treści. "
            "Resztę trzeba sprawdzić w PDF-ie."
        )
    if document.text_ocr_pages:
        return "Część stron to skan: wpisy odręczne trzeba sprawdzić w PDF-ie."
    return None


_CHUNK_COLUMNS = (
    ContractDocumentChunk.id,
    ContractDocumentChunk.contract_document_id,
    ContractDocumentChunk.chunk_index,
    ContractDocumentChunk.text,
)


async def load_chunks(db: AsyncSession, document_ids: Sequence[int]) -> list[ChunkRef]:
    """Fragmenty wskazanych dokumentów w kolejności.

    ``ChunkRef.contract_id`` niesie tu identyfikator DOKUMENTU — ranking
    i sklejanie sąsiadów (``framework_contract_text``) grupują po tym polu.
    """
    if not document_ids:
        return []
    rows = await db.execute(
        select(*_CHUNK_COLUMNS)
        .where(ContractDocumentChunk.contract_document_id.in_(list(document_ids)))
        .order_by(
            ContractDocumentChunk.contract_document_id,
            ContractDocumentChunk.chunk_index,
        )
    )
    return [
        ChunkRef(
            id=int(row.id),
            contract_id=int(row.contract_document_id),
            index=int(row.chunk_index),
            text=row.text,
        )
        for row in rows
    ]


async def vector_ranking(
    query: str, document_ids: Sequence[int]
) -> Optional[list[int]]:
    """Identyfikatory fragmentów najbliższych pytaniu; ``None`` = wektory niedostępne."""
    if not document_ids or not embeddings_enabled():
        return None
    vector = await embedding_service.generate_embedding(query, input_type="query")
    if vector is None:
        return None
    client = embedding_service._get_qdrant_client()
    if client is None:
        return None
    try:
        return await embedding_service._run_qdrant(
            lambda: search_points(client, vector, document_ids, VECTOR_HITS)
        )
    except Exception as exc:  # noqa: BLE001 — zostaje wyszukiwanie po słowach
        logger.warning(
            "[dokumenty kontraktu] wyszukiwanie wektorowe nieudane: %s",
            type(exc).__name__,
        )
        return None
