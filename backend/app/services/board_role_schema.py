"""Rola „Rada nadzorcza” (``board``) — tylko odczyt Insights.

JEDNO źródło SQL dla ``alembic/versions/0490_board_role.py`` i ``entrypoint.sh``
(przez ``hr_schema_bundle``). Wzór: 0456 (rola „Pracownik”).

Decyzja Artura 21.10.2026: członkowie Rady oglądają zbiorcze raporty
i statystyki, nie zakładają rekrutacji ani kontraktów.

* sekcja Insights do odczytu, reszta „none” — bramka sekcji odmawia każdego
  zapisu i każdego ekranu poza Insights,
* z uprawnień nic; kwoty kokpitu Firma wpuszcza rola w ``deps.BoardReader``,
  bez modułu Finanse (faktury, zgody na wydatki, zmiany w zamówieniach),
* nie przyjmuje nadań (``action_permissions.UNGRANTABLE_ROLES``).

Wartość typu ``userrole`` dodaje migracja w ``autocommit_block`` (osobna
transakcja); entrypoint ma ją literalnie w ``_ENUM_STATEMENTS``.
"""

from __future__ import annotations

ROLE = "board"
ENUM_DDL = f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{ROLE}'"

ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', 'talent_community_manager', "
    "'finance', 'tac', 'recruiter', 'sourcer', 'user', 'trainee', 'automation', "
    "'employee', 'board'"
)
PREVIOUS_ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', 'talent_community_manager', "
    "'finance', 'tac', 'recruiter', 'sourcer', 'user', 'trainee', 'automation', "
    "'employee'"
)

EXCLUSIVE_ROLES_CHECK = (
    "CASE WHEN role::text IN ('finance', 'user', 'trainee', 'automation', 'employee', "
    "'board') "
    "THEN roles = jsonb_build_array(role::text) "
    "ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee', 'automation', "
    "'employee', 'board']::text[]) END"
)
PREVIOUS_EXCLUSIVE_ROLES_CHECK = (
    "CASE WHEN role::text IN ('finance', 'user', 'trainee', 'automation', 'employee') "
    "THEN roles = jsonb_build_array(role::text) "
    "ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee', 'automation', "
    "'employee']::text[]) END"
)

_RBAC_ROLE_TABLES = ("rbac_role_section_permissions", "rbac_role_action_permissions")

# Znacznik w definicji CHECK-a: sama nazwa „board” trafiłaby też w przyszłe
# wartości typu „onboarding”, więc szukamy literału w apostrofach.
_MARKER = "%''board''%"


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

#: CHECK-i ról — po CHECK-ach roli „Pracownik” (te znają listę bez ``board``)
#: i przed zasiewem macierzy, który wstawia wiersze ``board``.
ROLE_CHECK_DDL: tuple[str, ...] = (
    *(_role_check_block(table) for table in _RBAC_ROLE_TABLES),
    EXCLUSIVE_CHECK_BLOCK,
)

# Sekcje: tylko Insights do odczytu. ON CONFLICT — decyzja admina z panelu wygrywa.
SEED_SECTIONS = """INSERT INTO rbac_role_section_permissions (role, section, access)
       SELECT 'board', s.section, s.access
       FROM (VALUES ('sourcing', 'none'), ('pipeline', 'none'),
                    ('delivery', 'none'), ('insights', 'read'),
                    ('finance', 'none'), ('system_admin', 'none')) AS s(section, access)
       ON CONFLICT (role, section) DO NOTHING"""

# Akcje: komplet wierszy „none” dla akcji, które macierz już zna.
SEED_ACTIONS = """INSERT INTO rbac_role_action_permissions (role, action, access)
       SELECT DISTINCT 'board', action, 'none'
       FROM rbac_role_action_permissions
       ON CONFLICT (role, action) DO NOTHING"""

SEED_DDL: tuple[str, ...] = (SEED_SECTIONS, SEED_ACTIONS)

BUMP_REVISION = (
    "UPDATE rbac_policy_state SET revision = revision + 1, updated_at = now() "
    "WHERE id = 1"
)
