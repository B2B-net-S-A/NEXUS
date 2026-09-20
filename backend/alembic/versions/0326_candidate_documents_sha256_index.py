"""Globalny indeks po `candidate_documents.content_sha256`.

Revision ID: 0326_candidate_documents_sha256_index
Revises: 0325_jobs_managed_in_nexus
Create Date: 2026-09-18

Darmowe sito duplikatów w `POST /api/candidates/from-cv` pyta „czy KTOKOLWIEK
ma już dokument o tych bajtach". Dotychczasowy
`ux_candidate_documents_candidate_sha` (0173) jest UNIQUE partial na
``(candidate_id, content_sha256)`` — prefiksem jest `candidate_id`, więc
lookup po samym skrócie go nie użyje i schodzi na skan sekwencyjny po ~96 tys.
wierszy, w gorącej ścieżce uploadu CV.

Indeks jest CZĘŚCIOWY z tego samego powodu co tamten: `content_sha256` ma dziś
wartość wyłącznie dla ~1000 wierszy (`from_cv`, `manual`, `m365`) — 93 945
dokumentów z Traffita ma tam NULL — a sito i tak czyta tylko dokumenty żywe
(`source_deleted_at IS NULL`). Pełny indeks byłby w większości pustymi wpisami.

Nie UNIQUE: ten sam plik LEGALNIE należy do kilku kandydatów (to właśnie
wykrywa sito), a unikalność per kandydat pilnuje już indeks z 0173.
"""

from alembic import op

revision = "0326_candidate_documents_sha256_index"
down_revision = "0325_jobs_managed_in_nexus"
branch_labels = None
depends_on = None


_INDEX = "ix_candidate_documents_sha256"


def upgrade() -> None:
    # CONCURRENTLY wymaga autocommitu — indeks na żywej tabeli nie może
    # blokować uploadów CV na czas budowy.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON candidate_documents (content_sha256) "
            "WHERE content_sha256 IS NOT NULL AND source_deleted_at IS NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
