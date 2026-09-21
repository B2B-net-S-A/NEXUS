"""Durable technical mail retry state and ambiguous-delivery protection."""

from alembic import op

revision = "0332_mail_delivery_recovery"
down_revision = "0331_central_cv_policies"
branch_labels = None
depends_on = None


def upgrade():
    from app.services.m365.mail_delivery_schema import DDL

    for statement in DDL:
        op.execute(statement)


def downgrade():
    op.drop_index("ix_notifications_mail_retry", table_name="notifications")
    op.drop_column("notifications", "email_delivery_uncertain")
    op.drop_column("notifications", "email_next_attempt_at")
    op.drop_table("mail_delivery_state")
