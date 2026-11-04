"""Doganianie starszej wersji promptu w nocnym odczycie notatek (22.09.2026).

Kandydat, którego notatki się nie zmieniły, a fakty policzono promptem sprzed
trybu pracy, ma dostać ponowny odczyt — ale PO kandydatach z nowymi
notatkami i bez wierszy „bez treści”.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.note import Note, NoteType
from app.services.notes_insights_extractor import EXTRACTION_MODEL, PROMPT_VERSION
from app.tasks.notes_insights_sync import _select_outdated_candidates


async def _seed(insights: dict | None) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Sync",
            lastname=f"Upgrade-{uuid.uuid4().hex[:6]}",
            email=f"notes-sync-{uuid.uuid4().hex[:8]}@example.com",
            cv_extracted_data={"_notes_insights": insights}
            if insights is not None
            else None,
        )
        db.add(cand)
        await db.flush()
        db.add(
            Note(
                content="Kandydat woli hybrydę, 2 dni w biurze.",
                note_type=NoteType.general,
                candidate_id=cand.id,
            )
        )
        await db.commit()
        return cand.id


@pytest.mark.asyncio
async def test_outdated_rows_are_selected_current_and_empty_are_not():
    old = await _seed({"_extractor": "notes_insights:v4-onsite-days:haiku-4.5"})
    legacy = await _seed({"expected_rate": {"value": 150}})
    current = await _seed(
        {"_extractor": f"notes_insights:{PROMPT_VERSION}:{EXTRACTION_MODEL}"}
    )
    no_content = await _seed({"_no_content": True})
    never = await _seed(None)

    picked = await _select_outdated_candidates(10_000, exclude=set())
    assert old in picked
    assert legacy in picked
    assert current not in picked
    assert no_content not in picked
    assert never not in picked, "brak ekstrakcji to sprawa selekcji po notatkach"

    assert old not in await _select_outdated_candidates(10_000, exclude={old})
    assert await _select_outdated_candidates(0, exclude=set()) == []


def _deepseek_402():
    import anthropic
    import httpx

    from app.services.llm_providers import _status_error

    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(
        402,
        request=request,
        json={"error": {"message": "Insufficient Balance", "type": "unknown_error"}},
    )
    err = _status_error("deepseek", response)
    assert type(err) is anthropic.APIStatusError
    return err


@pytest.mark.asyncio
async def test_run_stops_at_first_provider_account_error(monkeypatch):
    """25.09.2026: saldo DeepSeek −0,01 USD → 402 dla KAŻDEGO z ~1000
    kandydatów biegu, czyli ~1000 zdarzeń Sentry na noc. Błąd konta dostawcy
    jest identyczny dla każdego kandydata — bieg ma stanąć na pierwszym."""
    import app.tasks.notes_insights_sync as sync

    ids = [await _seed(None) for _ in range(3)]
    async with AsyncSessionLocal() as db:
        for cid in ids:
            db.add(
                Note(
                    content="Stawka 150 zł/h netto B2B, dostępny od zaraz, "
                    "woli pracę zdalną, dwa dni w biurze w Warszawie.",
                    note_type=NoteType.general,
                    candidate_id=cid,
                )
            )
        await db.commit()

    async def _stale(limit):
        return list(ids)

    async def _outdated(limit, exclude):
        return []

    calls: list[str] = []

    async def _extract(blob):
        calls.append(blob)
        raise _deepseek_402()

    monkeypatch.setattr(sync, "_select_stale_candidates", _stale)
    monkeypatch.setattr(sync, "_select_outdated_candidates", _outdated)
    monkeypatch.setattr(sync, "extract_insights", _extract)

    stats = await sync.run_notes_insights_sync()

    assert len(calls) == 1, "po 402 nie wolno pytać dostawcy o kolejnych kandydatów"
    assert stats["status"] == "provider_unavailable"
    assert stats["provider_error"] == "HTTP 402"
    assert stats["errors"] == 1
