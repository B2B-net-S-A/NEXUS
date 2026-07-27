"""Add token_sha256 to signature_links and engagement_declaration_tokens.

Revision ID: 0182_signature_engagement_token_hash
Revises: 0181_champion_share_token_hash
Create Date: 2026-07-21 09:00:00.000000

Same hash-at-rest v2 pattern as CVShareToken (0176) and champion (0181). Both
tables stored the raw capability secret in cleartext — signature_links as its
plaintext PK, engagement_declaration_tokens as a plaintext unique column — so a
DB leak yielded working signing / engagement-declaration links directly. New
tokens now store only the SHA-256 digest; the raw secret lives only in the URL,
and the stored column holds a non-secret ``v2$`` revoke key. Legacy rows
(token_sha256 NULL) keep resolving through the dual-read branch until they
expire and are not rewritten.

Additive and safe: both columns are nullable, no data is touched. Mirrored
idempotently in entrypoint.sh because prod's alembic bookmark predates this
revision (see 0180/0181).

invite_link is deliberately NOT included: its list endpoint reconstructs each
link's URL from the stored token, which hashing would break (the raw secret is
gone), so moving it to v2 is a UX change that needs a product decision, not a
mechanical migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "0182_signature_engagement_token_hash"
down_revision = "0181_champion_share_token_hash"
branch_labels = None
depends_on = None

_TABLES = ("signature_links", "engagement_declaration_tokens")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table, sa.Column("token_sha256", sa.String(length=64), nullable=True)
        )
        op.create_index(
            f"ix_{table}_token_sha256", table, ["token_sha256"]
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_token_sha256")
        op.drop_column(table, "token_sha256")
