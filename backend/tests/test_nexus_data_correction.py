"""Safety-contract tests for the manifest-driven Nexus data correction."""

from __future__ import annotations

import json
import stat
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

import app.services.nexus_data_correction as correction_service
from app.models.order_type import OrderType
from app.services import order_types as order_type_service
from app.services.nexus_data_correction import (
    ContractCorrection,
    NexusDataCorrectionError,
    NexusDataCorrectionManifest,
    _apply_contract_updates,
    _assert_postconditions,
    _contract_non_target_snapshot,
    _fetch_client_order_groups,
    _fetch_standalone_orders,
    _order_type_policy_inventory,
    approval_fingerprint,
    build_contract_deltas,
    build_nexus_data_correction_plan,
    load_nexus_data_correction_manifest,
    plan_fingerprint,
    redact_nexus_data_correction_report,
)
from scripts import correct_nexus_orders_contracts as correction_cli
from scripts.reconcile_nexus_data_correction import build_reconciliation_receipt


@pytest.fixture(autouse=True)
def _restore_correction_order_type_policy(
    monkeypatch, _detach_canonical_order_type_policy
):
    """This module validates the real pinned policy, unlike generic ID fixtures."""

    monkeypatch.setattr(
        order_type_service,
        "_PINNED_ALLOWED_ORDER_TYPES",
        {
            12: (OrderType.md,),
            18: (OrderType.md,),
            15: (OrderType.md, OrderType.cost),
            155: (OrderType.md, OrderType.cost),
        },
    )


MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "data"
    / "nexus_contract_correction_2026_08.json"
)


def test_checked_in_manifest_has_exact_source_and_purple_cell_scope():
    manifest = load_nexus_data_correction_manifest(MANIFEST)

    assert len(manifest.contracts) == 471
    assert len(set(manifest.contract_ids)) == 471
    assert manifest.source["sha256"] == (
        "5f4c38cba2ac3ba6703e66862ccc20525b400dc50f39455f3adf722ac4be8b7a"
    )
    assert sum(item.client_order_end_date_present for item in manifest.contracts) == 34
    assert sum(item.rate_client_present for item in manifest.contracts) == 30
    assert (
        sum(
            item.client_order_end_date_present or item.rate_client_present
            for item in manifest.contracts
        )
        == 58
    )
    assert manifest.clients == (
        (12, "BNP Paribas"),
        (15, "Polkomtel"),
        (18, "BIK"),
        (155, "Wedel"),
    )


@pytest.mark.asyncio
async def test_checked_in_audit_plan_executes_against_postgres_catalog():
    """Exercise the complete read-only plan with the production DB driver.

    PostgreSQL exposes ``pg_constraint.confdeltype`` as its internal ``char``
    type, which asyncpg decodes as bytes unless the catalog query casts it to
    text. Mocks that hand-build string actions cannot catch that boundary.
    """

    from app.core.database import AsyncSessionLocal

    manifest = load_nexus_data_correction_manifest(MANIFEST)
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            plan = await build_nexus_data_correction_plan(db, manifest)
        finally:
            await db.rollback()

    assert plan["summary"]["manifest_contracts"] == 471
    assert len(plan["fingerprint"]) == 64
    assert plan["live_state"]["client_order_foreign_keys"]
    assert all(
        isinstance(item["delete_action"], str)
        for item in plan["live_state"]["client_order_foreign_keys"]
    )


class _EmptyMappingsResult:
    def mappings(self):
        return self

    def all(self):
        return []


class _OrderTypeQuerySession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, params):
        self.statements.append(str(statement))
        return _EmptyMappingsResult()


class _RowsMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def _fk(
    table: str,
    column: str,
    action: str,
    *,
    schema: str = "public",
    target_schema: str = "public",
    target_column_name: str = "id",
    primary_key_columns: tuple[str, ...] = ("id",),
    column_count: int = 1,
):
    return {
        "schema_name": schema,
        "table_name": table,
        "column_name": column,
        "target_schema": target_schema,
        "target_column_name": target_column_name,
        "constraint_name": f"fk_{table}_{column}",
        "column_count": column_count,
        "delete_action": action,
        "primary_key_columns": list(primary_key_columns),
    }


@pytest.mark.asyncio
async def test_order_type_audit_fetches_complete_standalone_and_group_before_state():
    db = _OrderTypeQuerySession()

    assert await _fetch_standalone_orders(db, [12, 15, 18, 155], lock=True) == []
    assert await _fetch_client_order_groups(db, [12, 15, 18, 155], lock=True) == []

    standalone_sql, group_sql = db.statements
    assert "order_group_id IS NULL" in standalone_sql
    assert "order_type = 'periodic'" not in standalone_sql
    assert "order_type IS NULL" not in standalone_sql
    assert "FROM client_order_groups" in group_sql
    assert "FOR UPDATE OF o" in standalone_sql
    assert "FOR UPDATE OF g" in group_sql


