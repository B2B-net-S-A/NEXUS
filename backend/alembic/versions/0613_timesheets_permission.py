"""Uprawnienie „Raporty godzin: akceptacja całej firmy”.

Revision ID: 0613_timesheets_permission
Revises: 0612_new_person_setup

Decyzja Artura 28.10.2026: osoba z back office akceptuje timesheety całej
firmy i rozlicza premie, ale nie dostaje reszty „Kadr” (e-teczki, rodzaju
nieobecności, decyzji urlopowych) ani roli Finanse. Uprawnienie z grupy
„Ludzie” na końcu katalogu — CHECK akcji i zasiew liczy ``permission_schema``
z katalogu. Domyślnie ma je tylko admin; nadaje je ekran Osoby i role. Lustro
CHECK-a w ``entrypoint.sh``, siatka przy starcie w ``named_permissions_bootstrap``.
"""

from alembic import op

from app.services import permission_schema

#: Role znane w chwili tej migracji — rola dodana później nie mieści się
#: jeszcze w CHECK-u ról tabeli akcji (lekcja 0410/0446, opis w 0456).
ROLES_AT_0609: tuple[str, ...] = (
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

revision = "0613_timesheets_permission"
down_revision = "0612_new_person_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in permission_schema.apply_statements(roles=ROLES_AT_0609):
        op.execute(stmt)


def downgrade() -> None:
    for table in permission_schema.ACTION_TABLES:
        op.execute(f"DELETE FROM {table} WHERE action = 'timesheets'")
