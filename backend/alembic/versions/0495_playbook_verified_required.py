"""Karta klienta: pola wymagane przed „Zweryfikowany” (decyzja Artura 21.10.2026, D3).

Revision ID: 0495_playbook_verified_required
Revises: 0493_cost_consumption_manual_entry

``client_playbooks.verified_required_fields`` — lista kluczy pól karty
rekomendacji (np. ``["motivation"]`` u Nordei), które Delivery Lead klienta
dokłada do minimum przed „Zweryfikowany”. Lustro 1:1 w ``entrypoint.sh``
(pilnuje ``test_playbook_verified_required_mirror.py``).
"""

from alembic import op

revision = "0495_playbook_verified_required"
down_revision = "0493_cost_consumption_manual_entry"
branch_labels = None
depends_on = None

UPGRADE_SQL = (
    "ALTER TABLE client_playbooks "
    "ADD COLUMN IF NOT EXISTS verified_required_fields JSONB NULL"
)


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE client_playbooks DROP COLUMN IF EXISTS verified_required_fields"
    )
