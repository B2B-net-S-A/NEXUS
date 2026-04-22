"""FAQ z procedurami: tabela `procedures` (wewnętrzne SOP dla zespołu)

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-21 10:00:00.000000

Płaska lista procedur/SOP — tytuł + treść markdown + kolejność + flaga
publikacji. Wszyscy zalogowani mogą czytać opublikowane; tylko admin
tworzy/edytuje/usuwa. Unikalny slug używany do friendly URL.
"""

from alembic import op


revision = "0029_procedures"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS procedures (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            slug VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_published BOOLEAN NOT NULL DEFAULT true,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT procedures_slug_unique UNIQUE (slug)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_procedures_slug ON procedures(slug)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_procedures_sort ON procedures(sort_order)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_procedures_published_sort "
        "ON procedures(is_published, sort_order DESC, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS procedures CASCADE")
