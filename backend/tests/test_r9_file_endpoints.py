"""Runda 9 (FILES): zapisy plików kontraktów, zamówień i dokumentów wymaganych.

* R9-N7-4 — nazwa pliku z przeglądarki dłuższa niż kolumna (255) dawała
  DataError (500) i plik osierocony na dysku,
* R9-N7-5 — plik kasowany PRZED commitem; wysłany do podpisu snapshot
  (FK RESTRICT) wywracał commit już po 204,
* R9-N7-9 — pobranie PDF zamówienia bez pliku na dysku = 500 zamiast 410,
* R9-X2-2 — lista PDF-ów zamówień kontraktu nie sprawdzała klienta ZAMÓWIENIA.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio

_PDF = b"%PDF-1.4\n% minimalny plik\n"
_LONG_NAME = "Zamówienie_dla_konsultanta_" + "ąęśćżźółń" * 40 + ".pdf"


async def _seed_contract(client_name: str | None = None) -> dict[str, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Plik",
            lastname=f"R9-{uuid.uuid4().hex[:6]}",
            email=f"r9-files-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=client_name or f"R9Files-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=5),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            margin=Decimal("50.000"),
        )
        db.add(contract)
        await db.commit()
        return {
            "client_id": client.id,
            "candidate_id": cand.id,
            "contract_id": contract.id,
        }


async def _any_user_id() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        return int(await db.scalar(select(User.id).order_by(User.id).limit(1)))


async def test_contract_document_long_name_and_signed_snapshot_is_not_deleted(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract_document import ContractDocument
    from app.models.document_signature import DocumentSignature, SignatureStatus
    from app.services import storage_service

    ids = await _seed_contract()
    upload = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/documents",
        headers=app_auth_headers,
        files={"file": (_LONG_NAME, _PDF, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert len(body["filename"]) <= 255
    assert body["filename"].endswith(".pdf")
    doc_id = body["id"]

    async with AsyncSessionLocal() as db:
        doc = await db.get(ContractDocument, doc_id)
        file_path = doc.file_path
        signature = DocumentSignature(
            contract_id=ids["contract_id"],
            contract_document_id=doc_id,
            status=SignatureStatus.sent,
            sender_user_id=await _any_user_id(),
            signer_email="r9@example.com",
            signer_first_name="R",
            signer_last_name="Dziewięć",
        )
        db.add(signature)
        await db.commit()
        signature_id = signature.id

    refused = await app_client.delete(
        f"/api/contracts/{ids['contract_id']}/documents/{doc_id}",
        headers=app_auth_headers,
    )
    assert refused.status_code == 409, refused.text
    # Plik i wiersz zostają — to zapis tego, co wysłano do podpisu.
    assert storage_service.get_contract_document_path(file_path).is_file()
    async with AsyncSessionLocal() as db:
        assert await db.get(ContractDocument, doc_id) is not None
        await db.delete(await db.get(DocumentSignature, signature_id))
        await db.commit()

    deleted = await app_client.delete(
        f"/api/contracts/{ids['contract_id']}/documents/{doc_id}",
        headers=app_auth_headers,
    )
    assert deleted.status_code == 204, deleted.text
    with pytest.raises(FileNotFoundError):
        storage_service.get_contract_document_path(file_path)


async def test_required_document_replacement_keeps_the_old_file_until_commit(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_required_document import ClientRequiredDocument
    from app.services import storage_service

    ids = await _seed_contract()
    async with AsyncSessionLocal() as db:
        required = ClientRequiredDocument(client_id=ids["client_id"], name="NDA R9")
        db.add(required)
        await db.commit()
        doc_id = required.id

    url = f"/api/clients/{ids['client_id']}/required-documents/{doc_id}/upload"
    first = await app_client.post(
        url,
        headers=app_auth_headers,
        files={"file": (_LONG_NAME, _PDF, "application/pdf")},
    )
    assert first.status_code == 200, first.text
    assert len(first.json()["filename"]) <= 255
    async with AsyncSessionLocal() as db:
        old_path = (await db.get(ClientRequiredDocument, doc_id)).file_path

    second = await app_client.post(
        url,
        headers=app_auth_headers,
        files={"file": ("nda.pdf", _PDF, "application/pdf")},
    )
    assert second.status_code == 200, second.text
    async with AsyncSessionLocal() as db:
        new_path = (await db.get(ClientRequiredDocument, doc_id)).file_path
    assert new_path != old_path
    assert storage_service.get_client_required_doc_path(new_path).is_file()
    with pytest.raises(FileNotFoundError):
        storage_service.get_client_required_doc_path(old_path)

    removed = await app_client.delete(
        f"/api/clients/{ids['client_id']}/required-documents/{doc_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text
    with pytest.raises(FileNotFoundError):
        storage_service.get_client_required_doc_path(new_path)


async def test_order_pdf_missing_on_disk_is_410(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    ids = await _seed_contract()
    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=ids["client_id"],
            contract_id=ids["contract_id"],
            title=f"PO-{uuid.uuid4().hex[:5]}",
            status=ClientOrderStatus.draft,
            file_path=f"client_orders/{ids['client_id']}/nie-ma-{uuid.uuid4().hex}.pdf",
            filename="po.pdf",
        )
        db.add(order)
        await db.commit()
        order_id = order.id

    resp = await app_client.get(
        f"/api/clients/{ids['client_id']}/orders/{order_id}/file",
        headers=app_auth_headers,
    )
    assert resp.status_code == 410, resp.text


async def test_contract_order_documents_hide_orders_of_a_client_the_user_cannot_read(
    app_client: AsyncClient,
):
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from tests.test_multi_consultant_orders import _headers_for, _seed_user

    ids = await _seed_contract()
    async with AsyncSessionLocal() as db:
        other = Client(name=f"R9Other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.flush()
        own = ClientOrder(
            client_id=ids["client_id"],
            contract_id=ids["contract_id"],
            title="PO własnego klienta",
            status=ClientOrderStatus.draft,
            file_path="client_orders/r9/own.pdf",
            filename="own.pdf",
        )
        # Rozjazd znany z produkcji: zamówienie innego klienta na tym kontrakcie.
        foreign = ClientOrder(
            client_id=other.id,
            contract_id=ids["contract_id"],
            title="PO obcego klienta",
            status=ClientOrderStatus.draft,
            file_path="client_orders/r9/foreign.pdf",
            filename="foreign.pdf",
        )
        db.add_all([own, foreign])
        await db.commit()
        own_id, foreign_id = own.id, foreign.id

    _, email, password = await _seed_user("delivery_lead", ids["client_id"])
    dl_headers = await _headers_for(app_client, email, password)
    resp = await app_client.get(
        f"/api/clients/order-documents/by-contract/{ids['contract_id']}",
        headers=dl_headers,
    )
    assert resp.status_code == 200, resp.text
    listed = {d["order_id"] for d in resp.json()["documents"]}
    assert own_id in listed
    assert foreign_id not in listed
