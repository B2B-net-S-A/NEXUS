"""Job.hiring_manager_contact_id + Contract.client_pm_contact_id FK.

Revision ID: 0097_jobs_contracts_contact_fk
Revises: 0096_contacts_key_relationship
Create Date: 2026-05-11 18:05:00.000000

- jobs.hiring_manager_contact_id NULLABLE FK → contacts.id
  (kto po stronie klienta zatrudnia; jedna główna osoba per Job)
- contracts.client_pm_contact_id NULLABLE FK → contacts.id
  (PM klienta jako referencja do Contact; free text fields client_pm_name/email
  zostają jako fallback dla starych kontraktów bez powiązania)

ON DELETE SET NULL — kasacja Contact nie kasuje powiązanej Job/Contract.
"""

from alembic import op


revision = "0097_jobs_contracts_contact_fk"
down_revision = "0096_contacts_key_relationship"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jobs "
        "ADD COLUMN IF NOT EXISTS hiring_manager_contact_id INTEGER NULL "
        "REFERENCES contacts(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_hiring_manager_contact "
        "ON jobs(hiring_manager_contact_id) "
        "WHERE hiring_manager_contact_id IS NOT NULL"
    )

    op.execute(
        "ALTER TABLE contracts "
        "ADD COLUMN IF NOT EXISTS client_pm_contact_id INTEGER NULL "
        "REFERENCES contacts(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contracts_pm_contact "
        "ON contracts(client_pm_contact_id) "
        "WHERE client_pm_contact_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contracts_pm_contact")
    op.execute(
        "ALTER TABLE contracts DROP COLUMN IF EXISTS client_pm_contact_id"
    )
    op.execute("DROP INDEX IF EXISTS ix_jobs_hiring_manager_contact")
    op.execute(
        "ALTER TABLE jobs DROP COLUMN IF EXISTS hiring_manager_contact_id"
    )
