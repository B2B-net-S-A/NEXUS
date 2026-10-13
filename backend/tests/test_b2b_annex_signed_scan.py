"""Skan podpisanego aneksu → Dokumenty kontraktu.

Do 13.10.2026 po „Oznacz jako podpisany” w kontrakcie lądował wygenerowany
DOCX (plik bez podpisów), a przy aneksie z danymi wrażliwymi — nic.

Render szablonów jest podmieniony (``_fake_render``). Baza wspólna
i nieczyszczona: asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services import storage_service
from app.services.b2b_documents import signed_scan
from app.services.contract_folder_docs import sync
from tests.test_b2b_documents_api import (  # noqa: F401
    BASE,
    _create,
    _fake_render,
    _signed_parent,
)

PDF = b"%PDF-1.4\n% skan testowy\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


# ── czyste reguły ────────────────────────────────────────────────────────────


def test_scan_is_a_pdf_or_a_picture_whose_content_matches_its_name():
    assert signed_scan.check_scan("Aneks.PDF", PDF) == ("Aneks.PDF", "application/pdf")
    assert signed_scan.check_scan("aneks.png", PNG)[1] == "image/png"
    assert signed_scan.check_scan("aneks.jpeg", b"\xff\xd8\xff\xe0")[1] == "image/jpeg"

    with pytest.raises(HTTPException) as word:
        signed_scan.check_scan("aneks.docx", b"PK\x03\x04")
    assert word.value.status_code == 415
    # Nazwa pochodzi z przeglądarki — sama nie mówi, co jest w pliku.
    with pytest.raises(HTTPException) as disguised:
        signed_scan.check_scan("aneks.pdf", PNG)
    assert disguised.value.status_code == 415
    with pytest.raises(HTTPException) as empty:
        signed_scan.check_scan("aneks.pdf", b"")
    assert empty.value.status_code == 422


def test_scan_over_the_limit_is_refused():
    too_big = PDF + b"0" * signed_scan.MAX_SCAN_BYTES
    with pytest.raises(HTTPException) as refused:
        signed_scan.check_scan("aneks.pdf", too_big)
    assert refused.value.status_code == 413


# ── API ──────────────────────────────────────────────────────────────────────


async def _signed_rate_annex(app_client, headers) -> tuple[int, int]:
    """Podpisany aneks stawki do umowy z rejestru: ``(doc_id, contract_id)``."""
    from app.models.contract import Contract, RateUnit

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_candidate = Decimal("150")
        contract.rate_candidate_currency = "PLN"
        contract.rate_unit = RateUnit.hourly
        await db.commit()
    doc_id = await _create(
        app_client,
        headers,
        "annex_rate_change",
        rid,
        effective_date="2026-11-01",
        rate_items=[{"rate": "165"}],
    )
    return doc_id, contract_id


async def _rate_amendment(contract_id: int):
    from app.models.contract_amendment import ContractAmendment, ContractAmendmentType

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(ContractAmendment).where(
                ContractAmendment.contract_id == contract_id,
                ContractAmendment.amendment_type == ContractAmendmentType.rate_change,
            )
        )


async def _upload(app_client, headers, url: str, name: str = "aneks.pdf", data=PDF):
    return await app_client.post(
        url, headers=headers, files={"file": (name, data, "application/octet-stream")}
    )


async def test_signed_scan_lands_in_contract_documents_and_on_the_amendment(
    app_client, app_auth_headers
):
    from app.models.b2b_contract_document import B2BContractDocument
    from app.models.contract_document import ContractDocument, ContractDocumentType

    doc_id, contract_id = await _signed_rate_annex(app_client, app_auth_headers)
    url = f"{BASE}/documents/{doc_id}/signed-scan"

    early = await _upload(app_client, app_auth_headers, url)
    assert early.status_code == 409, early.text

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    generated_id = (await _rate_amendment(contract_id)).document_id
    assert generated_id is not None

    refused = await _upload(app_client, app_auth_headers, url, "aneks.docx", b"PK\x03")
    assert refused.status_code == 415, refused.text

    done = await _upload(app_client, app_auth_headers, url, "Aneks podpisany.pdf")
    assert done.status_code == 200, done.text
    scan_id = done.json()["signed_scan_document_id"]
    assert scan_id is not None and scan_id != generated_id
    assert (await _rate_amendment(contract_id)).document_id == scan_id
    async with AsyncSessionLocal() as db:
        scan = await db.get(ContractDocument, scan_id)
        assert scan.contract_id == contract_id
        assert scan.doc_type == ContractDocumentType.annex
        assert scan.filename == "Aneks podpisany.pdf"
        assert scan.content_type == "application/pdf"
        assert scan.source == "upload"
        assert scan.content_sha256
        # Wygenerowany DOCX zostaje obok — to wersja robocza aneksu.
        assert await db.get(ContractDocument, generated_id) is not None
        doc = await db.get(B2BContractDocument, doc_id)
        assert doc.effect_summary["signed_scan_document_id"] == scan_id
        # Reszta zapisu skutku zostaje nietknięta.
        assert doc.effect_summary["contract_id"] == contract_id
        # Synchronizacja wysłała już ten skan do SharePointa.
        first_path = scan.file_path
        scan.sharepoint_item_id = f"up-{scan_id}"
        scan.sharepoint_push_status = "done"
        await db.commit()

    # Drugi skan podmienia pierwszy, nie dokłada kolejnego dokumentu.
    again = await _upload(app_client, app_auth_headers, url, "poprawiony.png", PNG)
    assert again.status_code == 200, again.text
    assert again.json()["signed_scan_document_id"] == scan_id
    async with AsyncSessionLocal() as db:
        scan = await db.get(ContractDocument, scan_id)
        assert scan.filename == "poprawiony.png"
        assert scan.content_type == "image/png"
        # W SharePoincie leży jeszcze stary skan: dokument wraca do wysyłki
        # z tym samym plikiem docelowym (do 13.10.2026 nie wracał wcale).
        assert scan.sharepoint_item_id == f"up-{scan_id}"
        assert scan.sharepoint_push_status is None
        waiting = await db.execute(
            sync._push_candidates(None).where(ContractDocument.id == scan_id)
        )
        assert len(waiting.all()) == 1
        new_path = scan.file_path
    # Stary plik znika dopiero po zapisie nowego.
    assert new_path != first_path
    assert storage_service.get_contract_document_path(new_path).read_bytes() == PNG
    with pytest.raises(FileNotFoundError):
        storage_service.get_contract_document_path(first_path)


async def test_scan_can_be_attached_from_the_contract_side_only_to_generator_annexes(
    app_client, app_auth_headers
):
    doc_id, contract_id = await _signed_rate_annex(app_client, app_auth_headers)
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    amendment = await _rate_amendment(contract_id)

    attached = await _upload(
        app_client,
        app_auth_headers,
        f"/api/contracts/{contract_id}/amendments/{amendment.id}/document",
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["document_id"] != amendment.document_id
    assert (await _rate_amendment(contract_id)).document_id == (
        attached.json()["document_id"]
    )

    # Aneks dodany ręcznie w kontrakcie nie jest dokumentem z generatora.
    manual = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        headers=app_auth_headers,
        json={
            "amendment_type": "scope_change",
            "effective_date": "2026-11-01",
            "new_project_name": "Hurtownia danych",
        },
    )
    assert manual.status_code == 201, manual.text
    refused = await _upload(
        app_client,
        app_auth_headers,
        f"/api/contracts/{contract_id}/amendments/{manual.json()['id']}/document",
    )
    assert refused.status_code == 422, refused.text
    missing = await _upload(
        app_client,
        app_auth_headers,
        f"/api/contracts/{contract_id}/amendments/2000000000/document",
    )
    assert missing.status_code == 404, missing.text