@pytest.mark.asyncio
async def test_fk_catalog_scans_all_non_system_child_schemas():
    class Session:
        def __init__(self):
            self.statement = ""

        async def execute(self, statement):
            self.statement = str(statement)
            return _RowsMappingsResult([])

    db = Session()
    assert await correction_service._client_order_fk_catalog(db) == []
    assert "child_ns.nspname <> 'information_schema'" in db.statement
    assert "child_ns.nspname !~ '^pg_'" in db.statement
    assert "child_ns.nspname = current_schema()" not in db.statement
    assert "primary_key_columns" in db.statement
    assert "unnest(con.confkey)" in db.statement
    assert "target_column_name" in db.statement
    assert "con.confdeltype::text AS delete_action" in db.statement


def test_fk_catalog_is_fail_closed_for_schema_identifier_pk_and_action_drift():
    assert (
        correction_service._catalog_fk_issue(_fk("dl_alerts", "order_id", "n")) is None
    )
    # Reviewed CASCADE definitions are catalog-compatible; matching child rows
    # are separated into the blocking inventory below.
    assert (
        correction_service._catalog_fk_issue(
            _fk("client_order_md_consumptions", "order_id", "c")
        )
        is None
    )
    assert (
        correction_service._catalog_fk_issue(
            _fk("dl_alerts", "order_id", "n", schema="archive")
        )
        == "foreign_schema"
    )
    assert (
        correction_service._catalog_fk_issue(_fk("dl-alerts", "order_id", "n"))
        == "unsafe_identifier"
    )
    assert (
        correction_service._catalog_fk_issue(
            _fk("dl_alerts", "order_id", "n", primary_key_columns=("uuid",))
        )
        == "unexpected_primary_key"
    )
    assert (
        correction_service._catalog_fk_issue(
            _fk("dl_alerts", "order_id", "n", target_column_name="legacy_id")
        )
        == "unexpected_target_column"
    )
    assert (
        correction_service._catalog_fk_issue(_fk("dl_alerts", "order_id", "c"))
        == "unexpected_delete_action"
    )
    # Consumption rows are accounting facts: changing their FK to SET NULL
    # must never make them eligible for the reviewed preservation path.
    assert (
        correction_service._catalog_fk_issue(
            _fk("client_order_md_consumptions", "order_id", "n")
        )
        == "unexpected_delete_action"
    )
    assert (
        correction_service._catalog_fk_issue(
            _fk("client_order_invoice_consumptions", "order_id", "n")
        )
        == "unexpected_delete_action"
    )
    assert (
        correction_service._catalog_fk_issue(_fk("future_table", "order_id", "n"))
        == "unknown_foreign_key"
    )


@pytest.mark.asyncio
async def test_dependency_inventory_qualifies_identifiers_and_fingerprints_full_rows():
    before = {
        "id": 91,
        "order_id": 7,
        "status": "new",
        "payload": {"safe": "full-before-state"},
    }

    class Session:
        def __init__(self):
            self.statement = ""

        async def execute(self, statement, params):
            self.statement = str(statement)
            assert params == {"ids": [7]}
            return _RowsMappingsResult([{"row": before}])

    db = Session()
    inventory = await correction_service._dependency_inventory(
        db, [_fk("dl_alerts", "order_id", "n")], [7], lock=True
    )

    assert 'FROM "public"."dl_alerts" child' in db.statement
    assert 'child."order_id" = ANY(:ids)' in db.statement
    assert "FOR UPDATE OF child" in db.statement
    assert inventory["public.dl_alerts.order_id"]["rows"] == [before]
    changed = json.loads(json.dumps(inventory))
    changed["public.dl_alerts.order_id"]["rows"][0]["status"] = "read"
    assert plan_fingerprint({"dependencies": inventory}) != plan_fingerprint(
        {"dependencies": changed}
    )


def test_only_surviving_set_null_children_are_allowed():
    inventory = {
        "public.dl_alerts.order_id": {
            **_fk("dl_alerts", "order_id", "n"),
            "rows": [{"id": 91, "order_id": 7, "status": "new"}],
        },
        "public.client_order_md_consumptions.order_id": {
            **_fk("client_order_md_consumptions", "order_id", "c"),
            "rows": [{"id": 92, "order_id": 7, "md_reported": "1.0"}],
        },
        "public.client_orders.predecessor_order_id": {
            **_fk("client_orders", "predecessor_order_id", "n"),
            "rows": [{"id": 7, "predecessor_order_id": 7, "status": "draft"}],
        },
    }

    allowed, also_deleted, blocking = correction_service._split_deletion_dependencies(
        inventory, [7]
    )

    assert set(allowed) == {"public.dl_alerts.order_id"}
    assert set(also_deleted) == {"public.client_orders.predecessor_order_id"}
    assert set(blocking) == {"public.client_order_md_consumptions.order_id"}
    assert correction_service._dependency_row_ids(allowed) == {
        "public.dl_alerts.order_id": {7: [91]}
    }


def test_standalone_expected_state_applies_set_null_only_to_surviving_child():
    parent = {"id": 7, "order_type": "periodic", "predecessor_order_id": None}
    child = {"id": 8, "order_type": None, "predecessor_order_id": 7}
    plan = {
        "client_order_deletions": [{"order_id": 7, "client_id": 12}],
        "live_state": {
            "standalone_order_rows": [parent, child],
            "set_null_dependency_rows": {
                "public.client_orders.predecessor_order_id": {
                    **_fk("client_orders", "predecessor_order_id", "n"),
                    "rows": [child],
                }
            },
            "set_null_deleted_dependency_rows": {},
        },
    }

    assert correction_service._expected_standalone_after_order_delete(plan) == [
        {"id": 8, "order_type": None, "predecessor_order_id": None}
    ]


