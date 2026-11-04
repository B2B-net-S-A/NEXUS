import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import BackgroundTasks, HTTPException
import pytest
from pydantic import ValidationError

from app.api import candidate_stage_cv as api
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.services.cv_document_versions import freeze_approved_version
from app.schemas.candidate_stage_cv import (
    CVBrandedFinalize,
    CVBrandedNewDraft,
    CVBrandedUpdate,
)


def context(monkeypatch, status="draft"):
    csv = CandidateStageCV(
        id=1,
        candidate_stage_id=2,
        candidate_id=3,
        job_id=4,
        branded_status=status,
        branded_draft_html="<p>old</p>",
        edit_revision=5,
        branded_version=1,
        branded_language="pl",
        branded_template="standard",
        branded_finalized_at=datetime.now(timezone.utc)
        if status == "finalized"
        else None,
    )
    db = AsyncMock()

    def add(item):
        if isinstance(item, CvDocumentVersion):
            item.id = 10

    db.add = Mock(side_effect=add)
    db.scalar.return_value = None
    db.get.return_value = None
    loader = AsyncMock(return_value=csv)
    monkeypatch.setattr(api, "_load_csv_for_stage", loader)
    blobs = []

    def save(**kwargs):
        blob = kwargs["source"].read()
        blobs.append(blob)
        return "synthetic/version.html", len(blob)

    monkeypatch.setattr(api.storage_service, "save_branded_cv", save)
    return csv, db, SimpleNamespace(id=9), blobs, loader


async def test_finalization_saves_submitted_content_and_freezes_it(monkeypatch):
    from app.services import cv_approval_review
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        cv_approval_review,
        "review_for_approval",
        AsyncMock(return_value={"status": "verified"}),
    )
    csv, db, user, blobs, loader = context(monkeypatch)
    result = await api.finalize_branded_cv(
        2,
        CVBrandedFinalize(expected_revision=5, content_html="<p>just typed</p>"),
        user,
        db,
    )
    assert result.edit_revision == 6 and result.document_version_id == 10
    assert b"just typed" in blobs[0] and b">old<" not in blobs[0]
    version = next(
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], CvDocumentVersion)
    )
    csv.branded_draft_html = "changed later"
    assert version.content_html == "<p>just typed</p>"
    loader.assert_awaited_once_with(db, 2, user, lock=True)


@pytest.mark.parametrize("expected", [0, 4, 6])
async def test_stale_finalize_rejected_before_snapshot(monkeypatch, expected):
    csv, db, user, blobs, _ = context(monkeypatch)
    with pytest.raises(HTTPException) as error:
        await api.finalize_branded_cv(
            2,
            CVBrandedFinalize(expected_revision=expected, content_html="<p>new</p>"),
            user,
            db,
        )
    assert error.value.status_code == 409
    assert csv.branded_draft_html == "<p>old</p>" and blobs == []
    db.commit.assert_not_awaited()


async def test_new_draft_archives_legacy_version_before_clearing_status(monkeypatch):
    csv, db, user, _, loader = context(monkeypatch, "finalized")
    response = await api.new_branded_cv_draft(
        2, CVBrandedNewDraft(expected_revision=5), user, db
    )
    assert (
        response.version == 2
        and response.edit_revision == 6
        and response.status == "draft"
    )
    version = next(
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], CvDocumentVersion)
    )
    assert version.version == 1 and version.content_html == "<p>old</p>"
    # Only unpinned tokens for this stage are attached to that frozen version.
    statement = db.execute.call_args.args[0]
    assert "document_version_id IS NULL" in str(statement)
    assert statement.compile().params["document_version_id"] == 10
    loader.assert_awaited_once_with(db, 2, user, lock=True)


async def test_existing_version_is_never_overwritten(monkeypatch):
    csv, db, _, _, _ = context(monkeypatch, "finalized")
    version = CvDocumentVersion(id=10, content_html="frozen")
    db.scalar.return_value = version
    assert await freeze_approved_version(db, csv) is version
    assert version.content_html == "frozen"
    db.add.assert_not_called()


