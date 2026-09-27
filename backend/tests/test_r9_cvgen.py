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


# ── R9-N3-4: pakiet liczy „najnowszą” wersję w obrębie właściciela ────────


def _package_with_two_surfaces(monkeypatch):
    from hashlib import sha256

    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.cv_document_version import CvDocumentVersion
    from app.models.cv_generated_draft import CvGeneratedDraft
    from app.services import cv_packages as packages

    policy = {"required_languages": ["pl"], "version": 1}
    row = NS(
        id=1,
        language="pl",
        status="ready",
        filename="CV_pl.docx",
        candidate_id=8,
        job_id=9,
        central_policy=policy,
        package_review=None,
        position="Developer",
        content_mode="tailored",
        render_payload={},
    )

    def version(pk, **owner):
        html = f"<p>{pk}</p>"
        return NS(
            id=pk,
            language="pl",
            generated_document_id=1,
            generated_owner_id=owner.get("generated_owner_id"),
            candidate_stage_cv_id=owner.get("candidate_stage_cv_id"),
            content_html=html,
            content_sha256=sha256(html.encode()).hexdigest(),
            docx_content=b"file",
            docx_sha256=sha256(b"file").hexdigest(),
            consent_content=None,
            docx_filename="CV_pl.docx",
        )

    generator_version = version(11, generated_owner_id=1)
    # Nowsza wersja zatwierdzona w CV etapu, do którego podpięto ten dokument.
    stage_version = version(30, candidate_stage_cv_id=5)
    by_id = {11: generator_version, 30: stage_version}
    job = NS(status="complete", input_storage_key="cv/in.json", prepared_source_facts={})
    monkeypatch.setattr(packages, "members", AsyncMock(return_value=(job, row, [row])))
    db = AsyncMock()

    async def scalar(query):
        entity = query.column_descriptions[0]["entity"]
        params = query.compile().params
        if entity is CvDocumentVersion:
            if "id_1" in params:
                return by_id.get(params["id_1"])
            if "generated_owner_id_1" in params:
                return generator_version
            if "candidate_stage_cv_id_1" in params:
                return stage_version
            return stage_version  # globalnie najnowsza po id
        if entity is CvGeneratedDraft:
            return NS(
                branded_status="finalized",
                branded_draft_html=generator_version.content_html,
                edit_revision=1,
            )
        if entity is CandidateStageCV:
            return NS(
                branded_status="finalized",
                branded_draft_html=stage_version.content_html,
                edit_revision=1,
            )
        raise AssertionError(str(query))

    db.scalar.side_effect = scalar

    async def get(model, pk):
        assert model is CvDocumentVersion
        return by_id[pk]

    db.get.side_effect = get
    return packages, db, row


async def test_generator_share_accepts_its_own_latest_version(monkeypatch):
    packages, db, row = _package_with_two_surfaces(monkeypatch)
    assert await packages.require_ready(db, row, 11) == {"pl": 11}


async def test_stage_share_accepts_its_own_latest_version(monkeypatch):
    packages, db, row = _package_with_two_surfaces(monkeypatch)
    assert await packages.require_ready(db, row, 30) == {"pl": 30}
