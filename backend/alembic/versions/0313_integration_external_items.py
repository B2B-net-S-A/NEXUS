"""Stan importu JJIT w bazie: które aplikacje z portalu już przetworzono.

Revision ID: 0313_integration_external_items
Revises: 0312_integration_runs

Why:
- Scraper na Macu trzymał ``processedApplicationIds`` w pliku JSON. Job w
  NEXUS-ie (etap 2 planu integracji) potrzebuje tego samego, ale w bazie:
  Coolify buduje kontener od nowa przy każdym pushu, a plik by przepadł.
- Jeden wiersz na (źródło, ID aplikacji w portalu): kandydat w NEXUS/Traffit,
  odcisk CV (SHA-256) — żeby ten sam plik nie szedł drugi raz do istniejącego
  kandydata — i ostatnia akcja, dzięki czemu ponowny przebieg (replay) jest
  idempotentny.
- Lustro w ``entrypoint.sh``.
"""

from alembic import op
import sqlalchemy as sa

revision = "0313_integration_external_items"
down_revision = "0312_integration_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_external_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("traffit_id", sa.Integer(), nullable=True),
        sa.Column("cv_sha256", sa.String(64), nullable=True),
        sa.Column("offer_title", sa.String(255), nullable=True),
        sa.Column("last_action", sa.String(32), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source", "external_id", name="uq_integration_external_items"
        ),
    )
    op.create_index(
        "ix_integration_external_items_candidate",
        "integration_external_items",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integration_external_items_candidate",
        table_name="integration_external_items",
    )
    op.drop_table("integration_external_items")
