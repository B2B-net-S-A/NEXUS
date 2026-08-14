"""Kontrakt migracji 0227 — lustra, bez których zmiana nie dojdzie na produkcję.

Testy czytają PLIKI jako tekst, nie bazę. Powód: produkcyjny alembic bywa
osierocony, więc każda zmiana schematu musi mieć odbicie w ``entrypoint.sh``,
a każda nowa tabela — sondę w ``/api/health/deep``. Bez nich deploy świeci na
zielono, a endpoint wywala ``UndefinedTable`` (tryb awarii z incydentu Cortexa).
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0227_multi_consultant_orders.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
MAIN = BACKEND / "app" / "main.py"

NEW_TABLES = (
    "client_order_groups",
    "client_order_group_events",
    "client_order_md_consumptions",
    "md_consumption_imports",
    "md_consumption_import_rows",
)

NEW_COLUMNS = (
    "order_group_id",
    "md_rate_cost",
    "md_rate_revenue",
    "md_input_mode",
    "md_input_value",
    "md_total",
    "md_remaining",
    "md_manual_adjustment",
    "predecessor_order_id",
)


def test_migration_chains_onto_the_single_head():
    """Nowa migracja wisi na 0226 i nie tworzy drugiej głowy."""
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(
                    node.value, ast.Constant
                ):
                    values[target.id] = node.value.value
    assert values["revision"] == "0227_multi_consultant_orders"
    assert values["down_revision"] == "0226_b2b_generated_contract_suspended"


def test_only_one_alembic_head():
    """Nowa migracja nie rozszczepia łańcucha.

    Parser jest POŻYCZONY z ``test_analytics_release_gates`` zamiast napisany
    od nowa: własna, uboższa wersja (sam ``ast.Assign``, bez ``AnnAssign``
    i wieloliniowych krotek) raportuje kilka widmowych głów i myli
    „nie umiem tego przeczytać" z „to jest nowa głowa".
    """
    from tests.test_analytics_release_gates import _alembic_heads

    assert _alembic_heads() == ["0227_multi_consultant_orders"]


def test_entrypoint_mirrors_every_new_table():
    """Produkcyjny alembic bywa osierocony — bez lustra tabele nie powstaną."""
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in entrypoint, table


def test_entrypoint_mirrors_every_new_column():
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    for column in NEW_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in entrypoint, column


def test_entrypoint_mirrors_the_md_coherence_check():
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "ck_client_orders_md_coherence" in entrypoint


def test_md_check_is_added_as_not_valid_in_both_places():
    """``NOT VALID`` po obu stronach — inaczej migracja skanuje całą tabelę.

    Bez tego Postgres weryfikuje wiersze, które z definicji spełniają warunek
    (wszystkie kolumny MD są świeże, więc NULL), trzymając przez ten czas
    ACCESS EXCLUSIVE na `client_orders`.
    """
    for source in (MIGRATION, ENTRYPOINT):
        text = source.read_text(encoding="utf-8")
        head, _, tail = text.partition("ck_client_orders_md_coherence")
        assert tail, source.name
        assert "NOT VALID" in tail, f"{source.name}: CHECK dodany bez NOT VALID"


def test_entrypoint_keeps_consumption_uniqueness():
    """UNIQUE (order_id, period_month) JEST mechanizmem idempotencji importu.

    Zwykły indeks zamiast unikalnego przepuściłby drugi wiersz na ten sam
    miesiąc, a MD odjęłyby się dwa razy — cicho i nieodwracalnie.
    """
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_md_consumptions_order_month" in (
        entrypoint
    )
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "unique=True" in migration


def test_health_deep_probes_every_new_table():
    main = MAIN.read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'"{table}"' in main, table


def test_migration_downgrade_drops_what_it_created():
    """Bramka CI robi round trip downgrade→upgrade — niepełny downgrade go wywali."""
    migration = MIGRATION.read_text(encoding="utf-8")
    downgrade = migration.split("def downgrade()")[1]
    for table in NEW_TABLES:
        assert f'"{table}"' in downgrade, table
    for column in NEW_COLUMNS:
        assert f'"{column}"' in downgrade, column
