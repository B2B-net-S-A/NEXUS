"""Notatki: przypięcie, odpowiedzi, notatki systemowe; wynik auto-matcha przy procesie.

Revision ID: 0399_notes_pin_replies
Revises: 0397_skill_catalog_tools

Decyzje Artura 29.09.2026:

* automaty (auto-match z CV i scraper JJIT/RocketJobs) przestają pisać
  notatki — wynik trafia do ``recruitment_processes.entry_meta`` i jest
  plakietką przy procesie („Auto-match 67/100 · JJIT”);
* stare notatki automatów dostają ``external_source = 'system'`` (nie są
  kasowane, lista chowa je domyślnie);
* przypięcie notatki wspólne dla zespołu (``pinned_at``/``pinned_by``);
* odpowiedź na notatkę (``parent_note_id``, jeden poziom, CASCADE)
  i powiadomienie ``note_reply`` dla autora notatki głównej.

SQL ma jedno źródło (``app/services/note_threads_schema.py``) — to samo
czyta lustro w ``entrypoint.sh``.
"""

from alembic import op
from sqlalchemy import text

from app.services import note_threads_schema as schema

revision = "0399_notes_pin_replies"
down_revision = "0397_skill_catalog_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)
    for stmt in schema.COLUMN_DDL:
        op.execute(stmt)
    op.execute(schema.SYSTEM_NOTES_BACKFILL)


def downgrade() -> None:
    bind = op.get_bind()
    in_use = bind.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM notes "
            "WHERE parent_note_id IS NOT NULL OR pinned_at IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM recruitment_processes "
            "WHERE entry_meta IS NOT NULL)"
        )
    ).scalar()
    if in_use:
        # Jak 0381/0383/0388: downgrade nie kasuje danych, które ktoś zapisał.
        raise RuntimeError(
            "0399 downgrade: są przypięte notatki, odpowiedzi albo wyniki "
            "auto-matcha przy procesach — usunięcie kolumn skasowałoby je."
        )
    op.execute("DROP INDEX IF EXISTS ix_notes_candidate_pinned")
    op.execute("DROP INDEX IF EXISTS ix_notes_parent_note_id")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS parent_note_id")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS pinned_by")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS pinned_at")
    op.execute("ALTER TABLE recruitment_processes DROP COLUMN IF EXISTS entry_meta")
    # Wartość enuma `note_reply` zostaje (Postgres nie ma DROP VALUE), znacznik
    # notatek systemowych też — to dane, nie schemat.
