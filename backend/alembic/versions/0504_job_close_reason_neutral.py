"""Powody zamknięcia „nie liczy się do hit ratio” (21.10.2026).

Revision ID: 0504_job_close_neutral
Revises: 0503_b2b_document_participation_types

Decyzja Artura 21.10.2026: przegraną w hit ratio jest tylko rekrutacja, którą
wzięła inna firma. Enum ``jobclosereason`` dostaje dwa powody, które dotąd
lądowały w „Inny”:

* ``duplicate`` — duplikat innej rekrutacji albo założona przez pomyłkę,
* ``no_match`` — nie znaleźliśmy pasującego kandydata,

oraz ``jobs.duplicate_of_job_id`` — rekrutacja, która zostaje, gdy zamykana
jest duplikatem (opcjonalnie). Grupy powodów:
``app/services/metric_definitions.HIT_RATIO_*_CLOSE_REASONS``.

Lustro w safety-net ``entrypoint.sh`` — prod alembic bywa osierocony.
"""

from alembic import op

revision = "0504_job_close_neutral"
down_revision = "0503_b2b_document_participation_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE poza transakcją — Postgres nie pozwala użyć nowej etykiety
    # w transakcji, która ją dodała.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE jobclosereason ADD VALUE IF NOT EXISTS 'duplicate'")
        op.execute("ALTER TYPE jobclosereason ADD VALUE IF NOT EXISTS 'no_match'")
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duplicate_of_job_id INTEGER "
        "NULL REFERENCES jobs(id) ON DELETE SET NULL"
    )


# Etykiet enuma Postgres nie usuwa, a kod sprzed tej rewizji ich nie zna —
# zamknięta rekrutacja z takim powodem dałaby po cofnięciu 500 (audyt 22.10.2026).
REFUSE_WITH_NEUTRAL_CLOSES = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM jobs WHERE close_reason::text IN ('duplicate', 'no_match')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0504 odmawia: jobs ma rekrutacje zamknięte z powodem duplicate albo no_match, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_NEUTRAL_CLOSES)
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS duplicate_of_job_id")
