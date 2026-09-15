"""Audyt statystyk 14.09.2026, A05 — domknięcie raportu źródeł.

1. Źródło z importu bez prawdziwej daty ma `captured_at` = data importu.
   Nie może wejść do okna raportu (inaczej pierwszy pełny sync Traffita
   wrzuca całą historyczną atrybucję w „ostatnie 30 dni").
2. Raport nazywa model atrybucji (każdy kontakt) i niesie pokrycie: ilu
   nowych kandydatów nie ma żadnego datowanego źródła.

Prawdziwy Postgres. Baza shardu jest wspólna dla przebiegu i nieczyszczona,
więc raport okna „ostatnie N dni" porównujemy PRZYROSTAMI, a metrykę v1
liczymy w okresie 1983 r., którego nie używa żaden inny test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import delete

from app.analytics import metrics
from app.analytics.periods import Period, PeriodKind
from app.api.candidate_sources import report_sources
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_source_event import (
    UNDATED_IMPORT_NOTE_MARK,
    CandidateSourceEvent,
    SourceChannel,
)

UTC = timezone.utc


async def _report() -> Any:
    async with AsyncSessionLocal() as db:
        return await report_sources(None, db, days=30, group_by_utm=False)


def _by_channel(report: Any) -> dict[SourceChannel, int]:
    return {row.channel: row.candidates_total for row in report.rows}


async def _candidate(db, label: str) -> int:
    cand = Candidate(name="Źródło", lastname=f"{label}-{uuid.uuid4().hex[:8]}")
    db.add(cand)
    await db.flush()
    return cand.id


def _event(
    candidate_id: int,
    channel: SourceChannel,
    captured_at: datetime,
    *,
    undated: bool = False,
) -> CandidateSourceEvent:
    note = "traffit:source:1 — Test"
    if undated:
        note = f"{note} {UNDATED_IMPORT_NOTE_MARK}"
    return CandidateSourceEvent(
        candidate_id=candidate_id,
        channel=channel,
        note=note,
        captured_at=captured_at,
    )


async def _cleanup(ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_report_skips_undated_events_and_reports_coverage() -> None:
    before = await _report()
    now = datetime.now(UTC)
    ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            # Kontakt w dwóch kanałach: dwa wiersze, jedna osoba.
            both = await _candidate(db, "dwa-kanaly")
            db.add_all(
                [
                    _event(both, SourceChannel.referral, now - timedelta(days=1)),
                    _event(both, SourceChannel.email, now - timedelta(days=2)),
                ]
            )
            # Tylko źródło bez daty — w oknie według `captured_at`, ale zmyślone.
            undated = await _candidate(db, "bez-daty")
            db.add(_event(undated, SourceChannel.import_csv, now, undated=True))
            # Bez żadnego źródła.
            bare = await _candidate(db, "bez-zrodla")
            ids = [both, undated, bare]
            await db.commit()

        after = await _report()
    finally:
        if ids:
            await _cleanup(ids)

    rows_before, rows_after = _by_channel(before), _by_channel(after)

    def grew(channel: SourceChannel) -> int:
        return rows_after.get(channel, 0) - rows_before.get(channel, 0)

    assert after.attribution_model == "multi_touch"
    assert grew(SourceChannel.referral) == 1
    assert grew(SourceChannel.email) == 1
    assert grew(SourceChannel.import_csv) == 0, "zdarzenie bez daty weszło do okna"
    assert after.unique_candidates - before.unique_candidates == 1
    assert after.new_candidates_total - before.new_candidates_total == 3
    assert (
        after.new_candidates_without_source - before.new_candidates_without_source == 2
    ), "kandydat z samym źródłem bez daty ma nieznane źródło"
    assert after.undated_source_events - before.undated_source_events == 1


@pytest.mark.asyncio
async def test_v1_first_touch_skips_candidates_whose_first_event_is_undated() -> None:
    period = Period(
        kind=PeriodKind.custom,
        start=datetime(1983, 5, 1, tzinfo=UTC),
        end=datetime(1983, 6, 1, tzinfo=UTC),
    )
    ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            dated = await _candidate(db, "v1-datowany")
            db.add(
                _event(dated, SourceChannel.referral, datetime(1983, 5, 11, tzinfo=UTC))
            )
            # Pierwsze zdarzenie bez daty, późniejsze datowane: pierwszego
            # kontaktu nie znamy — kandydat wypada z podziału.
            first_undated = await _candidate(db, "v1-pierwsze-bez-daty")
            db.add_all(
                [
                    _event(
                        first_undated,
                        SourceChannel.import_csv,
                        datetime(1983, 5, 5, tzinfo=UTC),
                        undated=True,
                    ),
                    _event(
                        first_undated,
                        SourceChannel.posting,
                        datetime(1983, 5, 20, tzinfo=UTC),
                    ),
                ]
            )
            ids = [dated, first_undated]
            await db.commit()

        async with AsyncSessionLocal() as db:
            result = await metrics.sources(db, period)
    finally:
        if ids:
            await _cleanup(ids)

    assert result["sources"] == [
        {"channel": "referral", "candidates": 1, "hired": 0, "hire_rate_pct": 0.0}
    ]
