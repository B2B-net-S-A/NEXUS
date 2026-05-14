"""Graph webhook subscriptions registry.

Revision ID: 0106_graph_subscriptions
Revises: 0105_user_email_templates
Create Date: 2026-05-14 19:00:00.000000

Phase 7.3 of the M365 plan (.claude/plans/elegant-percolating-thimble.md).

Tracks Microsoft Graph push subscriptions so the renewal loop can keep them
alive (Graph caps subscription lifetime at 4230 minutes = ~70h for the
resources we use: Inbox messages, SentItems messages, calendarView events).

Each row maps a Graph `subscriptionId` to the owning user + connection, the
opaque `clientState` shared secret (used to authenticate inbound webhook
deliveries), and the expiry timestamp the renewal loop watches.

Forward-only / IF NOT EXISTS — same pattern as 0102/0103/0104/0105.
"""

from alembic import op


revision = "0106_graph_subscriptions"
down_revision = "0105_user_email_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_subscriptions (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            m365_connection_id INTEGER NOT NULL REFERENCES m365_connections(id) ON DELETE CASCADE,
            resource VARCHAR(255) NOT NULL,
            change_type VARCHAR(50) NOT NULL,
            subscription_id VARCHAR(255) NOT NULL,
            notification_url VARCHAR(998) NOT NULL,
            client_state VARCHAR(255) NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            last_renewed_at TIMESTAMP WITH TIME ZONE,
            renewal_failure_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_graph_subscriptions_subscription_id UNIQUE (subscription_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_subs_expires_at "
        "ON graph_subscriptions(expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_subs_user_id "
        "ON graph_subscriptions(user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_subs_connection_id "
        "ON graph_subscriptions(m365_connection_id)"
    )


def downgrade() -> None:
    # Forward-only — dropping the table mid-flight would orphan live Graph
    # subscriptions (no way to look up subscription_id for DELETE /subscriptions/{id}).
    raise NotImplementedError(
        "Cannot downgrade: would orphan live Graph subscriptions. "
        "If you must roll back, first call DELETE /subscriptions/{id} for every "
        "row via the Graph API, then drop the table manually."
    )
