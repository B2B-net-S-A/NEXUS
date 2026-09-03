"""Add configurable action permissions for the B2B contract generator.

Revision ID: 0273_action_permissions
Revises: 0272_client_playbooks
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0273_action_permissions"
down_revision = "0272_client_playbooks"
branch_labels = None
depends_on = None


ACTION = "b2b_contract_generator"
ROLE_DEFAULTS = {
    "admin": "manage",
    "finance": "manage",
    "head_of_recruitment": "manage",
    "delivery_lead": "manage",
    "talent_community_manager": "view",
    "tac": "manage",
    "recruiter": "manage",
    "sourcer": "manage",
    "user": "view",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rbac_role_action_permissions (
            role varchar(64) NOT NULL,
            action varchar(64) NOT NULL,
            access varchar(16) NOT NULL,
            updated_by integer REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (role, action),
            CONSTRAINT ck_rbac_role_action_permissions_role CHECK (
                role IN ('admin','head_of_recruitment','delivery_lead','talent_community_manager','finance','tac','recruiter','sourcer','user')
            ),
            CONSTRAINT ck_rbac_role_action_permissions_action CHECK (
                action IN ('b2b_contract_generator')
            ),
            CONSTRAINT ck_rbac_role_action_permissions_access CHECK (
                access IN ('none','view','generate','manage')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rbac_user_action_overrides (
            user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action varchar(64) NOT NULL,
            access varchar(16) NOT NULL,
            updated_by integer REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, action),
            CONSTRAINT ck_rbac_user_action_overrides_action CHECK (
                action IN ('b2b_contract_generator')
            ),
            CONSTRAINT ck_rbac_user_action_overrides_access CHECK (
                access IN ('none','view','generate','manage')
            )
        )
        """
    )

    conn = op.get_bind()
    matrix_empty = conn.execute(
        sa.text("SELECT NOT EXISTS (SELECT 1 FROM rbac_role_action_permissions)")
    ).scalar_one()
    if matrix_empty:
        seed = sa.text(
            "INSERT INTO rbac_role_action_permissions (role, action, access) "
            "VALUES (:role, :action, :access) "
            "ON CONFLICT (role, action) DO NOTHING"
        )
        for role, access in ROLE_DEFAULTS.items():
            conn.execute(seed, {"role": role, "action": ACTION, "access": access})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rbac_user_action_overrides")
    op.execute("DROP TABLE IF EXISTS rbac_role_action_permissions")
