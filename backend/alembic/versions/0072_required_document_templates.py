"""Faza 1: required_document_templates — globalne szablony wymaganych dokumentów

Revision ID: 0072_required_document_templates
Revises: 0071_traffit_external_ids
Create Date: 2026-05-01 09:35:00.000000

Tabela trzymająca globalne szablony wymaganych dokumentów (np. NDA, RODO,
karta off-limits) które aplikujemy do nowego klienta. Każdy szablon to
nazwa + opis + flag czy jest auto-aplikowany domyślnie.

Per-klient instancje (z plikiem, statusem) leżą w `client_required_documents`
(migracja 0073).

Seed: 4 startowe szablony (NDA, RODO, off-limits, payment terms) — wszystkie
`is_default=true`, czyli automatycznie dostępne do apply przy tworzeniu klienta.

Idempotent.
"""

from alembic import op
import sqlalchemy as sa

revision = "0072_required_document_templates"
down_revision = "0071_traffit_external_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS required_document_templates (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                description TEXT,
                is_default BOOLEAN NOT NULL DEFAULT true,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_rdt_sort_order
              ON required_document_templates (sort_order)
            """
        )
    )

    # Seed 4 startowe szablony (idempotentnie — ON CONFLICT po unique name)
    op.execute(
        sa.text(
            """
            INSERT INTO required_document_templates (name, description, is_default, sort_order)
            VALUES
              ('NDA klienta',
               'Umowa o zachowaniu poufności podpisana z klientem przed startem współpracy.',
               true, 10),
              ('Klauzula RODO',
               'Klauzula ochrony danych osobowych specyficzna dla klienta (zgoda na przetwarzanie CV kandydatów).',
               true, 20),
              ('Karta off-limits',
               'Lista pracowników klienta wykluczonych z hire (do podpisu lub potwierdzenia).',
               true, 30),
              ('Warunki płatności / faktury',
               'Specyficzne wymagania klienta dotyczące terminu płatności, formatu faktury, danych do faktury.',
               true, 40)
            ON CONFLICT (name) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_rdt_sort_order"))
    op.execute(sa.text("DROP TABLE IF EXISTS required_document_templates"))
