"""Migracja 0278 i jej lustro w ``entrypoint.sh`` muszą się zgadzać.

Prod alembic bywa osierocony (patrz CLAUDE.md) — ``entrypoint.sh`` niesie
safety-net DDL wykonywany na KAŻDYM starcie kontenera i jest realnym
wdrożeniem. Kolumny, DROP-y i cztery jednorazowe naprawy danych (S1-S4)
migracji 0278 muszą więc mieć DOKŁADNIE ten sam kształt po obu stronach —
rozjazd znaczyłby, że produkcja robi coś innego niż to, co przeszło review.

Ten kontrakt czyta OBIE strony ze źródeł (AST, nie ręcznie wpisana lista):
- ``op.execute(...)`` w ``upgrade()`` migracji — sparsowane, bez wykonania.
- elementy list ``_COLUMN_STATEMENTS`` / ``_DATA_STATEMENTS`` w heredocu
  Pythona osadzonym w ``entrypoint.sh`` — sparsowane, bez wykonania (świadomie
  NIE importujemy tego heredocu jako modułu: ``test_entrypoint_ddl_guards.py``
  robi to i przy okazji podmienia ``sys.modules["asyncpg"]`` atrapą bez
  sprzątania, co zatruwa testy z bazą uruchomione w tej samej sesji pytest).

Statementy porównujemy po normalizacji białych znaków (``_shape``) — ta sama
treść SQL ma różną indentację w migracji (wewnątrz funkcji) i w mirrorze
(element listy modułowej), więc porównanie bajt-w-bajt fałszywie by padało.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

from app.services.champion_job_sync import WORK_MODE_PREFIXES

_BACKEND = Path(__file__).resolve().parents[1]
_MIGRATION_PATH = (
    _BACKEND / "alembic" / "versions" / "0278_office_presence_rubric.py"
)
_ENTRYPOINT_PATH = _BACKEND / "entrypoint.sh"

_S1_ON_SITE_MARKER = "? 'on_site'"
_S2_MARKER_KEY = "0278_traffit_remote_policy_unstamped"
_S3_MARKER_KEY = "0278_champion_basics_to_job_columns"
_S4_MARKER_KEY = "0278_remote_only_onsite_days_zero"

_CANDIDATES_ADD_COLUMN = (
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS "
    "max_onsite_days_per_week INTEGER NULL"
)
_JOBS_ADD_COLUMN = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS onsite_days_per_week INTEGER NULL"
)
_DROP_NOT_NULL = "ALTER TABLE jobs ALTER COLUMN remote_policy DROP NOT NULL"
_DROP_DEFAULT = "ALTER TABLE jobs ALTER COLUMN remote_policy DROP DEFAULT"


def _shape(text: str) -> str:
    """Collapse whitespace so multi-line SQL compares on tokens, not layout."""
    return " ".join(text.split())


def _literal_or_none(node: ast.expr) -> Optional[str]:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _migration_upgrade_statements() -> list[str]:
    """``op.execute(...)`` argument strings from 0278's ``upgrade()``, in order.

    Parsed via AST — never imported/executed. ``ast.literal_eval`` resolves
    adjacent string-literal concatenation and raw-string prefixes exactly
    like the real interpreter would, without running any code.
    """
    tree = ast.parse(_MIGRATION_PATH.read_text(encoding="utf-8"))
    upgrade_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    )
    statements: list[str] = []
    for stmt in upgrade_fn.body:
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            continue
        call = stmt.value
        func = call.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "execute"
            and isinstance(func.value, ast.Name)
            and func.value.id == "op"
        ):
            continue
        if not call.args:
            continue
        literal = _literal_or_none(call.args[0])
        if literal is not None:
            statements.append(literal)
    return statements


def _heredoc_source() -> str:
    """Extract the "column backfill" Python heredoc body — text only, no exec.

    Same line-search as ``test_entrypoint_ddl_guards._load_backfill_module``,
    deliberately NOT shared with it: that helper imports the block as a real
    module and stubs ``asyncpg`` as a side effect, which is safe only when it
    is the sole consumer of the module. This test only needs the source text.
    """
    lines = _ENTRYPOINT_PATH.read_text(encoding="utf-8").split("\n")
    start = next(
        i + 1
        for i, line in enumerate(lines)
        if line.startswith("python - <<'PY'") and "column backfill" in line
    )
    end = start
    while lines[end] != "PY":
        end += 1
    return "\n".join(lines[start:end])


def _list_elements(module_source: str, list_name: str) -> list[ast.expr]:
    tree = ast.parse(module_source)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == list_name
            and isinstance(node.value, ast.List)
        ):
            return node.value.elts
    raise AssertionError(f"entrypoint.sh: brak listy {list_name}")


def _entrypoint_column_statements() -> list[str]:
    source = _heredoc_source()
    return [
        s
        for s in (_literal_or_none(e) for e in _list_elements(source, "_COLUMN_STATEMENTS"))
        if s is not None
    ]


def _entrypoint_data_elements() -> list[ast.expr]:
    return _list_elements(_heredoc_source(), "_DATA_STATEMENTS")


def _entrypoint_data_statements() -> list[str]:
    return [
        s for s in (_literal_or_none(e) for e in _entrypoint_data_elements()) if s is not None
    ]


def _find_containing(statements: list[str], needle: str, *, label: str) -> str:
    for stmt in statements:
        if needle in stmt:
            return stmt
    raise AssertionError(f"{label}: żaden statement nie zawiera {needle!r}")


def test_entrypoint_mirrors_both_columns():
    migration = _migration_upgrade_statements()
    entrypoint = _entrypoint_column_statements()

    for expected in (_CANDIDATES_ADD_COLUMN, _JOBS_ADD_COLUMN):
        assert any(_shape(s) == _shape(expected) for s in migration), (
            f"migracja 0278: brak {expected!r}"
        )
        assert any(_shape(s) == _shape(expected) for s in entrypoint), (
            f"entrypoint.sh: brak lustra {expected!r}"
        )


def test_entrypoint_drops_remote_policy_not_null_and_default():
    migration = _migration_upgrade_statements()
    entrypoint = _entrypoint_column_statements()

    for expected in (_DROP_NOT_NULL, _DROP_DEFAULT):
        assert any(_shape(s) == _shape(expected) for s in migration), (
            f"migracja 0278: brak {expected!r}"
        )
        assert any(_shape(s) == _shape(expected) for s in entrypoint), (
            f"entrypoint.sh: brak lustra {expected!r}"
        )


def test_marker_guarded_fixes_match_migration():
    """S2/S3/S4 są jednorazowe: marker key, ON CONFLICT DO NOTHING, EXISTS guard."""
    migration = _migration_upgrade_statements()
    entrypoint = _entrypoint_data_statements()

    for marker_key in (_S2_MARKER_KEY, _S3_MARKER_KEY, _S4_MARKER_KEY):
        for label, statements in (("migracja 0278", migration), ("entrypoint.sh", entrypoint)):
            stmt = _shape(_find_containing(statements, marker_key, label=label))
            assert marker_key in stmt, f"{label}: {marker_key} bez markera"
            assert "ON CONFLICT (key) DO NOTHING" in stmt, (
                f"{label}: {marker_key} — insert markera nie jest idempotentny"
            )
            assert "EXISTS (SELECT 1 FROM marker)" in stmt, (
                f"{label}: {marker_key} — fix nie jest zabramkowany markerem"
            )


def test_on_site_fix_is_predicate_idempotent():
    """S1 (`on_site` -> `onsite`) jest idempotentny sam z siebie — bez markera."""
    migration = _migration_upgrade_statements()
    entrypoint = _entrypoint_data_statements()

    for label, statements in (("migracja 0278", migration), ("entrypoint.sh", entrypoint)):
        stmt = _find_containing(statements, _S1_ON_SITE_MARKER, label=label)
        assert "app_settings" not in stmt, (
            f"{label}: S1 (on_site->onsite) nie powinien mieć markera — "
            "predykat jest sam z siebie idempotentny"
        )


def test_hybrid_unstamp_runs_before_champion_backfill():
    """S2 (odstemplowanie Traffita) MUSI wykonać się przed S3 (backfill Championa).

    Inaczej odstemplowanie i backfill rywalizowałyby o tę samą kolumnę
    (`remote_policy`) w nieprzewidywalnej kolejności.
    """
    migration_statements = _migration_upgrade_statements()
    s2_idx_migration = next(
        i for i, s in enumerate(migration_statements) if _S2_MARKER_KEY in s
    )
    s3_idx_migration = next(
        i for i, s in enumerate(migration_statements) if _S3_MARKER_KEY in s
    )
    assert s2_idx_migration < s3_idx_migration, (
        "migracja 0278: S3 (backfill Championa) wykonuje się przed S2 (unstamp)"
    )

    # Kolejność w liście `_DATA_STATEMENTS` == kolejność wykonania w pętli
    # entrypointu — pozycja w `elts` (nie tylko wśród elementów literalnych)
    # jest tym, co faktycznie decyduje o kolejności na produkcji.
    data_elements = _entrypoint_data_elements()
    s2_idx_entrypoint = next(
        i
        for i, e in enumerate(data_elements)
        if (lit := _literal_or_none(e)) is not None and _S2_MARKER_KEY in lit
    )
    s3_idx_entrypoint = next(
        i
        for i, e in enumerate(data_elements)
        if (lit := _literal_or_none(e)) is not None and _S3_MARKER_KEY in lit
    )
    assert s2_idx_entrypoint < s3_idx_entrypoint, (
        "entrypoint.sh: S3 (backfill Championa) wykonuje się przed S2 (unstamp)"
    )


def test_sql_work_mode_prefixes_match_python_map():
    """`champion_job_sync.WORK_MODE_PREFIXES` musi zgadzać się z CASE...LIKE w SQL S3."""
    migration = _migration_upgrade_statements()
    entrypoint = _entrypoint_data_statements()

    pattern = re.compile(r"LIKE '([a-z]+)%' THEN '([a-z]+)'::remotepolicy")
    for label, statements in (("migracja 0278", migration), ("entrypoint.sh", entrypoint)):
        stmt = _shape(_find_containing(statements, _S3_MARKER_KEY, label=label))
        found = dict(pattern.findall(stmt))
        assert found, f"{label}: S3 nie ma żadnego CASE WHEN ... LIKE ... THEN"
        assert found == WORK_MODE_PREFIXES, (
            f"{label}: prefiksy SQL {found} != champion_job_sync.WORK_MODE_PREFIXES "
            f"{WORK_MODE_PREFIXES}"
        )
