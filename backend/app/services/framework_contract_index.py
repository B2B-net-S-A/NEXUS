"""Indeks treści umów ramowych i aneksów: plik → fragmenty w bazie → wektory w Qdrancie.

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
- **Aneks czytany tak samo jak umowa** (0627): umowa bywa przedłużona samym
  aneksem (EY, aneks nr 3 z 28.03.2025), więc bez niego odpowiedź byłaby
  nieaktualna. Punkt aneksu ma w Qdrancie własny klucz payloadu, dlatego
  podmiana pliku umowy nie kasuje wektorów jej aneksów.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from qdrant_client import models as qmodels
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, release_idle_connection
from app.core.tasks import spawn
from app.models.client_contract_amendment import ClientContractAmendment
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
PAYLOAD_AMENDMENT_ID = "client_amendment_id"

RETRY_AFTER = timedelta(minutes=10)
# Umowa na kilkaset stron; dalej fragmenty nie powstają (notatka w odpowiedzi).
MAX_CHUNKS = 2000
EMBED_BATCH = 128
UPSERT_BATCH = 256
VECTOR_HITS = 12
# Poniżej tylu znaków na stronę PDF treść jest podejrzanie krótka.
SCAN_CHARS_PER_PAGE = 200
# Tyle czeka żądanie na odczyt umowy; bieg trwa dalej w tle (transport Jarvisa
# ma 45 s na całe wywołanie narzędzia).
ENSURE_WAIT_SECONDS = 30.0

RETRIEVAL_HYBRID = "hybrid"
RETRIEVAL_KEYWORDS = "keywords"
RETRIEVAL_NONE = "none"

_inflight: dict[Any, "asyncio.Task[None]"] = {}
# OCR umowy na 248 stron trwa kilkanaście minut — jeden odczyt naraz w procesie,
# żeby import paczki nie zabrał rdzeni wyszukiwarce i Jarvisowi.
_reading_slots: dict[int, asyncio.Semaphore] = {}


def _reading_slot() -> asyncio.Semaphore:
    """Semafor per pętla zdarzeń (testy i polecenia mają każde własną)."""
    return _reading_slots.setdefault(
        id(asyncio.get_running_loop()), asyncio.Semaphore(1)
    )


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
    for field_name in (PAYLOAD_CONTRACT_ID, PAYLOAD_AMENDMENT_ID):
        client.create_payload_index(
            collection_name=COLLECTION,
            field_name=field_name,
            field_schema=qmodels.PayloadSchemaType.INTEGER,
        )


def delete_points(
    client: Any, document_id: int, payload_key: str = PAYLOAD_CONTRACT_ID
) -> None:
    """Usuwa punkty dokumentu po filtrze; brak kolekcji znaczy, że nie ma czego usuwać."""
    try:
        client.delete(
            collection_name=COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key=payload_key,
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
    chunk_ids: Sequence[int],
    vectors: Sequence[Sequence[float]],
    payload_key: str = PAYLOAD_CONTRACT_ID,
) -> None:
    """Najpierw kasuje punkty dokumentu, potem zapisuje nowe — stare nie przeżywają."""
    ensure_collection(client)
    delete_points(client, document_id, payload_key)
    points = [
        qmodels.PointStruct(
            id=int(chunk_id),
            vector=list(vector),
            payload={payload_key: int(document_id), "chunk_index": index},
        )
        for index, (chunk_id, vector) in enumerate(zip(chunk_ids, vectors))
    ]
    # Paczkami: długa umowa w jednym żądaniu to kilkadziesiąt MB JSON-a.
    for start in range(0, len(points), UPSERT_BATCH):
        client.upsert(
            collection_name=COLLECTION, points=points[start : start + UPSERT_BATCH]
        )


def search_points(
    client: Any,
    vector: Sequence[float],
    contract_ids: Sequence[int],
    limit: int,
    amendment_ids: Sequence[int] = (),
) -> list[int]:
    query_filter = _contracts_filter(contract_ids)
    if amendment_ids:
        query_filter = qmodels.Filter(
            should=[
                qmodels.FieldCondition(
                    key=key, match=qmodels.MatchAny(any=[int(i) for i in ids])
                )
                for key, ids in (
                    (PAYLOAD_CONTRACT_ID, contract_ids),
                    (PAYLOAD_AMENDMENT_ID, amendment_ids),
                )
                if ids
            ]
        )
    hits = client.search(
        collection_name=COLLECTION,
        query_vector=list(vector),
        query_filter=query_filter,
        limit=limit,
        with_payload=False,
    )
    return [int(hit.id) for hit in hits]


# ── odczyt pliku i embedding ────────────────────────────────────────────────


def _read_file(path: str, filename: str) -> tuple[str, Optional[int], int]:
    """Tekst, liczba stron (tylko PDF) i strony z OCR. Blokujące — wołać w wątku."""
    extension = (
        cv_text_extractor.sniff_extension(path) or os.path.splitext(filename)[1].lower()
    )
    if extension == ".pdf":
        whole = cv_text_extractor.extract_pdf_all_pages_sandboxed(path)
        if whole is not None:
            return whole.text, whole.pages, whole.ocr_pages
    try:
        text = cv_text_extractor.extract_text(path, filename)
    except cv_text_extractor.UnsupportedCvFormat:
        return "", None, 0
    pages = (
        cv_text_extractor.pdf_page_count_sandboxed(path)
        if extension == ".pdf"
        else None
    )
    return text, pages, 0


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


@dataclass(frozen=True)
class _Source:
    """Rodzaj czytanego dokumentu: umowa ramowa albo jej aneks."""

    model: Any
    chunks_of: Callable[[int], Any]
    absolute_path: Callable[[str], Any]
    payload_key: str
    default_filename: str
    label: str


_CONTRACT = _Source(
    model=ClientFrameworkContract,
    chunks_of=lambda document_id: (
        ClientFrameworkContractChunk.framework_contract_id == document_id,
        ClientFrameworkContractChunk.amendment_id.is_(None),
    ),
    absolute_path=lambda path: storage_service.get_client_framework_contract_path(path),
    payload_key=PAYLOAD_CONTRACT_ID,
    default_filename="umowa.pdf",
    label="umowy",
)
_AMENDMENT = _Source(
    model=ClientContractAmendment,
    chunks_of=lambda document_id: (
        ClientFrameworkContractChunk.amendment_id == document_id,
    ),
    absolute_path=lambda path: storage_service.get_client_contract_amendment_path(path),
    payload_key=PAYLOAD_AMENDMENT_ID,
    default_filename="aneks.pdf",
    label="aneksu",
)


async def _save_state(
    source: _Source, document_id: int, file_path: str, **values: Any
) -> None:
    """Stan odczytu bez ruszania ``updated_at`` — to nie jest edycja dokumentu."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(source.model)
            .where(source.model.id == document_id, source.model.file_path == file_path)
            .values(
                text_file_path=file_path,
                text_attempted_at=datetime.now(timezone.utc),
                updated_at=source.model.updated_at,
                **values,
            )
        )
        await db.commit()


