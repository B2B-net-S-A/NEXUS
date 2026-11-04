"""Pliki kandydata: plakietka „nieaktualne” i autor wgrania (0400, 29.09.2026).

Decyzja: stare CV zostaje w teczce (nic nie kasuje CV), rekruter może je
tylko oznaczyć jako nieaktualne. Kontrakt, który łatwo cicho złamać:

- oznaczenie ustawia `outdated_at` + nazwisko osoby, „Cofnij” czyści oba,
- głównego CV nie da się oznaczyć (409 „Najpierw ustaw inne CV jako główne.”),
- nieaktualnego CV nie da się ustawić jako głównego (409), chyba że w tym
  samym żądaniu cofnięto oznaczenie,
- lista plików niesie nazwisko osoby, która wgrała plik.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _pdf(tag: str) -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
        + f"% {tag}\n".encode()
    )


async def _candidate_with_two_cvs(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[int, int, int]:
    unique = uuid.uuid4().hex[:8]
    created = await client.post(
        "/api/candidates",
        headers=headers,
        json={
            "name": "Plik",
            "lastname": f"Nieaktualny-{unique}",
            "email": f"doc-outdated-{unique}@example.com",
        },
    )
    assert created.status_code in (200, 201), created.text
    candidate_id = created.json()["id"]

    ids: list[int] = []
    for index in range(2):
        resp = await client.post(
            f"/api/candidates/{candidate_id}/documents",
            headers=headers,
            files={
                "file": (
                    f"cv-{index}.pdf",
                    _pdf(f"{unique}-{index}"),
                    "application/pdf",
                )
            },
            data={"document_kind": "cv"},
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return candidate_id, ids[0], ids[1]


async def test_upload_records_who_added_the_file(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id, primary_id, other_id = await _candidate_with_two_cvs(
        app_client, app_auth_headers
    )

    listing = await app_client.get(
        f"/api/candidates/{candidate_id}/documents", headers=app_auth_headers
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    # Główne CV pierwsze, potem najnowsze.
    assert [row["id"] for row in rows] == [primary_id, other_id]
    assert all(row["uploaded_by_name"] for row in rows)
    assert all(row["outdated_at"] is None for row in rows)


async def test_mark_outdated_and_undo(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id, _primary_id, other_id = await _candidate_with_two_cvs(
        app_client, app_auth_headers
    )
    url = f"/api/candidates/{candidate_id}/documents/{other_id}"

    marked = await app_client.patch(
        url, headers=app_auth_headers, json={"outdated": True}
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["outdated_at"] is not None
    assert marked.json()["outdated_by_name"]
    # Tylko plakietka — plik zostaje CV i zostaje w teczce.
    assert marked.json()["document_kind"] == "cv"

    undone = await app_client.patch(
        url, headers=app_auth_headers, json={"outdated": False}
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["outdated_at"] is None
    assert undone.json()["outdated_by_name"] is None


async def test_primary_cv_cannot_be_marked_outdated(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id, primary_id, _other_id = await _candidate_with_two_cvs(
        app_client, app_auth_headers
    )

    resp = await app_client.patch(
        f"/api/candidates/{candidate_id}/documents/{primary_id}",
        headers=app_auth_headers,
        json={"outdated": True},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Najpierw ustaw inne CV jako główne."


async def test_outdated_cv_cannot_become_primary_until_undone(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id, _primary_id, other_id = await _candidate_with_two_cvs(
        app_client, app_auth_headers
    )
    url = f"/api/candidates/{candidate_id}/documents/{other_id}"
    marked = await app_client.patch(
        url, headers=app_auth_headers, json={"outdated": True}
    )
    assert marked.status_code == 200, marked.text

    blocked = await app_client.patch(
        url, headers=app_auth_headers, json={"is_primary": True}
    )
    assert blocked.status_code == 409, blocked.text
    assert "nieaktualne" in blocked.json()["detail"]

    # Cofnięcie i ustawienie jako główne w jednym żądaniu jest dozwolone.
    both = await app_client.patch(
        url,
        headers=app_auth_headers,
        json={"outdated": False, "is_primary": True},
    )
    assert both.status_code == 200, both.text
    assert both.json()["is_primary"] is True
    assert both.json()["outdated_at"] is None