def test_manifest_rejects_a_sixth_contract_field(tmp_path: Path):
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["contracts"][0]["status"] = "active"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NexusDataCorrectionError, match="forbidden fields"):
        load_nexus_data_correction_manifest(tampered)


def test_manifest_rejects_contract_id_matching_scope_drift(tmp_path: Path):
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["contracts"][1]["id"] = raw["contracts"][0]["id"]
    tampered = tmp_path / "duplicate.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NexusDataCorrectionError, match="repeated"):
        load_nexus_data_correction_manifest(tampered)


def test_manifest_rejects_a_different_source_workbook_hash(tmp_path: Path):
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["source"]["sha256"] = "a" * 64
    tampered = tmp_path / "different-source.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NexusDataCorrectionError, match="sha256"):
        load_nexus_data_correction_manifest(tampered)


@pytest.mark.parametrize("mutation", ["date", "rate"])
def test_manifest_target_digest_rejects_silent_value_tampering(
    tmp_path: Path, mutation: str
):
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if mutation == "date":
        raw["contracts"][0]["start_date"] = "2099-01-01"
    else:
        rate_row = next(row for row in raw["contracts"] if "rate_client" in row)
        rate_row["rate_client"] = "0.001"
    tampered = tmp_path / f"tampered-{mutation}.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    # Declared source SHA and all row/purple counts are deliberately intact.
    with pytest.raises(NexusDataCorrectionError, match="targets digest"):
        load_nexus_data_correction_manifest(tampered)


def _manifest(*contracts: ContractCorrection) -> NexusDataCorrectionManifest:
    return NexusDataCorrectionManifest(
        contracts=contracts,
        clients=((12, "BNP Paribas"),),
        source={"sha256": "a" * 64},
        version=1,
    )


def test_optional_targets_are_changed_only_when_the_manifest_key_was_present():
    current = {
        1: {
            "id": 1,
            "contract_type": "b2b",
            "start_date": "2026-01-01",
            "end_date": None,
            "client_order_end_date": "2030-01-01",
            "rate_client": "999.000",
        },
        2: {
            "id": 2,
            "contract_type": "b2b",
            "start_date": "2026-01-01",
            "end_date": None,
            "client_order_end_date": "2030-01-01",
            "rate_client": "999.000",
        },
    }
    without_optional = ContractCorrection(
        1,
        "b2b",
        date(2026, 1, 1),
        None,
        False,
        None,
        False,
        None,
    )
    with_optional = ContractCorrection(
        2,
        "b2b",
        date(2026, 1, 1),
        None,
        True,
        date(2027, 1, 1),
        True,
        Decimal("200"),
    )

    deltas = build_contract_deltas(current, _manifest(without_optional, with_optional))

    assert [item["contract_id"] for item in deltas] == [2]
    assert [change["field"] for change in deltas[0]["changes"]] == [
        "client_order_end_date",
        "rate_client",
    ]


def test_plan_and_approval_fingerprints_are_stable_and_bind_live_before_state():
    first = {
        "mode": "audit",
        "ok": True,
        "live_state": {"contract_rows": [{"id": 1, "status": "active"}]},
        "contract_updates": [],
    }
    reordered = {
        "contract_updates": [],
        "live_state": {"contract_rows": [{"status": "active", "id": 1}]},
        "ok": False,
        "mode": "apply",
    }
    changed = {
        **first,
        "live_state": {"contract_rows": [{"id": 1, "status": "ended"}]},
    }

    fingerprint = plan_fingerprint(first)
    assert fingerprint == plan_fingerprint(reordered)
    assert fingerprint != plan_fingerprint(changed)
    assert approval_fingerprint(fingerprint) == approval_fingerprint(fingerprint)
    assert approval_fingerprint(fingerprint) != approval_fingerprint(
        plan_fingerprint(changed)
    )


def test_non_target_snapshot_keeps_audit_and_derived_fields():
    row = {
        "id": 1,
        "start_date": "2026-01-01",
        "end_date": None,
        "contract_type": "b2b",
        "client_order_end_date": None,
        "rate_client": "100.000",
        "rate_candidate": "80.000",
        "margin": "20.000",
        "status": "active",
        "updated_at": "2026-08-29T01:02:03+00:00",
    }

    snapshot = _contract_non_target_snapshot(
        row, ("contract_type", "start_date", "end_date")
    )

    assert "start_date" not in snapshot
    assert snapshot["client_order_end_date"] is None
    assert snapshot["rate_client"] == "100.000"
    assert snapshot["rate_candidate"] == "80.000"
    assert snapshot["margin"] == "20.000"
    assert snapshot["status"] == "active"
    assert snapshot["updated_at"] == "2026-08-29T01:02:03+00:00"


