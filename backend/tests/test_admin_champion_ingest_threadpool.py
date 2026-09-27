"""Runda 9 (R9-X1-6): odczyt pliku Championa (pdfplumber + OCR) poza pętlą."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import admin_champion_ingest as mod


class _Upload:
    filename = "profil.pdf"
    size = 10

    async def read(self, limit: int = -1) -> bytes:
        return b"%PDF-1.4 fake"


@pytest.mark.asyncio
async def test_document_text_is_extracted_off_the_event_loop(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    seen: list[int] = []

    def fake_extract(content: bytes, filename: str) -> str:
        seen.append(threading.get_ident())
        return ""

    monkeypatch.setattr(mod, "extract_document_text", fake_extract)
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(
        id=7, champion_profile=None
    )
    db = AsyncMock()
    db.execute.return_value = result

    handler = mod.champion_ingest.__wrapped__
    resp = await handler(
        request=None,
        current_user=SimpleNamespace(id=1),
        file=_Upload(),
        external_rid="123",
        file_id=5,
        db=db,
    )

    assert resp.status_code == 422  # krótki tekst = no_text
    assert seen and seen[0] != loop_thread
