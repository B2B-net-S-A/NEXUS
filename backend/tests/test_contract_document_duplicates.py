"""Jeden plik raz w Dokumentach kontraktu (decyzja Artura 19.11.2026).

Produkcja 19.11.2026 (1574 dokumenty): ten sam SHA-256 w jednym kontrakcie
w 12 kontraktach, 17 zbędnych kopii z ręcznego uploadu, w tym cztery obok skanu
podpisanego aneksu z Generatora; kopia PDF-u zamówienia zbiorczego obok
ręcznego pliku; PDF linii zamówienia i kopia PDF-u jej grupy jako dwa wiersze
w folderze „Zamówienia” (14 par). Wariant „Blokada uploadu + jedna kopia”:

* ręczny upload pliku, który kontrakt już ma → 409 ``document_duplicate``;
* kopia PDF-u grupy nie powstaje na kontrakcie, który ma już ten plik;
* skan aneksu wskazuje istniejący dokument, a „Podmień skan” go nie nadpisuje;
* trasa ``by-contract`` mówi, że PDF linii to ten sam plik co kopia grupy.

Baza wspólna i nieczyszczona: każdy test ma własne kontrakty, pliki leżą
w ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import io

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services import storage_service
from app.services.b2b_documents import signed_scan
from tests._permission_grants import grant_permissions
from tests.test_b2b_annex_signed_scan import _rate_amendment, _signed_rate_annex
from tests.test_b2b_documents_api import BASE, _fake_render  # noqa: F401
from tests.test_multi_consultant_orders import (
    _create_group,
    _enable_for,
    _line_payload,
    _seed_client_with_contracts,
)
from tests.test_permissions_contracts import _account, _contract

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n% zamowienie 4522222072\n"
SCAN = b"%PDF-1.4\n% skan podpisanego aneksu\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 24


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _isolated_storage(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "CONTRACTS_DIR", tmp_path / "contracts")
    monkeypatch.setattr(
        storage_service, "CLIENT_ORDER_POS_DIR", tmp_path / "client_orders"
    )
    monkeypatch.setattr(
        storage_service, "CLIENT_ORDER_GROUP_POS_DIR", tmp_path / "client_order_groups"
    )


async def _upload(
    app_client: AsyncClient,
    headers: dict,
    contract_id: int,
    name: str,
    data: bytes,
    doc_type: str = "other",
):
    return await app_client.post(
        f"/api/contracts/{contract_id}/documents",
        headers=headers,
        files={"file": (name, data, "application/pdf")},
        data={"doc_type": doc_type},
    )


async def _documents(contract_id: int) -> list[ContractDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(ContractDocument)
                    .where(ContractDocument.contract_id == contract_id)
                    .order_by(ContractDocument.id)
                )
            ).all()
        )


async def _group_copies(group_id: int) -> dict[int, ContractDocument]:
    async with AsyncSessionLocal() as db:
        copies = (
            await db.scalars(
                select(ContractDocument).where(
                    ContractDocument.source_order_group_id == group_id
                )
            )
        ).all()
        return {copy.contract_id: copy for copy in copies}


# ── Ręczny upload ────────────────────────────────────────────────────────────


async def test_the_same_file_twice_is_refused_and_leaves_nothing_on_disk(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    _isolated_storage(monkeypatch, tmp_path)
    contract_id, _ = await _contract()
    other_contract_id, _ = await _contract()

    first = await _upload(
        app_client, app_auth_headers, contract_id, "PO 4522222072.pdf", PDF, "order"
    )
    assert first.status_code == 201, first.text

    again = await _upload(app_client, app_auth_headers, contract_id, "kopia.pdf", PDF)
    assert again.status_code == 409, again.text
    detail = again.json()["detail"]
    assert detail["code"] == "document_duplicate"
    assert detail["document"]["id"] == first.json()["id"]
    assert detail["document"]["filename"] == "PO 4522222072.pdf"
    assert "„PO 4522222072.pdf”" in detail["message"]
    assert business_today().strftime("%d.%m.%Y") in detail["message"]
    # Zapisany plik znika z dysku, w bazie nic nie przybywa.
    stored = list((tmp_path / "contracts" / str(contract_id)).iterdir())
    assert len(stored) == 1, stored
    assert [doc.id for doc in await _documents(contract_id)] == [first.json()["id"]]
    async with AsyncSessionLocal() as db:
        assert await db.scalar(
            select(ContractDocument.content_sha256).where(
                ContractDocument.id == first.json()["id"]
            )
        ) == _sha(PDF)

    # Inny plik na tym kontrakcie i ten sam plik na innym kontrakcie przechodzą.
    other_file = await _upload(
        app_client, app_auth_headers, contract_id, "aneks.pdf", PDF + b"% 2\n", "annex"
    )
    assert other_file.status_code == 201, other_file.text
    elsewhere = await _upload(
        app_client, app_auth_headers, other_contract_id, "PO.pdf", PDF, "order"
    )
    assert elsewhere.status_code == 201, elsewhere.text


async def test_refusal_names_no_file_for_an_account_without_the_amounts_view(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    """Dodanie pliku jest otwarte bez podglądu kwot (22.10.2026), lista nie —
    odmowa nie może zdradzić nazwy pliku, którego ta osoba nie widzi."""
    _isolated_storage(monkeypatch, tmp_path)
    contract_id, _ = await _contract()
    tcm, tcm_id = await _account(app_client, "talent_community_manager")
    await grant_permissions(tcm_id, "contracts_orders_edit")

    first = await _upload(
        app_client, app_auth_headers, contract_id, "Umowa B2B 12-2025.pdf", PDF
    )
    assert first.status_code == 201, first.text

    refused = await _upload(app_client, tcm, contract_id, "umowa.pdf", PDF)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "document_duplicate"
    assert detail["document"]["filename"] is None
    assert "Umowa B2B" not in detail["message"]
    assert business_today().strftime("%d.%m.%Y") in detail["message"]


async def test_a_row_without_a_hash_counts_and_a_row_without_its_file_does_not(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    """Kopie PDF-ów grup sprzed 20.11.2026 nie mają skrótu — porównujemy plik.
    Wiersz, którego pliku nie ma na dysku, nie blokuje wgrania go z powrotem."""
    _isolated_storage(monkeypatch, tmp_path)
    contract_id, _ = await _contract()
    legacy = b"%PDF-1.4\n% kopia sprzed skrotow\n"
    lost = b"%PDF-1.4\n% plik zgubiony z dysku\n"
    async with AsyncSessionLocal() as db:
        path, size = storage_service.save_contract_document(
            contract_id, "0087020757.pdf", io.BytesIO(legacy)
        )
        db.add(
            ContractDocument(
                contract_id=contract_id,
                filename="0087020757.pdf",
                file_path=path,
                size_bytes=size,
                doc_type=ContractDocumentType.order,
            )
        )
        db.add(
            ContractDocument(
                contract_id=contract_id,
                filename="zgubiony.pdf",
                file_path=f"contracts/{contract_id}/nie-ma-na-dysku.pdf",
                size_bytes=len(lost),
                doc_type=ContractDocumentType.other,
                content_sha256=_sha(lost),
            )
        )
        await db.commit()

    refused = await _upload(
        app_client, app_auth_headers, contract_id, "PO0087020757.PDF", legacy, "order"
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["document"]["filename"] == "0087020757.pdf"

    restored = await _upload(
        app_client, app_auth_headers, contract_id, "zgubiony.pdf", lost
    )
    assert restored.status_code == 201, restored.text


# ── Kopia PDF-u zamówienia zbiorczego ────────────────────────────────────────


async def test_group_pdf_copy_skips_a_contract_that_already_has_the_file(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    _isolated_storage(monkeypatch, tmp_path)
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    manual = await _upload(
        app_client, app_auth_headers, contracts[0], "PO0087020757.PDF", PDF, "order"
    )
    assert manual.status_code == 201, manual.text
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0]), _line_payload(contracts[1])],
    )
    file_url = f"/api/clients/{client_id}/order-groups/{group['id']}/file"

    put = await app_client.put(
        file_url,
        headers=app_auth_headers,
        files={"file": ("0087020757.pdf", PDF, "application/pdf")},
    )
    assert put.status_code == 200, put.text
    copies = await _group_copies(group["id"])
    assert set(copies) == {contracts[1]}, "kontrakt z tym PDF-em dostał drugą kopię"
    assert copies[contracts[1]].content_sha256 == _sha(PDF)
    assert [doc.id for doc in await _documents(contracts[0])] == [manual.json()["id"]]

    # Nowa treść PDF-u: kontrakt bez niej dostaje kopię, istniejąca się podmienia.
    second = PDF + b"% wersja 2\n"
    replaced = await app_client.put(
        file_url,
        headers=app_auth_headers,
        files={"file": ("0087020757-v2.pdf", second, "application/pdf")},
    )
    assert replaced.status_code == 200, replaced.text
    after = await _group_copies(group["id"])
    assert set(after) == set(contracts)
    assert after[contracts[1]].id == copies[contracts[1]].id
    assert {copy.content_sha256 for copy in after.values()} == {_sha(second)}
    # Ręczny dokument zostaje nietknięty.
    kept = [
        doc for doc in await _documents(contracts[0]) if doc.id == manual.json()["id"]
    ]
    assert kept and kept[0].content_sha256 == _sha(PDF)


async def test_orders_folder_learns_that_the_line_pdf_is_the_group_copy(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    _isolated_storage(monkeypatch, tmp_path)
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line_id = group["lines"][0]["id"]
    put = await app_client.put(
        f"/api/clients/{client_id}/order-groups/{group['id']}/file",
        headers=app_auth_headers,
        files={"file": ("445.pdf", PDF, "application/pdf")},
    )
    assert put.status_code == 200, put.text
    copy = (await _group_copies(group["id"]))[contracts[0]]

    async def listing() -> dict[int, dict]:
        resp = await app_client.get(
            f"/api/clients/order-documents/by-contract/{contracts[0]}",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        return {item["order_id"]: item for item in resp.json()["documents"]}

    async def put_line_pdf(data: bytes) -> None:
        resp = await app_client.put(
            f"/api/clients/{client_id}/orders/{line_id}/file",
            headers=app_auth_headers,
            files={"file": ("PO-linia.pdf", data, "application/pdf")},
        )
        assert resp.status_code == 200, resp.text

    await put_line_pdf(PDF)
    assert (await listing())[line_id]["same_file_document_id"] == copy.id

    # Ten sam rozmiar, inna treść — dwa różne pliki, dwa wiersze.
    same_size = PDF[:-2] + b"X\n"
    assert len(same_size) == len(PDF)
    await put_line_pdf(same_size)
    assert (await listing())[line_id]["same_file_document_id"] is None


async def test_a_stale_hash_on_a_group_copy_decides_nothing(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    """Przegląd kodu 20.11.2026: do tej zmiany kopia PDF-u grupy nie dostawała
    skrótu, import z SharePointa dopisywał go, a podmiana PDF-u grupy zostawiała
    stary. Rozstrzyga plik na dysku, nie kolumna."""
    _isolated_storage(monkeypatch, tmp_path)
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    contract_id = contracts[0]
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contract_id)]
    )
    line_id = group["lines"][0]["id"]
    old = PDF
    current = PDF[:-2] + b"Y\n"
    assert len(old) == len(current)
    put = await app_client.put(
        f"/api/clients/{client_id}/order-groups/{group['id']}/file",
        headers=app_auth_headers,
        files={"file": ("445.pdf", current, "application/pdf")},
    )
    assert put.status_code == 200, put.text
    async with AsyncSessionLocal() as db:
        copy = (
            await db.scalars(
                select(ContractDocument).where(
                    ContractDocument.source_order_group_id == group["id"]
                )
            )
        ).one()
        # Stan po imporcie z SharePointa przy starym PDF-ie i podmianie na main.
        copy.content_sha256 = _sha(old)
        await db.commit()
        copy_id = copy.id

    # PDF linii równy staremu skrótowi kopii nie ukrywa kopii, która ma inny plik.
    line_pdf = await app_client.put(
        f"/api/clients/{client_id}/orders/{line_id}/file",
        headers=app_auth_headers,
        files={"file": ("PO-linia.pdf", old, "application/pdf")},
    )
    assert line_pdf.status_code == 200, line_pdf.text
    listing = await app_client.get(
        f"/api/clients/order-documents/by-contract/{contract_id}",
        headers=app_auth_headers,
    )
    assert listing.status_code == 200, listing.text
    items = {item["order_id"]: item for item in listing.json()["documents"]}
    assert items[line_id]["same_file_document_id"] is None

    # Pliku ze starego skrótu na kontrakcie nie ma — przechodzi…
    fresh = await _upload(app_client, app_auth_headers, contract_id, "PO-v1.pdf", old)
    assert fresh.status_code == 201, fresh.text
    # …a ten, który naprawdę leży w kopii grupy, dostaje odmowę.
    duplicate = await _upload(
        app_client, app_auth_headers, contract_id, "PO-v2.pdf", current, "order"
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"]["document"]["id"] == copy_id


# ── Skan podpisanego aneksu z Generatora ─────────────────────────────────────


async def test_annex_scan_points_to_the_file_the_contract_already_has(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    _isolated_storage(monkeypatch, tmp_path)
    doc_id, contract_id = await _signed_rate_annex(app_client, app_auth_headers)
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    manual = await _upload(
        app_client,
        app_auth_headers,
        contract_id,
        "Aneks 1 podpisany.pdf",
        SCAN,
        "annex",
    )
    assert manual.status_code == 201, manual.text
    manual_id = manual.json()["id"]
    url = f"{BASE}/documents/{doc_id}/signed-scan"

    def scan_file(name: str, data: bytes) -> dict:
        return {"file": (name, data, "application/octet-stream")}

    attached = await app_client.post(
        url, headers=app_auth_headers, files=scan_file("skan.pdf", SCAN)
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["signed_scan_document_id"] == manual_id
    assert (await _rate_amendment(contract_id)).document_id == manual_id
    async with AsyncSessionLocal() as db:
        copies = await db.scalar(
            select(func.count())
            .select_from(ContractDocument)
            .where(
                ContractDocument.contract_id == contract_id,
                ContractDocument.content_sha256 == _sha(SCAN),
            )
        )
    assert copies == 1, "skan dołożył drugą kopię pliku"

    # „Podmień skan” nie nadpisuje dokumentu, który był w Dokumentach wcześniej.
    replaced = await app_client.post(
        url, headers=app_auth_headers, files=scan_file("poprawiony.png", PNG)
    )
    assert replaced.status_code == 200, replaced.text
    own_id = replaced.json()["signed_scan_document_id"]
    assert own_id != manual_id
    assert (await _rate_amendment(contract_id)).document_id == own_id
    async with AsyncSessionLocal() as db:
        kept = await db.get(ContractDocument, manual_id)
        assert kept.filename == "Aneks 1 podpisany.pdf"
        assert kept.content_sha256 == _sha(SCAN)
        assert (
            storage_service.get_contract_document_path(kept.file_path).read_bytes()
            == SCAN
        )

    # Skan zapisany przez Generator podmienia się dalej w miejscu.
    third = SCAN + b"% poprawka\n"
    again = await app_client.post(
        url, headers=app_auth_headers, files=scan_file("ostateczny.pdf", third)
    )
    assert again.status_code == 200, again.text
    assert again.json()["signed_scan_document_id"] == own_id
    async with AsyncSessionLocal() as db:
        own = await db.get(ContractDocument, own_id)
        assert own.filename == "ostateczny.pdf"
        assert own.content_sha256 == _sha(third)


async def test_annex_scan_never_borrows_a_group_copy_or_a_generator_file(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    """Kopię PDF-u grupy podmienia zamówienie, a plik Generatora jego własne
    „Podmień” — skan wskazujący taki plik zmieniłby się pod aneksem."""
    _isolated_storage(monkeypatch, tmp_path)
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    contract_id = contracts[0]
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contract_id)]
    )
    put = await app_client.put(
        f"/api/clients/{client_id}/order-groups/{group['id']}/file",
        headers=app_auth_headers,
        files={"file": ("445.pdf", PDF, "application/pdf")},
    )
    assert put.status_code == 200, put.text

    async with AsyncSessionLocal() as db:
        path, size = storage_service.save_contract_document(
            contract_id,
            "skan innego aneksu.pdf",
            io.BytesIO(SCAN),
            stored_name="b2b-document-424242-skan-0123456789abcdef.pdf",
        )
        db.add(
            ContractDocument(
                contract_id=contract_id,
                filename="skan innego aneksu.pdf",
                file_path=path,
                size_bytes=size,
                doc_type=ContractDocumentType.annex,
                content_sha256=_sha(SCAN),
                source="upload",
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert (
            await signed_scan._existing_copy(db, contract_id, _sha(PDF), len(PDF))
            is None
        )
        assert (
            await signed_scan._existing_copy(db, contract_id, _sha(SCAN), len(SCAN))
            is None
        )
        path, size = storage_service.save_contract_document(
            contract_id, "Aneks podpisany.pdf", io.BytesIO(SCAN)
        )
        manual = ContractDocument(
            contract_id=contract_id,
            filename="Aneks podpisany.pdf",
            file_path=path,
            size_bytes=size,
            doc_type=ContractDocumentType.annex,
            content_sha256=_sha(SCAN),
            source="upload",
        )
        db.add(manual)
        await db.flush()
        found = await signed_scan._existing_copy(db, contract_id, _sha(SCAN), len(SCAN))
        assert found is not None and found.id == manual.id
        await db.rollback()
