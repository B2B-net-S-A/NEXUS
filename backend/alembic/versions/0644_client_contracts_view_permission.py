"""Uprawnienie „Umowy klientów: lista i pliki”.

Revision ID: 0644_client_contracts_view_permission
Revises: 0643_consultant_portal

Decyzja Artura 04.11.2026: osoba z administracji ma widzieć umowy z klientami bez
stawek w systemie. „Stawki i kwoty: podgląd” otwierało kwoty wszędzie, więc lista
i pliki dostają własne uprawnienie, bez sekcji Delivery. Uprawnienie na końcu
katalogu — CHECK akcji i zasiew liczy ``permission_schema`` z katalogu. Domyślnie
ma je tylko admin; nadaje je ekran Osoby i role. Lustro CHECK-a w ``entrypoint.sh``,
siatka przy starcie w ``named_permissions_bootstrap``.
"""

from alembic import op

from app.services import permission_schema

#: Role znane w chwili tej migracji — rola dodana później nie mieści się
#: jeszcze w CHECK-u ról tabeli akcji (lekcja 0410/0446, opis w 0456).
ROLES_AT_0643: tuple[str, ...] = (
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

revision = "0644_client_contracts_view_permission"
down_revision = "0643_consultant_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in permission_schema.apply_statements(roles=ROLES_AT_0643):
        op.execute(stmt)


def downgrade() -> None:
    for table in permission_schema.ACTION_TABLES:
        op.execute(f"DELETE FROM {table} WHERE action = 'client_contracts_view'")
