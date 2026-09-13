"""Backfill `candidate_documents.document_kind = 'cv'` nie przepisuje wierszy, które już są CV.

`_DATA_STATEMENTS` w `entrypoint.sh` leci przy KAŻDYM starcie kontenera. Ten
UPDATE nie ma markera jednorazowości (i mieć nie musi — nowe dokumenty mogą się
kwalifikować później), więc jedynym hamulcem jest predykat na kolumnie, którą
zapisuje. Bez niego Postgres przepisywał ~136 tys. krotek na każdy deploy.
Test czyta plik jako tekst (jak `test_rejection_reason_disqualifies.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

_ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _document_kind_update() -> str:
    source = _ENTRYPOINT.read_text(encoding="utf-8")
    match = re.search(
        r"UPDATE candidate_documents AS document\s+SET document_kind = 'cv'"
        r"[\s\S]*?\"\"\"",
        source,
    )
    assert match, "brak backfillu document_kind='cv' w entrypoint.sh"
    return match.group(0)


def test_document_kind_backfill_skips_rows_already_marked_as_cv() -> None:
    statement = _document_kind_update()
    assert "document.document_kind IS DISTINCT FROM 'cv'" in statement


def test_guard_sits_in_the_where_clause_not_in_a_comment() -> None:
    statement = _document_kind_update()
    where = statement.split("WHERE", 1)[1]
    assert "IS DISTINCT FROM 'cv'" in where
