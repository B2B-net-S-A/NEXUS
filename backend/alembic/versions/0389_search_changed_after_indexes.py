"""Indeksy pod „zmienieni od ostatniego przebiegu” skanera zapisanych wyszukiwań.

Revision ID: 0389_search_changed_after_indexes
Revises: 0388_purged_candidates

Runda 9 audytu (R9-N14-2). `candidates._changed_after_clause` (lista
z ``changed_after`` — skaner alertów zapisanych wyszukiwań co przebieg dla
każdego zapisu z dzwonkiem) sumuje cztery zbiory: kandydaci po
``updated_at`` (indeks jest), notatki po ``created_at`` / ``updated_at``,
dokumenty po ``created_at`` i rozmowy po ``created_at``. Trzech ostatnich
tabel nie indeksuje nic po czasie, więc każdy przebieg skanował w całości
``notes`` (setki tysięcy notatek z Traffita) i ``candidate_documents``.

CONCURRENTLY — ``notes`` i ``candidate_documents`` to gorące tabele
(nocny import Traffita). Lustro w `entrypoint.sh` (`_INDEX_STATEMENTS`) —
prod alembic bywa osierocony.
"""

from alembic import op

revision = "0389_search_changed_after_indexes"
down_revision = "0388_purged_candidates"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_notes_created_at", "notes (created_at)"),
    ("ix_notes_updated_at", "notes (updated_at)"),
    ("ix_candidate_documents_created_at", "candidate_documents (created_at)"),
    ("ix_calls_created_at", "calls (created_at)"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, target in INDEXES:
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {target}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in reversed(INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
