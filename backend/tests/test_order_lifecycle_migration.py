"""Kontrakt migracji 0231 — lustra, bez których zmiana nie dojdzie na produkcję.

Testy czytają PLIKI jako tekst, nie bazę. Powód ten sam co przy 0227:
produkcyjny alembic bywa osierocony, więc każda zmiana schematu musi mieć
odbicie w ``entrypoint.sh``, a każda nowa tabela — sondę w ``/api/health/deep``.
Bez nich deploy świeci na zielono, a pierwszy ruch wywala ``UndefinedTable``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0231_order_lifecycle_cost_and_dl_alerts.py"
)
ENTRYPOINT = BACKEND / "entrypoint.sh"
MAIN = BACKEND / "app" / "main.py"

NEW_TABLES = ("client_order_invoice_consumptions", "dl_alerts")

NEW_COLUMNS = (
    "status",
    "closure_date",
    "closure_reason",
    "closed_at",
    "closed_by_user_id",
    "is_cost_based",
    "budget_amount",
    "budget_remaining",
    "budget_manual_adjustment",
    "predecessor_group_id",
    "notes_raw",
    "order_number_hint",
    "invoice_amount",
    "matched_group_id",
    "cost_status",
    "rows_cost_applied",
    "rows_cost_unmatched",
)


def _flat(text: str) -> str:
    """Źródło z sklejonymi literałami → jeden ciąg do przeszukania.

    Instrukcje DDL w ``entrypoint.sh`` są łamane na kilka literałów Pythona
    (``"ALTER TABLE … ADD COLUMN IF NOT EXISTS "`` + ``"status VARCHAR(16)…"``),
    więc szukanie surowego podciągu myliłoby BRAK lustra z ZAWINIĘTĄ linią —
    i test świeciłby na czerwono za formatowanie.
    """
    return re.sub(r"\s+", " ", text.replace('"', ""))


def test_migration_chains_onto_the_single_head():
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(
                    node.value, ast.Constant
                ):
                    values[target.id] = node.value.value
    assert values["revision"] == "0231_order_lifecycle_cost_and_dl_alerts"
    assert values["down_revision"] == "0230_notes_extraction_ai_feature"


def test_only_one_alembic_head():
    """Liczba głów, NIE nazwa czubka — inaczej test pada przy każdej kolejnej
    migracji w repo, niezależnie od tego, czy cokolwiek się rozszczepiło."""
    from tests.test_analytics_release_gates import _alembic_heads

    heads = _alembic_heads()
    assert len(heads) == 1, f"łańcuch rozszczepiony, głowy: {heads}"

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
    assert "0231_order_lifecycle_cost_and_dl_alerts" in referenced


def test_entrypoint_mirrors_every_new_table():
    entrypoint = _flat(ENTRYPOINT.read_text(encoding="utf-8"))
    for table in NEW_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in entrypoint, table


def test_entrypoint_mirrors_every_new_column():
    entrypoint = _flat(ENTRYPOINT.read_text(encoding="utf-8"))
    for column in NEW_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in entrypoint, column


def test_health_deep_probes_every_new_table():
    """Bez sondy brak tabeli wyjdzie dopiero przy pierwszym imporcie faktur
    albo pierwszym przebiegu skanera — długo po zielonym deployu."""
    main = MAIN.read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'("{table}"' in main, table


def test_widened_checks_use_drop_then_add_not_exception_swallowing():
    """Poszerzana domena MUSI przejść przez DROP.

    Samo ``EXCEPTION WHEN duplicate_object`` zostawia na produkcji stary,
    węższy CHECK i pierwsza nowa wartość leci IntegrityError — dokładnie błąd,
    który naprawiała migracja 0226.
    """
    entrypoint = _flat(ENTRYPOINT.read_text(encoding="utf-8"))
    for constraint in (
        "ck_client_order_group_events_type",
        "ck_client_orders_md_coherence",
        "ck_client_order_groups_status",
        "ck_client_order_groups_cost_coherence",
    ):
        assert f"DROP CONSTRAINT IF EXISTS {constraint}" in entrypoint, constraint


def test_new_event_types_are_in_both_the_migration_and_the_mirror():
    migration = MIGRATION.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    for event in (
        "zakonczenie",
        "przywrocenie",
        "wyczerpanie",
        "przedluzenie",
        "import_faktur",
    ):
        assert event in migration, f"{event} brakuje w migracji"
        assert event in entrypoint, f"{event} brakuje w lustrze entrypointu"


def test_invoice_consumption_has_the_idempotency_index_in_both_places():
    """UNIQUE (order_id, period_month) JEST mechanizmem idempotencji importu.

    Tabela bez niego przez jeden boot przyjęłaby duplikaty, których potem nie
    da się już wstawić — a budżet zszedłby dwa razy.
    """
    migration = _flat(MIGRATION.read_text(encoding="utf-8"))
    entrypoint = _flat(ENTRYPOINT.read_text(encoding="utf-8"))
    assert "ux_invoice_consumptions_order_month" in migration
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_consumptions_order_month"
        in entrypoint
    )


def test_dl_alerts_dedupe_key_is_unique_in_both_places():
    """Klucz claimu — bez UNIQUE `ON CONFLICT DO NOTHING` nic nie tłumi
    powtórek i skaner mnożyłby alerty przy każdym przebiegu."""
    migration = _flat(MIGRATION.read_text(encoding="utf-8"))
    entrypoint = _flat(ENTRYPOINT.read_text(encoding="utf-8"))
    assert "uq_dl_alerts_dedupe_key" in migration
    assert "CONSTRAINT uq_dl_alerts_dedupe_key UNIQUE (dedupe_key)" in entrypoint
