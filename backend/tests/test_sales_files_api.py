"""Sprzedaż → Pliki: wgranie do firmy i szansy, typy, rozmiar, pobranie, usuwa autor."""

from __future__ import annotations

import uuid

import pytest

from app.services import storage_service
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/files"


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "SALES_FILES_DIR", tmp_path / "sales_files")
    return tmp_path


@pytest.mark.asyncio
async def test_upload_list_download_and_only_author_deletes(
    app_client, storage
) -> None:
    rep = await _user("sales_edit")
    other = await _user("sales_edit")
    viewer = await _user("sales_view")
    company = (
        await app_client.post(
            "/api/sales/companies",
            json={"name": f"Pliki {uuid.uuid4().hex[:8]}"},
            headers=_headers(rep),
        )
    ).json()
    opp = (
        await app_client.post(
            "/api/sales/opportunities",
            json={"company_id": company["id"], "title": "Z plikiem"},
            headers=_headers(rep),
        )
    ).json()

    uploaded = await app_client.post(
        URL,
        data={"opportunity_id": str(opp["id"])},
        files={"file": ("oferta klienta.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers=_headers(rep),
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]

    # Karta firmy widzi też pliki swoich szans.
    on_company = (
        await app_client.get(
            URL, params={"company_id": company["id"]}, headers=_headers(viewer)
        )
    ).json()
    assert [f["id"] for f in on_company] == [file_id]

    download = await app_client.get(
        f"{URL}/{file_id}/download", headers=_headers(viewer)
    )
    assert download.status_code == 200
    assert download.content == b"%PDF-1.4 test"
    assert "attachment" in download.headers["content-disposition"]

    exe = await app_client.post(
        URL,
        data={"company_id": str(company["id"])},
        files={"file": ("instalator.exe", b"MZ", "application/octet-stream")},
        headers=_headers(rep),
    )
    assert exe.status_code == 422
    both = await app_client.post(
        URL,
        data={"company_id": str(company["id"]), "opportunity_id": str(opp["id"])},
        files={"file": ("a.pdf", b"x", "application/pdf")},
        headers=_headers(rep),
    )
    assert both.status_code == 422
    denied_upload = await app_client.post(
        URL,
        data={"company_id": str(company["id"])},
        files={"file": ("a.pdf", b"x", "application/pdf")},
        headers=_headers(viewer),
    )
    assert denied_upload.status_code == 403

    assert (
        await app_client.delete(f"{URL}/{file_id}", headers=_headers(other))
    ).status_code == 403
    assert (
        await app_client.delete(f"{URL}/{file_id}", headers=_headers(rep))
    ).status_code == 204
    assert not list((storage / "sales_files").rglob("*.pdf"))


@pytest.mark.asyncio
async def test_too_big_file_is_refused(app_client, storage, monkeypatch) -> None:
    from app.api import sales_files

    monkeypatch.setattr(sales_files, "MAX_BYTES", 10)
    rep = await _user("sales_edit")
    company = (
        await app_client.post(
            "/api/sales/companies",
            json={"name": f"Duzy {uuid.uuid4().hex[:8]}"},
            headers=_headers(rep),
        )
    ).json()
    resp = await app_client.post(
        URL,
        data={"company_id": str(company["id"])},
        files={"file": ("duzy.pdf", b"x" * 11, "application/pdf")},
        headers=_headers(rep),
    )
    assert resp.status_code == 413
