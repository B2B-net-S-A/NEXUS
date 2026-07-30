"""Focused unit contracts for the PR2 client-directory safety gates."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, select

import app.models.skill  # noqa: F401  (register relationship target)
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.client_directory import (
    ClientAlias,
    ClientImportRow,
    ClientImportRun,
    ClientPortfolioScope,
    PortfolioCategory,
)
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.services import client_portfolio_import as service


def _client(
    client_id: int,
    name: str,
    *,
    nip: str | None = None,
    regon: str | None = None,
) -> Client:
    client = Client(
        name=name,
        status=ClientStatus.active,
        nip=nip,
        regon=regon,
    )
    client.id = client_id
    return client


def _manifest_row() -> dict:
    return {
        "source_key": "active:krajowa-izba-rozliczen",
        "client_key": "krajowa-izba-rozliczen",
        "sheet": "Aktywni Klienci",
        "row_number": 2,
        "legal_name": "Krajowa Izba Rozliczeń S.A.",
        "display_name": "Krajowa Izba Rozliczeń",
        "aliases": ["KIR"],
        "scope_label": None,
        "category": "active",
        "effective_date": None,
        "expiry_date": None,
        "expiry_is_open_ended": False,
        "workbook_status": "aktywny",
    }


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "snapshot_date": "2026-07-30",
        "source": {
            "filename": "pytest-kir.xlsx",
            "sha256": "a" * 64,
        },
        "known_anomalies": [],
        "rows": [_manifest_row()],
    }


def test_duplicate_report_uses_nip_regon_and_aliases_without_merging() -> None:
    clients = [
        _client(1, "Alpha One", nip="123-456-78-90"),
        _client(2, "Beta Two", nip="1234567890"),
        _client(3, "Gamma Three", regon="123 456 789"),
        _client(4, "Delta Four", regon="123456789"),
        _client(5, "Epsilon Five"),
        _client(6, "Zeta Six"),
    ]

    candidates = service._duplicate_candidates(
        clients,
        {
            5: ["Historic Company Name"],
            6: ["Historic Company Name"],
        },
    )
    by_pair = {tuple(candidate["client_ids"]): candidate for candidate in candidates}

    assert by_pair[(1, 2)]["reason"] == "same_nip"
    assert by_pair[(3, 4)]["reason"] == "same_regon"
    assert by_pair[(5, 6)]["reason"] == "same_normalized_name_or_alias"


@pytest.mark.asyncio
async def test_kir_alias_cannot_select_an_unapproved_survivor(monkeypatch) -> None:
    unrelated = _client(10, "Unrelated Holdings")
    exact_duplicate = _client(11, "Krajowa Izba Rozliczeń S.A.")
    monkeypatch.setattr(
        service,
        "_load_directory_clients",
        AsyncMock(
            return_value=(
                [unrelated, exact_duplicate],
                {unrelated.id: ["KIR"]},
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_direct_client_fk_counts",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        service,
        "_candidate_excluded_client_count",
        AsyncMock(return_value=0),
    )

    plan = await service.build_client_portfolio_plan(
        SimpleNamespace(), manifest=_manifest()
    )
    group = plan["groups"][0]

    assert group["action"] != "match"
    assert not (
        group.get("target_client") and group["target_client"]["id"] == unrelated.id
    )
    assert any(
        blocker["code"] == "kir_survivor_not_unique" for blocker in plan["blockers"]
    )


@pytest.mark.asyncio
async def test_exact_kir_source_name_wins_over_colliding_alias(monkeypatch) -> None:
    survivor = _client(20, "KIR")
    survivor.display_name = "Krajowa Izba Rozliczeń"
    exact_duplicate = _client(21, "Krajowa Izba Rozliczeń S.A.")
    unrelated = _client(22, "Unrelated Alias Owner")
    monkeypatch.setattr(
        service,
        "_load_directory_clients",
        AsyncMock(
            return_value=(
                [survivor, exact_duplicate, unrelated],
                {unrelated.id: ["KIR"]},
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_direct_client_fk_counts",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        service,
        "_candidate_excluded_client_count",
        AsyncMock(return_value=0),
    )

    plan = await service.build_client_portfolio_plan(
        SimpleNamespace(), manifest=_manifest()
    )
    group = plan["groups"][0]

    assert group["action"] == "match"
    assert group["match_method"] == "approved_kir_survivor"
    assert group["target_client"]["id"] == survivor.id
    assert plan["kir_merge"]["source"]["id"] == exact_duplicate.id
    assert plan["kir_merge"]["target"]["id"] == survivor.id
    reported_pairs = {
        tuple(candidate["client_ids"]) for candidate in plan["duplicate_candidates"]
    }
    assert (survivor.id, exact_duplicate.id) not in reported_pairs
    assert (survivor.id, unrelated.id) in reported_pairs


@pytest.mark.asyncio
async def test_kir_merge_revalidates_exact_source_and_survivor_names() -> None:
    duplicate = _client(30, "Krajowa Izba Rozliczeń S.A.")
    alias_only_target = _client(31, "Unrelated KIR Alias Owner")
    alias_only_target.display_name = "KIR"
    locked = MagicMock()
    locked.scalars.return_value.all.return_value = [
        duplicate,
        alias_only_target,
    ]
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=AsyncMock(return_value=locked),
    )

    with pytest.raises(
        service.ClientPortfolioImportError,
        match="not the approved survivor",
    ):
        await service._merge_kir(
            db,
            source_id=duplicate.id,
            target_id=alias_only_target.id,
            expected_source_updated_at=None,
            expected_target_updated_at=None,
            archived_by=None,
            import_run_id=1,
        )


@pytest.mark.asyncio
async def test_already_applied_is_blocked_when_live_health_is_inconsistent(
    monkeypatch,
) -> None:
    manifest = {
        "source": {"filename": "pytest.xlsx", "sha256": "b" * 64},
        "rows": [],
    }
    run = SimpleNamespace(
        id=71,
        summary={
            "normalized_manifest_sha256": service._normalized_manifest_sha256(manifest)
        },
    )
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
        scalar=AsyncMock(return_value=run),
    )
    health = AsyncMock(
        return_value={
            "status": "inconsistent",
            "counts": {"live_portfolio_scopes": 0},
        }
    )
    monkeypatch.setattr(service, "get_client_portfolio_import_health", health)

    result = await service.apply_client_portfolio_manifest(db, manifest=manifest)

    assert result["status"] == "blocked"
    assert result["run_id"] == run.id
    assert result["blockers"] == [
        {
            "code": "applied_manifest_state_inconsistent",
            "health_status": "inconsistent",
            "counts": {"live_portfolio_scopes": 0},
        }
    ]
    health.assert_awaited_once_with(db, manifest=manifest)


@pytest.mark.asyncio
async def test_postgres_candidate_dependency_count_uses_jsonb_containment() -> None:
    class Session:
        @property
        def bind(self):
            raise AssertionError("AsyncSession.bind must not be read")

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        scalar = AsyncMock(return_value=2)

    db = Session()
    count = await service._candidate_excluded_client_count(db, 42)

    assert count == 2
    statement = str(db.scalar.await_args.args[0])
    assert "@>" in statement
    assert db.scalar.await_args.args[1] == {
        "numeric_payload": '{"excluded_clients": [42]}',
        "string_payload": '{"excluded_clients": ["42"]}',
    }


def _apply_plan(
    manifest: dict,
    *,
    groups: list[dict],
    nexus_only: list[dict] | None = None,
    kir_merge: dict | None = None,
) -> dict:
    return {
        "manifest_sha256": manifest["source"]["sha256"],
        "snapshot_date": manifest["snapshot_date"],
        "groups": groups,
        "nexus_only": nexus_only or [],
        "kir_merge": kir_merge,
        "duplicate_candidates": [],
        "blockers": [],
        "warnings": [],
        "plan_sha256": uuid.uuid4().hex * 2,
        "summary": {
            "manifest_rows": len(manifest["rows"]),
            "matched_groups": sum(group["action"] == "match" for group in groups),
            "created_groups": sum(group["action"] == "create" for group in groups),
            "blocked_groups": 0,
            "nexus_only_clients": len(nexus_only or []),
            "duplicate_candidates": 0,
            "blockers": 0,
            "warnings": 0,
        },
    }


async def _delete_test_import_state(
    *,
    run_ids: list[int],
    client_ids: list[int],
    scope_ids: list[int],
    msa_ids: list[int] | None = None,
    candidate_ids: list[int] | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        if run_ids:
            await db.execute(
                delete(ClientImportRow).where(
                    ClientImportRow.import_run_id.in_(run_ids)
                )
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
        if client_ids:
            await db.execute(
                delete(ClientAlias).where(ClientAlias.client_id.in_(client_ids))
            )
        if run_ids:
            await db.execute(
                delete(ClientImportRun).where(ClientImportRun.id.in_(run_ids))
            )
        if candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        if client_ids:
            await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_kir_dependency_ledger_round_trips_fk_and_candidate_json(
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex[:12]
    client_ids: list[int] = []
    candidate_ids: list[int] = []
    scope_ids: list[int] = []
    run_ids: list[int] = []
    legacy_alias_id: int | None = None
    try:
        async with AsyncSessionLocal() as db:
            survivor = Client(name="KIR", status=ClientStatus.active)
            duplicate = Client(
                name="Krajowa Izba Rozliczeń S.A.",
                status=ClientStatus.active,
            )
            db.add_all((survivor, duplicate))
            await db.flush()
            legacy_alias = ClientAlias(
                client_id=duplicate.id,
                alias=f"Legacy KIR {suffix}",
                normalized_alias=service.normalize_client_name(f"Legacy KIR {suffix}"),
                source_system="pytest",
                source_key=f"pytest-kir-ledger:{suffix}",
            )
            candidate = Candidate(
                name=f"Candidate {suffix}",
                lastname="Ledger",
                preferences={
                    "excluded_clients": [str(duplicate.id), survivor.id],
                    "remote_modes": ["remote"],
                },
            )
            db.add_all((legacy_alias, candidate))
            await db.commit()
            await db.refresh(survivor)
            await db.refresh(duplicate)
            client_ids = [survivor.id, duplicate.id]
            candidate_ids = [candidate.id]
            legacy_alias_id = legacy_alias.id
            survivor_snapshot = service._public_client(survivor)
            duplicate_snapshot = service._public_client(duplicate)

        row = _manifest_row()
        row["source_key"] = f"pytest-kir-ledger:{suffix}:row"
        row["aliases"] = []
        manifest = {
            "schema_version": 1,
            "snapshot_date": "2026-07-30",
            "source": {
                "filename": f"pytest-kir-ledger-{suffix}.xlsx",
                "sha256": uuid.uuid4().hex * 2,
            },
            "known_anomalies": [],
            "rows": [row],
        }
        plan = _apply_plan(
            manifest,
            groups=[
                {
                    "client_key": row["client_key"],
                    "action": "match",
                    "match_method": "approved_kir_survivor",
                    "target_client": survivor_snapshot,
                    "rows": [row],
                }
            ],
            kir_merge={
                "source": duplicate_snapshot,
                "target": survivor_snapshot,
                "fk_impact": [
                    {
                        "table": "client_aliases",
                        "column": "client_id",
                        "rows": 1,
                        "primary_key_columns": ["id"],
                        "rollback_supported": True,
                    }
                ],
                "jsonb_candidates": 1,
            },
        )
        monkeypatch.setattr(
            service,
            "build_client_portfolio_plan",
            AsyncMock(return_value=plan),
        )
        # Fixed production alias keys are not relevant to this dependency
        # round-trip and would couple the test to pre-existing database data.
        monkeypatch.setattr(
            service,
            "_upsert_alias",
            AsyncMock(return_value=None),
        )

        async with AsyncSessionLocal() as db:
            applied = await service.apply_client_portfolio_manifest(
                db, manifest=manifest
            )
            assert applied["status"] == "applied"
            run_ids = [applied["run_id"]]
            merge = applied["summary"]["merge"]
            assert merge["jsonb_candidates"] == 1
            assert len(merge["candidate_preferences_ledger"]) == 1
            assert any(
                item["table"] == "client_aliases"
                and item["column"] == "client_id"
                and item["records"]
                for item in merge["reference_ledger"]
            )
            scope_ids = list(applied["summary"]["scope_ids"])
            await db.commit()

        async with AsyncSessionLocal() as db:
            alias = await db.get(ClientAlias, legacy_alias_id)
            candidate = await db.get(Candidate, candidate_ids[0])
            duplicate = await db.get(Client, client_ids[1])
            assert alias is not None and alias.client_id == client_ids[0]
            assert candidate is not None
            assert candidate.preferences["excluded_clients"] == [client_ids[0]]
            assert candidate.preferences["remote_modes"] == ["remote"]
            assert duplicate is not None
            assert duplicate.hidden is True
            assert duplicate.merged_into_client_id == client_ids[0]

        async with AsyncSessionLocal() as db:
            rolled_back = await service.rollback_client_portfolio_import(
                db, run_id=run_ids[0]
            )
            assert rolled_back["status"] == "rolled_back"
            await db.commit()

        async with AsyncSessionLocal() as db:
            alias = await db.get(ClientAlias, legacy_alias_id)
            candidate = await db.get(Candidate, candidate_ids[0])
            duplicate = await db.get(Client, client_ids[1])
            assert alias is not None and alias.client_id == client_ids[1]
            assert candidate is not None
            assert candidate.preferences == {
                "excluded_clients": [str(client_ids[1]), client_ids[0]],
                "remote_modes": ["remote"],
            }
            assert duplicate is not None
            assert duplicate.hidden is False
            assert duplicate.archived_at is None
            assert duplicate.merged_into_client_id is None
    finally:
        await _delete_test_import_state(
            run_ids=run_ids,
            client_ids=client_ids,
            scope_ids=scope_ids,
            candidate_ids=candidate_ids,
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_nexus_only_scope_id_is_reused_across_snapshot_hashes(
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex[:12]
    run_ids: list[int] = []
    client_ids: list[int] = []
    scope_ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            client = Client(
                name=f"Stable NEXUS Only {suffix}",
                status=ClientStatus.prospect,
            )
            db.add(client)
            await db.commit()
            await db.refresh(client)
            client_ids = [client.id]
            snapshot = service._public_client(client)

        first_manifest = {
            "schema_version": 1,
            "snapshot_date": "2026-07-30",
            "source": {
                "filename": f"pytest-stable-first-{suffix}.xlsx",
                "sha256": uuid.uuid4().hex * 2,
            },
            "known_anomalies": [],
            "rows": [],
        }
        second_manifest = {
            **first_manifest,
            "snapshot_date": "2026-08-30",
            "source": {
                "filename": f"pytest-stable-second-{suffix}.xlsx",
                "sha256": uuid.uuid4().hex * 2,
            },
        }
        first_plan = _apply_plan(
            first_manifest,
            groups=[],
            nexus_only=[snapshot],
        )
        second_plan = _apply_plan(
            second_manifest,
            groups=[],
            nexus_only=[snapshot],
        )
        # PostgreSQL apply builds once before and once after acquiring the
        # matching write-surface locks. Each apply must therefore observe the
        # same plan twice or fail closed on plan drift.
        plan_builder = AsyncMock(
            side_effect=[first_plan, first_plan, second_plan, second_plan]
        )
        monkeypatch.setattr(service, "build_client_portfolio_plan", plan_builder)

        async with AsyncSessionLocal() as db:
            first = await service.apply_client_portfolio_manifest(
                db, manifest=first_manifest
            )
            assert first["status"] == "applied"
            run_ids.append(first["run_id"])
            first_scope_id = first["summary"]["scope_ids"][0]
            scope_ids.append(first_scope_id)
            await db.commit()

        async with AsyncSessionLocal() as db:
            second = await service.apply_client_portfolio_manifest(
                db, manifest=second_manifest
            )
            assert second["status"] == "applied"
            run_ids.append(second["run_id"])
            assert second["summary"]["scope_ids"] == [first_scope_id]
            await db.commit()

        assert plan_builder.await_count == 4

        async with AsyncSessionLocal() as db:
            scopes = (
                (
                    await db.execute(
                        select(ClientPortfolioScope).where(
                            ClientPortfolioScope.client_id == client_ids[0],
                            ClientPortfolioScope.source_system == service.SOURCE_SYSTEM,
                            ClientPortfolioScope.source_key
                            == f"nexus-only:{client_ids[0]}",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [scope.id for scope in scopes] == [first_scope_id]
            assert scopes[0].archived_at is None
    finally:
        await _delete_test_import_state(
            run_ids=run_ids,
            client_ids=client_ids,
            scope_ids=scope_ids,
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_nexus_only_scope_is_stable_then_superseded_and_rollback_safe(
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex[:12]
    run_ids: list[int] = []
    client_ids: list[int] = []
    scope_ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            client = Client(
                name=f"Snapshot Evolution {suffix}",
                status=ClientStatus.prospect,
            )
            db.add(client)
            await db.commit()
            await db.refresh(client)
            client_ids = [client.id]
            first_snapshot = service._public_client(client)

        first_manifest = {
            "schema_version": 1,
            "snapshot_date": "2026-07-30",
            "source": {
                "filename": f"pytest-empty-{suffix}.xlsx",
                "sha256": uuid.uuid4().hex * 2,
            },
            "known_anomalies": [],
            "rows": [],
        }
        first_plan = _apply_plan(
            first_manifest,
            groups=[],
            nexus_only=[first_snapshot],
        )

        row = {
            **_manifest_row(),
            "source_key": f"pytest-snapshot-evolution:{suffix}",
            "client_key": f"snapshot-evolution-{suffix}",
            "legal_name": f"Snapshot Evolution Legal {suffix}",
            "display_name": f"Snapshot Evolution {suffix}",
            "aliases": [],
        }
        second_manifest = {
            "schema_version": 1,
            "snapshot_date": "2026-08-30",
            "source": {
                "filename": f"pytest-active-{suffix}.xlsx",
                "sha256": uuid.uuid4().hex * 2,
            },
            "known_anomalies": [],
            "rows": [row],
        }
        plan_builder = AsyncMock(side_effect=[first_plan, first_plan])
        monkeypatch.setattr(service, "build_client_portfolio_plan", plan_builder)

        async with AsyncSessionLocal() as db:
            first = await service.apply_client_portfolio_manifest(
                db, manifest=first_manifest
            )
            assert first["status"] == "applied"
            run_ids.append(first["run_id"])
            scope_ids.extend(first["summary"]["scope_ids"])
            await db.commit()

        async with AsyncSessionLocal() as db:
            client = await db.get(Client, client_ids[0])
            assert client is not None
            second_snapshot = service._public_client(client)
            stable_scope = await db.scalar(
                select(ClientPortfolioScope).where(
                    ClientPortfolioScope.source_system == service.SOURCE_SYSTEM,
                    ClientPortfolioScope.source_key == f"nexus-only:{client_ids[0]}",
                )
            )
            assert stable_scope is not None
            assert stable_scope.archived_at is None
            stable_scope_id = stable_scope.id

        second_plan = _apply_plan(
            second_manifest,
            groups=[
                {
                    "client_key": row["client_key"],
                    "action": "match",
                    "match_method": "exact_normalized_name",
                    "target_client": second_snapshot,
                    "rows": [row],
                }
            ],
        )
        plan_builder.side_effect = [second_plan, second_plan]
        async with AsyncSessionLocal() as db:
            second = await service.apply_client_portfolio_manifest(
                db, manifest=second_manifest
            )
            assert second["status"] == "applied"
            run_ids.append(second["run_id"])
            scope_ids.extend(second["summary"]["scope_ids"])
            superseded = second["summary"]["superseded_nexus_only_scope_audits"]
            assert [audit["scope_id"] for audit in superseded] == [stable_scope_id]
            await db.commit()

        assert plan_builder.await_count == 4

        async with AsyncSessionLocal() as db:
            scopes = (
                (
                    await db.execute(
                        select(ClientPortfolioScope).where(
                            ClientPortfolioScope.id.in_(scope_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            live = [scope for scope in scopes if scope.archived_at is None]
            assert len(live) == 1
            assert live[0].source_key == row["source_key"]
            assert live[0].category == PortfolioCategory.active

        async with AsyncSessionLocal() as db:
            rolled_back = await service.rollback_client_portfolio_import(
                db, run_id=run_ids[1]
            )
            assert rolled_back["status"] == "rolled_back"
            await db.commit()

        async with AsyncSessionLocal() as db:
            stable_scope = await db.get(ClientPortfolioScope, stable_scope_id)
            workbook_scope = await db.get(ClientPortfolioScope, scope_ids[-1])
            assert stable_scope is not None
            assert stable_scope.archived_at is None
            assert stable_scope.source_key == f"nexus-only:{client_ids[0]}"
            assert stable_scope.category == PortfolioCategory.inactive
            assert workbook_scope is not None
            assert workbook_scope.archived_at is not None
    finally:
        await _delete_test_import_state(
            run_ids=run_ids,
            client_ids=client_ids,
            scope_ids=list(set(scope_ids)),
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_msa_status_uses_apply_date_not_manifest_snapshot(
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex[:12]
    run_ids: list[int] = []
    client_ids: list[int] = []
    scope_ids: list[int] = []
    msa_ids: list[int] = []
    row = {
        **_manifest_row(),
        "source_key": f"pytest-apply-date:{suffix}",
        "client_key": f"apply-date-{suffix}",
        "legal_name": f"Apply Date Legal {suffix}",
        "display_name": f"Apply Date {suffix}",
        "aliases": [],
        "effective_date": "2026-12-01",
        "expiry_date": None,
        "expiry_is_open_ended": True,
    }
    manifest = {
        "schema_version": 1,
        "snapshot_date": "2026-07-30",
        "source": {
            "filename": f"pytest-apply-date-{suffix}.xlsx",
            "sha256": uuid.uuid4().hex * 2,
        },
        "known_anomalies": [],
        "rows": [row],
    }
    plan = _apply_plan(
        manifest,
        groups=[
            {
                "client_key": row["client_key"],
                "action": "create",
                "rows": [row],
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "build_client_portfolio_plan",
        AsyncMock(return_value=plan),
    )
    monkeypatch.setattr(service, "_application_date", lambda: date(2027, 1, 15))

    try:
        async with AsyncSessionLocal() as db:
            applied = await service.apply_client_portfolio_manifest(
                db, manifest=manifest
            )
            assert applied["status"] == "applied"
            assert applied["summary"]["msa_status_as_of"] == "2027-01-15"
            run_ids = [applied["run_id"]]
            client_ids = list(applied["summary"]["created_client_ids"])
            scope_ids = list(applied["summary"]["scope_ids"])
            msa_ids = list(applied["summary"]["created_msa_ids"])
            await db.commit()

        async with AsyncSessionLocal() as db:
            msa = await db.get(ClientFrameworkContract, msa_ids[0])
            assert msa is not None
            assert msa.status == FrameworkContractStatus.active
    finally:
        await _delete_test_import_state(
            run_ids=run_ids,
            client_ids=client_ids,
            scope_ids=scope_ids,
            msa_ids=msa_ids,
        )
