"""Nagrobki notatek z Traffita usuniętych w NEXUSIE (runda 10, R10-N6-1).

Revision ID: 0395_notes_deleted_note_sources
Revises: 0394_money_invoice_amount_grosze

``DELETE /api/notes/{id}`` kasował wiersz bez śladu, a promocja aktywności
Traffita (``_PROMOTE_NOTES_SQL``) deduplikuje wyłącznie po ISTNIEJĄCEJ
notatce — pełny bieg (i delta z aktywnością młodszą niż okno) zakładał
usuniętą notatkę od nowa. Tabela trzyma tylko identyfikator źródła
(``traffit:activity:<id>``), bez treści i bez danych osobowych. Lustro
w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``tests/test_deleted_note_sources_mirror.py``.
"""

from alembic import op

revision = "0395_notes_deleted_note_sources"
down_revision = "0394_money_invoice_amount_grosze"
branch_labels = None
depends_on = None

CREATE_DELETED_NOTE_SOURCES = """CREATE TABLE IF NOT EXISTS deleted_note_sources (
    source_ref VARCHAR(255) PRIMARY KEY,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""

DDL_STATEMENTS = [CREATE_DELETED_NOTE_SOURCES]


def upgrade() -> None:
    for statement in DDL_STATEMENTS:
        op.execute(statement)


# Bez nagrobków nocny sync odtworzy usunięte notatki — downgrade odmawia,
# gdy tabela nie jest pusta (wzorzec 0388). Zagnieżdżony IF, bo PL/pgSQL
# planuje wyrażenie w całości.
REFUSE_WITH_ROWS = """DO $$
BEGIN
    IF to_regclass('deleted_note_sources') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM deleted_note_sources) THEN
            RAISE EXCEPTION 'Downgrade 0395 odmawia: deleted_note_sources ma nagrobki usuniętych notatek. Bez nich nocny sync Traffita odtworzy te notatki.';
        END IF;
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_ROWS)
    op.execute("DROP TABLE IF EXISTS deleted_note_sources")
