"""Dziewięć uprawnień z ekranu Ustawienia → Osoby i role (02.10.2026).

Revision ID: 0409_named_permissions
Revises: 0408_board_task_waiting_notif

Ekran ustawiał sześć sekcji, a o operacjach decydowały bramki ról w kodzie —
administrator nie miał jak nadać np. Finansom tworzenia kontraktu. Od tej
rewizji tabele akcji przyjmują osiem nowych uprawnień (dziewiątym jest
istniejący podpis B2B), a role dostają wiersze według dzisiejszego stanu:
domyślny posiadacz ma „manage”, o ile jego ZAPISANA sekcja na to pozwala.

SQL ma jedno źródło z siatką przy starcie (``named_permissions_bootstrap``):
``app/services/permission_schema.py``.
"""

from alembic import op

from app.services import permission_catalog as catalog
from app.services import permission_schema as schema

revision = "0409_named_permissions"
down_revision = "0408_board_task_waiting_notif"
branch_labels = None
depends_on = None

_PREVIOUS_CHECK = "action IN ('b2b_contract_generator', 'b2b_signature_confirmation')"


def upgrade() -> None:
    for statement in schema.apply_statements():
        op.execute(statement)


def downgrade() -> None:
    keys = ", ".join(f"'{key}'" for key in catalog.SEEDED_KEYS)
    for table in schema.ACTION_TABLES:
        op.execute(f"DELETE FROM {table} WHERE action IN ({keys})")
        name = schema.constraint_name(table)
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({_PREVIOUS_CHECK})"
        )
    op.execute(schema.BUMP_REVISION_SQL)
