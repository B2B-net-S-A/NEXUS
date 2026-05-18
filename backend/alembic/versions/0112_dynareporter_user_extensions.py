"""DynaReporter B.0 — rozszerzenie tabeli users o allowed_sections + legacy id.

Revision ID: 0112_dynareporter_user_extensions
Revises: 0111_drop_legacy_client_contact
Create Date: 2026-05-18 12:00:00.000000

Phase B.0 of the DynaReporter migration plan
(.claude/plans/zaplanuj-migracje-pelna-nie-parallel-acorn.md).

Dodaje dwie kolumny do tabeli ``users``:

- ``allowed_sections`` JSONB ``DEFAULT '[]'::jsonb`` NOT NULL — lista
  identyfikatorów modułów DynaReportera do których user ma dostęp
  (``body-leasing``, ``sales``, ``delivery-lead``, ``placements``,
  ``clients-mrr``, ``competitions``, ``przetargi``, ``board``,
  ``sales-mgmt``, ``mindy``, ``admin``). Pusta lista = brak dostępu do
  jakiegokolwiek modułu DynaReportera. Pattern świadomie analogiczny
  do ``aad_group_ids`` (migracja 0107) — używamy JSONB + GIN index
  żeby móc zadawać pytanie "którzy userzy mają sekcję X".

- ``dynareporter_legacy_id`` INTEGER NULL UNIQUE — link do ``users.id``
  z systemu DynaReporter (Render/Coolify standalone). Wypełniany przez
  ETL ``scripts/migrate_dynareporter.py`` przy email-match. NULL
  dla userów którzy nigdy nie byli w DynaReporterze. Po zakończonej
  migracji można usunąć w osobnej migracji (B.4 decommission), ale
  zostaje dla audit trail.

Forward-only (no downgrade) — drop kolumn straciłby konteksty migracji
DynaReportera. Rollback: ``ALLOWED_SECTIONS_ENFORCEMENT_ENABLED=false``
i stop reading the column.
"""

from alembic import op


revision = "0112_dynareporter_user_extensions"
down_revision = "0111_drop_legacy_client_contact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # allowed_sections: per-module access list for DynaReporter modules.
    # JSONB so we can index with GIN and query @> '["body-leasing"]'::jsonb
    # ("which users have access to module X").
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS allowed_sections JSONB "
        "NOT NULL DEFAULT '[]'::jsonb"
    )

    # GIN index — supports `allowed_sections @> '["body-leasing"]'::jsonb`
    # queries which the admin UI uses for "list all users with module X access".
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_allowed_sections "
        "ON users USING gin (allowed_sections)"
    )

    # dynareporter_legacy_id — link to old DynaReporter user id (set by ETL).
    # Partial unique index: many NULLs allowed (users who never used
    # DynaReporter), but each legacy id maps to at most one nexus user.
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS dynareporter_legacy_id INTEGER NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_dynareporter_legacy_id "
        "ON users (dynareporter_legacy_id) "
        "WHERE dynareporter_legacy_id IS NOT NULL"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Forward-only: dropping users.allowed_sections / dynareporter_legacy_id "
        "would lose DynaReporter migration audit trail. To roll back behavior, "
        "stop reading the columns (allowed_sections will read as empty list)."
    )
