"""„Ludzie w NEXUSIE” — załącznik do wniosku urlopowego (potwierdzenie nieobecności).

Revision ID: 0473_hr_leave_proofs
Revises: 0472_kpi_milestones_manual_fill

SQL ma jedno źródło (``app/services/hr_leave_proofs_schema.py``) — ten sam moduł
czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_leave_proofs_schema as schema

revision = "0473_hr_leave_proofs"
down_revision = "0472_kpi_milestones_manual_fill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Rodzaj ``absence_proof`` zostaje w CHECK-u — zwężenie padłoby na
    # istniejących potwierdzeniach w e-teczkach.
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
