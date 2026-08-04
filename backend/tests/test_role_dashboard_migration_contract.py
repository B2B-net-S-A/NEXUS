"""Static contracts for revision 0210 and its production startup mirror.

These checks intentionally avoid a database.  Hosted CI still exercises the
real PostgreSQL upgrade; this file protects the replay and parity properties
that are easy to lose while editing the large entrypoint safety net.
"""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0210_role_dashboard_rbac_cutover.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
USER_MODEL = BACKEND / "app/models/user.py"
AUTH_EXCHANGE_MODEL = BACKEND / "app/models/auth_exchange_code.py"
TEAM_MODEL = BACKEND / "app/models/team_structure.py"
COMPETENCE_MODEL = BACKEND / "app/models/competence_category.py"
MIGRATION_KEY = "0210_role_dashboard_rbac_cutover"


def _literal_assignment(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"missing assignment {name}")


def _migration_parts() -> tuple[str, str, str]:
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_start = source.index("def upgrade")
    downgrade_start = source.index("def downgrade")
    return source, source[upgrade_start:downgrade_start], source[downgrade_start:]


def _entrypoint_cutover() -> str:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    start = source.index('_ROLE_DASHBOARD_CUTOVER_SQL = r"""')
    return source[start : source.index("\n\n_DATA_STATEMENTS", start)]


def test_0210_extends_the_single_current_head() -> None:
    source, _, _ = _migration_parts()
    tree = ast.parse(source)

    assert _literal_assignment(tree, "revision") == MIGRATION_KEY
    assert _literal_assignment(tree, "down_revision") == "0210_fix_nordea_display_name"


def test_schema_is_mirrored_by_models_and_entrypoint() -> None:
    _, upgrade, _ = _migration_parts()
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    user_model = USER_MODEL.read_text(encoding="utf-8")
    exchange_model = AUTH_EXCHANGE_MODEL.read_text(encoding="utf-8")
    team_model = TEAM_MODEL.read_text(encoding="utf-8")
    competence_model = COMPETENCE_MODEL.read_text(encoding="utf-8")

    for source in (upgrade, entrypoint):
        for token in (
            "role_session_migration_audit",
            "rbac_relationship_reconciliation",
            "authorization_version BIGINT NOT NULL DEFAULT 1",
            "issued_authorization_version BIGINT NOT NULL DEFAULT 1",
            "is_first_priority_for_tac BOOLEAN NULL",
            "ck_users_exclusive_finance_viewer_roles",
            "ck_user_cc_primary_priority",
            "ux_client_tac_one_first_priority_client",
            "ux_user_cc_one_primary",
        ):
            assert token in source

    assert "authorization_version: Mapped[int]" in user_model
    assert "ck_users_exclusive_finance_viewer_roles" in user_model
    assert "issued_authorization_version: Mapped[int]" in exchange_model
    assert "is_first_priority_for_tac: Mapped[bool | None]" in team_model
    assert 'postgresql_where=text("is_first_priority_for_tac IS TRUE")' in team_model
    assert "priority: Mapped[int]" in competence_model
    assert "ck_user_cc_primary_priority" in competence_model
    assert 'postgresql_where=text("priority = 1")' in competence_model


def test_cutover_replay_does_not_revoke_sessions_twice() -> None:
    _, upgrade, downgrade = _migration_parts()
    session_cutover = upgrade[
        upgrade.index("# One global cutover") : upgrade.index(
            "_add_constraint(", upgrade.index("# One global cutover")
        )
    ]

    # If entrypoint completed the one-shot cutover before Alembic recovered,
    # the canonical migration must not bump AV or consume new exchange codes.
    assert session_cutover.count("WHERE NOT EXISTS") == 2
    assert session_cutover.count(MIGRATION_KEY) == 2

    cutover = _entrypoint_cutover()
    assert cutover.index("IF NOT EXISTS (") < cutover.index("UPDATE users")
    assert cutover.index("UPDATE users\n        SET authorization_version") < (
        cutover.rindex("INSERT INTO app_settings")
    )

    # A true rollback removes the one-shot marker so a later forward upgrade
    # invalidates sessions issued by the downgraded application.
    assert f"WHERE key = '{MIGRATION_KEY}'" in downgrade
    assert downgrade.index("DROP COLUMN IF EXISTS authorization_version") < (
        downgrade.index(f"WHERE key = '{MIGRATION_KEY}'")
    )


