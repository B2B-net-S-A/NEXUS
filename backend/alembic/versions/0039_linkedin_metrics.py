"""LinkedIn daily metrics — manual entry dla TAC/recruiter/sourcer

Revision ID: 0039_linkedin_metrics
Revises: 0038_reporting_matrices
Create Date: 2026-04-22 22:30:00.000000

Decyzja Artura (zmiana kursu vs pierwotny plan "tylko auto z Nexusa"):
LinkedIn metrics wprowadzamy RĘCZNIE — zespół wpisuje dzienne liczby
(CV dodane, wiadomości wysłane, odpowiedzi) w bulk-edit adminem, podobnie
jak w InfraReporterze.

Tabela:
  - linkedin_daily_metrics (user_id, report_date, cv_added, messages_sent,
    responses_received, notes)
  - UNIQUE(user_id, report_date) — 1 wiersz per TAC per dzień
  - Indeks na report_date dla aggregacji czasowych
"""

from alembic import op


revision = "0039_linkedin_metrics"
down_revision = "0038_reporting_matrices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS linkedin_daily_metrics (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            report_date DATE NOT NULL,
            week_number SMALLINT,
            cv_added INTEGER NOT NULL DEFAULT 0,
            messages_sent INTEGER NOT NULL DEFAULT 0,
            responses_received INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_linkedin_daily UNIQUE (user_id, report_date),
            CONSTRAINT ck_linkedin_non_negative CHECK (
                cv_added >= 0 AND messages_sent >= 0 AND responses_received >= 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_linkedin_daily_user "
        "ON linkedin_daily_metrics (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_linkedin_daily_date "
        "ON linkedin_daily_metrics (report_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS linkedin_daily_metrics")
