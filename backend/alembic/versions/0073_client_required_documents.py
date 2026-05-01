"""Faza 1: client_required_documents — instancje wymaganych dokumentów per klient

Revision ID: 0073_client_required_documents
Revises: 0072_required_document_templates
Create Date: 2026-05-01 09:40:00.000000

Tabela trzymająca per-klient instancje wymaganych dokumentów. Każdy wiersz
może być utworzony z szablonu (`template_id`) lub ad-hoc (`template_id=NULL`).
Po utworzeniu można zmienić name/description/is_mandatory bez wpływu na szablon.

Plik (PDF/DOCX itp.) trzymamy poza DB przez `app.services.storage_service`
(spójne z `ClientOnePager.file_path` i `ContractDocument.file_path`).

Status enum: pending (utworzony, plik nie wgrany) / uploaded (plik wgrany,
nie podpisany) / signed (komplet) / n_a (klient nie wymaga).

Bez `expires_at` w v1 (decyzja: dodamy później jeśli będzie alert).

Idempotent.
"""

from alembic import op
import sqlalchemy as sa

revision = "0073_client_required_documents"
down_revision = "0072_required_document_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum type — DROP TYPE w downgrade. Tworzymy z IF NOT EXISTS bezpiecznie.
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                CREATE TYPE clientdocstatus AS ENUM ('pending','uploaded','signed','n_a');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS client_required_documents (
                id SERIAL PRIMARY KEY,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                template_id INTEGER REFERENCES required_document_templates(id) ON DELETE SET NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                is_mandatory BOOLEAN NOT NULL DEFAULT true,
                status clientdocstatus NOT NULL DEFAULT 'pending',
                filename VARCHAR(255),
                file_path VARCHAR(512),
                content_type VARCHAR(128),
                size_bytes INTEGER,
                uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                uploaded_at TIMESTAMPTZ,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_crd_client
              ON client_required_documents (client_id)
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_crd_template
              ON client_required_documents (template_id)
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_crd_template"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_crd_client"))
    op.execute(sa.text("DROP TABLE IF EXISTS client_required_documents"))
    op.execute(sa.text("DROP TYPE IF EXISTS clientdocstatus"))
