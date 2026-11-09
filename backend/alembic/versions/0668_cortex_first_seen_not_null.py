"""cortex_unmatched_terms.first_seen_at: uzupełnienie, domyślna now(), NOT NULL.

Revision ID: 0668_cortex_first_seen_not_null
Revises: 0667_drop_abandoned_tables

Model od 0167 deklaruje NOT NULL z domyślną, a kolumna powstała bez obu. Lustro
w ``entrypoint.sh`` robiło samo ADD COLUMN, więc na kopii produkcji z 08.11.2026
NULL miało 73 935 z 73 935 wierszy. Najlepszym przybliżeniem pierwszego
wystąpienia jest ``last_seen_at``.

Domyślna idzie przed UPDATE, żeby kontener ze starym kodem nie dopisał NULL-a
między uzupełnieniem a NOT NULL. Warunek na ``is_nullable`` jest po to, żeby
lustro przy kolejnych startach nie brało blokady na tabeli bez potrzeby.
"""

from alembic import op

revision = "0668_cortex_first_seen_not_null"
down_revision = "0667_drop_abandoned_tables"
branch_labels = None
depends_on = None

# Ten sam tekst stoi w `_COLUMN_STATEMENTS` w entrypoint.sh.
FILL_AND_REQUIRE_FIRST_SEEN = """DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'cortex_unmatched_terms'
              AND column_name = 'first_seen_at'
              AND is_nullable = 'YES'
        ) THEN
            ALTER TABLE cortex_unmatched_terms
                ALTER COLUMN first_seen_at SET DEFAULT now();
            UPDATE cortex_unmatched_terms
                SET first_seen_at = last_seen_at
                WHERE first_seen_at IS NULL;
            ALTER TABLE cortex_unmatched_terms
                ALTER COLUMN first_seen_at SET NOT NULL;
        END IF;
    END $$"""


def upgrade() -> None:
    op.execute(FILL_AND_REQUIRE_FIRST_SEEN)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cortex_unmatched_terms ALTER COLUMN first_seen_at DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE cortex_unmatched_terms ALTER COLUMN first_seen_at DROP DEFAULT"
    )
