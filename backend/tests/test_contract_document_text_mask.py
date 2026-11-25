"""Treść podpisanych umów do Voyage tylko z danymi osoby jako znacznikami.

Przegląd bezpieczeństwa 25.11: fragmenty umowy Partnera szły do embeddingu
jawnie (imię i nazwisko, firma, NIP, adres). W Postgresie zostaje pełny tekst —
maska dotyczy wyłącznie tego, co wychodzi do dostawcy wektorów. Bez bazy.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.services.contract_document_text import index
from app.services.legal.pseudonymize import partner_entities

PARTNER = {
    "full_name": "Jan Kowalski",
    "company": "Kowalski Consulting",
    "address": "ul. Długa 5",
    "postal_city": "00-001 Warszawa",
    "nip": "123-456-32-18",
    "regon": "",
    "email": "jan.kowalski@example.com",
    "phone": "600 100 200",
}
TEXT = (
    "Umowa zawarta pomiędzy Janem Kowalskim, prowadzącym działalność jako "
    "Kowalski Consulting, ul. Długa 5, 00-001 Warszawa, NIP 1234563218, "
    "e-mail jan.kowalski@example.com, tel. 600 100 200. Okres wypowiedzenia: 30 dni."
)


def test_masked_chunks_have_no_personal_data():
    (masked,) = index.masked_for_embedding([TEXT], partner_entities(PARTNER))
    lowered = masked.lower()
    for leak in ("kowalsk", "długa", "1234563218", "example.com", "600 100 200", "00-001"):
        assert leak not in lowered, leak
    assert "Okres wypowiedzenia: 30 dni." in masked


@pytest.mark.asyncio
async def test_index_document_embeds_masked_text_and_stores_full_text(monkeypatch):
    seen: dict = {}

    class _Db:
        async def execute(self, _stmt):
            row = SimpleNamespace(file_path="k/1.pdf", filename="umowa.pdf", doc_type="contract")
            return SimpleNamespace(first=lambda: row)

        async def scalar(self, _stmt):
            return 77

    @asynccontextmanager
    async def session():
        yield _Db()

    @asynccontextmanager
    async def slot():
        yield None

    async def fake_partner(_db, contract_id):
        assert contract_id == 77
        return dict(PARTNER)

    async def fake_embed(texts):
        seen["embedded"] = list(texts)
        return None

    async def fake_store(_doc_id, _path, chunks, _pages, _ocr):
        seen["stored"] = list(chunks)
        return None

    from app.services.trainings import agreement

    monkeypatch.setattr(index, "AsyncSessionLocal", session)
    monkeypatch.setattr(index, "is_read_type", lambda _t: True)
    monkeypatch.setattr(index.storage_service, "get_contract_document_path", lambda p: p)
    monkeypatch.setattr(index, "_reading_slot", slot)
    monkeypatch.setattr(index, "_read_file", lambda _p, _n: (TEXT, 1, 0))
    monkeypatch.setattr(index, "embeddings_enabled", lambda: True)
    monkeypatch.setattr(index, "_embed", fake_embed)
    monkeypatch.setattr(index, "_store_chunks", fake_store)
    monkeypatch.setattr(agreement, "partner_from_contract", fake_partner)

    await index.index_document(5)
    assert "".join(seen["stored"]) == TEXT
    assert "kowalsk" not in " ".join(seen["embedded"]).lower()
    assert "[PARTNER]" in " ".join(seen["embedded"])