def test_optional_legacy_dr_cleanup_is_guarded_in_both_paths() -> None:
    _, upgrade, _ = _migration_parts()
    cutover = _entrypoint_cutover()

    for table in (
        "dr_tac_delivery_lead_assignments",
        "dr_sourcer_category_assignments",
    ):
        guard = f"to_regclass('public.{table}') IS NOT NULL"
        assert guard in upgrade
        assert guard in cutover


def test_finance_snapshot_and_cleanup_scope_match_the_startup_mirror() -> None:
    _, upgrade, _ = _migration_parts()
    cutover = _entrypoint_cutover()

    for source in (upgrade, cutover):
        for audit_key in (
            "'allowed_sections'",
            "'kpi_coach_enabled'",
            "'cloudtalk_agent_id'",
            "'authorization_version'",
            "'tokens_valid_after'",
            "'delivery_lead_client_assignment_ids'",
            "'client_tac_assignment_ids'",
            "'tac_delivery_lead_assignment_ids'",
            "'competence_assignment_ids'",
        ):
            assert audit_key in source

        for approved_cleanup in (
            "DELETE FROM delivery_lead_client_assignments",
            "DELETE FROM client_tac_assignments",
            "DELETE FROM tac_delivery_lead_assignments",
            "DELETE FROM tac_linkedin_farming",
            "DELETE FROM user_competence_categories",
            "DELETE FROM job_collaborators",
            "UPDATE jobs j SET recruiter_id = NULL",
            "UPDATE jobs j SET delivery_lead_id = NULL",
            "UPDATE jobs j SET tac_id = NULL",
            "UPDATE contacts c SET key_relationship_owner_id = NULL",
            "UPDATE saved_searches s",
            "DELETE FROM notifications",
        ):
            assert approved_cleanup in source

        # Saved searches are retained with alerts disabled; candidate records
        # and M365 connection rows are outside this approved cleanup.
        assert "DELETE FROM saved_searches" not in source
        assert "DELETE FROM candidates" not in source
        assert "DELETE FROM microsoft_connections" not in source


def test_relationship_reconciliation_is_non_guessing_and_retry_safe() -> None:
    _, upgrade, _ = _migration_parts()
    cutover = _entrypoint_cutover()

    for source in (upgrade, cutover):
        assert "client_tac_first_priority_required" in source
        assert "competence_primary_required" in source
        # A resolved record is still evidence that this migration issue was
        # already handled.  A later Alembic recovery must not reopen it.
        assert "existing.resolved_at IS NULL" not in source
        assert "HAVING count(*) > 1" in source
        assert "assignment.is_first_priority_for_tac IS TRUE" in source
        assert ") <> 1" in source
        assert "SET priority = 2, is_primary = FALSE" in source
        assert "HAVING count(*) = 1" in source
        assert "SET is_first_priority_for_tac = TRUE" in source
        assert "SET is_first_priority_for_tac = is_primary" not in source

    # Expand migration retains the old client-centric flag for old pods and
    # existing notification rules; only the new TAC-centric column is dropped.
    _, _, downgrade = _migration_parts()
    assert "DROP COLUMN IF EXISTS is_first_priority_for_tac" in downgrade
    assert "DROP COLUMN IF EXISTS is_primary" not in downgrade


def test_downgrade_is_structural_and_preserves_forensic_evidence() -> None:
    _, _, downgrade = _migration_parts()

    assert "SET role = 'user'::userrole" in downgrade
    assert "DROP COLUMN IF EXISTS issued_authorization_version" in downgrade
    assert "DROP COLUMN IF EXISTS authorization_version" in downgrade
    assert "DROP TABLE IF EXISTS role_session_migration_audit" not in downgrade
    assert "DROP TABLE IF EXISTS rbac_relationship_reconciliation" not in downgrade
