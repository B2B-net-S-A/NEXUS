"""Trwały wpis w zespole dla osób dodanych z pulpitu (0429, 12.10.2026).

Lustro migracji w ``entrypoint.sh`` (prod alembic bywa osierocony) i kształt
jednorazowego uzupełnienia: tylko aktywne RĘCZNE przypisania osób, które nie są
prowadzącym; wiersz ``auto_cc`` staje się ręczny; drugi bieg nic nie robi.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0429_recruiter_member_backfill.py"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration():
    spec = importlib.util.spec_from_file_location("m0429", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_job_files_and_is_mirrored() -> None:
    module = _migration()
    assert module.revision == "0429_recruiter_member_backfill"
    assert module.down_revision == "0428_job_files"
    raw = (BACKEND / "entrypoint.sh").read_text()
    assert _collapse(module.BACKFILL) in _collapse(raw)


def test_backfill_takes_only_manual_assignments_of_people_who_are_not_the_owner() -> (
    None
):
    sql = _collapse(_migration().BACKFILL)
    assert "a.state = 'active'" in sql
    # Przypisań automatu nie utrwalamy — automat zwalnia je za urlop.
    assert "a.source = 'manual'" in sql
    assert "j.recruiter_id IS DISTINCT FROM a.user_id" in sql
    assert "u.is_active" in sql
    # Jednorazowo: bez znacznika nic się nie wstawia.
    assert "'0429_recruiter_member_backfill'" in sql
    assert "AND EXISTS (SELECT 1 FROM marker)" in sql


def test_backfill_promotes_category_rows_and_leaves_manual_ones() -> None:
    sql = _collapse(_migration().BACKFILL)
    assert "ON CONFLICT (job_id, user_id) DO UPDATE" in sql
    assert "removed_from_auto_cc = false" in sql
    assert (
        "WHERE job_collaborators.source <> 'manual'::jobcollaboratorsource "
        "OR job_collaborators.removed_from_auto_cc" in sql
    )
