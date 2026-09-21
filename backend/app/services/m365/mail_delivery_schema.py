"""Idempotent technical schema, shared by Alembic and production safety net."""

DDL = (
    "CREATE TABLE IF NOT EXISTS mail_delivery_state (scope VARCHAR(64) PRIMARY KEY, state JSONB NOT NULL DEFAULT '{}'::jsonb)",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_next_attempt_at TIMESTAMPTZ",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_delivery_uncertain BOOLEAN NOT NULL DEFAULT false",
    "CREATE INDEX IF NOT EXISTS ix_notifications_mail_retry ON notifications (created_at) WHERE email_sent_at IS NULL AND (email_delivery_uncertain OR email_next_attempt_at IS NOT NULL)",
)

if __name__ == "__main__":
    from app.services.m365.mail_circuit import _engine
    from sqlalchemy import text

    with _engine().begin() as connection:
        for statement in DDL:
            connection.execute(text(statement))
