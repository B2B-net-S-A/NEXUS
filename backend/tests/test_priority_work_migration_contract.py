"""Additive migration, startup safety-net and deep-health contracts."""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0200_recruitment_priority_work.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
MAIN = BACKEND / "app/main.py"
MODELS_INIT = BACKEND / "app/models/__init__.py"

PRIORITY_TABLES = {
    "recruitment_priority_plans",
    "recruitment_priority_plan_members",
    "recruitment_priority_demands",
    "recruitment_priority_assignments",
    "recruitment_priority_blockers",
    "recruitment_priority_exceptions",
    "recruitment_priority_state",
    "recruitment_priority_user_modes",
    "recruitment_priority_alerts",
    "recruitment_priority_audit_events",
}

PROCESS_COLUMNS = {
    "origin_assignment_id",
    "eligibility_assignment_id",
    "opened_by_user_id",
    "credit_user_id",
    "origin_kind",
    "priority_compliant_at_open",
    "kpi_eligible",
    "kpi_eligibility_reason",
    "kpi_eligibility_decided_at",
    "ownership_confirmed_at",
    "ownership_confirmed_by_user_id",
}


def _literal_assignment(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"missing assignment {name}")


def _migration_function(tree: ast.Module, name: str):
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    function_tree = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(function_tree)
    namespace = {"re": __import__("re")}
    exec(compile(function_tree, str(MIGRATION), "exec"), namespace)
    return namespace[name]


def test_migration_extends_priority_work_branch_head() -> None:
    source = MIGRATION.read_text()
    tree = ast.parse(source)
    assert _literal_assignment(tree, "revision") == "0200_recruitment_priority_work"
    assert _literal_assignment(tree, "down_revision") == "0199_candidate_stage_removals"


def test_migration_contains_all_priority_tables_and_process_provenance() -> None:
    source = MIGRATION.read_text()
    for table in PRIORITY_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source
    for column in PROCESS_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in source
    assert "ADD COLUMN IF NOT EXISTS origin_assignment_id INTEGER NULL" in source
    assert "ADD COLUMN IF NOT EXISTS priority_compliant_at_create BOOLEAN NULL" in (
        source
    )
    assert "fk_invite_link_origin_priority_assignment" in source
    assert "ix_candidate_invite_links_origin_assignment_id" in source


def test_upgrade_is_additive_and_does_not_backfill_historical_processes() -> None:
    source = MIGRATION.read_text()
    tree = ast.parse(source)
    upgrade = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    )
    upgrade_source = ast.get_source_segment(source, upgrade) or ""
    lowered = upgrade_source.lower()
    assert "drop table" not in lowered
    assert "drop column" not in lowered
    assert "delete from" not in lowered
    assert "update recruitment_processes" not in lowered
    assert "insert into recruitment_processes" not in lowered
    assert "backfill_recruitment_processes" not in source

    # Provenance remains nullable: history is classified by the resumable job.
    for column in ("origin_kind", "kpi_eligible", "credit_user_id"):
        statement = next(
            line
            for line in source.splitlines()
            if f"ADD COLUMN IF NOT EXISTS {column}" in line
        )
        assert "NULL" in statement


def test_migration_is_retry_safe() -> None:
    source = MIGRATION.read_text()
    assert "ON CONFLICT (id) DO NOTHING" in source
    assert "IF NOT EXISTS (" in source
    assert "CREATE INDEX IF NOT EXISTS" in source
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in source
    assert "FROM pg_constraint" in source
    assert "autocommit_block" in source
    assert "ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS" in source
    assert "_assert_required_schema()" in source
    assert "REQUIRED_CHECKS" in source
    assert "REQUIRED_NAMED_CONSTRAINTS" in source
    assert "REQUIRED_FOREIGN_KEYS" in source
    assert "ck_priority_demand_recommendations_minimum" in source
    assert "uq_priority_assignment_member_job" in source
    assert "expected_recommendations >= 3" in source
    assert "SELECT constraint_row.contype::text" in source
    assert "SELECT constraint_row.confdeltype::text" in source
    assert "column_names" in source
    assert "predicate_definition" in source
    assert "_canonical_index_predicate" in source
    assert "ux_priority_blocker_assignment_active" in source
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS\n"
        "        ux_priority_blocker_assignment_active"
    ) in source


