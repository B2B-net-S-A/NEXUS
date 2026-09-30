"""Propozycje: źródło „Z portalu” (job_board) i powód „Pomiń” (30.09.2026).

Revision ID: 0405_proposal_feedback_job_board
Revises: 0404_application_screenings

Dopasowania z integracji (JJIT/RocketJobs) idą do „Do przejrzenia” zamiast na
tablicę, a „Pomiń” zapisuje powód (``dismiss_reason``, ``dismiss_note``).
DDL ma jedno źródło z entrypointem: ``app/services/job_proposal_feedback_schema.py``.
"""

from alembic import op

from app.services import job_proposal_feedback_schema as schema

revision = "0405_proposal_feedback_job_board"
down_revision = "0404_application_screenings"
branch_labels = None
depends_on = None

_OLD_SOURCES = tuple(s for s in schema.SOURCES if s != "job_board")


def upgrade() -> None:
    for stmt in schema.COLUMN_DDL:
        op.execute(stmt)
    for stmt in schema.CONSTRAINT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Propozycje z portalu istnieją tylko w tym źródle — kod sprzed tej rewizji
    # ich nie odczyta, a skasowanie zgubiłoby kandydatów z ogłoszeń bez śladu.
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM job_proposals WHERE source = 'job_board') THEN
                RAISE EXCEPTION 'Downgrade 0405 odmawia: job_proposals ma wiersze job_board.';
            END IF;
        END $$"""
    )
    op.execute(
        "ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_dismiss_reason"
    )
    old = ", ".join(f"'{s}'" for s in _OLD_SOURCES)
    op.execute(
        f"""DO $$ BEGIN
            ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_source;
            ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_source
                CHECK (source IN ({old}));
        END $$"""
    )
    op.execute("ALTER TABLE job_proposals DROP COLUMN IF EXISTS dismiss_note")
    op.execute("ALTER TABLE job_proposals DROP COLUMN IF EXISTS dismiss_reason")
