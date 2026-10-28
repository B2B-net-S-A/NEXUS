"""Wtyczka LinkedIn: połączenia z kontami i klucz AI szkicu wiadomości.

Revision ID: 0608_linkedin_extension
Revises: 0607_job_closed_notification

Decyzja Artura 28.10.2026: wtyczka Chrome dla zespołu na LinkedInie
i w LinkedIn Recruiterze, klucz per osoba odwoływany w Ustawieniach.
SQL tabeli ma jedno źródło (``app/services/linkedin_extension_schema.py``);
entrypoint wykonuje ``TABLE_DDL`` przy każdym starcie. Klucz AI F38
(``linkedin_message_draft``) — wartość enumu i wiersz w ``ai_features``,
lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import linkedin_extension_schema as schema

revision = "0608_linkedin_extension"
down_revision = "0607_job_closed_notification"
branch_labels = None
depends_on = None

_KEY = "linkedin_message_draft"


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis w logu użycia dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}') THEN
        RAISE EXCEPTION 'Downgrade 0608 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    op.execute("DROP TABLE IF EXISTS linkedin_extension_connections")
