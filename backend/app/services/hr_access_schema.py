"""„Ludzie w NEXUSIE” — rola „Pracownik” i cztery uprawnienia z grupy „Ludzie”.

JEDNO źródło SQL dla ``alembic/versions/0456_hr_access.py`` i ``entrypoint.sh``
(przez ``hr_schema_bundle``). Wzór: 0446 (rola „Automatyzacje”).

* ``employee`` — rola wyłączna (decyzja Artura 16.10.2026, D1): osoba bez pracy
  w rekrutacji widzi swój czas, ludzi i pomoc. Żadnej sekcji produktu; przyjmuje
  nadania z „Osoby i role” (np. recepcja dostaje „Sprzęt”).
* uprawnienia ``people_admin`` (Kadry), ``payroll`` (Płace), ``equipment``
  (Sprzęt), ``cases`` (Sprawy) — dopisane NA KOŃCU katalogu; CHECK akcji
  i zasiew liczy ``permission_schema`` z katalogu.

Wartość typu ``userrole`` dodaje migracja w ``autocommit_block`` (osobna
transakcja); entrypoint ma ją literalnie w ``_ENUM_STATEMENTS``.
"""

from __future__ import annotations

ROLE = "employee"
ENUM_DDL = f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{ROLE}'"

ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', 'talent_community_manager', "
    "'finance', 'tac', 'recruiter', 'sourcer', 'user', 'trainee', 'automation', "
    "'employee'"
)
PREVIOUS_ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', 'talent_community_manager', "
    "'finance', 'tac', 'recruiter', 'sourcer', 'user', 'trainee', 'automation'"
)

EXCLUSIVE_ROLES_CHECK = (
    "CASE WHEN role::text IN ('finance', 'user', 'trainee', 'automation', 'employee') "
    "THEN roles = jsonb_build_array(role::text) "
    "ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee', 'automation', "
    "'employee']::text[]) END"
)
PREVIOUS_EXCLUSIVE_ROLES_CHECK = (
    "CASE WHEN role::text IN ('finance', 'user', 'trainee', 'automation') "
    "THEN roles = jsonb_build_array(role::text) "
    "ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee', 'automation']::text[]) END"
)

#: Akcje sprzed „Ludzi w NEXUSIE” — do cofnięcia CHECK-a w downgrade.
PREVIOUS_ACTIONS: tuple[str, ...] = (
    "b2b_contract_generator",
    "delivery_view",
    "clients_edit",
    "contracts_orders_edit",
    "contract_status",
    "b2b_signature_confirmation",
    "recruitment_manage",
    "amounts_view",
    "amounts_edit",
    "finance_module",
)
NEW_ACTIONS: tuple[str, ...] = ("people_admin", "payroll", "equipment", "cases")

_RBAC_ROLE_TABLES = ("rbac_role_section_permissions", "rbac_role_action_permissions")


def _role_check_block(table: str) -> str:
    name = f"ck_{table}_role"
    return f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = '{name}'
              AND pg_get_constraintdef(oid) LIKE '%employee%'
        ) THEN
            ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name};
            ALTER TABLE {table} ADD CONSTRAINT {name} CHECK (role IN ({ROLE_VALUES}));
        END IF;
    END $$"""


EXCLUSIVE_CHECK_BLOCK = f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_users_exclusive_finance_viewer_roles'
              AND pg_get_constraintdef(oid) LIKE '%employee%'
        ) THEN
            ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_exclusive_finance_viewer_roles;
            ALTER TABLE users ADD CONSTRAINT ck_users_exclusive_finance_viewer_roles CHECK ({EXCLUSIVE_ROLES_CHECK}) NOT VALID;
            ALTER TABLE users VALIDATE CONSTRAINT ck_users_exclusive_finance_viewer_roles;
        END IF;
    END $$"""

#: CHECK-i ról — przed zasiewem macierzy (który wstawia wiersze ``employee``).
ROLE_CHECK_DDL: tuple[str, ...] = (
    *(_role_check_block(table) for table in _RBAC_ROLE_TABLES),
    EXCLUSIVE_CHECK_BLOCK,
)

# Sekcje: pracownik nie ma żadnej. ON CONFLICT — decyzja admina z panelu wygrywa.
SEED_SECTIONS = """INSERT INTO rbac_role_section_permissions (role, section, access)
       SELECT 'employee', section, 'none'
       FROM (VALUES ('sourcing'), ('pipeline'), ('delivery'), ('insights'),
                    ('finance'), ('system_admin')) AS s(section)
       ON CONFLICT (role, section) DO NOTHING"""

# Akcje: komplet wierszy „none” dla akcji, które macierz już zna (generator
# i uprawnienia z ekranu). Nowe klucze „Ludzi” zasiewa ``permission_schema``.
SEED_ACTIONS = """INSERT INTO rbac_role_action_permissions (role, action, access)
       SELECT DISTINCT 'employee', action, 'none'
       FROM rbac_role_action_permissions
       ON CONFLICT (role, action) DO NOTHING"""

SEED_DDL: tuple[str, ...] = (SEED_SECTIONS, SEED_ACTIONS)

BUMP_REVISION = (
    "UPDATE rbac_policy_state SET revision = revision + 1, updated_at = now() "
    "WHERE id = 1"
)
