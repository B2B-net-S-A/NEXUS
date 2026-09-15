"""Panel „Moi klienci" na dashboardzie Delivery Leada.

Revision ID: 0310_dl_alerts_my_clients_panel
Revises: 0309_contract_hourly_rates

Zmiany w ``dl_alerts``:

* ``event_key`` — ``dedupe_key`` bez okna powtórki. Powtórki jednej sprawy
  składają się po nim w jedną kartę, a odhaczenie zamyka wszystkie naraz.
  Backfill obcina ostatni segment ``:…`` z istniejących kluczy.
* ``priority`` (``standard`` | ``high``) — wysoki priorytet T-7 i próg tempa.
* ``email_send_started_at`` / ``email_sent_at`` — claim maila z progów.
* ``episode_closed_at`` — wspólny stempel zamknięcia epizodu sprawy (także
  odhaczonej), żeby powrót warunku znów alarmował.
* status ``resolved`` — przyczyna ustąpiła bez odhaczenia DL.
* pięć nowych typów alertów.

``alert_type`` i ``status`` to VARCHAR + CHECK, więc poszerzenie = DROP+ADD;
lustro w ``entrypoint.sh`` robi to samo.
"""

from alembic import op
import sqlalchemy as sa

revision = "0310_dl_alerts_my_clients_panel"
down_revision = "0309_contract_hourly_rates"
branch_labels = None
depends_on = None

_TYPES = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor', "
    "'periodic_order_ending', 'framework_contract_expiring', "
    "'contract_ending', 'cost_budget_low', 'new_contractor_draft'"
)
_OLD_TYPES = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor'"
)


def upgrade() -> None:
    op.add_column("dl_alerts", sa.Column("event_key", sa.String(255), nullable=True))
    op.add_column(
        "dl_alerts",
        sa.Column(
            "priority",
            sa.String(16),
            nullable=False,
            server_default="standard",
        ),
    )
    op.add_column(
        "dl_alerts",
        sa.Column("email_send_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dl_alerts",
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dl_alerts",
        sa.Column("episode_closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE dl_alerts SET event_key = left(dedupe_key, "
        "length(dedupe_key) - position(':' in reverse(dedupe_key))) "
        "WHERE event_key IS NULL AND position(':' in dedupe_key) > 0"
    )
    op.create_index("ix_dl_alerts_event_key", "dl_alerts", ["event_key"])

    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        f"ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_TYPES}))"
    )
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_status")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_status "
        "CHECK (status IN ('new', 'handled', 'resolved'))"
    )
    op.execute(
        "ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_handled_coherence"
    )
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_handled_coherence "
        "CHECK (status = 'new' OR handled_at IS NOT NULL)"
    )
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_priority "
        "CHECK (priority IN ('standard', 'high'))"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM dl_alerts WHERE alert_type IN ('periodic_order_ending', "
        "'framework_contract_expiring', 'contract_ending', 'cost_budget_low', "
        "'new_contractor_draft')"
    )
    op.execute("UPDATE dl_alerts SET status = 'handled' WHERE status = 'resolved'")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_priority")
    op.execute(
        "ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_handled_coherence"
    )
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_handled_coherence "
        "CHECK (status <> 'handled' OR handled_at IS NOT NULL)"
    )
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_status")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_status "
        "CHECK (status IN ('new', 'handled'))"
    )
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        f"ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_OLD_TYPES}))"
    )
    op.drop_index("ix_dl_alerts_event_key", table_name="dl_alerts")
    op.drop_column("dl_alerts", "episode_closed_at")
    op.drop_column("dl_alerts", "email_sent_at")
    op.drop_column("dl_alerts", "email_send_started_at")
    op.drop_column("dl_alerts", "priority")
    op.drop_column("dl_alerts", "event_key")
