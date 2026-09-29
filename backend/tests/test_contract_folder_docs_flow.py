"""Ticket 9: pierwsze pobranie z SharePointa i synchronizacja — prawdziwa baza,
SharePoint podmieniony na folder w pamięci.

Baza testowa jest wspólna i nieczyszczona: każdy test ma własne, losowe
nazwiska i asercje wyłącznie na własnych kontraktach.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_doc_sharepoint import (
    ContractDocSpItem,
    ContractDocSpRun,
    ContractDocSpRunItem,
)
from app.models.contract_document import ContractDocument
from app.services.contract_folder_docs import service, sync
from app.services.contract_folder_docs.matching import Folder
from app.services.m365 import sharepoint_docs as sp

DRIVE = "drive-test"
ROOT = "root-test"


class FakeSharePoint:
    """Folder „Umowy pracowników” w pamięci: podfoldery osób i ich pliki."""

    def __init__(self) -> None:
        self.folders: dict[str, sp.DriveItem] = {}
        self.files: list[sp.PersonFile] = []
        self.content: dict[str, bytes] = {}
        self.uploads: list[tuple[str, str]] = []

    def add_folder(self, name: str) -> sp.DriveItem:
        item = sp.DriveItem(f"f-{uuid.uuid4().hex[:8]}", name, True, None, None, DRIVE)
        self.folders[name] = item
        return item

    def add_file(self, folder: str, path: str, content: bytes) -> str:
        parent = self.folders.get(folder) or self.add_folder(folder)
        item_id = f"i-{uuid.uuid4().hex[:10]}"
        item = sp.DriveItem(
            item_id, path.rsplit("/", 1)[-1], False, len(content), "c1", DRIVE
        )
        self.files.append(sp.PersonFile(parent, item, path))
        self.content[item_id] = content
        return item_id

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = self

        @asynccontextmanager
        async def graph_client():
            yield object()

        async def resolve_folder(
            client: Any, url: str, *, folder_name: str = ""
        ) -> Any:
            return sp.ResolvedFolder(DRIVE, ROOT, "Umowy pracowników")

        async def list_person_files(client: Any, drive_id: str, root: str, **_: Any):
            return sp.FolderListing(
                person_folders=list(fake.folders.values()),
                files=list(fake.files),
                loose_files=[],
            )

        async def download(client: Any, drive_id: str, item_id: str) -> bytes:
            return fake.content[item_id]

        async def ensure_person_folder(
            client: Any, drive_id: str, root: str, name: str
        ):
            return fake.folders.get(name) or fake.add_folder(name)

        async def upload_file(
            client, drive_id, folder_id, filename, content, content_type
        ):
            fake.uploads.append((folder_id, filename))
            return sp.DriveItem(
                f"up-{uuid.uuid4().hex[:8]}", filename, False, len(content), "c1", DRIVE
            )

        monkeypatch.setattr(sp, "graph_client", graph_client)
        monkeypatch.setattr(sp, "resolve_folder", resolve_folder)
        monkeypatch.setattr(sp, "list_person_files", list_person_files)
        monkeypatch.setattr(sp, "download", download)
        monkeypatch.setattr(sp, "ensure_person_folder", ensure_person_folder)
        monkeypatch.setattr(sp, "upload_file", upload_file)


def _tag() -> str:
    return "Tst" + uuid.uuid4().hex[:8]


async def _seed_person(first: str, last: str, contracts: int = 1) -> list[int]:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name=first, lastname=last)
        client = Client(name=f"Klient {last}")
        db.add_all([candidate, client])
        await db.flush()
        ids = []
        for _ in range(contracts):
            contract = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                contract_type=ContractType.b2b,
                status=ContractStatus.active,
                start_date=date(2026, 1, 1),
            )
            db.add(contract)
            await db.flush()
            ids.append(contract.id)
        await db.commit()
        return ids


async def _preview() -> int:
    async with AsyncSessionLocal() as db:
        run = ContractDocSpRun(
            mode="listing", source_url="https://x.sharepoint.com/s/y"
        )
        db.add(run)
        await db.commit()
        run_id = run.id
    await service.build_preview(run_id)
    return run_id


async def _apply(run_id: int, deselected: list[int] | None = None) -> None:
    async with AsyncSessionLocal() as db:
        await service.start_apply(
            db, run_id=run_id, deselected_item_ids=deselected or [], user_id=None
        )
        await db.commit()
    await service.apply_run(run_id)


async def _docs(contract_id: int) -> list[ContractDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(ContractDocument)
                    .where(ContractDocument.contract_id == contract_id)
                    .order_by(ContractDocument.id)
                )
            ).scalars()
        )


async def _items(run_id: int, contract_id: int) -> list[ContractDocSpRunItem]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(ContractDocSpRunItem).where(
                        ContractDocSpRunItem.run_id == run_id,
                        ContractDocSpRunItem.contract_id == contract_id,
                    )
                )
            ).scalars()
        )


async def test_first_import_attaches_documents_to_every_contract_of_the_person(
    monkeypatch,
):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    first_id, second_id = await _seed_person("Jan", tag, contracts=2)
    folder = f"{tag} Jan"
    fake.add_file(folder, "1401-2026 B2B 04.05.2026.pdf", b"umowa " + tag.encode())
    fake.add_file(folder, "Aneks 1.pdf", b"aneks " + tag.encode())
    fake.add_file(folder, "umowa.docx", b"word")

    run_id = await _preview()
    async with AsyncSessionLocal() as db:
        run = await db.get(ContractDocSpRun, run_id)
    assert run.mode == "preview", run.error
    assert await _docs(first_id) == []  # podgląd niczego nie zapisuje

    await _apply(run_id)
    for contract_id in (first_id, second_id):
        docs = await _docs(contract_id)
        assert sorted((d.filename, d.doc_type.value) for d in docs) == [
            ("1401-2026 B2B 04.05.2026.pdf", "contract"),
            ("Aneks 1.pdf", "annex"),
        ]
        assert all(d.source == "sharepoint_import" and d.content_sha256 for d in docs)
        assert all(d.import_run_id == run_id for d in docs)
    async with AsyncSessionLocal() as db:
        run = await db.get(ContractDocSpRun, run_id)
    assert run.mode == "applied"


async def test_second_import_skips_documents_the_contract_already_has(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    (contract_id,) = await _seed_person("Ewa", tag)
    fake.add_file(f"{tag} Ewa", "NDA.pdf", b"nda " + tag.encode())

    await _apply(await _preview())
    second = await _preview()
    await _apply(second)

    assert len(await _docs(contract_id)) == 1
    statuses = [
        i.status for i in await _items(second, contract_id) if i.kind == "assignment"
    ]
    assert statuses == ["skipped_existing"]


async def test_existing_manual_upload_without_hash_counts_as_already_there(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    (contract_id,) = await _seed_person("Ola", tag)
    content = b"polisa " + tag.encode()
    # Dokument sprzed 0402: bez skrótu, ta sama treść na dysku.
    import io

    from app.services import storage_service

    path, size = storage_service.save_contract_document(
        contract_id, "polisa.pdf", io.BytesIO(content)
    )
    async with AsyncSessionLocal() as db:
        db.add(
            ContractDocument(
                contract_id=contract_id,
                filename="polisa.pdf",
                file_path=path,
                size_bytes=size,
            )
        )
        await db.commit()
    fake.add_file(f"{tag} Ola", "Polisa OC.pdf", content)

    await _apply(await _preview())
    docs = await _docs(contract_id)
    assert len(docs) == 1 and docs[0].content_sha256
    # Związany z plikiem SharePointa — synchronizacja nie wyśle go z powrotem.
    assert docs[0].sharepoint_item_id and docs[0].sharepoint_push_status == "done"


async def test_same_file_name_in_two_subfolders_keeps_both_files(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    (contract_id,) = await _seed_person("Ada", tag)
    fake.add_file(f"{tag} Ada", "2023/umowa.pdf", b"stara " + tag.encode())
    fake.add_file(f"{tag} Ada", "2024/umowa.pdf", b"nowa " + tag.encode())

    await _apply(await _preview())
    docs = await _docs(contract_id)
    assert len(docs) == 2
    assert len({d.file_path for d in docs}) == 2
    from app.services import storage_service

    contents = {
        storage_service.get_contract_document_path(d.file_path).read_bytes()
        for d in docs
    }
    assert contents == {b"stara " + tag.encode(), b"nowa " + tag.encode()}


async def test_deselected_uncertain_assignment_is_not_imported(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    (contract_id,) = await _seed_person("Lukasz", tag)
    fake.add_file(f"{tag} Łukasz", "NDA.pdf", b"x" + tag.encode())

    run_id = await _preview()
    items = [i for i in await _items(run_id, contract_id) if i.kind == "assignment"]
    assert [i.match_kind for i in items] == ["uncertain"]
    assert items[0].reasons == ["diacritics"]
    await _apply(run_id, deselected=[items[0].id])
    assert await _docs(contract_id) == []


async def test_rollback_removes_only_documents_of_the_run(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    (contract_id,) = await _seed_person("Iza", tag)
    fake.add_file(f"{tag} Iza", "Wypowiedzenie.pdf", b"w" + tag.encode())
    run_id = await _preview()
    await _apply(run_id)
    assert len(await _docs(contract_id)) == 1

    async with AsyncSessionLocal() as db:
        result = await service.rollback_run(db, run_id=run_id, user_id=None)
        await db.commit()
        service.delete_files_after_commit(db)
    assert result["removed"] >= 1
    assert await _docs(contract_id) == []


async def test_sync_pulls_new_files_and_pushes_nexus_uploads_without_echo(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    (contract_id,) = await _seed_person("Kuba", tag)
    folder = fake.add_folder(f"{tag} Kuba")
    await _apply(await _preview())

    # Nowy plik w SharePoincie → dokument w NEXUSIE.
    new_item = fake.add_file(
        folder.name, "Zaświadczenie ZUS.pdf", b"zus" + tag.encode()
    )
    listing = await sp.list_person_files(None, DRIVE, ROOT)
    stats = sync.SyncStats()
    async with AsyncSessionLocal() as db:
        await sync._pull(db, None, DRIVE, listing, stats)
    docs = await _docs(contract_id)
    assert [(d.doc_type.value, d.sharepoint_item_id) for d in docs] == [
        ("zus_certificate", new_item)
    ]

    # Drugi bieg nie pobiera go ponownie.
    async with AsyncSessionLocal() as db:
        await sync._pull(db, None, DRIVE, listing, sync.SyncStats())
    assert len(await _docs(contract_id)) == 1

    # Dokument wgrany w NEXUSIE → folder osoby w SharePoincie.
    import io

    from app.services import storage_service

    path, size = storage_service.save_contract_document(
        contract_id, "aneks.pdf", io.BytesIO(b"nexus" + tag.encode())
    )
    async with AsyncSessionLocal() as db:
        doc = ContractDocument(
            contract_id=contract_id,
            filename="aneks.pdf",
            file_path=path,
            size_bytes=size,
            source="upload",
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id
    async with AsyncSessionLocal() as db:
        doc = await db.get(ContractDocument, doc_id)
        push_stats = sync.SyncStats()
        await sync._push_one(
            db,
            None,
            DRIVE,
            ROOT,
            doc,
            "Kuba",
            tag,
            [Folder.of(f.name, f.id) for f in fake.folders.values()],
            {},
            push_stats,
        )
        await db.commit()
    assert fake.uploads == [(folder.id, "aneks.pdf")]
    async with AsyncSessionLocal() as db:
        doc = await db.get(ContractDocument, doc_id)
        assert doc.sharepoint_push_status == "done" and doc.sharepoint_item_id
        state = await db.get(ContractDocSpItem, doc.sharepoint_item_id)
        assert state is not None and state.status == "pushed"


async def test_push_skips_a_folder_shared_by_two_people_of_the_same_name(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    folder = fake.add_folder("Wspolny Jan")
    doc = ContractDocument(contract_id=0, filename="x.pdf", file_path="nie/ma.pdf")
    stats = sync.SyncStats()
    async with AsyncSessionLocal() as db:
        await sync._push_one(
            db,
            None,
            DRIVE,
            ROOT,
            doc,
            "Jan",
            "Wspolny",
            [Folder.of(folder.name, folder.id)],
            {},
            stats,
            candidate_id=1,
            candidates_by_folder={folder.name: {1, 2}},
        )
    assert doc.sharepoint_push_status == "skipped"
    assert fake.uploads == []


async def test_push_does_not_create_a_shared_folder_for_two_people(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    (contract_id,) = await _seed_person("Jan", tag)
    await _seed_person("Jan", tag)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        doc = ContractDocument(
            contract_id=contract_id, filename="x.pdf", file_path="nie/ma.pdf"
        )
        stats = sync.SyncStats()
        await sync._push_one(
            db,
            None,
            DRIVE,
            ROOT,
            doc,
            "Jan",
            tag,
            [],
            {},
            stats,
            candidate_id=contract.candidate_id,
        )
    assert doc.sharepoint_push_status == "skipped"
    assert doc.sharepoint_push_error == sync.PUSH_SKIP_SAME_NAME
    assert fake.folders == {}
    assert fake.uploads == []


@pytest.mark.parametrize("same_content", [True, False])
async def test_push_compares_content_before_linking_same_name_and_size(
    monkeypatch, same_content
):
    import io

    from app.services import storage_service

    fake = FakeSharePoint()
    fake.install(monkeypatch)
    tag = _tag()
    (contract_id,) = await _seed_person("Jan", tag)
    folder = fake.add_folder(f"{tag} Jan")
    local_content = b"local document"
    remote_content = local_content if same_content else b"other document"
    assert len(local_content) == len(remote_content)
    item_id = fake.add_file(folder.name, "umowa.pdf", remote_content)
    path, size = storage_service.save_contract_document(
        contract_id, "umowa.pdf", io.BytesIO(local_content)
    )
    async with AsyncSessionLocal() as db:
        doc = ContractDocument(
            contract_id=contract_id,
            filename="umowa.pdf",
            file_path=path,
            size_bytes=size,
            source="upload",
        )
        db.add(doc)
        await db.flush()
        stats = sync.SyncStats()
        await sync._push_one(
            db,
            None,
            DRIVE,
            ROOT,
            doc,
            "Jan",
            tag,
            [Folder.of(folder.name, folder.id)],
            {folder.id: fake.files},
            stats,
        )
        await db.commit()
        assert doc.sharepoint_push_status == "done"
        assert (doc.sharepoint_item_id == item_id) is same_content
    assert len(fake.uploads) == (0 if same_content else 1)
    assert fake.content[item_id] == remote_content


async def test_filip_jablonski_is_never_pushed(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    async with AsyncSessionLocal() as db:
        doc = ContractDocument(contract_id=0, filename="x.pdf", file_path="nie/ma.pdf")
        stats = sync.SyncStats()
        await sync._push_one(
            db, None, DRIVE, ROOT, doc, "Filip", "Jabłoński", [], {}, stats
        )
    assert doc.sharepoint_push_status == "skipped"
    assert "Filip" in (doc.sharepoint_push_error or "")
    assert fake.uploads == []


async def test_preview_endpoint_refuses_without_the_azure_registration(
    app_client, app_auth_headers, monkeypatch
):
    monkeypatch.setattr(sp, "credentials_configured", lambda: False)
    resp = await app_client.post(
        "/api/contract-docs-sharepoint/preview",
        headers=app_auth_headers,
        json={"url": "https://b2bnetsa.sharepoint.com/:f:/s/Share_B2B/abc"},
    )
    assert resp.status_code == 409
    assert "Azure" in resp.json()["detail"]
    status = await app_client.get(
        "/api/contract-docs-sharepoint/status", headers=app_auth_headers
    )
    assert status.status_code == 200
    assert status.json()["configured"] is False
