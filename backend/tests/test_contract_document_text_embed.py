"""Treść podpisanych umów idzie do Voyage w pełnym brzmieniu.

Decyzja Artura 25.11.2026: umowy z Partnerami jak umowy klientów (zgoda
z 09.10) — embedding dostaje ten sam tekst, który zostaje w Postgresie.
Bez bazy.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.services.contract_document_text import index

TEXT = (
    "Umowa zawarta pomiędzy Zamawiającym a Wykonawcą. "
    "Okres wypowiedzenia: 30 dni ze skutkiem na koniec miesiąca."
)


@pytest.mark.asyncio
async def test_index_document_embeds_the_stored_text(monkeypatch):
    seen: dict = {}

    class _Db:
        async def execute(self, _stmt):
            row = SimpleNamespace(file_path="k/1.pdf", filename="umowa.pdf", doc_type="contract")
            return SimpleNamespace(first=lambda: row)

    @asynccontextmanager
    async def session():
        yield _Db()

    @asynccontextmanager
    async def slot():
        yield None

    async def fake_embed(texts):
        seen["embedded"] = list(texts)
        return None

    async def fake_store(_doc_id, _path, chunks, _pages, _ocr):
        seen["stored"] = list(chunks)
        return None

    monkeypatch.setattr(index, "AsyncSessionLocal", session)
    monkeypatch.setattr(index, "is_read_type", lambda _t: True)
    monkeypatch.setattr(index.storage_service, "get_contract_document_path", lambda p: p)
    monkeypatch.setattr(index, "_reading_slot", slot)
    monkeypatch.setattr(index, "_read_file", lambda _p, _n: (TEXT, 1, 0))
    monkeypatch.setattr(index, "embeddings_enabled", lambda: True)
    monkeypatch.setattr(index, "_embed", fake_embed)
    monkeypatch.setattr(index, "_store_chunks", fake_store)

    await index.index_document(5)
    assert seen["embedded"] == seen["stored"]
    assert "".join(seen["stored"]) == TEXT
