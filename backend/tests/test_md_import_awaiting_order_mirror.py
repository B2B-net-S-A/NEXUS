"""0492: status „Oczekuje na zamówienie” i jego kolumny mają lustro w entrypoincie.

Prod alembic bywa osierocony — ``entrypoint.sh`` JEST wdrożeniem. Bez lustra
import MD pada na produkcji (``UndefinedColumnError`` przy ``md_pending``,
naruszenie CHECK przy statusie ``awaiting_order``), a w CI, gdzie działa
migracja, wszystko jest zielone.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0492_md_import_awaiting_order.py"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0492", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _entrypoint_text() -> str:
    raw = (BACKEND / "entrypoint.sh").read_text()
    return _collapse(re.sub(r'"\s*\n\s*"', "", raw))


def test_columns_and_index_are_mirrored_in_entrypoint():
    module = _migration_module()
    entrypoint = _entrypoint_text()
    for sql in (module.ADD_ORIGIN, module.ADD_PENDING, module.ADD_INDEX):
        assert _collapse(sql) in entrypoint


def test_migration_statuses_match_the_model():
    from app.models.md_consumption import IMPORT_ROW_STATUSES

    statuses = set(re.findall(r"'([a-z_]+)'", _migration_module().STATUSES))
    assert statuses == set(IMPORT_ROW_STATUSES)
