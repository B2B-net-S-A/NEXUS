"""Dokumenty w paczce do podpisu (0687) — SQL migracji i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0687_b2b_signing_documents.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony). Model:
``app.models.b2b_signing_document``.
"""

from __future__ import annotations

TABLE = (
    "CREATE TABLE IF NOT EXISTS b2b_signing_documents ("
    "id SERIAL PRIMARY KEY, "
    "request_id INTEGER NOT NULL "
    "REFERENCES b2b_signing_requests(id) ON DELETE CASCADE, "
    "start_document_id INTEGER NULL "
    "REFERENCES client_start_documents(id) ON DELETE SET NULL, "
    "position SMALLINT NOT NULL DEFAULT 0, "
    "title VARCHAR(200) NOT NULL, "
    "source_pdf_path VARCHAR(512) NOT NULL, "
    "source_sha256 VARCHAR(64) NOT NULL, "
    "source_size INTEGER NOT NULL, "
    "signed_pdf_path VARCHAR(512) NULL, "
    "signed_sha256 VARCHAR(64) NULL, "
    "signed_at TIMESTAMPTZ NULL, "
    "validation JSONB NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
    ")"
)
INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_b2b_signing_documents_request "
    "ON b2b_signing_documents (request_id)"
)

TABLE_DDL: tuple[str, ...] = (TABLE, INDEX)
