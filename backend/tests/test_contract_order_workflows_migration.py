"""Release contract for migration 0238 and its production safety-net."""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0238_contract_order_workflows.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").replace('"', ""))


def _alembic_heads() -> list[str]:
    """Czysty parser grafu; ten test migracji nie powinien bootować aplikacji."""

    revisions: set[str] = set()
    parents: set[str] = set()
    for path in (BACKEND / "alembic" / "versions").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            if target.id == "revision" and isinstance(value, ast.Constant):
                revisions.add(value.value)
            elif target.id == "down_revision":
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parents.add(value.value)
                elif isinstance(value, (ast.Tuple, ast.List)):
                    parents.update(
                        item.value
                        for item in value.elts
                        if isinstance(item, ast.Constant)
                        and isinstance(item.value, str)
                    )
    return sorted(revisions - parents)


def test_migration_is_the_single_head_after_0237():
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                values[target.id] = node.value.value

    assert values["revision"] == "0238_contract_order_workflows"
    assert values["down_revision"] == "0237_proposal_snapshot_hidden"

    assert _alembic_heads() == ["0239_bik_contract_order_backfill"]


def test_every_new_column_has_an_entrypoint_mirror():
    entrypoint = _flat(ENTRYPOINT)
    for column in (
        "filename",
        "file_path",
        "content_type",
        "size_bytes",
        "file_uploaded_by",
        "file_uploaded_at",
        "source_order_group_id",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in entrypoint, column


def test_scheduled_status_is_widened_with_drop_then_add_in_both_paths():
    migration = MIGRATION.read_text(encoding="utf-8")
    entrypoint = _flat(ENTRYPOINT)
    assert "op.drop_constraint( ck_client_order_groups_status" in _flat(MIGRATION)
    assert "op.create_check_constraint( ck_client_order_groups_status" in _flat(
        MIGRATION
    )
    assert "DROP CONSTRAINT IF EXISTS ck_client_order_groups_status" in entrypoint
    assert "ADD CONSTRAINT ck_client_order_groups_status" in entrypoint
    assert "'scheduled'" in migration
    assert "'scheduled'" in ENTRYPOINT.read_text(encoding="utf-8")


def test_pdf_link_is_unique_and_foreign_keyed_in_both_paths():
    for source in (MIGRATION, ENTRYPOINT):
        text = _flat(source)
        assert "fk_contract_documents_source_order_group" in text
        assert "uq_contract_documents_contract_order_group" in text
        assert "source_order_group_id IS NOT NULL" in text


def test_bik_correction_contains_all_nine_people_in_both_paths():
    people = (
        "aleksander wojdyła",
        "daniel madejski",
        "maciej koc",
        "robert łuszczyński",
        "paweł łaski",
        "konrad teper",
        "michał leśniak",
        "wojciech wojtak",
        "grzegorz wadecki",
    )
    for source in (MIGRATION, ENTRYPOINT):
        text = source.read_text(encoding="utf-8").lower()
        assert "biuro informacji kredytowej" in text
        assert "'active'::contractstatus" in text
        for person in people:
            assert person in text, f"{source.name}: {person}"


def test_bik_correction_is_guarded_by_the_same_one_shot_marker():
    marker = "0238_bik_contract_status_correction"
    for source in (MIGRATION, ENTRYPOINT):
        text = source.read_text(encoding="utf-8")
        assert marker in text
        assert "ON CONFLICT (key) DO NOTHING" in text
        assert "EXISTS (SELECT 1 FROM marker)" in text


def test_downgrade_removes_schema_and_restores_supported_group_statuses():
    downgrade = MIGRATION.read_text(encoding="utf-8").split("def downgrade()", 1)[1]
    assert "source_order_group_id" in downgrade
    assert "file_uploaded_at" in downgrade
    assert "_PREVIOUS_GROUP_STATUSES" in downgrade
    assert "SET status = 'active' WHERE status = 'scheduled'" in downgrade
    assert "UPDATE contracts" not in downgrade
