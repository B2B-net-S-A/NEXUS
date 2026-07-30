"""Contract checks for reversible imported client aliases (revision 0209)."""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0209_client_alias_lifecycle.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
MODEL = BACKEND / "app/models/client_directory.py"


def _literal_assignment(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"missing assignment {name}")


def test_alias_lifecycle_revision_is_linear_and_additive() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert _literal_assignment(tree, "revision") == "0209_client_alias_lifecycle"
    assert _literal_assignment(tree, "down_revision") == "0208_monthly_rate_retired"
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    assert "DELETE FROM" not in upgrade.upper()
    assert "DROP COLUMN" not in upgrade.upper()


def test_alias_lifecycle_is_mirrored_in_model_and_entrypoint() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    model = MODEL.read_text(encoding="utf-8")

    for source in (migration, entrypoint):
        for token in (
            "ADD COLUMN IF NOT EXISTS import_run_id",
            "ADD COLUMN IF NOT EXISTS archived_at",
            "fk_client_aliases_import_run_id",
            "ix_client_aliases_import_run_id",
            "ix_client_aliases_archived_at",
            "ON DELETE SET NULL",
        ):
            assert token in source

    client_alias = model[model.index("class ClientAlias") :]
    assert 'ForeignKey("client_import_runs.id", ondelete="SET NULL")' in client_alias
    assert "archived_at" in client_alias
    assert '"ix_client_aliases_import_run_id"' in client_alias
    assert '"ix_client_aliases_archived_at"' in client_alias


def test_alias_lifecycle_downgrade_drops_fk_before_columns() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade") :]

    assert downgrade.index("fk_client_aliases_import_run_id") < downgrade.index(
        "DROP COLUMN IF EXISTS import_run_id"
    )
