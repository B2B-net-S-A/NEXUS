"""Uprawnienie „Wyniki firmy: podsumowania przychodu i marży”.

Revision ID: 0628_company_results_permission
Revises: 0627_client_amendment_text

Decyzja Artura 02.11.2026: zbiorcze wyniki firmy widzą Rada i admin, a Finanse
pracują na pojedynczych rekordach. „Moduł Finanse” przestaje otwierać te ekrany.
Uprawnienie na końcu katalogu — CHECK akcji i zasiew liczy ``permission_schema``
z katalogu. Domyślnie ma je tylko admin; nadaje je ekran Osoby i role. Lustro
CHECK-a w ``entrypoint.sh``, siatka przy starcie w ``named_permissions_bootstrap``.
"""

from alembic import op

from app.services import permission_schema

#: Role znane w chwili tej migracji — rola dodana później nie mieści się
#: jeszcze w CHECK-u ról tabeli akcji (lekcja 0410/0446, opis w 0456).
ROLES_AT_0628: tuple[str, ...] = (
    "admin",
    "finance",
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

revision = "0628_company_results_permission"
down_revision = "0627_client_amendment_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in permission_schema.apply_statements(roles=ROLES_AT_0628):
        op.execute(stmt)


def downgrade() -> None:
    for table in permission_schema.ACTION_TABLES:
        op.execute(f"DELETE FROM {table} WHERE action = 'company_results'")
