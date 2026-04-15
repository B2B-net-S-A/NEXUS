"""Add performance indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-19 02:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # candidates
    op.create_index('ix_candidates_email_perf', 'candidates', ['email'], unique=False, if_not_exists=True)
    op.create_index('ix_candidates_status_perf', 'candidates', ['status'], unique=False, if_not_exists=True)

    # jobs
    op.create_index('ix_jobs_status_perf', 'jobs', ['status'], unique=False, if_not_exists=True)

    # candidate_stages (pipeline)
    op.create_index('ix_pipeline_job_stage', 'candidate_stages', ['job_id', 'stage'], unique=False, if_not_exists=True)

    # user_activities
    op.create_index('ix_user_activities_user_created', 'user_activities', ['user_id', 'created_at'], unique=False, if_not_exists=True)

    # activities
    op.create_index('ix_activities_user_created', 'activities', ['user_id', 'created_at'], unique=False, if_not_exists=True)

    # notifications
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', 'is_read'], unique=False, if_not_exists=True)


def downgrade() -> None:
    op.drop_index('ix_candidates_email_perf', table_name='candidates', if_exists=True)
    op.drop_index('ix_candidates_status_perf', table_name='candidates', if_exists=True)
    op.drop_index('ix_jobs_status_perf', table_name='jobs', if_exists=True)
    op.drop_index('ix_pipeline_job_stage', table_name='candidate_stages', if_exists=True)
    op.drop_index('ix_user_activities_user_created', table_name='user_activities', if_exists=True)
    op.drop_index('ix_activities_user_created', table_name='activities', if_exists=True)
    op.drop_index('ix_notifications_user_unread', table_name='notifications', if_exists=True)
