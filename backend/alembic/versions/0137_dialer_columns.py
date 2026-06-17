"""Own browser dialer — additive columns on calls + users.

Purely additive (no rename of the live cloudtalk_* columns), so the dormant
CloudTalk integration is untouched:

- calls.provider_call_id     — jambonz call_sid, UNIQUE dedup key for the dialer
- calls.provider_type        — "cloudtalk" | "dialer" (source discriminator)
- calls.recording_storage_key — Object Storage key of the server-side recording
- users.dialer_sip_username  — per-recruiter SIP identity for the browser softphone

Revision ID: 0137_dialer_columns
Revises: 0136_traffit_sync_state

NOTE: rebased from 0132 → 0137 during the main-merge — main shipped its own
0132_b2b_render_payload (+0133–0136) off 0131, so the dialer migration now
chains after main's head to keep a single Alembic head.
"""

import sqlalchemy as sa
from alembic import op

revision = "0137_dialer_columns"
down_revision = "0136_traffit_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The Python CallStatus enum has had ``initiated`` (outbound stub before the
    # webhook arrives) since the CloudTalk work, but it was never added to the
    # Postgres ``callstatus`` type — so INSERTing/filtering status=initiated
    # errored on any DB built purely from migrations. Add it here (idempotent);
    # this also un-breaks the dormant CloudTalk initiate-call path. PG12+ allows
    # ADD VALUE inside a transaction as long as the value isn't used in the same
    # transaction (we only add it).
    op.execute("ALTER TYPE callstatus ADD VALUE IF NOT EXISTS 'initiated'")

    op.add_column("calls", sa.Column("provider_call_id", sa.String(255), nullable=True))
    op.add_column("calls", sa.Column("provider_type", sa.String(20), nullable=True))
    op.add_column(
        "calls", sa.Column("recording_storage_key", sa.String(512), nullable=True)
    )
    op.create_index(
        "ix_calls_provider_call_id", "calls", ["provider_call_id"], unique=True
    )

    op.add_column(
        "users", sa.Column("dialer_sip_username", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_users_dialer_sip_username", "users", ["dialer_sip_username"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_users_dialer_sip_username", table_name="users")
    op.drop_column("users", "dialer_sip_username")

    op.drop_index("ix_calls_provider_call_id", table_name="calls")
    op.drop_column("calls", "recording_storage_key")
    op.drop_column("calls", "provider_type")
    op.drop_column("calls", "provider_call_id")
