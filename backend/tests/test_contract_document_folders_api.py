"""0494: foldery w Dokumentach kontraktu — trasy na prawdziwej bazie.

Baza testowa jest wspólna i nieczyszczona: każdy test zakłada własny
kontrakt i sprawdza wyłącznie jego dokumenty.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_document import (
    ContractDocument,
    ContractDocumentFolder,
    ContractDocumentType as T,
)


async def _seed(files: list[tuple[str, T]]) -> tuple[int, list[int]]:
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Folder", lastname=f"Test-{marker}")
        client = Client(name=f"Klient Folderów {marker}")
        db.add_all([candidate, client])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2026, 1, 1),
        )
        db.add(contract)
        await db.flush()
        ids = []
        for filename, doc_type in files:
            doc = ContractDocument(
                contract_id=contract.id,
                filename=filename,
                file_path=f"contracts/{contract.id}/{uuid.uuid4().hex}.pdf",
                doc_type=doc_type,
                size_bytes=100,
            )
            db.add(doc)
            await db.flush()
            ids.append(doc.id)
        await db.commit()
        return contract.id, ids


async def _folder_ids(doc_ids: list[int]) -> dict[int, int | None]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ContractDocument.id, ContractDocument.folder_id).where(
                ContractDocument.id.in_(doc_ids)
            )
        )
        return {doc_id: folder_id for doc_id, folder_id in rows.all()}


async def test_folder_lifecycle(app_client: AsyncClient, app_auth_headers: dict):
    cid, (new_umowa, old_umowa, old_aneks, termination, order) = await _seed(
        [
            ("Umowa B2B nr 518-2026.pdf", T.contract),
            ("Umowa nr 361-2019.pdf", T.contract),
            ("Aneks nr 1 do umowy 361-2019.pdf", T.annex),
            ("wypowiedzenie b2b.pdf", T.termination_notice),
            ("Zamówienie 2026-09.pdf", T.order),
        ]
    )
    base = f"/api/contracts/{cid}"

    listed = await app_client.get(f"{base}/document-folders", headers=app_auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["folders"] == []
    assert body["orders_folder_name"] == "Zamówienia"
    assert body["current_contract_number"] == "518-2026"
    assert body["suggestions"] == [
        {
            "number": "361-2019",
            "folder_name": "Poprzednia umowa – nr 361-2019",
            "folder_id": None,
            "document_ids": sorted([old_umowa, old_aneks, termination]),
        }
    ]

    created = await app_client.post(
        f"{base}/document-folders",
        json={
            "name": "  Poprzednia umowa – nr 361-2019 ",
            "document_ids": [old_umowa, old_aneks, termination],
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    folder = created.json()["folder"]
    assert folder["name"] == "Poprzednia umowa – nr 361-2019"
    assert created.json()["moved"] == 3
    placed = await _folder_ids([new_umowa, old_umowa, old_aneks, termination])
    assert placed == {
        new_umowa: None,
        old_umowa: folder["id"],
        old_aneks: folder["id"],
        termination: folder["id"],
    }

    # Lista dokumentów niesie folder; podpowiedź znika, bo pliki są już w folderze.
    docs = await app_client.get(f"{base}/documents", headers=app_auth_headers)
    assert {d["id"]: d["folder_id"] for d in docs.json()}[old_umowa] == folder["id"]
    again = await app_client.get(f"{base}/document-folders", headers=app_auth_headers)
    assert again.json()["suggestions"] == []

    # Ta sama nazwa (bez względu na wielkość liter) i nazwa „Zamówień” = 409.
    for name in ("poprzednia umowa – NR 361-2019", "zamówienia"):
        dup = await app_client.post(
            f"{base}/document-folders", json={"name": name}, headers=app_auth_headers
        )
        assert dup.status_code == 409, name

    # Zamówienia nie przenosi się ręcznie.
    blocked = await app_client.post(
        f"{base}/documents/move",
        json={"document_ids": [order], "folder_id": folder["id"]},
        headers=app_auth_headers,
    )
    assert blocked.status_code == 422

    back = await app_client.post(
        f"{base}/documents/move",
        json={"document_ids": [old_aneks], "folder_id": None},
        headers=app_auth_headers,
    )
    assert back.status_code == 200 and back.json() == {"moved": 1}
    assert (await _folder_ids([old_aneks]))[old_aneks] is None

    renamed = await app_client.patch(
        f"{base}/document-folders/{folder['id']}",
        json={"name": "Umowa 2019"},
        headers=app_auth_headers,
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Umowa 2019"

    orders = await app_client.patch(
        f"{base}/document-folders/orders",
        json={"name": "Zamówienia BNP"},
        headers=app_auth_headers,
    )
    assert orders.status_code == 200
    assert orders.json() == {"orders_folder_name": "Zamówienia BNP"}
    listed = await app_client.get(f"{base}/document-folders", headers=app_auth_headers)
    assert listed.json()["orders_folder_name"] == "Zamówienia BNP"
    assert [f["name"] for f in listed.json()["folders"]] == ["Umowa 2019"]

    # Usunięcie folderu oddaje pliki na listę główną — nie kasuje ich.
    deleted = await app_client.delete(
        f"{base}/document-folders/{folder['id']}", headers=app_auth_headers
    )
    assert deleted.status_code == 200 and deleted.json() == {"released": 2}
    placed = await _folder_ids([old_umowa, termination])
    assert placed == {old_umowa: None, termination: None}

    activities = await app_client.get(f"{base}/activities", headers=app_auth_headers)
    assert activities.status_code == 200
    assert {
        "document_folder_created",
        "documents_moved",
        "document_folder_renamed",
        "document_folder_deleted",
    } <= {a.get("action") for a in activities.json()}


async def test_folder_of_another_contract_is_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid_a, (doc_a,) = await _seed([("Umowa nr 1-2020.pdf", T.contract)])
    cid_b, _ = await _seed([("Umowa nr 2-2020.pdf", T.contract)])
    created = await app_client.post(
        f"/api/contracts/{cid_b}/document-folders",
        json={"name": "Cudzy"},
        headers=app_auth_headers,
    )
    foreign = created.json()["folder"]["id"]

    moved = await app_client.post(
        f"/api/contracts/{cid_a}/documents/move",
        json={"document_ids": [doc_a], "folder_id": foreign},
        headers=app_auth_headers,
    )
    assert moved.status_code == 404
    deleted = await app_client.delete(
        f"/api/contracts/{cid_a}/document-folders/{foreign}", headers=app_auth_headers
    )
    assert deleted.status_code == 404
    # Plik innego kontraktu też nie wchodzi do folderu.
    stolen = await app_client.post(
        f"/api/contracts/{cid_b}/documents/move",
        json={"document_ids": [doc_a], "folder_id": foreign},
        headers=app_auth_headers,
    )
    assert stolen.status_code == 404


async def test_upload_into_folder_and_order_ignores_folder(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid, _ = await _seed([])
    folder = (
        await app_client.post(
            f"/api/contracts/{cid}/document-folders",
            json={"name": "Archiwum"},
            headers=app_auth_headers,
        )
    ).json()["folder"]

    up = await app_client.post(
        f"/api/contracts/{cid}/documents",
        files={"file": ("aneks.pdf", b"%PDF-1.4 a", "application/pdf")},
        data={"doc_type": "annex", "folder_id": str(folder["id"])},
        headers=app_auth_headers,
    )
    assert up.status_code == 201, up.text
    assert up.json()["folder_id"] == folder["id"]

    order = await app_client.post(
        f"/api/contracts/{cid}/documents",
        files={"file": ("zam.pdf", b"%PDF-1.4 z", "application/pdf")},
        data={"doc_type": "order", "folder_id": str(folder["id"])},
        headers=app_auth_headers,
    )
    assert order.status_code == 201
    assert order.json()["folder_id"] is None

    wrong = await app_client.post(
        f"/api/contracts/{cid}/documents",
        files={"file": ("x.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"doc_type": "other", "folder_id": "99999999"},
        headers=app_auth_headers,
    )
    assert wrong.status_code == 404


async def test_expiring_document_in_a_folder_raises_no_compliance_alert():
    from app.tasks.contract_alerts import _compliance_documents_expiring

    cid, (loose, archived) = await _seed(
        [("Polisa OC 2026.pdf", T.oc_policy), ("Polisa OC 2019.pdf", T.oc_policy)]
    )
    soon = business_today() + timedelta(days=3)
    async with AsyncSessionLocal() as db:
        folder = ContractDocumentFolder(contract_id=cid, name="Poprzednia umowa")
        db.add(folder)
        await db.flush()
        for doc in (
            await db.execute(
                select(ContractDocument).where(
                    ContractDocument.id.in_([loose, archived])
                )
            )
        ).scalars():
            doc.expiry_date = soon
            if doc.id == archived:
                doc.folder_id = folder.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        ids = {d.id for d in await _compliance_documents_expiring(db)}
    assert loose in ids
    assert archived not in ids


async def test_contract_merge_joins_same_name_folders():
    from app.services.contract_merge import _resolve_child_duplicates

    survivor, (kept_doc,) = await _seed([("Umowa nr 1-2020.pdf", T.contract)])
    loser, (moved_doc, own_doc) = await _seed(
        [("Aneks 1-2020.pdf", T.annex), ("Umowa nr 2-2019.pdf", T.contract)]
    )
    async with AsyncSessionLocal() as db:
        keep = ContractDocumentFolder(contract_id=survivor, name="Poprzednia umowa")
        dup = ContractDocumentFolder(contract_id=loser, name="POPRZEDNIA UMOWA")
        own = ContractDocumentFolder(contract_id=loser, name="Archiwum")
        orders = ContractDocumentFolder(contract_id=loser, name="Zam. X", kind="orders")
        db.add_all([keep, dup, own, orders])
        await db.flush()
        docs = {
            d.id: d
            for d in (
                await db.execute(
                    select(ContractDocument).where(
                        ContractDocument.id.in_([kept_doc, moved_doc, own_doc])
                    )
                )
            ).scalars()
        }
        docs[kept_doc].folder_id = keep.id
        docs[moved_doc].folder_id = dup.id
        docs[own_doc].folder_id = own.id
        await db.flush()

        out = await _resolve_child_duplicates(
            db,
            [{"table_name": "contract_document_folders", "column_name": "contract_id"}],
            [loser],
            survivor,
        )
        assert out["contract_document_folders_merged"] == 1
        left = {
            f.id
            for f in (
                await db.execute(
                    select(ContractDocumentFolder).where(
                        ContractDocumentFolder.contract_id.in_([survivor, loser])
                    )
                )
            ).scalars()
        }
        assert left == {keep.id, own.id}
        placed = dict(
            (
                await db.execute(
                    select(ContractDocument.id, ContractDocument.folder_id).where(
                        ContractDocument.id.in_([kept_doc, moved_doc, own_doc])
                    )
                )
            ).all()
        )
        assert placed == {kept_doc: keep.id, moved_doc: keep.id, own_doc: own.id}
        await db.rollback()


async def test_contract_merge_renames_loser_folder_named_like_survivor_orders():
    """Folder przegranego o nazwie „Zamówień” zachowanego nie łamie unikalności
    nazwy przy przepięciu (audyt 22.10, F71/F110) — dostaje dopisek „(2)”."""
    from sqlalchemy import text

    from app.services.contract_merge import _resolve_child_duplicates

    survivor, _ = await _seed([("Umowa nr 1-2020.pdf", T.contract)])
    loser, (renamed_doc,) = await _seed([("Aneks 1-2020.pdf", T.annex)])
    other_survivor, _ = await _seed([("Umowa nr 3-2020.pdf", T.contract)])
    async with AsyncSessionLocal() as db:
        orders = ContractDocumentFolder(
            contract_id=survivor, name="Archiwum", kind="orders"
        )
        clash = ContractDocumentFolder(contract_id=loser, name="ARCHIWUM")
        taken = ContractDocumentFolder(contract_id=survivor, name="Archiwum (2)")
        db.add_all([orders, clash, taken])
        await db.flush()
        doc = await db.get(ContractDocument, renamed_doc)
        doc.folder_id = clash.id
        await db.flush()

        await _resolve_child_duplicates(
            db,
            [{"table_name": "contract_document_folders", "column_name": "contract_id"}],
            [loser],
            survivor,
        )
        await db.execute(
            text(
                "UPDATE contract_document_folders SET contract_id = :survivor "
                "WHERE contract_id = ANY(:losers)"
            ),
            {"survivor": survivor, "losers": [loser]},
        )
        await db.refresh(clash)
        assert clash.contract_id == survivor
        assert clash.name == "ARCHIWUM (3)"
        await db.refresh(doc)
        assert doc.folder_id == clash.id
        await db.rollback()

    # Odwrotnie: zachowany ma nazwę domyślną, przegrany folder „Zamówienia”.
    async with AsyncSessionLocal() as db:
        named = ContractDocumentFolder(contract_id=loser, name="Zamówienia")
        db.add(named)
        await db.flush()
        await _resolve_child_duplicates(
            db,
            [{"table_name": "contract_document_folders", "column_name": "contract_id"}],
            [loser],
            other_survivor,
        )
        await db.refresh(named)
        assert named.name == "Zamówienia (2)"
        await db.rollback()
