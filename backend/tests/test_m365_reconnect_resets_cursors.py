"""Ponowne połączenie M365 musi zerować ŻYWE kursory delty (per-folder).

Regresja jest cicha i trwała. `delta_token_messages` jest martwe od Fazy 2.5 —
zerowanie samej tej kolumny zostawiało wypełnione `delta_token_inbox`
i `delta_token_sent`, więc `_sync_messages` nie widział ani jednego folderu
w trybie „pierwszy raz", `any_backfill` było `False`, a `backfill_completed_at`
(jedyny pisarz siedzi w tym bloku) nigdy nie było stemplowane ponownie.
Skutek: karta Microsoft 365 zostaje na zawsze ze spinnerem „Pobieramy
historię" i wyszarzonym „Synchronizuj teraz" — czyli z zablokowaną ręczną
furtką awaryjną, na którą wskazuje dokumentacja.

Test czyta gałąź reconnect z AST, bo jedyną alternatywą jest przejście pełnego
flow OAuth; nazwy kolumn są tu całym kontraktem.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SOURCE = BACKEND / "app" / "api" / "microsoft365.py"

# Kursory, których faktycznie używa `app/services/m365/sync.py`.
LIVE_CURSORS = {"delta_token_inbox", "delta_token_sent"}


def _reconnect_branch_assignments() -> dict[str, ast.AST]:
    """Przypisania do `existing.*` z gałęzi `else` upsertu połączenia."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # `if existing is None: ... else: <reconnect>`
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "existing"
            and isinstance(test.ops[0], ast.Is)
        ):
            continue
        found: dict[str, ast.AST] = {}
        for stmt in ast.walk(ast.Module(body=node.orelse, type_ignores=[])):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "existing"
                ):
                    found[target.attr] = stmt.value
        if "backfill_completed_at" in found:
            return found
    raise AssertionError("nie znalazłem gałęzi reconnect w microsoft365.py")


def test_reconnect_zeruje_oba_kursory_per_folder():
    assigned = _reconnect_branch_assignments()
    for column in LIVE_CURSORS:
        assert column in assigned, f"{column} nie jest zerowane przy reconnect"
        value = assigned[column]
        assert isinstance(value, ast.Constant) and value.value is None, column


def test_reconnect_nadal_resetuje_znacznik_backfillu():
    assigned = _reconnect_branch_assignments()
    value = assigned["backfill_completed_at"]
    assert isinstance(value, ast.Constant) and value.value is None


def test_kursory_per_folder_to_te_ktore_czyta_sync():
    """Kontrakt z `sync.py`: gdyby doszedł trzeci folder, ten test upadnie."""
    sync = (BACKEND / "app" / "services" / "m365" / "sync.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(sync)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("delta_token_")
    }
    assert literals == LIVE_CURSORS, literals
