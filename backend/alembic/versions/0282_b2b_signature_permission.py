"""Make signature confirmation independently configurable, including TCM."""

from alembic import op

revision = "0282_b2b_signature_permission"
down_revision = "0281_candidate_skill_audit_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("rbac_role_action_permissions", "rbac_user_action_overrides"):
        op.drop_constraint(f"ck_{table}_action", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_action",
            table,
            "action IN ('b2b_contract_generator', 'b2b_signature_confirmation')",
        )
    # Preserve existing grants for legacy signatories. TCM receives only this
    # command, with no change to generator, finance or document-edit access.
    op.execute("""
        INSERT INTO rbac_role_action_permissions (role, action, access)
        SELECT role, 'b2b_signature_confirmation',
            CASE WHEN role = 'talent_community_manager' THEN 'manage'
                 WHEN role IN ('admin', 'delivery_lead', 'tac') AND access = 'manage' THEN 'manage'
                 ELSE 'none' END
        FROM rbac_role_action_permissions WHERE action = 'b2b_contract_generator'
        ON CONFLICT (role, action) DO NOTHING
    """)
    # Carry forward per-user restrictions/grants for legacy signatories.
    op.execute("""
        INSERT INTO rbac_user_action_overrides (user_id, action, access)
        SELECT overrides.user_id, 'b2b_signature_confirmation',
               CASE WHEN overrides.access = 'manage' THEN 'manage' ELSE 'none' END
        FROM rbac_user_action_overrides AS overrides
        JOIN users ON users.id = overrides.user_id
        WHERE overrides.action = 'b2b_contract_generator'
          AND (users.role::text IN ('delivery_lead', 'tac')
               OR users.roles ?| array['delivery_lead', 'tac'])
          AND users.role::text <> 'talent_community_manager'
          AND NOT users.roles ? 'talent_community_manager'
        ON CONFLICT (user_id, action) DO NOTHING
    """)
    op.execute(
        "UPDATE rbac_policy_state SET revision = revision + 1, updated_at = now() WHERE id = 1"
    )


def downgrade() -> None:
    for table in ("rbac_role_action_permissions", "rbac_user_action_overrides"):
        op.execute(f"DELETE FROM {table} WHERE action = 'b2b_signature_confirmation'")
        op.drop_constraint(f"ck_{table}_action", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_action", table, "action IN ('b2b_contract_generator')"
        )
