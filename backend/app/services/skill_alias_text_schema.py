"""Znacznik „liczy się w tekście CV” przy wariancie nazwy — SQL migracji 0659
i lustra w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).

``skill_aliases.in_text``: ``NULL`` = reguła domyślna
(``skill_normalize.alias_counts_in_text``), ``TRUE``/``FALSE`` = decyzja osoby
prowadzącej „Słownik umiejętności”.
"""

from __future__ import annotations

COLUMN_DDL = (
    "ALTER TABLE skill_aliases ADD COLUMN IF NOT EXISTS in_text BOOLEAN NULL",
)

DOWNGRADE_DDL = ("ALTER TABLE skill_aliases DROP COLUMN IF EXISTS in_text",)
