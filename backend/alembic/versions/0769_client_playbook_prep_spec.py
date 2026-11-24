"""Karta klienta: „Specyfika na prep” (F2, decyzje Artura z 24.11.2026).

Revision ID: 0769_client_playbook_prep_spec
Revises: 0768_outside_poland_reason

``client_playbooks.prep_spec`` — osiem pól z punktami, które rekruter omawia
z kandydatem po fundamentach prepa (``services/client_prep_spec.py``). Lustro
1:1 w ``entrypoint.sh`` (pilnuje ``test_client_prep_spec.py``); zasiew 12 kart
idzie jednorazowym krokiem w ``entrypoint.sh``, nie tutaj.
"""

from alembic import op

revision = "0769_client_playbook_prep_spec"
down_revision = "0768_outside_poland_reason"
branch_labels = None
depends_on = None

UPGRADE_SQL = (
    "ALTER TABLE client_playbooks ADD COLUMN IF NOT EXISTS prep_spec JSONB NULL"
)


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("ALTER TABLE client_playbooks DROP COLUMN IF EXISTS prep_spec")
