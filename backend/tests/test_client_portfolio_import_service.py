"""Focused rollback safety tests for the client portfolio import."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import delete

import app.models.skill  # noqa: F401  (register relationship target)
from app.core.database import AsyncSessionLocal
from app.models.client import Client, ClientStatus
from app.models.client_directory import (
    ClientImportRow,
    ClientImportRowStatus,
    ClientImportRun,
    ClientImportRunStatus,
    ClientPortfolioScope,
    PortfolioCategory,
)
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractSignedVia,
    FrameworkContractStatus,
)
from app.services.client_portfolio_import import (
    SOURCE_SYSTEM,
    _client_state,
    _msa_state,
    _scope_state,
    rollback_client_portfolio_import,
)


def _source_sha() -> str:
    return uuid.uuid4().hex * 2


async def _cleanup(
    *,
    run_id: int,
    client_ids: list[int],
    scope_ids: list[int],
    msa_ids: list[int],
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientImportRow).where(ClientImportRow.import_run_id == run_id)
        )
        if scope_ids:
            await db.execute(
                delete(ClientPortfolioScope).where(
                    ClientPortfolioScope.id.in_(scope_ids)
                )
            )
        if msa_ids:
            await db.execute(
                delete(ClientFrameworkContract).where(
                    ClientFrameworkContract.id.in_(msa_ids)
                )
            )
        await db.execute(delete(ClientImportRun).where(ClientImportRun.id == run_id))
        if client_ids:
            await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.commit()


def _import_row(
    *,
    run_id: int,
    row_number: int,
    client_id: int,
    scope_id: int,
    msa_id: int | None,
    payload: dict,
) -> ClientImportRow:
    return ClientImportRow(
        import_run_id=run_id,
        sheet_name="test",
        row_number=row_number,
        source_key=f"pytest:{run_id}:{row_number}",
        source_name=f"Client {row_number}",
        normalized_name=f"client {row_number}",
        proposed_display_name=f"Client {row_number}",
        category=PortfolioCategory.active,
        status=ClientImportRowStatus.applied,
        match_confidence=1,
        raw_payload=payload,
        matched_client_id=client_id,
        portfolio_scope_id=scope_id,
        framework_contract_id=msa_id,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rollback_restores_existing_and_archives_created_without_lazy_loads() -> (
    None
):
    client_ids: list[int] = []
    scope_ids: list[int] = []
    msa_ids: list[int] = []
    async with AsyncSessionLocal() as db:
        run = ClientImportRun(
            source_system=SOURCE_SYSTEM,
            source_filename="pytest.xlsx",
            source_sha256=_source_sha(),
            status=ClientImportRunStatus.applied,
            summary={"merge": None},
        )
        db.add(run)
        await db.flush()

        existing_client = Client(
            name=f"Existing {uuid.uuid4().hex}",
            display_name="Old display",
            legal_name="Old legal",
            status=ClientStatus.prospect,
            external_source="manual",
        )
        db.add(existing_client)
        await db.flush()
        existing_client_before = _client_state(existing_client)
        existing_client.display_name = "Imported display"
        existing_client.legal_name = "Imported legal"
        existing_client_after = _client_state(existing_client)

        existing_msa = ClientFrameworkContract(
            client_id=existing_client.id,
            name="Old MSA",
            status=FrameworkContractStatus.draft,
            effective_date=date(2025, 1, 1),
            expiry_date=date(2025, 12, 31),
            signed_via=FrameworkContractSignedVia.upload,
            source_system=SOURCE_SYSTEM,
            source_key=f"pytest-existing-msa:{uuid.uuid4().hex}",
            notes="old notes",
        )
        db.add(existing_msa)
        await db.flush()
        existing_msa_before = _msa_state(existing_msa)
        existing_msa.name = "Imported MSA"
        existing_msa.status = FrameworkContractStatus.active
        existing_msa.effective_date = date(2026, 1, 1)
        existing_msa.expiry_date = None
        existing_msa.signed_via = FrameworkContractSignedVia.legacy_import
        existing_msa.import_run_id = run.id
        existing_msa_after = _msa_state(existing_msa)

        existing_scope = ClientPortfolioScope(
            client_id=existing_client.id,
            framework_contract_id=existing_msa.id,
            category=PortfolioCategory.inactive,
            label="Old scope",
            source_system=SOURCE_SYSTEM,
            source_key=f"pytest-existing-scope:{uuid.uuid4().hex}",
        )
        db.add(existing_scope)
        await db.flush()
        existing_scope_before = _scope_state(existing_scope)
        existing_scope.category = PortfolioCategory.active
        existing_scope.label = "Imported scope"
        existing_scope_after = _scope_state(existing_scope)

        created_client = Client(
            name=f"Created {uuid.uuid4().hex}",
            display_name="Created by import",
            legal_name="Created by import S.A.",
            status=ClientStatus.active,
            external_source="excel",
            external_id=f"pytest:{uuid.uuid4().hex}",
        )
        db.add(created_client)
        await db.flush()
        created_client_after = _client_state(created_client)

        created_msa = ClientFrameworkContract(
            client_id=created_client.id,
            name="Created MSA",
            status=FrameworkContractStatus.active,
            effective_date=date(2026, 1, 1),
            expiry_date=None,
            signed_via=FrameworkContractSignedVia.legacy_import,
            source_system=SOURCE_SYSTEM,
            source_key=f"pytest-created-msa:{uuid.uuid4().hex}",
            import_run_id=run.id,
            notes="import notes",
        )
        db.add(created_msa)
        await db.flush()

        created_scope = ClientPortfolioScope(
            client_id=created_client.id,
            framework_contract_id=created_msa.id,
            category=PortfolioCategory.active,
            label=None,
            source_system=SOURCE_SYSTEM,
            source_key=f"pytest-created-scope:{uuid.uuid4().hex}",
        )
        db.add(created_scope)
        await db.flush()

        db.add_all(
            [
                _import_row(
                    run_id=run.id,
                    row_number=1,
                    client_id=existing_client.id,
                    scope_id=existing_scope.id,
                    msa_id=existing_msa.id,
                    payload={
                        "client": {
                            "before": existing_client_before,
                            "after": existing_client_after,
                        },
                        "before_scope": existing_scope_before,
                        "after_scope": existing_scope_after,
                        "before_msa": existing_msa_before,
                        "after_msa": existing_msa_after,
                    },
                ),
                _import_row(
                    run_id=run.id,
                    row_number=2,
                    client_id=created_client.id,
                    scope_id=created_scope.id,
                    msa_id=created_msa.id,
                    payload={
                        "client": {
                            "before": None,
                            "after": created_client_after,
                        },
                        "before_scope": None,
                        "after_scope": _scope_state(created_scope),
                        "before_msa": None,
                        "after_msa": _msa_state(created_msa),
                    },
                ),
            ]
        )
        await db.commit()
        run_id = run.id
        client_ids = [existing_client.id, created_client.id]
        scope_ids = [existing_scope.id, created_scope.id]
        msa_ids = [existing_msa.id, created_msa.id]

    try:
        async with AsyncSessionLocal() as db:
            result = await rollback_client_portfolio_import(db, run_id=run_id)
            assert result == {
                "status": "rolled_back",
                "run_id": run_id,
                "conflicts": [],
            }
            await db.commit()

        async with AsyncSessionLocal() as db:
            existing_client = await db.get(Client, client_ids[0])
            created_client = await db.get(Client, client_ids[1])
            existing_scope = await db.get(ClientPortfolioScope, scope_ids[0])
            created_scope = await db.get(ClientPortfolioScope, scope_ids[1])
            existing_msa = await db.get(ClientFrameworkContract, msa_ids[0])
            created_msa = await db.get(ClientFrameworkContract, msa_ids[1])
            run = await db.get(ClientImportRun, run_id)

            assert existing_client is not None
            assert existing_client.display_name == "Old display"
            assert existing_client.legal_name == "Old legal"
            assert existing_client.status == ClientStatus.prospect
            assert created_client is not None
            assert created_client.hidden is True
            assert created_client.archived_at is not None
            assert existing_scope is not None
            assert existing_scope.category == PortfolioCategory.inactive
            assert existing_scope.label == "Old scope"
            assert created_scope is not None
            assert created_scope.archived_at is not None
            assert existing_msa is not None
            assert existing_msa.name == "Old MSA"
            assert existing_msa.status == FrameworkContractStatus.draft
            assert existing_msa.import_run_id is None
            assert created_msa is not None
            assert created_msa.status == FrameworkContractStatus.superseded
            assert run is not None
            assert run.status == ClientImportRunStatus.rolled_back
    finally:
        await _cleanup(
            run_id=run_id,
            client_ids=client_ids,
            scope_ids=scope_ids,
            msa_ids=msa_ids,
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rollback_preflight_conflict_changes_nothing_and_keeps_run_applied() -> (
    None
):
    async with AsyncSessionLocal() as db:
        run = ClientImportRun(
            source_system=SOURCE_SYSTEM,
            source_filename="pytest.xlsx",
            source_sha256=_source_sha(),
            status=ClientImportRunStatus.applied,
            summary={"merge": None},
        )
        client = Client(
            name=f"Preflight {uuid.uuid4().hex}",
            status=ClientStatus.active,
        )
        db.add_all((run, client))
        await db.flush()
        first = ClientPortfolioScope(
            client_id=client.id,
            category=PortfolioCategory.inactive,
            source_system=SOURCE_SYSTEM,
            source_key=f"pytest-first:{uuid.uuid4().hex}",
        )
        second = ClientPortfolioScope(
            client_id=client.id,
            category=PortfolioCategory.inactive,
            source_system=SOURCE_SYSTEM,
            source_key=f"pytest-second:{uuid.uuid4().hex}",
        )
        db.add_all((first, second))
        await db.flush()
        first_after = _scope_state(first)
        second_after = _scope_state(second)
        db.add_all(
            [
                _import_row(
                    run_id=run.id,
                    row_number=1,
                    client_id=client.id,
                    scope_id=first.id,
                    msa_id=None,
                    payload={
                        "before_scope": None,
                        "after_scope": first_after,
                    },
                ),
                _import_row(
                    run_id=run.id,
                    row_number=2,
                    client_id=client.id,
                    scope_id=second.id,
                    msa_id=None,
                    payload={
                        "before_scope": None,
                        "after_scope": second_after,
                    },
                ),
            ]
        )
        await db.commit()
        run_id = run.id
        client_id = client.id
        scope_ids = [first.id, second.id]

        second.label = "edited after import"
        await db.commit()

    try:
        async with AsyncSessionLocal() as db:
            result = await rollback_client_portfolio_import(db, run_id=run_id)
            assert result["status"] == "blocked"
            assert any(
                conflict["reason"] == "changed_after_import"
                and conflict["entity"] == "scope"
                and conflict["entity_id"] == scope_ids[1]
                for conflict in result["conflicts"]
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            first = await db.get(ClientPortfolioScope, scope_ids[0])
            second = await db.get(ClientPortfolioScope, scope_ids[1])
            run = await db.get(ClientImportRun, run_id)
            assert first is not None and first.archived_at is None
            assert second is not None and second.label == "edited after import"
            assert run is not None
            assert run.status == ClientImportRunStatus.applied
    finally:
        await _cleanup(
            run_id=run_id,
            client_ids=[client_id],
            scope_ids=scope_ids,
            msa_ids=[],
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rollback_kir_reference_ledger_gap_blocks_before_scope_mutation() -> None:
    async with AsyncSessionLocal() as db:
        run = ClientImportRun(
            source_system=SOURCE_SYSTEM,
            source_filename="pytest.xlsx",
            source_sha256=_source_sha(),
            status=ClientImportRunStatus.applied,
            summary={
                "merge": {
                    "already_merged": False,
                    "moved_references": [
                        {"table": "jobs", "column": "client_id", "rows": 1}
                    ],
                    "jsonb_candidates": 0,
                }
            },
        )
        client = Client(
            name=f"KIR blocker {uuid.uuid4().hex}",
            status=ClientStatus.active,
        )
        db.add_all((run, client))
        await db.flush()
        scope = ClientPortfolioScope(
            client_id=client.id,
            category=PortfolioCategory.active,
            source_system=SOURCE_SYSTEM,
            source_key=f"pytest-kir-scope:{uuid.uuid4().hex}",
        )
        db.add(scope)
        await db.flush()
        db.add(
            _import_row(
                run_id=run.id,
                row_number=1,
                client_id=client.id,
                scope_id=scope.id,
                msa_id=None,
                payload={
                    "before_scope": None,
                    "after_scope": _scope_state(scope),
                },
            )
        )
        await db.commit()
        run_id = run.id
        client_id = client.id
        scope_id = scope.id

    try:
        async with AsyncSessionLocal() as db:
            result = await rollback_client_portfolio_import(db, run_id=run_id)
            assert result["status"] == "blocked"
            assert any(
                conflict["reason"] == "kir_merge_requires_row_level_rollback"
                for conflict in result["conflicts"]
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            scope = await db.get(ClientPortfolioScope, scope_id)
            run = await db.get(ClientImportRun, run_id)
            assert scope is not None and scope.archived_at is None
            assert run is not None
            assert run.status == ClientImportRunStatus.applied
    finally:
        await _cleanup(
            run_id=run_id,
            client_ids=[client_id],
            scope_ids=[scope_id],
            msa_ids=[],
        )
