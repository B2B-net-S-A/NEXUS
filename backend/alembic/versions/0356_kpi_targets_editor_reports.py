"""Edytor celów KPI (historia) + znacznik raportów KPI mailem (plan PR3).

Revision ID: 0356_kpi_targets_editor_reports
Revises: 0355_jarvis_ui_events

* ``kpi_target_events`` — historia zmian z edytora „Cele KPI" (odstępstwa ról
  i osobiste cele). Bez FK do wiersza celu: cel kasowany przy powrocie do
  wartości z katalogu, a historia ma zostać.
* ``kpi_email_report_runs`` — UNIQUE (kind, period_key) = raport tygodniowy
  i miesięczny wychodzą najwyżej raz, także po restarcie kontenera.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0356_kpi_targets_editor_reports"
down_revision = "0355_jarvis_ui_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kpi_target_events (
            id SERIAL PRIMARY KEY,
            scope VARCHAR(8) NOT NULL,
            role VARCHAR(40),
            subject_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            subject_name VARCHAR(255),
            kpi_id VARCHAR(64) NOT NULL,
            action VARCHAR(16) NOT NULL,
            changes JSONB,
            actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            actor_name VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_kpi_target_events_scope CHECK (scope IN ('role', 'user')),
            CONSTRAINT ck_kpi_target_events_action CHECK (action IN ('set', 'reset'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kpi_target_events_created "
        "ON kpi_target_events (created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kpi_email_report_runs (
            id SERIAL PRIMARY KEY,
            kind VARCHAR(32) NOT NULL,
            period_key VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'claimed',
            recipients INTEGER NOT NULL DEFAULT 0,
            sent INTEGER NOT NULL DEFAULT 0,
            claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            CONSTRAINT uq_kpi_email_report_runs UNIQUE (kind, period_key),
            CONSTRAINT ck_kpi_email_report_runs_status
                CHECK (status IN ('claimed', 'sent', 'skipped', 'failed'))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kpi_email_report_runs")
    op.execute("DROP TABLE IF EXISTS kpi_target_events")
