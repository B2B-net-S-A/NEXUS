"""Strona kariery: tytuł publiczny rekrutacji.

Revision ID: 0340_career_public_title
Revises: 0339_career_links

``job_public_profiles.public_title`` — tytuł na stronie kariery ustawiany przez
rekrutera. Pusty = tytuł domyślny (``default_public_title``: surowy tytuł bez
prefiksu klienta i końcowych kodów). Surowy ``jobs.title`` niesie nazwę
klienta i numery zleceń, więc bez tego pola opisu nie dało się zatwierdzić.

Lustro w ``entrypoint.sh`` — pilnuje ``tests/test_career_migration_mirror.py``.
"""

from alembic import op

revision = "0340_career_public_title"
down_revision = "0339_career_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE job_public_profiles "
        "ADD COLUMN IF NOT EXISTS public_title VARCHAR(200) NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE job_public_profiles DROP COLUMN IF EXISTS public_title")