async def _store_chunks(
    source: _Source,
    document_id: int,
    file_path: str,
    chunks: Sequence[str],
    pages: Optional[int],
    ocr_pages: int,
) -> Optional[list[int]]:
    """Podmienia fragmenty dokumentu pod blokadą wiersza. ``None`` = plik już inny."""
    async with AsyncSessionLocal() as db:
        current = (
            await db.execute(
                select(
                    source.model.file_path,
                    (
                        ClientContractAmendment.framework_contract_id
                        if source is _AMENDMENT
                        else ClientFrameworkContract.id
                    ),
                )
                .where(source.model.id == document_id)
                .with_for_update()
            )
        ).first()
        if current is None or current[0] != file_path:
            return None
        await db.execute(
            delete(ClientFrameworkContractChunk).where(*source.chunks_of(document_id))
        )
        rows = [
            ClientFrameworkContractChunk(
                framework_contract_id=int(current[1]),
                amendment_id=document_id if source is _AMENDMENT else None,
                chunk_index=index,
                text=text,
            )
            for index, text in enumerate(chunks)
        ]
        db.add_all(rows)
        await db.flush()
        chunk_ids = [int(row.id) for row in rows]
        await db.execute(
            update(source.model)
            .where(source.model.id == document_id)
            .values(
                text_status=STATUS_TEXT_ONLY if chunks else STATUS_UNREADABLE,
                text_file_path=file_path,
                text_chars=sum(len(text) for text in chunks),
                text_pages=pages,
                text_ocr_pages=ocr_pages,
                text_model=None,
                text_attempted_at=datetime.now(timezone.utc),
                updated_at=source.model.updated_at,
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


async def _index_document(source: _Source, document_id: int) -> None:
    """Czyta plik dokumentu i odbudowuje jego fragmenty oraz wektory."""
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(source.model.file_path, source.model.filename).where(
                    source.model.id == document_id
                )
            )
        ).first()
    if row is None or row.file_path is None:
        return
    file_path, filename = row.file_path, row.filename or source.default_filename

    try:
        abs_path = source.absolute_path(file_path)
        async with _reading_slot():
            text, pages, ocr_pages = await asyncio.to_thread(
                _read_file, str(abs_path), filename
            )
    except Exception as exc:  # noqa: BLE001 — stan zamiast wyjątku w zadaniu tła
        logger.warning(
            "[umowy] odczyt pliku %s %s nieudany: %s",
            source.label,
            document_id,
            type(exc).__name__,
        )
        await _save_state(source, document_id, file_path, text_status=STATUS_FAILED)
        return

    chunks = split_into_chunks(text)[:MAX_CHUNKS]
    vectors = await _embed(chunks) if chunks and embeddings_enabled() else None

    chunk_ids = await _store_chunks(
        source, document_id, file_path, chunks, pages, ocr_pages
    )
    if chunk_ids is None:
        return
    client = embedding_service._get_qdrant_client()
    if client is None:
        return
    if not chunks or vectors is None:
        # Punkty poprzedniego pliku nie mają już wierszy w bazie — sprzątamy.
        await _qdrant_call(
            lambda: delete_points(client, document_id, source.payload_key)
        )
        return
    if await _qdrant_call(
        lambda: replace_points(
            client, document_id, chunk_ids, vectors, source.payload_key
        )
    ):
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(source.model)
                .where(
                    source.model.id == document_id,
                    source.model.text_file_path == file_path,
                    source.model.text_status == STATUS_TEXT_ONLY,
                )
                .values(
                    text_status=STATUS_INDEXED,
                    text_model=embedding_service._voyage_model(),
                    updated_at=source.model.updated_at,
                )
            )
            await db.commit()


