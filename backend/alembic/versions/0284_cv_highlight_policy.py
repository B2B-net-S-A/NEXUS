"""Independent, typed CV highlighting policy.

Revision ID: 0284_cv_highlight_policy
Revises: 0283_cv_rule_publications
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0284_cv_highlight_policy"
down_revision = "0283_cv_rule_publications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_cv_rules",
        sa.Column(
            "highlight_policy",
            sa.String(24),
            nullable=False,
            server_default="technologies",
        ),
    )
    op.add_column("client_cv_rules", sa.Column("highlight_terms", postgresql.JSONB()))
    op.create_check_constraint(
        "ck_cv_highlight_policy",
        "client_cv_rules",
        "highlight_policy IN ('none', 'technologies', 'must', 'must_nice', 'explicit')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cv_highlight_policy", "client_cv_rules", type_="check")
    op.drop_column("client_cv_rules", "highlight_terms")
    op.drop_column("client_cv_rules", "highlight_policy")
