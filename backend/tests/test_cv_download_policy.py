"""Osoba z samą rolą rekrutera nie zapisuje plików kandydata na dysk (02.11.2026).

Wyjątek jeden: oryginał CV po próbie z generatorem, z podaniem powodu. Podgląd
działa dalej, także podgląd pliku Word, którego nagłówek zawsze ma `attachment`.
Bez bazy: trasy wołane wprost; zestawienie na końcu pliku czyta prawdziwe tabele.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.models  # noqa: F401
from app.api import candidate_stage_cv as stage_cv_api
from app.api import candidates as candidates_api
from app.api.candidate_access import CANDIDATE_BULK_CV_ROLES, CANDIDATE_DOCUMENT_ROLES
from app.models.cv_generator_feedback import CvGeneratorFeedback
from app.models.user import User, UserRole
from app.services import cv_download_policy as policy

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _user(*roles: UserRole) -> User:
    return User(id=7, role=roles[0], roles=[role.value for role in roles])


RECRUITER = _user(UserRole.recruiter)
RECRUITER_DL = _user(UserRole.recruiter, UserRole.delivery_lead)
RECRUITER_TCM = _user(UserRole.recruiter, UserRole.talent_community_manager)


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        (RECRUITER, True),
        (RECRUITER_DL, False),
        (RECRUITER_TCM, False),
        (_user(UserRole.delivery_lead, UserRole.recruiter), False),
        (_user(UserRole.finance), False),
        (_user(UserRole.admin), False),
        (_user(UserRole.head_of_recruitment), False),
    ],
)
def test_only_recruiter_without_other_role_is_limited(user, expected) -> None:
    assert policy.is_recruiter_only(user) is expected


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("cv.pdf", None, True),
        ("CV.DOCX", None, True),
        ("bez-rozszerzenia", "application/pdf", True),
        ("bez-rozszerzenia", DOCX, True),
        ("skan.jpg", "image/jpeg", True),
        ("cv.doc", "application/msword", False),
        ("cv.odt", None, False),
        ("formularz.xlsx", None, False),
        (None, None, False),
    ],
)
def test_preview_rule_mirrors_frontend(filename, content_type, expected) -> None:
    assert policy.has_inline_preview(filename, content_type) is expected


def test_zip_roles_drop_only_the_recruiter() -> None:
    assert UserRole.recruiter not in CANDIDATE_BULK_CV_ROLES
    assert set(CANDIDATE_DOCUMENT_ROLES) - set(CANDIDATE_BULK_CV_ROLES) == {
        UserRole.recruiter
    }


@pytest.fixture
def no_cpro(monkeypatch):
    async def handles(_db, _user_id):
        return False

    monkeypatch.setattr(policy, "_handles_cpro", handles)


@pytest.mark.asyncio
async def test_recruiter_cannot_save_file_with_preview(no_cpro) -> None:
    with pytest.raises(HTTPException) as exc:
        await policy.ensure_can_save_file(
            None, RECRUITER, filename="cv.pdf", content_type="application/pdf"
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == policy.DOWNLOAD_BLOCKED_CODE


@pytest.mark.asyncio
async def test_file_without_preview_stays_downloadable(no_cpro) -> None:
    await policy.ensure_can_save_file(
        None, RECRUITER, filename="cv.doc", content_type="application/msword"
    )


@pytest.mark.asyncio
async def test_additional_role_lifts_the_block(no_cpro) -> None:
    await policy.ensure_can_save_file(
        None, RECRUITER_DL, filename="cv.pdf", content_type="application/pdf"
    )


@pytest.mark.asyncio
async def test_cpro_sender_keeps_downloading(monkeypatch) -> None:
    async def handles(_db, _user_id):
        return True

    monkeypatch.setattr(policy, "_handles_cpro", handles)
    await policy.ensure_can_save_file(
        None, RECRUITER, filename="cv.pdf", content_type="application/pdf"
    )


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def first(self):
        return self.value


class _FakeDb:
    def __init__(self, execute_result=None):
        self.execute_result = execute_result
        self.added: list = []
        self.commits = 0

    async def execute(self, _statement):
        return _Result(self.execute_result)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj, attribute_names=None):
        return None

    def add(self, obj):
        self.added.append(obj)


@pytest.fixture
def audit(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(
        candidates_api.candidate_audit,
        "record_candidate_audit",
        lambda db, **kwargs: events.append(kwargs),
    )
    return events


def _document(filename: str, content_type: str):
    return SimpleNamespace(
        id=11,
        filename=filename,
        content_type=content_type,
        storage_key=None,
        file_content=b"bytes",
    )


@pytest.mark.asyncio
async def test_word_preview_passes_and_is_logged_as_preview(no_cpro, audit) -> None:
    db = _FakeDb(_document("cv.docx", DOCX))
    response = await candidates_api.download_candidate_document(
        5, 11, RECRUITER, db, disposition="inline"
    )
    assert response.status_code == 200
    # Nagłówek zostaje `attachment` (ochrona originu), dziennik mówi „podgląd”.
    assert response.headers["content-disposition"].startswith("attachment")
    assert audit[0]["details"]["disposition"] == "inline"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("cv.pdf", "application/pdf"), ("cv.docx", DOCX), ("inny.pdf", "application/pdf")],
)
async def test_save_is_refused_regardless_of_document_kind(
    no_cpro, audit, filename, content_type
) -> None:
    db = _FakeDb(_document(filename, content_type))
    with pytest.raises(HTTPException) as exc:
        await candidates_api.download_candidate_document(
            5, 11, RECRUITER, db, disposition="attachment"
        )
    assert exc.value.status_code == 403
    assert audit == []


@pytest.mark.asyncio
async def test_delivery_lead_with_recruiter_role_still_saves(no_cpro, audit) -> None:
    db = _FakeDb(_document("cv.pdf", "application/pdf"))
    response = await candidates_api.download_candidate_document(
        5, 11, RECRUITER_DL, db, disposition="attachment"
    )
    assert response.status_code == 200
    assert audit[0]["details"]["disposition"] == "attachment"


@pytest.fixture
def stage(monkeypatch):
    csv = SimpleNamespace(
        candidate_id=4242,
        job_id=99,
        generated_document_id=None,
        original_cv_filename="resume.pdf",
    )

    async def load_csv(db, stage_id, user, **kwargs):
        return csv

    async def load_bytes(_csv):
        return b"%PDF-1.4"

    monkeypatch.setattr(stage_cv_api, "_load_csv_for_stage", load_csv)
    monkeypatch.setattr(stage_cv_api, "load_original_cv_bytes", load_bytes)
    monkeypatch.setattr(stage_cv_api, "snapshot_exists", lambda _csv: True)
    return csv


@pytest.fixture
def stage_audit(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(
        stage_cv_api.candidate_audit,
        "record_candidate_audit",
        lambda db, **kwargs: events.append(kwargs),
    )
    return events


@pytest.mark.asyncio
async def test_stage_route_refuses_save_but_serves_preview(
    no_cpro, stage, stage_audit
) -> None:
    with pytest.raises(HTTPException) as exc:
        await stage_cv_api.download_original_cv(
            55, RECRUITER, _FakeDb(), disposition="attachment"
        )
    assert exc.value.status_code == 403

    response = await stage_cv_api.download_original_cv(
        55, RECRUITER, _FakeDb(), disposition="inline"
    )
    assert response.status_code == 200
    assert stage_audit[0]["details"]["disposition"] == "inline"


def _generation(status: str = "ready"):
    return SimpleNamespace(
        id=321,
        status=status,
        client_id=8,
        client_rule_version=3,
        content_mode="new",
    )


_FEEDBACK = stage_cv_api.GeneratorFeedbackIn(reasons=["why_candidate", "layout"])


@pytest.mark.asyncio
async def test_download_without_generator_attempt_is_refused(
    no_cpro, stage, stage_audit
) -> None:
    db = _FakeDb(None)
    with pytest.raises(HTTPException) as exc:
        await stage_cv_api.download_original_cv_after_generator(
            55, _FEEDBACK, RECRUITER, db
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "generator_attempt_required"
    assert db.added == []
    assert stage_audit == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ready", "failed"])
async def test_download_after_generator_saves_reasons(
    no_cpro, stage, stage_audit, status
) -> None:
    db = _FakeDb(_generation(status))
    response = await stage_cv_api.download_original_cv_after_generator(
        55, _FEEDBACK, RECRUITER, db
    )
    assert response.status_code == 200
    assert response.body == b"%PDF-1.4"
    assert response.headers["content-disposition"].startswith("attachment")

    (feedback,) = db.added
    assert isinstance(feedback, CvGeneratorFeedback)
    assert feedback.reasons == ["why_candidate", "layout"]
    assert feedback.candidate_stage_id == 55
    assert feedback.candidate_id == 4242
    assert feedback.job_id == 99
    assert feedback.client_id == 8
    assert feedback.generated_document_id == 321
    assert feedback.generation_status == status
    assert feedback.created_by == RECRUITER.id
    assert db.commits == 1

    (event,) = stage_audit
    assert event["details"]["via"] == "after_generator"
    assert event["details"]["disposition"] == "attachment"


@pytest.mark.asyncio
async def test_pair_without_snapshot_gets_current_cv(
    monkeypatch, no_cpro, stage, stage_audit
) -> None:
    monkeypatch.setattr(stage_cv_api, "snapshot_exists", lambda _csv: False)

    async def current_cv(_db, _candidate):
        return SimpleNamespace(content=b"profile", filename="profil.pdf")

    monkeypatch.setattr("app.services.cv_source.get_current_cv", current_cv)
    db = _FakeDb(_generation())

    async def get(_model, _id):
        return SimpleNamespace(id=4242)

    db.get = get
    response = await stage_cv_api.download_original_cv_after_generator(
        55, _FEEDBACK, RECRUITER, db
    )
    assert response.body == b"profile"
    assert 'profil.pdf' in response.headers["content-disposition"]


@pytest.mark.parametrize(
    "payload",
    [
        {"reasons": []},
        {"reasons": ["nie_ma_takiego"]},
        {"reasons": ["other"]},
        {"reasons": ["other"], "detail": "   "},
        {"reasons": ["layout"], "detail": "x" * (policy.FEEDBACK_DETAIL_MAX + 1)},
    ],
)
def test_feedback_validation_refuses(payload) -> None:
    with pytest.raises(ValidationError):
        stage_cv_api.GeneratorFeedbackIn(**payload)


def test_feedback_cleans_input() -> None:
    parsed = stage_cv_api.GeneratorFeedbackIn(
        reasons=["layout", "layout", "other"], detail="  brak projektu\x00  "
    )
    assert parsed.reasons == ["layout", "other"]
    assert parsed.detail == "brak projektu"


@pytest.mark.asyncio
async def test_generator_quality_summary_reads_the_real_tables(
    app_client, app_auth_headers
) -> None:
    response = await app_client.get(
        "/api/cv-generator/feedback/summary", headers=app_auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 30
    assert isinstance(body["generations_ready"], int)
    assert isinstance(body["entries"], list)
