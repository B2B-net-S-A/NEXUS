"""Finanse → Zmiany w zamówieniach: dziennik zmian, braki i alert DL.

* ``order_change_events`` — stara → nowa wartość stawki kosztowej,
  przychodowej i daty końca zamówienia. Do tej migracji nic nie zapisywało
  starej wartości, więc podzakładki „Zmiany" nie dało się zbudować.
* ``order_gaps`` — trwały wpis „zamówienie zakończone bez następcy", który
  zostaje także po późniejszym uzupełnieniu (status ``filled_late``).
* ``dl_alerts.alert_type`` + ``order_missing_successor`` — alert DL o braku.
* ``notificationtype`` + ``order_missing_successor`` — ten sam brak w dzwonku.

Obie tabele celowo bez FK (wpis przeżywa usunięcie zamówienia, zapis
w środku flusha nie czeka na blokady). Lustro w ``entrypoint.sh``.
"""

from alembic import op
import sqlalchemy as sa

revision = "0308_finance_order_changes"
down_revision = "0307_client_deletion_event_history"
branch_labels = None
depends_on = None

_DL_TYPES = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor'"
)


def upgrade():
    op.create_table(
        "order_change_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("order_group_id", sa.Integer(), nullable=True),
        sa.Column("contract_id", sa.Integer(), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("field", sa.String(16), nullable=False),
        sa.Column("old_amount", sa.Numeric(16, 6), nullable=True),
        sa.Column("new_amount", sa.Numeric(16, 6), nullable=True),
        sa.Column("old_unit", sa.String(16), nullable=True),
        sa.Column("new_unit", sa.String(16), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("old_date", sa.Date(), nullable=True),
        sa.Column("new_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="system"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "field IN ('rate_cost', 'rate_revenue', 'end_date')",
            name="ck_order_change_events_field",
        ),
        sa.CheckConstraint(
            "source IN ('user', 'system')", name="ck_order_change_events_source"
        ),
    )
    op.create_index(
        "ix_order_change_events_created_at", "order_change_events", ["created_at"]
    )
    op.create_index(
        "ix_order_change_events_order",
        "order_change_events",
        ["order_id", "created_at"],
    )

    op.create_table(
        "order_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("order_group_id", sa.Integer(), nullable=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("order_number", sa.String(255), nullable=True),
        sa.Column("ended_on", sa.Date(), nullable=False),
        sa.Column("detected_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("resolved_order_id", sa.Integer(), nullable=True),
        sa.Column("resolved_order_number", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("order_id", name="uq_order_gaps_order_id"),
        sa.CheckConstraint(
            "status IN ('open', 'filled_late')", name="ck_order_gaps_status"
        ),
        sa.CheckConstraint(
            "status <> 'filled_late' OR resolved_at IS NOT NULL",
            name="ck_order_gaps_resolved_coherence",
        ),
    )
    op.create_index("ix_order_gaps_detected_on", "order_gaps", ["detected_on"])
    op.create_index(
        "ix_order_gaps_contract_status", "order_gaps", ["contract_id", "status"]
    )

    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_DL_TYPES}))"
    )

    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
            "'order_missing_successor'"
        )


def downgrade():
    op.execute("DELETE FROM dl_alerts WHERE alert_type = 'order_missing_successor'")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type CHECK (alert_type IN ("
        "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
        "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review'))"
    )
    op.drop_index("ix_order_gaps_contract_status", table_name="order_gaps")
    op.drop_index("ix_order_gaps_detected_on", table_name="order_gaps")
    op.drop_table("order_gaps")
    op.drop_index("ix_order_change_events_order", table_name="order_change_events")
    op.drop_index("ix_order_change_events_created_at", table_name="order_change_events")
    op.drop_table("order_change_events")
    # Wartość enuma notificationtype zostaje — PostgreSQL nie kasuje jej in-place.
