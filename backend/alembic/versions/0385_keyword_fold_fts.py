"""Korpus złożony słów kluczowych (kandydaci + notatki) i indeks listy.

Revision ID: 0385_keyword_fold_fts
Revises: 0384_audit_indexes

Audyt szybkości wyszukiwania (25.09.2026): słowo kluczowe na liście trwało
0,9–2 s, „c#” 5,9 s. 68% czasu przy „java” zjadał regex po ``keyword_doc``
(rozpakowywanie tekstu z TOAST dla każdego pasującego kandydata), a dokładał
2 osoby z 15 710. Zamiast niego: ``candidates.keyword_fold_fts`` i
``notes.content_fold_fts`` — indeks tekstu bez polskich znaków, z ukośnikiem
jako spacją i ze słowami ``c#``/``c++``/``f#``/``.net`` zapisanymi zwykłymi
literami (``app/services/keyword_corpus.py``).

Kształt jak 0350: kolumny bez wartości domyślnej, triggery, indeksy
CONCURRENTLY, BEZ uzupełniania w migracji — istniejące wiersze uzupełnia pętla
``keyword_corpus_backfill`` (przy okazji rozpakowuje notatki zapisane przez
import z Traffita jako JSON). Zapytanie przechodzi na nowe kolumny dopiero przy
``KEYWORD_SEARCH_FOLDED_FTS`` i po uzupełnieniu.

``ix_candidates_created_at_id`` — domyślne sortowanie listy („najnowsi”) bez
sortowania całej tabeli.

Lustro w ``entrypoint.sh`` (``_kc.schema_ddl()``, ``_INDEX_STATEMENTS``).
"""

from alembic import op

from app.services import keyword_corpus as kc

revision = "0385_keyword_fold_fts"
down_revision = "0384_audit_indexes"
branch_labels = None
depends_on = None

_CREATED_AT_INDEX = "ix_candidates_created_at_id"


def upgrade() -> None:
    for stmt in kc.FOLD_COLUMN_DDL:
        op.execute(stmt)
    for stmt in kc.FOLD_FUNCTION_DDLS:
        op.execute(stmt)
    with op.get_context().autocommit_block():
        for stmt in kc.fold_index_ddl(concurrently=True):
            op.execute(stmt)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_CREATED_AT_INDEX} "
            "ON candidates (created_at DESC, id DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_CREATED_AT_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {kc.NOTE_FOLD_FTS_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {kc.FOLD_FTS_INDEX}")
    op.execute(f"DROP TRIGGER IF EXISTS {kc.NOTE_TRIGGER_NAME} ON notes")
    op.execute(f"DROP FUNCTION IF EXISTS {kc.NOTE_TRIGGER_FUNCTION}()")
    op.execute(kc.TRIGGER_FUNCTION_DDL_0350)
    op.execute(f"DROP FUNCTION IF EXISTS {kc.NOTE_TEXT_FUNCTION}(text)")
    op.execute(f"DROP FUNCTION IF EXISTS {kc.NOTE_UNWRAP_FUNCTION}(text)")
    op.execute(f"DROP FUNCTION IF EXISTS {kc.FOLD_FUNCTION}(text)")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS content_fold_fts")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS keyword_fold_fts")