def test_type_policy_deletes_only_explicit_periodic_and_preserves_legacy_null():
    inventory = _order_type_policy_inventory(
        [
            {"id": 1, "client_id": 12, "order_type": None},
            {"id": 2, "client_id": 12, "order_type": "periodic"},
            {"id": 3, "client_id": 12, "order_type": "cost"},
            {"id": 4, "client_id": 15, "order_type": "cost"},
            {"id": 5, "client_id": 155, "order_type": None},
        ],
        [
            {
                "id": 10,
                "client_id": 12,
                "order_type": None,
                "is_cost_based": False,
            },
            {
                "id": 11,
                "client_id": 12,
                "order_type": None,
                "is_cost_based": True,
            },
            {
                "id": 12,
                "client_id": 15,
                "order_type": "cost",
                "is_cost_based": True,
            },
        ],
    )

    assert [row["id"] for row in inventory["periodic_orders"]] == [2]
    assert [row["id"] for row in inventory["legacy_null_orders"]] == [1, 5]
    assert inventory["disallowed_orders"] == [
        {"order_id": 3, "client_id": 12, "effective_type": "cost"}
    ]
    assert inventory["disallowed_groups"] == [
        {"group_id": 11, "client_id": 12, "effective_type": "cost"}
    ]


def test_correction_detects_runtime_order_type_policy_drift(monkeypatch):
    monkeypatch.setattr(order_type_service, "_PINNED_ALLOWED_ORDER_TYPES", {})

    assert correction_service._runtime_order_type_policy_drift() == [
        {"client_id": 12},
        {"client_id": 15},
        {"client_id": 18},
        {"client_id": 155},
    ]


