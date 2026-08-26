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
    _rate_plan,
    _rate_snapshot,
    _rate_timeline_plan,
    _explicit_historical_reference_blocker,
    _replace_contract_link,
    _same_day_schedule_conflicts,
    _snapshot_for_source,
    approval_fingerprint,
    choose_survivor,
    load_contract_merge_manifest,
    merge_field_plan,
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


def test_effective_rate_uses_latest_schedule_step_and_compares_metadata():
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

    same_number_different_unit = dict(snapshot, contract_id=8, rate_unit="monthly")
    assert _rate_plan([snapshot, same_number_different_unit])["conflict"] is True

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


def test_timeline_detects_future_divergence_and_metadata_even_for_null_rate():
    contracts = [
        {
            "id": 1,
            "rate_candidate": None,
            "rate_unit": "hourly",
            "currency": "PLN",
            "billing_hours_per_month": 160,
        },
        {
            "id": 2,
            "rate_candidate": None,
            "rate_unit": "monthly",
            "currency": "PLN",
            "billing_hours_per_month": 160,
        },
    ]
    plan = _rate_timeline_plan(contracts, [], "candidate", date(2026, 8, 26))
    assert plan["conflict"] is True
    assert plan["metadata_conflict"] is True

    contracts[1]["rate_unit"] = "hourly"
    schedule = [
        {
            "id": 10,
            "contract_id": 1,
            "effective_from": date(2027, 1, 1),
            "rate": Decimal("100"),
        },
        {
            "id": 11,
            "contract_id": 2,
            "effective_from": date(2027, 1, 1),
            "rate": Decimal("110"),
        },
    ]
    plan = _rate_timeline_plan(contracts, schedule, "candidate", date(2026, 8, 26))
    assert plan["conflict"] is True
    assert plan["timeline_divergence"]


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
    assert approval_fingerprint(plan_hash, {2: 20, 1: 10}, {3: 30}) == (
        approval_fingerprint(plan_hash, {1: 10, 2: 20}, {3: 30})
    )
    assert approval_fingerprint(plan_hash, {1: 10}, {}) != approval_fingerprint(
        plan_hash, {1: 11}, {}
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
        {"candidate_rate_source_contract_id": 1},
        {"client_orders": 1},
        ["draft_content_html", "rate_candidate"],
    )
    encoded = json.dumps(snapshot)
    assert "secret" not in encoded
    assert "999" not in encoded
    assert snapshot["changed_fields"] == ["draft_content_html", "rate_candidate"]


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
                    "snapshots": [{"rate": "123.45"}],
                },
                "client_rates": {"conflict": False, "snapshots": []},
                "blockers": [{"code": "candidate_rate_conflict", "values": ["123.45"]}],
            }
        ],
    }

    encoded = json.dumps(redact_contract_merge_report(full), ensure_ascii=False)

    assert "Sensitive" not in encoded
    assert "123.45" not in encoded
    assert "Secret Boss" not in encoded
    assert "line_manager" in encoded
    assert "candidate_rate_conflict" in encoded


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
            moved_order = await db.get(ClientOrder, order.id)
            assert moved_order is not None and moved_order.contract_id == survivor.id
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
