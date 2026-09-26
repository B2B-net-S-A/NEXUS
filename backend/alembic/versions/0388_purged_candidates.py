"""Nagrobki usuniętych kandydatów — sync Traffita nie odtwarza osoby (RODO).

Revision ID: 0388_purged_candidates
Revises: 0387_keyword_fold_combining

Runda 6 audytu (RODO-01): ``DELETE /api/candidates/{id}`` kasował wiersz, a
nocny import ``/employees/`` wstawiał tę osobę od nowa (za nią etapy, notatki
i pliki). Tabela trzyma wyłącznie źródło i kluczowany HMAC identyfikatora
źródłowego — bez danych osobowych. Lustro w ``entrypoint.sh`` (prod alembic
bywa osierocony) — pilnuje ``tests/test_purged_candidates_migration_mirror.py``.
"""

from alembic import op

revision = "0388_purged_candidates"
down_revision = "0387_keyword_fold_combining"
branch_labels = None
depends_on = None

CREATE_PURGED_CANDIDATES = """CREATE TABLE IF NOT EXISTS purged_candidates (
    id BIGSERIAL PRIMARY KEY,
    external_source VARCHAR(50) NOT NULL,
    external_id_hash VARCHAR(64) NOT NULL,
    purged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_purged_candidates_source_hash UNIQUE (external_source, external_id_hash)
)"""

DDL_STATEMENTS = [CREATE_PURGED_CANDIDATES]


def upgrade() -> None:
    for statement in DDL_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS purged_candidates")
