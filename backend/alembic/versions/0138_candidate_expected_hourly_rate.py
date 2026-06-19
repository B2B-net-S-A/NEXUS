"""Candidates: oczekiwana stawka godzinowa (expected_rate_hourly).

Revision ID: 0138_candidate_expected_hourly_rate
Revises: 0137_talent_pool_is_personal
Create Date: 2026-06-19

Dodaje oczekiwaną stawkę godzinową kandydata (B2B, PLN/h) jako osobne pole
obok miesięcznego ``salary_expectation``:
  * ``expected_rate_hourly``  — INTEGER, stawka godzinowa (np. 120, 200).
  * ``expected_rate_currency``— VARCHAR(3), domyślnie 'PLN'.

Napędza filtr „Stawka godzinowa (od–do)" na /candidates
(``GET /api/candidates?min_rate=&max_rate=``) oraz edycję w profilu kandydata.
Indeks częściowy (WHERE NOT NULL) wspiera zakresowy filtr bez kosztu na
~49,8k wierszy bez stawki.

Idempotent: ADD COLUMN / CREATE INDEX IF NOT EXISTS — współgra z DEBUG
``Base.metadata.create_all`` oraz z entrypoint safety-net (entrypoint.sh).
"""

from alembic import op

revision = "0138_candidate_expected_hourly_rate"
down_revision = "0137_talent_pool_is_personal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS expected_rate_hourly INTEGER"
    )
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS expected_rate_currency VARCHAR(3)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_expected_rate_hourly "
        "ON candidates (expected_rate_hourly) "
        "WHERE expected_rate_hourly IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidates_expected_rate_hourly")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS expected_rate_currency")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS expected_rate_hourly")
