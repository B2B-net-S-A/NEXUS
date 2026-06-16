"""Provider-agnostic signing rail: rename Autenti columns + add provider cols + signature_links.

Revision ID: 0133_signing_provider_refactor
Revises: 0132_b2b_render_payload
Create Date: 2026-06-16

Faza 1 planu ``docs/in-house-qes-signature-plan.md`` (in-house QES, drop Autenti).
Czyni szynę podpisów provider-agnostyczną, bez zmiany zachowania (Autenti dalej
działa pod ``provider='autenti'``):

- ``document_signatures.autenti_process_id`` → ``provider_ref`` (unikat podąża
  automatycznie w PG przy RENAME kolumny — nie ruszamy nazwy ograniczenia).
- ``document_signatures.autenti_signature_type`` → ``signature_type`` (SES/AdES/QES
  to terminy eIDAS — zostaje free-form ``String(16)``, NIE enum).
- Nowe kolumny ``provider`` (backfill ``'autenti'``), ``signing_session_id``,
  ``identity_provider``, ``signature_level``, ``validation_report`` (JSONB).
- Nowa tabela ``signature_links`` (single-use tokeny dla strony podpisu /sign).
- ``chk_signature_target_xor`` (z 0091) NIETKNIĘTE.
- BRAK ``ALTER TYPE`` na ``notificationtype`` — reuse ``signature_*`` z 0080.

Idempotentne dodatki (IF NOT EXISTS) — bezpieczne przy ewentualnym re-runie.
RENAME nie jest idempotentny, ale jest jednorazowy w łańcuchu migracji.
"""

from alembic import op

revision = "0133_signing_provider_refactor"
down_revision = "0132_b2b_render_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── document_signatures: rename Autenti-specific columns ────────────────
    # PG przenosi UNIQUE constraint razem z kolumną przy RENAME — nie trzeba
    # ruszać nazwy ograniczenia. RENAME owinięty IF EXISTS guardem, żeby
    # re-run / środowiska bez kolumny nie wybuchały.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_signatures'
                  AND column_name = 'autenti_process_id'
            ) THEN
                ALTER TABLE document_signatures
                    RENAME COLUMN autenti_process_id TO provider_ref;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_signatures'
                  AND column_name = 'autenti_signature_type'
            ) THEN
                ALTER TABLE document_signatures
                    RENAME COLUMN autenti_signature_type TO signature_type;
            END IF;
        END $$;
        """
    )

    # ── document_signatures: provider-agnostic columns ──────────────────────
    op.execute(
        "ALTER TABLE document_signatures "
        "ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'autenti'"
    )
    op.execute(
        "ALTER TABLE document_signatures "
        "ADD COLUMN IF NOT EXISTS signing_session_id VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE document_signatures "
        "ADD COLUMN IF NOT EXISTS identity_provider VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE document_signatures "
        "ADD COLUMN IF NOT EXISTS signature_level VARCHAR(16)"
    )
    op.execute(
        "ALTER TABLE document_signatures "
        "ADD COLUMN IF NOT EXISTS validation_report JSONB"
    )

    # ── signature_links: single-use tokeny dla strony podpisu ───────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS signature_links (
            token          TEXT PRIMARY KEY,
            signature_id   INTEGER NOT NULL
                               REFERENCES document_signatures(id) ON DELETE CASCADE,
            party          VARCHAR(16) NOT NULL,
            purpose        VARCHAR(32) NOT NULL,
            created_by     INTEGER NOT NULL
                               REFERENCES users(id) ON DELETE RESTRICT,
            expires_at     TIMESTAMPTZ NOT NULL,
            revoked        BOOLEAN NOT NULL DEFAULT FALSE,
            used_at        TIMESTAMPTZ,
            use_count      INTEGER NOT NULL DEFAULT 0,
            last_used_at   TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_signature_link_signature "
        "ON signature_links (signature_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS signature_links")
    op.execute(
        "ALTER TABLE document_signatures DROP COLUMN IF EXISTS validation_report"
    )
    op.execute(
        "ALTER TABLE document_signatures DROP COLUMN IF EXISTS signature_level"
    )
    op.execute(
        "ALTER TABLE document_signatures DROP COLUMN IF EXISTS identity_provider"
    )
    op.execute(
        "ALTER TABLE document_signatures DROP COLUMN IF EXISTS signing_session_id"
    )
    op.execute("ALTER TABLE document_signatures DROP COLUMN IF EXISTS provider")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_signatures'
                  AND column_name = 'signature_type'
            ) THEN
                ALTER TABLE document_signatures
                    RENAME COLUMN signature_type TO autenti_signature_type;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_signatures'
                  AND column_name = 'provider_ref'
            ) THEN
                ALTER TABLE document_signatures
                    RENAME COLUMN provider_ref TO autenti_process_id;
            END IF;
        END $$;
        """
    )
