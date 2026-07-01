"""Unit tests for CV Generator B2B async-generation status transitions.

Generation runs in the background now (the recruiter can close/leave the tab
without losing the result — see ``/api/cv-generator/generate``). These pin the
row lifecycle performed by the finalizers — „processing" → „ready" / „failed" —
independent of the DB/HTTP layer, using a tiny async stand-in for the session.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.cv_generator_b2b import _finalize_failure, _finalize_success


class _FakeDB:
    """Minimal async stand-in exposing just ``AsyncSession.get``."""

    def __init__(self, row):
        self._row = row

    async def get(self, _model, _id):
        return self._row


def _pending_row() -> SimpleNamespace:
    """A freshly-inserted „processing" placeholder row."""
    return SimpleNamespace(
        candidate_name="Generowanie…",
        position=None,
        job_id=None,
        filename="",
        render_payload=None,
        warnings=None,
        error_message=None,
        status="processing",
    )


@pytest.mark.asyncio
async def test_finalize_success_flips_processing_row_to_ready():
    row = _pending_row()
    result = SimpleNamespace(
        candidate_name="Rafał Pogorzelski",
        render_payload={"name": "Rafał Pogorzelski", "position": "DevOps Engineer"},
        job_id=42,
        filename="CV_B2B_Rafal_Pogorzelski.docx",
        warnings=["WERYFIKUJ: technologia 'Ansible' nie występuje w CV"],
    )

    ok = await _finalize_success(_FakeDB(row), 1, result=result)

    assert ok is True
    assert row.status == "ready"
    assert row.candidate_name == "Rafał Pogorzelski"
    assert row.position == "DevOps Engineer"
    assert row.job_id == 42
    assert row.filename == "CV_B2B_Rafal_Pogorzelski.docx"
    assert row.render_payload == result.render_payload
    assert row.warnings == ["WERYFIKUJ: technologia 'Ansible' nie występuje w CV"]
    assert row.error_message is None


@pytest.mark.asyncio
async def test_finalize_success_uses_real_name_from_payload_for_blind_cv():
    # Blind CV: ``result.candidate_name`` is the anonymized "Kandydat", but the
    # INTERNAL list must stay identifiable via the real name in the payload
    # (the DOCX itself remains anonymized on re-render).
    row = _pending_row()
    result = SimpleNamespace(
        candidate_name="Kandydat",
        render_payload={"name": "Małgorzata Żółć"},
        job_id=None,
        filename="CV_B2B_kandydat.docx",
        warnings=[],
    )

    await _finalize_success(_FakeDB(row), 1, result=result)

    assert row.candidate_name == "Małgorzata Żółć"
    assert row.status == "ready"
    assert row.warnings == []


@pytest.mark.asyncio
async def test_finalize_failure_marks_row_failed_and_truncates_message():
    row = _pending_row()
    long_message = "x" * 1500  # exceeds the error_message column width (1000)

    await _finalize_failure(_FakeDB(row), 1, long_message)

    assert row.status == "failed"
    assert row.error_message is not None
    assert len(row.error_message) == 1000


@pytest.mark.asyncio
async def test_finalizers_noop_when_row_deleted_midflight():
    # Recruiter deleted the „processing" row before the job finished — both
    # finalizers must no-op (return / do nothing) rather than raise.
    empty_db = _FakeDB(None)
    result = SimpleNamespace(
        candidate_name="X",
        render_payload={},
        job_id=None,
        filename="f.docx",
        warnings=[],
    )

    assert await _finalize_success(empty_db, 999, result=result) is False
    await _finalize_failure(empty_db, 999, "boom")  # must not raise
