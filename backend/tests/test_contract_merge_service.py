"""Safety-contract tests for the one-off duplicate-contract merge engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.contract_merge import (
    ContractMergeManifest,
    ContractMergeError,
    _assert_rate_sources_match_metadata,
    _financial_metadata_plan,
    _rate_snapshot,
    _rate_timeline_plan,
    _explicit_historical_reference_blocker,
    _replace_contract_link,
    _resolve_field_decisions,
    _resolvable_merge_blocker_codes,
    _same_day_schedule_conflicts,
    _snapshot_for_source,
    _validate_decision,
    _validate_financial_metadata_decision,
    approval_fingerprint,
    choose_survivor,
    load_contract_merge_manifest,
    merge_field_plan,
    parse_field_source_map,
    parse_rate_source_map,
    plan_fingerprint,
    redact_contract_merge_report,
    resolve_current_client_order,
)


@dataclass
class _Order:
    id: int
    status: str
    start_date: date | None
    end_date: date | None


def test_current_order_resolver_uses_only_active_covering_business_day():
    orders = [
        _Order(1, "completed", date(2026, 1, 1), date(2026, 6, 30)),
        _Order(2, "active", date(2026, 7, 1), date(2026, 9, 30)),
        _Order(3, "active", date(2026, 10, 1), date(2026, 12, 31)),
        _Order(4, "paused", date(2026, 7, 1), date(2026, 9, 30)),
    ]

    resolution = resolve_current_client_order(orders, today=date(2026, 8, 26))

    assert resolution.order is orders[1]
    assert resolution.overlapping_orders == ()
    assert resolution.needs_manual_verification is False


def test_current_order_resolver_never_guesses_between_overlaps():
    orders = [
        {
            "id": 10,
            "status": "active",
            "start_date": "2026-07-01",
            "end_date": "2026-09-30",
        },
        {"id": 11, "status": "active", "start_date": "2026-08-01", "end_date": None},
    ]

    resolution = resolve_current_client_order(orders, today=date(2026, 8, 26))

    assert resolution.order is None
    assert [row["id"] for row in resolution.overlapping_orders] == [10, 11]
    assert resolution.needs_manual_verification is True


def test_active_order_without_start_date_is_not_treated_as_current():
    resolution = resolve_current_client_order(
        [
            {
                "id": 12,
                "status": "active",
                "start_date": None,
                "end_date": "2026-09-30",
            }
        ],
        today=date(2026, 8, 26),
    )
    assert resolution.order is None
    assert resolution.needs_manual_verification is False


def test_survivor_never_replaces_live_contract_with_draft_having_an_order():
    contracts = [
        {"id": 100, "status": "active", "project_name": "filled"},
        {"id": 101, "status": "draft", "project_name": None},
    ]
    evidence = {
        100: {"current_orders": 0, "completed_signatures": 4, "documents": 5},
        101: {"current_orders": 1, "completed_signatures": 0, "documents": 0},
    }
    assert choose_survivor(contracts, evidence) == 100

    contracts[1]["status"] = "active"
    evidence[100]["current_orders"] = 1
    assert choose_survivor(contracts, evidence) == 100


def test_field_merge_is_additive_and_reports_two_nonempty_values():
    contracts = [
        {"id": 20, "project_name": None, "line_manager": "A"},
        {"id": 21, "project_name": "Phoenix", "line_manager": "B"},
    ]
    updates, conflicts = merge_field_plan(contracts, 20)

    assert updates["project_name"] == "Phoenix"
    assert "line_manager" not in updates
    assert [item["field"] for item in conflicts] == ["line_manager"]


def test_field_merge_resolves_period_bounds_but_not_other_nonempty_conflicts():
    contracts = [
        {
            "id": 20,
            "start_date": date(2026, 8, 1),
            "end_date": date(2026, 9, 30),
            "line_manager": "A",
        },
        {
            "id": 21,
            "start_date": date(2026, 7, 1),
            "end_date": date(2026, 12, 31),
            "line_manager": "B",
        },
    ]
    updates, conflicts = merge_field_plan(contracts, 20)

    assert updates["start_date"] == date(2026, 7, 1)
    assert updates["end_date"] == date(2026, 12, 31)
    assert [item["field"] for item in conflicts] == ["line_manager"]


def test_effective_rate_uses_latest_schedule_step():
    contract = {
        "id": 7,
        "rate_candidate": Decimal("900"),
        "rate_unit": "hourly",
        "currency": "PLN",
        "billing_hours_per_month": 160,
    }
    schedule = [
        {
            "id": 1,
            "contract_id": 7,
            "rate": Decimal("100"),
            "effective_from": date(2026, 1, 1),
        },
        {
            "id": 2,
            "contract_id": 7,
            "rate": Decimal("120"),
            "effective_from": date(2026, 7, 1),
        },
        {
            "id": 3,
            "contract_id": 7,
            "rate": Decimal("150"),
            "effective_from": date(2027, 1, 1),
        },
    ]
    snapshot = _rate_snapshot(contract, schedule, "candidate", date(2026, 8, 26))
    assert snapshot["rate"] == "120"
    assert snapshot["schedule_id"] == 2

    same_day = _same_day_schedule_conflicts(
        [
            {
                "id": 1,
                "contract_id": 7,
                "effective_from": "2026-09-01",
                "rate": "100",
            },
            {
                "id": 2,
                "contract_id": 7,
                "effective_from": "2026-09-01",
                "rate": "101",
            },
        ]
    )
    assert len(same_day) == 1


def test_rate_snapshot_uses_currency_of_the_selected_rate_side():
    contract = {
        "id": 8,
        "rate_candidate": Decimal("100"),
        "rate_client": Decimal("150"),
        "framework_rate": Decimal("120"),
        "rate_unit": "hourly",
        "currency": "EUR",
        "rate_client_currency": "EUR",
        "rate_candidate_currency": "PLN",
        "billing_hours_per_month": 160,
    }

    assert (
        _rate_snapshot(contract, [], "client", date(2026, 8, 26))["currency"] == "EUR"
    )
    assert (
        _rate_snapshot(contract, [], "candidate", date(2026, 8, 26))["currency"]
        == "PLN"
    )
    assert (
        _rate_snapshot(contract, [], "framework", date(2026, 8, 26))["currency"]
        == "PLN"
    )


def test_rate_timeline_treats_equal_amounts_in_different_currencies_as_conflict():
    contracts = [
        {
            "id": 8,
            "rate_client": Decimal("100"),
            "rate_unit": "hourly",
            "currency": "EUR",
            "rate_client_currency": "EUR",
            "billing_hours_per_month": 160,
        },
        {
            "id": 9,
            "rate_client": Decimal("100"),
            "rate_unit": "hourly",
            "currency": "PLN",
            "rate_client_currency": "PLN",
            "billing_hours_per_month": 160,
        },
    ]

    plan = _rate_timeline_plan(contracts, [], "client", date(2026, 8, 26))

    assert plan["current_value_conflict"] is True
    assert plan["conflict"] is True
    assert plan["single_source_contract_id"] is None
    assert plan["available_source_contract_ids"] == [8, 9]


def test_effective_rate_future_only_uses_earliest_future_and_highest_id_tie():
    contract = {
        "id": 9,
        "rate_candidate": Decimal("999"),
        "rate_unit": "hourly",
        "currency": "PLN",
        "billing_hours_per_month": 160,
    }
    schedule = [
        {
            "id": 5,
            "contract_id": 9,
            "rate": Decimal("120"),
            "effective_from": date(2026, 10, 1),
        },
        {
            "id": 6,
            "contract_id": 9,
            "rate": Decimal("125"),
            "effective_from": date(2026, 10, 1),
        },
        {
            "id": 7,
            "contract_id": 9,
            "rate": Decimal("150"),
            "effective_from": date(2027, 1, 1),
        },
    ]

    snapshot = _rate_snapshot(contract, schedule, "candidate", date(2026, 8, 26))

    assert snapshot["rate"] == "125"
    assert snapshot["schedule_id"] == 6


def test_timeline_separates_current_value_from_schedule_conflict():
    contracts = [
        {
            "id": 1,
            "rate_candidate": Decimal("100"),
            "rate_unit": "hourly",
            "currency": "PLN",
            "billing_hours_per_month": 160,
        },
        {
            "id": 2,
            "rate_candidate": Decimal("100"),
            "rate_unit": "hourly",
            "currency": "PLN",
            "billing_hours_per_month": 160,
        },
    ]
    schedule = [
        {
            "id": 10,
            "contract_id": 1,
            "effective_from": date(2026, 1, 1),
            "rate": Decimal("100"),
        },
        {
            "id": 11,
            "contract_id": 2,
            "effective_from": date(2026, 1, 1),
            "rate": Decimal("100"),
        },
        {
            "id": 12,
            "contract_id": 1,
            "effective_from": date(2027, 1, 1),
            "rate": Decimal("120"),
        },
        {
            "id": 13,
            "contract_id": 2,
            "effective_from": date(2027, 1, 1),
            "rate": Decimal("130"),
        },
    ]
    plan = _rate_timeline_plan(contracts, schedule, "candidate", date(2026, 8, 26))

    assert plan["current_value_conflict"] is False
    assert plan["schedule_conflict"] is True
    assert plan["schedule_conflict_scopes"] == ["future"]
    assert plan["conflict"] is True
    assert plan["schedule_divergence"]


def test_timeline_current_cache_conflict_is_not_a_schedule_conflict():
    contracts = [
        {
            "id": 1,
            "rate_candidate": Decimal("100"),
            "rate_unit": "hourly",
            "currency": "PLN",
            "billing_hours_per_month": 160,
        },
        {
            "id": 2,
            "rate_candidate": Decimal("110"),
            "rate_unit": "hourly",
            "currency": "PLN",
            "billing_hours_per_month": 160,
        },
    ]

    plan = _rate_timeline_plan(contracts, [], "candidate", date(2026, 8, 26))

    assert plan["current_value_conflict"] is True
    assert plan["schedule_conflict"] is False
    assert plan["schedule_conflict_scopes"] == []
    assert plan["conflict"] is True


def test_financial_metadata_separates_rate_empty_conflict_and_coalesces_safe_values():
    today = date(2026, 8, 26)
    contracts = [
        {
            "id": 1,
            "rate_candidate": Decimal("100"),
            "rate_client": Decimal("150"),
            "framework_rate": Decimal("160"),
            "rate_unit": "hourly",
            "currency": None,
            "billing_hours_per_month": 160,
        },
        {
            "id": 2,
            "rate_candidate": None,
            "rate_client": None,
            "framework_rate": None,
            "rate_unit": "monthly",
            "currency": "PLN",
            "billing_hours_per_month": 160,
        },
    ]
    plans = [
        _rate_timeline_plan(contracts, [], kind, today)
        for kind in ("candidate", "client", "framework")
    ]

    metadata = _financial_metadata_plan(contracts, plans)

    assert all(plan["conflict"] is False for plan in plans)
    assert metadata["conflict"] is False
    assert metadata["rate_empty_metadata_conflict"] is True
    assert metadata["rate_empty_metadata_conflict_fields"] == ["rate_unit"]
    assert metadata["rate_bearing_contract_ids"] == [1]
    assert metadata["rate_empty_contract_ids"] == [2]
    assert metadata["single_source_contract_id"] == 1
    assert metadata["resolved_metadata"] == {
        "rate_unit": "hourly",
        "billing_hours_per_month": 160,
    }


def test_financial_metadata_reports_only_different_nonempty_rate_bearing_values():
    today = date(2026, 8, 26)
    contracts = [
        {
            "id": 1,
            "rate_candidate": Decimal("100"),
            "rate_client": None,
            "framework_rate": None,
            "rate_unit": "hourly",
            "currency": None,
            "billing_hours_per_month": 160,
        },
        {
            "id": 2,
            "rate_candidate": Decimal("100"),
            "rate_client": None,
            "framework_rate": None,
            "rate_unit": "monthly",
            "currency": "PLN",
            "billing_hours_per_month": 160,
        },
    ]
    plans = [
        _rate_timeline_plan(contracts, [], kind, today)
        for kind in ("candidate", "client", "framework")
    ]

    metadata = _financial_metadata_plan(contracts, plans)

    assert all(plan["conflict"] is False for plan in plans)
    assert metadata["conflict"] is True
    assert metadata["rate_empty_metadata_conflict"] is False
    assert metadata["conflict_fields"] == ["rate_unit"]
    assert metadata["available_source_contract_ids"] == [1, 2]
    assert metadata["resolved_metadata"] == {
        "rate_unit": None,
        "billing_hours_per_month": 160,
    }


def test_financial_metadata_does_not_couple_client_and_cost_currencies():
    today = date(2026, 8, 26)
    contracts = [
        {
            "id": 1,
            "rate_candidate": Decimal("100"),
            "rate_client": None,
            "framework_rate": None,
            "rate_unit": "hourly",
            "currency": "PLN",
            "rate_client_currency": "PLN",
            "rate_candidate_currency": "EUR",
            "billing_hours_per_month": 160,
        },
        {
            "id": 2,
            "rate_candidate": None,
            "rate_client": Decimal("150"),
            "framework_rate": None,
            "rate_unit": "hourly",
            "currency": "GBP",
            "rate_client_currency": "GBP",
            "rate_candidate_currency": "PLN",
            "billing_hours_per_month": 160,
        },
    ]
    plans = [
        _rate_timeline_plan(contracts, [], kind, today)
        for kind in ("candidate", "client", "framework")
    ]

    metadata = _financial_metadata_plan(contracts, plans)

    assert metadata["conflict"] is False
    assert metadata["conflict_fields"] == []
    assert metadata["resolved_metadata"] == {
        "rate_unit": "hourly",
        "billing_hours_per_month": 160,
    }


def test_framework_and_metadata_decisions_are_explicit_and_compatible():
    group = {
        "group_key": 1,
        "framework_rates": {
            "conflict": True,
            "available_source_contract_ids": [1, 2],
            "single_source_contract_id": None,
        },
        "financial_metadata_plan": {
            "conflict": True,
            "conflict_fields": ["rate_unit"],
            "available_source_contract_ids": [1, 2],
            "single_source_contract_id": None,
            "resolved_metadata": {
                "rate_unit": None,
                "billing_hours_per_month": 160,
            },
            "snapshots": [
                {
                    "contract_id": 1,
                    "rate_unit": "hourly",
                    "currency": "PLN",
                    "billing_hours_per_month": 160,
                },
                {
                    "contract_id": 2,
                    "rate_unit": "monthly",
                    "currency": "PLN",
                    "billing_hours_per_month": 160,
                },
            ],
        },
    }

    with pytest.raises(ContractMergeError, match="missing framework rate decision"):
        _validate_decision(group, "framework", {})
    assert _validate_decision(group, "framework", {1: 2}) == 2

    with pytest.raises(ContractMergeError, match="metadata decision"):
        _validate_financial_metadata_decision(group, {})
    source, resolved = _validate_financial_metadata_decision(group, {1: 2})
    assert source == 2
    assert resolved["rate_unit"] == "monthly"
    _assert_rate_sources_match_metadata(
        group,
        {"framework": 2},
        resolved,
    )
    with pytest.raises(ContractMergeError, match="disagrees with selected rate_unit"):
        _assert_rate_sources_match_metadata(
            group,
            {"candidate": 1, "framework": 2},
            resolved,
        )


def test_rate_empty_metadata_blocker_requires_explicit_bulk_allow():
    blocker = "rate_empty_financial_metadata_conflict"

    assert blocker not in _resolvable_merge_blocker_codes(False)
    assert blocker in _resolvable_merge_blocker_codes(True)


def test_manifest_rejects_overlap_and_rate_parser_is_allowlisted(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "same_client_groups": [[1, 2], [2, 3]],
                "explicit_deletes": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractMergeError, match="multiple groups"):
        load_contract_merge_manifest(manifest)

    assert parse_rate_source_map("344=348,349=349") == {344: 348, 349: 349}
    with pytest.raises(ContractMergeError):
        parse_rate_source_map("344=$(bad)")

    assert parse_field_source_map("31.line_manager=31,344.project_name=346") == {
        (31, "line_manager"): 31,
        (344, "project_name"): 346,
    }
    with pytest.raises(ContractMergeError):
        parse_field_source_map("31.line_manager=$(bad)")
    with pytest.raises(ContractMergeError, match="not allowed"):
        parse_field_source_map("31.start_date=31")


def test_field_decisions_are_exact_and_copy_only_the_selected_source():
    group = {
        "group_key": 31,
        "survivor_id": 31,
        "contract_rows": [
            {"id": 31, "line_manager": "Manager A"},
            {"id": 194, "line_manager": "Manager B"},
        ],
        "field_conflicts": [
            {
                "field": "line_manager",
                "values": [
                    {"contract_ids": [31], "value": "Manager A"},
                    {"contract_ids": [194], "value": "Manager B"},
                ],
            }
        ],
    }

    sources, updates = _resolve_field_decisions(group, {(31, "line_manager"): 194})
    assert sources == {"line_manager": 194}
    assert updates == {"line_manager": "Manager B"}
    with pytest.raises(ContractMergeError, match="missing field decision"):
        _resolve_field_decisions(group, {})
    with pytest.raises(ContractMergeError, match="invalid field source"):
        _resolve_field_decisions(group, {(31, "line_manager"): 999})


def test_checked_in_manifest_matches_all_ticket_cardinalities():
    manifest = load_contract_merge_manifest(
        Path(__file__).resolve().parents[1]
        / "app"
        / "data"
        / "contract_merge_2026_08.json"
    )
    assert len(manifest.same_client_groups) == 69
    assert sum(len(group) for group in manifest.same_client_groups) == 139
    assert sum(len(group) - 1 for group in manifest.same_client_groups) == 70
    assert len(manifest.different_client_noop_groups) == 3
    assert [(item.keep_id, item.delete_id) for item in manifest.explicit_deletes] == [
        (341, 563),
        (600, 560),
    ]
    assert [
        (
            item.expected_keep_client_id,
            item.expected_delete_client_id,
            item.expected_keep_status,
            item.expected_delete_status,
        )
        for item in manifest.explicit_deletes
    ] == [(11, 30, "active", "draft"), (16, 41, "draft", "draft")]


def test_fingerprint_is_stable_across_presentation_fields_but_not_plan_data():
    left = {
        "mode": "audit",
        "ok": True,
        "generated_at": "one",
        "business_date": "2026-08-26",
        "groups": [{"contract_ids": [1, 2], "rate": Decimal("100.000")}],
    }
    right = dict(left, mode="apply", generated_at="two")
    assert plan_fingerprint(left) == plan_fingerprint(right)

    right["groups"] = [{"contract_ids": [1, 2], "rate": Decimal("101.000")}]
    assert plan_fingerprint(left) != plan_fingerprint(right)

    left["groups"] = [{"children": {"orders": 1}, "child_row_ids": [10]}]
    right["groups"] = [{"children": {"orders": 1}, "child_row_ids": [11]}]
    assert plan_fingerprint(left) != plan_fingerprint(right)


def test_approval_fingerprint_binds_normalized_rate_decisions():
    plan_hash = "a" * 64
    assert approval_fingerprint(
        plan_hash,
        candidate_rate_sources={2: 20, 1: 10},
        client_rate_sources={3: 30},
        framework_rate_sources={4: 40},
        rate_metadata_sources={5: 50},
    ) == (
        approval_fingerprint(
            plan_hash,
            candidate_rate_sources={1: 10, 2: 20},
            client_rate_sources={3: 30},
            framework_rate_sources={4: 40},
            rate_metadata_sources={5: 50},
        )
    )
    assert approval_fingerprint(plan_hash, {1: 10}, {}) != approval_fingerprint(
        plan_hash, {1: 11}, {}
    )
    baseline = approval_fingerprint(plan_hash)
    assert baseline != approval_fingerprint(plan_hash, framework_rate_sources={4: 40})
    assert baseline != approval_fingerprint(plan_hash, rate_metadata_sources={5: 50})
    assert baseline != approval_fingerprint(plan_hash, allow_rate_empty_metadata=True)
    assert baseline != approval_fingerprint(
        plan_hash, field_sources={(31, "line_manager"): 194}
    )
    assert approval_fingerprint(
        plan_hash,
        field_sources={(344, "project_name"): 346, (31, "line_manager"): 194},
    ) == approval_fingerprint(
        plan_hash,
        field_sources={(31, "line_manager"): 194, (344, "project_name"): 346},
    )


def test_activity_snapshot_is_a_minimal_value_free_allowlist():
    group = {
        "operation": "merge_same_client",
        "contract_ids": [1, 2],
        "delete_ids": [2],
        "survivor_id": 1,
        "contract_rows": [{"client_pm_email": "secret@example.com"}],
        "rate_schedules": {"candidate": [{"rate": "999"}]},
        "field_updates": {"draft_content_html": "<b>secret</b>"},
    }
    snapshot = _snapshot_for_source(
        group,
        {
            "candidate_rate_source_contract_id": 1,
            "allow_rate_empty_metadata": True,
        },
        {"line_manager": 2},
        {"client_orders": 1},
        ["draft_content_html", "rate_candidate"],
    )
    encoded = json.dumps(snapshot)
    assert "secret" not in encoded
    assert "999" not in encoded
    assert snapshot["changed_fields"] == ["draft_content_html", "rate_candidate"]
    assert snapshot["source_id_decisions"] == {"candidate_rate_source_contract_id": 1}
    assert snapshot["allow_rate_empty_metadata"] is True
    assert snapshot["field_source_contract_ids"] == {"line_manager": 2}


def test_notification_contract_links_are_exact_and_explicit_refs_block_delete():
    link = "/contracts/12?tab=x&contract=12#/contracts/123"
    assert _replace_contract_link(link, 12, 99) == (
        "/contracts/99?tab=x&contract=99#/contracts/123"
    )
    assert _replace_contract_link("/contracts/123?contract=123", 12, 99) == (
        "/contracts/123?contract=123"
    )

    blocker = _explicit_historical_reference_blocker(
        {
            "activities": [1],
            "notifications": [],
            "notification_link_refs": [2],
            "alert_dedup": [3],
            "activities_sha256": "a" * 64,
        }
    )
    assert blocker == {
        "code": "explicit_delete_has_historical_references",
        "references": {
            "activities": 1,
            "notification_link_refs": 1,
            "alert_dedup": 1,
        },
    }


def test_redacted_report_contains_no_names_rates_or_field_values():
    full = {
        "mode": "audit",
        "ok": True,
        "fingerprint": "a" * 64,
        "summary": {"groups": 1},
        "groups": [
            {
                "operation": "merge_same_client",
                "group_key": 1,
                "contract_ids": [1, 2],
                "survivor_id": 1,
                "delete_ids": [2],
                "candidate": "Sensitive Person",
                "client": "Sensitive Client",
                "contract_rows": [{"rate_candidate": "123.45"}],
                "field_conflicts": [
                    {"field": "line_manager", "values": ["Secret Boss"]}
                ],
                "candidate_rates": {
                    "conflict": True,
                    "current_value_conflict": True,
                    "schedule_conflict": True,
                    "schedule_conflict_scopes": ["future"],
                    "snapshots": [{"rate": "123.45"}],
                },
                "client_rates": {"conflict": False, "snapshots": []},
                "framework_rates": {
                    "conflict": True,
                    "current_value_conflict": True,
                    "schedule_conflict": False,
                    "snapshots": [{"rate": "987.65"}],
                },
                "financial_metadata_plan": {
                    "conflict": True,
                    "conflict_fields": ["rate_unit"],
                    "rate_bearing_contract_ids": [1, 2],
                    "rate_empty_metadata_conflict": True,
                    "rate_empty_metadata_conflict_fields": ["currency"],
                    "rate_empty_contract_ids": [3],
                    "snapshots": [{"contract_id": 1, "rate_unit": "secret-unit"}],
                },
                "blockers": [
                    {
                        "code": "candidate_rate_current_value_conflict",
                        "values": ["123.45"],
                    },
                    {"code": "financial_metadata_conflict"},
                    {"code": "rate_empty_financial_metadata_conflict"},
                ],
            }
        ],
    }

    encoded = json.dumps(redact_contract_merge_report(full), ensure_ascii=False)

    assert "Sensitive" not in encoded
    assert "123.45" not in encoded
    assert "Secret Boss" not in encoded
    assert "line_manager" in encoded
    assert "987.65" not in encoded
    assert "secret-unit" not in encoded
    assert "candidate_rate_current_value_conflict" in encoded
    assert "financial_metadata_conflict" in encoded
    redacted = redact_contract_merge_report(full)["groups"][0]
    assert redacted["rate_conflicts"]["candidate"] == {
        "current_value": True,
        "schedule": True,
        "schedule_scopes": ["future"],
    }
    assert redacted["rate_conflicts"]["framework"]["current_value"] is True
    assert redacted["financial_metadata_conflict_fields"] == ["rate_unit"]
    assert redacted["rate_empty_metadata_conflict"] is True
    assert redacted["rate_empty_metadata_conflict_fields"] == ["currency"]
    assert redacted["rate_empty_metadata_contract_ids"] == [3]


def test_redacted_explicit_delete_exposes_only_exact_allowlisted_dependency_ids():
    full = {
        "mode": "audit",
        "ok": True,
        "fingerprint": "a" * 64,
        "summary": {"groups": 1},
        "groups": [
            {
                "operation": "explicit_delete_wrong_project",
                "group_key": 341,
                "contract_ids": [341, 563],
                "survivor_id": 341,
                "delete_ids": [563],
                "field_conflicts": [],
                "blockers": [{"code": "explicit_delete_has_children"}],
                "hard_delete_plan": {
                    "child_row_ids": {
                        "b2b_generated_contracts": [48],
                        "client_orders": [90],
                    },
                    "historical_row_ids": {
                        "activities": [700],
                        "notifications": [701],
                        "notification_link_refs": [701],
                        "alert_dedup": [702],
                    },
                    "protective_completed_signature_ids": [],
                    "protective_signed_generated_contract_ids": [],
                },
            }
        ],
    }

    hard_delete = redact_contract_merge_report(full)["groups"][0]["hard_delete"]
    assert hard_delete["child_row_ids"] == {
        "b2b_generated_contracts": [48],
        "client_orders": [90],
    }
    assert hard_delete["child_row_counts"] == {
        "b2b_generated_contracts": 1,
        "client_orders": 1,
    }
    assert hard_delete["historical_row_counts"] == {
        "activities": 1,
        "alert_dedup": 1,
        "notification_link_refs": 1,
        "notifications": 1,
    }

    full["groups"][0]["hard_delete_plan"]["child_row_ids"]["unknown"] = [999]
    with pytest.raises(ContractMergeError, match="unexpected keys"):
        redact_contract_merge_report(full)


@pytest.mark.asyncio
async def test_transacted_apply_keeps_live_survivor_and_physically_deletes_loser():
    """Migrated-Postgres proof of plan -> fingerprint -> locked physical merge."""
    import uuid
    from datetime import timedelta

    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.contract_alert_dedup import ContractAlertDedup
    from app.services.contract_merge import (
        apply_contract_merge_plan,
        build_contract_merge_plan,
    )

    suffix = uuid.uuid4().hex[:10]
    today = business_today()
    candidate_id = client_id = survivor_id = loser_id = None
    source_alert_key = alias_alert_key = None
    async with AsyncSessionLocal() as db:
        try:
            candidate = Candidate(
                name="Merge",
                lastname=f"Proof-{suffix}",
                email=f"contract-merge-{suffix}@example.com",
            )
            client = Client(name=f"Contract Merge Proof {suffix}")
            db.add_all([candidate, client])
            await db.flush()
            candidate_id, client_id = candidate.id, client.id

            survivor = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=today - timedelta(days=90),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
                margin=Decimal("50.000"),
                rate_unit=RateUnit.hourly,
                billing_hours_per_month=160,
                currency="PLN",
            )
            loser = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=ContractStatus.draft,
                start_date=today - timedelta(days=90),
                rate_candidate=None,
                rate_client=None,
                rate_unit=RateUnit.hourly,
                billing_hours_per_month=160,
                currency="PLN",
                line_manager="Manager carried from duplicate",
            )
            db.add_all([survivor, loser])
            await db.flush()
            survivor_id, loser_id = survivor.id, loser.id
            source_alert_key = f"ending:30:{loser.id}:2026-12-31"
            alias_alert_key = f"ending:30:{survivor.id}:2026-12-31"

            order = ClientOrder(
                client_id=client.id,
                contract_id=loser.id,
                title="Current order on duplicate",
                status=ClientOrderStatus.active,
                start_date=today - timedelta(days=30),
                end_date=today + timedelta(days=60),
            )
            db.add_all([order, ContractAlertDedup(dedup_key=source_alert_key)])
            await db.flush()
            order_id = order.id
            await db.commit()
            manifest = ContractMergeManifest(
                same_client_groups=((survivor_id, loser_id),)
            )
            audit = await build_contract_merge_plan(db, manifest, today=today)
            assert audit["global_blockers"] == []
            assert all(
                isinstance(fk["confdeltype"], str)
                and fk["confdeltype"] in {"a", "r", "c", "n", "d"}
                for fk in audit["schema"]["contract_foreign_keys"]
            )
            assert audit["groups"][0]["survivor_id"] == survivor_id
            assert audit["groups"][0]["blockers"] == []
            # Apply intentionally requires SERIALIZABLE as its first SQL
            # statement, just like the separate operational apply invocation.
            await db.rollback()

            applied = await apply_contract_merge_plan(
                db,
                manifest,
                expected_fingerprint=audit["fingerprint"],
                expected_approval_fingerprint=approval_fingerprint(
                    audit["fingerprint"]
                ),
                today=today,
            )
            await db.commit()
            assert applied["summary"]["contracts_deleted"] == 1
            db.expunge_all()  # raw-SQL merge bypasses the ORM identity map

            kept = await db.get(Contract, survivor_id)
            assert kept is not None
            assert kept.status == ContractStatus.active
            assert kept.line_manager == "Manager carried from duplicate"
            assert kept.client_order_end_date == today + timedelta(days=60)
            assert await db.get(Contract, loser_id) is None
            moved_order = await db.get(ClientOrder, order_id)
            assert moved_order is not None and moved_order.contract_id == survivor_id
            activity = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == survivor_id,
                    Activity.external_source == "contract_merge_2026_08",
                )
            )
            assert activity is not None
            assert activity.details["source_contract_ids"] == sorted(
                [survivor_id, loser_id]
            )
            assert activity.details["deleted_contract_ids"] == [loser_id]
            assert "source_contract_snapshots" not in activity.details
            assert "line_manager" in activity.details["changed_fields"]
            alert_keys = set(
                (
                    await db.execute(
                        select(ContractAlertDedup.dedup_key).where(
                            ContractAlertDedup.dedup_key.in_(
                                [source_alert_key, alias_alert_key]
                            )
                        )
                    )
                ).scalars()
            )
            assert alert_keys == {source_alert_key, alias_alert_key}
        finally:
            await db.rollback()
            if source_alert_key is not None and alias_alert_key is not None:
                await db.execute(
                    delete(ContractAlertDedup).where(
                        ContractAlertDedup.dedup_key.in_(
                            [source_alert_key, alias_alert_key]
                        )
                    )
                )
            if survivor_id is not None:
                await db.execute(
                    delete(Activity).where(
                        Activity.external_source == "contract_merge_2026_08",
                        Activity.entity_id == survivor_id,
                    )
                )
            if survivor_id is not None and loser_id is not None:
                await db.execute(
                    delete(Contract).where(Contract.id.in_([survivor_id, loser_id]))
                )
            if candidate_id is not None:
                await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
            if client_id is not None:
                await db.execute(delete(Client).where(Client.id == client_id))
            await db.commit()


@pytest.mark.asyncio
async def test_apply_handles_no_current_order_notification_collision_and_noop_history():
    """Postgres proof for nonblocking audit paths and lossless notifications."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.notification import Notification, NotificationType
    from app.models.user import User, UserRole
    from app.services.contract_merge import (
        apply_contract_merge_plan,
        build_contract_merge_plan,
    )

    suffix = uuid.uuid4().hex[:10]
    today = business_today()
    contract_ids: list[int] = []
    candidate_ids: list[int] = []
    client_ids: list[int] = []
    notification_ids: list[int] = []
    user_id: int | None = None
    survivor_id = loser_id = ended_id = live_id = None
    survivor_notification_id = loser_notification_id = None
    async with AsyncSessionLocal() as db:
        try:
            merge_candidate = Candidate(
                name="Merge",
                lastname=f"NoOrder-{suffix}",
                email=f"merge-no-order-{suffix}@example.com",
            )
            history_candidate = Candidate(
                name="History",
                lastname=f"Noop-{suffix}",
                email=f"merge-noop-{suffix}@example.com",
            )
            merge_client = Client(name=f"Merge No Order {suffix}")
            old_client = Client(name=f"History Old {suffix}")
            new_client = Client(name=f"History New {suffix}")
            user = User(
                email=f"merge-notification-{suffix}@example.com",
                name="Merge Notification Proof",
                role=UserRole.recruiter,
                roles=[UserRole.recruiter.value],
                is_active=True,
            )
            db.add_all(
                [
                    merge_candidate,
                    history_candidate,
                    merge_client,
                    old_client,
                    new_client,
                    user,
                ]
            )
            await db.flush()
            candidate_ids = [merge_candidate.id, history_candidate.id]
            client_ids = [merge_client.id, old_client.id, new_client.id]
            user_id = user.id

            survivor = Contract(
                candidate_id=merge_candidate.id,
                client_id=merge_client.id,
                status=ContractStatus.active,
                start_date=today - timedelta(days=90),
                client_order_end_date=today + timedelta(days=10),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
                rate_unit=RateUnit.hourly,
                billing_hours_per_month=160,
                currency="PLN",
            )
            loser = Contract(
                candidate_id=merge_candidate.id,
                client_id=merge_client.id,
                status=ContractStatus.draft,
                start_date=today - timedelta(days=90),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
                rate_unit=RateUnit.hourly,
                billing_hours_per_month=160,
                currency="PLN",
            )
            ended = Contract(
                candidate_id=history_candidate.id,
                client_id=old_client.id,
                status=ContractStatus.ended,
                start_date=today - timedelta(days=180),
                end_date=today - timedelta(days=31),
            )
            live = Contract(
                candidate_id=history_candidate.id,
                client_id=new_client.id,
                status=ContractStatus.active,
                start_date=today - timedelta(days=30),
            )
            db.add_all([survivor, loser, ended, live])
            await db.flush()
            survivor_id, loser_id = survivor.id, loser.id
            ended_id, live_id = ended.id, live.id
            contract_ids = [survivor_id, loser_id, ended_id, live_id]

            created_at = datetime.now(timezone.utc)
            survivor_notification = Notification(
                user_id=user.id,
                title="Survivor notification",
                message="First history row",
                link=f"/contracts/{survivor_id}",
                notification_type=NotificationType.contract_ending_90d,
                related_entity_type="contract",
                related_entity_id=survivor_id,
                is_read=True,
                created_at=created_at,
            )
            loser_notification = Notification(
                user_id=user.id,
                title="Loser notification",
                message="Second history row",
                link=f"/contracts/{loser_id}",
                notification_type=NotificationType.contract_ending_90d,
                related_entity_type="contract",
                related_entity_id=loser_id,
                is_read=False,
                created_at=created_at,
            )
            db.add_all([survivor_notification, loser_notification])
            await db.flush()
            survivor_notification_id = survivor_notification.id
            loser_notification_id = loser_notification.id
            notification_ids = [survivor_notification_id, loser_notification_id]
            await db.commit()

            manifest = ContractMergeManifest(
                same_client_groups=((survivor_id, loser_id),),
                different_client_noop_groups=((ended_id, live_id),),
            )
            audit = await build_contract_merge_plan(db, manifest, today=today)
            merge_group = next(
                group
                for group in audit["groups"]
                if group["operation"] == "merge_same_client"
            )
            noop_group = next(
                group
                for group in audit["groups"]
                if group["operation"] == "sequential_history_noop"
            )
            assert merge_group["blockers"] == []
            assert merge_group["field_updates"]["client_order_end_date"] is None
            assert merge_group["notification_repoint_plan"][
                "retained_historical_notification_ids"
            ] == [loser_notification_id]
            assert noop_group["blockers"] == []
            assert {item["code"] for item in noop_group["observations"]} == {
                "noop_ended_contract_has_no_eligible_order",
                "noop_live_contract_has_no_current_order",
            }
            await db.rollback()

            applied = await apply_contract_merge_plan(
                db,
                manifest,
                expected_fingerprint=audit["fingerprint"],
                expected_approval_fingerprint=approval_fingerprint(
                    audit["fingerprint"]
                ),
                today=today,
            )
            await db.commit()
            db.expunge_all()

            kept = await db.get(Contract, survivor_id)
            assert kept is not None and kept.client_order_end_date is None
            assert await db.get(Contract, loser_id) is None
            assert await db.get(Contract, ended_id) is not None
            assert await db.get(Contract, live_id) is not None
            assert applied["summary"]["sequential_groups_verified_unchanged"] == 1
            merge_result = next(
                item
                for item in applied["applied"]
                if item["operation"] == "merge_same_client"
            )
            assert merge_result["reparented"]["notifications_retained_historical"] == 1

            notifications = (
                (
                    await db.execute(
                        select(Notification)
                        .where(Notification.id.in_(notification_ids))
                        .order_by(Notification.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(notifications) == 2
            by_id = {item.id: item for item in notifications}
            assert by_id[survivor_notification_id].related_entity_id == survivor_id
            assert by_id[loser_notification_id].related_entity_id == loser_id
            assert by_id[survivor_notification_id].title == "Survivor notification"
            assert by_id[loser_notification_id].title == "Loser notification"
            assert by_id[loser_notification_id].link == f"/contracts/{survivor_id}"
        finally:
            await db.rollback()
            if notification_ids:
                await db.execute(
                    delete(Notification).where(Notification.id.in_(notification_ids))
                )
            if survivor_id is not None:
                await db.execute(
                    delete(Activity).where(
                        Activity.external_source == "contract_merge_2026_08",
                        Activity.entity_id == survivor_id,
                    )
                )
            if contract_ids:
                await db.execute(delete(Contract).where(Contract.id.in_(contract_ids)))
            if candidate_ids:
                await db.execute(
                    delete(Candidate).where(Candidate.id.in_(candidate_ids))
                )
            if client_ids:
                await db.execute(delete(Client).where(Client.id.in_(client_ids)))
            if user_id is not None:
                await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