def test_index_predicate_parity_preserves_boolean_semantics() -> None:
    source = MIGRATION.read_text()
    tree = ast.parse(source)
    canonical = _migration_function(tree, "_canonical_index_predicate")
    required = {
        row[1]: row[5]
        for row in _literal_assignment(tree, "REQUIRED_INDEXES")
        if row[3]
    }

    published = canonical("(status = 'published'::priorityplanstatus)")
    not_published = canonical("(status <> 'published'::priorityplanstatus)")
    unresolved = canonical("(resolved_at IS NULL)")
    resolved = canonical("(resolved_at IS NOT NULL)")

    assert published == required["ux_recruitment_priority_one_published"]
    assert not_published != required["ux_recruitment_priority_one_published"]
    assert unresolved == required["ix_priority_alert_unresolved"]
    assert resolved != required["ix_priority_alert_unresolved"]


def test_startup_safety_net_mirrors_process_columns_and_foreign_keys() -> None:
    source = ENTRYPOINT.read_text()
    for column in PROCESS_COLUMNS:
        assert column in source
    for constraint in (
        "fk_process_origin_priority_assignment",
        "fk_process_eligibility_priority_assignment",
        "fk_process_opened_by_user",
        "fk_process_credit_user",
        "fk_process_ownership_confirmed_by_user",
        "fk_invite_link_origin_priority_assignment",
    ):
        assert constraint in source
    assert "Base.metadata.create_all" in source
    assert "INSERT INTO recruitment_priority_state (id) VALUES (1)" in source
    assert "ON CONFLICT (id) DO NOTHING" in source
    assert "ix_recruitment_processes_origin_assignment_id" in source
    assert "ix_recruitment_processes_eligibility_assignment_id" in source


def test_startup_safety_net_creates_origin_enum_before_process_column() -> None:
    source = ENTRYPOINT.read_text()
    enum_position = source.index("CREATE TYPE priorityoriginkind")
    column_position = source.index(
        "ADD COLUMN IF NOT EXISTS origin_kind priorityoriginkind"
    )
    assert enum_position < column_position


def test_deep_health_probes_every_priority_table() -> None:
    source = MAIN.read_text()
    for table in PRIORITY_TABLES:
        assert f'("{table}",' in source
    assert '("candidate_invite_links", CandidateInviteLink)' in source
    assert '("recruitment_processes", RecruitmentProcess)' in source
    assert 'checks["priority_work_schema"]' in source
    assert "enum_value.enumlabel = expected.label" in source
    assert "index_row.indisvalid" in source
    assert "constraint_row.confrelid" in source
    assert "constraint_row.confdeltype::text" in source
    assert "expected.delete_action" in source
    assert "expected_check" in source
    assert "expected_constraint" in source
    assert "expected_index_columns" in source
    assert "expected_index_predicate" in source
    assert "expected.canonical_definition" in source
    assert "REGEXP_REPLACE" in source
    assert "uq_priority_assignment_member_job" in source
    assert "ck_priority_demand_recommendations_minimum" in source
    assert "ix_recruitment_processes_eligibility_assignment_id" in source


def test_standard_health_keeps_qdrant_and_priority_worker_signals() -> None:
    source = MAIN.read_text()
    assert 'checks["qdrant"]' in source
    assert 'checks["priority_work"]' in source


def test_priority_models_are_registered_for_metadata_create_all() -> None:
    source = MODELS_INIT.read_text()
    assert "from app.models.recruitment_priority import" in source
    for model in (
        "RecruitmentPriorityPlan",
        "RecruitmentPriorityPlanMember",
        "RecruitmentPriorityDemand",
        "RecruitmentPriorityAssignment",
        "RecruitmentPriorityBlocker",
        "RecruitmentPriorityException",
        "RecruitmentPriorityState",
        "RecruitmentPriorityUserMode",
        "RecruitmentPriorityAlert",
        "RecruitmentPriorityAuditEvent",
    ):
        assert model in source
