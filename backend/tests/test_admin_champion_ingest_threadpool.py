"""Ingest profili Championa z karty Traffita — od 14.10.2026 zawsze 410.

Do 14.10 test pilnował, że odczyt pliku (pdfplumber + OCR, Runda 9 R9-X1-6)
biegnie poza pętlą. Traffit jest wyłączony na stałe (decyzja Artura,
`app/services/traffit_retired.py`), a collector czyta pliki z karty Traffita —
trasa odpowiada 410 przed odczytem pliku, więc nie ma już czego wątkować.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import admin_champion_ingest as mod
from app.services.traffit_retired import TRAFFIT_RETIRED_MESSAGE


class _Upload:
    filename = "profil.pdf"
    size = 10

    async def read(self, limit: int = -1) -> bytes:
        return b"%PDF-1.4 fake"


@pytest.mark.asyncio
async def test_ingest_answers_410_without_extracting_the_document(
    monkeypatch,
) -> None:
    extracted: list[str] = []

    def fake_extract(content: bytes, filename: str) -> str:
        extracted.append(filename)
        return ""

    monkeypatch.setattr(mod, "extract_document_text", fake_extract)
    db = AsyncMock()

    handler = mod.champion_ingest.__wrapped__
    resp = await handler(
        request=None,
        current_user=SimpleNamespace(id=1),
        file=_Upload(),
        external_rid="123",
        file_id=5,
        db=db,
    )

    assert resp.status_code == 410
    assert TRAFFIT_RETIRED_MESSAGE in resp.body.decode("utf-8")
    assert extracted == []
    db.execute.assert_not_awaited()
