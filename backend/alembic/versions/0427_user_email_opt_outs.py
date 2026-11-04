"""Własne wyłączniki maili konta — „Maile do Ciebie” (09.10.2026).

Revision ID: 0427_user_email_opt_outs
Revises: 0426_framework_contract_text

Do tej daty jedynym własnym wyłącznikiem maila był poranny skrót (0425);
pozostałe maile włączał i wyłączał administrator całej firmie, a zakładka
„Moje” nie mówiła nawet, które z nich konto dostaje.
``users.email_opt_outs`` trzyma ``{rodzaj maila: czas wyłączenia}`` — rodzaje
z ``notification_delivery.CATALOG``, regułę czyta
``services/notification_email_prefs``. Lustro w ``entrypoint.sh`` — ta sama
instrukcja, pilnuje ``test_notification_email_prefs.py``.
"""

from alembic import op

revision = "0427_user_email_opt_outs"
down_revision = "0426_framework_contract_text"
branch_labels = None
depends_on = None

ADD_EMAIL_OPT_OUTS = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_opt_outs "
    "JSONB NOT NULL DEFAULT '{}'::jsonb"
)


def upgrade() -> None:
    op.execute(ADD_EMAIL_OPT_OUTS)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_opt_outs")
