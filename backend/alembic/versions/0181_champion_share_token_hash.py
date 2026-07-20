"""Add token_sha256 to champion_card_share_tokens (hash-at-rest, v2).

Revision ID: 0181_champion_share_token_hash
Revises: 0180_close_measured_schema_drift
Create Date: 2026-07-20 19:00:00.000000

ChampionCardShareToken stored the raw share secret as its plaintext primary
key, so a database leak was a ready-made list of working links to filled
Champion cards — candidate PII plus the screening answer key. This mirrors the
fix already shipped for CVShareToken in 0176: add a nullable ``token_sha256``
column, mint new tokens with only the SHA-256 digest stored (the PK becomes a
non-secret ``v2$`` revoke key), and dual-read so legacy rows keep working until
they expire.

Additive and safe: the column is nullable, no data is rewritten, and existing
recruiter-shared links (raw secret still in ``token``, ``token_sha256`` NULL)
continue to resolve through the legacy branch of the lookup. The plaintext tail
ages out on its own as tokens expire — legacy ``token`` values are deliberately
NOT nulled, which would break live shared links.

Prod note: NEXUS's alembic bookmark predates this revision, so this migration
will not run on production. The same column add is mirrored idempotently in
entrypoint.sh (see the schema-drift precedent, 0180 / #828). Both are needed —
without the mirror prod stays without the column and every v2 mint 500s on an
UndefinedColumn; without the migration a fresh database is born without it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0181_champion_share_token_hash"
down_revision = "0180_close_measured_schema_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "champion_card_share_tokens",
        sa.Column("token_sha256", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_champion_card_share_tokens_token_sha256",
        "champion_card_share_tokens",
        ["token_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_champion_card_share_tokens_token_sha256")
    op.drop_column("champion_card_share_tokens", "token_sha256")
