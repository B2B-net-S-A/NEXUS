"""Add candidate_pins table for short-listing workflow (Phase 4 manual search).

Revision ID: 0118_candidate_pins
Revises: 0117_dr_timestamptz_campaign
Create Date: 2026-05-19 22:30:00.000000

Replaces Traffit's "Otwarte karty" sidebar with an explicit short-list:
recruiters pin candidates they're considering for a role, then compare
2–5 pinned candidates side-by-side. Unlike "Otwarte karty" (auto-recent),
pins are intentional — only show up when the user clicks the pin icon.

Schema:
- `candidate_pins` — composite-unique (user_id, candidate_id) so a user
  can pin a given candidate at most once. Both FKs cascade so removing a
  user or candidate cleans up their pins automatically.
- `note` is TEXT free-form ("für client X", "follow up Friday") — the
  recruiter's own scratchpad. Optional.
- `pinned_at` defaults to now() for ORDER BY in "show pinned" queries.

Indexes:
- Primary key (id) — surrogate for delete-by-id from API.
- UNIQUE (user_id, candidate_id) — prevents double-pin, also accelerates
  the "is this candidate pinned" lookup used by the drawer toggle.
- (user_id, pinned_at DESC) — used by GET /api/candidates/pins which
  returns the current user's pinned list sorted by recency.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0118_candidate_pins"
down_revision: str | Sequence[str] | None = "0117_dr_timestamptz_campaign"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_pins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "pinned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "candidate_id", name="uq_candidate_pins_user_candidate"
        ),
    )
    op.create_index(
        "ix_candidate_pins_user_pinned_at",
        "candidate_pins",
        ["user_id", sa.text("pinned_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_pins_user_pinned_at", table_name="candidate_pins")
    op.drop_table("candidate_pins")
