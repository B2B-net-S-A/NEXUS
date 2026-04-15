"""Initial schema - create all tables from models

Revision ID: 0001
Revises:
Create Date: 2026-03-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Import all models to register them with Base.metadata
    # Import whatever models exist
    import app.models  # noqa - triggers all model registrations
    
    from app.models.base import Base
    
    # Create all tables from model definitions
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    from app.models.base import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