async def index_contract(contract_id: int) -> None:
    """Czyta plik umowy i odbudowuje jej fragmenty oraz wektory."""
    await _index_document(_CONTRACT, contract_id)


async def index_amendment(amendment_id: int) -> None:
    """Czyta plik aneksu i odbudowuje jego fragmenty oraz wektory."""
    await _index_document(_AMENDMENT, amendment_id)


async def delete_contract_points(contract_id: int) -> None:
    client = embedding_service._get_qdrant_client()
    if client is not None:
        await _qdrant_call(lambda: delete_points(client, contract_id))


async def delete_amendment_points(amendment_id: int) -> None:
    client = embedding_service._get_qdrant_client()
    if client is not None:
        await _qdrant_call(
            lambda: delete_points(client, amendment_id, PAYLOAD_AMENDMENT_ID)
        )


def index_after_upload(contract_id: int) -> None:
    """Po wgraniu albo podmianie pliku: odczyt w tle, żądanie nie czeka."""
    start_indexing(contract_id)


def index_amendment_after_upload(amendment_id: int) -> None:
    """Po wgraniu aneksu: odczyt w tle, żądanie nie czeka."""
    start_amendment_indexing(amendment_id)


def forget_after_delete(contract_id: int) -> None:
    """Po trwałym usunięciu umowy (wiersze fragmentów znikają kaskadą)."""
    spawn(
        delete_contract_points(contract_id),
        f"framework-contract-forget:{contract_id}",
    )


def forget_amendment_after_delete(amendment_id: int) -> None:
    """Po usunięciu aneksu (wiersze fragmentów znikają kaskadą)."""
    spawn(
        delete_amendment_points(amendment_id),
        f"client-amendment-forget:{amendment_id}",
    )


def needs_indexing(contract: Any, *, now: Optional[datetime] = None) -> bool:
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


def _start_once(key: Any, coroutine_factory: Callable[[], Any], name: str) -> Any:
    """Jeden bieg naraz na dokument w procesie; zwraca trwający albo nowy."""
    task = _inflight.get(key)
    if task is None or task.done():
        task = spawn(coroutine_factory(), name)
        _inflight[key] = task

        def _done(finished: "asyncio.Task[None]") -> None:
            if _inflight.get(key) is finished:
                del _inflight[key]

        task.add_done_callback(_done)
    return task


def start_indexing(contract_id: int) -> "asyncio.Task[None]":
    return _start_once(
        contract_id,
        lambda: index_contract(contract_id),
        f"framework-contract-index:{contract_id}",
    )