async def test_save_uses_revision_and_rejects_stale_response(monkeypatch):
    csv, db, user, _, _ = context(monkeypatch)
    result = await api.update_branded_cv(
        2, CVBrandedUpdate(expected_revision=5, content_html="new"), user, db
    )
    assert result.edit_revision == 6
    with pytest.raises(HTTPException) as error:
        await api.update_branded_cv(
            2, CVBrandedUpdate(expected_revision=5, content_html="older"), user, db
        )
    assert error.value.status_code == 409 and csv.branded_draft_html == "new"


def test_legacy_request_without_current_content_or_revision_is_not_accepted():
    with pytest.raises(ValidationError):
        CVBrandedFinalize(expected_revision=5)
    with pytest.raises(ValidationError):
        CVBrandedUpdate(content_html="new")


@pytest.mark.parametrize(
    "candidate_id,job_id,status,code",
    [
        (99, 4, "ready", 404),
        (None, None, "ready", 404),
        (3, 4, "processing", 422),
        # 09.10.2026: CV tej samej osoby z INNEJ rekrutacji da się wybrać
        # (kopia odłączona, `test_stage_cv_pick_from_profile.py`) — ale
        # nadal tylko zakończoną generację.
        (3, 99, "processing", 422),
    ],
)
async def test_selection_rejects_foreign_or_incomplete_document(
    monkeypatch, candidate_id, job_id, status, code
):
    from app.schemas.candidate_stage_cv import CVBrandedSelectGenerated

    csv, db, user, _, _ = context(monkeypatch)
    db.get.return_value = SimpleNamespace(
        id=42,
        candidate_id=candidate_id,
        job_id=job_id,
        status=status,
        render_payload={"why_points": ["selected source"]},
    )
    with pytest.raises(HTTPException) as exc:
        await api.select_generated_cv(
            2,
            CVBrandedSelectGenerated(expected_revision=5, generated_document_id=42),
            user,
            BackgroundTasks(),
            db,
        )
    assert exc.value.status_code == code
    assert csv.branded_draft_html == "<p>old</p>"
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("approved_id", [None, 81])
async def test_selection_archives_old_approval_and_uses_exact_generated_content(
    monkeypatch,
    approved_id,
):
    from app.schemas.candidate_stage_cv import CVBrandedSelectGenerated

    csv, db, user, _, loader = context(monkeypatch, "finalized")
    csv.generated_document_id = 41
    generated = SimpleNamespace(
        id=42,
        filename="chosen.docx",
        client_id=None,
        client_rule_version=None,
        candidate_id=3,
        job_id=4,
        status="ready",
        render_payload={
            "name": "Secret Person",
            "language": "en",
            "blind_cv": True,
            "why_points": ["Selected Python experience"],
            "highlight_keywords": ["Python"],
            "warnings": ["PRIVATE WARNING"],
            "_full_source": "PRIVATE SOURCE",
        },
    )

    async def get(model, key):
        return generated if model is api.CvGeneratedDocument else None

    db.get.side_effect = get
    from app.services import cv_generated_approval

    resolver = AsyncMock(
        return_value=SimpleNamespace(
            template_content=b"frozen template",
            consent_content=None,
            render_metadata={
                "template_sha256": __import__("hashlib")
                .sha256(b"frozen template")
                .hexdigest(),
                "consent_sha256": None,
            },
            language="en",
            template="blind",
            id=81,
            content_html="<p>Approved <b>Python</b> edit</p>",
            content_sha256="h" * 64,
            docx_sha256="d" * 64,
        )
    )
    monkeypatch.setattr(
        cv_generated_approval, "approved_version_for_generation", resolver
    )
    tasks = BackgroundTasks()
    result = await api.select_generated_cv(
        2,
        CVBrandedSelectGenerated(
            expected_revision=5,
            generated_document_id=42,
            document_version_id=approved_id,
        ),
        user,
        tasks,
        db,
    )
    assert result.generated_document_id == 42 and result.from_generator
    # CV w procesie: QC nowej wersji liczy się w tle po zapisie.
    assert [t.func.__name__ for t in tasks.tasks] == ["qc_after_attach"]
    assert (
        result.version == 2 and result.edit_revision == 6 and result.status == "draft"
    )
    if approved_id is None:
        assert "Selected <b>Python</b> experience" in result.content_html
        resolver.assert_not_awaited()
    else:
        assert result.content_html == "<p>Approved <b>Python</b> edit</p>"
        assert csv.branded_render_metadata["source_document_version_id"] == 81
        resolver.assert_awaited_once_with(db, generated, 81)
    assert all(
        value not in result.content_html
        for value in ("Secret Person", "PRIVATE", "<script", "<button", ">old<")
    )
    assert result.template == "blind" and result.language == "en"
    version = next(
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], CvDocumentVersion)
    )
    assert version.content_html == "<p>old</p>" and version.generated_document_id == 41
    loader.assert_awaited_once_with(db, 2, user, lock=True, create_missing=True)
    with pytest.raises(HTTPException) as exc:
        await api.select_generated_cv(
            2,
            CVBrandedSelectGenerated(expected_revision=5, generated_document_id=42),
            user,
            BackgroundTasks(),
            db,
        )
    assert exc.value.status_code == 409


