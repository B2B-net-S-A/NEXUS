"""Drop sales_opportunities table (CRM out of scope for Nexus)

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-15 14:00:00.000000

Removes the CRM sales pipeline table. Nexus is pure ATS — Clients, Contacts,
Client Knowledge Base, and Contracts remain (core of body leasing), but
SalesOpportunity deal tracking is removed per product decision.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("sales_opportunities", if_exists=True)
    # Drop the enum type if it still exists (Postgres only)
    op.execute("DROP TYPE IF EXISTS salesstage")


def downgrade() -> None:
    salesstage = postgresql.ENUM(
        "lead", "qualification", "proposal", "negotiation", "won", "lost",
        name="salesstage",
    )
    salesstage.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sales_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False, index=True),
        sa.Column("contact_person", sa.String(length=255)),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("stage", salesstage, nullable=False, server_default="lead", index=True),
        sa.Column("value", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="PLN"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("expected_close_date", sa.Date()),
        sa.Column("assigned_to", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("lost_reason", sa.Text()),
        sa.Column("converted_job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
