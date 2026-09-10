"""Enrichment phases report errors but never freeze the `__daily__` watermark.

Measured on prod: one unparseable CV (candidate 287387, `enrich candidate_name
… backfill failed`) held `__daily__` from 2026-09-08. The quarantine could not
release it — a budgeted full sweep sees a row once per pass, and
`_next_quarantine` forgets a row that is absent from the next run, so the
counter never reached the limit. Enrichment re-derives data Nexus already
stores; holding the Traffit delta window back re-covers nothing for it.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

import app.services.cortex.extractor_traffit as cortex_extractor
import app.services.cv_field_backfill as cv_fields
import tests.test_traffit_error_ids_sources as sources
from app.tasks import traffit_sync
from app.tasks.traffit_sync import ADVISORY_PHASES, DAILY_MARKER, PHASE_NAMES
from tests.test_traffit_enrich_names_budget import _FakeDB, _importer, _stub_backfill
from tests.test_traffit_watermark_on_failure import (
    _marker_call,
    _ok_phase,
    _raising_phase,
    _row_error_phase,
    _run,
)

# The failing-row fakes of the error-id suite, reused as-is (fixture included).
cv_fields_env = sources.cv_fields_env


def test_advisory_phases_are_real_phase_names() -> None:
    """A misspelt name would silently leave that phase blocking."""
    assert ADVISORY_PHASES <= set(PHASE_NAMES)
    assert ADVISORY_PHASES == {
        "candidates_enrich_names",
        "candidates_cv_fields",
        "cortex",
    }


@pytest.mark.parametrize("phase", sorted(ADVISORY_PHASES))
async def test_row_errors_in_enrichment_do_not_freeze_the_watermark(monkeypatch, phase):
    upserts = await _run(
        monkeypatch,
        mode="delta",
        phases=[("candidates", _ok_phase()), (phase, _row_error_phase(1))],
    )

    daily = _marker_call(upserts, DAILY_MARKER)
    assert isinstance(daily.kwargs["last_synced_at"], datetime)
    assert daily.kwargs["last_status"] == "ok"
    # …but the phase itself keeps saying what happened.
    row = _marker_call(upserts, phase)
    assert row.kwargs["last_status"] == "errors"
    assert row.kwargs["stats"]["advisory_errors"] == 1
    assert "blocking_errors" not in row.kwargs["stats"]


async def test_a_crashing_enrichment_phase_does_not_freeze_it_either(monkeypatch):
    upserts = await _run(
        monkeypatch,
        mode="delta",
        phases=[
            ("candidates", _ok_phase()),
            ("candidates_enrich_names", _raising_phase()),
        ],
    )

    daily = _marker_call(upserts, DAILY_MARKER)
    assert isinstance(daily.kwargs["last_synced_at"], datetime)
    row = _marker_call(upserts, "candidates_enrich_names")
    assert row.kwargs["last_status"] == "error"


async def test_import_phase_errors_still_freeze_it(monkeypatch):
    """Advisory is per phase — a data-import failure keeps M2-IMP-01."""
    upserts = await _run(
        monkeypatch,
        mode="full",
        phases=[
            ("candidates", _row_error_phase(1)),
            ("candidates_enrich_names", _ok_phase()),
        ],
    )

    for marker in (DAILY_MARKER, traffit_sync.FULL_MARKER):
        assert _marker_call(upserts, marker).kwargs["last_synced_at"] is None


async def test_run_summary_names_the_advisory_failures(monkeypatch):
    from unittest.mock import AsyncMock

    from tests.test_traffit_watermark_on_failure import _FakeClient, _FakeSessionCM

    monkeypatch.setattr(traffit_sync, "_upsert_state", AsyncMock())
    monkeypatch.setattr(
        traffit_sync,
        "_get_state",
        AsyncMock(return_value=SimpleNamespace(last_synced_at=None, stats=None)),
    )
    monkeypatch.setattr(
        traffit_sync,
        "_phase_plan",
        lambda importer, since, files_since: [("cortex", _row_error_phase(2))],
    )
    monkeypatch.setattr(traffit_sync, "TraffitImporter", lambda *a, **k: object())
    monkeypatch.setattr(traffit_sync, "TraffitClient", _FakeClient)
    monkeypatch.setattr(traffit_sync, "AsyncSessionLocal", lambda: _FakeSessionCM())
    monkeypatch.setattr(
        traffit_sync.TraffitConfig, "from_env", staticmethod(lambda: object())
    )

    summary = await traffit_sync.run_traffit_sync("delta")

    assert summary["status"] == "ok"
    assert summary["advisory_failures"] == ["cortex"]


# ── The exception class travels into the error sample ────────────────────────


async def test_enrich_names_sample_carries_the_exception_class(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENRICH_NAMES_LIMIT", 10)
    _stub_backfill(
        monkeypatch,
        stats={
            "total": 1,
            "processed": 1,
            "resolved": 0,
            "unresolved": 0,
            "errors": 1,
            "error_ids": [287387],
            "error_types": {287387: "ValueError"},
            "last_id": 287387,
        },
    )

    progress = await _importer(_FakeDB()).enrich_missing_names(since=None)

    assert progress.error_samples == [
        "enrich candidate_name id=287387: backfill failed (ValueError)"
    ]
    # The class name comes AFTER the key the quarantine regex reads.
    assert progress.error_refs == {"candidate_name:287387"}


def test_adapter_sample_carries_the_exception_class() -> None:
    progress = traffit_sync._attributed_progress(
        {"errors": 1, "error_ids": [7], "error_types": {7: "KeyError"}},
        phase="cortex",
        verb="extract",
        entity="candidate_facts",
        detail="cortex extraction failed",
    )

    assert progress.error_samples == [
        "extract candidate_facts id=7: cortex extraction failed (KeyError)"
    ]
    assert progress.error_refs == {"candidate_facts:7"}


async def test_cortex_source_records_the_exception_class(monkeypatch):
    async def _taxonomy(db):
        return {}

    def _explode(*a, **k):
        raise LookupError("normalize boom")

    monkeypatch.setattr(cortex_extractor, "load_taxonomy", _taxonomy)
    monkeypatch.setattr(cortex_extractor, "normalize_and_upsert", _explode)

    stats = await cortex_extractor.run_traffit_backfill(
        sources._CortexDb([(41, "Python")])
    )

    assert stats["error_types"] == {41: "LookupError"}


async def test_cv_fields_source_records_the_exception_class(cv_fields_env):
    stats = await cv_fields.backfill_cv_fields(
        sources._CvFieldsDb([sources._candidate(7)])
    )

    assert stats["error_types"] == {7: "RuntimeError"}


async def test_name_backfill_source_records_the_exception_class(monkeypatch):
    import app.services.cv_backfill as cv_backfill

    class _Quota:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Db:
        async def execute(self, *a, **k):
            return [SimpleNamespace(id=287387)]

        async def scalar(self, *a, **k):
            return SimpleNamespace(id=287387)

        async def rollback(self):
            return None

        async def commit(self):
            return None

    async def _broken(*a, **k):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "synthetic")

    monkeypatch.setattr(cv_backfill, "ai_feature", lambda *a, **k: _Quota())
    monkeypatch.setattr(cv_backfill, "backfill_candidate_from_stored_cv", _broken)

    stats = await cv_backfill.backfill_missing_names(_Db())

    assert stats["error_ids"] == [287387]
    assert stats["error_types"] == {287387: "UnicodeDecodeError"}
