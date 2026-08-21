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


def test_migration_chains_onto_0237():
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


def test_only_one_alembic_head():
    """Liczba głów, NIE nazwa czubka.

    Wcześniej stała tu równość z konkretną rewizją (`== ["0239_..."]`) — jedyne
    takie miejsce w repo; trzy pozostałe strażniki jednogłowości
    (`test_multi_consultant_orders_migration`, `test_order_lifecycle_migration`,
    `test_analytics_release_gates`) liczą głowy. Przypięta nazwa pada przy
    KAŻDEJ następnej migracji, niezależnie od tego, czy cokolwiek się
    rozszczepiło, i kieruje diagnostykę na niewłaściwą migrację: czerwony test
    „…_after_0237" w pliku o 0238, gdy zmiana dotyczy zupełnie innej rewizji.
    Fakt „ile jest głów" jest wyliczalny — nie ma powodu zapisywać go literałem.
    """

    heads = _alembic_heads()
    assert len(heads) == 1, f"łańcuch rozszczepiony, głowy: {heads}"

    # Osierocona rewizja nigdy się nie wykona na produkcji, a sam licznik głów
    # tego nie wykryje — 0238 ma nadal wisieć w łańcuchu.
    referenced = {
        node.value.value
        for path in MIGRATION.parent.glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"revision", "down_revision"}
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    assert "0238_contract_order_workflows" in referenced


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


def test_0239_widens_the_status_check_before_writing_scheduled():
    """Blok 0239 nie może polegać na kolejności list w `backfill()`.

    `_DATA_STATEMENTS` biegną PRZED `_CONSTRAINT_STATEMENTS`, więc zapis
    `status = 'scheduled'` trafia na wąski CHECK z 0233 wszędzie tam, gdzie
    poszerzenie z 0238 jeszcze nie weszło (świeża baza, osierocony alembic).
    Wyjątek wywraca CAŁY blok DO — razem z aktywacją kontraktu i markerem —
    a w logu zostaje jedna linijka „backfill data skip"; `/api/health` jest
    wtedy zielony, więc regresja jest CICHA i to jest jedyne miejsce, w którym
    da się ją złapać przed produkcją.
    """

    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    block = entrypoint.split("DO $contract_order_backfill$", 1)[1].split(
        "$contract_order_backfill$;", 1
    )[0]

    widen = block.find("ADD CONSTRAINT ck_client_order_groups_status")
    write = block.find("SET status = 'scheduled'")

    assert widen != -1, "0239 zapisuje 'scheduled' bez lustra poszerzonego CHECK-a"
    assert write != -1, "blok 0239 przestał ustawiać status grupy na 'scheduled'"
    assert widen < write, "poszerzenie CHECK-a musi poprzedzać zapis 'scheduled'"

    # Poszerzenie ma być idempotentne i faktycznie dopuszczać nową wartość:
    # sam ADD bez DROP-a wywróciłby się na istniejącym więzie o tej nazwie.
    assert "DROP CONSTRAINT IF EXISTS ck_client_order_groups_status" in block
    assert "'scheduled'" in block[widen:write]


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
