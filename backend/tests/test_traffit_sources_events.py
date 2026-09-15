"""Audyt statystyk 14.09.2026, A05: źródła z Traffita zasilają raport źródeł.

Faza ``candidate_sources`` zapisywała źródło Traffita WYŁĄCZNIE jako tag
``{"type": "traffit_source", ...}`` w ``candidates.tags``. Raport
``/api/reports/sources`` i widok ``analytics_candidate_first_sources`` czytają
wyłącznie ``candidate_source_events`` — więc ~49 tys. kandydatów z importu
miało w raporcie źródeł zero wierszy.

Prawdziwy Postgres: idempotencja stoi na SELECT-cie po prefiksie ``note``,
a zapis idzie przez ORM wewnątrz savepointu kandydata — atrapa bazy nie
udowodniłaby ani jednego, ani drugiego.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.services.traffit.importer import (
    TRAFFIT_SOURCE_NO_DATE_MARK,
    TraffitImporter,
    traffit_source_channel,
    traffit_source_ref,
)

UTC = timezone.utc


class _FakeTraffit:
    """Oddaje zadane rekordy ``/sources/`` niezależnie od argumentów strony."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records

    async def total_count(self, path: str) -> int:
        return len(self.records)

    async def get_paginated(self, path: str, **kwargs: Any):
        assert path == "/sources/"
        for record in self.records:
            yield record


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Any]:
    async with AsyncSessionLocal() as session:
        yield session


