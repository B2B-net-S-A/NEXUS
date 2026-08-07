"""Interaktywne CV: publiczny link do wygenerowanego CV + kafelki wymagań + chat.

Revision ID: 0217_cv_interactive_share
Revises: 0216_client_order_project_part
Create Date: 2026-08-07

Generator CV B2B dostaje ścieżkę do klienta: rekruter tworzy token-link
(`/cv/i/{token}`), hiring manager przełącza się między widokiem „classic"
(HTML 1:1 z ``render_payload``) a „interaktywnym" (kafelki must/nice-have z
dowodami z doświadczenia + chat AI). Cztery zmiany schematu:

1. ``cv_generated_share_tokens`` — tokeny linków. Od pierwszego dnia wyłącznie
   token v2 (hash-at-rest): PK = nie-sekretny revoke-key ``v2$<hex>``, sekret
   tylko jako SHA-256. Brak gałęzi legacy.
2. ``cv_generated_documents.requirement_map*`` — precomputowana mapa
   „wymaganie → dowody" (jeden call Claude przy generacji; publiczny endpoint
   serwuje wyłącznie cache).
3. ``cv_share_chat_messages`` — log pytań managera i odpowiedzi AI (dzienny
   limit anty-kosztowy per link + sygnał sprzedażowy).
4. ``clients.cv_interactive_enabled`` — per-klientowy włącznik wersji
   interaktywnej (niezależny od ``cv_content_mode_cap``).

Plus dwie nowe wartości ``aifeaturekey`` (``cv_requirement_map``,
``cv_interactive_chat``) z seedem ``ai_features`` — wzorzec 0214. Całość
zdublowana w safety-net ``entrypoint.sh`` (prod alembic bywa orphaned).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0217_cv_interactive_share"
down_revision = "0216_client_order_project_part"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Enum poza transakcją (ALTER TYPE ADD VALUE tego wymaga).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_requirement_map'"
        )
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_interactive_chat'"
        )

    # 2. Seed konfiguracji (enabled, unlimited) — idempotentny.
    for key in ("cv_requirement_map", "cv_interactive_chat"):
        op.execute(
            "INSERT INTO ai_features "
            "(feature, enabled, monthly_limit, created_at, updated_at) "
            f"SELECT '{key}', TRUE, 0, NOW(), NOW() "
            f"WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = '{key}')"
        )

    # 3. Tokeny publicznych linków do wygenerowanych CV.
    op.create_table(
        "cv_generated_share_tokens",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "generated_document_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoke_reason", sa.String(length=255), nullable=True),
        sa.Column("max_views", sa.Integer(), nullable=True),
        sa.Column(
            "view_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_cv_generated_share_tokens_token_sha256",
        "cv_generated_share_tokens",
        ["token_sha256"],
    )
    op.create_index(
        "ix_cv_generated_share_tokens_generated_document_id",
        "cv_generated_share_tokens",
        ["generated_document_id"],
    )

    # 4. Chat na publicznym linku.
    op.create_table(
        "cv_share_chat_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "share_token",
            sa.String(length=64),
            sa.ForeignKey("cv_generated_share_tokens.token", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_cv_share_chat_token_created",
        "cv_share_chat_messages",
        ["share_token", "created_at"],
    )

    # 5. Mapa wymagań na wygenerowanym CV.
    op.add_column(
        "cv_generated_documents",
        sa.Column(
            "requirement_map",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column(
        "cv_generated_documents",
        sa.Column("requirement_map_input_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "cv_generated_documents",
        sa.Column("requirement_map_model", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "cv_generated_documents",
        sa.Column(
            "requirement_map_generated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    # 6. Per-klientowy włącznik wersji interaktywnej.
    op.add_column(
        "clients",
        sa.Column(
            "cv_interactive_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("clients", "cv_interactive_enabled")
    op.drop_column("cv_generated_documents", "requirement_map_generated_at")
    op.drop_column("cv_generated_documents", "requirement_map_model")
    op.drop_column("cv_generated_documents", "requirement_map_input_hash")
    op.drop_column("cv_generated_documents", "requirement_map")
    op.drop_index("ix_cv_share_chat_token_created", table_name="cv_share_chat_messages")
    op.drop_table("cv_share_chat_messages")
    op.drop_index(
        "ix_cv_generated_share_tokens_generated_document_id",
        table_name="cv_generated_share_tokens",
    )
    op.drop_index(
        "ix_cv_generated_share_tokens_token_sha256",
        table_name="cv_generated_share_tokens",
    )
    op.drop_table("cv_generated_share_tokens")
    # PostgreSQL nie usuwa wartości enuma — kasujemy tylko seed konfiguracji.
    op.execute(
        "DELETE FROM ai_features "
        "WHERE feature IN ('cv_requirement_map', 'cv_interactive_chat')"
    )
