"""„Ludzie w NEXUSIE”: rola „Pracownik” i uprawnienia Kadry, Płace, Sprzęt, Sprawy.

Revision ID: 0456_hr_access
Revises: 0455_hr_foundation

* rola ``employee`` (wyłączna, bez sekcji produktu; przyjmuje nadania),
* cztery uprawnienia z grupy „Ludzie” na końcu katalogu — CHECK akcji
  i zasiew liczy ``permission_schema`` z katalogu (Płace domyślnie dla
  Finansów, Sprawy dla Talent Community Managera, admin ma wszystko).

Lustro w ``entrypoint.sh`` przez ``hr_schema_bundle`` (CHECK-i ról, zasiew)
oraz literał wartości enum w ``_ENUM_STATEMENTS`` — pilnuje
``tests/test_hr_access_migration_mirror.py``.
"""

from alembic import op

from app.services import hr_access_schema as schema
from app.services import permission_schema

revision = "0456_hr_access"
down_revision = "0455_hr_foundation"
branch_labels = None
depends_on = None


def _replace_check(
    table: str, name: str, expression: str, *, not_valid: bool = False
) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    suffix = " NOT VALID" if not_valid else ""
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}){suffix}"
    )
    if not_valid:
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(schema.ENUM_DDL)

    for table in ("rbac_role_section_permissions", "rbac_role_action_permissions"):
        _replace_check(table, f"ck_{table}_role", f"role IN ({schema.ROLE_VALUES})")
    _replace_check(
        "users",
        "ck_users_exclusive_finance_viewer_roles",
        schema.EXCLUSIVE_ROLES_CHECK,
        not_valid=True,
    )
    for stmt in schema.SEED_DDL:
        op.execute(stmt)
    # CHECK akcji z katalogu → zasiew wszystkich ról × uprawnień → rewizja.
    for stmt in permission_schema.apply_statements():
        op.execute(stmt)


def downgrade() -> None:
    op.execute("""DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM users
            WHERE role::text = 'employee' OR roles ? 'employee'
        ) THEN
            RAISE EXCEPTION 'Konta z rolą employee istnieją — zmień im rolę przed cofnięciem 0456';
        END IF;
    END $$""")
    new_actions = ", ".join(f"'{action}'" for action in schema.NEW_ACTIONS)
    for table in permission_schema.ACTION_TABLES:
        op.execute(f"DELETE FROM {table} WHERE action IN ({new_actions})")
    op.execute("DELETE FROM rbac_role_section_permissions WHERE role = 'employee'")
    op.execute("DELETE FROM rbac_role_action_permissions WHERE role = 'employee'")
    previous = ", ".join(f"'{action}'" for action in schema.PREVIOUS_ACTIONS)
    for table in permission_schema.ACTION_TABLES:
        _replace_check(
            table, permission_schema.constraint_name(table), f"action IN ({previous})"
        )
    for table in ("rbac_role_section_permissions", "rbac_role_action_permissions"):
        _replace_check(
            table, f"ck_{table}_role", f"role IN ({schema.PREVIOUS_ROLE_VALUES})"
        )
    _replace_check(
        "users",
        "ck_users_exclusive_finance_viewer_roles",
        schema.PREVIOUS_EXCLUSIVE_ROLES_CHECK,
        not_valid=True,
    )
    op.execute(schema.BUMP_REVISION)
