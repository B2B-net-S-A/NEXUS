"""Poranny skrót mailem — własny wyłącznik konta (09.10.2026).

Revision ID: 0425_daily_digest_opt_out
Revises: 0424_screening_form_versions

Do tej daty jedynym wyłącznikiem skrótu był przełącznik w Ustawienia →
System → Powiadomienia, który działa na całą firmę: 09.10 jedna osoba,
chcąc wyłączyć skrót sobie, wyłączyła go 28 osobom.
``users.daily_digest_email_enabled`` (domyślnie włączony) czyta
``tasks/daily_digest_email._recipients``. Lustro w ``entrypoint.sh`` — ta sama
instrukcja, pilnuje ``test_notification_role_mutes.py``.
"""

from alembic import op

revision = "0425_daily_digest_opt_out"
down_revision = "0424_screening_form_versions"
branch_labels = None
depends_on = None

ADD_DAILY_DIGEST_EMAIL_ENABLED = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_digest_email_enabled "
    "BOOLEAN NOT NULL DEFAULT true"
)


def upgrade() -> None:
    op.execute(ADD_DAILY_DIGEST_EMAIL_ENABLED)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS daily_digest_email_enabled")
