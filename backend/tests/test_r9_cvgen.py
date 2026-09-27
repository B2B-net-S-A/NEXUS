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
    [
        ("blind", "pl", "Kandydat"),
        ("blind", "en", "Candidate"),
        ("standard", "pl", "Jan"),
    ],
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
    job = NS(
        status="complete", input_storage_key="cv/in.json", prepared_source_facts={}
    )
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


# ── R9-N3-6: podgląd Championa niebędący obiektem = 422, nie 500 ──────────


@pytest.mark.parametrize(
    "profile",
    [["lista"], "napis", {"basics": "x"}, {"stack": ["Java"]}, {"project": "opis"}],
)
def test_prepare_profile_rejects_non_object_input_with_type_error(profile):
    from app.services.champion_intake import prepare_profile

    with pytest.raises(TypeError):
        prepare_profile(profile, actor_id=1)


def test_prepare_profile_keeps_tolerating_empty_legacy_sections():
    from app.services.champion_intake import prepare_profile

    profile = prepare_profile({"experience": [], "project": ""}, actor_id=1)
    assert isinstance(profile["experience"], dict)


# ── R9-N3-2: nieczytelny zrzut zgody ──────────────────────────────────────


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (40, 30), "white").save(out, format="PNG")
    return out.getvalue()


def test_consent_upload_rejects_damaged_image_with_valid_signature():
    from app.api.cv_generator_b2b import _consent_image_readable, _sniff_image_type

    good = _png()
    truncated = good[: len(good) // 2]
    garbage = b"\x89PNG\r\n\x1a\n" + b"not really an image"
    assert _consent_image_readable(good)
    for damaged in (truncated, garbage):
        # Sygnatura przechodzi — dlatego sama nie wystarczała.
        assert _sniff_image_type(damaged) == "image/png"
        assert not _consent_image_readable(damaged)


async def test_central_policy_generation_survives_unreadable_consent(monkeypatch):
    from app.api import cv_generator_b2b as api
    from app.services.cv_generator_b2b import job_leases

    monkeypatch.setattr(job_leases, "lock_owned_job", AsyncMock(return_value=None))
    monkeypatch.setattr(
        api, "_render_with_consent", Mock(side_effect=OSError("cannot identify image"))
    )
    row = NS(
        status="processing",
        error_message=None,
        job_id=None,
        central_policy={"requires_rodo_consent_block": True},
    )
    db = AsyncMock()
    db.get.return_value = row
    result = NS(
        docx_bytes=b"docx-without-consent",
        render_payload={"name": "Synthetic", "position": "Dev"},
        candidate_name="Synthetic",
        job_id=None,
        filename="cv.docx",
        warnings=["inne"],
    )
    finalized = await api._finalize_success(
        db, 11, result=result, consent_screenshot={"storage_key": "synthetic/consent"}
    )
    assert finalized is True
    assert row.status == "ready"
    assert row.docx_content == b"docx-without-consent"
    assert row.consent_content is None
    assert "consent_screenshot" not in row.render_payload
    assert api.CONSENT_NOT_ATTACHED_WARNING in row.warnings
    # Pobranie i tak jest zablokowane do czasu dołączenia zgody.
    from app.services import cv_consent_gate

    assert cv_consent_gate.consent_missing(row)


# ── R9-V3-4: wzorce e-maili/URL-i liniowe na tekście z zewnątrz ───────────

_ADVERSARIAL = [
    "a" * 16384,
    "a-" * 8192,
    "a." * 8192,
    "a@" * 8192,
    "@" * 16384,
    "x" * 16383 + "@",
    "ab.cd" * 3277,
]


@pytest.mark.parametrize("text", _ADVERSARIAL, ids=range(len(_ADVERSARIAL)))
def test_email_and_url_patterns_are_linear_on_16kb(text):
    import time

    from app.services.cv_qc import _url_spans
    from app.services.public_profile_lint import _EMAIL

    started = time.perf_counter()
    _EMAIL.search(text)
    _url_spans(text)
    assert time.perf_counter() - started < 0.05


_OLD_EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
_OLD_URLISH = r"\S+@\S+|https?://\S+|www\.\S+|\b[\w-]+\.(?:com|pl|io|org)\S*"


@pytest.mark.parametrize(
    "text",
    [
        "Napisz: jan.kowalski+cv@firma-x.com.pl lub zadzwoń.",
        "(anna@b2b.pl), www.nexus.pl/cv i https://x.io/a?b=1 oraz kontakt@firma",
        "Java, Spring, PostgreSQL — portfolio github.com/jan, e-mail: a@b.c",
        "a@@b @x y@ foo.pl, test.org.",
    ],
)
def test_rewritten_patterns_match_like_the_old_ones(text):
    import re

    from app.services.cv_qc import _URLISH
    from app.services.public_profile_lint import _EMAIL

    old_email = re.compile(_OLD_EMAIL, re.IGNORECASE).search(text)
    new_email = _EMAIL.search(text)
    assert (old_email and old_email.span()) == (new_email and new_email.span())
    old_spans = [m.span() for m in re.finditer(_OLD_URLISH, text)]
    assert old_spans == [m.span() for m in _URLISH.finditer(text)]


def _request(path_params: dict, query: bytes = b""):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/cv-generator/x",
            "query_string": query,
            "headers": [],
            "path_params": path_params,
        }
    )


