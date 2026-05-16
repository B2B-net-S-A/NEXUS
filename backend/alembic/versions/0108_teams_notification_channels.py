"""Teams notification channels — Phase 7.6 of the M365 plan.

Revision ID: 0108_teams_notification_channels
Revises: 0105_user_email_templates
Create Date: 2026-05-14 16:00:00.000000

Phase 7.6 of the M365 repair plan (.claude/plans/elegant-percolating-thimble.md).

Adds `teams_notification_channels` so admins can configure Microsoft Teams
channels that receive Adaptive Card notifications when key ATS events fire
(candidate added, verification decision, contract signed). One row per
team+channel pair (UNIQUE), with a JSONB list of `notification_types` that
gates which events trigger a send.

Application-only auth (client credentials flow) is used for Graph sends, so
notifications come from a single AAD app principal — no per-user OAuth here.
The kill-switch lives in settings (`TEAMS_NOTIFICATIONS_ENABLED`), not in the
table — the row's `enabled` column controls per-channel mute without losing
the configuration.

Forward-only with IF NOT EXISTS guards (matches the codebase convention —
see 0105_user_email_templates, 0099_cloudtalk_agent_mapping).
"""

from alembic import op


revision = "0108_teams_notification_channels"
down_revision = "0107_users_aad_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS teams_notification_channels (
            id                  BIGSERIAL PRIMARY KEY,
            workspace_label     VARCHAR(120) NOT NULL,
            team_id             VARCHAR(255) NOT NULL,
            channel_id          VARCHAR(255) NOT NULL,
            notification_types  JSONB NOT NULL DEFAULT '[]'::jsonb,
            enabled             BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_user_id  INTEGER NOT NULL REFERENCES users(id),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_teams_channel_team_id_channel_id UNIQUE (team_id, channel_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_teams_notification_channels_enabled "
        "ON teams_notification_channels (enabled) WHERE enabled = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS teams_notification_channels CASCADE")
