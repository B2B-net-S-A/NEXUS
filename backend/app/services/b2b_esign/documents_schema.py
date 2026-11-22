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

# 0754 (decyzja Artura 22.11.2026): kwalifikowany podpis wymagany tylko przy
# umowie, która przenosi prawa autorskie. Dokument z paczki ma wymóg
# ``qualified`` (jak dotąd, także wymóg klienta) albo ``any`` — wtedy
# kontraktor może go zaakceptować kodem z maila. ``signed_via`` mówi, jak
# dokument podpisano. Kod z maila: skrót HMAC, termin i chwila wysłania przy
# wniosku. Stare wiersze zostają ``qualified`` (podpisane kwalifikowanym).
DOC_REQUIREMENTS = ("qualified", "any")
DOC_SIGNED_VIA = ("qualified", "email_code")

ACCEPT_CODE_DDL: tuple[str, ...] = (
    "ALTER TABLE b2b_signing_documents ADD COLUMN IF NOT EXISTS requirement "
    "VARCHAR(16) NOT NULL DEFAULT 'qualified'",
    "ALTER TABLE b2b_signing_documents ADD COLUMN IF NOT EXISTS signed_via "
    "VARCHAR(16) NULL",
    "UPDATE b2b_signing_documents SET signed_via = 'qualified' "
    "WHERE signed_pdf_path IS NOT NULL AND signed_via IS NULL",
    """DO $$ BEGIN
    ALTER TABLE b2b_signing_documents ADD CONSTRAINT ck_b2b_signing_documents_requirement
        CHECK (requirement IN ('qualified', 'any'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$""",
    """DO $$ BEGIN
    ALTER TABLE b2b_signing_documents ADD CONSTRAINT ck_b2b_signing_documents_signed_via
        CHECK (signed_via IS NULL OR signed_via IN ('qualified', 'email_code'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$""",
    "ALTER TABLE b2b_signing_requests ADD COLUMN IF NOT EXISTS accept_code_hash "
    "VARCHAR(64) NULL",
    "ALTER TABLE b2b_signing_requests ADD COLUMN IF NOT EXISTS "
    "accept_code_expires_at TIMESTAMPTZ NULL",
    "ALTER TABLE b2b_signing_requests ADD COLUMN IF NOT EXISTS "
    "accept_code_sent_at TIMESTAMPTZ NULL",
)