@pytest.mark.parametrize(
    ("path_params", "query"),
    [
        ({"generated_id": "2147483648"}, b""),
        ({"generated_id": "1", "version_number": "99999999999"}, b""),
        ({}, b"candidate_id=2147483648"),
        ({}, b"before_id=" + b"9" * 5000),
    ],
)
def test_ids_beyond_int32_are_rejected_with_422(path_params, query):
    from fastapi import HTTPException

    from app.api.cv_generator_b2b import _reject_out_of_range_ids

    with pytest.raises(HTTPException) as error:
        _reject_out_of_range_ids(_request(path_params, query))
    assert error.value.status_code == 422


def test_ids_within_int32_and_other_params_pass():
    from app.api.cv_generator_b2b import _reject_out_of_range_ids, router

    _reject_out_of_range_ids(
        _request({"generated_id": "2147483647", "token": "9" * 40}, b"limit=20")
    )
    assert any(
        dep.dependency is _reject_out_of_range_ids for dep in router.dependencies
    )


def test_generate_body_ids_beyond_int32_are_validation_errors():
    from pydantic import ValidationError

    from app.api.cv_generator_b2b import GenerateRequest

    with pytest.raises(ValidationError):
        GenerateRequest(cv_document_id=1, candidate_id=2**31)
    with pytest.raises(ValidationError):
        GenerateRequest(cv_document_id=1, candidate_id=1, stage_id=2**31)


@pytest.mark.parametrize("profile", [{"basics": "x"}, {"search": [1, 2]}])
def test_generator_champion_preview_with_bad_shape_is_422(profile):
    from fastapi import HTTPException

    from app.api.cv_generator_b2b import _imported_champion

    with pytest.raises(HTTPException) as error:
        _imported_champion(profile, 1)
    assert error.value.status_code == 422


# ── R9-N3-5: generacja przerwana przez deploy ─────────────────────────────


