"""Per-client pipeline template assignment (Traffit gap #1).

Revision ID: 0090_pipeline_template_client_id
Revises: 0089_entity_field_defs
Create Date: 2026-05-08 15:00:00.000000

NEXUS already ships full PipelineTemplate / PipelineStageDef storage
(see ``app/models/pipeline_template.py``) plus an admin CRUD UI at
``/settings/pipeline-templates``. The remaining Traffit gap was the
ability to make a template the *default for a specific client* — so a
new job for "Nordea" automatically picks the Nordea pipeline rather
than the global B2B one.

This migration adds:
- ``pipeline_templates.client_id`` (nullable FK → clients) — NULL means
  "global, available to any client". When set, the template becomes the
  preferred default for jobs of that client.
- Index ``ix_pipeline_templates_client_id`` for the per-client lookup.

Auto-assign logic (resolved at Job creation time, not at the DB level):
1. If ``Job.client_id`` is set, find a non-archived template with that
   ``client_id`` — use it.
2. Otherwise, fall back to the existing ``is_default`` template.

The resolution lives in the job-create handler (separate commit).
"""

from alembic import op
import sqlalchemy as sa


revision = "0090_pipeline_template_client_id"
down_revision = "0089_entity_field_defs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_templates",
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_pipeline_templates_client_id",
        "pipeline_templates",
        ["client_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_templates_client_id", table_name="pipeline_templates")
    op.drop_column("pipeline_templates", "client_id")