def start_amendment_indexing(amendment_id: int) -> "asyncio.Task[None]":
    return _start_once(
        ("amendment", amendment_id),
        lambda: index_amendment(amendment_id),
        f"client-amendment-index:{amendment_id}",
    )


async def ensure_indexed(
    db: AsyncSession,
    contracts: Sequence[Any],
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
        task = (
            start_amendment_indexing(contract.id)
            if isinstance(contract, ClientContractAmendment)
            else start_indexing(contract.id)
        )
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


def has_current_text(contract: Any) -> bool:
    return (
        contract.file_path is not None
        and contract.text_file_path == contract.file_path
        and contract.text_status in (STATUS_INDEXED, STATUS_TEXT_ONLY)
    )


def reading_note(contract: Any) -> Optional[str]:
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
            "Z pliku odczytano mało tekstu: część stron może nie być w treści. "
            "Resztę trzeba sprawdzić w PDF-ie."
        )
    # Test paczki 30.10.2026: data wpisana długopisem (mLeasing, KIR) daje w OCR
    # znaki bez sensu, a reszta skanu czyta się dobrze.
    if contract.text_ocr_pages:
        return (
            "Część stron to skan: pismo ręczne, np. wpisaną datę zawarcia, "
            "trzeba sprawdzić w PDF-ie."
        )
    return None


def _chunk_ref(row: Any) -> ChunkRef:
    return ChunkRef(
        id=int(row.id),
        contract_id=int(row.framework_contract_id),
        index=int(row.chunk_index),
        text=row.text,
        amendment_id=row.amendment_id,
    )


_CHUNK_COLUMNS = (
    ClientFrameworkContractChunk.id,
    ClientFrameworkContractChunk.framework_contract_id,
    ClientFrameworkContractChunk.chunk_index,
    ClientFrameworkContractChunk.text,
    ClientFrameworkContractChunk.amendment_id,
)


async def load_chunks(
    db: AsyncSession,
    contract_ids: Sequence[int],
    amendment_ids: Sequence[int] = (),
) -> list[ChunkRef]:
    """Fragmenty umów (bez ich aneksów) i wskazanych aneksów."""
    conditions = []
    if contract_ids:
        conditions.append(
            and_(
                ClientFrameworkContractChunk.framework_contract_id.in_(contract_ids),
                ClientFrameworkContractChunk.amendment_id.is_(None),
            )
        )
    if amendment_ids:
        conditions.append(ClientFrameworkContractChunk.amendment_id.in_(amendment_ids))
    if not conditions:
        return []
    rows = await db.execute(
        select(*_CHUNK_COLUMNS)
        .where(or_(*conditions))
        .order_by(
            ClientFrameworkContractChunk.framework_contract_id,
            ClientFrameworkContractChunk.amendment_id.nulls_first(),
            ClientFrameworkContractChunk.chunk_index,
        )
    )
    return [_chunk_ref(row) for row in rows]


async def vector_ranking(
    query: str, contract_ids: Sequence[int], amendment_ids: Sequence[int] = ()
) -> Optional[list[int]]:
    """Identyfikatory fragmentów najbliższych pytaniu; ``None`` = wektory niedostępne."""
    if not (contract_ids or amendment_ids) or not embeddings_enabled():
        return None
    vector = await embedding_service.generate_embedding(query, input_type="query")
    if vector is None:
        return None
    client = embedding_service._get_qdrant_client()
    if client is None:
        return None
    try:
        return await embedding_service._run_qdrant(
            lambda: search_points(
                client, vector, contract_ids, VECTOR_HITS, amendment_ids
            )
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
    db: AsyncSession,
    contracts: Sequence[ClientFrameworkContract],
    query: str,
    amendments: Sequence[ClientContractAmendment] = (),
) -> SearchOutcome:
    """Fragmenty umów i aneksów pasujące do pytania: po znaczeniu i po słowach (RRF)."""
    readable = [contract for contract in contracts if has_current_text(contract)]
    readable_amendments = [a for a in amendments if has_current_text(a)]
    chunks = await load_chunks(
        db,
        [contract.id for contract in readable],
        [amendment.id for amendment in readable_amendments],
    )
    if not chunks:
        return SearchOutcome([], RETRIEVAL_NONE)
    keyword_ids = rank_by_keywords(query_stems(query), chunks)
    vector_ids = await vector_ranking(
        query,
        [c.id for c in readable if c.text_status == STATUS_INDEXED],
        [a.id for a in readable_amendments if a.text_status == STATUS_INDEXED],
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
