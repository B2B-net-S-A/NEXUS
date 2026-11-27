"""Alert przy logowaniu hasłem z listy awaryjnej (break-glass).

Revision ID: 0802_break_glass_login_alert
Revises: 0801_b2b_krz_check

Decyzja Artura z 27.11.2026 (organizacyjna część bezpieczeństwa): konto
awaryjne NEXUSA zostaje, bo chroni przed awarią Microsoftu, ale omija MFA
Entra — więc każde logowanie nim widzą wszyscy admini. Nowy typ dzwonka
``break_glass_password_login`` (tylko admini, mail od razu); zdarzenie trafia
do ``security_events`` (tabela z 0800). Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0802_break_glass_login_alert"
down_revision = "0801_b2b_krz_check"
branch_labels = None
depends_on = None

ENUM_DDL = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'break_glass_password_login'"
)

# Kod sprzed tej rewizji nie zna typu dzwonka, więc downgrade odmawia przy
# żywych wierszach (Postgres nie ma `ALTER TYPE … DROP VALUE`).
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'break_glass_password_login'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0802 odmawia: są dzwonki break_glass_password_login, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(ENUM_DDL)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
