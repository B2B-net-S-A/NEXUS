"""Rola „Back office” (``back_office``) — zamówienia i umowy bez finansów firmy.

JEDNO źródło SQL dla ``alembic/versions/0645_back_office_role.py``
i ``entrypoint.sh`` (przez ``hr_schema_bundle``). Wzór: 0490 (Rada nadzorcza).

Decyzja Artura 04.11.2026: osoby od zamówień i umów pracują na kontraktach,
zamówieniach i stawkach przy pojedynczym rekordzie, ale nie widzą Wyników
miesięcznych, Płac ani faktur.

* sekcje jak u Finansów, z wyjątkiem sekcji Finanse: ta zostaje „none”, bo
  jej odczyt nadaje ``VIEW_FINANCE`` (``analytics/capabilities.py``), a ta
  capability steruje ponad 40 powierzchniami,
* zakładki o zamówieniach w ``/finance`` otwiera uprawnienie „Zamówienia:
  zmiany, PDF-y, import MD” (``orders_work``),
* rola wyłączna, jak Finanse.

Wartość typu ``userrole`` dodaje migracja w ``autocommit_block`` (osobna
transakcja); entrypoint ma ją literalnie w ``_ENUM_STATEMENTS``.
"""

from __future__ import annotations

ROLE = "back_office"
ENUM_DDL = f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{ROLE}'"

ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', 'talent_community_manager', "
    "'finance', 'tac', 'recruiter', 'sourcer', 'user', 'trainee', 'automation', "
    "'employee', 'board', 'back_office'"
)
PREVIOUS_ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', 'talent_community_manager', "
    "'finance', 'tac', 'recruiter', 'sourcer', 'user', 'trainee', 'automation', "
    "'employee', 'board'"
)

EXCLUSIVE_ROLES_CHECK = (
    "CASE WHEN role::text IN ('finance', 'user', 'trainee', 'automation', 'employee', "
    "'board', 'back_office') "
    "THEN roles = jsonb_build_array(role::text) "
    "ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee', 'automation', "
    "'employee', 'board', 'back_office']::text[]) END"
)
PREVIOUS_EXCLUSIVE_ROLES_CHECK = (
    "CASE WHEN role::text IN ('finance', 'user', 'trainee', 'automation', 'employee', "
    "'board') "
    "THEN roles = jsonb_build_array(role::text) "
    "ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee', 'automation', "
    "'employee', 'board']::text[]) END"
)

_RBAC_ROLE_TABLES = ("rbac_role_section_permissions", "rbac_role_action_permissions")

_MARKER = "%''back_office''%"


def _role_check_block(table: str) -> str:
    name = f"ck_{table}_role"
    return f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = '{name}'
              AND pg_get_constraintdef(oid) LIKE '{_MARKER}'
        ) THEN
            ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name};
            ALTER TABLE {table} ADD CONSTRAINT {name} CHECK (role IN ({ROLE_VALUES}));
        END IF;
    END $$"""


EXCLUSIVE_CHECK_BLOCK = f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_users_exclusive_finance_viewer_roles'
              AND pg_get_constraintdef(oid) LIKE '{_MARKER}'
        ) THEN
            ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_exclusive_finance_viewer_roles;
            ALTER TABLE users ADD CONSTRAINT ck_users_exclusive_finance_viewer_roles CHECK ({EXCLUSIVE_ROLES_CHECK}) NOT VALID;
            ALTER TABLE users VALIDATE CONSTRAINT ck_users_exclusive_finance_viewer_roles;
        END IF;
    END $$"""

#: CHECK-i ról — po CHECK-ach Rady (te znają listę bez ``back_office``)
#: i przed zasiewem macierzy, który wstawia wiersze ``back_office``.
ROLE_CHECK_DDL: tuple[str, ...] = (
    *(_role_check_block(table) for table in _RBAC_ROLE_TABLES),
    EXCLUSIVE_CHECK_BLOCK,
)

# Sekcje. ON CONFLICT — decyzja admina z panelu wygrywa.
SEED_SECTIONS = """INSERT INTO rbac_role_section_permissions (role, section, access)
       SELECT 'back_office', s.section, s.access
       FROM (VALUES ('sourcing', 'write'), ('pipeline', 'write'),
                    ('delivery', 'write'), ('insights', 'read'),
                    ('finance', 'none'), ('system_admin', 'none')) AS s(section, access)
       ON CONFLICT (role, section) DO NOTHING"""

# Komplet wierszy dla akcji, które macierz już zna; „orders_work” dopisuje
# ``permission_schema.seed_sql`` z posiadaczy w katalogu. ON CONFLICT jak wyżej.
SEED_ACTIONS = """INSERT INTO rbac_role_action_permissions (role, action, access)
       SELECT DISTINCT 'back_office', action,
              CASE
                  WHEN action = 'b2b_contract_generator' THEN 'manage'
                  WHEN action = 'delivery_view' THEN 'manage'
                  WHEN action = 'clients_edit' THEN 'manage'
                  WHEN action = 'contracts_orders_edit' THEN 'manage'
                  WHEN action = 'contract_status' THEN 'manage'
                  WHEN action = 'b2b_signature_confirmation' THEN 'manage'
                  WHEN action = 'amounts_view' THEN 'manage'
                  WHEN action = 'amounts_edit' THEN 'manage'
                  WHEN action = 'orders_work' THEN 'manage'
                  ELSE 'none'
              END
       FROM rbac_role_action_permissions
       ON CONFLICT (role, action) DO NOTHING"""

SEED_DDL: tuple[str, ...] = (SEED_SECTIONS, SEED_ACTIONS)

BUMP_REVISION = (
    "UPDATE rbac_policy_state SET revision = revision + 1, updated_at = now() "
    "WHERE id = 1"
)
