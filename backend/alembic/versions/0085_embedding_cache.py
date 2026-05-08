"""Embedding content-hash cache.

Revision ID: 0085_embedding_cache
Revises: 0084_saved_search_pinned_job
Create Date: 2026-05-08 14:50:00.000000

Stores Voyage embeddings keyed by SHA-256(model || input_type || text). Used
by `embedding_service.cached_voyage_embed` so duplicate uploads (same CV
content, same model) skip the API call.

Why content-hash and not entity FK:
- Same CV uploaded twice (re-upload, dup candidate) hits the cache regardless
  of which row points to it.
- Job descriptions tend to be templated — FTE-1 from team X looks like FTE-2
  from team X. Content-hash dedupes those automatically.

Why include `model` and `input_type` in the hash:
- voyage-3 vector space differs from voyage-3-large; mixing entries would
  silently corrupt search.
- "document" vs "query" inputs use different instruction prompts in
  voyage-3-large — they are not interchangeable.

`hits` and `last_hit_at` enable simple LRU-style eviction (we don't run it
for now — 50K candidates × 4KB embedding ≈ 200MB, fine for years).
"""

import sqlalchemy as sa
from alembic import op

revision = "0085_embedding_cache"
down_revision = "0084_saved_search_pinned_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_cache",
        sa.Column("content_sha256", sa.String(length=64), primary_key=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_type", sa.String(length=16), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_hit_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_embedding_cache_model_lasthit",
        "embedding_cache",
        ["model", "last_hit_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_embedding_cache_model_lasthit", table_name="embedding_cache")
    op.drop_table("embedding_cache")
