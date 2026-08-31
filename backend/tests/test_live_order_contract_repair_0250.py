"""Safety contract for the targeted repair and the wider read-only audit."""

from __future__ import annotations

from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0250_live_order_contract_repair.py"


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_0250_chains_after_order_rate_snapshot_head():
    source = _source()
    assert 'revision = "0250_live_order_contract_repair"' in source
    assert 'down_revision = "0249_order_rate_snapshots_offboarding"' in source


def test_repair_requires_business_identity_not_bare_ticket_ids():
    source = _source()
    target_block = source.split("CREATE TEMP TABLE _ticket_live_order_targets", 1)[
        1
    ].split("UPDATE contracts", 1)[0]

    for value in (
        "contract_id = 327",
        "contract_id = 165",
        "candidate_first_name = 'grzegorz'",
        "candidate_last_name = 'królikowski'",
        "candidate_first_name = 'wojciech'",
        "candidate_last_name = 'drąg'",
        "'285493' = ANY(audit.live_order_numbers)",
        "'285623' = ANY(audit.live_order_numbers)",
        "client_labels LIKE '%nordea%'",
        "target_order.start_date = DATE '2026-08-29'",
        "target_order.end_date = DATE '2027-02-28'",
        "target_order.end_date = DATE '2026-11-30'",
    ):
        assert value in target_block


def test_wider_population_is_audited_but_only_ticket_targets_are_updated():
    source = _source()
    update = source.split("WITH updated AS (", 1)[1].split(
        "RETURNING c.id AS contract_id", 1
    )[0]
    assert "FROM _action_ticket_targets AS t" in update
    assert "FROM _ticket_live_order_targets AS t" not in update
    assert "FROM _stale_live_order_audit AS t" not in update
    assert "analogous_contracts_not_mutated" in source
    assert "audited_contract_ids" in source
    assert "by_client" in source


def test_audit_requires_an_active_date_effective_order():
    source = _source()
    audit = source.split("CREATE TEMP TABLE _stale_live_order_audit", 1)[1].split(
        "CREATE TEMP TABLE _ticket_live_order_targets", 1
    )[0]
    assert "c.status IN ('ended', 'ending')" in audit
    assert "o.client_id = c.client_id" in audit
    assert "o.status = 'active'" in audit
    assert "o.start_date IS NOT NULL" in audit
    assert "o.start_date <= business_day" in audit
    assert "o.end_date IS NULL OR o.end_date >= business_day" in audit
    assert "Europe/Warsaw" in source


def test_repair_moves_the_horizon_and_preserves_untracked_order_end():
    source = _source()
    update = source.split("WITH updated AS (", 1)[1].split(
        "RETURNING c.id AS contract_id", 1
    )[0]
    assert "WHEN t.has_open_ended THEN NULL" in update
    assert "WHEN t.max_end > c.end_date THEN t.max_end" in update
    assert "WHEN c.client_order_end_date IS NULL THEN NULL" in update
    assert "WHEN t.max_end > c.client_order_end_date THEN t.max_end" in update


def test_action_time_revalidation_locks_and_rechecks_exact_ticket_rows():
    source = _source()
    action = source.split("-- The audit snapshot above", 1)[1].split(
        "CREATE TEMP TABLE _repaired_ticket_targets", 1
    )[0]
    update = source.split("CREATE TEMP TABLE _repaired_ticket_targets", 1)[1].split(
        "INSERT INTO activities", 1
    )[0]

    assert "FOR UPDATE OF c, target_order" in action
    assert "CREATE TEMP TABLE _action_ticket_targets" in action
    # The mutation horizon and receipt must come from the exact locked Order,
    # never from the earlier aggregate of other orders on that Contract.
    assert "(target_order.end_date IS NULL) AS has_open_ended" in action
    assert "target_order.end_date AS max_end" in action
    assert "ARRAY[target_order.id] AS live_order_ids" in action
    assert "ARRAY[target_order.title] AS live_order_numbers" in action
    assert "t.has_open_ended" not in action
    assert "t.max_end" not in action
    assert "t.live_order_ids" not in action
    assert "t.live_order_numbers" not in action
    for value in (
        "c.status IN ('ended', 'ending')",
        "target_order.status = 'active'",
        "target_order.start_date <= business_day",
        "target_order.end_date >= business_day",
        "btrim(target_order.title) = '285493'",
        "target_order.start_date = DATE '2026-08-29'",
        "target_order.end_date = DATE '2027-02-28'",
        "btrim(target_order.title) = '285623'",
        "target_order.end_date = DATE '2026-11-30'",
    ):
        assert value in action
        assert value in update

    assert "WITH updated AS (" in update
    assert "UPDATE contracts AS c" in update
    assert "RETURNING c.id AS contract_id" in update
    assert "SELECT count(*) INTO repaired_rows FROM _repaired_ticket_targets" in update


def test_activity_and_receipt_include_only_rows_returned_by_update():
    source = _source()
    after_update = source.split("RETURNING c.id AS contract_id", 1)[1]
    activity = after_update.split("INSERT INTO activities", 1)[1].split(
        "SELECT count(*), count(DISTINCT client_id)", 1
    )[0]
    receipt = source.split("INTO ticket_targets", 1)[1].split(
        "INSERT INTO app_settings", 1
    )[0]

    assert "FROM _repaired_ticket_targets AS t" in activity
    assert "FROM _ticket_live_order_targets AS t" not in activity
    assert "FROM _repaired_ticket_targets" in receipt
    assert "FROM _ticket_live_order_targets" not in receipt


def test_already_active_counter_is_snapshotted_before_the_repair():
    source = _source()
    snapshot_start = source.index("CREATE TEMP TABLE _known_ticket_live_order_records")
    update_start = source.index("UPDATE contracts AS c")
    assert snapshot_start < update_start

    snapshot = source[snapshot_start:update_start]
    assert "c.status::text AS previous_status" in snapshot
    counter = source.split("INTO known_records, known_already_active", 1)[0].rsplit(
        "SELECT", 1
    )[1]
    assert "previous_status = 'active'" in counter
    assert "c.status = 'active'" not in counter


def test_repair_is_one_shot_audited_and_non_reversible():
    source = _source()
    marker = "0250_live_order_contract_repair"
    assert "pg_advisory_xact_lock" in source
    assert "WHERE key = '{_MARKER}'" in source
    assert "ON CONFLICT (key) DO NOTHING" in source
    assert "INSERT INTO activities" in source
    assert "'contract_reopened'" in source
    assert "'from_status', t.previous_status" in source
    assert marker in source
    downgrade = source.split("def downgrade()", 1)[1]
    assert "UPDATE contracts" not in downgrade
