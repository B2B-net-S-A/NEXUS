"""Pętla retencji Jarvisa nie zdejmuje blokad tur przy starcie (audyt R3, 24.11.2026).

Pętla biegnie w procesie ``worker`` (``app/core/process_role.py``), a tury
w procesach ``web`` — restart workera nie oznacza, że żadna tura nie trwa.
Zdjęcie ``busy_until`` przy starcie otwierało rozmowę na drugą, równoległą
turę. Blokada tury ubitej deployem wygasa sama po ``_lock_seconds()``.
Bez bazy.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.jarvis import store
from app.tasks import jarvis_retention


async def test_loop_start_does_not_release_turn_locks(monkeypatch):
    released: list[bool] = []

    async def release() -> int:
        released.append(True)
        return 1

    async def stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(store, "release_turns_after_restart", release, raising=False)
    monkeypatch.setattr(jarvis_retention.asyncio, "sleep", stop)

    with pytest.raises(asyncio.CancelledError):
        await jarvis_retention.jarvis_retention_loop()

    assert released == []
