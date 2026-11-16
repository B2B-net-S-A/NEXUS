"""Umowy ramowe na scalonych duplikatach klientów (decyzja Artura 16.11.2026).

Błąd: umowa z manifestu portfela leżała na duplikacie scalonym w klienta
z Traffita, a karta klienta docelowego i wyszukiwanie umów (Jarvis) czytają
po ``client_id`` celu — umowy nie było ani na liście, ani w wynikach.
Korekta przepina umowę, scalenie przenosi umowy od teraz samo, a inwariant
manifestu uznaje przeniesioną umowę. Klienci i treść zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_directory import (
    ClientImportRow,
    ClientImportRun,
    ClientImportRunStatus,
    PortfolioCategory,
)
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_framework_contract_chunk import ClientFrameworkContractChunk
from app.services.framework_contract_owner_repair import (
    REPAIR_MARKER,
    TICKET_DROPS,
    TICKET_MOVES,
    DuplicateDrop,
    Move,
    reassigned_manifest_contracts,
    run_framework_contract_owner_repair,
    summarize_for_log,
)

pytestmark = pytest.mark.asyncio


def _marker() -> str:
    return f"9999_fc_owner_{uuid.uuid4().hex[:8]}"


async def test_ticket_ids_match_the_decision_and_receipt_is_public_safe():
    from scripts.show_migration_receipts import is_receipt_key

    assert is_receipt_key(REPAIR_MARKER)
    assert {(m.framework_contract_id, m.to_client_id) for m in TICKET_MOVES} == {
        (30, 116),
        (10, 13),
        (16, 106),
        (6, 58),
        (2, 39),
        (9, 103),
        (33, 141),
    }
    assert TICKET_DROPS == (DuplicateDrop(41, 39, 2),)
    assert (30, 38342, 116) in reassigned_manifest_contracts()


async def _client(suffix: str, label: str, **kwargs) -> Client:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"FC owner {label} {suffix}", **kwargs)
        db.add(client)
        await db.commit()
        return client


async def _seed(
    *, merged: bool = True, source_system: str = "client_excel"
) -> tuple[int, int, int, str]:
    """Cel, duplikat (scalony w cel) i umowa z treścią na duplikacie."""
    suffix = uuid.uuid4().hex[:8]
    target = await _client(suffix, "target")
    async with AsyncSessionLocal() as db:
        duplicate = Client(
            name=f"FC owner duplicate {suffix}",
            merged_into_client_id=target.id if merged else None,
            archived_at=datetime.now(timezone.utc) if merged else None,
        )
        db.add(duplicate)
        await db.flush()
        path = f"client_framework_contracts/{duplicate.id}/{suffix}.pdf"
        fc = ClientFrameworkContract(
            client_id=duplicate.id,
            name=f"MSA {suffix}",
            status=FrameworkContractStatus.active,
            effective_date=date(2023, 6, 21),
            source_system=source_system,
            source_key=f"active:{suffix}",
            filename=f"Umowa {suffix}.pdf",
            file_path=path,
            size_bytes=1234,
            text_status="text_only",
            text_file_path=path,
        )
        db.add(fc)
        await db.flush()
        db.add(
            ClientFrameworkContractChunk(
                framework_contract_id=fc.id,
                chunk_index=0,
                text=f"Raport miesięczny kwalifikacyjny{suffix} do 5. dnia miesiąca.",
            )
        )
        db.add(
            ClientContractAmendment(
                framework_contract_id=fc.id,
                name=f"Aneks {suffix}",
                effective_date=date(2024, 6, 26),
            )
        )
        await db.commit()
        return target.id, duplicate.id, fc.id, suffix


async def _cleanup(*client_ids: int, markers: tuple[str, ...] = ()) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key.in_(markers)))
        await db.execute(
            delete(ClientFrameworkContract).where(
                ClientFrameworkContract.client_id.in_(client_ids)
            )
        )
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "client", Activity.entity_id.in_(client_ids)
            )
        )
        for cid in client_ids:
            client = await db.get(Client, cid)
            if client is not None and client.merged_into_client_id is not None:
                client.merged_into_client_id = None
        await db.flush()
        for cid in client_ids:
            client = await db.get(Client, cid)
            if client is not None:
                await db.delete(client)
        await db.commit()


async def test_contract_on_merged_duplicate_reaches_target_card_and_search(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    monkeypatch.setattr(settings, "FRAMEWORK_CONTRACT_EMBEDDINGS_ENABLED", False)
    target_id, duplicate_id, fc_id, suffix = await _seed()
    marker = _marker()
    try:
        listed = await app_client.get(
            f"/api/clients/{target_id}/framework-contracts", headers=app_auth_headers
        )
        assert listed.status_code == 200, listed.text
        assert fc_id not in {row["id"] for row in listed.json()["items"]}  # błąd z 15.11

        async with AsyncSessionLocal() as db:
            summary = await run_framework_contract_owner_repair(
                db,
                moves=(Move(fc_id, duplicate_id, target_id, f"active:{suffix}"),),
                drops=(),
                marker=marker,
            )
            await db.commit()
        assert summary is not None
        assert summary["moved_fc_ids"] == [fc_id]
        assert summary["moves"] == [
            {"fc_id": fc_id, "from": duplicate_id, "to": target_id}
        ]
        assert f"moved [{fc_id}]" in summarize_for_log(summary)

        listed = await app_client.get(
            f"/api/clients/{target_id}/framework-contracts", headers=app_auth_headers
        )
        assert fc_id in {row["id"] for row in listed.json()["items"]}
        found = await app_client.get(
            f"/api/clients/{target_id}/framework-contracts/search",
            params={"q": f"kwalifikacyjny{suffix}"},
            headers=app_auth_headers,
        )
        assert found.status_code == 200, found.text
        passages = found.json()["passages"]
        assert [p["framework_contract_id"] for p in passages] == [fc_id]

        async with AsyncSessionLocal() as db:
            amendment_owner = await db.scalar(
                select(ClientContractAmendment.framework_contract_id).where(
                    ClientContractAmendment.name == f"Aneks {suffix}"
                )
            )
            assert amendment_owner == fc_id  # aneks idzie za umową
            again = await run_framework_contract_owner_repair(
                db, moves=(), drops=(), marker=marker
            )
            assert again is None
    finally:
        await _cleanup(duplicate_id, target_id, markers=(marker,))


async def test_gates_skip_with_reason_and_write_nothing():
    target_id, duplicate_id, fc_id, suffix = await _seed()
    other = await _client(suffix, "other")
    closed = await _client(suffix, "closed", archived_at=datetime.now(timezone.utc))
    marker = _marker()
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_framework_contract_owner_repair(
                db,
                moves=(
                    Move(fc_id, other.id, target_id, f"active:{suffix}"),
                    Move(fc_id, duplicate_id, target_id, "active:inna-umowa"),
                    Move(fc_id, duplicate_id, closed.id, f"active:{suffix}"),
                ),
                drops=(),
                marker=marker,
            )
            await db.commit()
        assert summary is not None
        assert summary["moved_fc_ids"] == []
        assert [s["reason"] for s in summary["skipped"]] == [
            "other_client",
            "identity_mismatch",
            "target_not_open",
        ]
        async with AsyncSessionLocal() as db:
            fc = await db.get(ClientFrameworkContract, fc_id)
            assert fc.client_id == duplicate_id
    finally:
        await _cleanup(duplicate_id, target_id, other.id, closed.id, markers=(marker,))


async def test_duplicate_upload_is_dropped_only_when_same_document_and_unused():
    target_id, duplicate_id, fc_id, suffix = await _seed()
    marker = _marker()
    async with AsyncSessionLocal() as db:
        kept = await db.get(ClientFrameworkContract, fc_id)
        copy_path = f"client_framework_contracts/{target_id}/{suffix}-copy.pdf"
        copy = ClientFrameworkContract(
            client_id=target_id,
            name=f"Kopia {suffix}",
            status=FrameworkContractStatus.active,
            effective_date=kept.effective_date,
            filename=kept.filename,
            file_path=copy_path,
            size_bytes=kept.size_bytes,
        )
        other = ClientFrameworkContract(
            client_id=target_id,
            name=f"Inna {suffix}",
            status=FrameworkContractStatus.active,
            effective_date=kept.effective_date,
            filename="Inna umowa.pdf",
            file_path=f"client_framework_contracts/{target_id}/{suffix}-inna.pdf",
            size_bytes=999,
        )
        db.add_all([copy, other])
        await db.commit()
        copy_id, other_id = copy.id, other.id
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_framework_contract_owner_repair(
                db,
                moves=(Move(fc_id, duplicate_id, target_id, f"active:{suffix}"),),
                drops=(
                    DuplicateDrop(copy_id, target_id, fc_id),
                    DuplicateDrop(other_id, target_id, fc_id),
                ),
                marker=marker,
            )
            await db.commit()
        assert summary["dropped_fc_ids"] == [copy_id]
        assert summary["dropped_file_paths"] == [copy_path]
        assert {"fc_id": other_id, "reason": "not_the_same_document"} in summary[
            "skipped"
        ]
        async with AsyncSessionLocal() as db:
            assert await db.get(ClientFrameworkContract, copy_id) is None
            assert await db.get(ClientFrameworkContract, other_id) is not None
            receipt = await db.get(AppSetting, marker)
            assert "dropped_file_paths" not in receipt.value  # paragon = same ID
    finally:
        await _cleanup(duplicate_id, target_id, markers=(marker,))


async def test_drop_waits_when_kept_contract_did_not_move():
    target_id, duplicate_id, fc_id, suffix = await _seed()
    marker = _marker()
    async with AsyncSessionLocal() as db:
        kept = await db.get(ClientFrameworkContract, fc_id)
        copy = ClientFrameworkContract(
            client_id=target_id,
            name=f"Kopia {suffix}",
            status=FrameworkContractStatus.active,
            effective_date=kept.effective_date,
            filename=kept.filename,
            file_path=f"client_framework_contracts/{target_id}/{suffix}-copy.pdf",
            size_bytes=kept.size_bytes,
        )
        db.add(copy)
        await db.commit()
        copy_id = copy.id
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_framework_contract_owner_repair(
                db,
                moves=(),
                drops=(DuplicateDrop(copy_id, target_id, fc_id),),
                marker=marker,
            )
            await db.commit()
        assert summary["dropped_fc_ids"] == []
        assert summary["skipped"] == [
            {"fc_id": copy_id, "reason": "kept_not_on_client"}
        ]
    finally:
        await _cleanup(duplicate_id, target_id, markers=(marker,))


async def test_merge_moves_framework_contracts_to_target(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    target_id, duplicate_id, fc_id, _suffix = await _seed(merged=False)
    try:
        resp = await app_client.post(
            f"/api/clients/{duplicate_id}/merge-into/{target_id}",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        async with AsyncSessionLocal() as db:
            fc = await db.get(ClientFrameworkContract, fc_id)
            assert fc.client_id == target_id
    finally:
        await _cleanup(duplicate_id, target_id)


async def test_manifest_invariant_accepts_contract_moved_to_merge_target():
    from app.services.client_portfolio_import import _framework_contract_owner_matches

    target_id, duplicate_id, fc_id, suffix = await _seed()
    stranger = await _client(suffix, "stranger")
    async with AsyncSessionLocal() as db:
        run = ClientImportRun(
            source_system="client_excel",
            source_filename=f"{suffix}.xlsx",
            source_sha256=uuid.uuid4().hex * 2,
            status=ClientImportRunStatus.applied,
        )
        db.add(run)
        await db.flush()
        db.add(
            ClientImportRow(
                import_run_id=run.id,
                sheet_name="Aktywni",
                row_number=1,
                source_key=f"active:{suffix}",
                source_name=suffix,
                category=PortfolioCategory.active,
                matched_client_id=duplicate_id,
                framework_contract_id=fc_id,
            )
        )
        await db.commit()
        run_id = run.id

    async def live() -> int:
        async with AsyncSessionLocal() as db:
            return int(
                await db.scalar(
                    select(func.count(ClientImportRow.id))
                    .join(
                        ClientFrameworkContract,
                        ClientFrameworkContract.id
                        == ClientImportRow.framework_contract_id,
                    )
                    .where(
                        ClientImportRow.import_run_id == run_id,
                        _framework_contract_owner_matches(),
                    )
                )
            )

    async def move_to(client_id: int) -> None:
        async with AsyncSessionLocal() as db:
            fc = await db.get(ClientFrameworkContract, fc_id)
            fc.client_id = client_id
            await db.commit()

    try:
        assert await live() == 1  # na duplikacie z wiersza importu
        await move_to(target_id)
        assert await live() == 1  # na celu scalenia
        await move_to(stranger.id)
        assert await live() == 0  # gdzie indziej = dryf
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientImportRun).where(ClientImportRun.id == run_id)
            )
            await db.commit()
        await _cleanup(duplicate_id, target_id, stranger.id)
