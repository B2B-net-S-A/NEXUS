"""Saved-search alerts V2 — catch existing candidates that newly match.

Revision ID: 0131_saved_search_match_log
Revises: 0130_merge_0129_heads
Create Date: 2026-06-11

Adds:
- ``saved_search_alert_log`` — append-only per-(search, candidate) dedup log
  (alert-once). Seeded with current matchers when the bell is enabled, so only
  genuine transitions into the match set fire later.
- ``saved_searches.last_scanned_at`` — updated_at watermark for the V2 scanner.
- ``ix_candidates_updated_at`` — makes the scanner's ``updated_at > X`` slice an
  index scan instead of a 48k-row seq scan.
"""

import sqlalchemy as sa
from alembic import op

revision = "0131_saved_search_match_log"
down_revision = "0130_merge_0129_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_search_alert_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "saved_search_id",
            sa.Integer(),
            sa.ForeignKey("saved_searches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "saved_search_id", "candidate_id", name="uq_saved_search_alert_pair"
        ),
    )
    op.create_index(
        "ix_saved_search_alert_log_saved_search_id",
        "saved_search_alert_log",
        ["saved_search_id"],
    )
    op.create_index(
        "ix_saved_search_alert_log_candidate_id",
        "saved_search_alert_log",
        ["candidate_id"],
    )

    op.add_column(
        "saved_searches",
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_candidates_updated_at", "candidates", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_candidates_updated_at", table_name="candidates")
    op.drop_column("saved_searches", "last_scanned_at")
    op.drop_index(
        "ix_saved_search_alert_log_candidate_id", table_name="saved_search_alert_log"
    )
    op.drop_index(
        "ix_saved_search_alert_log_saved_search_id", table_name="saved_search_alert_log"
    )
    op.drop_table("saved_search_alert_log")
