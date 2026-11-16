"""Archiwum dokumentów z eBI24 (E5) — import paczki, lista, plik, dostęp. Dane fikcyjne."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api import finance_archive as api
from app.core.database import AsyncSessionLocal
from app.models.finance_archive import FinanceArchiveDocument
from app.services import storage_service
from app.services.finance_ledger import archive
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

BASE = "/api/finance/archive-ebi24"
COST_ID = "6aedb26a96e7de43680a5a48"
SALE_ID = "6ae9989cb3aef10f3cf0ab6b"
PDF = b"%PDF-1.7\n%fikcyjny\n%%EOF"
SALE_DOC = {
    "invoiceNumber": "1/1/2026",
    "issuedDate": "2026-01-02T00:00:00.000",
    "currency": "PLN",
    "nettAmount": 400000,
    "taxAmount": 92000,
    "grossAmount": 492000,
    "vendor": {"name": "Spółka Testowa", "officialId": fx.COMPANY_NIP},
    "customer": {"name": "Klient <b>Testowy</b>", "officialId": fx.CLIENT_NIP},
    "items": [
        {
            "name": "Usługa",
            "amountOfUnits": 1,
            "unitNettPrice": 400000,
            "taxRate": "23",
            "nettAmount": 400000,
            "grossAmount": 492000,
        }
    ],
}
META = [
    {
        "_id": COST_ID,
        "_bucketNumber": 60836,
        "_schemaName": "COST_INVOICE",
        "_partner": {"name": "Dostawca Testowy", "officialId": "3333333333"},
        "invoiceNumber": "254/11/2026/PRO",
        "issuedDate": "2026-11-06T00:00:00.000",
        "currency": "PLN",
        "nettAmount": 5691,
        "taxAmount": 1309,
        "grossAmount": 7000,
        "_plnGrossAmount": 7000,
        "paid": True,
        "_accountancyWorkflowLog": [{"event": "STARTED"}],
        "_documentsMetaData": {
            "document": {"documentType": "FILE", "fileName": "faktura.pdf"}
        },
    },
    {
        "_id": SALE_ID,
        "_bucketNumber": 100,
        "_schemaName": "INCOME_INVOICE",
        "_partner": {"name": "Klient Testowy", "officialId": fx.CLIENT_NIP},
        "_ksefReferenceNumber": f"{fx.COMPANY_NIP}-20260102-ABC-01",
        "invoiceNumber": "1/1/2026",
        "issuedDate": "2026-01-02T00:00:00.000",
        "currency": "PLN",
        "nettAmount": 400000,
        "grossAmount": 492000,
    },
]


def _package(meta=META, files=None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("metadane.json", json.dumps(meta))
        for name, data in (
            files
            or {
                f"pliki/{COST_ID}.pdf": PDF,
                f"pliki/{SALE_ID}.json": json.dumps(SALE_DOC).encode(),
            }
        ).items():
            zf.writestr(name, data)
    return buffer.getvalue()


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    target = FastAPI()
    target.include_router(api.router, prefix=BASE)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def seed():
    data = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        await db.execute(delete(FinanceArchiveDocument))
        await db.commit()
    yield data
    async with AsyncSessionLocal() as db:
        await db.execute(delete(FinanceArchiveDocument))
        await db.commit()
    await fx.wipe()


async def _upload(client, seed, content: bytes, role: str = "admin"):
    return await client.post(
        f"{BASE}/import",
        files={"file": ("paczka-001.zip", content, "application/zip")},
        headers=fx.headers(seed.users[role]),
    )


async def test_import_is_admin_only_and_idempotent(client, seed):
    refused = await _upload(client, seed, _package(), role="finance")
    assert refused.status_code == 403
    first = await _upload(client, seed, _package())
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 2
    again = await _upload(client, seed, _package())
    assert again.json() == {"created": 0, "skipped": 2, "errors": [], "error_count": 0}


async def test_list_search_amounts_and_files(client, seed):
    await _upload(client, seed, _package())
    headers = fx.headers(seed.users["admin"])
    listing = (await client.get(BASE, params={"kind": "cost"}, headers=headers)).json()
    assert listing["total"] == 1
    (cost,) = listing["documents"]
    # eBI24 trzyma kwoty w groszach.
    assert (cost["net"], cost["gross"], cost["paid"]) == ("56.91", "70.00", True)
    assert cost["file_type"] == "pdf"
    search = (
        await client.get(BASE, params={"q": "20260102-abc"}, headers=headers)
    ).json()
    assert [d["invoice_number"] for d in search["documents"]] == ["1/1/2026"]
    by_nip = (
        await client.get(BASE, params={"q": fx.CLIENT_NIP}, headers=headers)
    ).json()
    assert by_nip["total"] == 1
    year = (
        await client.get(BASE, params={"year": 2026, "month": 1}, headers=headers)
    ).json()
    assert year["total"] == 1

    pdf = await client.get(f"{BASE}/{cost['id']}/file", headers=headers)
    assert pdf.status_code == 200 and pdf.content == PDF
    assert pdf.headers["content-type"] == "application/pdf"
    sale_id = search["documents"][0]["id"]
    view = await client.get(f"{BASE}/{sale_id}/file", headers=headers)
    assert view.status_code == 200
    assert "4 000,00 PLN" in view.text and "4 920,00 PLN" in view.text
    assert "<b>Testowy</b>" not in view.text  # dane z eBI24 są escapowane
    raw = (await client.get(f"{BASE}/{sale_id}/raw", headers=headers)).json()
    assert raw["document"]["invoiceNumber"] == "1/1/2026"
    async with AsyncSessionLocal() as db:
        doc = await db.get(FinanceArchiveDocument, cost["id"])
        assert (
            "_accountancyWorkflowLog" not in doc.meta
        )  # stan obiegu eBI24 nie przechodzi
    summary = (await client.get(f"{BASE}/summary", headers=headers)).json()
    assert summary["total"] == 2
    assert summary["years"][0] == {"year": "2026", "sale": 1, "cost": 1, "other": 0}


async def test_package_errors(client, seed):
    bad = await _upload(client, seed, b"to nie zip")
    assert bad.status_code == 422
    missing = await _upload(client, seed, _package(files={f"pliki/{COST_ID}.pdf": PDF}))
    body = missing.json()
    assert body["created"] == 1 and body["error_count"] == 1
    assert SALE_ID in body["errors"][0]
    traversal = await _upload(
        client, seed, _package(meta=[META[0]], files={"pliki/../../etc.pdf": PDF})
    )
    assert traversal.json()["created"] == 0


async def test_recruiter_cannot_read_archive(client, seed):
    response = await client.get(BASE, headers=fx.headers(seed.users["recruiter"]))
    assert response.status_code == 403


def test_kind_mapping():
    assert archive.kind_of("EUROPEAN_INCOME_INVOICE") == "sale"
    assert archive.kind_of("COST_INVOICE") == "cost"
    assert archive.kind_of("OTHER_EXPENSE") == "cost"
    assert archive.kind_of("INCOME_ORDER") == "sale"
    assert archive.kind_of("FILE") == "other"
