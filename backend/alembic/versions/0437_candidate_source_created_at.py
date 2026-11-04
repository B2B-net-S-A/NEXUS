"""Kandydat: data dodania u źródła — „W bazie od” (13.10.2026).

Revision ID: 0437_candidate_source_created_at
Revises: 0436_candidate_name_markers

Import z Traffita stemplował `candidates.created_at = NOW()`, więc 65 tys.
osób miało w bazie dzień importu (16.04 i 04.05.2026) zamiast dnia, w którym
trafiły do Traffita. `source_created_at` trzyma datę dodania u źródła
(Traffit `created_at`); „w bazie od” to `LEAST(created_at, source_created_at)`
(`app/services/candidate_added_date.py`). `created_at` zostaje czasem
wstawienia do NEXUSA — import liczy z niego ponowienia plików.

Indeks wyrażeniowy obsługuje sortowanie listy „Najnowsi” / „Najstarsi”.

Lustro DDL: `_COLUMN_STATEMENTS` i `_INDEX_STATEMENTS` w `entrypoint.sh`.
"""

from alembic import op

revision = "0437_candidate_source_created_at"
down_revision = "0436_candidate_name_markers"
branch_labels = None
depends_on = None

_ADDED_TO_BASE_INDEX = "ix_candidates_added_to_base_id"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS source_created_at TIMESTAMPTZ"
    )
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_ADDED_TO_BASE_INDEX} "
            "ON candidates ((LEAST(created_at, source_created_at)) DESC, id DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_ADDED_TO_BASE_INDEX}")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS source_created_at")
