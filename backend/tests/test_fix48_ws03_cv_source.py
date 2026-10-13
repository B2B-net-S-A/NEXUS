"""Audyt 48 h (13.10.2026), obszar WS03 — „bieżące CV” osoby, testy bez bazy.

* pkt 8: plik z kwarantanny tożsamości (CV innej osoby) dalej był bieżącym CV —
  `current_cv_filters` patrzył tylko na rodzaj i `source_deleted_at`, a
  kwarantanna zdejmuje z pliku samo `is_primary`. Następna kopia CV etapu
  (ruch karty, „Użyj w tej rekrutacji”) i generator brały go znowu;
* po usunięciu głównego CV `get_current_cv` brał następny plik, także
  „nieaktualny” albo „…B2B…” przygotowany dla klienta;
* awaria odczytu z magazynu przy „Wgraj nowe CV” w rekrutacji: kopia etapu
  dostawała starsze CV ze wskaźnika kandydata pod nazwą nowego pliku.

Zapytania sprawdzamy po skompilowanym SQL (jak `test_r9_cvgen.py`); te same
scenariusze na Postgresie: `test_fix48_ws03_cv_source_db.py` (CI).
"""

from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.candidate_stage_cv import CandidateStageCV
from app.services import candidate_stage_cv_service as stage_cv
from app.services import cv_source


def _sql(query) -> str:
    return str(query.compile(compile_kwargs={"literal_binds": True}))


def _no_document_db(*, legacy_quarantined: bool) -> AsyncMock:
    db = AsyncMock()
    db.scalars.return_value = Mock(first=Mock(return_value=None))
    db.scalar.return_value = legacy_quarantined
    return db


async def _current_cv_sql() -> str:
    db = _no_document_db(legacy_quarantined=False)
    candidate = NS(id=5, cv_storage_key=None, cv_file_content=None, cv_language=None)
    assert await cv_source.get_current_cv(db, candidate) is None
    return _sql(db.scalars.call_args.args[0])


async def test_quarantined_document_is_never_the_current_cv():
    sql = await _current_cv_sql()
    # Żywa kwarantanna (bez zwolnienia przez admina/HoR) wyklucza plik.
    assert "NOT (EXISTS (SELECT candidate_source_identity_reviews.id" in sql
    assert "candidate_source_identity_reviews.source_kind = 'document'" in sql
    assert "candidate_source_identity_reviews.source_id = candidate_documents.id" in sql
    assert "candidate_source_identity_reviews.decision = 'confirmed_mismatch'" in sql
    assert "candidate_source_identity_reviews.override_at IS NULL" in sql


async def test_outdated_files_are_not_a_successor():
    sql = await _current_cv_sql()
    assert "candidate_documents.outdated_at IS NULL" in sql
    # Bez heurystyki po nazwie: plik „…B2B…” bywa jedynym CV osoby.
    assert "b2b" not in sql.lower()


async def test_generator_default_source_follows_the_same_rule():
    from app.services.cv_generator_b2b import standalone_service as svc

    db = AsyncMock()
    db.get.return_value = NS(id=2, name="A", lastname="B")
    db.scalars.return_value = Mock(first=Mock(return_value=None))
    db.scalar.return_value = None
    with pytest.raises(svc.StandaloneGenerationError):
        await svc.load_candidate_generation_source(db, candidate_id=2, stage_id=None)
    sql = _sql(db.scalars.call_args_list[0].args[0])
    assert "candidate_source_identity_reviews.decision = 'confirmed_mismatch'" in sql
    assert "candidate_documents.outdated_at IS NULL" in sql


async def test_quarantined_legacy_pointer_is_not_the_current_cv():
    db = _no_document_db(legacy_quarantined=True)
    candidate = NS(
        id=5,
        cv_storage_key=None,
        cv_file_content=b"%PDF-1.4 CV innej osoby",
        cv_filename="cv.pdf",
        cv_language=None,
    )

    assert await cv_source.get_current_cv(db, candidate) is None
    sql = _sql(db.scalar.call_args.args[0])
    assert "candidate_source_identity_reviews.source_kind = 'legacy_cv'" in sql
    assert "candidate_source_identity_reviews.source_id = 5" in sql


async def test_legacy_pointer_without_quarantine_still_serves_the_cv():
    db = _no_document_db(legacy_quarantined=False)
    candidate = NS(
        id=5,
        cv_storage_key=None,
        cv_file_content=b"%PDF-1.4 wlasne CV",
        cv_filename="wlasne.pdf",
        cv_language="pl",
    )

    current = await cv_source.get_current_cv(db, candidate)

    assert current is not None
    assert current.content == b"%PDF-1.4 wlasne CV"
    assert current.source == "candidate_bytea"


async def test_stage_copy_is_built_from_the_given_bytes_not_from_the_profile(
    monkeypatch: pytest.MonkeyPatch,
):
    # Trasa „Wgraj nowe CV” ma bajty pliku w pamięci. Ponowny odczyt przez
    # `get_current_cv` przy awarii magazynu oddawał starsze CV ze wskaźnika
    # kandydata — pod nazwą nowego pliku.
    async def _must_not_read(*_args, **_kwargs):
        raise AssertionError("kopia z wgrania nie czyta CV z profilu")

    monkeypatch.setattr(stage_cv, "get_current_cv", _must_not_read)
    monkeypatch.setattr("app.services.object_storage.is_available", lambda: False)
    csv_row = CandidateStageCV(
        id=3,
        candidate_stage_id=900,
        candidate_id=41,
        job_id=7,
        original_cv_filename="stare.pdf",
        original_cv_content=b"%PDF-1.4 OLD",
    )
    db = AsyncMock()
    db.add = Mock()
    db.scalar.return_value = csv_row
    uploaded = cv_source.CurrentCV(
        content=b"%PDF-1.4 NEW",
        filename="nowe-cv.pdf",
        language="pl",
        source="stage_upload",
    )

    row = await stage_cv.refresh_original_cv_snapshot(
        db, 900, user_id=1, source="manual_upload", current=uploaded
    )

    assert row.original_cv_content == b"%PDF-1.4 NEW"
    assert row.original_cv_filename == "nowe-cv.pdf"
    assert row.original_snapshot_source == "manual_upload"
    activity = db.add.call_args.args[0]
    assert activity.details["old_filename"] == "stare.pdf"
    assert activity.details["cv_source"] == "stage_upload"
