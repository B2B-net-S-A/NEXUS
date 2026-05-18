"""Drop legacy Client.contact_person/email/phone after safe-migrate to contacts.

Revision ID: 0111_drop_legacy_client_contact
Revises: 0110_users_multi_role
Create Date: 2026-05-18 18:00:00.000000

Before consolidation, the `clients` table carried an inline "primary contact"
trio (``contact_person``, ``contact_email``, ``contact_phone``) that
duplicated semantics of the dedicated ``contacts`` table (1:N relationship,
each row already pointing to a client via ``Contact.client_id``).

The 2026-05-18 UX consolidation removed the standalone /contacts page and
promoted ContactsTab as a full tab on the Klient profile — meaning every
contact now lives in ``contacts`` table. The inline columns became a legacy
duplicate.

Migration is safe-migrate:

1. For every client with a non-empty ``contact_person``, insert a row into
   ``contacts`` (``is_decision_maker=true``, marker notes, external_source
   = ``legacy_client_migration``) — but only when no equivalent row exists
   already (deduped by email match, falling back to name match).
2. Drop ``contact_person``, ``contact_email``, ``contact_phone`` columns
   from ``clients``.

Downgrade re-adds the columns but does NOT backfill data — recovery is
expected to use the rows still present in ``contacts`` (migration is
non-destructive).
"""

from alembic import op


revision = "0111_drop_legacy_client_contact"
down_revision = "0110_users_multi_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1 — safe-migrate non-empty legacy contact_person rows into
    # the `contacts` table. Idempotent: skips clients whose primary
    # contact (by email match, or by name when email is null) already
    # exists in `contacts`.
    op.execute(
        """
        INSERT INTO contacts (
            client_id, name, email, phone, is_decision_maker,
            notes, external_source, created_at
        )
        SELECT
            c.id,
            c.contact_person,
            NULLIF(c.contact_email, ''),
            NULLIF(c.contact_phone, ''),
            true,
            'Migrated from legacy Client.contact_person (2026-05-18)',
            'legacy_client_migration',
            NOW()
        FROM clients c
        WHERE c.contact_person IS NOT NULL
          AND c.contact_person != ''
          AND NOT EXISTS (
              SELECT 1
              FROM contacts ct
              WHERE ct.client_id = c.id
                AND (
                    (ct.email IS NOT NULL AND ct.email = c.contact_email)
                    OR (ct.email IS NULL AND ct.name = c.contact_person)
                )
          )
        """
    )

    # Step 2 — drop legacy columns.
    op.drop_column("clients", "contact_person")
    op.drop_column("clients", "contact_email")
    op.drop_column("clients", "contact_phone")


def downgrade() -> None:
    # Recreate columns. Data is NOT backfilled — recovery should query
    # `contacts` table (migrated rows are tagged with
    # external_source='legacy_client_migration').
    op.execute(
        "ALTER TABLE clients ADD COLUMN contact_person VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE clients ADD COLUMN contact_email VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE clients ADD COLUMN contact_phone VARCHAR(30)"
    )
