"""Password reset infrastructure — DB-backed tokens + force-change flag.

Revision ID: 0078_password_reset_infrastructure
Revises: 0077_promote_traffit_notes
Create Date: 2026-05-06 12:00:00.000000

Wprowadza pełny flow "zapomniałem hasła":

1. Tabela ``password_reset_tokens`` z hashem tokena (SHA-256) i TTL.
   Plain token istnieje tylko w mailu — DB trzyma jedynie hash.
2. Pola ``users.force_password_change`` + ``force_password_change_at``
   — analog do ``profile_completed``. Po admin-resecie user musi przy
   pierwszym loginie zmienić hasło.
3. Rozszerzenie enum ``notificationtype`` o ``password_reset_requested``
   oraz ``password_changed_by_admin``.

Safety net:
- ``ALTER TYPE … ADD VALUE`` w autocommit_block (PG limitation, vide 0063).
- ``CREATE TABLE`` idempotentne (``IF NOT EXISTS``).
- Downgrade dropuje tabelę i kolumny; enum values pozostają (PG nie
  wspiera ich usuwania bez rekreacji typu).
"""

from alembic import op
import sqlalchemy as sa


revision = "0078_password_reset_infrastructure"
down_revision = "0077_promote_traffit_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Rozszerz enum NotificationType (PG: ADD VALUE wymaga autocommit).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype "
            "ADD VALUE IF NOT EXISTS 'password_reset_requested'"
        )
        op.execute(
            "ALTER TYPE notificationtype "
            "ADD VALUE IF NOT EXISTS 'password_changed_by_admin'"
        )

    # 2) password_reset_tokens
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ NULL,
            requested_ip VARCHAR(45) NULL,
            requested_by_admin_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user_id "
        "ON password_reset_tokens(user_id)"
    )
    # Partial index — dla szybkiego lookupu aktywnych (nieużytych, nie wygasłych)
    # tokenów per user (do invalidate-previous w create_reset_token).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user_active "
        "ON password_reset_tokens(user_id) WHERE used_at IS NULL"
    )

    # 3) users.force_password_change + .force_password_change_at
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS force_password_change BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS force_password_change_at TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    # Drop columns + table. Enum values pozostają (PG limitation).
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS force_password_change_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS force_password_change")
    op.execute("DROP INDEX IF EXISTS ix_password_reset_tokens_user_active")
    op.execute("DROP INDEX IF EXISTS ix_password_reset_tokens_user_id")
    op.execute("DROP TABLE IF EXISTS password_reset_tokens")
