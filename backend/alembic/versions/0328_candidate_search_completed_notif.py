"""notificationtype: ``candidate_search_completed`` — koniec przeglądu bazy.

Revision ID: 0328_candidate_search_completed_notif
Revises: 0327_cv_factual_verification

Pełny przegląd bazy kandydatów (Talent Radar, AI Matching w rekrutacji) trwa
około trzech minut. Autor dostaje wpis w dzwonku, gdy przegląd się zakończy
albo nie powiedzie. Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
Postgres nie usuwa wartości enuma, więc downgrade jest no-opem.
"""

from alembic import op

revision = "0328_candidate_search_completed_notif"
down_revision = "0327_cv_factual_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
            "'candidate_search_completed'"
        )


def downgrade() -> None:
    # Wartości enuma nie da się usunąć bez przebudowy typu; wiersze z tym typem
    # zostają czytelne dla starszego kodu tylko jako surowy tekst — no-op.
    pass