@pytest.mark.asyncio
async def test_plan_blocks_disallowed_standalone_and_group_types(monkeypatch):
    manifest = _manifest(
        ContractCorrection(
            1,
            "b2b",
            date(2026, 1, 1),
            None,
            False,
            None,
            False,
            None,
        )
    )
    contract_row = {
        "id": 1,
        "contract_type": "b2b",
        "start_date": "2026-01-01",
        "end_date": None,
    }
    monkeypatch.setattr(
        correction_service,
        "_fetch_contracts",
        AsyncMock(return_value={1: contract_row}),
    )
    monkeypatch.setattr(
        correction_service,
        "_fetch_clients",
        AsyncMock(return_value=[{"id": 12, "name": "BNP Paribas"}]),
    )
    monkeypatch.setattr(
        correction_service, "_fetch_rate_schedule_rows", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        correction_service, "_client_order_fk_catalog", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        correction_service,
        "_fetch_standalone_orders",
        AsyncMock(
            return_value=[
                {
                    "id": 2,
                    "client_id": 12,
                    "order_type": "cost",
                    "status": "draft",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        correction_service,
        "_fetch_client_order_groups",
        AsyncMock(
            return_value=[
                {
                    "id": 3,
                    "client_id": 12,
                    "order_type": None,
                    "is_cost_based": True,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        correction_service, "_dependency_inventory", AsyncMock(return_value={})
    )

    plan = await build_nexus_data_correction_plan(
        db=SimpleNamespace(), manifest=manifest
    )

    assert plan["ok"] is False
    assert {item["code"] for item in plan["blockers"]} == {
        "disallowed_client_order_type",
        "disallowed_client_order_group_type",
    }


@pytest.mark.asyncio
async def test_plan_allows_set_null_rows_but_blocks_cascade_rows(monkeypatch):
    manifest = _manifest(
        ContractCorrection(
            1,
            "b2b",
            date(2026, 1, 1),
            None,
            False,
            None,
            False,
            None,
        )
    )
    contract_row = {
        "id": 1,
        "contract_type": "b2b",
        "start_date": "2026-01-01",
        "end_date": None,
    }
    periodic = {
        "id": 7,
        "client_id": 12,
        "order_type": "periodic",
        "status": "draft",
    }
    monkeypatch.setattr(
        correction_service,
        "_fetch_contracts",
        AsyncMock(return_value={1: contract_row}),
    )
    monkeypatch.setattr(
        correction_service,
        "_fetch_clients",
        AsyncMock(return_value=[{"id": 12, "name": "BNP Paribas"}]),
    )
    monkeypatch.setattr(
        correction_service, "_fetch_rate_schedule_rows", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        correction_service, "_client_order_fk_catalog", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        correction_service,
        "_fetch_standalone_orders",
        AsyncMock(return_value=[periodic]),
    )
    monkeypatch.setattr(
        correction_service, "_fetch_client_order_groups", AsyncMock(return_value=[])
    )

    set_null_entry = {
        **_fk("dl_alerts", "order_id", "n"),
        "rows": [{"id": 91, "order_id": 7, "status": "new"}],
    }
    cascade_entry = {
        **_fk("client_order_md_consumptions", "order_id", "c"),
        "rows": [{"id": 92, "order_id": 7, "md_reported": "1.0"}],
    }
    also_deleted_entry = {
        **_fk("client_orders", "predecessor_order_id", "n"),
        "rows": [{**periodic, "predecessor_order_id": 7}],
    }
    dependencies = AsyncMock(
        side_effect=[
            {
                "public.dl_alerts.order_id": set_null_entry,
                "public.client_orders.predecessor_order_id": also_deleted_entry,
            },
            {},
            {
                "public.dl_alerts.order_id": set_null_entry,
                "public.client_orders.predecessor_order_id": also_deleted_entry,
                "public.client_order_md_consumptions.order_id": cascade_entry,
            },
            {},
        ]
    )
    monkeypatch.setattr(correction_service, "_dependency_inventory", dependencies)

    allowed = await build_nexus_data_correction_plan(
        db=SimpleNamespace(), manifest=manifest
    )
    assert allowed["ok"] is True
    assert allowed["summary"]["set_null_dependency_rows"] == 1
    assert allowed["summary"]["set_null_deleted_dependency_rows"] == 1
    assert allowed["summary"]["dependency_rows"] == 0
    assert set(allowed["live_state"]["set_null_dependency_rows"]) == {
        "public.dl_alerts.order_id"
    }
    assert set(allowed["live_state"]["set_null_deleted_dependency_rows"]) == {
        "public.client_orders.predecessor_order_id"
    }

    blocked = await build_nexus_data_correction_plan(
        db=SimpleNamespace(), manifest=manifest
    )
    assert blocked["ok"] is False
    assert blocked["summary"]["set_null_dependency_rows"] == 1
    assert blocked["summary"]["set_null_deleted_dependency_rows"] == 1
    assert blocked["summary"]["dependency_rows"] == 1
    dependency_blocker = next(
        item
        for item in blocked["blockers"]
        if item["code"] == "client_order_dependencies"
    )
    assert dependency_blocker["dependencies"] == {
        "public.client_order_md_consumptions.order_id": {7: [92]}
    }


@pytest.mark.asyncio
async def test_postcondition_preserves_legacy_null_and_non_target_order_rows(
    monkeypatch,
):
    target = ContractCorrection(
        1,
        "b2b",
        date(2026, 1, 1),
        None,
        False,
        None,
        False,
        None,
    )
    manifest = _manifest(target)
    contract_row = {
        "id": 1,
        "contract_type": "b2b",
        "start_date": "2026-01-01",
        "end_date": None,
    }
    legacy_null = {
        "id": 2,
        "client_id": 12,
        "order_type": None,
        "status": "draft",
    }
    deleted_periodic = {
        "id": 3,
        "client_id": 12,
        "order_type": "periodic",
        "status": "draft",
    }
    group = {
        "id": 4,
        "client_id": 12,
        "order_type": None,
        "is_cost_based": False,
    }
    plan = {
        "live_state": {
            "contract_rows": [contract_row],
            "standalone_order_rows": [legacy_null, deleted_periodic],
            "client_order_group_rows": [group],
        },
        "client_order_deletions": [{"order_id": 3, "client_id": 12}],
    }
    monkeypatch.setattr(
        correction_service,
        "_fetch_contracts",
        AsyncMock(return_value={1: contract_row}),
    )
    preserved_orders = AsyncMock(return_value=[legacy_null])
    monkeypatch.setattr(
        correction_service, "_fetch_standalone_orders", preserved_orders
    )
    monkeypatch.setattr(
        correction_service,
        "_fetch_client_order_groups",
        AsyncMock(return_value=[group]),
    )
    monkeypatch.setattr(
        correction_service,
        "_fetch_clients",
        AsyncMock(return_value=[{"id": 12, "name": "BNP Paribas"}]),
    )
    monkeypatch.setattr(
        correction_service, "_fetch_rate_schedule_rows", AsyncMock(return_value=[])
    )

    await _assert_postconditions(SimpleNamespace(), manifest, plan)

    preserved_orders.return_value = []
    with pytest.raises(NexusDataCorrectionError, match="preservation"):
        await _assert_postconditions(SimpleNamespace(), manifest, plan)


@pytest.mark.asyncio
async def test_set_null_postcondition_requires_same_pk_null_fk_and_same_before_state():
    entry = {
        **_fk("dl_alerts", "order_id", "n"),
        "rows": [
            {
                "id": 91,
                "order_id": 7,
                "status": "new",
                "payload": {"kind": "order-ending"},
            }
        ],
    }

    class Session:
        def __init__(self, row):
            self.row = row

        async def execute(self, statement, params):
            assert 'FROM "public"."dl_alerts" child' in str(statement)
            assert params == {"ids": [91]}
            rows = [] if self.row is None else [{"row": self.row}]
            return _RowsMappingsResult(rows)

    after = {
        "id": 91,
        "order_id": None,
        "status": "new",
        "payload": {"kind": "order-ending"},
    }
    await correction_service._assert_set_null_dependency_postconditions(
        Session(after), {"public.dl_alerts.order_id": entry}
    )

    with pytest.raises(NexusDataCorrectionError, match="preservation"):
        await correction_service._assert_set_null_dependency_postconditions(
            Session(None), {"public.dl_alerts.order_id": entry}
        )

    changed = {**after, "status": "read"}
    with pytest.raises(NexusDataCorrectionError, match="state changed"):
        await correction_service._assert_set_null_dependency_postconditions(
            Session(changed), {"public.dl_alerts.order_id": entry}
        )


@pytest.mark.asyncio
async def test_also_deleted_self_fk_postcondition_requires_exact_pk_absence():
    entry = {
        **_fk("client_orders", "predecessor_order_id", "n"),
        "rows": [{"id": 7, "predecessor_order_id": 7, "status": "draft"}],
    }

    class Session:
        def __init__(self, remaining: int):
            self.remaining = remaining

        async def scalar(self, statement, params):
            assert 'FROM "public"."client_orders" child' in str(statement)
            assert params == {"ids": [7]}
            return self.remaining

    await correction_service._assert_deleted_dependency_postconditions(
        Session(0), {"public.client_orders.predecessor_order_id": entry}
    )
    with pytest.raises(NexusDataCorrectionError, match="self-FK"):
        await correction_service._assert_deleted_dependency_postconditions(
            Session(1), {"public.client_orders.predecessor_order_id": entry}
        )


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, params):
        self.statements.append(str(statement))
        return SimpleNamespace(rowcount=1)


class _ApplySession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return SimpleNamespace(rowcount=0)

    async def scalar(self, statement, params=None):
        self.statements.append(str(statement))
        if "pg_namespace" in str(statement):
            return "public"
        return True


@pytest.mark.asyncio
async def test_apply_locks_order_groups_before_rebuilding_plan(monkeypatch):
    fingerprint = "f" * 64
    approved = approval_fingerprint(fingerprint)
    plan = {
        "fingerprint": fingerprint,
        "approval_fingerprint": approved,
        "blockers": [],
        "contract_updates": [],
        "client_order_deletions": [],
    }
    monkeypatch.setattr(
        correction_service,
        "build_nexus_data_correction_plan",
        AsyncMock(return_value=plan),
    )
    monkeypatch.setattr(
        correction_service, "_apply_contract_updates", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(correction_service, "_assert_postconditions", AsyncMock())
    db = _ApplySession()

    await correction_service.apply_nexus_data_correction_plan(
        db,
        SimpleNamespace(clients=((12, "BNP Paribas"),)),
        expected_fingerprint=fingerprint,
        expected_approval_fingerprint=approved,
    )

    lock_statement = next(
        statement for statement in db.statements if statement.startswith("LOCK TABLE")
    )
    search_path_statement = next(
        statement
        for statement in db.statements
        if statement.startswith("SET LOCAL search_path")
    )
    assert search_path_statement == (
        'SET LOCAL search_path TO pg_catalog, "public", pg_temp'
    )
    assert db.statements.index(search_path_statement) < db.statements.index(
        lock_statement
    )
    assert '"public"."client_order_groups"' in lock_statement
    assert '"public"."dl_alerts"' in lock_statement


@pytest.mark.asyncio
async def test_raw_contract_update_has_a_closed_scope_and_no_updated_at():
    db = _RecordingSession()
    updates = [
        {
            "contract_id": 10,
            "changes": [
                {"field": "start_date", "before": None, "after": date(2026, 1, 1)},
                {"field": "rate_client", "before": None, "after": Decimal("200")},
            ],
        }
    ]

    assert await _apply_contract_updates(db, updates) == 1
    sql = db.statements[0]
    assert "start_date = CAST(:v_start_date AS date)" in sql
    assert "rate_client = CAST(:v_rate_client AS numeric(12,3))" in sql
    assert "updated_at" not in sql
    assert "margin" not in sql

    unsafe = [
        {
            "contract_id": 10,
            "changes": [{"field": "status", "before": "draft", "after": "active"}],
        }
    ]
    with pytest.raises(NexusDataCorrectionError, match="unsafe"):
        await _apply_contract_updates(db, unsafe)


def test_redacted_report_has_only_ids_field_names_counts_and_safe_order_flags():
    report = {
        "mode": "audit",
        "ok": False,
        "fingerprint": "f" * 64,
        "approval_fingerprint": "a" * 64,
        "summary": {"contracts_with_changes": 1, "periodic_orders_to_delete": 1},
        "manifest": {
            "clients": [{"id": 12, "name": "BNP Paribas"}],
            "contract_targets": [{"id": 1, "rate_client": "123.000"}],
        },
        "contract_updates": [
            {
                "contract_id": 1,
                "changes": [{"field": "rate_client", "before": "999", "after": "123"}],
            }
        ],
        "live_state": {
            "periodic_order_rows": [
                {
                    "id": 7,
                    "client_id": 12,
                    "status": "draft",
                    "title": "Candidate Person",
                    "file_path": "/secret/order.pdf",
                }
            ],
            "dependency_row_ids": {
                "public.client_order_md_consumptions.order_id": {7: [10, 11]},
            },
            "set_null_dependency_row_ids": {
                "public.dl_alerts.order_id": {7: [13]},
            },
            "set_null_dependency_rows": {
                "public.dl_alerts.order_id": {
                    "schema_name": "public",
                    "table_name": "dl_alerts",
                    "column_name": "order_id",
                    "delete_action": "n",
                    "primary_key_columns": ["id"],
                    "rows": [
                        {
                            "id": 13,
                            "order_id": 7,
                            "message": "Secret candidate dependency message",
                        }
                    ],
                }
            },
            "legacy_null_order_rows": [
                {
                    "id": 8,
                    "client_id": 15,
                    "status": "active",
                    "order_type": None,
                    "title": "Legacy Person",
                    "file_path": None,
                }
            ],
            "legacy_null_dependency_row_ids": {
                "public.dl_alerts.order_id": {8: [12]},
            },
        },
        "blockers": [
            {
                "code": "client_order_dependencies",
                "dependencies": {
                    "public.client_order_md_consumptions.order_id": {7: [10, 11]}
                },
            },
            {"code": "client_order_file_evidence", "order_ids": [7]},
            {
                "code": "disallowed_client_order_group_type",
                "group_id": 9,
                "client_id": 12,
                "effective_type": "cost",
            },
        ],
    }

    redacted = redact_nexus_data_correction_report(report)
    encoded = json.dumps(redacted, ensure_ascii=False)

    assert set(redacted) == {
        "mode",
        "ok",
        "fingerprint",
        "summary",
        "contracts",
        "orders",
        "legacy_null_orders",
        "blockers",
    }
    assert redacted["contracts"] == [{"id": 1, "changed_fields": ["rate_client"]}]
    assert redacted["summary"]["approval_fingerprint"] == "a" * 64
    assert redacted["orders"] == [
        {
            "id": 7,
            "client_id": 12,
            "status": "draft",
            "dependency_counts": {"public.client_order_md_consumptions.order_id": 2},
            "set_null_dependency_counts": {"public.dl_alerts.order_id": 1},
            "set_null_deleted_dependency_counts": {},
            "has_file": True,
        }
    ]
    assert redacted["legacy_null_orders"] == [
        {
            "id": 8,
            "client_id": 15,
            "status": "active",
            "dependency_counts": {"public.dl_alerts.order_id": 1},
            "has_file": False,
        }
    ]
    assert {
        "code": "client_order_dependencies",
        "order_id": 7,
        "schema": "public",
        "table": "client_order_md_consumptions",
        "column": "order_id",
    } in redacted["blockers"]
    assert {
        "code": "disallowed_client_order_group_type",
        "group_id": 9,
        "client_id": 12,
        "effective_type": "cost",
    } in redacted["blockers"]
    assert "Candidate Person" not in encoded
    assert "Legacy Person" not in encoded
    assert "Secret candidate dependency message" not in encoded
    assert "BNP Paribas" not in encoded
    assert "123" not in encoded
    assert "/secret" not in encoded
    assert "approval_fingerprint" not in set(redacted)


def test_cli_writes_both_reports_and_returns_blocked_exit_code(
    monkeypatch, tmp_path: Path, capsys
):
    full_output = tmp_path / "full.json"
    redacted_output = tmp_path / "redacted.json"
    args = SimpleNamespace(
        mode="audit",
        manifest=MANIFEST,
        output=full_output,
        redacted_output=redacted_output,
        intent_output=None,
        fingerprint=None,
        approval_fingerprint=None,
    )
    report = {
        "mode": "audit",
        "ok": False,
        "fingerprint": "f" * 64,
        "summary": {"blockers": 2},
        "contract_updates": [],
        "live_state": {},
        "blockers": [
            {"code": "missing_contracts", "contract_ids": [1, 2]},
        ],
    }

    async def fake_run(_args):
        return report

    monkeypatch.setattr(
        correction_cli,
        "_parser",
        lambda: SimpleNamespace(parse_args=lambda: args),
    )
    monkeypatch.setattr(correction_cli, "_run", fake_run)

    assert correction_cli.main() == 2
    assert json.loads(full_output.read_text(encoding="utf-8")) == report
    redacted = json.loads(redacted_output.read_text(encoding="utf-8"))
    assert redacted["ok"] is False
    assert redacted["blockers"] == [
        {"code": "missing_contracts", "contract_id": 1},
        {"code": "missing_contracts", "contract_id": 2},
    ]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "audit blocked" in captured.err


class _CliSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_cli_audit_uses_one_read_only_snapshot_without_intent(monkeypatch):
    events: list[str] = []

    class Db:
        async def execute(self, statement):
            events.append(str(statement))

        async def rollback(self):
            events.append("rollback")

    args = SimpleNamespace(
        mode="audit",
        manifest=MANIFEST,
        output=Path("unused"),
        redacted_output=None,
        intent_output=None,
        fingerprint=None,
        approval_fingerprint=None,
    )
    report = {"mode": "audit", "ok": True}
    monkeypatch.setattr(
        correction_cli, "load_nexus_data_correction_manifest", lambda _path: object()
    )
    monkeypatch.setattr(
        correction_cli,
        "AsyncSessionLocal",
        lambda: _CliSessionContext(Db()),
    )
    monkeypatch.setattr(
        correction_cli,
        "build_nexus_data_correction_plan",
        AsyncMock(return_value=report),
    )

    assert await correction_cli._run(args) == report
    assert events == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "rollback",
    ]


@pytest.mark.asyncio
async def test_cli_fsyncs_redacted_intent_before_apply_commit(monkeypatch, tmp_path):
    intent_output = tmp_path / "intent.json"
    events: list[str] = []

    class Db:
        async def commit(self):
            assert intent_output.is_file()
            assert json.loads(intent_output.read_text(encoding="utf-8"))["ok"] is True
            events.append("commit")

        async def rollback(self):
            events.append("rollback")

    fingerprint = "f" * 64
    approved = approval_fingerprint(fingerprint)
    report = {
        "mode": "apply",
        "ok": True,
        "fingerprint": fingerprint,
        "approval_fingerprint": approved,
        "summary": {"blockers": 0},
        "contract_updates": [],
        "live_state": {},
        "blockers": [],
    }
    args = SimpleNamespace(
        mode="apply",
        manifest=MANIFEST,
        output=tmp_path / "unused.json",
        redacted_output=None,
        intent_output=intent_output,
        fingerprint=fingerprint,
        approval_fingerprint=approved,
    )
    monkeypatch.setattr(
        correction_cli, "load_nexus_data_correction_manifest", lambda _path: object()
    )
    monkeypatch.setattr(
        correction_cli,
        "AsyncSessionLocal",
        lambda: _CliSessionContext(Db()),
    )
    monkeypatch.setattr(
        correction_cli,
        "apply_nexus_data_correction_plan",
        AsyncMock(return_value=report),
    )

    assert await correction_cli._run(args) == report
    assert events == ["commit"]


def test_cli_atomic_json_fsyncs_file_and_parent_directory(monkeypatch, tmp_path):
    real_fsync = correction_cli.os.fsync
    fsync_targets: list[str] = []

    def recording_fsync(fd: int):
        mode = correction_cli.os.fstat(fd).st_mode
        fsync_targets.append("directory" if stat.S_ISDIR(mode) else "file")
        return real_fsync(fd)

    monkeypatch.setattr(correction_cli.os, "fsync", recording_fsync)
    output = tmp_path / "atomic.json"

    correction_cli._write_json(output, {"ok": True})

    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    assert fsync_targets == ["file", "directory"]


def _redacted_reconciliation_report(
    mode: str, fingerprint: str, *, contract_changes: int = 0
) -> dict:
    return {
        "mode": mode,
        "ok": True,
        "fingerprint": fingerprint,
        "summary": {
            "contracts_with_changes": contract_changes,
            "periodic_orders_to_delete": 0,
            "disallowed_standalone_order_types": 0,
            "disallowed_group_order_types": 0,
            "blockers": 0,
        },
        "contracts": (
            [{"id": 1, "changed_fields": ["start_date"]}] if contract_changes else []
        ),
        "orders": [],
        "legacy_null_orders": [],
        "blockers": [],
    }


def test_reconciliation_recovers_a_commit_when_normal_report_was_lost():
    plan_fingerprint = "f" * 64
    post_fingerprint = "e" * 64
    intent = _redacted_reconciliation_report("apply", plan_fingerprint)
    post_audit = _redacted_reconciliation_report("audit", post_fingerprint)

    receipt, verified = build_reconciliation_receipt(
        intent=intent,
        apply_report=None,
        post_audit_report=post_audit,
        plan_fingerprint=plan_fingerprint,
        apply_exit_code=1,
        post_audit_exit_code=0,
    )

    assert verified is True
    assert receipt["ok"] is True
    assert receipt["reconciliation"] == {
        "status": "verified_after_cli_failure",
        "precommit_intent": True,
        "apply_report_present": False,
        "apply_report_matches_intent": False,
        "apply_exit_code": 1,
        "post_apply_audit_exit_code": 0,
        "post_apply_fingerprint": post_fingerprint,
        "desired_state_verified": True,
    }


def test_reconciliation_fails_closed_without_intent_or_with_post_apply_drift():
    plan_fingerprint = "f" * 64
    clean_post = _redacted_reconciliation_report("audit", "e" * 64)
    no_intent, no_intent_verified = build_reconciliation_receipt(
        intent=None,
        apply_report=None,
        post_audit_report=clean_post,
        plan_fingerprint=plan_fingerprint,
        apply_exit_code=1,
        post_audit_exit_code=0,
    )
    assert no_intent_verified is False
    assert no_intent["reconciliation"]["status"] == "not_committed"

    intent = _redacted_reconciliation_report("apply", plan_fingerprint)
    drifted_post = _redacted_reconciliation_report(
        "audit", "d" * 64, contract_changes=1
    )
    drifted, drifted_verified = build_reconciliation_receipt(
        intent=intent,
        apply_report=intent,
        post_audit_report=drifted_post,
        plan_fingerprint=plan_fingerprint,
        apply_exit_code=0,
        post_audit_exit_code=0,
    )
    assert drifted_verified is False
    assert drifted["ok"] is False
    assert drifted["reconciliation"]["status"] == "verification_failed"

    mismatched_report = _redacted_reconciliation_report("apply", plan_fingerprint)
    mismatched_report["legacy_null_orders"] = [
        {
            "id": 99,
            "client_id": 12,
            "status": "draft",
            "dependency_counts": {},
            "has_file": False,
        }
    ]
    mismatched, mismatched_verified = build_reconciliation_receipt(
        intent=intent,
        apply_report=mismatched_report,
        post_audit_report=clean_post,
        plan_fingerprint=plan_fingerprint,
        apply_exit_code=0,
        post_audit_exit_code=0,
    )
    assert mismatched_verified is False
    assert mismatched["reconciliation"]["apply_report_matches_intent"] is False
