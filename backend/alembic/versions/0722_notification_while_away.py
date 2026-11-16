"""„Gdy Cię nie było”: cichy wiersz zastępcy i sprawy załatwione po powrocie.

Revision ID: 0722_notification_while_away
Revises: 0720_finance_archive

Zgłoszenie 16.11.2026: zastępca zamknął dwie rekrutacje nieobecnej rekruterki
i powiadomienie nie powstało wcale, bo autor ruchu nie dostaje dzwonka.
Same dodania kolumn z wartością domyślną albo NULL — stary kod działa na
nowym schemacie (``podstawy/migracje-zgodne-wstecz.md``).

Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0722_notification_while_away"
down_revision = "0720_finance_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS quiet "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS handled_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS handled_by_user_id "
        "INTEGER NULL REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS away_dismissed_at "
        "TIMESTAMPTZ NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notif_on_behalf_created "
        "ON notifications (on_behalf_of_user_id, created_at) "
        "WHERE on_behalf_of_user_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notif_on_behalf_created")
    for column in ("away_dismissed_at", "handled_by_user_id", "handled_at", "quiet"):
        op.execute(f"ALTER TABLE notifications DROP COLUMN IF EXISTS {column}")
