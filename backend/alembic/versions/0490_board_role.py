"""Rola „Rada nadzorcza” — tylko odczyt Insights, kwoty kokpitu Firma.

Revision ID: 0490_board_role
Revises: 0489_career_recruiter_about

Decyzja Artura 21.10.2026: Rada nadzorcza ogląda zbiorcze raporty
i statystyki (kokpit Firma z kwotami, rok do roku, ranking klientów, zespół
imiennie), nie zakłada rekrutacji ani kontraktów. Rola ``board``:

* wyłączna (CHECK ``ck_users_exclusive_finance_viewer_roles``),
* sekcja Insights do odczytu, reszta „none”, żadne z uprawnień ekranu,
* nie przyjmuje nadań (``action_permissions.UNGRANTABLE_ROLES``).

Lustro w ``entrypoint.sh`` przez ``hr_schema_bundle`` (CHECK-i ról, zasiew)
oraz literał wartości enum w ``_ENUM_STATEMENTS`` — pilnuje
``tests/test_board_role_migration_mirror.py``.
"""

from alembic import op

from app.services import board_role_schema as schema

revision = "0490_board_role"
down_revision = "0489_career_recruiter_about"
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
    op.execute(schema.BUMP_REVISION)


def downgrade() -> None:
    # Wartości nie da się usunąć z typu `userrole`; cofamy wiersze i CHECK-i.
    # Konto z tą rolą zablokowałoby węższy CHECK — wtedy odmowa, nie cicha
    # zmiana czyjejś roli.
    op.execute("""DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM users
            WHERE role::text = 'board' OR roles ? 'board'
        ) THEN
            RAISE EXCEPTION 'Konta z rolą board istnieją — zmień im rolę przed cofnięciem 0490';
        END IF;
    END $$""")
    op.execute("DELETE FROM rbac_role_section_permissions WHERE role = 'board'")
    op.execute("DELETE FROM rbac_role_action_permissions WHERE role = 'board'")
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
