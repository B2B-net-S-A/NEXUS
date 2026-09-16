"""Integracje zewnętrzne (scrapery pracuj.pl / JJIT): runy, zdarzenia, stan alertów.

Revision ID: 0314_integration_runs
Revises: 0313_md_optional_scope_and_consumption_status

Why:
- Scrapery chodzą poza NEXUS-em (Mac / cron) i jedynym śladem ich pracy były
  wiadomości na Slacku. Brak runu wyglądał identycznie jak brak kandydatów.
  ``integration_runs`` daje odpowiedź „kiedy ostatnio poszło i z jakim wynikiem",
  ``integration_run_events`` — „co dokładnie zrobiono z każdą aplikacją"
  (kandydat w NEXUS/Traffit, dopasowane rekrutacje, błąd), a
  ``integration_alert_state`` pilnuje, żeby alert o zastoju nie szedł co 30 min.
- Bez FK na ``run_id`` w zdarzeniach? Jest FK z CASCADE — zdarzenie bez runu nie
  ma sensu; ``candidate_id`` z SET NULL, bo usunięcie kandydata (RODO) nie może
  kasować historii integracji.
- Lustro w ``entrypoint.sh`` (``_COLUMN_STATEMENTS`` / ``_INDEX_STATEMENTS``).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0314_integration_runs"
down_revision = "0313_md_optional_scope_and_consumption_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="import"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("host", sa.String(64), nullable=True),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("oauth_client_id", sa.String(64), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'ok', 'errors', 'failed')",
            name="ck_integration_runs_status",
        ),
        sa.CheckConstraint(
            "mode IN ('import', 'replay', 'test', 'dry_run')",
            name="ck_integration_runs_mode",
        ),
    )
    op.create_index(
        "ix_integration_runs_source_started",
        "integration_runs",
        ["source", "started_at"],
    )

    op.create_table(
        "integration_run_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("integration_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("traffit_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("candidate_name", sa.String(255), nullable=True),
        sa.Column("offer_title", sa.String(255), nullable=True),
        sa.Column(
            "matched_jobs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('created', 'duplicate', 'cv_refreshed', 'error', 'skipped')",
            name="ck_integration_run_events_action",
        ),
    )
    op.create_index(
        "ix_integration_run_events_run", "integration_run_events", ["run_id"]
    )
    op.create_index(
        "ix_integration_run_events_source_occurred",
        "integration_run_events",
        ["source", "occurred_at"],
    )
    op.create_index(
        "ix_integration_run_events_candidate",
        "integration_run_events",
        ["candidate_id"],
    )

    op.create_table(
        "integration_alert_state",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_alert_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("integration_alert_state")
    op.drop_index(
        "ix_integration_run_events_candidate", table_name="integration_run_events"
    )
    op.drop_index(
        "ix_integration_run_events_source_occurred", table_name="integration_run_events"
    )
    op.drop_index("ix_integration_run_events_run", table_name="integration_run_events")
    op.drop_table("integration_run_events")
    op.drop_index("ix_integration_runs_source_started", table_name="integration_runs")
    op.drop_table("integration_runs")
