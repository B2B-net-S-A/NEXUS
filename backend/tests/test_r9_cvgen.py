"""Runda 9 audytu — generator CV (kod CVGEN), testy bez bazy."""

from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import cv_source
from app.services.cv_generator_b2b import standalone_service as svc


def _sql(query) -> str:
    return str(query.compile(compile_kwargs={"literal_binds": True}))


# ── R9-X1-1 / R9-N7-11: bieżące CV ────────────────────────────────────────


async def test_current_cv_query_loads_bytea_and_skips_non_cv_kinds():
    db = AsyncMock()
    db.scalars.return_value = Mock(first=Mock(return_value=None))
    candidate = NS(id=5, cv_storage_key=None, cv_file_content=None, cv_language=None)
    assert await cv_source.get_current_cv(db, candidate) is None
    sql = _sql(db.scalars.call_args.args[0])
    # undefer: kolumna BYTEA jest w SELECT, nie doczytywana leniwie.
    assert "candidate_documents.file_content" in sql.split("FROM")[0]
    assert "document_kind NOT IN ('certificate', 'cover_letter')" in sql
    assert "CASE WHEN (candidate_documents.document_kind = 'cv')" in sql


async def test_generation_source_query_loads_bytea_and_skips_non_cv_kinds():
    db = AsyncMock()
    db.get.return_value = NS(id=2, name="A", lastname="B")
    db.scalars.return_value = Mock(first=Mock(return_value=None))
    db.scalar.return_value = None
    with pytest.raises(svc.StandaloneGenerationError):
        await svc.load_candidate_generation_source(db, candidate_id=2, stage_id=None)
    sql = _sql(db.scalars.call_args_list[0].args[0])
    assert "candidate_documents.file_content" in sql.split("FROM")[0]
    assert "document_kind NOT IN ('certificate', 'cover_letter')" in sql


async def test_explicitly_chosen_document_is_not_filtered_by_kind():
    db = AsyncMock()
    db.get.return_value = NS(id=2, name="A", lastname="B")
    db.scalars.return_value = Mock(first=Mock(return_value=None))
    with pytest.raises(svc.StandaloneGenerationError, match="Wybrane CV"):
        await svc.load_candidate_generation_source(
            db, candidate_id=2, stage_id=None, cv_document_id=71
        )
    sql = _sql(db.scalars.call_args_list[0].args[0])
    assert "NOT IN ('certificate'" not in sql


# ── R9-N3-1: publiczny link do CV etapu w szablonie blind ─────────────────


@pytest.mark.parametrize(
    ("template", "language", "expected"),
    [("blind", "pl", "Kandydat"), ("blind", "en", "Candidate"), ("standard", "pl", "Jan")],
)
async def test_frozen_stage_version_masks_first_name_for_blind(
    template, language, expected
):
    from datetime import datetime, timezone

    from app.models.candidate import Candidate
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.cv_document_version import CvDocumentVersion
    from app.models.job import Job
    from app.services.cv_document_versions import freeze_approved_version

    csv = CandidateStageCV(
        id=1,
        candidate_stage_id=2,
        candidate_id=3,
        job_id=4,
        branded_status="finalized",
        branded_draft_html="<p>cv</p>",
        edit_revision=1,
        branded_version=1,
        branded_language=language,
        branded_template=template,
        branded_finalized_at=datetime.now(timezone.utc),
    )
    db = AsyncMock()
    db.add = Mock()
    db.scalar.return_value = None

    async def get(model, pk):
        if model is Candidate:
            return NS(name="Jan")
        if model is Job:
            return NS(title="Developer")
        raise AssertionError(model)

    db.get.side_effect = get
    version = await freeze_approved_version(db, csv)
    assert isinstance(version, CvDocumentVersion)
    assert version.candidate_first_name == expected


@pytest.mark.parametrize(
    ("template", "language", "expected"),
    [
        ("blind", "pl", "Kandydat"),
        ("blind", "en", "Candidate"),
        ("standard", "en", "Jan"),
        (None, "pl", "Jan"),
    ],
)
def test_public_first_name_rule(template, language, expected):
    from app.services.cv_document_versions import public_first_name

    assert public_first_name("Jan", template, language) == expected


# ── R9-N3-3: zatwierdzenie z edytora generatora niesie nagłówek linku ─────


@pytest.mark.parametrize(
    ("blind", "expected_name"), [(False, "Jan Kowalski"), (True, "Kandydat")]
)
async def test_editor_finalize_stamps_first_name_and_title(
    monkeypatch, blind, expected_name
):
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.models.cv_generated_draft import CvGeneratedDraft
    from app.services import cv_generated_editor as editor

    monkeypatch.setattr(editor, "render", AsyncMock(return_value=b"docx"))
    monkeypatch.setattr(
        editor, "review_for_approval", AsyncMock(return_value={"status": "verified"})
    )
    draft = CvGeneratedDraft(
        id=1,
        generated_document_id=7,
        edit_revision=2,
        branded_version=1,
        branded_status="draft",
        branded_draft_html="<p>cv</p>",
        branded_template_content=b"template",
        branded_consent_content=None,
        branded_render_metadata={},
        branded_language="pl",
        branded_template="blind" if blind else "standard",
        branded_docx_filename="cv.docx",
    )
    generated = NS(
        render_payload={
            "name": "Jan Kowalski",
            "position": "Java Developer",
            "language": "pl",
            "blind_cv": blind,
        }
    )
    db = AsyncMock()
    db.add = Mock()

    async def get(model, pk):
        assert model is CvGeneratedDocument and pk == 7
        return generated

    db.get.side_effect = get
    version = await editor.finalize(db, draft, 2, "<p>cv</p>", user_id=3)
    assert version.candidate_first_name == expected_name
    assert version.job_title == "Java Developer"
