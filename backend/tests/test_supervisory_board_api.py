"""Rada (R1) z bazą: odpis KRS, wiersze z wzmianek, dzwonek, dokumenty i bramki ról."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.board_document import BoardDocument, BoardKrsSnapshot
from app.models.notification import Notification, NotificationType
from app.services.board import krs as krs_service
from tests.test_sales_companies_api import _headers, _user
from tests.test_supervisory_board_unit import _odpis

API = "/api/supervisory-board"


@pytest.fixture(autouse=True)
async def _clean_board_tables():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoardDocument))
        await db.execute(delete(BoardKrsSnapshot))
        await db.commit()
    yield


async def _bells(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.board_krs_entry,
            )
        )


async def test_refresh_stores_once_seeds_documents_and_bells_only_new_entries(
    app_client, monkeypatch
) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    payloads = [_odpis(entries=3), _odpis(entries=3), _odpis(entries=4)]

    async def fake_fetch(_krs: str) -> dict:
        return payloads.pop(0)

    monkeypatch.setattr(krs_service, "fetch_full_extract", fake_fetch)

    first = await app_client.post(f"{API}/krs/refresh", headers=_headers(admin))
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["changed"] is True and body["new_entries"] == 0
    assert body["documents_created"] == len(
        krs_service.document_seeds(krs_service.parse_odpis(_odpis()))
    )
    assert await _bells(board.id) == 0  # pierwszy odpis to stan zastany

    again = (
        await app_client.post(f"{API}/krs/refresh", headers=_headers(admin))
    ).json()
    assert again["changed"] is False and again["documents_created"] == 0

    third = (
        await app_client.post(f"{API}/krs/refresh", headers=_headers(admin))
    ).json()
    assert third["changed"] is True and third["new_entries"] == 1
    assert await _bells(board.id) == 1

    view = (await app_client.get(f"{API}/krs", headers=_headers(board))).json()[
        "snapshot"
    ]
    assert view["entries_count"] == 4
    assert view["management"]["functions"] == ["PREZES ZARZĄDU"]
    assert view["missing_filings"][0]["year"] == 2025


async def test_board_reads_admin_writes_others_are_denied(app_client) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    finance = await _user("finance_module", role="finance")
    recruiter = await _user()

    created = await app_client.post(
        f"{API}/documents",
        headers=_headers(admin),
        data={
            "category": "resolution_supervisory",
            "organ": "supervisory",
            "number": "1/2026",
            "title": "Uchwała RN — budżet 2027",
            "doc_date": "2026-11-30",
        },
        files={"file": ("uchwala.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert created.status_code == 201, created.text
    doc = created.json()
    assert doc["has_file"] is True and doc["source"] == "upload"

    listed = await app_client.get(
        f"{API}/documents",
        params={"category": "resolution_supervisory"},
        headers=_headers(board),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [doc["id"]]
    counts = {c["key"]: c for c in listed.json()["categories"]}
    assert counts["resolution_supervisory"] == {
        "key": "resolution_supervisory",
        "total": 1,
        "without_file": 0,
    }

    file_resp = await app_client.get(
        f"{API}/documents/{doc['id']}/file", headers=_headers(board)
    )
    assert file_resp.status_code == 200 and file_resp.content.startswith(b"%PDF")

    for user in (finance, recruiter):
        assert (
            await app_client.get(f"{API}/documents", headers=_headers(user))
        ).status_code == 403
    assert (
        await app_client.patch(
            f"{API}/documents/{doc['id']}", json={"title": "x"}, headers=_headers(board)
        )
    ).status_code == 403
    assert (
        await app_client.delete(f"{API}/documents/{doc['id']}", headers=_headers(board))
    ).status_code == 403

    patched = await app_client.patch(
        f"{API}/documents/{doc['id']}",
        json={"subject": "przyjęcie budżetu na 2027", "organ": None},
        headers=_headers(admin),
    )
    assert patched.status_code == 200 and patched.json()["organ"] is None

    bad = await app_client.post(
        f"{API}/documents",
        headers=_headers(admin),
        data={"category": "nieznana", "title": "x"},
    )
    assert bad.status_code == 422

    wrong_type = await app_client.post(
        f"{API}/documents/{doc['id']}/file",
        headers=_headers(admin),
        files={"file": ("skrypt.exe", b"MZ", "application/octet-stream")},
    )
    assert wrong_type.status_code == 422

    assert (
        await app_client.delete(f"{API}/documents/{doc['id']}", headers=_headers(admin))
    ).status_code == 204


async def test_krs_row_cannot_be_deleted_but_takes_a_scan(
    app_client, monkeypatch
) -> None:
    admin = await _user(role="admin")

    async def fake_fetch(_krs: str) -> dict:
        return _odpis()

    monkeypatch.setattr(krs_service, "fetch_full_extract", fake_fetch)
    assert (
        await app_client.post(f"{API}/krs/refresh", headers=_headers(admin))
    ).status_code == 200
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(BoardDocument).where(BoardDocument.krs_key == "approval:2025")
            )
        ).scalar_one()
    assert (
        await app_client.delete(f"{API}/documents/{row.id}", headers=_headers(admin))
    ).status_code == 409
    attached = await app_client.post(
        f"{API}/documents/{row.id}/file",
        headers=_headers(admin),
        files={"file": ("zwz-2026.pdf", b"%PDF-1.4 zwz", "application/pdf")},
    )
    assert attached.status_code == 200 and attached.json()["has_file"] is True
    assert attached.json()["source"] == "krs"


async def test_krs_before_first_fetch_is_empty_not_error(app_client) -> None:
    board = await _user(role="board")
    resp = await app_client.get(f"{API}/krs", headers=_headers(board))
    assert resp.status_code == 200 and resp.json() == {"snapshot": None}
