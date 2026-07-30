"""Focused rollback safety tests for the client portfolio import."""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

import app.models.skill  # noqa: F401  (register relationship target)
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.client import Client, ClientStatus
from app.models.client_directory import (
    ClientAlias,
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
    _public_client,
    _scope_state,
    apply_client_portfolio_manifest,
    build_client_portfolio_plan,
    normalize_client_name,
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
        if client_ids:
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "client",
                    Activity.entity_id.in_(client_ids),
                )
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


def _manifest_row(
    *,
    suffix: str,
    client_key: str,
    display_name: str,
    row_number: int,
    aliases: list[str] | None = None,
    category: str = "active",
) -> dict:
    return {
        "source_key": f"pytest:{suffix}:{row_number}",
        "client_key": client_key,
        "sheet": f"pytest-{category}",
        "row_number": row_number,
        "legal_name": display_name,
        "display_name": display_name,
        "aliases": aliases or [],
        "scope_label": None,
        "category": category,
        "effective_date": None,
        "expiry_date": None,
        "expiry_is_open_ended": False,
        "workbook_status": None,
    }


def _manifest(*, suffix: str, rows: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "snapshot_date": "2026-07-30",
        "source": {
            "filename": f"pytest-{suffix}.xlsx",
            "sha256": uuid.uuid4().hex * 2,
        },
        "known_anomalies": [],
        "rows": rows,
    }


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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_plan_prefers_alias_and_blocks_ambiguous_or_fuzzy_matches() -> None:
    suffix = uuid.uuid4().hex[:12]
    alias_label = f"Reviewed Alias {suffix}"
    ambiguous_label = f"Ambiguous Holdings {suffix}"
    fuzzy_client_label = f"Fuzzy Consulting {suffix}"
    clients: list[Client] = [
        Client(name="KIR", status=ClientStatus.active),
        Client(
            name=f"Canonical Alias Target {suffix}",
            status=ClientStatus.active,
        ),
        # The exact-name record must lose to the reviewed alias above.
        Client(name=alias_label, status=ClientStatus.active),
        Client(name=ambiguous_label, status=ClientStatus.active),
        Client(name=ambiguous_label, status=ClientStatus.inactive),
        Client(name=fuzzy_client_label, status=ClientStatus.active),
        Client(
            name=f"NEXUS Only {suffix}",
            status=ClientStatus.prospect,
        ),
    ]
    client_ids: list[int] = []
    alias_id: int | None = None
    try:
        async with AsyncSessionLocal() as db:
            db.add_all(clients)
            await db.flush()
            alias_target = clients[1]
            nexus_only = clients[-1]
            reviewed_alias = ClientAlias(
                client_id=alias_target.id,
                alias=alias_label,
                normalized_alias=normalize_client_name(alias_label),
                source_system="pytest",
                source_key=f"pytest-plan-alias:{suffix}",
            )
            db.add(reviewed_alias)
            await db.commit()
            client_ids = [client.id for client in clients]
            alias_id = reviewed_alias.id
            alias_target_id = alias_target.id
            nexus_only_id = nexus_only.id

        rows = [
            _manifest_row(
                suffix=suffix,
                client_key="alias",
                display_name=alias_label,
                row_number=2,
            ),
            _manifest_row(
                suffix=suffix,
                client_key="new",
                display_name=f"Brand New Portfolio {suffix}",
                row_number=3,
            ),
            _manifest_row(
                suffix=suffix,
                client_key="ambiguous",
                display_name=ambiguous_label,
                row_number=4,
            ),
            _manifest_row(
                suffix=suffix,
                client_key="fuzzy",
                display_name=f"Fuzzy Consultng {suffix}",
                row_number=5,
            ),
        ]
        manifest = _manifest(suffix=suffix, rows=rows)

        async with AsyncSessionLocal() as db:
            plan = await build_client_portfolio_plan(db, manifest=manifest)

        groups = {group["client_key"]: group for group in plan["groups"]}
        blockers = {blocker["client_key"]: blocker for blocker in plan["blockers"]}

        assert groups["alias"]["action"] == "match"
        assert groups["alias"]["match_method"] == "approved_alias"
        assert groups["alias"]["target_client"]["id"] == alias_target_id
        assert groups["new"]["action"] == "create"
        assert groups["ambiguous"]["action"] == "blocked"
        assert blockers["ambiguous"]["code"] == "ambiguous_exact_match"
        assert groups["fuzzy"]["action"] == "blocked"
        assert blockers["fuzzy"]["code"] == "plausible_duplicate_requires_review"
        assert nexus_only_id in {client["id"] for client in plan["nexus_only"]}
    finally:
        if client_ids:
            async with AsyncSessionLocal() as db:
                if alias_id is not None:
                    await db.execute(
                        delete(ClientAlias).where(ClientAlias.id == alias_id)
                    )
                await db.execute(delete(Client).where(Client.id.in_(client_ids)))
                await db.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_apply_creates_client_adds_nexus_only_scope_and_is_idempotent(
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex[:12]
    existing_client_id: int | None = None
    created_client_id: int | None = None
    run_id: int | None = None
    scope_ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            existing = Client(
                name=f"Existing NEXUS Only {suffix}",
                status=ClientStatus.prospect,
            )
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            existing_client_id = existing.id
            nexus_only_snapshot = _public_client(existing)

        row = _manifest_row(
            suffix=suffix,
            client_key=f"new-{suffix}",
            display_name=f"New Imported Client {suffix}",
            row_number=2,
        )
        manifest = _manifest(suffix=suffix, rows=[row])
        plan = {
            "manifest_sha256": manifest["source"]["sha256"],
            "snapshot_date": manifest["snapshot_date"],
            "groups": [
                {
                    "client_key": row["client_key"],
                    "action": "create",
                    "rows": [row],
                }
            ],
            "nexus_only": [nexus_only_snapshot],
            "kir_merge": None,
            "duplicate_candidates": [],
            "blockers": [],
            "warnings": [],
            "plan_sha256": uuid.uuid4().hex * 2,
            "summary": {
                "manifest_rows": 1,
                "matched_groups": 0,
                "created_groups": 1,
                "blocked_groups": 0,
                "nexus_only_clients": 1,
                "duplicate_candidates": 0,
                "blockers": 0,
                "warnings": 0,
            },
        }
        plan_builder = AsyncMock(return_value=plan)
        monkeypatch.setattr(
            "app.services.client_portfolio_import.build_client_portfolio_plan",
            plan_builder,
        )

        async with AsyncSessionLocal() as db:
            first = await apply_client_portfolio_manifest(db, manifest=manifest)
            assert first["status"] == "applied"
            await db.commit()
            run_id = first["run_id"]

            second = await apply_client_portfolio_manifest(db, manifest=manifest)
            assert second["status"] == "already_applied"
            assert second["run_id"] == run_id
            await db.rollback()

        assert plan_builder.await_count == 1
        async with AsyncSessionLocal() as db:
            created = await db.scalar(
                select(Client).where(
                    Client.external_source == SOURCE_SYSTEM,
                    Client.name == row["display_name"],
                )
            )
            assert created is not None
            created_client_id = created.id
            assert created.status == ClientStatus.active

            existing = await db.get(Client, existing_client_id)
            assert existing is not None
            assert existing.status == ClientStatus.prospect

            scopes = (
                (
                    await db.execute(
                        select(ClientPortfolioScope).where(
                            ClientPortfolioScope.client_id.in_(
                                [created_client_id, existing_client_id]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            scope_ids = [scope.id for scope in scopes]
            categories = {
                scope.client_id: scope.category
                for scope in scopes
                if scope.archived_at is None
            }
            assert categories == {
                created_client_id: PortfolioCategory.active,
                existing_client_id: PortfolioCategory.inactive,
            }

            runs = (
                (
                    await db.execute(
                        select(ClientImportRun).where(
                            ClientImportRun.source_sha256
                            == manifest["source"]["sha256"]
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [run.status for run in runs] == [ClientImportRunStatus.applied]
    finally:
        if run_id is not None and existing_client_id is not None:
            await _cleanup(
                run_id=run_id,
                client_ids=[
                    client_id
                    for client_id in (existing_client_id, created_client_id)
                    if client_id is not None
                ],
                scope_ids=scope_ids,
                msa_ids=[],
            )
        elif existing_client_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Client).where(Client.id == existing_client_id))
                await db.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rollback_then_reapply_revives_same_scope_client_and_alias(
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex[:12]
    alias_text = f"Reversible Alias {suffix}"
    row = _manifest_row(
        suffix=suffix,
        client_key=f"reversible-{suffix}",
        display_name=f"Reversible Client {suffix}",
        row_number=2,
        aliases=[alias_text],
    )
    manifest = _manifest(suffix=suffix, rows=[row])
    plan = {
        "manifest_sha256": manifest["source"]["sha256"],
        "snapshot_date": manifest["snapshot_date"],
        "groups": [
            {
                "client_key": row["client_key"],
                "action": "create",
                "rows": [row],
            }
        ],
        "nexus_only": [],
        "kir_merge": None,
        "duplicate_candidates": [],
        "blockers": [],
        "warnings": [],
        "plan_sha256": uuid.uuid4().hex * 2,
        "summary": {
            "manifest_rows": 1,
            "matched_groups": 0,
            "created_groups": 1,
            "blocked_groups": 0,
            "nexus_only_clients": 0,
            "duplicate_candidates": 0,
            "blockers": 0,
            "warnings": 0,
        },
    }
    plan_builder = AsyncMock(side_effect=[plan, plan])
    monkeypatch.setattr(
        "app.services.client_portfolio_import.build_client_portfolio_plan",
        plan_builder,
    )

    first_run_id: int | None = None
    second_run_id: int | None = None
    client_id: int | None = None
    scope_id: int | None = None
    alias_id: int | None = None
    try:
        async with AsyncSessionLocal() as db:
            first = await apply_client_portfolio_manifest(db, manifest=manifest)
            assert first["status"] == "applied"
            first_run_id = first["run_id"]
            await db.commit()

        async with AsyncSessionLocal() as db:
            client = await db.scalar(
                select(Client).where(
                    Client.external_source == SOURCE_SYSTEM,
                    Client.name == row["display_name"],
                )
            )
            assert client is not None
            client_id = client.id
            scope = await db.scalar(
                select(ClientPortfolioScope).where(
                    ClientPortfolioScope.source_system == SOURCE_SYSTEM,
                    ClientPortfolioScope.source_key == row["source_key"],
                )
            )
            alias = await db.scalar(
                select(ClientAlias).where(
                    ClientAlias.client_id == client_id,
                    ClientAlias.normalized_alias == normalize_client_name(alias_text),
                )
            )
            assert scope is not None
            assert alias is not None
            scope_id = scope.id
            alias_id = alias.id
            assert scope.archived_at is None
            assert alias.archived_at is None
            assert alias.import_run_id == first_run_id

        async with AsyncSessionLocal() as db:
            rolled_back = await rollback_client_portfolio_import(
                db, run_id=first_run_id
            )
            assert rolled_back["status"] == "rolled_back"
            await db.commit()

        async with AsyncSessionLocal() as db:
            client = await db.get(Client, client_id)
            scope = await db.get(ClientPortfolioScope, scope_id)
            alias = await db.get(ClientAlias, alias_id)
            assert client is not None
            assert client.hidden is True
            assert client.archived_at is not None
            assert scope is not None
            assert scope.archived_at is not None
            assert alias is not None
            assert alias.archived_at is not None
            assert alias.import_run_id == first_run_id

        async with AsyncSessionLocal() as db:
            second = await apply_client_portfolio_manifest(db, manifest=manifest)
            assert second["status"] == "applied"
            second_run_id = second["run_id"]
            assert second_run_id != first_run_id
            await db.commit()

        assert plan_builder.await_count == 2
        async with AsyncSessionLocal() as db:
            client = await db.get(Client, client_id)
            scopes = (
                (
                    await db.execute(
                        select(ClientPortfolioScope).where(
                            ClientPortfolioScope.source_system == SOURCE_SYSTEM,
                            ClientPortfolioScope.source_key == row["source_key"],
                        )
                    )
                )
                .scalars()
                .all()
            )
            aliases = (
                (
                    await db.execute(
                        select(ClientAlias).where(
                            ClientAlias.client_id == client_id,
                            ClientAlias.normalized_alias
                            == normalize_client_name(alias_text),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert client is not None
            assert client.hidden is False
            assert client.archived_at is None
            assert [scope.id for scope in scopes] == [scope_id]
            assert scopes[0].archived_at is None
            assert [alias.id for alias in aliases] == [alias_id]
            assert aliases[0].archived_at is None
            assert aliases[0].import_run_id == second_run_id
    finally:
        if second_run_id is not None:
            await _cleanup(
                run_id=second_run_id,
                client_ids=[],
                scope_ids=[],
                msa_ids=[],
            )
        if first_run_id is not None:
            await _cleanup(
                run_id=first_run_id,
                client_ids=[client_id] if client_id is not None else [],
                scope_ids=[scope_id] if scope_id is not None else [],
                msa_ids=[],
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_apply_failure_rolls_back_all_business_rows_but_keeps_failed_audit(
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex[:12]
    first_row = _manifest_row(
        suffix=suffix,
        client_key=f"first-{suffix}",
        display_name=f"First Atomic Client {suffix}",
        row_number=2,
    )
    second_row = _manifest_row(
        suffix=suffix,
        client_key=f"second-{suffix}",
        display_name=f"Second Atomic Client {suffix}",
        row_number=3,
    )
    manifest = _manifest(suffix=suffix, rows=[first_row, second_row])
    plan = {
        "manifest_sha256": manifest["source"]["sha256"],
        "snapshot_date": manifest["snapshot_date"],
        "groups": [
            {
                "client_key": first_row["client_key"],
                "action": "create",
                "rows": [first_row],
            },
            {
                "client_key": second_row["client_key"],
                "action": "invalid-test-action",
                "rows": [second_row],
            },
        ],
        "nexus_only": [],
        "kir_merge": None,
        "duplicate_candidates": [],
        "blockers": [],
        "warnings": [],
        "plan_sha256": uuid.uuid4().hex * 2,
        "summary": {},
    }
    monkeypatch.setattr(
        "app.services.client_portfolio_import.build_client_portfolio_plan",
        AsyncMock(return_value=plan),
    )
    run_id: int | None = None
    try:
        async with AsyncSessionLocal() as db:
            result = await apply_client_portfolio_manifest(db, manifest=manifest)
            assert result["status"] == "failed"
            assert "Unexpected group action" in result["error"]
            run_id = result["run_id"]
            await db.commit()

        async with AsyncSessionLocal() as db:
            imported_clients = (
                (
                    await db.execute(
                        select(Client).where(
                            Client.external_source == SOURCE_SYSTEM,
                            Client.name.in_(
                                [
                                    first_row["display_name"],
                                    second_row["display_name"],
                                ]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            import_rows = (
                (
                    await db.execute(
                        select(ClientImportRow).where(
                            ClientImportRow.import_run_id == run_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            run = await db.get(ClientImportRun, run_id)

            assert imported_clients == []
            assert import_rows == []
            assert run is not None
            assert run.status == ClientImportRunStatus.failed
    finally:
        if run_id is not None:
            await _cleanup(
                run_id=run_id,
                client_ids=[],
                scope_ids=[],
                msa_ids=[],
            )
