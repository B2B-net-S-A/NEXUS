"""Correct the Nordea client display name shown in the B2B contract generator.

Revision ID: 0210_fix_nordea_display_name
Revises: 0209_client_alias_lifecycle
Create Date: 2026-08-03

The curated client dropdown in the B2B contract generator renders
``clients.display_name`` (see ``/api/clients-lookup?featured=true``). The Nordea
record carried the abbreviated, incorrect override ``"Nordea ABP"`` while its
full, correct name is ``"Nordea Bank Abp"`` (already stored in ``legal_name``).
This data fix aligns the manual override with the correct name.

Idempotent: matched on the canonical ``name = 'Nordea'`` plus the exact wrong
value, so re-running is a no-op and it never touches an unrelated client that
happens to share the target ``display_name``. Scoping on ``name`` (not ``id``)
keeps the fix portable across environments where the row id differs.
"""

from alembic import op


revision = "0210_fix_nordea_display_name"
down_revision = "0209_client_alias_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE clients
           SET display_name = 'Nordea Bank Abp'
         WHERE name = 'Nordea'
           AND display_name = 'Nordea ABP'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE clients
           SET display_name = 'Nordea ABP'
         WHERE name = 'Nordea'
           AND display_name = 'Nordea Bank Abp'
        """
    )
