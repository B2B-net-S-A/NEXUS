"""Korpus złożony, wersja 2: myślnik jako spacja w ``candidate_keyword_fold``.

Revision ID: 0386_keyword_fold_hyphen
Revises: 0385_keyword_fold_fts

Porównanie starej i nowej ścieżki słów kluczowych na produkcji (26.09.2026):
parser tsvector rozbija „CI/CD-driven” na ``cd-driven``, ``cd``, ``driven``,
więc „cd” ląduje o pozycję dalej i fraza „ci/cd” nie łączy się z tekstem.
Myślnik zamieniamy na spację po obu stronach (dokument i zapytanie przechodzą
przez tę samą funkcję). Tylko DDL funkcji — zapisane kolumny przelicza pętla
``keyword_corpus_backfill`` (``FOLD_VERSION``), bez przepisywania tabel
w migracji. Lustro: ``entrypoint.sh`` (``keyword_corpus.schema_ddl()``).
"""

from alembic import op

from app.services import keyword_corpus as kc

revision = "0386_keyword_fold_hyphen"
down_revision = "0385_keyword_fold_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(kc.FOLD_FUNCTION_DDL)


def downgrade() -> None:
    # Wersja 1 różni się wyłącznie myślnikiem; po cofnięciu pętla przeliczy
    # kolumny tak samo (inna wersja w app_settings niż w kodzie).
    op.execute(kc.FOLD_FUNCTION_DDL.replace("'/\\-', '   '", "'/\\', '  '"))