async def test_selected_content_cannot_be_silently_regenerated_from_profile(
    monkeypatch,
):
    csv, db, user, _, _ = context(monkeypatch)
    csv.branded_from_generator = True
    csv.generated_document_id = None  # Even after source deletion.
    with pytest.raises(HTTPException) as exc:
        await api.update_branded_cv(
            2, CVBrandedUpdate(expected_revision=5, language="en"), user, db
        )
    # Generator v3: zmiana szablonu/języka (stary szablon „CV firmowe") jest
    # wycofana w całości — 410 zanim cokolwiek zostanie wczytane.
    assert exc.value.status_code == 410
    assert csv.branded_draft_html == "<p>old</p>"
    db.commit.assert_not_awaited()


# ── Historia wersji w edytorze CV (Edytor CV 2, PR 5) ────────────────────────

APPROVED = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)


def _stage_cv(status="finalized", version=3):
    return CandidateStageCV(
        id=1,
        candidate_stage_id=2,
        candidate_id=3,
        job_id=4,
        branded_status=status,
        branded_version=version,
        branded_language="en",
        branded_draft_html="<p>Treść na etapie</p>",
        branded_finalized_at=APPROVED if status == "finalized" else None,
        branded_finalized_by=9 if status == "finalized" else None,
    )


def test_history_lists_versions_newest_first_and_marks_the_approved_one():
    from app.services.cv_document_versions import version_summaries

    rows = [
        (1, APPROVED, "Fikcyjna Rekruterka", "pl", False),
        (3, APPROVED, None, "en", True),
        (2, APPROVED, "  ", None, True),
    ]

    listed = version_summaries(_stage_cv("finalized", 3), rows)

    assert [item["version"] for item in listed] == [3, 2, 1]
    assert [item["is_current"] for item in listed] == [True, False, False]
    assert listed[0] == {
        "version": 3,
        "approved_at": APPROVED,
        "approved_by_name": None,
        "language": "en",
        "docx_available": True,
        "is_current": True,
    }
    # Nazwa to imię i nazwisko z konta; pusta albo brak konta = nieznany.
    assert [item["approved_by_name"] for item in listed] == [
        None,
        None,
        "Fikcyjna Rekruterka",
    ]
    # Wiersz bez języka (starszy) to polskie CV — kontrakt zna tylko pl i en.
    assert [item["language"] for item in listed] == ["en", "pl", "pl"]
    assert [item["docx_available"] for item in listed] == [True, True, False]


