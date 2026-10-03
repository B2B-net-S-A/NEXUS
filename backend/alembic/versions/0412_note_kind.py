"""Notatki: rodzaj notatki (`notes.kind`) i „Reply” z Traffita jako zwykła notatka.

Revision ID: 0412_note_kind
Revises: 0411_merge_recruiter_roles

Pomiar 03.10.2026: z 75 231 notatek 16% to wpisy automatu auto-match, 5%
wątki mailowe, 7% „nie odbiera”, a żaden czytelnik (nocny odczyt faktów,
bramka must, QC CV, podsumowanie AI) ich nie odróżniał. Rodzaj nadaje reguła
``services/note_kinds.py``; ta migracja dodaje tylko kolumnę. Istniejące
wiersze uzupełnia pętla ``note_kind_backfill`` po starcie.

SQL ma jedno źródło (``app/services/note_kind_schema.py``) — to samo czyta
lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import note_kind_schema as schema

revision = "0412_note_kind"
down_revision = "0411_merge_recruiter_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.COLUMN_DDL:
        op.execute(stmt)
    op.execute(schema.REPLY_RETYPE)


def downgrade() -> None:
    # Rodzaj da się policzyć od nowa z treści, więc kolumna znika bez straty.
    # Typ „Reply” zostaje `general` — powrót do `email` przywróciłby błąd.
    op.execute("DROP INDEX IF EXISTS ix_notes_kind_pending")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS kind")
