"""Indeks treści umów ramowych: fragmenty w bazie, wektory w Qdrancie (0426).

Bez sieci: Qdrant i Voyage są podstawione. Treść umów jest fikcyjna.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from qdrant_client import models as qmodels
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_framework_contract_chunk import ClientFrameworkContractChunk
from app.services import embedding_service
from app.services import framework_contract_index as fci
from app.services.framework_contract_text_schema import (
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_TEXT_ONLY,
    STATUS_UNREADABLE,
)

_FILLER = (
    "Wykonawca zobowiązuje się świadczyć Usługi z należytą starannością, zgodnie "
    "z Umową oraz obowiązującymi przepisami prawa.\n"
)
_CLAUSE = (
    "§ 7 Rozliczenia\n"
    "1. Specjalista sporządza Kartę Ewidencji Świadczenia Usług za każdy miesiąc.\n"
    "2. Zamawiający akceptuje Kartę albo zgłasza uwagi w terminie 5 Dni Roboczych "
    "od dnia jej otrzymania.\n"
)
_TEXT = (_FILLER * 30) + _CLAUSE + (_FILLER * 30)


class _FakeQdrant:
    def __init__(self, *, collections=(), hits=()):
        self.calls: list[tuple[str, dict]] = []
        self._collections = list(collections)
        self.hits = list(hits)

    def get_collections(self):
        self.calls.append(("get_collections", {}))
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self._collections]
        )

    def create_collection(self, **kwargs):
        self.calls.append(("create_collection", kwargs))
        self._collections.append(kwargs["collection_name"])

    def create_payload_index(self, **kwargs):
        self.calls.append(("create_payload_index", kwargs))

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))

    def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return [SimpleNamespace(id=hit) for hit in self.hits]

    def names(self) -> list[str]:
        return [name for name, _kwargs in self.calls]


# ── Qdrant ──────────────────────────────────────────────────────────────────


def test_collection_name_is_safe_from_candidate_deletion():
    """``delete_candidate_embedding`` kasuje punkt o id kandydata z każdej
    kolekcji ``nexus_candidates*`` — fragment umowy o tym numerze by zniknął."""
    assert not fci.COLLECTION.startswith("nexus_candidates")


def test_replace_deletes_old_points_before_writing_new_ones():
    client = _FakeQdrant()

    fci.replace_points(client, 40, [101, 102], [[0.1] * 4, [0.2] * 4])

    assert client.names() == [
        "get_collections",
        "create_collection",
        "create_payload_index",
        "delete",
        "upsert",
    ]
    created = client.calls[1][1]
    assert created["collection_name"] == fci.COLLECTION
    assert created["vectors_config"].size == embedding_service.VECTOR_SIZE
    assert created["vectors_config"].distance == qmodels.Distance.COSINE
    index = client.calls[2][1]
    assert index["field_name"] == fci.PAYLOAD_CONTRACT_ID
    selector = client.calls[3][1]["points_selector"]
    assert selector.filter.must[0].match.any == [40]
    points = client.calls[4][1]["points"]
    assert [point.id for point in points] == [101, 102]
    assert all(point.payload[fci.PAYLOAD_CONTRACT_ID] == 40 for point in points)
    # Treść umowy zostaje w bazie — do Qdranta idą same wektory.
    assert all("text" not in point.payload for point in points)


def test_existing_collection_is_not_recreated():
    client = _FakeQdrant(collections=[fci.COLLECTION])

    fci.ensure_collection(client)

    assert "create_collection" not in client.names()


def test_missing_collection_means_nothing_to_delete():
    class _Missing(_FakeQdrant):
        def delete(self, **kwargs):
            raise RuntimeError("Collection `nexus_client_documents` doesn't exist!")

    fci.delete_points(_Missing(), 40)

    class _Down(_FakeQdrant):
        def delete(self, **kwargs):
            raise ConnectionError("connection refused")

    with pytest.raises(ConnectionError):
        fci.delete_points(_Down(), 40)


def test_search_is_filtered_by_contracts():
    client = _FakeQdrant(hits=[7, 9])

    assert fci.search_points(client, [0.1] * 4, [40, 41], 12) == [7, 9]
    kwargs = client.calls[0][1]
    assert kwargs["query_filter"].must[0].match.any == [40, 41]
    assert kwargs["with_payload"] is False


# ── kiedy czytać plik ───────────────────────────────────────────────────────


def _contract(**values):
    base = dict(
        id=40,
        file_path="client_framework_contracts/7/a-msa.pdf",
        text_file_path="client_framework_contracts/7/a-msa.pdf",
        text_status=STATUS_INDEXED,
        text_attempted_at=datetime.now(timezone.utc),
        text_pages=None,
        text_chars=1000,
    )
    base.update(values)
    return SimpleNamespace(**base)


def test_contract_without_file_is_never_read():
    assert fci.needs_indexing(_contract(file_path=None, text_file_path=None)) is False


def test_new_or_replaced_file_is_read():
    assert fci.needs_indexing(_contract(text_file_path=None, text_status=None))
    assert fci.needs_indexing(_contract(text_file_path="old.pdf"))


def test_indexed_and_unreadable_are_final_until_the_file_changes():
    assert fci.needs_indexing(_contract()) is False
    old = datetime.now(timezone.utc) - timedelta(days=3)
    assert (
        fci.needs_indexing(
            _contract(text_status=STATUS_UNREADABLE, text_attempted_at=old)
        )
        is False
    )


@pytest.mark.parametrize("status", [STATUS_TEXT_ONLY, STATUS_FAILED])
def test_missing_vectors_and_failed_read_retry_after_a_pause(status):
    now = datetime.now(timezone.utc)
    recent = _contract(text_status=status, text_attempted_at=now - timedelta(minutes=2))
    stale = _contract(text_status=status, text_attempted_at=now - timedelta(minutes=30))

    assert fci.needs_indexing(recent, now=now) is False
    assert fci.needs_indexing(stale, now=now) is True


def test_text_only_is_final_when_embeddings_are_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "FRAMEWORK_CONTRACT_EMBEDDINGS_ENABLED", False)
    old = datetime.now(timezone.utc) - timedelta(days=1)

    assert (
        fci.needs_indexing(
            _contract(text_status=STATUS_TEXT_ONLY, text_attempted_at=old)
        )
        is False
    )


def test_reading_note_names_the_reason():
    assert "Brak wgranego pliku" in fci.reading_note(_contract(file_path=None))
    assert "właśnie czytany" in fci.reading_note(_contract(text_file_path=None))
    assert "nie da się odczytać" in fci.reading_note(
        _contract(text_status=STATUS_UNREADABLE)
    )
    assert "nie udał" in fci.reading_note(_contract(text_status=STATUS_FAILED))
    # 43 strony i 2000 znaków = skan, z którego OCR przeczytał początek.
    assert "skan" in fci.reading_note(_contract(text_pages=43, text_chars=2000))
    assert fci.reading_note(_contract(text_pages=43, text_chars=108_000)) is None


@pytest.mark.asyncio
async def test_embedding_goes_in_batches_and_is_all_or_nothing(monkeypatch):
    sizes: list[int] = []

    async def _batch(texts, *, input_type):
        assert input_type == "document"
        sizes.append(len(texts))
        return [[0.5] * 4 for _ in texts]

    monkeypatch.setattr(embedding_service, "_voyage_embed_batch", _batch)
    vectors = await fci._embed(["x"] * (fci.EMBED_BATCH + 5))
    assert sizes == [fci.EMBED_BATCH, 5]
    assert len(vectors) == fci.EMBED_BATCH + 5

    async def _partial(texts, *, input_type):
        return [[0.5] * 4, None][: len(texts)]

    monkeypatch.setattr(embedding_service, "_voyage_embed_batch", _partial)
    assert await fci._embed(["a", "b"]) is None

    async def _down(texts, *, input_type):
        return None

    monkeypatch.setattr(embedding_service, "_voyage_embed_batch", _down)
    assert await fci._embed(["a"]) is None


# ── pełny przebieg na bazie ─────────────────────────────────────────────────


async def _seed(*, file_path: str | None = "client_framework_contracts/x/msa.pdf"):
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Umowy Jarvis {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        fc = ClientFrameworkContract(
            client_id=client.id,
            name="Umowa ramowa 2026",
            status=FrameworkContractStatus.active,
            filename="msa.pdf" if file_path else None,
            file_path=f"{file_path}-{uuid.uuid4().hex[:6]}" if file_path else None,
        )
        db.add(fc)
        await db.commit()
        return client.id, fc.id


async def _cleanup(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientFrameworkContract.__table__.delete().where(
                ClientFrameworkContract.client_id == client_id
            )
        )
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.commit()


async def _state(fc_id: int):
    async with AsyncSessionLocal() as db:
        fc = await db.get(ClientFrameworkContract, fc_id)
        chunk_ids = list(
            await db.scalars(
                select(ClientFrameworkContractChunk.id)
                .where(ClientFrameworkContractChunk.framework_contract_id == fc_id)
                .order_by(ClientFrameworkContractChunk.chunk_index)
            )
        )
        return fc, chunk_ids


@pytest.fixture
def pipeline(monkeypatch):
    """Plik, Voyage i Qdrant podstawione; zwraca uchwyty do sterowania nimi."""
    box = SimpleNamespace(
        text=_TEXT, pages=3, vectors=True, qdrant=_FakeQdrant(), read_error=None
    )

    def _read(_path, _filename):
        if box.read_error is not None:
            raise box.read_error
        return box.text, box.pages

    async def _batch(texts, *, input_type):
        return [[0.1] * 4 for _ in texts] if box.vectors else None

    async def _query(text, *, input_type="document", use_cache=True):
        return [0.1] * 4 if box.vectors else None

    monkeypatch.setattr(fci, "_read_file", _read)
    monkeypatch.setattr(
        fci.storage_service,
        "get_client_framework_contract_path",
        lambda relative: relative,
    )
    monkeypatch.setattr(embedding_service, "_voyage_embed_batch", _batch)
    monkeypatch.setattr(embedding_service, "generate_embedding", _query)
    monkeypatch.setattr(embedding_service, "_get_qdrant_client", lambda: box.qdrant)
    monkeypatch.setattr(embedding_service, "_voyage_model", lambda: "voyage-test")
    return box


@pytest.mark.asyncio
async def test_contract_is_chunked_embedded_and_marked_indexed(pipeline):
    client_id, fc_id = await _seed()
    try:
        await fci.index_contract(fc_id)

        fc, chunk_ids = await _state(fc_id)
        assert fc.text_status == STATUS_INDEXED
        assert fc.text_file_path == fc.file_path
        assert fc.text_model == "voyage-test"
        assert fc.text_chars == len(_TEXT) and fc.text_pages == 3
        assert len(chunk_ids) > 5
        upsert = next(k for name, k in pipeline.qdrant.calls if name == "upsert")
        assert [point.id for point in upsert["points"]] == chunk_ids
    finally:
        await _cleanup(client_id)


@pytest.mark.asyncio
async def test_reading_state_does_not_touch_updated_at(pipeline):
    """Odczyt pliku to nie edycja umowy — ``updated_at`` zostaje."""
    client_id, fc_id = await _seed()
    try:
        before, _ = await _state(fc_id)
        await fci.index_contract(fc_id)
        after, _ = await _state(fc_id)
        assert after.updated_at == before.updated_at
    finally:
        await _cleanup(client_id)


@pytest.mark.asyncio
async def test_without_vectors_the_text_still_answers_by_keywords(pipeline):
    pipeline.vectors = False
    client_id, fc_id = await _seed()
    try:
        await fci.index_contract(fc_id)
        fc, chunk_ids = await _state(fc_id)
        assert fc.text_status == STATUS_TEXT_ONLY and fc.text_model is None
        assert chunk_ids
        assert "upsert" not in pipeline.qdrant.names()

        async with AsyncSessionLocal() as db:
            contract = await db.get(ClientFrameworkContract, fc_id)
            outcome = await fci.search(
                db, [contract], "ile czasu na akceptację karty czasu pracy"
            )
        assert outcome.retrieval == fci.RETRIEVAL_KEYWORDS
        assert "5 Dni Roboczych" in outcome.passages[0].text
    finally:
        await _cleanup(client_id)


@pytest.mark.asyncio
async def test_hybrid_search_uses_vector_hits_and_drops_orphans(pipeline):
    client_id, fc_id = await _seed()
    try:
        await fci.index_contract(fc_id)
        _, chunk_ids = await _state(fc_id)
        # Pytanie bez wspólnych słów z umową: trafia wyłącznie noga wektorowa.
        # 999_999_999 to punkt bez wiersza w bazie (sierota po dawnym pliku).
        pipeline.qdrant.hits = [999_999_999, chunk_ids[2]]

        async with AsyncSessionLocal() as db:
            contract = await db.get(ClientFrameworkContract, fc_id)
            outcome = await fci.search(db, [contract], "timesheet")

        assert outcome.retrieval == fci.RETRIEVAL_HYBRID
        assert [(p.first_chunk, p.last_chunk) for p in outcome.passages] == [(2, 2)]
        search_call = next(k for name, k in pipeline.qdrant.calls if name == "search")
        assert search_call["query_filter"].must[0].match.any == [fc_id]
    finally:
        await _cleanup(client_id)


@pytest.mark.asyncio
async def test_replaced_file_rebuilds_chunks(pipeline):
    client_id, fc_id = await _seed()
    try:
        await fci.index_contract(fc_id)
        _, first_ids = await _state(fc_id)

        async with AsyncSessionLocal() as db:
            fc = await db.get(ClientFrameworkContract, fc_id)
            fc.file_path = "client_framework_contracts/x/nowa.pdf"
            assert fci.needs_indexing(fc)
            await db.commit()
        pipeline.text = _CLAUSE
        await fci.index_contract(fc_id)

        fc, second_ids = await _state(fc_id)
        assert fc.text_file_path == "client_framework_contracts/x/nowa.pdf"
        assert fc.text_chars == len(_CLAUSE)
        assert not set(first_ids) & set(second_ids)
    finally:
        await _cleanup(client_id)


@pytest.mark.asyncio
async def test_empty_text_is_unreadable_and_failed_read_keeps_a_state(pipeline):
    client_id, fc_id = await _seed()
    try:
        pipeline.text = "   "
        await fci.index_contract(fc_id)
        fc, chunk_ids = await _state(fc_id)
        assert fc.text_status == STATUS_UNREADABLE and chunk_ids == []
        assert fci.has_current_text(fc) is False

        pipeline.read_error = FileNotFoundError("brak pliku")
        await fci.index_contract(fc_id)
        fc, _ = await _state(fc_id)
        assert fc.text_status == STATUS_FAILED
        assert fc.text_file_path == fc.file_path
    finally:
        await _cleanup(client_id)


@pytest.mark.asyncio
async def test_qdrant_outage_leaves_text_only(pipeline):
    class _Down(_FakeQdrant):
        def get_collections(self):
            raise ConnectionError("connection refused")

    pipeline.qdrant = _Down()
    client_id, fc_id = await _seed()
    try:
        await fci.index_contract(fc_id)
        fc, chunk_ids = await _state(fc_id)
        assert fc.text_status == STATUS_TEXT_ONLY
        assert chunk_ids
    finally:
        await _cleanup(client_id)


# ── trasy ───────────────────────────────────────────────────────────────────


def test_search_route_is_registered_before_the_id_route():
    """Inaczej „search” trafia w `/{fc_id}` i kończy się 422."""
    from app.api import client_framework_contracts as api

    paths = [route.path for route in api.router.routes]
    assert paths.index("/{client_id}/framework-contracts/search") < paths.index(
        "/{client_id}/framework-contracts/{fc_id}"
    )


@pytest.mark.asyncio
async def test_search_route_reads_the_file_lazily_and_returns_passages(
    app_client: AsyncClient, app_auth_headers: dict[str, str], pipeline
) -> None:
    client_id, fc_id = await _seed()
    async with AsyncSessionLocal() as db:
        db.add(
            ClientFrameworkContract(
                client_id=client_id,
                name="Umowa z importu (bez pliku)",
                status=FrameworkContractStatus.active,
            )
        )
        await db.commit()
    try:
        resp = await app_client.get(
            f"/api/clients/{client_id}/framework-contracts/search",
            params={"q": "akceptacja karty czasu pracy"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["retrieval"] == fci.RETRIEVAL_HYBRID
        assert any("5 Dni Roboczych" in p["text"] for p in body["passages"])
        assert body["passages"][0]["contract_name"] == "Umowa ramowa 2026"
        by_name = {c["name"]: c for c in body["contracts"]}
        assert by_name["Umowa ramowa 2026"]["readable"] is True
        without_file = by_name["Umowa z importu (bez pliku)"]
        assert without_file["has_file"] is False and without_file["readable"] is False
        assert "Brak wgranego pliku" in without_file["note"]

        async with AsyncSessionLocal() as db:
            stored = await db.scalar(
                select(func.count(ClientFrameworkContractChunk.id)).where(
                    ClientFrameworkContractChunk.framework_contract_id == fc_id
                )
            )
        assert stored > 5
    finally:
        await _cleanup(client_id)


@pytest.mark.asyncio
async def test_text_route_reads_in_order(
    app_client: AsyncClient, app_auth_headers: dict[str, str], pipeline
) -> None:
    client_id, fc_id = await _seed()
    try:
        base = f"/api/clients/{client_id}/framework-contracts/{fc_id}/text"
        first = (await app_client.get(base, headers=app_auth_headers)).json()
        assert first["passage"]["first_chunk"] == 0
        assert first["contract"]["total_chunks"] > 5
        assert first["next_chunk"] == first["passage"]["last_chunk"] + 1

        second = (
            await app_client.get(
                base,
                params={"from_chunk": first["next_chunk"]},
                headers=app_auth_headers,
            )
        ).json()
        assert second["passage"]["first_chunk"] == first["next_chunk"]

        past_end = (
            await app_client.get(
                base, params={"from_chunk": 1999}, headers=app_auth_headers
            )
        ).json()
        assert past_end["passage"] is None and "koniec" in past_end["note"]

        missing = await app_client.get(
            f"/api/clients/{client_id}/framework-contracts/999999999/text",
            headers=app_auth_headers,
        )
        assert missing.status_code == 404
    finally:
        await _cleanup(client_id)


@pytest.mark.asyncio
async def test_search_without_any_readable_contract_says_so(
    app_client: AsyncClient, app_auth_headers: dict[str, str], pipeline
) -> None:
    client_id, _fc_id = await _seed(file_path=None)
    try:
        resp = await app_client.get(
            f"/api/clients/{client_id}/framework-contracts/search",
            params={"q": "termin płatności"},
            headers=app_auth_headers,
        )
        body = resp.json()
        assert resp.status_code == 200, resp.text
        assert body["retrieval"] == fci.RETRIEVAL_NONE
        assert body["passages"] == []
        assert "nie ma treści" in body["note"]
    finally:
        await _cleanup(client_id)
