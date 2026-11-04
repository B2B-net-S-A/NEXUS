"""Rola „Back office” i uprawnienie „Zamówienia: zmiany, PDF-y, import MD”.

Revision ID: 0645_back_office_role
Revises: 0644_client_contracts_view_permission

Decyzja Artura 04.11.2026: osoby od zamówień i umów nie mają widzieć Wyników
miesięcznych, Płac ani faktur. Rola ``back_office``:

* wyłączna (CHECK ``ck_users_exclusive_finance_viewer_roles``),
* sekcje jak u Finansów bez sekcji Finanse,
* uprawnienia: podgląd, klienci, kontrakty i zamówienia, status, podpis B2B,
  kwoty przy rekordzie, ``orders_work``.

``orders_work`` to osobna pozycja katalogu, bo trzy zakładki o zamówieniach
stały dotąd za „Modułem Finanse” razem z Wynikami. Dostają ją domyślnie
Finanse i Back office; „Moduł Finanse” ją pociąga.

Lustro w ``entrypoint.sh`` przez ``hr_schema_bundle`` oraz literał wartości enum
w ``_ENUM_STATEMENTS`` — pilnuje ``tests/test_back_office_role_migration_mirror.py``.
"""

from alembic import op

from app.services import back_office_role_schema as schema
from app.services import permission_schema

#: Role znane w chwili tej migracji (lekcja 0410/0446, opis w 0456).
ROLES_AT_0645: tuple[str, ...] = (
    "admin",
    "finance",
    "back_office",
    "head_of_recruitment",
    "delivery_lead",
    "talent_community_manager",
    "recruiter",
    "user",
    "trainee",
    "automation",
    "employee",
    "board",
)

revision = "0645_back_office_role"
down_revision = "0644_client_contracts_view_permission"
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
    for stmt in permission_schema.apply_statements(roles=ROLES_AT_0645):
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
            WHERE role::text = 'back_office' OR roles ? 'back_office'
        ) THEN
            RAISE EXCEPTION 'Konta z rolą back_office istnieją — zmień im rolę przed cofnięciem 0645';
        END IF;
    END $$""")
    for table in permission_schema.ACTION_TABLES:
        op.execute(f"DELETE FROM {table} WHERE action = 'orders_work'")
    op.execute("DELETE FROM rbac_role_action_permissions WHERE role = 'back_office'")
    op.execute("DELETE FROM rbac_role_section_permissions WHERE role = 'back_office'")
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
