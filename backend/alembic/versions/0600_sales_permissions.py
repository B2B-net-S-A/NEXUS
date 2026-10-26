"""Sprzedaż (Atlas → NEXUS): uprawnienia „Sprzedaż: podgląd” i „Sprzedaż: edycja”.

Revision ID: 0600_sales_permissions
Revises: 0522_candidate_client_forms

Dwa uprawnienia z grupy „Sprzedaż” na końcu katalogu — CHECK akcji i zasiew
liczy ``permission_schema`` z katalogu. Domyślnie ma je tylko admin; handlowcom
nadaje je ekran Osoby i role (decyzja Artura 26.10.2026: uprawnienia zamiast
roli „Handlowiec”). Lustro CHECK-a w ``entrypoint.sh``, siatka przy starcie
w ``named_permissions_bootstrap``.
"""

from alembic import op

from app.services import permission_schema

#: Role znane w chwili tej migracji — rola dodana później nie mieści się
#: jeszcze w CHECK-u ról tabeli akcji (lekcja 0410/0446, opis w 0456).
ROLES_AT_0600: tuple[str, ...] = (
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

revision = "0600_sales_permissions"
down_revision = "0522_candidate_client_forms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in permission_schema.apply_statements(roles=ROLES_AT_0600):
        op.execute(stmt)


def downgrade() -> None:
    for table in permission_schema.ACTION_TABLES:
        op.execute(f"DELETE FROM {table} WHERE action IN ('sales_view', 'sales_edit')")
