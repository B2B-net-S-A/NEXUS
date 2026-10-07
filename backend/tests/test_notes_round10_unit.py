"""Notatki i czaty — runda 10 audytu (część bez bazy).

R10-N6-2 (fakty z usuniętej notatki), R10-N6-4 (``@<liczba>``), R10-N6-5
(``null`` w PATCH notatki), R10-N6-11 (N+1 w czacie rekrutacji) oraz lustro
DDL migracji 0395 (R10-N6-1).
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.schemas.note import NoteUpdate
from app.services.candidate_notes_facts import (
    NOTES_CHANGED_AT_KEY,
    clear_notes_facts,
    mark_notes_changed,
)
from app.services.mention_parser import parse_mentions_global

BACKEND = pathlib.Path(__file__).resolve().parents[1]


# ── R10-N6-4 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hour_after_at_sign_does_not_mention_user_number_10() -> None:
    db = AsyncMock()
    assert await parse_mentions_global(db, "Rozmowa jutro @10:00, sala @3") == []
    db.execute.assert_not_awaited()


# ── R10-N6-5 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["content", "note_type"])
def test_note_update_rejects_explicit_null(field: str) -> None:
    with pytest.raises(ValidationError):
        NoteUpdate.model_validate({field: None})


def test_note_update_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        NoteUpdate.model_validate({"content": ""})


def test_note_update_omitted_fields_stay_unset() -> None:
    data = NoteUpdate.model_validate({"content": "nowa treść"})
    assert data.model_dump(exclude_unset=True) == {"content": "nowa treść"}


# ── R10-N6-2 ─────────────────────────────────────────────────────────────────


def _candidate(*, rate: str | None, written: dict | None, manual: bool = False):
    insights = {"expected_rate": {"value": 180, "currency": "PLN", "period": "h"}}
    if written is not None:
        insights["_rate_written"] = written
    data = {"_notes_insights": insights, "summary": "z CV"}
    if manual:
        data["_manual_override_rate"] = True
    return SimpleNamespace(
        id=7,
        cv_extracted_data=data,
        expected_rate_hourly=Decimal(rate) if rate is not None else None,
        expected_rate_currency="PLN" if rate is not None else None,
        profile_rate_version=3,
        profile_rate_updated_at=None,
        accepts_below_min_rate=None,
    )


def _flag(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.candidate_notes_facts.flag_modified", lambda *a, **k: None
    )


def test_clear_notes_facts_removes_rate_written_by_notes(monkeypatch) -> None:
    _flag(monkeypatch)
    cand = _candidate(
        rate="180.00",
        written={"amount": "180.00", "currency": "PLN", "version": 3},
    )
    audit = clear_notes_facts(cand)
    assert audit is not None and audit["source"] == "notes_removed"
    assert cand.expected_rate_hourly is None
    assert "_notes_insights" not in cand.cv_extracted_data
    assert cand.cv_extracted_data["summary"] == "z CV"


def test_clear_notes_facts_keeps_rate_someone_else_wrote(monkeypatch) -> None:
    _flag(monkeypatch)
    # Rekruter zmienił stawkę po zapisie z notatek — wersja się różni.
    cand = _candidate(
        rate="200.00",
        written={"amount": "180.00", "currency": "PLN", "version": 2},
    )
    assert clear_notes_facts(cand) is None
    assert cand.expected_rate_hourly == Decimal("200.00")
    assert "_notes_insights" not in cand.cv_extracted_data


def test_clear_notes_facts_respects_manual_override(monkeypatch) -> None:
    _flag(monkeypatch)
    cand = _candidate(
        rate="180.00",
        written={"amount": "180.00", "currency": "PLN", "version": 3},
        manual=True,
    )
    assert clear_notes_facts(cand) is None
    assert cand.expected_rate_hourly == Decimal("180.00")


def _with_availability(cand, *, profile_date, marker_date: str):
    cand.availability_date = profile_date
    cand.cv_extracted_data["_notes_insights"]["_availability_from_notes"] = {
        "date": marker_date,
        "as_of": "2023-05-04",
        "basis": "asap",
    }
    return cand


def test_clear_notes_facts_removes_availability_written_by_notes(monkeypatch) -> None:
    _flag(monkeypatch)
    cand = _with_availability(
        _candidate(rate=None, written=None),
        profile_date=date(2023, 5, 4),
        marker_date="2023-05-04",
    )
    assert clear_notes_facts(cand) is None
    assert cand.availability_date is None
    assert "_notes_insights" not in cand.cv_extracted_data


def test_clear_notes_facts_keeps_availability_corrected_by_a_person(
    monkeypatch,
) -> None:
    _flag(monkeypatch)
    cand = _with_availability(
        _candidate(rate=None, written=None),
        profile_date=date(2026, 12, 1),
        marker_date="2023-05-04",
    )
    clear_notes_facts(cand)
    assert cand.availability_date == date(2026, 12, 1)


def test_mark_notes_changed_stamps_insights(monkeypatch) -> None:
    _flag(monkeypatch)
    cand = _candidate(rate=None, written=None)
    assert mark_notes_changed(cand, now_iso="2026-09-27T10:00:00+00:00")
    insights = cand.cv_extracted_data["_notes_insights"]
    assert insights[NOTES_CHANGED_AT_KEY] == "2026-09-27T10:00:00+00:00"
    assert insights["expected_rate"]["value"] == 180


def test_selection_treats_deleted_note_as_newer_than_extraction() -> None:
    from app.services.notes_insights_extractor import legacy_row_is_fresh
    from app.tasks.notes_insights_sync import _later

    extracted = "2026-09-20T02:00:00+00:00"
    latest_note = datetime(2026, 9, 19, tzinfo=timezone.utc)
    insights = {"_v2_extracted_at": extracted}
    assert legacy_row_is_fresh(insights, latest_note)
    latest = _later(latest_note, "2026-09-27T09:00:00+00:00")
    assert not legacy_row_is_fresh(insights, latest)
    assert _later(latest_note, "zepsuty") == latest_note
    assert _later(latest_note, None) == latest_note


# ── R10-N6-11 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_chat_serialization_has_constant_query_count() -> None:
    from app.api import job_chat

    now = datetime.now(timezone.utc)
    msgs = [
        SimpleNamespace(
            id=i,
            job_id=1,
            author_id=10 + i % 2,
            content=f"wiadomość {i}",
            reply_to_message_id=(i - 1) if i > 1 else None,
            is_edited=False,
            edited_at=None,
            is_deleted=False,
            pinned=False,
            pinned_at=None,
            pinned_by=None,
            created_at=now,
            updated_at=now,
        )
        for i in range(1, 41)
    ]
    authors = [
        SimpleNamespace(
            id=uid, name=f"U{uid}", email=f"u{uid}@example.com", role="recruiter"
        )
        for uid in (10, 11)
    ]

    def result(scalars=None, rows=None):
        res = MagicMock()
        res.scalars.return_value.all.return_value = scalars or []
        res.all.return_value = rows or []
        return res

    db = MagicMock()
    db.get = AsyncMock(side_effect=AssertionError("db.get per wiadomość"))
    db.execute = AsyncMock(
        side_effect=[
            result(scalars=authors),
            result(scalars=msgs),
            result(rows=[(3, 10)]),
            result(rows=[]),
        ]
    )
    out = await job_chat._serialize_many(db, msgs)
    assert len(out) == 40
    assert db.execute.await_count == 4
    assert out[2].mentions == [10]
    assert out[1].reply_to_preview == "wiadomość 1"


# ── R10-N6-1: lustro DDL ─────────────────────────────────────────────────────


def _migration():
    path = BACKEND / "alembic" / "versions" / "0395_notes_deleted_note_sources.py"
    spec = importlib.util.spec_from_file_location("m0395", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_entrypoint_mirrors_every_0395_statement() -> None:
    entrypoint = _flat((BACKEND / "entrypoint.sh").read_text())
    for statement in _migration().DDL_STATEMENTS:
        assert _flat(statement) in entrypoint, statement[:80]


def test_deleted_note_source_model_matches_migration() -> None:
    from app.models.deleted_note_source import DeletedNoteSource

    ddl = _migration().CREATE_DELETED_NOTE_SOURCES
    for column in DeletedNoteSource.__table__.columns:
        assert re.search(rf"\b{column.name}\b", ddl), column.name


def test_promotion_sql_reads_the_tombstones() -> None:
    from app.services.traffit.importer import _PROMOTE_NOTES_SQL

    assert "FROM deleted_note_sources" in _PROMOTE_NOTES_SQL