async def test_requeue_touches_only_expired_unstarted_generation_jobs():
    from app.services.cv_generator_b2b import job_leases

    db = AsyncMock()
    db.execute.return_value = Mock(
        scalars=Mock(return_value=Mock(all=Mock(return_value=[7])))
    )
    assert await job_leases.requeue_unstarted_expired_jobs(db) == [7]
    sql = str(
        db.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "status='queued'" in sql.replace(" ", "")
    assert "cv_generation_jobs.status = 'running'" in sql
    assert "cv_generation_jobs.kind IN ('new', 'upload')" in sql
    assert "prepared_source_facts IS NULL" in sql
    assert "jsonb_typeof" in sql
    assert "cv_generation_jobs.created_at >" in sql


def test_recovery_loop_requeues_before_it_interrupts():
    import inspect

    from app.services.cv_generator_b2b import durable_jobs

    source = inspect.getsource(durable_jobs.recovery_loop)
    assert source.index("requeue_unstarted_expired_jobs(db)") < source.index(
        "interrupt_expired_jobs(db)"
    )


async def test_retry_resumes_interrupted_primary_generation(monkeypatch):
    from fastapi import BackgroundTasks

    from app.api import cv_generator_b2b as api
    from app.services import cv_packages
    from app.services.cv_generator_b2b import durable_jobs

    primary = NS(id=11, status="failed", error_message="przerwana", central_policy=None)
    job = NS(
        id=5,
        status="interrupted",
        finished_at=object(),
        error_code="worker_lease_expired",
        input_storage_key="cv-inputs/abc.json",
        prepared_source_facts={"facts": 1},
    )
    monkeypatch.setattr(
        api, "_load_generated_document", AsyncMock(return_value=primary)
    )
    monkeypatch.setattr(
        cv_packages, "members", AsyncMock(return_value=(job, primary, [primary]))
    )
    tasks = BackgroundTasks()
    db = AsyncMock()
    result = await api.retry_cv_package(11, NS(id=3), tasks, db)
    assert result == {"id": 11, "status": "queued"}
    assert primary.status == "processing" and primary.error_message is None
    assert job.status == "queued" and job.finished_at is None and job.error_code is None
    db.commit.assert_awaited_once()
    assert [t.func for t in tasks.tasks] == [durable_jobs.execute_job]


async def test_retry_refuses_ordinary_generation_failure(monkeypatch):
    from fastapi import BackgroundTasks, HTTPException

    from app.api import cv_generator_b2b as api
    from app.services import cv_packages

    primary = NS(id=11, status="failed", error_message="błąd", central_policy=None)
    job = NS(id=5, status="failed", input_storage_key="k", prepared_source_facts=None)
    monkeypatch.setattr(
        api, "_load_generated_document", AsyncMock(return_value=primary)
    )
    monkeypatch.setattr(
        cv_packages, "members", AsyncMock(return_value=(job, primary, [primary]))
    )
    with pytest.raises(HTTPException) as error:
        await api.retry_cv_package(11, NS(id=3), BackgroundTasks(), AsyncMock())
    assert error.value.status_code == 409
    assert primary.status == "failed"


async def test_resumed_job_reuses_frozen_source_facts(monkeypatch):
    from app.api import cv_generator_b2b as api
    from app.services.cv_generator_b2b import job_leases
    from app.services.cv_generator_b2b.job_snapshot import _encode

    facts = svc.PreparedSourceFacts("original source", "{}", "sha", "notes")
    job = NS(prepared_source_facts=_encode(facts))
    monkeypatch.setattr(job_leases, "lock_owned_job", AsyncMock(return_value=job))
    prepare = AsyncMock(side_effect=AssertionError("must reuse frozen facts"))
    assert await api._frozen_or_prepared_source_facts(AsyncMock(), prepare) == facts


async def test_fresh_job_prepares_and_freezes_source_facts(monkeypatch):
    from app.api import cv_generator_b2b as api
    from app.services.cv_generator_b2b import job_leases
    from app.services.cv_generator_b2b.job_snapshot import _decode

    facts = svc.PreparedSourceFacts("original source", "{}", "sha", "notes")
    job = NS(prepared_source_facts=None)
    monkeypatch.setattr(job_leases, "lock_owned_job", AsyncMock(return_value=job))

    async def prepare():
        return facts

    assert await api._frozen_or_prepared_source_facts(AsyncMock(), prepare) == facts
    assert _decode(job.prepared_source_facts) == facts
