"""Strona kariery: szablon graficzny rekrutacji (19.10.2026).

Revision ID: 0478_career_page_theme
Revises: 0477_candidate_consents_two_kinds

``job_public_profiles.theme`` — wybrany przez rekrutera szablon strony, grafiki
OG i plakatu. NULL = domyślny według roli z tytułu, potem kategorii
kompetencji (``app/services/career_theme.py``). Kolumna nie wchodzi do skrótu
treści, więc zmiana wyglądu nie cofa zatwierdzonego opisu do szkicu.

Lustro w ``entrypoint.sh`` — pilnuje ``tests/test_career_migration_mirror.py``.
"""

from alembic import op

revision = "0478_career_page_theme"
down_revision = "0477_candidate_consents_two_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE job_public_profiles "
        "ADD COLUMN IF NOT EXISTS theme VARCHAR(32) NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE job_public_profiles DROP COLUMN IF EXISTS theme")
