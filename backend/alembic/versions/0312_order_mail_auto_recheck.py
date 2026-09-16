"""Godzinowa ponowna weryfikacja wstrzymanych zamówień z maila.

* ``order_mail_documents.gate_reason_codes`` — kody powodów równoległe do
  ``gate_reasons``. Recheck rozstrzyga po kodzie, czy zamówienie czeka na podpis
  umowy (czeka bezterminowo, bez karty dla DL), czy utknęło na czymś innym.
* ``order_mail_recheck_runs`` — historia biegów pokazywana na dole widoku
  „Zamówienia z maila": ile sprawdzono, które zaakceptowano, które wstrzymano
  i z jakiego powodu.

Lustro w ``entrypoint.sh``.

Revision ID: 0312_order_mail_auto_recheck
Revises: 0311_oauth_client_acting_user
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0312_order_mail_auto_recheck"
down_revision = "0311_oauth_client_acting_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_mail_documents",
        sa.Column("gate_reason_codes", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "order_mail_recheck_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "trigger",
            sa.String(length=16),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column("checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("held", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "trigger IN ('scheduled','manual')",
            name="ck_order_mail_recheck_runs_trigger",
        ),
    )
    op.create_index(
        "ix_order_mail_recheck_runs_started",
        "order_mail_recheck_runs",
        ["started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_mail_recheck_runs_started", table_name="order_mail_recheck_runs"
    )
    op.drop_table("order_mail_recheck_runs")
    op.drop_column("order_mail_documents", "gate_reason_codes")
