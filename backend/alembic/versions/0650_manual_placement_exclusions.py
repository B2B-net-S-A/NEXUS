"""Wykluczone placementy: powód ręczny (0650).

Revision ID: 0650_manual_placement_exclusions
Revises: 0649_start_documents

Decyzja Artura 05.11.2026: placement osoby, która nie podjęła pracy albo
którą klient odprawił zaraz po starcie, nie ma się liczyć w statystykach,
Lidze i wyścigach. Admin dodaje taką parę ręcznie w Ustawieniach → System →
Wykluczone placementy. Migracja poszerza CHECK powodu o ``manual``; DDL
w ``app/services/placement_exclusions.py`` (``REASON_CHECK_DDL``), lustro
w ``entrypoint.sh``.
"""

from alembic import op

from app.services.placement_exclusions import REASON_CHECK_DDL

revision = "0650_manual_placement_exclusions"
down_revision = "0649_start_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in REASON_CHECK_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DELETE FROM placement_exclusions WHERE reason = 'manual'")
    op.execute(
        "ALTER TABLE placement_exclusions "
        "DROP CONSTRAINT IF EXISTS ck_placement_exclusions_reason"
    )
    op.execute(
        "ALTER TABLE placement_exclusions "
        "ADD CONSTRAINT ck_placement_exclusions_reason "
        "CHECK (reason IN ('admin_bulk_no_cv', 'admin_bulk_2025_09_series'))"
    )
