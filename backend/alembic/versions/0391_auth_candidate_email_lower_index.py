"""Indeks wyrażeniowy pod dopasowanie kandydata po adresie w M365.

Revision ID: 0391_auth_candidate_email_lower_index
Revises: 0390_cand_retained_candidate_files

Runda 10 audytu (R10-V3-3). Po R9-N10-8 dopasowanie maila i uczestnika
spotkania z Outlooka do kandydata porównuje ``lower(btrim(email))`` —
adres w bazie bywa z wielkimi literami albo spacją z importu. Indeks
``ix_candidates_email`` jest na gołej kolumnie, więc każda wiadomość
z delty M365 czytała całą tabelę ``candidates``. Wyrażenie w zapytaniu
(`services/m365/matcher.py`, `services/m365/sync.py`) musi być dokładnie
tym z indeksu — pilnuje ``tests/test_candidate_email_lower_index.py``.

CONCURRENTLY — ``candidates`` to gorąca tabela (nocny import Traffita).
Lustro w `entrypoint.sh` (`_INDEX_STATEMENTS`) — prod alembic bywa
osierocony.
"""

from alembic import op

revision = "0391_auth_candidate_email_lower_index"
down_revision = "0390_cand_retained_candidate_files"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_candidates_email_lower_btrim"
INDEX_DDL = (
    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
    "ON candidates (lower(btrim(email)))"
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(INDEX_DDL)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
