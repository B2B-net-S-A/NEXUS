"""Classify candidate documents and enforce one active primary CV.

Revision ID: 0195_candidate_document_kind
Revises: 0194_match_score_invalidations
"""

from alembic import op

revision = "0195_candidate_document_kind"
down_revision = "0194_match_score_invalidations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'candidatedocumentkind'
            ) THEN
                CREATE TYPE candidatedocumentkind AS ENUM (
                    'cv', 'cover_letter', 'certificate', 'other'
                );
            END IF;
        END $$
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_documents
        ADD COLUMN IF NOT EXISTS document_kind candidatedocumentkind
        NOT NULL DEFAULT 'other'
        """
    )
    op.execute(
        """
        UPDATE candidate_documents AS document
        SET document_kind = 'cv'
        FROM candidates AS candidate
        WHERE document.candidate_id = candidate.id
          AND document.source_deleted_at IS NULL
          AND (
              document.is_primary IS TRUE
              OR document.external_source = 'apply_submission'
              OR (
                  candidate.cv_filename IS NOT NULL
                  AND lower(document.filename) = lower(candidate.cv_filename)
              )
              OR document.filename ~* '(^|[^a-z])(cv|resume|curriculum)([^a-z]|$)'
          )
        """
    )
    op.execute(
        """
        INSERT INTO candidate_documents (
            candidate_id,
            filename,
            file_content,
            storage_key,
            size_bytes,
            document_kind,
            is_primary,
            uploaded_at,
            external_source,
            created_at,
            updated_at
        )
        SELECT
            candidate.id,
            candidate.cv_filename,
            CASE
                WHEN candidate.cv_storage_key IS NULL
                THEN candidate.cv_file_content
                ELSE NULL
            END,
            candidate.cv_storage_key,
            CASE
                WHEN candidate.cv_storage_key IS NULL
                THEN octet_length(candidate.cv_file_content)
                ELSE NULL
            END,
            'cv',
            TRUE,
            COALESCE(candidate.cv_parsed_at, candidate.updated_at),
            'legacy_backfill',
            NOW(),
            NOW()
        FROM candidates AS candidate
        WHERE candidate.cv_filename IS NOT NULL
          AND btrim(candidate.cv_filename) <> ''
          AND (
              candidate.cv_storage_key IS NOT NULL
              OR candidate.cv_file_content IS NOT NULL
          )
          AND NOT EXISTS (
              SELECT 1
              FROM candidate_documents AS document
              WHERE document.candidate_id = candidate.id
                AND document.source_deleted_at IS NULL
                AND (
                    document.is_primary IS TRUE
                    OR lower(document.filename) = lower(candidate.cv_filename)
                )
          )
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY candidate_id
                       ORDER BY uploaded_at DESC NULLS LAST, created_at DESC, id DESC
                   ) AS position
            FROM candidate_documents
            WHERE document_kind = 'cv'
              AND is_primary IS TRUE
              AND source_deleted_at IS NULL
        )
        UPDATE candidate_documents AS document
        SET is_primary = FALSE
        FROM ranked
        WHERE document.id = ranked.id
          AND ranked.position > 1
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_candidate_documents_document_kind
        ON candidate_documents (document_kind)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_candidate_documents_active_primary_cv
        ON candidate_documents (candidate_id)
        WHERE is_primary IS TRUE
          AND source_deleted_at IS NULL
          AND document_kind = 'cv'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_candidate_documents_active_primary_cv")
    op.execute("DROP INDEX IF EXISTS ix_candidate_documents_document_kind")
    op.execute("ALTER TABLE candidate_documents DROP COLUMN IF EXISTS document_kind")
    op.execute("DROP TYPE IF EXISTS candidatedocumentkind")
