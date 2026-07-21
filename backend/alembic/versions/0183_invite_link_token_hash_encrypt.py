"""Add token_sha256 + token_ct to candidate_invite_links (hash + encrypt v2).

Revision ID: 0183_invite_link_token_hash_encrypt
Revises: 0182_signature_engagement_token_hash
Create Date: 2026-07-21 10:00:00.000000

The last plaintext-at-rest capability token. Invite links differ from the
others (champion/signature/engagement) in one way that ruled out a plain hash:
the invite LIST endpoint reconstructs each link's ``/apply/{token}`` URL for the
frontend "copy link" button, so a one-way hash would lose the URL for every
existing invite.

Two columns close the gap without a UX change:

- ``token_sha256`` — deterministic digest, for the ``/apply`` lookup and revoke
- ``token_ct``     — Fernet ciphertext of the raw secret, so the list can
                     decrypt it back into a URL while a DB leak without the
                     encryption key yields nothing usable

New tokens store only these two; the PK holds a non-secret ``v2$`` revoke key.
Minting falls back to the legacy plaintext-PK path when no encryption key is
configured, so invite creation never breaks on a missing secret — the security
improvement simply waits for a key. Legacy rows (token_sha256 NULL) keep
resolving through the dual-read branch and their URL from the raw PK.

Both columns nullable, no data rewritten. Mirrored in entrypoint.sh because
prod's alembic bookmark predates this revision (0180–0182 precedent).
"""

import sqlalchemy as sa
from alembic import op

revision = "0183_invite_link_token_hash_encrypt"
down_revision = "0182_signature_engagement_token_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_invite_links",
        sa.Column("token_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "candidate_invite_links",
        sa.Column("token_ct", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_candidate_invite_links_token_sha256",
        "candidate_invite_links",
        ["token_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_invite_links_token_sha256")
    op.drop_column("candidate_invite_links", "token_ct")
    op.drop_column("candidate_invite_links", "token_sha256")
