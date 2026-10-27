"""Przypomnienia o brakujących ogłoszeniach: „nie publikujemy” i typy dzwonka.

Revision ID: 0525_job_ad_reminders
Revises: 0524_agreement_admin_details

Decyzja Artura 27.10.2026: codziennie rano mail o każdej otwartej rekrutacji
bez strony kariery, Pracuj.pl albo JustJoin.IT — do osoby, która ma to
zrobić (``services/job_ad/reminders.py``). Tabela ``job_ad_channel_skips``
zapisuje świadome „nie publikujemy tu” z powodem, trzy wartości enuma to
dzwonki ``job_ad_missing``, ``job_ad_backlog`` i ``job_ad_nudge``.

SQL ma jedno źródło (``app/services/job_ad_reminder_schema.py``) — te same
instrukcje stoją dosłownie w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_ad_reminder_schema as schema

revision = "0525_job_ad_reminders"
down_revision = "0524_agreement_admin_details"
branch_labels = None
depends_on = None

# Wartości enuma zostają po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji ich nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text IN ('job_ad_missing', 'job_ad_backlog', 'job_ad_nudge')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0525 odmawia: notifications ma wpisy przypomnień o ogłoszeniach, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    bind = op.get_bind()
    if (
        bind.exec_driver_sql("SELECT 1 FROM job_ad_channel_skips LIMIT 1").first()
        is not None
    ):
        raise RuntimeError(
            "job_ad_channel_skips zawiera decyzje „nie publikujemy” — downgrade "
            "by je skasował. Usuń wiersze świadomie albo zostań przy 0525."
        )
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