async def _mk_candidate(db, ext: str, *, tags: list[dict] | None = None) -> int:
    row = await db.execute(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname, tags,
                created_at, updated_at
            ) VALUES (:e, 'traffit', 'Src', 'Test', CAST(:tags AS JSONB), NOW(), NOW())
            RETURNING id
            """
        ),
        {"e": ext, "tags": json.dumps(tags or [])},
    )
    cid = row.scalar_one()
    await db.commit()
    return cid


async def _events(db, candidate_id: int) -> list[CandidateSourceEvent]:
    db.expire_all()
    rows = await db.execute(
        select(CandidateSourceEvent)
        .where(CandidateSourceEvent.candidate_id == candidate_id)
        .order_by(CandidateSourceEvent.id)
    )
    return list(rows.scalars().all())


async def _tags(db, candidate_id: int) -> list[dict]:
    row = await db.execute(
        text("SELECT tags FROM candidates WHERE id = :c"), {"c": candidate_id}
    )
    return row.scalar_one() or []


async def _cleanup(db, candidate_ids: list[int]) -> None:
    await db.rollback()
    await db.execute(
        text("DELETE FROM candidates WHERE id = ANY(:ids)"), {"ids": candidate_ids}
    )
    await db.commit()


def _source(source_id: int, ext: str, value: str, **extra: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": source_id,
        "employee": {"id": int(ext)},
        "dictionary_item": {"id": 1, "value": value},
        "domain": None,
        "url": None,
    }
    record.update(extra)
    return record


def _ext() -> str:
    # Traffit `employee.id` jest liczbą; mapa external_id → id kluczuje po str.
    return str(uuid.uuid4().int % 10**9)


# ── Normalizacja kanału (bez bazy) ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "domain", "channel"),
    [
        ("LinkedIn", "linkedin.com", SourceChannel.aktywny_search),
        ("Polecenie pracownika", None, SourceChannel.referral),
        ("Pracuj.pl", "pracuj.pl", SourceChannel.posting),
        ("Formularz aplikacyjny", None, SourceChannel.posting),
        ("E-mail", None, SourceChannel.email),
        ("Dodany manualnie", None, SourceChannel.manual),
        ("Załącznik CV", None, SourceChannel.cv_upload),
        ("Baza zewnętrzna XYZ", None, SourceChannel.import_csv),
        (None, None, SourceChannel.import_csv),
    ],
)
def test_traffit_source_channel_keyword_mapping(value, domain, channel) -> None:
    assert traffit_source_channel(value, domain) is channel


# ── Import: tag + dokładnie jedno zdarzenie, idempotentnie ──────────────────


@pytest.mark.asyncio
async def test_source_import_writes_tag_and_exactly_one_event(db) -> None:
    ext = _ext()
    cid = await _mk_candidate(db, ext)
    source_id = uuid.uuid4().int % 10**9
    created_at = "2025-03-04 10:20:30"
    traffit = _FakeTraffit(
        [
            _source(
                source_id, ext, "LinkedIn", domain="linkedin.com", created_at=created_at
            )
        ]
    )
    try:
        progress = await TraffitImporter(traffit, db).import_candidate_sources()
        assert progress.errors == 0, progress.error_samples
        assert progress.inserted == 1
        assert progress.updated == 1

        tags = await _tags(db, cid)
        assert [t["source_id"] for t in tags if t.get("type") == "traffit_source"] == [
            source_id
        ]

        events = await _events(db, cid)
        assert len(events) == 1
        event = events[0]
        assert event.channel is SourceChannel.aktywny_search
        assert event.captured_at == datetime(2025, 3, 4, 10, 20, 30, tzinfo=UTC)
        assert event.note.startswith(traffit_source_ref(source_id))
        assert "LinkedIn" in event.note
        assert TRAFFIT_SOURCE_NO_DATE_MARK not in event.note

        # Ponowny import (delta z nakładką albo pełny przebieg) nie dubluje.
        again = await TraffitImporter(traffit, db).import_candidate_sources()
        assert again.errors == 0, again.error_samples
        assert again.updated == 0
        assert again.skipped == 1
        assert len(await _events(db, cid)) == 1
    finally:
        await _cleanup(db, [cid])


@pytest.mark.asyncio
async def test_source_without_date_gets_import_time_and_says_so(db) -> None:
    ext = _ext()
    cid = await _mk_candidate(db, ext)
    source_id = uuid.uuid4().int % 10**9
    traffit = _FakeTraffit([_source(source_id, ext, "Polecenie")])
    try:
        before = datetime.now(UTC)
        progress = await TraffitImporter(traffit, db).import_candidate_sources()
        after = datetime.now(UTC)
        assert progress.errors == 0, progress.error_samples

        events = await _events(db, cid)
        assert len(events) == 1
        event = events[0]
        assert event.channel is SourceChannel.referral
        assert before <= event.captured_at <= after
        assert event.captured_at == progress.started_at
        assert TRAFFIT_SOURCE_NO_DATE_MARK in event.note
    finally:
        await _cleanup(db, [cid])


@pytest.mark.asyncio
async def test_tag_imported_before_the_fix_still_gets_its_event(db) -> None:
    """Dedup tagów NIE może bramkować zdarzenia.

    Produkcja ma dziesiątki tysięcy tagów zapisanych zanim faza zaczęła pisać
    zdarzenia. Gdyby zdarzenie powstawało tylko razem z NOWYM tagiem, pełny
    przebieg nigdy by ich nie uzupełnił — a to jedyna droga do backfillu.
    """
    ext = _ext()
    source_id = uuid.uuid4().int % 10**9
    existing_tag = {
        "type": "traffit_source",
        "source_id": source_id,
        "value": "Pracuj.pl",
        "domain": "pracuj.pl",
        "url": None,
    }
    cid = await _mk_candidate(db, ext, tags=[existing_tag])
    traffit = _FakeTraffit(
        [
            _source(
                source_id, ext, "Pracuj.pl", domain="pracuj.pl", created_at="2024-11-01"
            )
        ]
    )
    try:
        progress = await TraffitImporter(traffit, db).import_candidate_sources()
        assert progress.errors == 0, progress.error_samples
        assert progress.inserted == 0  # tag już był
        assert progress.updated == 1  # zdarzenie — nie

        assert len(await _tags(db, cid)) == 1
        events = await _events(db, cid)
        assert len(events) == 1
        assert events[0].channel is SourceChannel.posting
        assert events[0].captured_at == datetime(2024, 11, 1, tzinfo=UTC)
    finally:
        await _cleanup(db, [cid])


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(db) -> None:
    ext = _ext()
    cid = await _mk_candidate(db, ext)
    traffit = _FakeTraffit([_source(uuid.uuid4().int % 10**9, ext, "LinkedIn")])
    try:
        progress = await TraffitImporter(
            traffit, db, dry_run=True
        ).import_candidate_sources()
        assert progress.inserted == 1
        assert await _tags(db, cid) == []
        assert await _events(db, cid) == []
    finally:
        await _cleanup(db, [cid])


@pytest.mark.asyncio
async def test_undated_mark_survives_note_truncation(db) -> None:
    """Raporty rozpoznają zmyśloną datę po SUFIKSIE `note`.

    `note` ma 500 znaków; dopisek przycięty razem z długą nazwą źródła
    wpuściłby zdarzenie z datą importu do okna raportu źródeł.
    """
    ext = _ext()
    cid = await _mk_candidate(db, ext)
    traffit = _FakeTraffit([_source(uuid.uuid4().int % 10**9, ext, "X" * 700)])
    try:
        progress = await TraffitImporter(traffit, db).import_candidate_sources()
        assert progress.errors == 0, progress.error_samples

        events = await _events(db, cid)
        assert len(events) == 1
        assert len(events[0].note) <= 500
        assert events[0].note.endswith(TRAFFIT_SOURCE_NO_DATE_MARK)
    finally:
        await _cleanup(db, [cid])
