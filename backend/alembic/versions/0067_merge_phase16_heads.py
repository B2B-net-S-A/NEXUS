"""Merge three Phase 16 heads — note_mentions + stage_notification_rules + candidate_risk gate

Revision ID: 0067_merge_phase16_heads
Revises: 0066_note_mentions, 0066_stage_notification_rules
Create Date: 2026-04-27 18:30:00.000000

Pure merge — no DDL. Joins the two pre-existing 0066 branches that diverged from
0065_chat_phase2 so that the next migration (0068_candidate_risk) has a single
parent and the alembic tree returns to a single head.

See user memory: "Nexus Alembic state — trzymaj single-head".
"""

revision = "0067_merge_phase16_heads"
down_revision = ("0066_note_mentions", "0066_stage_notification_rules")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
