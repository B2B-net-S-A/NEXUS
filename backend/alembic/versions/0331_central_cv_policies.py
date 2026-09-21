"""Central CV policies and immutable package approvals (additive)."""
from alembic import op
revision = "0331_central_cv_policies"
down_revision = "0330_jarvis"
branch_labels = None
depends_on = None
DDL = (
    "ALTER TABLE cv_generation_jobs ADD COLUMN IF NOT EXISTS prepared_source_facts JSONB",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS managed_policy JSONB",
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS central_policy JSONB",
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS package_review JSONB",
    "ALTER TABLE cv_generated_share_tokens ADD COLUMN IF NOT EXISTS package_versions JSONB",
    "ALTER TABLE cv_share_tokens ADD COLUMN IF NOT EXISTS package_versions JSONB",
)
def upgrade():
    for statement in DDL:
        op.execute(statement)
def downgrade():
    pass  # Preserve published policies, package approvals and existing links.