def test_history_marks_no_version_as_current_while_a_new_draft_is_open():
    """Szkic nosi już następny numer: etap nie pokazuje wtedy żadnej wersji
    jako zatwierdzonej, więc każdą z listy da się przywrócić."""
    from app.services.cv_document_versions import version_summaries

    rows = [(2, APPROVED, None, "pl", True), (1, APPROVED, None, "pl", False)]

    listed = version_summaries(_stage_cv("draft", 3), rows)

    assert [item["version"] for item in listed] == [2, 1]
    assert not any(item["is_current"] for item in listed)


def test_history_of_a_cv_that_was_never_approved_is_empty():
    from app.services.cv_document_versions import version_summaries

    assert version_summaries(_stage_cv("draft", 1), []) == []
    assert version_summaries(_stage_cv("none", 1), []) == []


def test_history_shows_an_approved_cv_that_has_no_frozen_row_yet():
    """CV zatwierdzone przed migracją 0287 dostaje wiersz wersji dopiero przy
    nowym szkicu albo linku. Lista jest tylko do odczytu, więc pokazuje je
    z wiersza etapu — pusta lista znaczyłaby „nigdy nie zatwierdzone”."""
    from app.services.cv_document_versions import version_summaries

    listed = version_summaries(
        _stage_cv("finalized", 2),
        [(1, APPROVED, None, "pl", True)],
        "Fikcyjny Zatwierdzający",
    )

    assert listed[0] == {
        "version": 2,
        "approved_at": APPROVED,
        "approved_by_name": "Fikcyjny Zatwierdzający",
        "language": "en",
        "docx_available": False,
        "is_current": True,
    }
    assert [item["version"] for item in listed] == [2, 1]
    assert listed[1]["is_current"] is False


def _history_db(*, rows=(), content=None, approver=None):
    """Atrapa bazy dla odczytów historii: lista wersji albo jedna treść."""
    db = AsyncMock()
    db.execute.return_value = Mock(
        all=Mock(return_value=list(rows)), first=Mock(return_value=content)
    )
    db.scalar.return_value = approver
    db.add = Mock()
    return db


def _history_route(monkeypatch, csv):
    monkeypatch.setattr(api, "_stage_job_and_cv", AsyncMock(return_value=(4, csv)))
    scope = AsyncMock()
    monkeypatch.setattr(api, "ensure_job_read_access", scope)
    return scope


def _nothing_written(db) -> bool:
    return not (
        db.add.called
        or db.commit.await_count
        or db.flush.await_count
        or db.delete.await_count
    )


async def test_versions_route_answers_in_the_contract_shape_and_writes_nothing(
    monkeypatch,
):
    csv = _stage_cv("finalized", 2)
    scope = _history_route(monkeypatch, csv)
    db = _history_db(
        rows=[
            (2, APPROVED, "Fikcyjna Rekruterka", "pl", True),
            (1, APPROVED, None, "pl", False),
        ]
    )
    user = SimpleNamespace(id=9)

    result = await api.list_branded_cv_versions(2, user, db)

    assert result.model_dump(mode="json") == {
        "versions": [
            {
                "version": 2,
                "approved_at": "2026-10-01T09:30:00Z",
                "approved_by_name": "Fikcyjna Rekruterka",
                "language": "pl",
                "docx_available": True,
                "is_current": True,
            },
            {
                "version": 1,
                "approved_at": "2026-10-01T09:30:00Z",
                "approved_by_name": None,
                "language": "pl",
                "docx_available": False,
                "is_current": False,
            },
        ]
    }
    # Ta sama bramka zakresu co odczyt CV etapu: rekrutacja tego etapu.
    scope.assert_awaited_once_with(db, user, 4)
    assert _nothing_written(db)


async def test_versions_route_answers_an_empty_list_for_a_stage_without_a_cv_row(
    monkeypatch,
):
    """Etap z importu nie ma wiersza CV — to stan, nie 404 (jak `GET …/branded`)."""
    scope = _history_route(monkeypatch, None)
    db = _history_db()

    result = await api.list_branded_cv_versions(2, SimpleNamespace(id=9), db)

    assert result.model_dump() == {"versions": []}
    scope.assert_awaited_once()
    db.execute.assert_not_awaited()


