"""Saved-search alerts — notify owner about new matching candidates.

Revision ID: 0129_saved_search_alerts
Revises: 0128_b2b_number_unique
Create Date: 2026-06-11

Adds to ``saved_searches``:

- ``notify_new_matches``    — alert subscription toggle (bell in the menu)
- ``last_seen_candidate_id``— PK watermark for the background scanner; only
                              candidates with a higher id count as "new"
- ``unseen_count``          — cheap badge counter (scanner += new, /viewed → 0)
- ``last_viewed_at``        — FE highlights rows created after the previous
                              value as "Nowy" when the search is opened

Plus a new ``notificationtype`` enum value ``saved_search_match`` for the
aggregate "new candidates match your saved search" notification. The enum DDL
runs in an autocommit block (same pattern as 0100) and is mirrored by the
entrypoint.sh safety-net.
"""

import sqlalchemy as sa
from alembic import op

revision = "0129_saved_search_alerts"
down_revision = "0128_b2b_number_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'saved_search_match'"
        )

    op.add_column(
        "saved_searches",
        sa.Column(
            "notify_new_matches",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "saved_searches",
        sa.Column("last_seen_candidate_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "saved_searches",
        sa.Column(
            "unseen_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "saved_searches",
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Enum value stays — PostgreSQL cannot drop enum values in-place.
    op.drop_column("saved_searches", "last_viewed_at")
    op.drop_column("saved_searches", "unseen_count")
    op.drop_column("saved_searches", "last_seen_candidate_id")
    op.drop_column("saved_searches", "notify_new_matches")
