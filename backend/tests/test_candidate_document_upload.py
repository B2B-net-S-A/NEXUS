"""Upload plików do teczki kandydata — `POST /api/candidates/{id}/documents`.

Do tej pory jedyną drogą wgrania pliku było `POST /{id}/cv`, które przyjmuje
wyłącznie CV i zawsze nadpisuje primary. Zakładka „Pliki i umowy" nie miała
write-path w ogóle — stąd zgłoszenie „nie da się dodać pliku do kandydata".

Testy pilnują kontraktu, który łatwo cicho złamać przy kolejnej zmianie:

- załącznik inny niż CV zapisuje się i NIE staje się primary,
- `is_primary=true` poza CV jest odrzucane (parytet z `PATCH /documents/{id}`),
- pierwsze CV wgrane tą drogą przejmuje primary i ustawia `cv_filename`, żeby
  legacy `/cv-download` dalej działało,
- `content_type` bierze się z rozszerzenia, nie z nagłówka klienta (podrobiony
  `text/html` przy `?disposition=inline` byłby XSS-em na originie API),
- rozszerzenia spoza allowlisty → 415, pusty plik → 400,
- ponowny upload tej samej treści deduplikuje się po SHA-256.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)


async def _create_candidate(client: AsyncClient, headers: dict[str, str]) -> int:
    unique = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/candidates",
        headers=headers,
        json={
            "name": "Doc",
            "lastname": f"Upload-{unique}",
            "email": f"doc-upload-{unique}@example.com",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    candidate_id: int,
    *,
    filename: str,
    content: bytes = b"dowolna tresc zalacznika",
    content_type: str = "application/octet-stream",
    document_kind: str | None = None,
    is_primary: bool | None = None,
):
    data: dict[str, str] = {}
    if document_kind is not None:
        data["document_kind"] = document_kind
    if is_primary is not None:
        data["is_primary"] = "true" if is_primary else "false"
    return await client.post(
        f"/api/candidates/{candidate_id}/documents",
        headers=headers,
        files={"file": (filename, content, content_type)},
        data=data,
    )


async def test_upload_attachment_shows_up_in_listing(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _create_candidate(app_client, app_auth_headers)

    resp = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="certyfikat.pdf",
        content=MINIMAL_PDF,
        content_type="application/pdf",
        document_kind="certificate",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "certyfikat.pdf"
    assert body["document_kind"] == "certificate"
    assert body["is_primary"] is False
    assert body["size_bytes"] == len(MINIMAL_PDF)

    listing = await app_client.get(
        f"/api/candidates/{candidate_id}/documents", headers=app_auth_headers
    )
    assert listing.status_code == 200, listing.text
    assert [d["id"] for d in listing.json()] == [body["id"]]

    content = await app_client.get(
        f"/api/candidates/{candidate_id}/documents/{body['id']}/content",
        headers=app_auth_headers,
    )
    assert content.status_code == 200
    assert content.content == MINIMAL_PDF


async def test_content_type_comes_from_extension_not_client_header(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Klient nie może wybrać `text/html` — inline preview renderowałoby HTML."""
    candidate_id = await _create_candidate(app_client, app_auth_headers)

    resp = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="skan.png",
        content=b"\x89PNG\r\n\x1a\nfake",
        content_type="text/html",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["content_type"] == "image/png"


async def test_non_cv_cannot_be_primary(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _create_candidate(app_client, app_auth_headers)

    resp = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="list.pdf",
        content=MINIMAL_PDF,
        content_type="application/pdf",
        document_kind="cover_letter",
        is_primary=True,
    )
    assert resp.status_code == 422, resp.text


async def test_first_cv_becomes_primary_and_sets_cv_filename(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _create_candidate(app_client, app_auth_headers)

    resp = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="cv-kandydata.pdf",
        content=MINIMAL_PDF,
        content_type="application/pdf",
        document_kind="cv",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["document_kind"] == "cv"
    assert resp.json()["is_primary"] is True

    detail = await app_client.get(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["cv_filename"] == "cv-kandydata.pdf"


async def test_image_cannot_be_classified_as_cv(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _create_candidate(app_client, app_auth_headers)

    resp = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="zdjecie.png",
        content=b"\x89PNG\r\n\x1a\nfake",
        content_type="image/png",
        document_kind="cv",
    )
    assert resp.status_code == 415, resp.text


async def test_unsupported_extension_and_empty_file_are_rejected(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _create_candidate(app_client, app_auth_headers)

    unsupported = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="skrypt.exe",
        content=b"MZ\x90\x00",
    )
    assert unsupported.status_code == 415, unsupported.text

    empty = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="pusty.pdf",
        content=b"",
        content_type="application/pdf",
    )
    assert empty.status_code == 400, empty.text


async def test_reupload_of_identical_content_deduplicates(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _create_candidate(app_client, app_auth_headers)

    first = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="dyplom.pdf",
        content=MINIMAL_PDF,
        content_type="application/pdf",
        document_kind="certificate",
    )
    second = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="dyplom-kopia.pdf",
        content=MINIMAL_PDF,
        content_type="application/pdf",
        document_kind="other",
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["filename"] == "dyplom-kopia.pdf"
    assert second.json()["document_kind"] == "other"

    listing = await app_client.get(
        f"/api/candidates/{candidate_id}/documents", headers=app_auth_headers
    )
    assert len(listing.json()) == 1


async def test_filename_path_traversal_is_stripped(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _create_candidate(app_client, app_auth_headers)

    resp = await _upload(
        app_client,
        app_auth_headers,
        candidate_id,
        filename="../../etc/passwd.txt",
        content=b"root:x:0:0",
        content_type="text/plain",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["filename"] == "passwd.txt"
