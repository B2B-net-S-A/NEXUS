"""Rola „Automatyzacje” — podgląd bez kwot i bez zapisu.

Revision ID: 0446_automation_role
Revises: 0445_cv_stage_draft_snapshots

Decyzja Artura 14.10.2026: osoba, która podpina procesy firmy pod NEXUSA
(API integracyjne v1), nie dostaje roli Finanse — ta czyta wszystkie stawki
i marże, a nadania osoby tylko dodają, więc nie da się jej przyciąć. Nowa
rola wyłączna:

* sekcje Sourcing, Pipeline, Insights i (jako próg zasiewu) Delivery —
  wyłącznie ODCZYT, więc bramka sekcji odmawia każdego zapisu,
* z dziewięciu uprawnień tylko „Klienci, kontrakty i zamówienia: podgląd”;
  bez kwot, bez modułu Finanse, bez rejestru Generatora B2B,
* przyjmuje późniejsze nadania z „Osoby i role” (w odróżnieniu od Viewera).

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``tests/test_automation_role_migration_mirror.py``.
"""

from alembic import op

revision = "0446_automation_role"
down_revision = "0445_cv_stage_draft_snapshots"
branch_labels = None
depends_on = None

ROLE = "automation"

ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', 'talent_community_manager', "
    "'finance', 'tac', 'recruiter', 'sourcer', 'user', 'trainee', 'automation'"
)
PREVIOUS_ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', 'talent_community_manager', "
    "'finance', 'tac', 'recruiter', 'sourcer', 'user', 'trainee'"
)

EXCLUSIVE_ROLES_CHECK = (
    "CASE WHEN role::text IN ('finance', 'user', 'trainee', 'automation') "
    "THEN roles = jsonb_build_array(role::text) "
    "ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee', 'automation']::text[]) END"
)
PREVIOUS_EXCLUSIVE_ROLES_CHECK = (
    "CASE WHEN role::text IN ('finance', 'user', 'trainee') "
    "THEN roles = jsonb_build_array(role::text) "
    "ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee']::text[]) END"
)

# Wiersze sekcji: wszędzie odczyt albo nic. Delivery „read” to próg zasiewu
# podglądu Delivery — sama sekcja wynika z uprawnień (0410).
SEED_SECTIONS = """INSERT INTO rbac_role_section_permissions (role, section, access)
       SELECT 'automation', s.section, s.access
       FROM (VALUES ('sourcing', 'read'), ('pipeline', 'read'),
                    ('delivery', 'read'), ('insights', 'read'),
                    ('finance', 'none'), ('system_admin', 'none')) AS s(section, access)
       ON CONFLICT (role, section) DO NOTHING"""

# Wiersze akcji: komplet dla każdej akcji z macierzy, „manage” tylko dla
# podglądu Delivery. ON CONFLICT: decyzja admina w panelu wygrywa.
SEED_ACTIONS = """INSERT INTO rbac_role_action_permissions (role, action, access)
       SELECT DISTINCT 'automation', action,
              CASE WHEN action = 'delivery_view' THEN 'manage' ELSE 'none' END
       FROM rbac_role_action_permissions
       ON CONFLICT (role, action) DO NOTHING"""

BUMP_REVISION = (
    "UPDATE rbac_policy_state SET revision = revision + 1, updated_at = now() "
    "WHERE id = 1"
)


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
        op.execute(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{ROLE}'")

    for table in ("rbac_role_section_permissions", "rbac_role_action_permissions"):
        _replace_check(table, f"ck_{table}_role", f"role IN ({ROLE_VALUES})")
    _replace_check(
        "users",
        "ck_users_exclusive_finance_viewer_roles",
        EXCLUSIVE_ROLES_CHECK,
        not_valid=True,
    )
    op.execute(SEED_SECTIONS)
    op.execute(SEED_ACTIONS)
    op.execute(BUMP_REVISION)


def downgrade() -> None:
    # Wartości nie da się usunąć z typu `userrole`; cofamy wiersze i CHECK-i.
    # Konto z tą rolą zablokowałoby węższy CHECK — wtedy odmowa, nie cicha
    # zmiana czyjejś roli.
    op.execute("""DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM users
            WHERE role::text = 'automation' OR roles ? 'automation'
        ) THEN
            RAISE EXCEPTION 'Konta z rolą automation istnieją — zmień im rolę przed cofnięciem 0446';
        END IF;
    END $$""")
    op.execute("DELETE FROM rbac_role_section_permissions WHERE role = 'automation'")
    op.execute("DELETE FROM rbac_role_action_permissions WHERE role = 'automation'")
    for table in ("rbac_role_section_permissions", "rbac_role_action_permissions"):
        _replace_check(table, f"ck_{table}_role", f"role IN ({PREVIOUS_ROLE_VALUES})")
    _replace_check(
        "users",
        "ck_users_exclusive_finance_viewer_roles",
        PREVIOUS_EXCLUSIVE_ROLES_CHECK,
        not_valid=True,
    )
    op.execute(BUMP_REVISION)
