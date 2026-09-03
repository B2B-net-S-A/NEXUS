"""Persist configurable role permissions and per-user section overrides.

Revision ID: 0269_configurable_section_rbac
Revises: 0268_talent_community_manager
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0269_configurable_section_rbac"
down_revision = "0268_talent_community_manager"
branch_labels = None
depends_on = None


SECTIONS = (
    "sourcing",
    "pipeline",
    "delivery",
    "insights",
    "finance",
    "system_admin",
)

# Exact mirror of DEFAULT_ROLE_SECTION_ACCESS. These are bootstrap values only:
# ON CONFLICT DO NOTHING must never overwrite an administrator's later edits.
ROLE_DEFAULTS: dict[str, dict[str, str]] = {
    "admin": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "write",
        "insights": "write",
        "finance": "write",
        "system_admin": "write",
    },
    "finance": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "write",
        "insights": "read",
        "finance": "write",
        "system_admin": "none",
    },
    "head_of_recruitment": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "none",
        "insights": "write",
        "finance": "none",
        "system_admin": "none",
    },
    "delivery_lead": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "write",
        "insights": "read",
        "finance": "none",
        "system_admin": "none",
    },
    "talent_community_manager": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "read",
        "insights": "read",
        "finance": "none",
        "system_admin": "none",
    },
    "tac": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "none",
        "insights": "read",
        "finance": "none",
        "system_admin": "none",
    },
    "recruiter": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "none",
        "insights": "read",
        "finance": "none",
        "system_admin": "none",
    },
    "sourcer": {
        "sourcing": "write",
        "pipeline": "write",
        "delivery": "none",
        "insights": "read",
        "finance": "none",
        "system_admin": "none",
    },
    "user": {
        "sourcing": "read",
        "pipeline": "read",
        "delivery": "none",
        "insights": "read",
        "finance": "none",
        "system_admin": "none",
    },
}


def upgrade() -> None:
    # IF NOT EXISTS is intentional: entrypoint.sh is a recovery safety-net in
    # installations where Alembic can be interrupted before stamping the head.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rbac_policy_state (
            id integer PRIMARY KEY,
            revision bigint NOT NULL DEFAULT 1,
            updated_by integer REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_rbac_policy_state_singleton CHECK (id = 1),
            CONSTRAINT ck_rbac_policy_state_revision_positive CHECK (revision > 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rbac_role_section_permissions (
            role varchar(64) NOT NULL,
            section varchar(32) NOT NULL,
            access varchar(16) NOT NULL,
            updated_by integer REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (role, section),
            CONSTRAINT ck_rbac_role_section_permissions_role CHECK (
                role IN ('admin','head_of_recruitment','delivery_lead','talent_community_manager','finance','tac','recruiter','sourcer','user')
            ),
            CONSTRAINT ck_rbac_role_section_permissions_section CHECK (
                section IN ('sourcing','pipeline','delivery','insights','finance','system_admin')
            ),
            CONSTRAINT ck_rbac_role_section_permissions_access CHECK (
                access IN ('none','read','write')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rbac_user_section_overrides (
            user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            section varchar(32) NOT NULL,
            access varchar(16) NOT NULL,
            updated_by integer REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, section),
            CONSTRAINT ck_rbac_user_section_overrides_section CHECK (
                section IN ('sourcing','pipeline','delivery','insights','finance','system_admin')
            ),
            CONSTRAINT ck_rbac_user_section_overrides_access CHECK (
                access IN ('none','read','write')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rbac_permission_audit (
            id bigserial PRIMARY KEY,
            actor_user_id integer REFERENCES users(id) ON DELETE SET NULL,
            target_kind varchar(16) NOT NULL,
            target_key varchar(128) NOT NULL,
            revision bigint NOT NULL,
            before jsonb NOT NULL,
            after jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_rbac_permission_audit_target_kind CHECK (
                target_kind IN ('role','user')
            ),
            CONSTRAINT ck_rbac_permission_audit_revision_positive CHECK (revision > 0)
        )
        """
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO rbac_policy_state (id, revision) VALUES (1, 1) "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    # Exact parity with entrypoint.sh: bootstrap a pristine installation, but
    # never heal a partial matrix with permissive code defaults. A missing row
    # is an operational fault and resolves to ``none`` until an administrator
    # explicitly repairs it through the audited API.
    matrix_empty = conn.execute(
        sa.text("SELECT NOT EXISTS (SELECT 1 FROM rbac_role_section_permissions)")
    ).scalar_one()
    if matrix_empty:
        seed = sa.text(
            "INSERT INTO rbac_role_section_permissions (role, section, access) "
            "VALUES (:role, :section, :access) "
            "ON CONFLICT (role, section) DO NOTHING"
        )
        for role, permissions in ROLE_DEFAULTS.items():
            for section in SECTIONS:
                conn.execute(
                    seed,
                    {
                        "role": role,
                        "section": section,
                        "access": permissions[section],
                    },
                )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rbac_permission_audit")
    op.execute("DROP TABLE IF EXISTS rbac_user_section_overrides")
    op.execute("DROP TABLE IF EXISTS rbac_role_section_permissions")
    op.execute("DROP TABLE IF EXISTS rbac_policy_state")
