"""Email-verification infrastructure for self-service registration.

Revision ID: 0139_email_verification
Revises: 0138_candidate_expected_hourly_rate
Create Date: 2026-06-23

Dwie zmiany pod self-service rejestrację (POST /api/auth/register):

1. ``users.email_verified`` (BOOLEAN NOT NULL DEFAULT true). Wszystkie
   istniejące konta (legacy email/password, Microsoft SSO, admin-created) są
   implicit zweryfikowane → ``server_default true`` backfilluje je na true.
   Tylko świeżo self-zarejestrowane konta dostają ``false`` (jawnie w endpoint)
   i nie mogą się zalogować dopóki nie klikną linku aktywacyjnego.

2. ``email_verification_tokens`` — jednorazowe, czasowe tokeny (SHA-256 hash,
   TTL 24 h). Bliźniacza do ``password_reset_tokens`` (migracja 0078).

Idempotent: ADD COLUMN / CREATE TABLE / CREATE INDEX z IF (NOT) EXISTS —
współgra z entrypoint ``alembic upgrade heads`` (multi-head tolerated) oraz
z DEBUG ``Base.metadata.create_all``.

NB: chained off the ``0138_candidate_expected_hourly_rate`` head (jeden z
czterech równoległych headów na main; ``upgrade heads`` zastosuje ten lineage).
"""

from alembic import op

revision = "0139_email_verification"
down_revision = "0138_candidate_expected_hourly_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. email_verified flag — true for all existing rows (backfill via default).
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT true"
    )

    # 2. email_verification_tokens table.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER NOT NULL
                                REFERENCES users(id) ON DELETE CASCADE,
            token_hash      VARCHAR(64) NOT NULL,
            expires_at      TIMESTAMPTZ NOT NULL,
            used_at         TIMESTAMPTZ NULL,
            requested_ip    VARCHAR(45) NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_email_verification_tokens_token_hash "
        "ON email_verification_tokens (token_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_user_id "
        "ON email_verification_tokens (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_id "
        "ON email_verification_tokens (id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS email_verification_tokens")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified")
