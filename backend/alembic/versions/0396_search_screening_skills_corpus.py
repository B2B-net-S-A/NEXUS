"""Korpus słów kluczowych: umiejętności potwierdzone w screeningu (runda 11, SEARCH).

Revision ID: 0396_search_screening_skills_corpus
Revises: 0395_notes_deleted_note_sources

Profil kandydata pokazuje z ✓ umiejętności potwierdzone w screeningu
(``screening_notes.verified_skills``, poziom „confirmed”), a słowa kluczowe ich
nie znajdowały — runda 10 (F17) dołożyła do korpusu tylko ``verified_tech``.
Trigger kandydata czyta je podzapytaniem, a nowy trigger na ``screening_notes``
przelicza korpus kandydata przy zapisie notatki. Zapisane wiersze przelicza
pętla ``keyword_corpus_backfill`` (``CORPUS_SOURCES_VERSION`` = 3). Lustro:
``entrypoint.sh`` (``keyword_corpus.schema_ddl()``).
"""

from alembic import op

from app.services import keyword_corpus as kc

revision = "0396_search_screening_skills_corpus"
down_revision = "0395_notes_deleted_note_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(kc.TRIGGER_FUNCTION_DDL)
    for stmt in kc.SCREENING_TOUCH_DDLS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in kc.SCREENING_TOUCH_DROP_DDLS:
        op.execute(stmt)
    op.execute(kc.trigger_function_ddl(screening_skills=False))
