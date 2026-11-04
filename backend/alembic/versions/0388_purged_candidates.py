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


# Runda 8 (R8-N15-1): downgrade odmawia, gdy są nagrobki. Po `DROP TABLE`
# i ponownym upgrade tabela wracała pusta, a nocny sync Traffita zakładał
# usuniętych kandydatów od nowa (razem z etapami, notatkami i plikami).
# Zagnieżdżony IF, bo PL/pgSQL planuje wyrażenie w całości — zapytanie
# o nieistniejącą tabelę padłoby mimo `to_regclass` obok.
REFUSE_WITH_TOMBSTONES = """DO $$
BEGIN
    IF to_regclass('purged_candidates') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM purged_candidates) THEN
            RAISE EXCEPTION 'Downgrade 0388 odmawia: purged_candidates ma nagrobki usuniętych kandydatów. Bez nich nocny sync Traffita odtworzy te osoby. Zostaw tę rewizję albo przenieś nagrobki ręcznie.';
        END IF;
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_TOMBSTONES)
    op.execute("DROP TABLE IF EXISTS purged_candidates")