async def test_history_routes_check_the_recruitment_before_reading_anything(
    monkeypatch,
):
    scope = _history_route(monkeypatch, _stage_cv("finalized", 2))
    scope.side_effect = HTTPException(403, "Brak dostępu do tej rekrutacji.")
    db = _history_db(content=("<p>Tajne</p>", "pl", APPROVED))

    for call in (
        api.list_branded_cv_versions(2, SimpleNamespace(id=9), db),
        api.get_branded_cv_version(2, 2, SimpleNamespace(id=9), db),
    ):
        with pytest.raises(HTTPException) as refused:
            await call
        assert refused.value.status_code == 403
    db.execute.assert_not_awaited()


async def test_single_version_route_returns_the_frozen_content(monkeypatch):
    _history_route(monkeypatch, _stage_cv("draft", 3))
    # Treść wersji przechodzi przez sanitizer także przy odczycie.
    db = _history_db(
        content=("<p>Wersja druga</p><script>alert(1)</script>", "en", APPROVED)
    )

    result = await api.get_branded_cv_version(2, 2, SimpleNamespace(id=9), db)

    body = result.model_dump(mode="json")
    assert body["version"] == 2 and body["language"] == "en"
    assert body["approved_at"] == "2026-10-01T09:30:00Z"
    assert "<p>Wersja druga</p>" in body["content_html"]
    assert "<script" not in body["content_html"]
    assert set(body) == {"version", "content_html", "language", "approved_at"}
    assert _nothing_written(db)


@pytest.mark.parametrize("csv_exists", [True, False])
async def test_single_version_route_answers_404_in_polish(monkeypatch, csv_exists):
    _history_route(monkeypatch, _stage_cv("draft", 3) if csv_exists else None)
    db = _history_db(content=None)

    with pytest.raises(HTTPException) as missing:
        await api.get_branded_cv_version(2, 7, SimpleNamespace(id=9), db)

    assert missing.value.status_code == 404
    assert missing.value.detail == "Nie znaleziono zatwierdzonej wersji CV."


async def test_single_version_route_serves_an_approved_cv_without_a_frozen_row(
    monkeypatch,
):
    """Bliźniak listy: wersja pokazana z wiersza etapu musi dać się otworzyć."""
    csv = _stage_cv("finalized", 2)
    _history_route(monkeypatch, csv)
    db = _history_db(content=None)

    result = await api.get_branded_cv_version(2, 2, SimpleNamespace(id=9), db)

    assert result.model_dump(mode="json") == {
        "version": 2,
        "content_html": "<p>Treść na etapie</p>",
        "language": "en",
        "approved_at": "2026-10-01T09:30:00Z",
    }
    # Szkic o tym samym numerze NIE jest zatwierdzoną wersją.
    csv.branded_status = "draft"
    with pytest.raises(HTTPException) as missing:
        await api.get_branded_cv_version(2, 2, SimpleNamespace(id=9), db)
    assert missing.value.status_code == 404


def test_history_routes_do_not_shadow_the_word_download():
    """`…/versions/{n}` i `…/versions/{n}/docx` to różne trasy — żadna nie
    może przejąć adresu drugiej, niezależnie od kolejności rejestracji."""
    from starlette.routing import compile_path

    from app.main import app
    from tests._route_introspection import iter_api_routes

    def handlers(path: str) -> list[str]:
        return [
            route.endpoint.__name__
            for template, route in iter_api_routes(app)
            if "GET" in route.methods and compile_path(template)[0].match(path)
        ]

    base = "/api/candidates/stages/5/cv/branded"
    assert handlers(base + "/versions") == ["list_branded_cv_versions"]
    assert handlers(base + "/versions/2") == ["get_branded_cv_version"]
    assert handlers(base + "/versions/2/docx") == ["download_approved_docx"]
