"""Client display_name + hidden override (odporne na sync Traffita).

Revision ID: 0127_client_display_override
Revises: 0126_candidate_search_doc
Create Date: 2026-06-10 12:00:00.000000

Klienci są synchronizowani z Traffita — importer robi
``ON CONFLICT (external_source, external_id) DO UPDATE SET name = EXCLUDED.name``,
więc każdy sync NADPISUJE `name` (ręczne zmiany nazw były cofane). Dodajemy dwie
kolumny, których importer NIE rusza:

  - ``display_name`` — nazwa wyświetlana w dropdownach (np. „Nordea Bank Abp").
    ``clients-lookup`` zwraca ``COALESCE(display_name, name)`` → nadpisanie jest
    trwałe niezależnie od Traffita.
  - ``hidden`` — chowa zdublowane warianty klienta z list wyboru (Traffit
    odtwarza usunięte duplikaty, więc zamiast kasować — chowamy).

Idempotentne (IF NOT EXISTS) — bezpieczne przy ewentualnym re-runie.
"""

from alembic import op

revision = "0127_client_display_override"
down_revision = "0126_candidate_search_doc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS display_name VARCHAR(255)")
    op.execute(
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL "
        "DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE clients DROP COLUMN IF EXISTS hidden")
    op.execute("ALTER TABLE clients DROP COLUMN IF EXISTS display_name")
