"""0375: kolumna ``overflow_md`` i status ``overflow`` mają lustro w entrypoincie.

Prod alembic bywa osierocony — ``entrypoint.sh`` JEST wdrożeniem. Bez lustra
import MD pada na produkcji (``UndefinedColumnError`` przy ``overflow_md``,
naruszenie CHECK przy statusie ``overflow``), a w CI, gdzie działa migracja,
wszystko jest zielone.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0375_md_import_row_overflow.py"
CONSTRAINT = "ck_md_import_rows_status"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0375", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _entrypoint_text() -> str:
    raw = (BACKEND / "entrypoint.sh").read_text()
    return _collapse(re.sub(r'"\s*\n\s*"', "", raw))


def _statuses(sql: str) -> set[str]:
    return set(re.findall(r"'([a-z_]+)'", sql))


def test_migration_chains_after_trainee_call_lists():
    module = _migration_module()
    assert module.revision == "0375_md_import_row_overflow"
    assert module.down_revision == "0374_trainee_call_lists"


def test_overflow_column_is_mirrored_in_entrypoint():
    assert _collapse(_migration_module().ADD_OVERFLOW_MD) in _entrypoint_text()


def test_migration_statuses_match_the_model():
    from app.models.md_consumption import IMPORT_ROW_STATUSES

    assert _statuses(_migration_module().STATUSES) == set(IMPORT_ROW_STATUSES)


def test_entrypoint_widens_the_status_check_after_dropping_it():
    """Ostatnie ``ADD CONSTRAINT`` w entrypoincie zna każdy status modelu
    i stoi po ``DROP`` — inaczej na istniejącej bazie zostaje stary CHECK
    (``CREATE TABLE IF NOT EXISTS`` niesie tylko trzy pierwsze statusy)."""
    from app.models.md_consumption import IMPORT_ROW_STATUSES

    entrypoint = _entrypoint_text()
    drop = entrypoint.rfind(f"DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    add = entrypoint.rfind(f"ADD CONSTRAINT {CONSTRAINT}")
    assert drop != -1 and add != -1
    assert drop < add
    match = re.match(
        r"ADD CONSTRAINT \w+ CHECK \(status IN \(([^)]*)\)\)", entrypoint[add:]
    )
    assert match is not None, entrypoint[add : add + 200]
    assert _statuses(match.group(1)) == set(IMPORT_ROW_STATUSES)
