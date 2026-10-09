"""0427: pliki rekrutacji — reguły przyjęcia (bez bazy) i przepływ
formularz → rekrutacja → menu „⋯” (z bazą, CI)."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text
from starlette.datastructures import UploadFile

from app.core.database import AsyncSessionLocal
from app.core.http_headers import safe_document_disposition
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_file import JobFile
from app.models.job_intake_form import JobIntakeForm
from app.models.user import UserRole
from app.services import job_files, storage_service
from tests._jarvis_helpers import make_user

FORMS_URL = "/api/job-intake/forms"
PDF = b"%PDF-1.4 fikcyjny request klienta"


# ── bez bazy ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename, content_type",
    [
        ("request.pdf", "application/pdf"),
        ("Opis roli.DOCX", job_files.CONTENT_TYPES[".docx"]),
        ("stawki.xlsx", job_files.CONTENT_TYPES[".xlsx"]),
        ("mail od klienta.msg", "application/vnd.ms-outlook"),
        ("zrzut.JPG", "image/jpeg"),
    ],
)
def test_allowed_types_get_their_content_type_from_the_extension(
    filename, content_type
):
    name, resolved = job_files.checked_name(filename)
    assert name == filename and resolved == content_type


@pytest.mark.parametrize(
    "filename", ["skrypt.exe", "strona.html", "obraz.svg", "bez_rozszerzenia", "", None]
)
def test_other_types_are_refused_in_polish(filename):
    with pytest.raises(job_files.JobFileRefused) as refused:
        job_files.checked_name(filename)
    assert refused.value.status == 415
    assert refused.value.message.startswith("Tego typu pliku nie da się dodać.")


def test_path_parts_are_dropped_and_a_long_name_keeps_its_extension():
    assert job_files.checked_name("../../etc/request.pdf")[0] == "request.pdf"
    # Znaki sterujące z nagłówka multipart nie trafiają do bazy ani do pobrania.
    assert job_files.checked_name("req\x00uest\r\n.pdf")[0] == "request.pdf"
    assert job_files.checked_name("Zapytanie – żółć.pdf")[0] == "Zapytanie – żółć.pdf"
    assert job_files.checked_name("C:\\\\Users\\\\dl\\\\request.pdf")[0] == "request.pdf"
    long_name, _ = job_files.checked_name("a" * 300 + ".pdf")
    assert len(long_name) == 255 and long_name.endswith(".pdf")


@pytest.mark.asyncio
async def test_read_is_bounded_and_refuses_empty_and_oversized(monkeypatch):
    monkeypatch.setattr(job_files, "MAX_FILE_BYTES", 8)
    assert await job_files.read_bounded(
        UploadFile(io.BytesIO(b"12345678"), filename="a.pdf")
    ) == b"12345678"
    with pytest.raises(job_files.JobFileRefused) as too_big:
        await job_files.read_bounded(
            UploadFile(io.BytesIO(b"123456789"), filename="a.pdf")
        )
    assert too_big.value.status == 413
    with pytest.raises(job_files.JobFileRefused) as empty:
        await job_files.read_bounded(UploadFile(io.BytesIO(b""), filename="a.pdf"))
    assert empty.value.status == 422


def test_only_pdf_and_images_may_open_in_the_browser_tab():
    assert safe_document_disposition("application/pdf", "inline") == "inline"
    assert safe_document_disposition("image/png", "inline") == "inline"
    for extension in (".docx", ".xlsx", ".txt", ".csv", ".eml", ".msg"):
        media_type = job_files.CONTENT_TYPES[extension]
        assert safe_document_disposition(media_type, "inline") == "attachment"


def test_a_file_belongs_to_exactly_one_owner():
    with pytest.raises(ValueError):
        job_files._owner_clause(job_id=None, form_id=None)
    with pytest.raises(ValueError):
        job_files._owner_clause(job_id=1, form_id=2)


# ── z bazą ───────────────────────────────────────────────────────────────────


@pytest.fixture
def storage(tmp_path, monkeypatch) -> Path:
    """Pliki testu lądują w katalogu tymczasowym, nie w magazynie."""
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "JOB_FILES_DIR", tmp_path / "job_files")
    return tmp_path


@pytest.fixture
def offline_matching(monkeypatch):
    """Tworzenie rekrutacji bez Qdranta i Voyage (jak w test_job_no_drafts)."""
    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)


async def _client_id() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Pliki {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        return client.id


async def _form(app_client, headers, client_id=None) -> int:
    resp = await app_client.post(
        FORMS_URL,
        json={"label": "Fikcyjny request", "client_id": client_id, "form": {}},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload(app_client, url, headers, name="request.pdf", data=PDF, **form):
    return await app_client.post(
        url,
        files={"file": (name, data, "application/octet-stream")},
        data=form or None,
        headers=headers,
    )


async def _bare_job() -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Pliki {uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=await _client_id(),
        )
        db.add(job)
        await db.commit()
        return job.id


def _stored(storage: Path) -> list[Path]:
    return sorted(p for p in (storage / "job_files").glob("*") if p.is_file())


@pytest.mark.asyncio
async def test_form_files_move_to_the_job_created_from_the_form(
    app_client, app_auth_headers, storage, offline_matching
):
    from tests._job_factory import complete_job_payload

    client_id = await _client_id()
    form_id = await _form(app_client, app_auth_headers, client_id)
    files_url = f"{FORMS_URL}/{form_id}/files"

    extra = await _upload(app_client, files_url, app_auth_headers, name="zakres.docx")
    assert extra.status_code == 201, extra.text
    request_file = await _upload(
        app_client, files_url, app_auth_headers, name="request.pdf", source="request"
    )
    assert request_file.status_code == 201, request_file.text
    assert request_file.json()["source"] == "request"
    # Typ z rozszerzenia, nie z nagłówka przeglądarki.
    assert request_file.json()["content_type"] == "application/pdf"

    listed = await app_client.get(files_url, headers=app_auth_headers)
    assert listed.status_code == 200, listed.text
    # Request klienta stoi pierwszy, niezależnie od kolejności dodania.
    assert [item["filename"] for item in listed.json()["items"]] == [
        "request.pdf",
        "zakres.docx",
    ]
    assert len(_stored(storage)) == 2

    created = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(client_id, intake_form_id=form_id),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    async with AsyncSessionLocal() as db:
        assert await db.get(JobIntakeForm, form_id) is None
        rows = (
            await db.scalars(select(JobFile).where(JobFile.job_id == job_id))
        ).all()
        assert len(rows) == 2
        assert all(row.intake_form_id is None for row in rows)
    job_files_resp = await app_client.get(
        f"/api/jobs/{job_id}/files", headers=app_auth_headers
    )
    assert job_files_resp.status_code == 200, job_files_resp.text
    body = job_files_resp.json()
    assert [item["filename"] for item in body["items"]] == ["request.pdf", "zakres.docx"]
    assert body["can_edit"] is True
    assert len(_stored(storage)) == 2


@pytest.mark.asyncio
async def test_refused_create_keeps_the_files_on_the_form(
    app_client, app_auth_headers, storage
):
    form_id = await _form(app_client, app_auth_headers)
    files_url = f"{FORMS_URL}/{form_id}/files"
    assert (await _upload(app_client, files_url, app_auth_headers)).status_code == 201

    refused = await app_client.post(
        "/api/jobs",
        json={"title": "Niekompletna", "intake_form_id": form_id},
        headers=app_auth_headers,
    )
    assert refused.status_code == 422, refused.text
    listed = await app_client.get(files_url, headers=app_auth_headers)
    assert [item["filename"] for item in listed.json()["items"]] == ["request.pdf"]


@pytest.mark.asyncio
async def test_someone_elses_form_is_404_for_files_too(app_client, storage):
    _, author = await make_user(UserRole.delivery_lead)
    _, other = await make_user(UserRole.delivery_lead)
    form_id = await _form(app_client, author)
    files_url = f"{FORMS_URL}/{form_id}/files"
    file_id = (await _upload(app_client, files_url, author)).json()["id"]

    assert (await app_client.get(files_url, headers=other)).status_code == 404
    assert (await _upload(app_client, files_url, other)).status_code == 404
    assert (
        await app_client.get(f"{files_url}/{file_id}/content", headers=other)
    ).status_code == 404
    assert (
        await app_client.delete(f"{files_url}/{file_id}", headers=other)
    ).status_code == 404
    assert len(_stored(storage)) == 1


@pytest.mark.asyncio
async def test_wrong_type_and_the_file_limit_are_refused(app_client, storage):
    user_id, headers = await make_user(UserRole.delivery_lead)
    form_id = await _form(app_client, headers)
    files_url = f"{FORMS_URL}/{form_id}/files"

    wrong = await _upload(app_client, files_url, headers, name="strona.html")
    assert wrong.status_code == 415, wrong.text
    assert wrong.json()["detail"].startswith("Tego typu pliku nie da się dodać.")
    unknown_source = await _upload(app_client, files_url, headers, source="inne")
    assert unknown_source.status_code == 422, unknown_source.text
    assert _stored(storage) == []

    async with AsyncSessionLocal() as db:
        db.add_all(
            JobFile(
                intake_form_id=form_id,
                filename=f"plik-{index}.pdf",
                file_path=f"job_files/fikcyjny-{index}.pdf",
                content_type="application/pdf",
                size_bytes=1,
                uploaded_by=user_id,
            )
            for index in range(job_files.MAX_FILES)
        )
        await db.commit()
    full = await _upload(app_client, files_url, headers)
    assert full.status_code == 409, full.text
    assert "najwyżej 20 plików" in full.json()["detail"]
    assert _stored(storage) == []


@pytest.mark.asyncio
async def test_team_reads_and_editors_change_the_job_files(
    app_client, app_auth_headers, storage
):
    job_id = await _bare_job()
    url = f"/api/jobs/{job_id}/files"
    _, recruiter = await make_user(UserRole.recruiter)
    _, viewer = await make_user(UserRole.user)

    pdf = await _upload(app_client, url, app_auth_headers, name="request.pdf")
    assert pdf.status_code == 201, pdf.text
    docx = await _upload(app_client, url, recruiter, name="notatka.docx")
    assert docx.status_code == 201, docx.text

    # Każda rola wewnętrzna widzi pliki; stara rola podglądu nie wchodzi.
    listed = await app_client.get(url, headers=recruiter)
    assert listed.status_code == 200, listed.text
    assert [item["filename"] for item in listed.json()["items"]] == [
        "request.pdf",
        "notatka.docx",
    ]
    assert (await app_client.get(url, headers=viewer)).status_code == 403
    assert (await _upload(app_client, url, viewer)).status_code == 403

    # W karcie przeglądarki otwiera się tylko PDF; Word zawsze do pobrania.
    inline_pdf = await app_client.get(
        f"{url}/{pdf.json()['id']}/content?disposition=inline", headers=recruiter
    )
    assert inline_pdf.status_code == 200, inline_pdf.text
    assert inline_pdf.content == PDF
    assert inline_pdf.headers["content-disposition"].startswith("inline")
    assert inline_pdf.headers["x-content-type-options"] == "nosniff"
    inline_docx = await app_client.get(
        f"{url}/{docx.json()['id']}/content?disposition=inline", headers=recruiter
    )
    assert inline_docx.headers["content-disposition"].startswith("attachment")

    # Plik innej rekrutacji nie wychodzi pod tym adresem.
    other_job = await _bare_job()
    assert (
        await app_client.get(
            f"/api/jobs/{other_job}/files/{pdf.json()['id']}/content",
            headers=app_auth_headers,
        )
    ).status_code == 404

    deleted = await app_client.delete(
        f"{url}/{docx.json()['id']}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    assert len(_stored(storage)) == 1
    async with AsyncSessionLocal() as db:
        actions = (
            await db.execute(
                text(
                    "SELECT action FROM activities WHERE entity_type = 'job' "
                    "AND entity_id = :job AND action LIKE 'job_file_%' ORDER BY id"
                ),
                {"job": job_id},
            )
        ).scalars().all()
    assert actions == ["job_file_added", "job_file_added", "job_file_removed"]


@pytest.mark.asyncio
async def test_deleting_the_job_removes_its_files_from_disk(
    app_client, app_auth_headers, storage
):
    job_id = await _bare_job()
    uploaded = await _upload(
        app_client, f"/api/jobs/{job_id}/files", app_auth_headers
    )
    assert uploaded.status_code == 201, uploaded.text
    assert len(_stored(storage)) == 1

    deleted = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert deleted.status_code == 204, deleted.text
    assert _stored(storage) == []
    async with AsyncSessionLocal() as db:
        left = await db.scalar(
            select(JobFile.id).where(JobFile.id == uploaded.json()["id"])
        )
    assert left is None


@pytest.mark.asyncio
async def test_retention_sweeps_files_of_a_deleted_form_only(
    app_client, app_auth_headers, storage
):
    from app.tasks import queue_retention

    kept_form = await _form(app_client, app_auth_headers)
    gone_form = await _form(app_client, app_auth_headers)
    kept = await _upload(app_client, f"{FORMS_URL}/{kept_form}/files", app_auth_headers)
    gone = await _upload(app_client, f"{FORMS_URL}/{gone_form}/files", app_auth_headers)
    assert kept.status_code == gone.status_code == 201
    assert (
        await app_client.delete(f"{FORMS_URL}/{gone_form}", headers=app_auth_headers)
    ).status_code == 204

    stats = await queue_retention.prune_once()

    assert stats["orphan_job_files"] >= 1
    async with AsyncSessionLocal() as db:
        left = set(
            (
                await db.scalars(
                    select(JobFile.id).where(
                        JobFile.id.in_([kept.json()["id"], gone.json()["id"]])
                    )
                )
            ).all()
        )
    assert left == {kept.json()["id"]}
    assert len(_stored(storage)) == 1


@pytest.mark.asyncio
async def test_deleting_one_form_file_removes_it_from_disk(
    app_client, app_auth_headers, storage
):
    form_id = await _form(app_client, app_auth_headers)
    files_url = f"{FORMS_URL}/{form_id}/files"
    file_id = (await _upload(app_client, files_url, app_auth_headers)).json()["id"]

    content = await app_client.get(
        f"{files_url}/{file_id}/content", headers=app_auth_headers
    )
    assert content.status_code == 200 and content.content == PDF
    deleted = await app_client.delete(
        f"{files_url}/{file_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    assert _stored(storage) == []
    listed = await app_client.get(files_url, headers=app_auth_headers)
    assert listed.json()["items"] == []
