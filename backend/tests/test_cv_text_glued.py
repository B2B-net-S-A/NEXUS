"""Ponowny odczyt CV z tekstem SKLEJONYM (słowa bez przerw) — na Postgresie.

Produkcja 23.09.2026: 1 581 z 54 257 CV z tekstem miało średnią długość
„słowa” > 12 znaków („ledtheqainitiativeandthedevelopment…”), więc „qa”,
„tester” czy „devops” w środku ciągu nie były słowami dla wyszukiwarki.
``run_backfill(glued=True)`` czyta je ponownie; tu pilnujemy, że:

* zakres łapie sklejony tekst i nie łapie zwykłego,
* lepszy odczyt zastępuje tekst i przelicza korpus słów kluczowych (trigger),
* odczyt nadal sklejony albo uboższy NIE nadpisuje tekstu i dostaje znacznik,
  który wyjmuje wiersz z zakresu (kolejne noce go nie czytają w kółko).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services import cv_text_backfill as svc
from app.services.cv_text_backfill import ExtractionResult

_GLUED = "ledtheqainitiativeandthedevelopmentofunittestingtoolforcobolprograms " * 8
_SPACED = (
    "led the qa initiative and the development of unit testing tool for cobol programs "
    * 8
)


async def _make(raw: str) -> tuple[int, str]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    key = f"cv/glued-{uuid.uuid4().hex}.pdf"
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Sklejony",
            lastname=uuid.uuid4().hex[:8],
            email=f"glued-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            raw_cv_text=raw,
            cv_storage_key=key,
            cv_filename="cv.pdf",
        )
        db.add(cand)
        await db.commit()
        return cand.id, key


async def _row(cid: int):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT raw_cv_text, keyword_fts::text AS fts, "
                    "cv_extracted_data->'_cv_text_extraction'->>'outcome' AS marker "
                    "FROM candidates WHERE id = :id"
                ),
                {"id": cid},
            )
        ).one()


async def _in_scope(cid: int) -> bool:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ids = {r.id for r in (await db.execute(svc._glued_candidates_stmt(None))).all()}
    return cid in ids


def _stub_extraction(monkeypatch, results: dict[str, ExtractionResult]) -> None:
    def _extract(key, _name):
        if key not in results:
            # Cudze wiersze wspólnej bazy: błąd = brak zapisu, nic nie zmieniamy.
            raise RuntimeError("not this test's row")
        return results[key]

    monkeypatch.setattr(svc, "extract_one", _extract)
    monkeypatch.setattr(svc, "is_available", lambda: True)


@pytest.mark.asyncio
async def test_scope_takes_glued_text_and_leaves_normal_text():
    glued_id, _ = await _make(_GLUED)
    normal_id, _ = await _make(_SPACED)
    assert await _in_scope(glued_id)
    assert not await _in_scope(normal_id)


@pytest.mark.asyncio
async def test_better_read_replaces_text_and_makes_words_searchable(monkeypatch):
    cid, key = await _make(_GLUED)
    assert "'qa'" not in (await _row(cid)).fts, "sklejone — słowa „qa” brak"

    _stub_extraction(monkeypatch, {key: ExtractionResult("extracted", _SPACED)})
    stats = await svc.run_backfill(commit=True, glued=True, enqueue_reindex=False)

    row = await _row(cid)
    assert row.raw_cv_text == _SPACED
    assert "'qa'" in row.fts, "trigger korpusu przeliczył keyword_fts"
    assert row.marker == "extracted"
    assert cid in stats.candidate_ids_written
    assert not await _in_scope(cid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        ExtractionResult("extracted", _GLUED + "jeszczeraz"),  # nadal sklejone
        ExtractionResult("extracted", "led the qa " * 30),  # uboższe w treść
        ExtractionResult("junk"),
    ],
    ids=["still-glued", "less-content", "junk"],
)
async def test_worse_read_keeps_old_text_and_leaves_the_scope(monkeypatch, result):
    cid, key = await _make(_GLUED)
    _stub_extraction(monkeypatch, {key: result})
    await svc.run_backfill(commit=True, glued=True, enqueue_reindex=False)

    row = await _row(cid)
    assert row.raw_cv_text == _GLUED, "gorszy odczyt nie nadpisuje tekstu"
    assert row.marker == svc._STILL_GLUED
    assert not await _in_scope(cid), "kolejna noc nie czyta go ponownie"


@pytest.mark.asyncio
async def test_failed_download_is_deferred_not_dropped(monkeypatch):
    """Runda 6 audytu (T6-4): chwilowy błąd nie zamyka wiersza na zawsze, ale
    też nie wraca co noc na czoło kolejki — czeka na odroczenie."""
    cid, key = await _make(_GLUED)
    _stub_extraction(monkeypatch, {key: ExtractionResult("download_failed")})
    await svc.run_backfill(commit=True, glued=True, enqueue_reindex=False)

    row = await _row(cid)
    assert row.raw_cv_text == _GLUED
    assert row.marker == "download_failed"
    assert not await _in_scope(cid), "odroczony — nie wraca następnej nocy"

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE candidates SET cv_extracted_data = jsonb_set("
                "cv_extracted_data, '{_cv_text_extraction,retry_after}', "
                "to_jsonb('2000-01-01T00:00:00+00:00'::text)) WHERE id = :id"
            ),
            {"id": cid},
        )
        await db.commit()
    assert await _in_scope(cid), "po odroczeniu wiersz dostaje kolejną próbę"
