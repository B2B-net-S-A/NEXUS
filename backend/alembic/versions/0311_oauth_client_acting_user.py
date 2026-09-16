"""OAuth client "acting user" — client_credentials tokens act as a service user.

Revision ID: 0311_oauth_client_acting_user
Revises: 0310_dl_alerts_my_clients_panel

Why:
- ``POST /api/oauth/token`` issued ``type=client`` JWTs since 0086, but no
  endpoint ever accepted them (``require_scope`` had zero call sites), so
  integrations (scrapery pracuj.pl / JJIT) could not push candidates via API.
- Instead of duplicating every endpoint behind ``require_scope``, a client
  token now resolves to the user pointed at by ``acting_user_id`` inside
  ``get_current_user``. Existing RBAC (``RecruiterPlus`` etc.), audit
  columns (``created_by``) and rate limits keep working unchanged.
- Nullable + ON DELETE SET NULL: a client without an acting user cannot
  authenticate (401) — safe default for pre-existing rows.
"""

from alembic import op

revision = "0311_oauth_client_acting_user"
down_revision = "0310_dl_alerts_my_clients_panel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE oauth_clients
        ADD COLUMN IF NOT EXISTS acting_user_id INTEGER NULL
        REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_oauth_clients_acting_user_id
        ON oauth_clients (acting_user_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_oauth_clients_acting_user_id")
    op.execute("ALTER TABLE oauth_clients DROP COLUMN IF EXISTS acting_user_id")
