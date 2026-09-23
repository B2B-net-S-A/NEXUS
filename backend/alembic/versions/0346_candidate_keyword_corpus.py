"""Korpus słów kluczowych kandydata: ``keyword_doc`` + ``keyword_fts``.

Revision ID: 0346_candidate_keyword_corpus
Revises: 0345_billing_hours_168
Create Date: 2026-09-22 23:00:00.000000

Po co: porównanie z Traffitem (22.09.2026) — szczegóły i lista pól
w ``app/services/keyword_corpus.py``. W skrócie: słowa kluczowe szukały też
w podsumowaniu AI i w kluczach/poziomach JSON-ów, a nie szukały w polach
własnych Traffita i w „Kandydat o sobie”.

Kształt jak 0143 (kolumny bez wartości domyślnej = zmiana metadanych, trigger
zamiast kolumny generowanej, indeksy CONCURRENTLY) — z jedną różnicą: BEZ
backfillu. Backfill 0143 w starcie kontenera trwał ponad 6 minut i przez ten
czas publiczny adres zwracał 502. Istniejące wiersze uzupełnia pętla
``keyword_corpus_backfill`` po starcie, paczkami; do jej końca zapytania dla
wierszy bez korpusu używają starych kolumn (``keyword_corpus.ready()``).

Indeksy na kolumnach pełnych NULL-i budują się w sekundę; rosną razem
z backfillem.
"""

from alembic import op

from app.services import keyword_corpus as kc

revision = "0346_candidate_keyword_corpus"
down_revision = "0345_billing_hours_168"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for stmt in kc.COLUMN_DDL:
        op.execute(stmt)
    op.execute(kc.JSON_TEXT_FUNCTION_DDL)
    op.execute(kc.TRIGGER_FUNCTION_DDL)
    op.execute(kc.TRIGGER_DDL)
    with op.get_context().autocommit_block():
        for stmt in kc.index_ddl(concurrently=True):
            op.execute(stmt)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {kc.DOC_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {kc.FTS_INDEX}")
    op.execute(f"DROP TRIGGER IF EXISTS {kc.TRIGGER_NAME} ON candidates")
    op.execute(f"DROP FUNCTION IF EXISTS {kc.TRIGGER_FUNCTION}()")
    op.execute(f"DROP FUNCTION IF EXISTS {kc.JSON_TEXT_FUNCTION}(jsonb, text[])")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS keyword_fts")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS keyword_doc")
