"""Engagement declaration magic-link tokens.

Revision ID: 0062_engagement_declaration_tokens
Revises: 0061_open_to_timestamps
Create Date: 2026-04-24 14:30:00.000000

Tabela do self-service deklaracji „Otwartość na dodatkowe projekty".
Rekruter generuje jednokrotny token (TTL 30 dni), wysyła link kandydatowi,
kandydat sam zaznacza preferencje przez publiczny formularz.

  engagement_declaration_tokens
    id            INTEGER PK
    candidate_id  INTEGER FK candidates(id) ON DELETE CASCADE
    token         VARCHAR(48) UNIQUE INDEXED — random urlsafe ~32 chars
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    expires_at    TIMESTAMPTZ NOT NULL  — domyślnie created_at + 30 days
    used_at       TIMESTAMPTZ NULL — set on first successful POST
    created_by    INTEGER FK users(id) ON DELETE SET NULL
"""

from alembic import op
import sqlalchemy as sa


revision = "0062_engagement_declaration_tokens"
down_revision = "0061_open_to_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engagement_declaration_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(48), unique=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_engagement_decl_tokens_token",
        "engagement_declaration_tokens",
        ["token"],
        unique=True,
    )
    op.create_index(
        "ix_engagement_decl_tokens_candidate",
        "engagement_declaration_tokens",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_engagement_decl_tokens_candidate",
        table_name="engagement_declaration_tokens",
    )
    op.drop_index(
        "ix_engagement_decl_tokens_token",
        table_name="engagement_declaration_tokens",
    )
    op.drop_table("engagement_declaration_tokens")
