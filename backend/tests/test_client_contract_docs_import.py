"""Import umów i aneksów z paczki: próba na sucho, blokady, idempotencja, cofnięcie."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.services import client_contract_docs_import as imp
from app.services import storage_service


@pytest.fixture
def storage(monkeypatch, tmp_path):
    saved = tmp_path / "storage"
    saved.mkdir()
    counter = iter(range(1000))

    def _save(*, upload_filename, source, **_kwargs):
        data = source.read()
        target = saved / f"{next(counter)}-{upload_filename}"
        target.write_bytes(data)
        return str(target), len(data)

    deleted: list[str] = []
    for name in ("save_client_framework_contract", "save_client_contract_amendment"):
        monkeypatch.setattr(storage_service, name, _save)
    for name in (
        "delete_client_framework_contract",
        "delete_client_contract_amendment",
    ):
        monkeypatch.setattr(storage_service, name, deleted.append)
    return deleted


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "paczka"
    folder.mkdir()
    (folder / "umowa.pdf").write_bytes(b"%PDF-1.7 umowa")
    (folder / "aneks.pdf").write_bytes(b"%PDF-1.7 aneks")
    return folder


async def _seed(*, with_file: bool = False):
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Import umów {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        contract = ClientFrameworkContract(
            client_id=client.id,
            name="Umowa z importu dat",
            status=FrameworkContractStatus.active,
            effective_date=date(2023, 6, 21),
            filename="stara.pdf" if with_file else None,
            file_path=f"x/{uuid.uuid4().hex}.pdf" if with_file else None,
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id


async def _cleanup(client_id: int, sha: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientFrameworkContract.__table__.delete().where(
                ClientFrameworkContract.client_id == client_id
            )
        )
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.execute(
            AppSetting.__table__.delete().where(
                AppSetting.key == f"{imp.RECEIPT_KEY_PREFIX}{sha[:12]}"
            )
        )
        await db.commit()


def _manifest(client_id: int, fc_id: int):
    raw = json.dumps(
        {
            "documents": [
                {
                    "key": f"umowa-{fc_id}",
                    "kind": "contract",
                    "client_id": client_id,
                    "framework_contract_id": fc_id,
                    "source": "umowa.pdf",
                    "filename": "Umowa.pdf",
                    "name": "Umowa ramowa",
                },
                {
                    "key": f"aneks-{fc_id}",
                    "kind": "amendment",
                    "client_id": client_id,
                    "contract_key": f"umowa-{fc_id}",
                    "source": "aneks.pdf",
                    "filename": "Aneks nr 1.pdf",
                    "name": "Aneks nr 1",
                    "effective_date": "2024-05-01",
                },
            ]
        }
    ).encode()
    return imp.load_manifest(raw)


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(root, storage):
    client_id, fc_id = await _seed()
    manifest, sha = _manifest(client_id, fc_id)
    try:
        async with AsyncSessionLocal() as db:
            report = await imp.build_plan(db, manifest, sha, root)
            contract = await db.get(ClientFrameworkContract, fc_id)
            assert contract.file_path is None
        assert report.counts == {imp.ATTACH: 1, imp.CREATE_AMENDMENT: 1}
        assert report.applied is False
    finally:
        await _cleanup(client_id, sha)


@pytest.mark.asyncio
async def test_apply_attaches_is_idempotent_and_undo_restores(root, storage):
    client_id, fc_id = await _seed()
    manifest, sha = _manifest(client_id, fc_id)
    try:
        async with AsyncSessionLocal() as db:
            report = await imp.apply_import(db, manifest, sha, root)
        assert report.applied and report.counts[imp.ATTACH] == 1

        async with AsyncSessionLocal() as db:
            contract = await db.get(ClientFrameworkContract, fc_id)
            assert contract.filename == "Umowa.pdf"
            assert contract.effective_date == date(2023, 6, 21)
            amendments = list(
                await db.scalars(
                    select(ClientContractAmendment).where(
                        ClientContractAmendment.framework_contract_id == fc_id
                    )
                )
            )
            assert [a.name for a in amendments] == ["Aneks nr 1"]

        async with AsyncSessionLocal() as db:
            again = await imp.apply_import(db, manifest, sha, root)
        assert again.counts == {imp.ALREADY_DONE: 2}

        async with AsyncSessionLocal() as db:
            undone = await imp.undo_import(db, report.receipt_key)
        assert undone == {
            "amendments_deleted": 1,
            "contracts_deleted": 0,
            "files_detached": 1,
        }
        assert len(storage) == 2
        async with AsyncSessionLocal() as db:
            contract = await db.get(ClientFrameworkContract, fc_id)
            assert contract.file_path is None
            assert contract.effective_date == date(2023, 6, 21)
            assert await db.get(AppSetting, report.receipt_key) is None
    finally:
        await _cleanup(client_id, sha)


@pytest.mark.asyncio
async def test_existing_file_is_never_overwritten(root, storage):
    client_id, fc_id = await _seed(with_file=True)
    manifest, sha = _manifest(client_id, fc_id)
    try:
        async with AsyncSessionLocal() as db:
            before = (await db.get(ClientFrameworkContract, fc_id)).file_path
            report = await imp.apply_import(db, manifest, sha, root)
            assert report.rows[0].action == imp.HAS_OTHER_FILE
        async with AsyncSessionLocal() as db:
            assert (await db.get(ClientFrameworkContract, fc_id)).file_path == before
    finally:
        await _cleanup(client_id, sha)


@pytest.mark.asyncio
async def test_new_contract_is_created_once_and_undo_removes_it(root, storage):
    client_id, _fc_id = await _seed()
    key = f"nowa-{uuid.uuid4().hex}"
    raw = json.dumps(
        {
            "documents": [
                {
                    "key": key,
                    "kind": "contract",
                    "client_id": client_id,
                    "source": "umowa.pdf",
                    "filename": "Nowa.pdf",
                    "name": "Nowa umowa",
                    "effective_date": "2026-01-02",
                    "expiry_date": "2027-01-02",
                }
            ]
        }
    ).encode()
    manifest, sha = imp.load_manifest(raw)
    try:
        async with AsyncSessionLocal() as db:
            report = await imp.apply_import(db, manifest, sha, root)
        assert report.counts == {imp.CREATE_CONTRACT: 1}
        async with AsyncSessionLocal() as db:
            assert (await imp.build_plan(db, manifest, sha, root)).counts == {
                imp.ALREADY_DONE: 1
            }
            undone = await imp.undo_import(db, report.receipt_key)
        assert undone["contracts_deleted"] == 1
    finally:
        await _cleanup(client_id, sha)


@pytest.mark.asyncio
async def test_blocker_means_zero_writes(root, storage):
    client_id, fc_id = await _seed()
    other_client, other_fc = await _seed()
    manifest, sha = _manifest(client_id, fc_id)
    manifest.documents[1].source = "brak.pdf"
    try:
        async with AsyncSessionLocal() as db:
            report = await imp.apply_import(db, manifest, sha, root)
        assert report.applied is False
        assert report.blocked[0].reason == "brak pliku w paczce"
        async with AsyncSessionLocal() as db:
            assert (await db.get(ClientFrameworkContract, fc_id)).file_path is None

        foreign, foreign_sha = _manifest(client_id, other_fc)
        async with AsyncSessionLocal() as db:
            blocked = await imp.build_plan(db, foreign, foreign_sha, root)
        assert "nie należy" in blocked.rows[0].reason
    finally:
        await _cleanup(client_id, sha)
        await _cleanup(other_client, sha)


@pytest.mark.asyncio
async def test_other_client_name_blocks_the_document(root, storage):
    client_id, fc_id = await _seed()
    manifest, sha = _manifest(client_id, fc_id)
    manifest.documents[0].client_name = "Inny klient"
    try:
        async with AsyncSessionLocal() as db:
            report = await imp.build_plan(db, manifest, sha, root)
        assert report.rows[0].reason == "nazwa klienta inna niż w manifeście"
        assert report.rows[1].action == imp.BLOCKED
    finally:
        await _cleanup(client_id, sha)


def test_source_cannot_escape_the_package(root: Path):
    document = imp.ManifestDocument(
        key="k",
        kind="contract",
        client_id=1,
        source="../sekret.pdf",
        filename="a.pdf",
        name="a",
    )
    (root.parent / "sekret.pdf").write_bytes(b"x")
    assert imp._source_problem(root, document) == "plik poza katalogiem paczki"


@pytest.mark.parametrize(
    "document",
    [
        {
            "key": "a",
            "kind": "amendment",
            "client_id": 1,
            "source": "a",
            "filename": "a.pdf",
            "name": "a",
            "framework_contract_id": 1,
        },
        {
            "key": "a",
            "kind": "amendment",
            "client_id": 1,
            "source": "a",
            "filename": "a.pdf",
            "name": "a",
            "effective_date": "2026-01-01",
        },
    ],
)
def test_amendment_needs_a_date_and_a_contract(document):
    with pytest.raises(ValueError):
        imp.load_manifest(json.dumps({"documents": [document]}).encode())


def test_repeated_keys_are_refused():
    document = {
        "key": "a",
        "kind": "contract",
        "client_id": 1,
        "source": "a",
        "filename": "a.pdf",
        "name": "a",
    }
    with pytest.raises(ValueError):
        imp.load_manifest(json.dumps({"documents": [document, document]}).encode())
